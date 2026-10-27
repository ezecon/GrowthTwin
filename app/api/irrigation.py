"""Irrigation control: pump start/stop from anywhere, auto-schedule, safety limits.
Moisture is a RANDOM-WALK SIMULATION until a real sensor calls push_sensor(plot_id, pct).
In-memory state (resets on restart) - fine for the demo."""
import asyncio, logging, random, time
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from ..core.auth import User, current_user
from ..core.twin_store import get_twin_store
from ..services import twin_engine as te
from .twin import _owned, _persist

log = logging.getLogger("growthtwin.irrigation")
MM_PER_MIN = 0.5  # DEMO ASSUMPTION: water depth delivered per pump minute; calibrate with a real flow meter

router = APIRouter(prefix="/twin/plots/{pid}/irrigation", tags=["irrigation"])
TH = {"emergency_below": 20, "irrigate_below": 35, "stop_at": 60}
MAX_MIN, DAILY_CAP, COOLDOWN_S = 30, 90, 5
_S: dict[str, dict] = {}


def _iso(ts): return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def _st(pid):
    if pid not in _S:
        _S[pid] = {"v": random.uniform(28, 55), "mode": "sim", "last_sensor": None, "pump": None, "series": [],
                   "hist": [], "sync": [], "seeded": False, "last_stop": 0.0, "last_sample": 0.0, "last_tick": time.time(),
                   "sch": {"enabled": False, "every_minutes": 1440, "minutes": 10, "only_if_dry": True,
                           "anchor": time.time(), "last_skip": None}}
    return _S[pid]


def push_sensor(pid: str, pct: float):
    """Call this from the ESP32 ingest route later: real value replaces the simulation."""
    s = _st(pid); s["v"] = float(pct); s["mode"] = "sensor"; s["last_sensor"] = time.time()


def _used(s, now):
    tot = sum(h["actual_s"] for h in s["hist"] if h["_t"] > now - 86400) / 60
    if s["pump"]: tot += (now - s["pump"]["t0"]) / 60
    return tot


def _start(s, minutes, source, now):
    s["pump"] = {"t0": now, "minutes": minutes, "source": source, "before": s["v"]}
    s["sync"].append(("on", 0))


def _stop(s, reason, now):
    p = s["pump"]
    if not p: return
    s["hist"].insert(0, {"source": p["source"], "actual_s": round(now - p["t0"]), "stop_reason": reason,
                         "moisture_before": round(p["before"]), "moisture_after": round(s["v"]),
                         "started_at": _iso(p["t0"]), "_t": now})
    del s["hist"][30:]
    s["pump"], s["last_stop"] = None, now
    s["sync"].append(("off", s["hist"][0]["actual_s"]))
    s["sch"]["anchor"] = now  # manual or auto watering restarts the timer


def tick(pid, s):
    now = time.time(); dt = min(now - s["last_tick"], 5); s["last_tick"] = now
    if s["mode"] == "sensor" and s["last_sensor"] and now - s["last_sensor"] > 300:
        s["mode"] = "sim"  # sensor silent for 5 min -> fall back to demo values
    if s["mode"] == "sim":
        s["v"] = max(0, min(125, s["v"] + (0.5 * dt if s["pump"] else -0.03 * dt) + random.uniform(-.15, .15)))
    p = s["pump"]
    if p:
        if s["v"] >= TH["stop_at"]: _stop(s, "target_reached", now)
        elif now - p["t0"] >= p["minutes"] * 60: _stop(s, "completed", now)
        elif _used(s, now) >= DAILY_CAP: _stop(s, "completed", now)
    sc = s["sch"]
    if sc["enabled"] and not s["pump"] and now >= sc["anchor"] + sc["every_minutes"] * 60:
        if sc["only_if_dry"] and s["v"] >= TH["irrigate_below"]:
            sc["last_skip"] = {"at": _iso(now), "text_bn": f"মাটি যথেষ্ট ভেজা ({s['v']:.0f}%), সেচ বাদ"}
            sc["anchor"] = now
        elif _used(s, now) + sc["minutes"] > DAILY_CAP:
            sc["last_skip"] = {"at": _iso(now), "text_bn": "দৈনিক সীমা পূর্ণ, সেচ বাদ"}; sc["anchor"] = now
        else:
            _start(s, sc["minutes"], "schedule", now)
    if now - s["last_sample"] >= 3:
        s["last_sample"] = now
        s["series"].append({"t": _iso(now), "v": round(s["v"], 1), "pump": bool(s["pump"])}); del s["series"][:-240]


async def _sync(pid, kind, secs):
    """Mirror the real pump into the Section-2 twin so both screens agree."""
    try:
        st = await get_twin_store().get_plot(pid)
        if not st or st["status"] not in te.ACTIVE: return
        te._migrate(st)
        evs = [te.apply_action(st, "pump", on=(kind == "on"))]
        mm = min(secs / 60 * MM_PER_MIN, 60)
        if kind == "off" and mm > 0.2: evs.append(te.apply_action(st, "irrigate", mm=mm))
        await _persist(st, evs)
    except Exception as e:
        log.warning("twin sync failed: %s", e)


async def _drain(pid, s):
    while s["sync"]:
        kind, secs = s["sync"].pop(0); await _sync(pid, kind, secs)


async def loop():  # started from main.py lifespan: schedule works even when nobody has the page open
    while True:
        for pid, s in list(_S.items()):
            tick(pid, s); await _drain(pid, s)
        await asyncio.sleep(2)


def _view(s, full):
    now = time.time(); sc = s["sch"]; p = s["pump"]; used = _used(s, now)
    out = {"server_time": _iso(now), "mode": s["mode"],
           "moisture": {"value": round(s["v"], 1), "quality": "valid", "age_s": 0 if s["mode"] == "sim" else round(now - (s["last_sensor"] or now)),
                        "source": "sensor" if s["mode"] == "sensor" else "sim"},
           "thresholds": TH, "device": {"required": False, "online": True},
           "pump": {"on": bool(p), "source": p and p["source"], "minutes": p and p["minutes"],
                    "ends_at": p and _iso(p["t0"] + p["minutes"] * 60)},
           "limits": {"max_minutes": MAX_MIN, "daily_cap_min": DAILY_CAP, "used_24h_min": round(used, 1),
                      "left_24h_min": round(max(0, DAILY_CAP - used), 1)},
           "schedule": {k: sc[k] for k in ("enabled", "every_minutes", "minutes", "only_if_dry", "last_skip")}
                       | {"next_due_at": _iso(sc["anchor"] + sc["every_minutes"] * 60) if sc["enabled"] else None},
           "history": [{k: v for k, v in h.items() if k != "_t"} for h in s["hist"]]}
    if full: out["series"] = s["series"]
    return out


async def _get(pid, user):
    plot = await _owned(pid, user); first = pid not in _S; s = _st(pid)
    if first and not s["seeded"]:  # start the demo moisture from the twin's own soil-water value
        try: s["v"] = max(0.0, min(125.0, float(te._aw(plot))))
        except Exception: pass
        s["seeded"] = True
    tick(pid, s); await _drain(pid, s); return s


@router.get("")
async def state(pid: str, full: bool = True, user: User = Depends(current_user)):
    return _view(await _get(pid, user), full)


class StartIn(BaseModel):
    minutes: int = Field(5, ge=1, le=MAX_MIN)
    force: bool = False


@router.post("/start")
async def start(pid: str, body: StartIn, user: User = Depends(current_user)):
    s = await _get(pid, user); now = time.time()
    def bad(code, msg): raise HTTPException(409, {"code": code, "message_bn": msg})
    if s["pump"]: bad("already_on", "পাম্প আগে থেকেই চালু আছে")
    if now - s["last_stop"] < COOLDOWN_S: bad("cooldown", "কয়েক সেকেন্ড পরে আবার চেষ্টা করুন (পাম্প সুরক্ষা)")
    if s["v"] >= TH["stop_at"] + 15: bad("flooded", "জমি অতিরিক্ত ভেজা, সেচ দেওয়া হবে না")
    if s["v"] >= TH["stop_at"] and not body.force: bad("already_wet", f"মাটির আর্দ্রতা এখনই {s['v']:.0f}%")
    if _used(s, now) + body.minutes > DAILY_CAP: bad("daily_cap", "আজকের সেচের সীমা পূর্ণ হয়ে গেছে")
    _start(s, body.minutes, "manual", now)
    return _view(s, True)


@router.post("/stop")
async def stop(pid: str, user: User = Depends(current_user)):
    s = await _get(pid, user); _stop(s, "manual", time.time()); return _view(s, True)


class SchedIn(BaseModel):
    enabled: bool
    every_minutes: int = Field(1440, ge=2, le=10080)
    minutes: int = Field(10, ge=1, le=MAX_MIN)
    only_if_dry: bool = True


@router.post("/schedule")
async def schedule(pid: str, body: SchedIn, user: User = Depends(current_user)):
    s = await _get(pid, user); sc = s["sch"]
    if body.minutes >= body.every_minutes: raise HTTPException(422, {"code": "bad_sched", "message_bn": "সেচের সময় ব্যবধানের চেয়ে ছোট হতে হবে"})
    if body.enabled and not sc["enabled"]: sc["anchor"] = time.time()
    sc.update(enabled=body.enabled, every_minutes=body.every_minutes, minutes=body.minutes, only_if_dry=body.only_if_dry)
    return _view(s, True)


class SimIn(BaseModel):
    moisture_pct: float = Field(ge=0, le=125)


@router.post("/sim")
async def sim(pid: str, body: SimIn, user: User = Depends(current_user)):
    s = await _get(pid, user)
    if s["mode"] == "sensor": raise HTTPException(409, {"code": "real", "message_bn": "আসল সেন্সর চালু, সিমুলেশন বদলানো যাবে না"})
    s["v"] = body.moisture_pct; return _view(s, True)
