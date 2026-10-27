"""WhatsApp (Meta Cloud API) client + short Bangla message builders shared by WhatsApp and SMS.

Nothing here raises: sending returns 'sent' | 'failed' | 'simulated' | 'needs_template'.
With no WHATSAPP_* settings every send is 'simulated' (logged), so the whole flow works locally.
"""
import hashlib
import hmac
import logging
import re
from datetime import datetime, timezone

import httpx

from ..core.config import get_settings
from . import notify
from .lexicon import bn_num

log = logging.getLogger("growthtwin.channels")

HASH_NAME = re.compile(r"^[0-9a-f]{32}$")
WA_MAX = 3500                       # WhatsApp limit is 4096 chars; stay below
DISCLAIMER = "এটি পরামর্শ মাত্র; বীজ, সার ও কীটনাশকের মাত্রা স্থানীয় কৃষি কর্মকর্তার সাথে যাচাই করুন।"


# ------------------------------------------------------------------ phone numbers
def normalize_phone(raw: str) -> str | None:
    """'8801712345678' / '+8801712345678' / '01712345678' -> '01712345678'; None if not a BD mobile."""
    d = re.sub(r"\D", "", raw or "")
    if d.startswith("880") and len(d) == 13:
        d = "0" + d[3:]
    return d if notify.valid_phone(d) and len(d) == 11 else None


def to_wa(phone: str) -> str:
    return "88" + phone


# ------------------------------------------------------------------ WhatsApp Cloud API
def wa_configured() -> bool:
    s = get_settings()
    return bool(s.whatsapp_access_token and s.whatsapp_phone_number_id)


def verify_signature(body: bytes, header: str | None) -> bool:
    """X-Hub-Signature-256 = 'sha256=' + HMAC_SHA256(app_secret, raw body). No secret -> only allowed outside prod."""
    s = get_settings()
    if not s.whatsapp_app_secret:
        return s.app_env != "prod"
    if not header or not header.startswith("sha256="):
        return False
    want = hmac.new(s.whatsapp_app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(want, header[7:])


def _url(path: str) -> str:
    s = get_settings()
    return f"https://graph.facebook.com/{s.whatsapp_graph_version}/{path}"


def _auth() -> dict:
    return {"Authorization": f"Bearer {get_settings().whatsapp_access_token}"}


def split_text(text: str, limit: int = WA_MAX) -> list[str]:
    out, text = [], text.strip()
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        cut = cut if cut > limit // 2 else limit
        out.append(text[:cut].strip())
        text = text[cut:].strip()
    return out + ([text] if text else [])


async def _post_message(payload: dict) -> str:
    s = get_settings()
    if not wa_configured():
        log.info("WhatsApp (simulated) -> %s", str(payload)[:200])
        return "simulated"
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(_url(f"{s.whatsapp_phone_number_id}/messages"),
                             json={"messaging_product": "whatsapp", **payload}, headers=_auth())
        if not r.is_success:
            log.warning("WhatsApp send failed %s: %s", r.status_code, r.text[:300])
        return "sent" if r.is_success else "failed"
    except Exception as e:                  # noqa: BLE001
        log.warning("WhatsApp send error: %s", e)
        return "failed"


async def wa_send_text(phone: str, text: str) -> str:
    status = "sent"
    for part in split_text(text):
        st = await _post_message({"to": to_wa(phone), "type": "text", "text": {"body": part}})
        status = st if st != "sent" else status
        if st == "failed":
            return "failed"
    return status


def within_24h(last_inbound_at: str | None) -> bool:
    """Free-form messages are only allowed for 24h after the farmer last wrote to us."""
    try:
        t = datetime.fromisoformat(last_inbound_at)
    except (TypeError, ValueError):
        return False
    return (datetime.now(timezone.utc) - t).total_seconds() < 24 * 3600 - 300


async def wa_send_alert(phone: str, text: str, last_inbound_at: str | None) -> str:
    """Business-initiated message: plain text inside the 24h window, otherwise an approved template (if configured)."""
    s = get_settings()
    if within_24h(last_inbound_at) or not wa_configured():
        return await wa_send_text(phone, text)
    if not s.whatsapp_alert_template:
        return "needs_template"
    return await _post_message({"to": to_wa(phone), "type": "template", "template": {
        "name": s.whatsapp_alert_template, "language": {"code": s.whatsapp_template_lang},
        "components": [{"type": "body", "parameters": [{"type": "text", "text": text[:900].replace("\n", " ")}]}]}})


async def wa_download_media(media_id: str, max_bytes: int = 2_000_000) -> bytes | None:
    """Two steps: media id -> temporary URL -> bytes. None when unavailable or too large."""
    if not wa_configured():
        return None
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            meta = await c.get(_url(media_id), headers=_auth())
            meta.raise_for_status()
            info = meta.json()
            if int(info.get("file_size") or 0) > max_bytes:
                return b""                  # empty = "too large" marker
            r = await c.get(info["url"], headers=_auth())
            r.raise_for_status()
            return r.content if len(r.content) <= max_bytes else b""
    except Exception as e:                  # noqa: BLE001
        log.warning("WhatsApp media download failed: %s", e)
        return None


# ------------------------------------------------------------------ text builders
def fit_words(text: str, limit: int) -> str:
    """Cut at a word boundary (never mid-word: Bangla joined letters break easily)."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text.rfind(" ", 0, limit - 1)
    return text[: cut if cut > limit // 2 else limit - 1].rstrip(" ,;:।") + "…"


def _sources(rep: dict) -> list[str]:
    seen, out = set(), []
    for e in rep.get("evidence") or []:
        name = e.get("source", "")
        if name and not HASH_NAME.match(name) and name not in seen:      # skip un-named books (hash file names)
            seen.add(name)
            out.append(name + (f", পৃষ্ঠা {bn_num(e['page'])}" if e.get("page") else ""))
    return out[:2]


def profit_phrase(profit: float) -> str:
    """'গড়ে লাভ ৫০০ টাকা' or 'গড়ে লোকসান ১৪৬ টাকা' (never a confusing 'লাভ -১৪৬')."""
    return f"গড়ে লাভ {bn_num(profit)} টাকা" if profit >= 0 else f"গড়ে লোকসান {bn_num(-profit)} টাকা"


def wa_advice(rep: dict) -> str:
    """Full WhatsApp message for a finished advisor report (Section 1)."""
    lines = [f"*{rep['summary']['headline_bn']}*", ""]
    t = rep.get("target")
    if t:
        sc = t["scenarios"]
        lines += [f"{t['name_bn']} — {t['rating_bn']}",
                  f"{profit_phrase(sc['base']['profit'])} সম্ভব (খরচ {bn_num(sc['cost'])} টাকা)"]
        if sc.get("breakeven_price"):
            lines.append(f"লোকসান এড়াতে কেজিপ্রতি অন্তত {bn_num(sc['breakeven_price'], 1)} টাকা দাম দরকার")
        if t.get("reasons_bn"):
            lines += ["", "বিবেচ্য বিষয়:"] + [f"• {r}" for r in t["reasons_bn"][:3]]
    cmp = rep.get("comparison")
    if cmp and cmp.get("verdict_bn"):
        lines += ["", f"বর্তমান বনাম নতুন ফসল: {cmp['verdict_bn']}"]
    alts = rep.get("alternatives") or []
    if alts:
        lines += ["", "বিকল্প: " + "; ".join(f"{a['name_bn']} ({a['rating_bn']})" for a in alts[:2])]
    src = _sources(rep)
    if src:
        lines += ["", "সূত্র: " + "; ".join(src)]
    lines += ["", DISCLAIMER, "", "নতুন প্রশ্নের জন্য আপনার জমি ও ফসলের কথা লিখুন। মেনু: *সাহায্য*"]
    return "\n".join(lines)


def sms_advice(rep: dict, limit: int | None = None) -> str:
    """Compact SMS: headline + one profit line + top reason. Bangla is Unicode, so every character is expensive."""
    limit = limit or get_settings().sms_max_chars
    parts = [rep["summary"]["headline_bn"].rstrip("।") + "।"]
    t = rep.get("target")
    if t:
        parts.append(profit_phrase(t["scenarios"]["base"]["profit"]) + "।")
        if t.get("reasons_bn"):
            parts.append(t["reasons_bn"][0].rstrip("।") + "।")
    return fit_words(" ".join(parts), limit)


def question_text(q: dict, step: int | None = None, total: int | None = None) -> str:
    head = q["text_bn"] + (f" ({bn_num(step)}/{bn_num(total)})" if step and total and total > 1 else "")
    opts = [f"{bn_num(i)}. {o['label_bn']}" for i, o in enumerate(q["options"], 1)]
    return head + "\n" + "\n".join(opts) + "\n(নম্বর লিখে উত্তর দিন)"


def sms_question(q: dict) -> str:
    """SMS version: options on one line. NOT trimmed - cutting would silently drop options the farmer must choose from."""
    opts = " ".join(f"{bn_num(i)}={o['label_bn']}" for i, o in enumerate(q["options"], 1))
    return f"{q['text_bn']} {opts}"
