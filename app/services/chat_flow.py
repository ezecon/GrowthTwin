"""Conversation logic for WhatsApp and SMS. Channel-agnostic: returns the reply texts, the API layer sends them.

  WhatsApp : advisor Q&A (Section 1) + leaf photo -> disease hint (Section 2) + alerts
  SMS      : advisor Q&A (Section 1) ONLY. Short texts, no photos, no alerts.

A farmer can use the advisor without any account (owner = "ch:<phone>"). Photos need a plot, so the phone must be
linked to an account first: logged-in user asks POST /messaging/link-code, then sends "LINK 123456" on WhatsApp
(WhatsApp itself proves the sender's number, so nobody can claim someone else's number).
"""
import asyncio
import logging
import re
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

from ..core.channel_store import get_channel_store
from ..core.config import get_settings
from ..core.store import get_store
from ..core.twin_store import get_twin_store
from . import channels, disease_models, notify, pipeline
from . import twin_engine as te

log = logging.getLogger("growthtwin.chat")

BN2EN = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
HELLO = {"hi", "hello", "hey", "helo", "সাহায্য", "মেনু", "menu", "help", "হ্যালো", "হাই", "আসসালামু আলাইকুম", "সালাম"}
RESET = {"reset", "নতুন", "শুরু", "cancel", "বাতিল"}
STOP = {"stop", "বন্ধ"}
START = {"start", "চালু"}
LINK_RE = re.compile(r"^(?:link|লিংক)\s*(\d{6})$", re.I)
MAX_PROMPT = 1500
_hits: dict[str, deque] = defaultdict(deque)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm(text: str) -> str:
    return " ".join((text or "").translate(BN2EN).strip().lower().split())


def rate_ok(phone: str) -> bool:
    """Max N messages per hour per phone (every advisor call may cost an LLM request)."""
    q, now, cap = _hits[phone], time.time(), get_settings().channel_msgs_per_hour
    while q and q[0] < now - 3600:
        q.popleft()
    if len(q) >= cap:
        return False
    q.append(now)
    return True


def new_rec(phone: str) -> dict:
    return {"phone": phone, "user_id": None, "session_id": None, "queue": [], "answers": {},
            "last_inbound_at": None, "seen": [], "alerts": True}


def help_text(channel: str, linked: bool) -> str:
    if channel == "sms":
        return "GrowthTwin: আপনার জমির পরিমাণ, আগের ফসল ও কোন ফসল চাষ করতে চান তা লিখে পাঠান। নতুন করে শুরু: শুরু"
    lines = ["GrowthTwin-এ স্বাগতম।", "",
             "১) চাষের পরামর্শ: আপনার জমি ও ফসলের কথা লিখুন। যেমন: \"আমার ৩০ শতাংশ জমি, গত বছর ধান করেছি, এবার ভুট্টা চাষ করতে চাই\"",
             "২) রোগ দেখা: গাছের পাতার ছবি পাঠান" + ("" if linked else " (এজন্য আগে অ্যাপের সাথে নম্বর সংযুক্ত করতে হবে: LINK কোড)"),
             "৩) নতুন করে শুরু: *শুরু*", "৪) সতর্কবার্তা বন্ধ: *বন্ধ*, আবার চালু: *চালু*"]
    return "\n".join(lines)


def parse_choice(text: str, q: dict):
    """Map a reply to the option value: number (১ or 1) or the option's name. None when unclear."""
    t = _norm(text)
    opts = q["options"]
    if t.isdigit() and 1 <= int(t) <= len(opts):
        return opts[int(t) - 1]["value"]
    hits = [o for o in opts if t and len(t) >= 2 and (t in _norm(o["label_bn"]) or _norm(o["label_bn"]) in t)]
    return hits[0]["value"] if len(hits) == 1 else None


def _ask(q: dict, channel: str, step: int, total: int) -> str:
    return channels.sms_question(q) if channel == "sms" else channels.question_text(q, step, total)


async def _advise(rec: dict, channel: str, prompt: str | None, answers: dict | None) -> list[str]:
    store = get_store()
    owner = rec.get("user_id") or f"ch:{rec['phone']}"
    sid = rec.get("session_id")
    state = await store.get_session(sid) if sid else None
    if sid and state is None and not prompt:           # session expired/lost: start over from the prompt
        rec.update(session_id=None, queue=[], answers={})
        return ["আগের তথ্য পাওয়া যায়নি। আপনার জমি ও ফসলের কথা আবার লিখুন।"]
    sid, state, rep, questions = await pipeline.analyze(sid, prompt, answers, None, owner, state)
    await store.save_session(sid, state)
    rec["session_id"] = sid
    if rep:
        rec.update(queue=[], answers={})
        return [channels.sms_advice(rep) if channel == "sms" else channels.wa_advice(rep)]
    rec.update(queue=questions or [], answers={})
    return [_ask(rec["queue"][0], channel, 1, len(rec["queue"]))]


async def _answer(rec: dict, channel: str, text: str) -> list[str]:
    q = rec["queue"][0]
    value = parse_choice(text, q)
    if value is None:
        return ["বুঝতে পারিনি। নম্বর লিখে উত্তর দিন, অথবা নতুন করে শুরু করতে *শুরু* লিখুন।", _ask(q, channel, 1, len(rec["queue"]))]
    rec["answers"][q["slot"]] = value
    rec["queue"] = rec["queue"][1:]
    if rec["queue"]:
        return [_ask(rec["queue"][0], channel, 1, len(rec["queue"]))]
    return await _advise(rec, channel, None, rec["answers"])


async def handle_text(rec: dict, channel: str, text: str) -> list[str]:
    t = _norm(text)
    store = get_channel_store()
    m = LINK_RE.match(t)
    if m:
        if channel != "whatsapp":
            return ["নম্বর সংযুক্ত করতে WhatsApp ব্যবহার করুন।"]
        uid = await store.consume_code(m.group(1))
        if not uid:
            return ["কোডটি সঠিক নয় বা মেয়াদ শেষ। অ্যাপ থেকে নতুন কোড নিন।"]
        old = await store.get_link_by_user(uid)
        if old and old["phone"] != rec["phone"]:
            await store.delete_link(old["phone"])
        rec.update(user_id=uid, session_id=None, queue=[], answers={})
        return ["নম্বর সংযুক্ত হয়েছে। এখন থেকে সতর্কবার্তা এখানে পাবেন এবং পাতার ছবি পাঠিয়ে রোগ দেখাতে পারবেন।"]
    if t in STOP or t in START:
        rec["alerts"] = t in START
        return ["সতর্কবার্তা চালু হয়েছে।" if rec["alerts"] else "সতর্কবার্তা বন্ধ হয়েছে। আবার চালু করতে *চালু* লিখুন।"]
    if t in RESET:
        rec.update(session_id=None, queue=[], answers={})
        return ["ঠিক আছে, নতুন করে শুরু করি। আপনার জমি ও ফসলের কথা লিখুন।"]
    if t in HELLO:
        return [help_text(channel, bool(rec.get("user_id")))]
    if rec.get("queue") and (t.isdigit() or len(t) <= 25):      # a short reply while a question is open = the answer
        return await _answer(rec, channel, text)
    if len(t) < 3:
        return [help_text(channel, bool(rec.get("user_id")))]
    return await _advise(rec, channel, (text or "").strip()[:MAX_PROMPT], None)   # a fresh prompt always restarts


async def handle_image(rec: dict, channel: str, image: bytes | None, caption: str) -> list[str]:
    if channel != "whatsapp":
        return ["ছবি শুধু WhatsApp-এ দেখা যায়।"]
    if not rec.get("user_id"):
        return ["ছবি দিয়ে রোগ দেখতে হলে আগে অ্যাপে লগইন করে \"WhatsApp সংযুক্ত করুন\" থেকে কোড নিন, তারপর এখানে লিখুন: LINK কোড"]
    if image is None:
        return ["ছবিটি নামানো যায়নি। আবার পাঠান।"]
    if not image or len(image) > disease_models.MAX_IMAGE_BYTES or not disease_models.looks_like_image(image):
        return ["ছবি JPEG/PNG/WebP এবং ২ এমবির ছোট হতে হবে। আবার পাঠান।"]
    plots = [p for p in await get_twin_store().list_plots(rec["user_id"]) if p["status"] in te.ACTIVE]
    if not plots:
        return ["আপনার কোনো চলমান প্লট নেই। অ্যাপে প্লট খুলে আবার ছবি পাঠান।"]
    cap = _norm(caption)
    s = next((p for p in plots if cap and _norm(p["name"]) in cap), plots[0])
    te._migrate(s)
    pred = await asyncio.to_thread(disease_models.predict, s["crop_id"], image)
    evs = te.record_photo(s, pred)
    from ..api.twin import _persist              # lazy: api.twin imports this package's notify/channels
    await _persist(s, evs)
    out = [f"প্লট: {s['name']}"] + [e["payload"]["text_bn"] for e in evs if e["kind"] == "photo"]
    if len(plots) > 1:
        out.append(f"আপনার {len(plots)}টি প্লট আছে। অন্য প্লটের জন্য ছবির ক্যাপশনে প্লটের নাম লিখুন।")
    out.append("ছবি সংরক্ষণ করা হয় না। এটি শুধু পরামর্শ; নিশ্চিত হতে কৃষি অফিসের সাথে কথা বলুন।")
    return ["\n".join(out)]


async def process_inbound(msg: dict) -> list[str]:
    """msg = {phone, channel: whatsapp|sms, type: text|image, text, caption, media_id, id}. Never raises."""
    store = get_channel_store()
    channel, phone = msg["channel"], msg["phone"]
    try:
        rec = await store.get_link(phone) or new_rec(phone)
        if msg.get("id"):
            if msg["id"] in rec["seen"]:
                return []                          # Meta retries webhooks: answer each message once
            rec["seen"] = (rec["seen"] + [msg["id"]])[-20:]
        if channel == "whatsapp":
            rec["last_inbound_at"] = _now()
        if not rate_ok(phone):
            replies = ["অনেক বার্তা পাঠানো হয়েছে। কিছুক্ষণ পর আবার চেষ্টা করুন।"]
        elif msg["type"] == "image":
            img = await channels.wa_download_media(msg["media_id"]) if msg.get("media_id") else None
            replies = await handle_image(rec, channel, img, msg.get("caption", ""))
        else:
            replies = await handle_text(rec, channel, msg.get("text", ""))
        await store.save_link(rec)
        return replies
    except Exception:                              # noqa: BLE001
        log.exception("chat flow failed")
        return ["দুঃখিত, এখন উত্তর দেওয়া যাচ্ছে না। একটু পরে আবার চেষ্টা করুন।"]


ALERT_LEVELS = ("critical", "action")
MAX_ALERTS_PER_CALL = 3


async def push_alerts(s: dict, events: list) -> list[dict]:
    """Section 2 alerts -> the plot owner's linked WhatsApp (same levels/limit as the existing SMS). Never raises.
    Returns event rows (kind 'whatsapp') to be saved next to the alerts."""
    try:
        rec = await get_channel_store().get_link_by_user(s["user_id"])
        if not rec or not rec.get("alerts"):
            return []
        urgent = [e for e in events if e["kind"] == "alert" and e["payload"]["level"] in ALERT_LEVELS][:MAX_ALERTS_PER_CALL]
        out = []
        for e in urgent:
            p = e["payload"]
            text = f"GrowthTwin {s['name']}: {p['title_bn']}. {p['text_bn']}"
            st = await channels.wa_send_alert(rec["phone"], text, rec.get("last_inbound_at"))
            out.append({"day": e["day"], "kind": "whatsapp",
                        "payload": {"to": notify.mask(rec["phone"]), "text_bn": text[:200], "status": st}})
        return out
    except Exception:                                  # noqa: BLE001
        log.exception("whatsapp alert push failed")
        return []
