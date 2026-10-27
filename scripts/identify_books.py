"""books/ ফোল্ডারের প্রতিটা ফাইল চেনার সাহায্যকারী (কিছুই বদলায় না, শুধু দেখায়)।

চালান (backend ফোল্ডার থেকে):
    python -m scripts.identify_books ./books

ফলাফল পর্দায় দেখায় এবং books_preview.txt ফাইলেও (UTF-8) সেভ করে।
প্রতিটা ফাইলের জন্য দেখায়: ধরন, সাইজ, শিরোনাম (PDF title / HTML <title>), শুরুর লেখা,
আর একই ফাইল দুবার থাকলে "DUPLICATE" লিখে দেয়।
"""
import hashlib, re, sys
from pathlib import Path

from scripts.ingest_rag import kind, read_pages, pdf_title

SKIP = ("readme.txt", "readme.md", "sources.csv", "books_preview.txt")


def file_hash(p: Path) -> str:
    h = hashlib.sha1()
    with p.open("rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def html_title(p: Path):
    head = p.open("rb").read(3_000_000).decode("utf-8", "ignore")
    m = re.search(r"<title[^>]*>(.*?)</title>", head, re.I | re.S)
    return " ".join(m.group(1).split()) if m else None


def html_start(p: Path, n=350):
    # বড় ফাইল পুরো না পড়ে শুরুর অংশ থেকে লেখা বের করি
    import io
    from scripts.ingest_rag import _Text
    head = p.open("rb").read(2_000_000).decode("utf-8", "ignore")
    t = _Text()
    try:
        t.feed(head)
    except Exception:
        pass
    return " ".join("".join(t.out).split())[:n]


def pdf_start(p: Path, n=350):
    for page, txt in read_pages(p, ".pdf"):
        txt = " ".join(txt.split())
        if len(txt) > 60:
            return f"(পৃষ্ঠা {page}) " + txt[:n]
        if page and page >= 15:
            break
    return "(প্রথম ১৫ পৃষ্ঠায় পড়ার মতো লেখা নেই - স্ক্যান করা হতে পারে)"


def main():
    folder = Path(sys.argv[1] if len(sys.argv) > 1 else "books")
    files = [f for f in sorted(folder.rglob("*")) if f.is_file() and f.name.lower() not in SKIP and kind(f)]
    seen, lines = {}, []
    for f in files:
        k = kind(f)
        size = f.stat().st_size / 1_000_000
        hx = file_hash(f)
        dup = seen.get(hx)
        seen.setdefault(hx, f.name)
        title = pdf_title(f) if k == ".pdf" else html_title(f) if k == ".html" else None
        try:
            start = pdf_start(f) if k == ".pdf" else html_start(f) if k == ".html" else f.read_text(encoding="utf-8", errors="ignore")[:350]
        except Exception as e:
            start = f"(পড়া যায়নি: {e})"
        lines += [
            "=" * 78,
            f"ফাইল   : {f.name}   [{k}, {size:.1f} MB]",
            f"শিরোনাম: {title or '-'}",
            f"শুরু   : {start}",
        ]
        if dup:
            lines.append(f"!! DUPLICATE: {dup} এর হুবহু কপি - একটা সরিয়ে দিন")
    out = "\n".join(lines)
    (folder / "books_preview.txt").write_text(out, encoding="utf-8")
    try:
        print(out)
    except UnicodeEncodeError:
        print(out.encode("ascii", "replace").decode())
    print(f"\n{len(files)} টা ফাইল। একই লেখা {folder / 'books_preview.txt'} ফাইলেও সেভ হয়েছে (Notepad এ খুলুন)।")


if __name__ == "__main__":
    main()