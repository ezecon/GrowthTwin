"""Session + report-cache storage. Supabase when configured, in-memory otherwise."""
import asyncio
import time
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from .db import get_supabase

CACHE_TTL_S = 7 * 24 * 3600


def _now() -> datetime:
    return datetime.now(timezone.utc)


class MemoryStore:
    kind = "memory"

    def __init__(self):
        self.sessions: dict[str, dict] = {}
        self.cache: dict[str, tuple[float, dict]] = {}

    async def get_session(self, sid):
        return self.sessions.get(sid)

    async def save_session(self, sid, state):
        self.sessions[sid] = state

    async def get_cached(self, key):
        v = self.cache.get(key)
        if v and time.time() - v[0] < CACHE_TTL_S:
            return v[1]
        return None

    async def put_cached(self, key, report):
        self.cache[key] = (time.time(), report)

    async def review_queue(self):
        return [
            {"session_id": sid, **s}
            for sid, s in self.sessions.items()
            if s.get("review_status") == "pending"
        ]


class SupabaseStore:
    kind = "supabase"

    def __init__(self, client):
        self.c = client

    async def get_session(self, sid):
        def run():
            r = self.c.table("advisor_sessions").select("state").eq("id", sid).limit(1).execute()
            return r.data[0]["state"] if r.data else None

        return await asyncio.to_thread(run)

    async def save_session(self, sid, state):
        def run():
            self.c.table("advisor_sessions").upsert(
                {
                    "id": sid,
                    "state": state,
                    "review_status": state.get("review_status", "none"),
                    "updated_at": _now().isoformat(),
                }
            ).execute()

        await asyncio.to_thread(run)

    async def get_cached(self, key):
        cutoff = (_now() - timedelta(seconds=CACHE_TTL_S)).isoformat()

        def run():
            r = (
                self.c.table("report_cache")
                .select("report")
                .eq("key", key)
                .gte("created_at", cutoff)
                .limit(1)
                .execute()
            )
            return r.data[0]["report"] if r.data else None

        return await asyncio.to_thread(run)

    async def put_cached(self, key, report):
        def run():
            self.c.table("report_cache").upsert(
                {"key": key, "report": report, "created_at": _now().isoformat()}
            ).execute()

        await asyncio.to_thread(run)

    async def review_queue(self):
        def run():
            r = (
                self.c.table("advisor_sessions")
                .select("id,state")
                .eq("review_status", "pending")
                .order("updated_at")
                .limit(100)
                .execute()
            )
            return [{"session_id": row["id"], **row["state"]} for row in r.data]

        return await asyncio.to_thread(run)


@lru_cache
def get_store():
    client = get_supabase()
    return SupabaseStore(client) if client else MemoryStore()
