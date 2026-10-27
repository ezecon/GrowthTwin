import asyncio
import time
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request

from .config import get_settings
from .db import get_supabase


@dataclass
class User:
    id: str
    role: str  # farmer | expert | admin
    email: str = ""
    name: str = ""


_cache: dict[str, tuple[float, User]] = {}


async def current_user(request: Request) -> User:
    s = get_settings()
    if not s.auth_required:
        # DEV ONLY: role via header. main.py refuses to boot in prod with this mode.
        return User(
            request.headers.get("x-dev-user", "anon"),
            request.headers.get("x-dev-role", "farmer"),
        )
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(401, "Missing bearer token")
    token = header[7:].strip()
    hit = _cache.get(token)
    if hit and time.time() - hit[0] < 60:
        return hit[1]
    client = get_supabase()
    if client is None:
        raise HTTPException(500, "Auth backend not configured")
    try:
        res = await asyncio.to_thread(client.auth.get_user, token)
        u = res.user
        role = (u.app_metadata or {}).get("role", "farmer")
        um = u.user_metadata or {}
        user = User(u.id, role if role in ("farmer", "expert", "admin") else "farmer",
                    u.email or "", str(um.get("full_name", ""))[:80])
    except Exception:
        raise HTTPException(401, "Invalid token")
    _cache[token] = (time.time(), user)
    return user


def forget_tokens() -> None:
    """Drop the 60 s token cache (called after a role change so it applies immediately)."""
    _cache.clear()


def require_role(*roles: str):
    async def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, "Forbidden")
        return user

    return dep
