"""Login / register / logout with Supabase Auth (GoTrue REST), plus admin role management.

The browser never talks to Supabase directly: it calls these endpoints and keeps the returned access token
(`Authorization: Bearer ...`). Roles live in `app_metadata.role` and can only be changed by an admin (or the SQL editor).
"""
import asyncio
import re
import time
from collections import defaultdict, deque

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..core.auth import User, current_user, forget_tokens, require_role
from ..core.config import get_settings
from ..core.db import get_supabase

router = APIRouter(tags=["auth"])
ROLES = ("farmer", "expert", "admin")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# ---- tiny in-memory rate limit (per IP, per minute). Use a real limiter (Caddy/Cloudflare) when scaling to many workers.
_hits: dict[str, deque] = defaultdict(deque)


def _limit(request: Request, bucket: str, n: int = 10, per: int = 60) -> None:
    ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "?")).split(",")[0].strip()
    q = _hits[f"{bucket}|{ip}"]
    now = time.time()
    while q and now - q[0] > per:
        q.popleft()
    if len(q) >= n:
        raise HTTPException(429, "অনেকবার চেষ্টা হয়েছে। এক মিনিট পরে আবার চেষ্টা করুন।")
    q.append(now)


# ---- GoTrue helpers
def _need_supabase() -> tuple[str, str]:
    s = get_settings()
    if not (s.supabase_url and s.supabase_anon_key):
        raise HTTPException(503, "লগইন ব্যবস্থা এখনো চালু হয়নি (SUPABASE_URL ও SUPABASE_ANON_KEY দিন)")
    return s.supabase_url.rstrip("/"), s.supabase_anon_key


GOTRUE_ERR_BN = {
    "invalid_credentials": "ইমেইল বা পাসওয়ার্ড ভুল।",
    "email_not_confirmed": "আপনার ইমেইল এখনো নিশ্চিত করা হয়নি। ইনবক্সের লিংকে ক্লিক করুন।",
    "user_already_exists": "এই ইমেইল দিয়ে আগেই একাউন্ট আছে। লগইন করুন।",
    "email_exists": "এই ইমেইল দিয়ে আগেই একাউন্ট আছে। লগইন করুন।",
    "weak_password": "পাসওয়ার্ড দুর্বল। অন্তত ৮ অক্ষর দিন, অক্ষর ও সংখ্যা মেশান।",
    "over_request_rate_limit": "অনেকবার চেষ্টা হয়েছে। কিছুক্ষণ পরে আবার চেষ্টা করুন।",
    "over_email_send_rate_limit": "ইমেইল পাঠানোর সীমা শেষ। কিছুক্ষণ পরে আবার চেষ্টা করুন।",
    "signup_disabled": "এখন নতুন একাউন্ট খোলা বন্ধ আছে।",
    "refresh_token_not_found": "সেশন শেষ, আবার লগইন করুন।",
    "refresh_token_already_used": "সেশন শেষ, আবার লগইন করুন।",
    "session_not_found": "সেশন শেষ, আবার লগইন করুন।",
}


async def _gotrue(method: str, path: str, *, json=None, params=None, bearer: str | None = None) -> dict:
    url, anon = _need_supabase()
    headers = {"apikey": anon, "Content-Type": "application/json"}
    headers["Authorization"] = f"Bearer {bearer or anon}"
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.request(method, f"{url}/auth/v1{path}", json=json, params=params, headers=headers)
    except httpx.HTTPError:
        raise HTTPException(502, "লগইন সার্ভারের সাথে যোগাযোগ করা যাচ্ছে না।")
    body = {}
    if r.content:
        try:
            body = r.json()
        except ValueError:
            body = {}
    if r.status_code >= 400:
        code = body.get("error_code") or body.get("code") or body.get("error") or ""
        if isinstance(code, int):
            code = ""
        msg = GOTRUE_ERR_BN.get(str(code))
        if not msg:
            # older GoTrue versions have no error_code: fall back to the message text
            low = str(body.get("msg") or body.get("error_description") or body.get("message") or "").lower()
            if "invalid login" in low:
                msg = GOTRUE_ERR_BN["invalid_credentials"]
            elif "not confirmed" in low:
                msg = GOTRUE_ERR_BN["email_not_confirmed"]
            elif "already" in low and "registered" in low:
                msg = GOTRUE_ERR_BN["user_already_exists"]
        status = 401 if (path == "/token" and r.status_code == 400) else r.status_code
        raise HTTPException(status, msg or "অনুরোধ সফল হয়নি। আবার চেষ্টা করুন।")
    return body


def _user_view(u: dict) -> dict:
    role = (u.get("app_metadata") or {}).get("role", "farmer")
    um = u.get("user_metadata") or {}
    return {"id": u.get("id"), "email": u.get("email"), "role": role if role in ROLES else "farmer",
            "full_name": um.get("full_name", ""), "phone": um.get("phone", ""),
            "role_request": um.get("role_request", "farmer")}


def _session_view(b: dict) -> dict:
    return {"access_token": b["access_token"], "refresh_token": b["refresh_token"],
            "expires_in": b.get("expires_in", 3600), "user": _user_view(b.get("user") or {})}


# ---- models
class RegisterIn(BaseModel):
    email: str = Field(..., max_length=120)
    password: str = Field(..., min_length=8, max_length=72)
    full_name: str = Field(..., min_length=2, max_length=80)
    phone: str = Field("", max_length=16)
    role_request: str = "farmer"            # "expert" only records a request; an admin must approve it


class LoginIn(BaseModel):
    email: str = Field(..., max_length=120)
    password: str = Field(..., min_length=1, max_length=72)


class RefreshIn(BaseModel):
    refresh_token: str = Field(..., min_length=10, max_length=500)


class RoleIn(BaseModel):
    role: str


# ---- public
@router.get("/auth/config")
async def auth_config():
    s = get_settings()
    return {"auth_required": s.auth_required, "signup_enabled": s.signup_enabled,
            "configured": bool(s.supabase_url and s.supabase_anon_key), "roles": list(ROLES)}


@router.post("/auth/register")
async def register(body: RegisterIn, request: Request):
    _limit(request, "register", 5)
    if not get_settings().signup_enabled:
        raise HTTPException(403, GOTRUE_ERR_BN["signup_disabled"])
    email = body.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(422, "ইমেইল সঠিক নয়।")
    if not (re.search(r"[A-Za-z]", body.password) and re.search(r"\d", body.password)):
        raise HTTPException(422, GOTRUE_ERR_BN["weak_password"])
    if body.phone and not re.fullmatch(r"01[3-9]\d{8}", body.phone):
        raise HTTPException(422, "মোবাইল নম্বর সঠিক নয় (যেমন 01712345678)।")
    # NOTE: the role is NOT taken from the client. Everyone starts as a farmer; "role_request" is only a note for admins.
    data = {"full_name": body.full_name.strip(), "phone": body.phone,
            "role_request": "expert" if body.role_request == "expert" else "farmer"}
    b = await _gotrue("POST", "/signup", json={"email": email, "password": body.password, "data": data})
    if b.get("access_token"):                      # email confirmation is OFF in Supabase: signed in straight away
        return {"status": "signed_in", **_session_view(b)}
    return {"status": "confirm_email", "message_bn": "ইমেইলে একটি নিশ্চিতকরণ লিংক পাঠানো হয়েছে। লিংকে ক্লিক করে তারপর লগইন করুন।"}


@router.post("/auth/login")
async def login(body: LoginIn, request: Request):
    _limit(request, "login", 10)
    b = await _gotrue("POST", "/token", params={"grant_type": "password"},
                      json={"email": body.email.strip().lower(), "password": body.password})
    return _session_view(b)


@router.post("/auth/refresh")
async def refresh(body: RefreshIn, request: Request):
    _limit(request, "refresh", 30)
    b = await _gotrue("POST", "/token", params={"grant_type": "refresh_token"}, json={"refresh_token": body.refresh_token})
    return _session_view(b)


@router.post("/auth/logout")
async def logout(request: Request):
    h = request.headers.get("authorization", "")
    if h.lower().startswith("bearer ") and get_settings().auth_required:
        try:
            await _gotrue("POST", "/logout", params={"scope": "local"}, bearer=h[7:].strip())
        except HTTPException:
            pass                                    # already expired: nothing to revoke
        forget_tokens()
    return {"ok": True}


@router.get("/auth/me")
async def me(user: User = Depends(current_user)):
    return {"id": user.id, "email": user.email, "role": user.role, "full_name": user.name}


# ---- admin: approve experts / change roles
@router.get("/admin/users")
async def list_users(user: User = Depends(require_role("admin"))):
    c = get_supabase()
    if c is None:
        raise HTTPException(503, "Supabase সেট করা নেই")
    users = await asyncio.to_thread(lambda: c.auth.admin.list_users(page=1, per_page=200))
    out = []
    for u in users:
        am, um = (u.app_metadata or {}), (u.user_metadata or {})
        out.append({"id": u.id, "email": u.email, "role": am.get("role", "farmer"),
                    "full_name": um.get("full_name", ""), "role_request": um.get("role_request", "farmer"),
                    "created_at": str(u.created_at)[:10]})
    out.sort(key=lambda x: (x["role_request"] != "expert" or x["role"] == "expert", x["created_at"]))
    return out


@router.post("/admin/users/{uid}/role")
async def set_role(uid: str, body: RoleIn, user: User = Depends(require_role("admin"))):
    if body.role not in ROLES:
        raise HTTPException(422, "ভূমিকা সঠিক নয়")
    if uid == user.id and body.role != "admin":
        raise HTTPException(400, "নিজের অ্যাডমিন ভূমিকা সরানো যাবে না")
    c = get_supabase()
    if c is None:
        raise HTTPException(503, "Supabase সেট করা নেই")
    try:
        await asyncio.to_thread(lambda: c.auth.admin.update_user_by_id(uid, {"app_metadata": {"role": body.role}}))
    except Exception:
        raise HTTPException(404, "ব্যবহারকারী পাওয়া যায়নি")
    forget_tokens()
    return {"id": uid, "role": body.role}
