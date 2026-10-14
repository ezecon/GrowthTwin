"""WhatsApp/SMS storage: who a phone number is, where its chat is, one-time link codes.
Supabase when configured, in-memory otherwise (same pattern as store.py / twin_store.py).

link record (one per phone, phone = local format 01XXXXXXXXX):
  {"phone", "user_id": str|None, "session_id": str|None, "queue": [..pending questions..],
   "last_inbound_at": iso, "seen": [last message ids], "alerts": bool}
"""
import asyncio
import copy
import secrets
import time
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from .db import get_supabase

CODE_TTL_S = 600


def _now() -> datetime:
    return datetime.now(timezone.utc)


def new_code() -> str:
    return f"{secrets.randbelow(10**6):06d}"


class MemoryChannelStore:
    kind = "memory"

    def __init__(self):
        self.links: dict[str, dict] = {}
        self.codes: dict[str, tuple[float, str]] = {}

    async def get_link(self, phone):
        r = self.links.get(phone)
        return copy.deepcopy(r) if r else None

    async def save_link(self, rec):
        self.links[rec["phone"]] = copy.deepcopy(rec)

    async def get_link_by_user(self, user_id):
        for r in self.links.values():
            if r.get("user_id") == user_id:
                return copy.deepcopy(r)
        return None

    async def delete_link(self, phone):
        self.links.pop(phone, None)

    async def create_code(self, user_id):
        for k in [k for k, v in self.codes.items() if v[0] < time.time()]:
            self.codes.pop(k, None)
        for k in [k for k, v in self.codes.items() if v[1] == user_id]:  # one live code per user
            self.codes.pop(k, None)
        code = new_code()
        while code in self.codes:
            code = new_code()
        self.codes[code] = (time.time() + CODE_TTL_S, user_id)
        return code

    async def consume_code(self, code):
        v = self.codes.pop(code, None)
        return v[1] if v and v[0] >= time.time() else None


class SupabaseChannelStore:
    kind = "supabase"

    def __init__(self, client):
        self.c = client

    async def get_link(self, phone):
        def run():
            r = self.c.table("channel_links").select("state").eq("phone", phone).limit(1).execute()
            return r.data[0]["state"] if r.data else None
        return await asyncio.to_thread(run)

    async def save_link(self, rec):
        row = {"phone": rec["phone"], "user_id": rec.get("user_id"), "state": rec, "updated_at": _now().isoformat()}
        await asyncio.to_thread(lambda: self.c.table("channel_links").upsert(row).execute())

    async def get_link_by_user(self, user_id):
        def run():
            r = self.c.table("channel_links").select("state").eq("user_id", user_id).limit(1).execute()
            return r.data[0]["state"] if r.data else None
        return await asyncio.to_thread(run)

    async def delete_link(self, phone):
        await asyncio.to_thread(lambda: self.c.table("channel_links").delete().eq("phone", phone).execute())

    async def create_code(self, user_id):
        def run():
            self.c.table("channel_link_codes").delete().lt("expires_at", _now().isoformat()).execute()
            self.c.table("channel_link_codes").delete().eq("user_id", user_id).execute()
            for _ in range(5):
                code = new_code()
                try:
                    self.c.table("channel_link_codes").insert({
                        "code": code, "user_id": user_id,
                        "expires_at": (_now() + timedelta(seconds=CODE_TTL_S)).isoformat()}).execute()
                    return code
                except Exception:           # code collision: try another
                    continue
            raise RuntimeError("could not create link code")
        return await asyncio.to_thread(run)

    async def consume_code(self, code):
        def run():
            r = self.c.table("channel_link_codes").select("user_id,expires_at").eq("code", code).limit(1).execute()
            if not r.data:
                return None
            self.c.table("channel_link_codes").delete().eq("code", code).execute()
            exp = datetime.fromisoformat(r.data[0]["expires_at"].replace("Z", "+00:00"))
            return r.data[0]["user_id"] if exp >= _now() else None
        return await asyncio.to_thread(run)


@lru_cache
def get_channel_store():
    client = get_supabase()
    return SupabaseChannelStore(client) if client else MemoryChannelStore()
