"""Section 2: plot digital twin (full crop life-cycle simulation)."""
import base64
import binascii
import logging
import hmac
import hashlib
import secrets
import copy
import uuid
import random
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from ..core.auth import User, current_user, require_role
from ..core.config import get_settings
from ..core.twin_store import get_twin_store
from ..data import SOILS_BN, crops
from ..services.sensor_calibration import MoistureCalibration
from ..services.sensor_health import assess_reading

SOILS_EN = {"doash": "Loam", "entel": "Clay", "beley": "Sandy"}
from ..services import crop_stages as cs
from ..services import chat_flow, disease_models, notify
from ..services import twin_engine as te
from ..services import twin_summary
from ..services.state_estimator import correct_state

log = logging.getLogger(__name__)
router = APIRouter(prefix="/twin", tags=["twin"])
MAX_PLOTS_PER_USER = 20
SMS_LEVELS = ("critical", "action")
MAX_SMS_PER_CALL = 3


class PlotIn(BaseModel):
    crop_id: str
    name: str = Field("", max_length=60)
    area_decimal: float = Field(..., gt=0, le=5000)
    soil_type: str = "doash"
    ph: float | None = Field(None, ge=3.5, le=9.5)
    ec: float | None = Field(None, ge=0, le=20)
    start_date: date | None = None
    seed: int | None = None
    auto_irrigation: bool = True
    auto_inputs: bool = False
    sms_enabled: bool = False
    phone: str = Field("", max_length=16)


class AdvanceIn(BaseModel):
    days: int = Field(1, ge=1, le=400)
    stop_on_alert: bool = True
    auto_harvest: bool = False


class ActionIn(BaseModel):
    type: str
    nutrient: str | None = None
    mm: float | None = Field(None, ge=0, le=60)
    kg_per_decimal: float | None = Field(None, ge=0, le=15)
    on: bool | None = None


class AnswersIn(BaseModel):
    answers: dict[str, str]


class ConfigIn(BaseModel):
    auto_irrigation: bool | None = None
    auto_inputs: bool | None = None
    sms_enabled: bool | None = None
    phone: str | None = Field(None, max_length=16)


class ReadingIn(BaseModel):
    ph: float | None = Field(None, ge=3.5, le=9.5)                 # pH strip
    ec: float | None = Field(None, ge=0, le=20)                    # dS/m
    moisture_pct: float | None = Field(None, ge=0, le=160)         # calibrated plant-available water %, not raw ADC
    source: Literal["manual", "sensor", "simulation"] = "manual"
    moisture_quality: Literal["valid", "suspect", "invalid", "stale"] = "valid"


class SensorCalibrationIn(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=80)
    adc_at_wilting_point: int = Field(..., ge=0, le=65535)
    adc_at_field_capacity: int = Field(..., ge=0, le=65535)
    adc_min: int = Field(0, ge=0, le=65535)
    adc_max: int = Field(4095, ge=1, le=65535)


class SensorSimulationIn(BaseModel):
    count: int = Field(12, ge=1, le=100)
    device_id: str = Field("SIM-ESP32-01", min_length=1, max_length=80)


class DeviceReadingIn(BaseModel):
    plot_id: str = Field(..., min_length=1, max_length=100)
    device_id: str = Field(..., min_length=1, max_length=80)
    sequence: int = Field(..., ge=0, le=2**31 - 1)
    timestamp: datetime
    raw_moisture_adc: int = Field(..., ge=0, le=65535)
    temperature_c: float | None = Field(None, ge=-30, le=80)
    humidity_pct: float | None = Field(None, ge=0, le=100)


class PhotoIn(BaseModel):
    image_b64: str = Field(..., max_length=3_000_000)   # shrink on the phone first (about 512 px JPEG)


class ReviewIn(BaseModel):
    verdict: Literal["disease", "healthy", "unsure"]
    label: str = Field("", max_length=80)
    note: str = Field("", max_length=1000)


class ExperimentIn(BaseModel):
    name: str = Field("", max_length=80)
    horizon_days: int = Field(14, ge=1, le=120)
    intervention: Literal["irrigation", "fertilizer"]
    irrigation_auto: bool | None = None
    nutrient: Literal["N", "P", "K"] | None = None


def _check_phone(p: str) -> None:
    if p and not notify.valid_phone(p):
        raise HTTPException(400, "মোবাইল নম্বর সঠিক নয় (যেমন 01712345678)")


async def _owned(pid: str, user: User) -> dict:
    s = await get_twin_store().get_plot(pid)
    if not s or (s["user_id"] != user.id and user.role not in ("expert", "admin")):
        raise HTTPException(404, "প্লট পাওয়া যায়নি")
    te._migrate(s)
    return s


async def _persist(s: dict, events: list, logs=()) -> list:
    """Side effects after the engine ran: SMS for urgent alerts, harvest record, then save everything."""
    store = get_twin_store()
    extra = []
    cfg = s["config"]
    if cfg.get("sms_enabled") and cfg.get("phone"):
        urgent = [e for e in events if e["kind"] == "alert" and e["payload"]["level"] in SMS_LEVELS][:MAX_SMS_PER_CALL]
        for e in urgent:
            p = e["payload"]
            text = f"GrowthTwin {s['name']}: {p['title_bn']}. {p['text_bn']}"
            status = await notify.send_sms(cfg["phone"], text)
            extra.append({"day": e["day"], "kind": "sms",
                          "payload": {"to": notify.mask(cfg["phone"]), "text_bn": text[:200], "status": status}})
    extra += await chat_flow.push_alerts(s, events)       # WhatsApp copy of the same urgent alerts (if the owner linked a phone)
    if s["status"] in ("harvested", "dead") and not s.get("harvest_saved"):
        try:
            await store.save_harvest(te.harvest_record(s))
            s["harvest_saved"] = True
        except Exception:                      # e.g. schema.sql not re-run yet (outcome/source columns): never block the farmer
            log.exception("harvest record not saved")
    await store.save_plot(s)
    await store.append_logs(s["id"], list(logs))
    await store.append_events(s["id"], events + extra)
    return extra


@router.get("/meta")
async def meta():
    return {"crops": [{"id": c.id, "name_bn": c.name_bn, "name_en": c.name_en, "duration_days": c.duration_days,
                       "stages": [x.name_bn for x in cs.stages(c.id)],
                       "disease_model": disease_models.available(c.id)} for c in crops().values()],
            "soils": [{"id": k, "name_bn": v, "name_en": SOILS_EN.get(k, k)} for k, v in SOILS_BN.items()]}


@router.post("/plots")
async def create_plot(body: PlotIn, user: User = Depends(current_user)):
    store = get_twin_store()
    if body.crop_id not in crops():
        raise HTTPException(400, "অজানা ফসল")
    _check_phone(body.phone)
    if body.sms_enabled and not body.phone:
        raise HTTPException(400, "SMS চালু করতে মোবাইল নম্বর দিন")
    if len(await store.list_plots(user.id)) >= MAX_PLOTS_PER_USER:
        raise HTTPException(400, f"সর্বোচ্চ {MAX_PLOTS_PER_USER}টি প্লট রাখা যায়")
    try:
        s = te.new_plot(user.id, body.name, body.crop_id, body.soil_type, body.area_decimal, body.ph, body.ec,
                        body.start_date.isoformat() if body.start_date else None, body.seed,
                        {"auto_irrigation": body.auto_irrigation, "auto_inputs": body.auto_inputs,
                         "sms_enabled": body.sms_enabled, "phone": body.phone})
    except ValueError as e:
        raise HTTPException(400, str(e))
    await store.save_plot(s)
    return te.snapshot(s)


@router.get("/plots")
async def list_plots(user: User = Depends(current_user)):
    out = []
    for s in await get_twin_store().list_plots(user.id):
        v = te.snapshot(s)
        out.append({k: v[k] for k in ("id", "name", "crop", "day", "duration", "status", "health", "date")})
    return out


@router.get("/plots/{pid}")
async def get_plot(pid: str, user: User = Depends(current_user)):
    return te.snapshot(await _owned(pid, user))


@router.delete("/plots/{pid}")
async def delete_plot(pid: str, user: User = Depends(current_user)):
    await _owned(pid, user)
    await get_twin_store().delete_plot(pid)
    return {"ok": True}


@router.post("/plots/{pid}/config")
async def set_config(pid: str, body: ConfigIn, user: User = Depends(current_user)):
    s = await _owned(pid, user)
    upd = body.model_dump(exclude_none=True)
    if "phone" in upd:
        _check_phone(upd["phone"])
    s["config"].update(upd)
    if s["config"].get("sms_enabled") and not s["config"].get("phone"):
        raise HTTPException(400, "SMS চালু করতে মোবাইল নম্বর দিন")
    await get_twin_store().save_plot(s)
    return te.snapshot(s)


@router.post("/plots/{pid}/advance")
async def advance(pid: str, body: AdvanceIn, user: User = Depends(current_user)):
    s = await _owned(pid, user)
    if s["status"] not in te.ACTIVE:
        raise HTTPException(400, "এই ফসলের জীবনচক্র শেষ হয়ে গেছে")
    r = te.advance(s, body.days, body.stop_on_alert, body.auto_harvest)
    sms = await _persist(s, r["events"], r["logs"])
    return {"plot": te.snapshot(s), "days_run": len(r["logs"]), "stopped_for": r["stopped_for"],
            "events": r["events"] + sms, "logs": r["logs"]}


@router.post("/plots/{pid}/action")
async def action(pid: str, body: ActionIn, user: User = Depends(current_user)):
    s = await _owned(pid, user)
    try:
        ev = te.apply_action(s, body.type, nutrient=body.nutrient, mm=body.mm,
                             kg_per_decimal=body.kg_per_decimal, on=body.on)
    except ValueError as e:
        raise HTTPException(400, str(e))
    await _persist(s, [ev])
    return {"plot": te.snapshot(s), "event": ev}


@router.get("/plots/{pid}/experiments")
async def list_experiments(pid: str, user: User = Depends(current_user)):
    """Return saved, reproducible what-if experiments for this plot."""
    s = await _owned(pid, user)
    return {"plot_id": pid, "experiments": s.get("experiments", [])[-20:]}


@router.post("/plots/{pid}/experiments")
async def run_experiment(pid: str, body: ExperimentIn, user: User = Depends(current_user)):
    """Compare baseline and intervention on isolated copies; never changes the live plot."""
    live = await _owned(pid, user)
    if live["status"] not in te.ACTIVE:
        raise HTTPException(400, "এই প্লটের ফসলের জীবনচক্র শেষ; নতুন পরীক্ষা চালানো যাবে না।")
    if body.intervention == "irrigation" and body.irrigation_auto is None:
        raise HTTPException(400, "সেচ পরীক্ষায় অটো সেচ চালু বা বন্ধ বেছে নিন।")
    if body.intervention == "fertilizer" and body.nutrient is None:
        raise HTTPException(400, "সার পরীক্ষায় N, P অথবা K বেছে নিন।")

    baseline = copy.deepcopy(live)
    variant = copy.deepcopy(live)
    # Keep identical starting state and deterministic weather seed for a fair comparison.
    if body.intervention == "irrigation":
        variant["config"]["auto_irrigation"] = bool(body.irrigation_auto)
        intervention_bn = "অটো সেচ " + ("চালু" if body.irrigation_auto else "বন্ধ")
    else:
        nutrient_names = {"N": "ইউরিয়া (N)", "P": "টিএসপি (P)", "K": "এমওপি (K)"}
        try:
            te.apply_action(variant, "fertilize", nutrient=body.nutrient)
        except ValueError as e:
            raise HTTPException(400, str(e))
        intervention_bn = f"শুরুতে {nutrient_names[body.nutrient]} প্রয়োগ"

    base_run = te.advance(baseline, body.horizon_days, stop_on_alert=False, auto_harvest=False)
    test_run = te.advance(variant, body.horizon_days, stop_on_alert=False, auto_harvest=False)

    def metrics(state, run):
        crop = crops()[state["crop_id"]]
        est = te._estimate(state, crop) if state["status"] != "dead" else {"yield_kg": 0, "profit": -round(crop.cost * state["area"]), "revenue": 0, "cost": round(crop.cost * state["area"])}
        return {
            "days_simulated": len(run["logs"]), "status": state["status"],
            "health": round(state["health"], 1), "soil_moisture_pct": round(state["w_mm"] / state["awc"] * 100, 1),
            "water_l": round(state["totals"].get("water_l", 0), 1),
            "irrigation_mm": round(state["totals"].get("irrig_mm", 0), 1),
            "estimated_yield_kg": int(est["yield_kg"]), "estimated_profit_bdt": int(est["profit"]),
            "crop_stress": round(max(0, 100 - state["health"]), 1),
        }

    before, after = metrics(baseline, base_run), metrics(variant, test_run)
    delta = {k: round(after[k] - before[k], 1) for k in ("health", "water_l", "irrigation_mm", "estimated_yield_kg", "estimated_profit_bdt", "crop_stress")}
    record = {
        "id": uuid.uuid4().hex[:12], "name": body.name.strip() or f"পরীক্ষা: {intervention_bn}",
        "created_at": datetime.now(timezone.utc).isoformat(), "plot_id": pid,
        "crop_id": live["crop_id"], "plot_day_start": live["day"], "horizon_days": body.horizon_days,
        "intervention": body.intervention, "intervention_bn": intervention_bn,
        "assumptions": {"same_starting_state": True, "same_weather_seed": True,
                        "model": "GrowthTwin rule-based simulation", "live_plot_modified": False},
        "baseline": before, "scenario": after, "delta": delta,
        "explanation_bn": "এটি একই প্রাথমিক অবস্থা ও একই সিমুলেটেড আবহাওয়া দিয়ে করা তুলনামূলক পরীক্ষা। ফলাফল মডেল-নির্ভর অনুমান, বাস্তব ফলনের নিশ্চয়তা নয়।"
    }
    history = live.setdefault("experiments", [])
    history.append(record)
    live["experiments"] = history[-20:]
    await get_twin_store().save_plot(live)
    return record


@router.post("/plots/{pid}/sensor-calibration")
async def set_sensor_calibration(pid: str, body: SensorCalibrationIn, user: User = Depends(current_user)):
    """Register the device and its two measured calibration endpoints for one plot."""
    s = await _owned(pid, user)
    calibration = MoistureCalibration(
        adc_at_wilting_point=body.adc_at_wilting_point,
        adc_at_field_capacity=body.adc_at_field_capacity,
        adc_min=body.adc_min,
        adc_max=body.adc_max,
    )
    try:
        calibration.validate()
    except ValueError as e:
        raise HTTPException(400, str(e))
    sentinel = s.setdefault("sentinel", {})
    # A device gets its own one-time secret. Only the SHA-256 digest is retained.
    device_token = secrets.token_urlsafe(32)
    sentinel["sensor_config"] = {
        "device_id": body.device_id,
        "device_token_sha256": hashlib.sha256(device_token.encode("utf-8")).hexdigest(),
        "calibration": {
            "adc_at_wilting_point": body.adc_at_wilting_point,
            "adc_at_field_capacity": body.adc_at_field_capacity,
            "adc_min": body.adc_min,
            "adc_max": body.adc_max,
        },
    }
    await get_twin_store().save_plot(s)
    return {"ok": True, "plot_id": pid, "device_id": body.device_id,
            "device_token": device_token,
            "calibration": sentinel["sensor_config"]["calibration"],
            "note": "Save device_token securely now; it is shown only at provisioning. Use measured endpoints for this probe and soil."}


@router.post("/device/readings")
async def ingest_device_reading(
    body: DeviceReadingIn,
    x_sensor_token: str = Header(default="", alias="X-Sensor-Token"),
):
    """ESP32 ingestion endpoint. Requires SENSOR_INGEST_TOKEN and plot-specific calibration."""
    expected_token = get_settings().sensor_ingest_token
    if not expected_token:
        raise HTTPException(503, "Sensor ingestion is disabled: configure SENSOR_INGEST_TOKEN")
    s = await get_twin_store().get_plot(body.plot_id)
    if not s:
        raise HTTPException(404, "Plot not found")
    te._migrate(s)
    if s["status"] not in te.ACTIVE:
        raise HTTPException(409, "Plot lifecycle has ended")

    timestamp = body.timestamp
    if timestamp.tzinfo is None:
        raise HTTPException(422, "timestamp must include a timezone, for example Z")
    timestamp = timestamp.astimezone(timezone.utc)
    now = datetime.now(timezone.utc)
    if timestamp > now + timedelta(minutes=5):
        raise HTTPException(422, "Sensor timestamp is too far in the future")
    if timestamp < now - timedelta(hours=24):
        raise HTTPException(422, "Sensor reading is stale (older than 24 hours)")

    sentinel = s.setdefault("sentinel", {})
    config = sentinel.get("sensor_config") or {}
    if config.get("device_id") != body.device_id or not config.get("calibration"):
        raise HTTPException(409, "This device is not registered with calibration for the requested plot")
    device_hash = config.get("device_token_sha256")
    supplied_hash = hashlib.sha256(x_sensor_token.encode("utf-8")).hexdigest()
    # New registrations use per-device credentials. The shared token is accepted only
    # for pre-migration plot registrations which do not yet have a device-token digest.
    valid_token = (hmac.compare_digest(supplied_hash, device_hash) if device_hash
                   else hmac.compare_digest(x_sensor_token, expected_token))
    if not valid_token:
        raise HTTPException(401, "Invalid sensor token")
    device_state = sentinel.setdefault("device_state", {})
    previous = device_state.get(body.device_id, {})
    if body.sequence <= int(previous.get("last_sequence", -1)):
        raise HTTPException(409, "Duplicate or out-of-order sensor sequence")

    try:
        calibrated = MoistureCalibration(**config["calibration"]).convert(body.raw_moisture_adc)
    except (ValueError, TypeError) as e:
        raise HTTPException(422, str(e))

    measured = calibrated["moisture_pct"]
    health = assess_reading(body.raw_moisture_adc, previous, calibrated["quality"])
    quality = health.quality
    predicted = float(s["w_mm"] / s["awc"] * 100)
    gap = correct_state(predicted, measured, alpha=0.65, minimum=0.0, maximum=160.0,
                        quality=quality).as_dict()
    try:
        ev = te.apply_reading(s, moisture_pct=gap["estimated_value"], source="sensor")
    except ValueError as e:
        raise HTTPException(400, str(e))

    reading_record = {
        "source": "real",
        "device_id": body.device_id,
        "sequence": body.sequence,
        "timestamp": timestamp.isoformat(),
        "raw_moisture_adc": body.raw_moisture_adc,
        "temperature_c": body.temperature_c,
        "humidity_pct": body.humidity_pct,
        "calibrated_moisture_pct": measured,
        "quality": quality,
        "health": health.as_dict(),
        "reality_gap": gap,
    }
    device_state[body.device_id] = {"last_sequence": body.sequence, "last_timestamp": timestamp.isoformat(),
                                    "last_raw_moisture_adc": body.raw_moisture_adc,
                                    "consecutive_identical": health.consecutive_identical}
    sentinel["latest_device_reading"] = reading_record
    history = sentinel.setdefault("device_reading_history", [])
    history.append({"day": s["day"], **reading_record})
    del history[:-500]
    # Try normalized telemetry storage. If the optional table migration has not
    # been applied yet, the reading remains in the plot JSON state and the device
    # request still succeeds; the dashboard can use that fallback history.
    try:
        await get_twin_store().append_sensor_reading({
            "plot_id": body.plot_id, "source": "real", "device_id": body.device_id,
            "sequence": body.sequence, "timestamp": timestamp.isoformat(),
            "raw_moisture_adc": body.raw_moisture_adc,
            "temperature_c": body.temperature_c, "humidity_pct": body.humidity_pct,
            "calibrated_moisture_pct": measured, "quality": quality, "reality_gap": gap,
        })
    except Exception as exc:
        log.warning("Sensor telemetry table unavailable; keeping reading in plot state: %s", exc)
    sentinel["latest_reality_gap"] = gap
    gap_history = sentinel.setdefault("reality_gap_history", [])
    gap_history.append({"day": s["day"], **gap})
    del gap_history[:-500]
    ev["payload"].update({"device_reading": reading_record, "reality_gap": gap})
    await _persist(s, [ev])
    return {"accepted": True, "plot_id": body.plot_id, "source": "real", "device_id": body.device_id,
            "sequence": body.sequence, "calibrated_moisture_pct": measured,
            "quality": quality, "health": health.as_dict(), "reality_gap": gap}


@router.get("/plots/{pid}/sensor-readings")
async def sensor_readings(pid: str, limit: int = 100, user: User = Depends(current_user)):
    """Read telemetry from the table, falling back to plot-state history if migration is pending."""
    if not 1 <= limit <= 500:
        raise HTTPException(422, "limit must be between 1 and 500")
    plot = await _owned(pid, user)
    store = get_twin_store()
    storage = "table"
    try:
        rows = await store.get_sensor_readings(pid, limit=limit)
    except Exception as exc:
        log.warning("Could not query sensor_readings table; using plot-state fallback: %s", exc)
        rows = []
        storage = "plot_state_fallback"
    if not rows:
        sentinel = plot.get("sentinel", {})
        history = sentinel.get("device_reading_history", [])
        rows = []
        for item in reversed(history):
            row = {k: v for k, v in item.items() if k != "day"}
            row.setdefault("plot_id", pid)
            row.setdefault("source", "real")
            rows.append(row)
        rows.sort(key=lambda r: (r.get("timestamp", ""), r.get("sequence", -1)), reverse=True)
        rows = rows[:limit]
        if rows and storage == "table":
            storage = "plot_state_fallback"
    return {"plot_id": pid, "count": len(rows), "readings": rows, "storage": storage}


@router.post("/plots/{pid}/sensor-simulation")
async def simulate_sensor_readings(pid: str, body: SensorSimulationIn, user: User = Depends(current_user)):
    """Generate clearly-labelled simulated telemetry for UI/demo use; never controls the pump."""
    plot = await _owned(pid, user)
    if plot["status"] not in te.ACTIVE:
        raise HTTPException(409, "Plot lifecycle has ended; telemetry simulation is unavailable.")
    sentinel = plot.setdefault("sentinel", {})
    history = sentinel.setdefault("device_reading_history", [])
    state_moisture = max(0.0, min(100.0, float(plot["w_mm"] / max(plot["awc"], 1e-6) * 100)))
    seed = int(datetime.now(timezone.utc).timestamp()) + int(plot.get("day", 0))
    rng = random.Random(seed)
    now = datetime.now(timezone.utc)
    start_seq = int(sentinel.get("simulation_sequence", 0))
    config = sentinel.get("sensor_config") or {}
    cal = config.get("calibration") or {}
    wp = cal.get("adc_at_wilting_point", 3000)
    fc = cal.get("adc_at_field_capacity", 1500)
    new_rows = []
    for i in range(body.count):
        # Smooth, bounded variation around the current twin estimate, not a real measurement.
        moisture = round(max(0.0, min(100.0, state_moisture + rng.uniform(-8, 8) + (i - body.count / 2) * 0.15)), 2)
        denominator = float(fc - wp) if fc != wp else -1500.0
        raw_adc = int(max(0, min(65535, wp + (moisture / 100.0) * denominator)))
        timestamp = (now - timedelta(seconds=(body.count - i - 1) * 30)).isoformat()
        predicted = state_moisture
        gap = correct_state(predicted, moisture, alpha=0.65, minimum=0.0, maximum=160.0, quality="valid").as_dict()
        seq = start_seq + i + 1
        row = {
            "day": plot["day"], "source": "simulation", "device_id": body.device_id,
            "sequence": seq, "timestamp": timestamp, "raw_moisture_adc": raw_adc,
            "temperature_c": round(rng.uniform(24, 34), 1),
            "humidity_pct": round(rng.uniform(55, 90), 1),
            "calibrated_moisture_pct": moisture, "quality": "valid", "reality_gap": gap,
        }
        history.append(row)
        new_rows.append(row)
        try:
            await get_twin_store().append_sensor_reading({"plot_id": pid, **{k: v for k, v in row.items() if k != "day"}})
        except Exception as exc:
            log.debug("Simulated telemetry kept in plot state because table storage is unavailable: %s", exc)
    sentinel["simulation_sequence"] = start_seq + body.count
    sentinel["latest_device_reading"] = new_rows[-1]
    sentinel["latest_reality_gap"] = new_rows[-1]["reality_gap"]
    del history[:-500]
    await get_twin_store().save_plot(plot)
    return {"plot_id": pid, "source": "simulation", "created": len(new_rows),
            "readings": list(reversed(new_rows)),
            "note": "Simulated values are for UI/testing only; they are not real sensor measurements and do not change pump state."}


@router.post("/plots/{pid}/readings")
async def readings(pid: str, body: ReadingIn, user: User = Depends(current_user)):
    """Record a reading; calibrated moisture observations pass through the Reality Gap Engine."""
    s = await _owned(pid, user)
    if s["status"] not in te.ACTIVE:
        raise HTTPException(400, "এই ফসলের জীবনচক্র শেষ হয়ে গেছে")
    measured_moisture = body.moisture_pct
    gap = None
    if measured_moisture is not None:
        # GrowthTwin represents soil water as plant-available water percent:
        # 100 means field capacity. Raw ADC values must be calibrated first.
        predicted = float(s["w_mm"] / s["awc"] * 100)
        gap = correct_state(
            predicted,
            measured_moisture,
            alpha=0.65,  # provisional; tune only on a separate calibration set
            minimum=0.0,
            maximum=160.0,
            quality=body.moisture_quality,
        ).as_dict()
        # Preserve the physical observation in the audit record, but only apply
        # the corrected estimate to the simulation state.
        measured_moisture = gap["estimated_value"]
        sentinel = s.setdefault("sentinel", {})
        sentinel["latest_reality_gap"] = gap
        history = sentinel.setdefault("reality_gap_history", [])
        history.append({"day": s["day"], **gap})
        del history[:-500]
    try:
        ev = te.apply_reading(s, body.ph, body.ec, measured_moisture, source=body.source)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if gap is not None:
        ev["payload"]["reality_gap"] = gap
        ev["payload"]["measured_moisture_pct"] = body.moisture_pct
        ev["payload"]["moisture_quality"] = body.moisture_quality
    await _persist(s, [ev])
    return {"plot": te.snapshot(s), "event": ev, "reality_gap": gap}


@router.get("/plots/{pid}/reality-gap")
async def reality_gap(pid: str, user: User = Depends(current_user)):
    """Return the latest correction and retained history for this plot."""
    s = await _owned(pid, user)
    sentinel = s.get("sentinel", {})
    return {
        "estimator_version": "reality-gap-v1",
        "latest": sentinel.get("latest_reality_gap"),
        "history": sentinel.get("reality_gap_history", []),
        "latest_device_reading": sentinel.get("latest_device_reading"),
        "device_reading_history": sentinel.get("device_reading_history", []),
        "sensor_configured": bool(sentinel.get("sensor_config")),
        "note": "Moisture values must be calibrated plant-available water percentages; raw ADC values are not accepted as calibrated moisture.",
    }


@router.post("/plots/{pid}/answers")
async def answers(pid: str, body: AnswersIn, user: User = Depends(current_user)):
    s = await _owned(pid, user)
    try:
        evs = te.answer(s, body.answers)
    except ValueError as e:
        raise HTTPException(400, str(e))
    await _persist(s, evs)
    return {"plot": te.snapshot(s), "notes": [e["payload"]["text_bn"] for e in evs]}


@router.post("/plots/{pid}/photo")
async def photo(pid: str, body: PhotoIn, user: User = Depends(current_user)):
    """Leaf photo (base64 JPEG/PNG/WebP, <= 2 MB) -> per-crop disease model. Advisory only; the image is NOT stored."""
    s = await _owned(pid, user)
    if s["status"] not in te.ACTIVE:
        raise HTTPException(400, "এই ফসলের জীবনচক্র শেষ হয়ে গেছে")
    raw = body.image_b64.split(",", 1)[-1]
    try:
        img = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(400, "ছবির ফরম্যাট সঠিক নয়")
    if len(img) > disease_models.MAX_IMAGE_BYTES or not disease_models.looks_like_image(img):
        raise HTTPException(400, "ছবি JPEG/PNG/WebP এবং ২ এমবির ছোট হতে হবে")
    pred = disease_models.predict(s["crop_id"], img)
    evs = te.record_photo(s, pred)
    await _persist(s, evs)
    return {"prediction": pred, "plot": te.snapshot(s), "notes": [e["payload"]["text_bn"] for e in evs if e["kind"] == "photo"]}


@router.get("/plots/{pid}/why/{key}")
async def why(pid: str, key: str, user: User = Depends(current_user)):
    """'Why?' button: the rule + numbers behind the latest alert or automatic action with this key."""
    s = await _owned(pid, user)
    for a in reversed(s["alerts"]):
        if a["key"] == key and a.get("why"):
            return {"key": key, "title_bn": a["title_bn"], "day": a["day"], **a["why"]}
    for e in await get_twin_store().get_events(pid, 200):           # newest first
        p = e["payload"]
        if e["kind"] in ("alert", "auto_action") and p.get("key") == key and p.get("why"):
            return {"key": key, "title_bn": p.get("title_bn") or p.get("text_bn", ""), "day": e["day"], **p["why"]}
    raise HTTPException(404, "ব্যাখ্যা পাওয়া যায়নি")


@router.get("/plots/{pid}/logs")
async def logs(pid: str, since_day: int = 0, user: User = Depends(current_user)):
    await _owned(pid, user)
    return await get_twin_store().get_logs(pid, since_day)


@router.get("/plots/{pid}/events")
async def events(pid: str, user: User = Depends(current_user)):
    await _owned(pid, user)
    return await get_twin_store().get_events(pid)


@router.get("/plots/{pid}/summary")
async def summary(pid: str, user: User = Depends(current_user)):
    s = await _owned(pid, user)
    text, source = await twin_summary.summarize(te.snapshot(s))
    return {"text": text, "source": source}


# ---------------------------------------------------------------- harvest history (feeds Section 1)
@router.get("/harvests")
async def harvests(user: User = Depends(current_user)):
    return await get_twin_store().list_harvests(user.id)


@router.get("/harvests/stats")
async def harvest_stats(user: User = Depends(current_user)):
    """This farmer's real average yield per decimal, per crop. Section 1 can compare it with the CSV yield range."""
    by = defaultdict(list)
    for r in await get_twin_store().list_harvests(user.id):
        if r.get("outcome", "harvested") != "harvested":
            continue
        by[r["crop_id"]].append(float(r["yield_kg_per_decimal"]))
    return [{"crop_id": k, "harvests": len(v), "avg_yield_kg_per_decimal": round(sum(v) / len(v), 2),
             "best": round(max(v), 2), "worst": round(min(v), 2)} for k, v in by.items()]


# ---------------------------------------------------------------- expert review of uncertain photos
@router.get("/expert/reviews")
async def expert_reviews(user: User = Depends(require_role("expert", "admin"))):
    out = []
    for s in await get_twin_store().list_review_plots():
        for r in s.get("review_pending", []):
            if r["status"] == "pending":
                out.append({"plot_id": s["id"], "review_id": r["id"], "crop": s["crop_id"], "day": r["day"],
                            "label": r.get("label"), "score": r.get("score"), "reason": r.get("reason")})
    return out


@router.post("/expert/reviews/{pid}/{rid}")
async def expert_review(pid: str, rid: str, body: ReviewIn, user: User = Depends(require_role("expert", "admin"))):
    s = await _owned(pid, user)
    try:
        ev = te.resolve_review(s, rid, body.verdict, body.label, body.note, user.id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    await _persist(s, [ev])
    return {"plot_id": pid, "review_id": rid, "status": "reviewed"}
