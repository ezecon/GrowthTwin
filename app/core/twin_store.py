"""Section 2 storage: plots (state jsonb), daily logs, events. Supabase when configured, in-memory otherwise."""
import asyncio
import copy
from datetime import datetime, timezone
from functools import lru_cache

from .db import get_supabase


def _now():
    return datetime.now(timezone.utc).isoformat()


def _needs_review(s) -> bool:
    return any(r.get("status") == "pending" for r in s.get("review_pending", []))


class MemoryTwinStore:
    kind = "memory"

    def __init__(self):
        self.plots, self.logs, self.events, self.harvests = {}, {}, {}, {}
        self.sensor_readings = {}

    async def list_review_plots(self):
        return [copy.deepcopy(s) for s in self.plots.values() if _needs_review(s)]

    async def save_harvest(self, rec):
        self.harvests[rec["plot_id"]] = copy.deepcopy(rec)

    async def list_harvests_by_crop(self, crop_id):
        return [copy.deepcopy(r) for r in self.harvests.values() if r["crop_id"] == crop_id]

    async def count_active(self, crop_id):
        return len({s["user_id"] for s in self.plots.values() if s["crop_id"] == crop_id and s["status"] in ("growing", "ready")})

    async def list_harvests(self, user_id):
        return [copy.deepcopy(r) for r in self.harvests.values() if r["user_id"] == user_id]

    async def save_plot(self, s):
        self.plots[s["id"]] = copy.deepcopy(s)

    async def get_plot(self, pid):
        s = self.plots.get(pid)
        return copy.deepcopy(s) if s else None

    async def list_plots(self, user_id):
        return [copy.deepcopy(s) for s in self.plots.values() if s["user_id"] == user_id]

    async def delete_plot(self, pid):
        self.plots.pop(pid, None), self.logs.pop(pid, None), self.events.pop(pid, None)
        for key in [k for k in self.sensor_readings if k[0] == pid]:
            self.sensor_readings.pop(key, None)

    async def append_logs(self, pid, rows):
        d = self.logs.setdefault(pid, {})
        for r in rows:
            d[r["day"]] = copy.deepcopy(r)

    async def get_logs(self, pid, since_day=0, limit=400):
        rows = sorted((r for r in self.logs.get(pid, {}).values() if r["day"] >= since_day), key=lambda r: r["day"])
        return copy.deepcopy(rows[:limit])

    async def append_sensor_reading(self, row):
        """Persist a normalized device reading; sequence is unique per device."""
        key = (row["plot_id"], row["device_id"], int(row["sequence"]))
        if key in self.sensor_readings:
            raise ValueError("duplicate sensor sequence")
        self.sensor_readings[key] = copy.deepcopy(row)

    async def get_sensor_readings(self, pid, limit=200):
        rows = [r for r in self.sensor_readings.values() if r["plot_id"] == pid]
        rows.sort(key=lambda r: (r.get("timestamp", ""), r.get("sequence", -1)), reverse=True)
        return copy.deepcopy(rows[:limit])

    async def append_events(self, pid, rows):
        self.events.setdefault(pid, []).extend(copy.deepcopy(rows))

    async def get_events(self, pid, limit=100):
        return copy.deepcopy(self.events.get(pid, [])[-limit:][::-1])


class SupabaseTwinStore:
    kind = "supabase"

    def __init__(self, client):
        self.c = client

    async def save_plot(self, s):
        row = {"id": s["id"], "user_id": s["user_id"], "name": s["name"], "crop_id": s["crop_id"],
               "status": s["status"], "day": s["day"], "state": s, "needs_review": _needs_review(s),
               "updated_at": _now()}
        await asyncio.to_thread(lambda: self.c.table("twin_plots").upsert(row).execute())

    async def get_plot(self, pid):
        def run():
            r = self.c.table("twin_plots").select("state").eq("id", pid).limit(1).execute()
            return r.data[0]["state"] if r.data else None
        return await asyncio.to_thread(run)

    async def list_plots(self, user_id):
        def run():
            r = self.c.table("twin_plots").select("state").eq("user_id", user_id).order("updated_at", desc=True).limit(100).execute()
            return [x["state"] for x in r.data]
        return await asyncio.to_thread(run)

    async def delete_plot(self, pid):
        await asyncio.to_thread(lambda: self.c.table("twin_plots").delete().eq("id", pid).execute())

    async def list_review_plots(self):
        def run():
            r = self.c.table("twin_plots").select("state").eq("needs_review", True).limit(200).execute()
            return [x["state"] for x in r.data]
        return await asyncio.to_thread(run)

    async def save_harvest(self, rec):
        await asyncio.to_thread(lambda: self.c.table("harvest_records").upsert(rec, on_conflict="plot_id").execute())

    async def list_harvests_by_crop(self, crop_id):
        def run():
            r = (self.c.table("harvest_records")
                 .select("user_id,plot_id,crop_id,area,yield_kg_per_decimal,revenue,cost,profit,days,outcome,source,start_date")
                 .eq("crop_id", crop_id).order("created_at", desc=True).limit(2000).execute())
            return r.data
        return await asyncio.to_thread(run)

    async def count_active(self, crop_id):
        def run():
            r = (self.c.table("twin_plots").select("user_id").eq("crop_id", crop_id)
                 .in_("status", ["growing", "ready"]).limit(5000).execute())
            return len({x["user_id"] for x in r.data})
        return await asyncio.to_thread(run)

    async def list_harvests(self, user_id):
        def run():
            r = (self.c.table("harvest_records").select("*").eq("user_id", user_id)
                 .order("created_at", desc=True).limit(200).execute())
            return r.data
        return await asyncio.to_thread(run)

    async def append_logs(self, pid, rows):
        if not rows:
            return
        data = [{"plot_id": pid, "day": r["day"], "record": r} for r in rows]
        await asyncio.to_thread(lambda: self.c.table("twin_logs").upsert(data).execute())

    async def get_logs(self, pid, since_day=0, limit=400):
        def run():
            r = (self.c.table("twin_logs").select("record").eq("plot_id", pid).gte("day", since_day)
                 .order("day").limit(limit).execute())
            return [x["record"] for x in r.data]
        return await asyncio.to_thread(run)

    async def append_sensor_reading(self, row):
        data = {
            "plot_id": row["plot_id"], "source": row.get("source", "real"), "device_id": row["device_id"],
            "sequence": row["sequence"], "timestamp": row["timestamp"],
            "raw_moisture_adc": row["raw_moisture_adc"],
            "temperature_c": row.get("temperature_c"), "humidity_pct": row.get("humidity_pct"),
            "calibrated_moisture_pct": row["calibrated_moisture_pct"],
            "quality": row["quality"], "reality_gap": row["reality_gap"],
        }
        await asyncio.to_thread(lambda: self.c.table("sensor_readings").insert(data).execute())

    async def get_sensor_readings(self, pid, limit=200):
        def run():
            r = (self.c.table("sensor_readings").select(
                    "plot_id,source,device_id,sequence,timestamp,raw_moisture_adc,temperature_c,humidity_pct,calibrated_moisture_pct,quality,reality_gap,created_at")
                 .eq("plot_id", pid).order("timestamp", desc=True).limit(limit).execute())
            return r.data
        return await asyncio.to_thread(run)

    async def append_events(self, pid, rows):
        if not rows:
            return
        data = [{"plot_id": pid, "day": e["day"], "kind": e["kind"], "payload": e["payload"]} for e in rows]
        await asyncio.to_thread(lambda: self.c.table("twin_events").insert(data).execute())

    async def get_events(self, pid, limit=100):
        def run():
            r = (self.c.table("twin_events").select("day,kind,payload").eq("plot_id", pid)
                 .order("id", desc=True).limit(limit).execute())
            return r.data
        return await asyncio.to_thread(run)


@lru_cache
def get_twin_store():
    client = get_supabase()
    return SupabaseTwinStore(client) if client else MemoryTwinStore()
