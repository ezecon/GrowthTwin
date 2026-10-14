"""SMS fallback for urgent Section 2 alerts. Provider-agnostic: SMS_PROVIDER=none (simulated) or webhook
(POST {"to","text"} to SMS_WEBHOOK_URL, so you can put any Bangladeshi gateway behind a small adapter)."""
import re

import httpx

from ..core.config import get_settings

PHONE_RE = re.compile(r"^(\+?88)?01[3-9]\d{8}$")


def valid_phone(p: str) -> bool:
    return bool(PHONE_RE.match(p or ""))


def mask(phone: str) -> str:
    return (phone[:4] + "****" + phone[-2:]) if phone else ""


async def send_sms(phone: str, text: str) -> str:
    """Returns 'sent' | 'failed' | 'simulated'. Never raises."""
    s = get_settings()
    if s.sms_provider == "webhook" and s.sms_webhook_url:
        try:
            async with httpx.AsyncClient(timeout=8) as c:
                r = await c.post(s.sms_webhook_url, json={"to": phone, "text": text[:300]})
            return "sent" if r.is_success else "failed"
        except Exception:                   # noqa: BLE001
            return "failed"
    return "simulated"
