"""Chunk + embed books into Supabase (table rag_chunks).

  python -m scripts.ingest_rag ./books --dry-run          # NO Supabase/embeddings: just shows what would be read
  python -m scripts.ingest_rag ./books                    # ingest everything (skips sources already ingested)
  python -m scripts.ingest_rag ./books --crop rice        # tag all books with a crop (default: general knowledge)
  python -m scripts.ingest_rag ./books --replace          # delete + re-ingest sources that already exist

Reads .pdf .txt .md .html .htm (files without extension are sniffed). Scanned PDFs have no text layer: run OCR first.
Citation names: books/sources.csv (columns: file,source,crop) > --source (single file only) > PDF title > file name.
Hash-named files (e.g. 0bd78f01...) would give useless citations, so --dry-run writes a sources.csv template to fill in.
"""
import argparse, csv, hashlib, re, sys
from html.parser import HTMLParser
from pathlib import Path

CHUNK, OVERLAP, BATCH, MIN_CHARS = 900, 150, 64, 80
EXT = {".pdf", ".txt", ".md", ".html", ".htm"}


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(); self.out, self.skip = [], 0
    def handle_starttag(self, tag, a):
        if tag in ("script", "style", "noscript", "svg", "head"): self.skip += 1
        elif tag in ("p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4"): self.out.append("\n")
    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg", "head") and self.skip: self.skip -= 1
    def handle_data(self, d):
        if not self.skip: self.out.append(d)


def kind(path: Path):
    s = path.suffix.lower()
    if s in EXT: return {".htm": ".html"}.get(s, s)
    try:
        head = path.open("rb").read(2048).lstrip()
    except OSError:
        return None
    if head.startswith(b"%PDF"): return ".pdf"
    if head[:1] == b"<": return ".html"
    return ".txt" if path.suffix == "" else None


def read_pages(path: Path, k: str):
    """yield (page_number|None, text); PDFs are streamed page by page (some books are 100MB+)."""
    if k == ".pdf":
        from pypdf import PdfReader
        for n, p in enumerate(PdfReader(str(path)).pages, 1):
            try: yield n, p.extract_text() or ""
            except Exception: yield n, ""
    elif k == ".html":
        t = _Text(); t.feed(path.read_text(encoding="utf-8", errors="ignore")); yield None, "".join(t.out)
    else:
        yield None, path.read_text(encoding="utf-8", errors="ignore")


def pdf_title(path: Path):
    try:
        from pypdf import PdfReader
        t = (PdfReader(str(path)).metadata or {}).get("/Title")
        return t.strip() if t and len(t.strip()) > 3 else None
    except Exception:
        return None


def chunks(text: str):
    text = " ".join(text.split()); i = 0
    while i < len(text):
        end = min(i + CHUNK, len(text))
        if end < len(text):  # cut at a space, not mid-word
            sp = text.rfind(" ", i + CHUNK - 120, end)
            end = sp if sp > i else end
        yield text[i:end]
        if end >= len(text): break
        i = max(end - OVERLAP, i + 1)


def load_map(folder: Path):
    m, f = {}, folder / "sources.csv"
    if f.exists():
        for r in csv.DictReader(f.open(encoding="utf-8-sig")):
            key = (r.get("file") or "").strip()
            if key: m[key] = ((r.get("source") or "").strip(), (r.get("crop") or "").strip() or None)
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder"); ap.add_argument("--source"); ap.add_argument("--crop")
    ap.add_argument("--dry-run", action="store_true"); ap.add_argument("--replace", action="store_true")
    a = ap.parse_args()
    folder = Path(a.folder)
    files = [f for f in sorted(folder.rglob("*")) if f.is_file() and f.name.lower() not in ("readme.txt", "readme.md", "sources.csv") and kind(f)]
    if not files: raise SystemExit(f"No readable books in {folder} (.pdf .txt .md .html .htm)")
    if a.source and len(files) > 1: raise SystemExit("--source names ONE book; for many books use books/sources.csv (run --dry-run to create it)")
    mp = load_map(folder)
    db = model = None
    if not a.dry_run:
        from app.core.db import get_supabase
        db = get_supabase()
        if db is None: raise SystemExit("Set SUPABASE_URL and SUPABASE_SERVICE_KEY first (or use --dry-run)")
        from app.services.rag import _embedder
        model = _embedder()
    template, total_rows, problems = [], 0, []
    for f in files:
        k = kind(f); src, crop = mp.get(f.name) or mp.get(f.stem) or ("", None)
        src = a.source or src or (pdf_title(f) if k == ".pdf" else None) or f.stem
        crop = crop or a.crop
        template.append((f.name, src if src != f.stem else "", crop or ""))
        if db is not None:
            have = db.table("rag_chunks").select("id", count="exact").eq("source", src).limit(1).execute().count or 0
            if have and not a.replace: print(f"= skip (already ingested, {have} chunks): {src}"); continue
            if have: db.table("rag_chunks").delete().eq("source", src).execute()
        rows, seen, pages_n, chars, n_rows = [], set(), 0, 0, 0
        def flush():
            nonlocal rows, n_rows
            if not rows or db is None: n_rows += len(rows); rows = []; return
            vecs = model.encode(["passage: " + r["content"] for r in rows], normalize_embeddings=True)
            for r, v in zip(rows, vecs): r["embedding"] = v.tolist()
            db.table("rag_chunks").insert(rows).execute(); n_rows += len(rows); rows = []
        try:
            for page, txt in read_pages(f, k):
                pages_n += 1; chars += len(txt)
                for c in chunks(txt):
                    h = hashlib.md5(c.encode()).hexdigest()
                    if len(c) > MIN_CHARS and h not in seen:
                        seen.add(h); rows.append({"source": src, "page": page, "crop_id": crop, "content": c})
                        if len(rows) >= BATCH: flush()
            flush()
        except Exception as e:
            problems.append((f.name, f"read failed: {e}")); print(f"! {f.name}: {e}"); continue
        scanned = k == ".pdf" and pages_n and chars / pages_n < 40
        if scanned or n_rows == 0: problems.append((f.name, "no text found - scanned PDF? run OCR first"))
        total_rows += n_rows
        print(f"{'!' if scanned or not n_rows else '+'} {f.name[:40]:40} -> \"{src[:50]}\"  pages={pages_n or '-'} chars={chars:,} chunks={n_rows:,}{'  (SCANNED?)' if scanned else ''}")
    if a.dry_run and not (folder / "sources.csv").exists():
        with (folder / "sources.csv").open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh); w.writerow(["file", "source", "crop"]); w.writerows(template)
        print(f"\nWrote {folder / 'sources.csv'} - fill the 'source' column (shown in citations) and optional 'crop' (e.g. rice), then run without --dry-run.")
    print(f"\n{'Would create' if a.dry_run else 'Inserted'} {total_rows:,} chunks from {len(files)} files.")
    if problems:
        print("Needs attention:"); [print("  -", n, "->", why) for n, why in problems]


if __name__ == "__main__":
    main()
