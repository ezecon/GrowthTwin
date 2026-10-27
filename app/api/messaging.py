"""WhatsApp + SMS endpoints.

  POST   /messaging/link-code          (logged in) one-time 6-digit code; the farmer sends "LINK <code>" on WhatsApp
  GET    /messaging/status             (logged in) is a phone linked, are alerts on
  DELETE /messaging/link               (logged in) unlink the phone
  GET    /messaging/whatsapp/webhook   Meta webhook verification
  POST   /messaging/whatsapp/webhook   incoming WhatsApp messages (text + photos); signature-checked
  POST   /messaging/sms/inbound        incoming SMS from ANY gateway (header X-Channel-Secret); advisor only
"""
import hmac
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from ..core.auth import User, current_user
from ..core.channel_store import CODE_TTL_S, get_channel_store
from ..core.config import get_settings
from ..services import channels, chat_flow, notify
from .auth import _limit

log = logging.getLogger("growthtwin.messaging")
router = APIRouter(prefix="/messaging", tags=["messaging"])


# ------------------------------------------------------------------ account side (logged-in farmer)
@router.post("/link-code")
async def link_code(request: Request, user: User = Depends(current_user)):
    _limit(request, "linkcode", 5)
    code = await get_channel_store().create_code(user.id)
    num = get_settings().whatsapp_number
    return {"code": code, "expires_in_s": CODE_TTL_S, "whatsapp_number": num,
            "instruction_bn": f"WhatsApp-এ{(' ' + num + ' নম্বরে') if num else ''} লিখে পাঠান: LINK {code} (১০ মিনিটের মধ্যে)"}


@router.get("/status")
async def status(user: User = Depends(current_user)):
    rec = await get_channel_store().get_link_by_user(user.id)
    return {"linked": bool(rec), "phone_masked": notify.mask(rec["phone"]) if rec else "",
            "alerts": bool(rec and rec.get("alerts"))}


@router.delete("/link")
async def unlink(user: User = Depends(current_user)):
    store = get_channel_store()
    rec = await store.get_link_by_user(user.id)
    if rec:
        await store.delete_link(rec["phone"])
    return {"linked": False}


# ------------------------------------------------------------------ WhatsApp
@router.get("/whatsapp/webhook")
async def wa_verify(request: Request):
    q, s = request.query_params, get_settings()
    ok = (q.get("hub.mode") == "subscribe" and s.whatsapp_verify_token
          and hmac.compare_digest(q.get("hub.verify_token", ""), s.whatsapp_verify_token))
    if not ok:
        raise HTTPException(403, "verification failed")
    return PlainTextResponse(q.get("hub.challenge", ""))


def parse_whatsapp(payload: dict) -> list[dict]:
    """Meta payload -> [{phone, channel, type, text, caption, media_id, id}]. Status receipts and odd types handled."""
    out = []
    for entry in payload.get("entry", []):
        for ch in entry.get("changes", []):
            for m in (ch.get("value") or {}).get("messages", []) or []:
                phone = channels.normalize_phone(m.get("from", ""))
                if not phone:
                    continue                              # not a Bangladeshi mobile: ignore
                base = {"phone": phone, "channel": "whatsapp", "id": m.get("id"), "text": "", "caption": "", "media_id": None}
                t = m.get("type")
                if t == "text":
                    out.append({**base, "type": "text", "text": (m.get("text") or {}).get("body", "")})
                elif t == "image":
                    img = m.get("image") or {}
                    out.append({**base, "type": "image", "media_id": img.get("id"), "caption": img.get("caption", "")})
                else:                                     # audio, location, sticker...
                    out.append({**base, "type": "other"})
    return out


async def _run_whatsapp(msgs: list[dict]) -> None:
    for m in msgs:
        if m["type"] == "other":
            replies = ["দুঃখিত, এখন শুধু লেখা বা ছবি বুঝতে পারি। আপনার প্রশ্ন লিখে পাঠান।"]
        else:
            replies = await chat_flow.process_inbound(m)
        for r in replies:
            await channels.wa_send_text(m["phone"], r)


@router.post("/whatsapp/webhook")
async def wa_incoming(request: Request, background: BackgroundTasks):
    body = await request.body()
    if not channels.verify_signature(body, request.headers.get("x-hub-signature-256")):
        raise HTTPException(403, "bad signature")
    try:
        payload = await request.json()
    except Exception:                                     # noqa: BLE001
        raise HTTPException(400, "bad json")
    msgs = parse_whatsapp(payload)
    if msgs:
        background.add_task(_run_whatsapp, msgs)          # answer 200 fast; Meta retries slow webhooks
    return {"status": "ok"}


# ------------------------------------------------------------------ SMS (any gateway)
class SmsIn(BaseModel):
    sender: str = Field(..., alias="from", max_length=20)
    text: str = Field("", max_length=1000)
    id: str | None = Field(None, max_length=80)

    model_config = {"populate_by_name": True}


async def _run_sms(phone: str, replies: list[str]) -> None:
    for r in replies:
        await notify.send_sms(phone, r)


@router.post("/sms/inbound")
async def sms_incoming(body: SmsIn, request: Request, background: BackgroundTasks):
    """Point your gateway's 'incoming SMS' callback here. SMS carries ONLY the advisor (no photos, no alerts)."""
    s = get_settings()
    if not s.channel_secret or not hmac.compare_digest(request.headers.get("x-channel-secret", ""), s.channel_secret):
        raise HTTPException(403, "bad secret")
    phone = channels.normalize_phone(body.sender)
    if not phone:
        raise HTTPException(400, "not a Bangladeshi mobile number")
    replies = await chat_flow.process_inbound({"phone": phone, "channel": "sms", "type": "text", "text": body.text, "id": body.id})
    background.add_task(_run_sms, phone, replies)
    return {"replies": replies}
