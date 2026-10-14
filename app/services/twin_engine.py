"""Section 2 engine: day-by-day digital twin of one plot (one crop, one field part).

Pure functions over a JSON-serialisable state dict (so it can live in Supabase jsonb). No LLM, no trained model in the
control loop: water balance + nutrient/pH/salinity/disease/temperature/light stress + rule-based controller.
Photo disease models (services/disease_models.py) are ADVISORY ONLY: they never switch the pump or dose inputs.
All coefficients are SAMPLE-VERIFY (see crop_stages.py).
"""
import random
import uuid
from datetime import date, timedelta

from ..data import crops
from . import crop_stages as cs
from . import twin_questions as tq
from . import weather_sim as wsim

M2_PER_DECIMAL = 40.47
DEATH_AFTER_READY = 15
HARVEST_WINDOW = 10
LOW_LEVEL = 38.0         # N/P/K level below which a dose is recommended
MANUAL_PUMP_MAX_DAYS = 2  # a remotely started pump stops by itself after this many days
AUTO_PUMP_MAX_DAYS = 7    # fail-safe for auto mode
ACTIVE = ("growing", "ready")
_BN = str.maketrans("0123456789.", "০১২৩৪৫৬৭৮৯.")


def bn(x, nd=0) -> str:
    return (f"{x:.{nd}f}" if nd else f"{round(x)}").translate(_BN)


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def _why(rule_bn: str, *facts) -> dict:
    """Explanation for the 'Why?' button: the rule that fired + the numbers it used."""
    return {"rule_bn": rule_bn, "facts": [{"label_bn": l, "value": v} for l, v in facts]}


def _migrate(s: dict) -> None:
    """Make states saved by older versions usable."""
    s["config"].setdefault("sms_enabled", False)
    s["config"].setdefault("phone", "")
    for k, v in (("pump_days", 0), ("pump_manual", False), ("review_pending", []), ("dark_days", 0)):
        s.setdefault(k, v)


def new_plot(user_id, name, crop_id, soil, area, ph=None, ec=None, start_date=None, seed=None, config=None) -> dict:
    crop = crops()[crop_id]
    if soil not in cs.AWC_MM:
        raise ValueError("অজানা মাটির ধরন")
    seed = seed if seed is not None else random.randrange(10**6)
    rnd = random.Random(f"init|{seed}")
    rice = cs.template_of(crop_id) == "rice"
    awc = cs.AWC_MM[soil]
    start = start_date or date.today().isoformat()
    s = {
        "id": uuid.uuid4().hex[:12], "user_id": user_id, "name": name or crop.name_bn, "crop_id": crop_id,
        "soil": soil, "area": float(area), "seed": seed, "start_date": start,
        "config": {"auto_irrigation": True, "auto_inputs": False, "sms_enabled": False, "phone": "", **(config or {})},
        "day": 0, "status": "growing", "end_reason": None, "result": None,
        "awc": awc, "w_mm": awc * (1.2 if rice else 0.8),
        "ph": float(ph if ph is not None else 6.3), "ec": float(ec if ec is not None else 1.0),
        "N": round(rnd.uniform(45, 65), 1), "P": round(rnd.uniform(40, 60), 1), "K": round(rnd.uniform(45, 65), 1),
        "health": 100.0, "pump_on": False, "pump_manual": False, "pump_days": 0, "wl_days": 0, "dark_days": 0,
        "dis": 0.0, "spray_until": -1, "protect_needed": False,
        "yf_num": 0.0, "yf_den": 0.0, "stand": 1.0, "last_rain": [],
        "totals": {"water_l": 0.0, "irrig_mm": 0.0, "urea_kg": 0.0, "tsp_kg": 0.0, "mop_kg": 0.0, "lime_kg": 0.0,
                   "rain_mm": 0.0, "sprays": 0},
        "last_fert_day": {"N": -99, "P": -99, "K": -99}, "last_lime_day": -99,
        "alert_last": {}, "alerts": [], "pending_actions": {}, "open_q": {}, "q_last": {}, "answers": {},
        "review_pending": [], "last_wx": None, "last_factors": None, "warnings": [],
    }
    m = date.fromisoformat(start).month
    if cs.season_of(m) not in crop.seasons:
        s["warnings"].append(f"{crop.name_bn} সাধারণত {' / '.join(cs.SEASON_BN[x] for x in crop.seasons)} মৌসুমের ফসল; "
                             f"এই সময়ে বপন করলে ঝুঁকি বাড়বে।")
    if soil not in crop.soils:
        s["warnings"].append(f"{crop.name_bn} এর জন্য এই মাটি আদর্শ নয়।")
    if s["ph"] < crop.ph_min or s["ph"] > crop.ph_max:
        s["warnings"].append(f"মাটির pH ({bn(s['ph'], 1)}) এই ফসলের আদর্শ সীমার ({bn(crop.ph_min, 1)}–{bn(crop.ph_max, 1)}) বাইরে।")
    return s


# ---------------------------------------------------------------- helpers
def _aw(s) -> float:
    return s["w_mm"] / s["awc"] * 100


def _today(s) -> date:
    return date.fromisoformat(s["start_date"]) + timedelta(days=s["day"])


def _alert(s, events, key, level, title, text, cooldown=7, action=None, why=None) -> None:
    last = s["alert_last"].get(key)
    if last is not None and s["day"] - last < cooldown:
        return
    s["alert_last"][key] = s["day"]
    payload = {"key": key, "level": level, "title_bn": title, "text_bn": text, "action": action, "why": why,
               "day": s["day"]}
    events.append({"day": s["day"], "kind": "alert", "payload": payload})
    s["alerts"] = (s["alerts"] + [payload])[-12:]
    if action:
        s["pending_actions"][key] = {**action, "key": key, "day": s["day"], "title_bn": title}


def _event(events, s, kind, **payload):
    ev = {"day": s["day"], "kind": kind, "payload": payload}
    events.append(ev)
    return ev


def _lime_dose(s, crop) -> float:
    target = min((crop.ph_min + crop.ph_max) / 2, crop.ph_min + 0.6)
    return round(max(0.0, (target - s["ph"]) * cs.LIME_KG_PER_DECIMAL_PER_PH * cs.SOIL_BUFFER[s["soil"]]), 1)


# ---------------------------------------------------------------- manual / auto actions
def apply_action(s, type_, **kw) -> dict:
    _migrate(s)
    if s["status"] not in ACTIVE:
        raise ValueError("এই ফসলের জীবনচক্র শেষ হয়ে গেছে")
    crop = crops()[s["crop_id"]]
    prof = cs.profile(crop.id, crop.water_need)
    events: list = []
    if type_ == "irrigate":
        need = max(0.0, (prof["target"] - _aw(s)) / 100 * s["awc"])
        mm = _clamp(float(kw.get("mm") or min(prof["pump_mm"], need)), 0, 60)
        s["w_mm"] = min(s["awc"] + 80, s["w_mm"] + mm)
        s["totals"]["irrig_mm"] += mm
        s["totals"]["water_l"] += mm * M2_PER_DECIMAL * s["area"]
        s["pending_actions"].pop("irrigate", None)
        return _event(events, s, "action", type="irrigate", mm=round(mm, 1), text_bn=f"{bn(mm)} মিমি সেচ দেওয়া হলো।")
    if type_ == "pump":
        on = bool(kw.get("on"))
        s["pump_on"], s["pump_manual"], s["pump_days"] = on, on, 0
        s["pending_actions"].pop("irrigate", None)
        txt = (f"পাম্প চালু করা হলো (লক্ষ্যমাত্রায় পৌঁছালে বা সর্বোচ্চ {bn(MANUAL_PUMP_MAX_DAYS)} দিন পর নিজে বন্ধ হবে)।"
               if on else "পাম্প বন্ধ করা হলো।")
        return _event(events, s, "action", type="pump", on=on, text_bn=txt)
    if type_ == "fertilize":
        n = kw.get("nutrient")
        if n not in cs.FERT:
            raise ValueError("অজানা সার")
        name, kg, gain = cs.FERT[n]
        s[n] = min(100.0, s[n] + gain)
        s["last_fert_day"][n] = s["day"]
        s["totals"][{"N": "urea_kg", "P": "tsp_kg", "K": "mop_kg"}[n]] += kg * s["area"]
        if n == "N":
            s["ph"] -= 0.03
        s["pending_actions"].pop(f"fert_{n}", None)
        return _event(events, s, "action", type="fertilize", nutrient=n,
                      text_bn=f"{name} {bn(kg * s['area'], 1)} কেজি দেওয়া হলো।")
    if type_ == "lime":
        d = _clamp(float(kw.get("kg_per_decimal") or _lime_dose(s, crop)), 0, 15)
        s["ph"] += d / (cs.LIME_KG_PER_DECIMAL_PER_PH * cs.SOIL_BUFFER[s["soil"]])
        s["last_lime_day"] = s["day"]
        s["totals"]["lime_kg"] += d * s["area"]
        s["pending_actions"].pop("lime", None)
        return _event(events, s, "action", type="lime", kg=round(d * s["area"], 1),
                      text_bn=f"চুন {bn(d * s['area'], 1)} কেজি দেওয়া হলো।")
    if type_ == "spray":
        s["dis"] = max(0.0, s["dis"] - 60)
        s["protect_needed"] = False
        s["spray_until"] = s["day"] + 7
        s["totals"]["sprays"] += 1
        s["pending_actions"].pop("spray", None)
        return _event(events, s, "action", type="spray", text_bn="রোগ/পোকা দমনের স্প্রে দেওয়া হলো (৭ দিন সুরক্ষা)।")
    if type_ == "harvest":
        if s["status"] != "ready":
            raise ValueError("ফসল এখনো কর্তনের উপযুক্ত নয়")
        return _finish(s, "harvested", "ফসল কাটা হয়েছে", events)
    raise ValueError("অজানা কাজ")


def _estimate(s, crop) -> dict:
    yf = s["yf_num"] / s["yf_den"] if s["yf_den"] > 0 else 1.0
    over_m = max(0.5, 1 - 0.02 * max(0, s["day"] - crop.duration_days))
    kg = crop.y[1] * s["area"] * yf * s["stand"] * over_m
    revenue, cost = kg * crop.p[1], crop.cost * s["area"]
    return {"yield_kg": round(kg), "revenue": round(revenue), "cost": round(cost), "profit": round(revenue - cost),
            "yield_factor": round(yf, 3)}


def _finish(s, outcome, reason, events) -> dict:
    crop = crops()[s["crop_id"]]
    est = _estimate(s, crop)
    if outcome == "dead":
        est.update(yield_kg=0, revenue=0, profit=-est["cost"])
    s.update(status=outcome, end_reason=reason, pump_on=False, pending_actions={}, open_q={})
    s["result"] = {**est, "outcome": outcome, "day": s["day"], "health": round(s["health"])}
    txt = (f"ফসল কাটা হলো। মোট ফলন প্রায় {bn(est['yield_kg'])} কেজি, আনুমানিক লাভ/লোকসান {bn(est['profit'])} টাকা।"
           if outcome == "harvested" else f"গাছ মারা গেছে। কারণ: {reason}।")
    return _event(events, s, "status", outcome=outcome, reason=reason, text_bn=txt)


def harvest_record(s) -> dict:
    """Row for harvest_records (feeds Section 1: what this farmer really got per decimal)."""
    r = s["result"]
    return {"user_id": s["user_id"], "plot_id": s["id"], "crop_id": s["crop_id"], "soil": s["soil"], "area": s["area"],
            "yield_kg": r["yield_kg"], "yield_kg_per_decimal": round(r["yield_kg"] / s["area"], 2),
            "revenue": r["revenue"], "cost": r["cost"], "profit": r["profit"], "days": r["day"],
            "health": r["health"], "start_date": s["start_date"],
            "outcome": r.get("outcome", "harvested"),      # harvested | dead (failures count: trust needs them)
            "source": "simulation"}                        # becomes "real" only when verified field data exists


# ---------------------------------------------------------------- one simulated day
def step(s) -> tuple[dict, list]:
    _migrate(s)
    crop = crops()[s["crop_id"]]
    prof = cs.profile(crop.id, crop.water_need)
    tmpl = cs.template_of(crop.id)
    rice = tmpl == "rice"
    cfg = s["config"]
    events: list = []

    s["day"] += 1
    d = s["day"]
    today = _today(s)
    wx = wsim.day_weather(s["seed"], today)
    fc = wsim.forecast(s["seed"], today, 3)
    idx, st = cs.stage_at(crop.id, d, crop.duration_days)
    aw = _aw(s)
    rain_soon = sum(f["rain_mm"] * f["prob"] / 100 for f in fc[:2])
    storm_soon = any(f["rain_mm"] >= 60 and f["prob"] >= 50 for f in fc[:2])
    emergency = aw < prof["emergency"]
    lo, hi, clo, chi = cs.TEMP[tmpl]

    pa = s["pending_actions"]                       # prune stale pending actions
    if aw >= prof["trigger"] or s["pump_on"]:
        pa.pop("irrigate", None)
    for n in cs.FERT:
        if s[n] >= LOW_LEVEL:
            pa.pop(f"fert_{n}", None)
    if s["ph"] >= crop.ph_min - 0.15:
        pa.pop("lime", None)
    if s["dis"] < 30 and not s["protect_needed"]:
        pa.pop("spray", None)

    # ---- controller: irrigation (hard rules + hysteresis) ----
    if st.irrigate and s["status"] == "growing":
        if storm_soon and s["pump_on"] and not emergency:
            s["pump_on"], s["pump_days"] = False, 0
            _event(events, s, "auto_action", key="pump_off", type="pump_off", reason="storm",
                   text_bn="প্রবল বৃষ্টির পূর্বাভাসে পাম্প বন্ধ করা হলো।",
                   why=_why("প্রবল বৃষ্টির (৬০ মিমি+) পূর্বাভাস থাকলে, জরুরি না হলে পাম্প বন্ধ থাকে",
                            ("আজ/কাল বৃষ্টির পূর্বাভাস", f"{bn(max(f['rain_mm'] for f in fc[:2]))} মিমি"),
                            ("মাটির আর্দ্রতা", f"{bn(aw)}%")))
        if cfg["auto_irrigation"]:
            if not s["pump_on"]:
                if emergency:
                    s["pump_on"], s["pump_manual"], s["pump_days"] = True, False, 0
                    why = _why("আর্দ্রতা জরুরি সীমার নিচে নামলে বৃষ্টির পূর্বাভাস থাকলেও পাম্প চালু হয়",
                               ("মাটির আর্দ্রতা", f"{bn(aw)}%"), ("জরুরি সীমা", f"{bn(prof['emergency'])}%"),
                               ("২ দিনে সম্ভাব্য বৃষ্টি", f"{bn(rain_soon)} মিমি"))
                    _event(events, s, "auto_action", key="pump_on", type="pump_on", reason="emergency",
                           text_bn=f"জরুরি: মাটির আর্দ্রতা {bn(aw)}% এ নেমেছে, পাম্প চালু হলো।", why=why)
                    _alert(s, events, "emergency", "warn", "জরুরি স্বয়ংক্রিয় সেচ",
                           f"আর্দ্রতা {bn(aw)}% (সীমা {bn(prof['emergency'])}%), পাম্প চালু; লক্ষ্যমাত্রায় পৌঁছালে বন্ধ হবে।", 3, why=why)
                elif aw < prof["trigger"]:
                    if rain_soon >= 10 or storm_soon:
                        _alert(s, events, "irrigation_skipped", "info", "বৃষ্টির পূর্বাভাসে সেচ স্থগিত",
                               f"আগামী ২ দিনে প্রায় {bn(rain_soon)} মিমি বৃষ্টির সম্ভাবনা, তাই এখন সেচ দিচ্ছি না।", 3,
                               why=_why("আর্দ্রতা সেচের সীমার নিচে, কিন্তু ২ দিনে ১০ মিমি+ বৃষ্টির সম্ভাবনা থাকলে সেচ স্থগিত থাকে",
                                        ("মাটির আর্দ্রতা", f"{bn(aw)}%"), ("সেচের সীমা", f"{bn(prof['trigger'])}%"),
                                        ("২ দিনে সম্ভাব্য বৃষ্টি", f"{bn(rain_soon)} মিমি")))
                    else:
                        s["pump_on"], s["pump_manual"], s["pump_days"] = True, False, 0
                        _event(events, s, "auto_action", key="pump_on", type="pump_on", reason="schedule",
                               text_bn=f"আর্দ্রতা {bn(aw)}%, নির্ধারিত সীমার নিচে; পাম্প চালু হলো।",
                               why=_why("আর্দ্রতা সেচের সীমার নিচে নামলে এবং কাছাকাছি বৃষ্টির সম্ভাবনা কম থাকলে পাম্প চালু হয়",
                                        ("মাটির আর্দ্রতা", f"{bn(aw)}%"), ("সেচের সীমা", f"{bn(prof['trigger'])}%"),
                                        ("২ দিনে সম্ভাব্য বৃষ্টি", f"{bn(rain_soon)} মিমি")))
        elif not s["pump_on"] and aw < prof["trigger"]:
            _alert(s, events, "irrigate", "critical" if emergency else "action",
                   "জরুরি সেচ দরকার" if emergency else "সেচ দিতে হবে",
                   f"মাটির আর্দ্রতা {bn(aw)}%।" + (" গাছ শুকিয়ে যাওয়ার ঝুঁকি।" if emergency else ""), 3, {"type": "irrigate"},
                   why=_why("আর্দ্রতা সেচের সীমার নিচে নামলে সেচ প্রস্তাব করা হয় (স্বয়ংক্রিয় সেচ বন্ধ আছে)",
                            ("মাটির আর্দ্রতা", f"{bn(aw)}%"), ("সেচের সীমা", f"{bn(prof['trigger'])}%")))
    if not st.irrigate:
        s["pump_on"] = False

    # ---- water balance ----
    rain = wx["rain_mm"]
    eff_rain = rain if rain < 40 else 40 + (rain - 40) * 0.5
    etc = wx["et0"] * st.kc
    irr = 0.0
    if s["pump_on"]:      # deliver what ENDS the day at target (after today's ET and rain), capped by pump capacity
        need = max(0.0, prof["target"] / 100 * s["awc"] - (s["w_mm"] + eff_rain - etc))
        irr = min(prof["pump_mm"], need)
        s["totals"]["irrig_mm"] += irr
        s["totals"]["water_l"] += irr * M2_PER_DECIMAL * s["area"]
    s["w_mm"] = max(0.0, s["w_mm"] + eff_rain + irr - etc)
    s["w_mm"] -= max(0.0, s["w_mm"] - s["awc"]) * (0.08 if rice else 0.5)
    s["w_mm"] = min(s["w_mm"], s["awc"] + 80)
    aw = _aw(s)
    s["totals"]["rain_mm"] += rain
    s["last_rain"] = (s["last_rain"] + [rain])[-3:]
    if s["pump_on"] and aw >= prof["target"] - 0.05:
        s["pump_on"], s["pump_days"] = False, 0
        _event(events, s, "auto_action", key="pump_off", type="pump_off", reason="target",
               text_bn=f"আর্দ্রতা {bn(aw)}% এ পৌঁছেছে, পাম্প বন্ধ হলো।",
               why=_why("আর্দ্রতা লক্ষ্যমাত্রায় পৌঁছালে পাম্প বন্ধ হয় (হিস্টেরেসিস)",
                        ("মাটির আর্দ্রতা", f"{bn(aw)}%"), ("বন্ধের লক্ষ্য", f"{bn(prof['target'])}%")))
    elif s["pump_on"]:
        s["pump_days"] += 1
        limit = MANUAL_PUMP_MAX_DAYS if s["pump_manual"] else AUTO_PUMP_MAX_DAYS
        if s["pump_days"] >= limit:
            s["pump_on"] = False
            why = _why("পাম্প সর্বোচ্চ নির্ধারিত দিনের বেশি চলতে পারে না (সুরক্ষা সীমা)",
                       ("টানা চলার দিন", bn(s["pump_days"])), ("সীমা", f"{bn(limit)} দিন"), ("মাটির আর্দ্রতা", f"{bn(aw)}%"))
            s["pump_days"] = 0
            _event(events, s, "auto_action", key="pump_failsafe", type="pump_off", reason="failsafe",
                   text_bn=f"নিরাপত্তা সীমা ({bn(limit)} দিন) পার হওয়ায় পাম্প বন্ধ হলো। পাম্প/সেন্সর ঠিক আছে কি দেখুন।", why=why)
            _alert(s, events, "pump_failsafe", "warn", "পাম্প নিরাপত্তায় বন্ধ হয়েছে",
                   "লক্ষ্য আর্দ্রতায় না পৌঁছেই পাম্প সময়সীমায় বন্ধ হয়েছে। পাম্প, নল ও সেন্সর পরীক্ষা করুন।", 5, why=why)
    else:
        s["pump_days"] = 0

    # ---- nutrients, pH, salinity ----
    if s["status"] == "growing":
        s["N"] -= 0.45 * st.demand
        s["P"] -= 0.20 * st.demand
        s["K"] -= 0.30 * st.demand
    if rain > 40:
        s["N"] -= 3 if rice else 8
        s["K"] -= 3
    for n in cs.FERT:
        s[n] = _clamp(s[n], 0.0, 100.0)
    if rain > 20:
        s["ph"] -= 0.01
    s["ec"] = max(0.3, s["ec"] + irr * 0.002 + (0.005 if rain == 0 else 0) - rain * 0.006 - max(0.0, s["ec"] - 0.8) * 0.012)

    # ---- disease risk ----
    if wx["rh"] >= 85 and 20 <= wx["tmean"] <= 32 and d > s["spray_until"]:
        s["dis"] = min(100.0, s["dis"] + 12)
    else:
        s["dis"] = max(0.0, s["dis"] - (10 if d <= s["spray_until"] else 6))

    # ---- stress factors (1 = no stress) ----
    sens = st.sens
    wf = _clamp((aw - prof["wilt"]) / (prof["stress"] - prof["wilt"]), 0.1, 1.0)
    if rice:
        s["wl_days"] = 0
    else:
        s["wl_days"] = s["wl_days"] + 1 if aw > 115 else max(0, s["wl_days"] - 1)
        wf *= max(0.5, 1 - 0.12 * max(0, s["wl_days"] - 1))
    f_water = _clamp(1 - (1 - wf) * min(sens, 1.5), 0.1, 1.0)
    lv = lambda x: 1.0 if x >= 30 else 0.4 + 0.6 * x / 30
    f_nut = min(lv(s["N"]), lv(s["P"]), lv(s["K"])) if idx >= 1 else 1.0
    if s["ph"] < crop.ph_min:
        f_ph = max(0.4, 1 - (crop.ph_min - s["ph"]) * 0.25)
    elif s["ph"] > crop.ph_max:
        f_ph = max(0.4, 1 - (s["ph"] - crop.ph_max) * 0.25)
    else:
        f_ph = 1.0
    t = wx["tmean"]
    if lo <= t <= hi:
        tf = 1.0
    elif t < lo:
        tf = 1 - 0.6 * min(1, (lo - t) / (lo - clo))
    else:
        tf = 1 - 0.6 * min(1, (t - hi) / (chi - hi))
    f_temp = _clamp(1 - (1 - tf) * min(sens, 2.0), 0.2, 1.0)
    tol = cs.SALT_TOL.get(crop.id, 3.0)
    f_salt = 1.0 if s["ec"] <= tol else max(0.4, 1 - 0.12 * (s["ec"] - tol))
    f_dis = 1.0 if s["dis"] < 60 else max(0.6, 1 - (s["dis"] - 60) / 100)
    if s["protect_needed"]:
        f_dis *= 0.88
    need_sun, sun = cs.LIGHT_NEED[tmpl], wx["sun_h"]
    lf = 1.0 if sun >= need_sun else 0.75 + 0.25 * sun / need_sun
    f_light = _clamp(1 - (1 - lf) * min(sens, 1.5), 0.5, 1.0)
    s["dark_days"] = s["dark_days"] + 1 if sun < need_sun * 0.5 else 0
    factors = {"water": f_water, "nutrient": f_nut, "ph": f_ph, "temp": f_temp, "salt": f_salt, "disease": f_dis,
               "light": f_light}
    s_all = 1.0
    for v in factors.values():
        s_all *= v
    s["last_factors"] = {k: round(v, 3) for k, v in factors.items()}
    if s_all >= 0.9:
        s["health"] = min(100.0, s["health"] + 1)
    else:
        s["health"] -= (0.9 - s_all) * 12
    if s["status"] == "growing":
        s["yf_num"] += sens * s_all
        s["yf_den"] += sens

    # ---- alerts / recommendations ----
    if storm_soon:
        _alert(s, events, "storm", "warn", "প্রবল বৃষ্টির পূর্বাভাস",
               "সার ও সেচ স্থগিত রাখুন, জমির নিকাশ ঠিক আছে কি না দেখুন।", 3,
               why=_why("আগামী ২ দিনে ৬০ মিমি+ বৃষ্টির ৫০%+ সম্ভাবনা থাকলে সতর্কতা আসে",
                        ("সর্বোচ্চ পূর্বাভাস", f"{bn(max(f['rain_mm'] for f in fc[:2]))} মিমি")))
    heat_hot = max(f["tmax"] for f in fc[:2])
    if heat_hot >= hi + 5:
        _alert(s, events, "heat_soon", "info", "গরমের পূর্বাভাস",
               f"আগামী ২ দিনে সর্বোচ্চ তাপমাত্রা প্রায় {bn(heat_hot)}°সে। সকাল/সন্ধ্যায় সেচ দেওয়া ভালো।", 4,
               why=_why("পূর্বাভাসের সর্বোচ্চ তাপমাত্রা ফসলের আদর্শ সীমার ৫° উপরে গেলে সতর্কতা আসে",
                        ("পূর্বাভাসের সর্বোচ্চ", f"{bn(heat_hot)}°সে"), ("আদর্শ সর্বোচ্চ", f"{bn(hi)}°সে")))
    if s["dark_days"] >= 4:
        _alert(s, events, "lowlight", "info", "টানা মেঘলা দিন",
               "কয়েক দিন ধরে রোদ কম। সার ও সেচ কমান, রোগের দিকে নজর রাখুন।", 10,
               why=_why("টানা ৪ দিন রোদের ঘণ্টা ফসলের প্রয়োজনের অর্ধেকের কম থাকলে সতর্কতা আসে",
                        ("আজকের রোদ", f"{bn(sun, 1)} ঘণ্টা"), ("প্রয়োজন", f"{bn(need_sun, 1)} ঘণ্টা")))
    if s["status"] == "growing" and st.irrigate:
        for n, (fname, kg, _g) in cs.FERT.items():
            if idx >= 1 and st.demand >= 0.5 and s[n] < LOW_LEVEL and d - s["last_fert_day"][n] >= 10:
                if rain_soon >= 15:
                    _alert(s, events, "fert_wait", "info", "বৃষ্টির আগে সার নয়",
                           "প্রবল বৃষ্টিতে সার ধুয়ে যাবে; বৃষ্টির পর দিন।", 4,
                           why=_why("২ দিনে ১৫ মিমি+ বৃষ্টির সম্ভাবনা থাকলে সার দেওয়া পিছিয়ে দেওয়া হয়",
                                    ("২ দিনে সম্ভাব্য বৃষ্টি", f"{bn(rain_soon)} মিমি")))
                elif cfg["auto_inputs"]:
                    ev = apply_action(s, "fertilize", nutrient=n)
                    ev["kind"], ev["payload"]["key"] = "auto_action", f"auto_fert_{n}"
                    ev["payload"]["why"] = _why(f"{n} এর মাত্রা {bn(LOW_LEVEL)}% এর নিচে নামলে সার দেওয়া হয় (স্বয়ংক্রিয় মোড)",
                                                (f"{n} এর মাত্রা", f"{bn(s[n])}%"))
                    events.append(ev)
                else:
                    _alert(s, events, f"fert_{n}", "action", f"{fname} সার দিতে হবে",
                           f"{n} এর মাত্রা কমে {bn(s[n])}% হয়েছে। প্রস্তাবিত: {fname} {bn(kg * s['area'], 1)} কেজি।", 5,
                           {"type": "fertilize", "nutrient": n},
                           why=_why(f"{n} এর মাত্রা {bn(LOW_LEVEL)}% এর নিচে নামলে ও গাছের চাহিদা থাকলে সার প্রস্তাব হয়",
                                    (f"{n} এর মাত্রা", f"{bn(s[n])}%"), ("পর্যায়", st.name_bn),
                                    ("শেষ প্রয়োগের পর", f"{bn(d - s['last_fert_day'][n]) if s['last_fert_day'][n] >= 0 else '—'} দিন")))
        if s["ph"] < crop.ph_min - 0.15 and d - s["last_lime_day"] >= 20 and idx < len(cs.stages(crop.id)) - 1:
            dose = _lime_dose(s, crop)
            if cfg["auto_inputs"]:
                ev = apply_action(s, "lime")
                ev["kind"], ev["payload"]["key"] = "auto_action", "auto_lime"
                ev["payload"]["why"] = _why("pH ফসলের ন্যূনতমের চেয়ে ০.১৫ বেশি কমলে চুন দেওয়া হয় (স্বয়ংক্রিয় মোড)",
                                            ("মাটির pH", bn(s["ph"], 1)), ("ন্যূনতম", bn(crop.ph_min, 1)))
                events.append(ev)
            else:
                _alert(s, events, "lime", "action", "চুন দিতে হবে",
                       f"মাটির pH {bn(s['ph'], 1)}, ফসলের জন্য কমপক্ষে {bn(crop.ph_min, 1)} দরকার। "
                       f"প্রস্তাবিত চুন: {bn(dose * s['area'], 1)} কেজি।", 10, {"type": "lime"},
                       why=_why("pH ফসলের ন্যূনতম সীমার ০.১৫ নিচে নামলে চুন প্রস্তাব হয়",
                                ("মাটির pH", bn(s["ph"], 1)), ("ফসলের ন্যূনতম", bn(crop.ph_min, 1)),
                                ("মাটির ধরন", s["soil"])))
        elif s["ph"] > crop.ph_max + 0.5:
            _alert(s, events, "alkaline", "info", "মাটি ক্ষারীয়",
                   f"pH {bn(s['ph'], 1)} বেশি। জৈব সার/জিপসাম ব্যবহারের পরামর্শ নিন।", 30)
        if (s["dis"] >= 60 or s["protect_needed"]) and d > s["spray_until"]:
            why = _why("রোগের ঝুঁকি ৬০ এর বেশি হলে (বা রোগ/পোকা নিশ্চিত হলে) স্প্রে প্রস্তাব হয়",
                       ("রোগের ঝুঁকি", f"{bn(s['dis'])}%"), ("আজকের আর্দ্রতা", f"{bn(wx['rh'])}%"),
                       ("আজকের তাপমাত্রা", f"{bn(wx['tmean'], 1)}°সে"), ("নিশ্চিত সমস্যা", "হ্যাঁ" if s["protect_needed"] else "না"))
            if cfg["auto_inputs"]:
                ev = apply_action(s, "spray")
                ev["kind"], ev["payload"]["key"], ev["payload"]["why"] = "auto_action", "auto_spray", why
                events.append(ev)
            else:
                _alert(s, events, "spray", "action", "রোগ/পোকা দমন দরকার",
                       "আর্দ্র ও গরম আবহাওয়ায় রোগের ঝুঁকি বেড়েছে। কৃষি অফিসের পরামর্শে স্প্রে করুন।", 7, {"type": "spray"}, why=why)
    if f_temp < 0.75:
        _alert(s, events, "temp", "warn", "তাপমাত্রার চাপ",
               ("গরম বেশি" if t > hi else "ঠান্ডা বেশি") + f" ({bn(t, 1)}°সে)। সেচ/ছায়া/আবরণের ব্যবস্থা ভাবুন।", 5,
               why=_why("দৈনিক গড় তাপমাত্রা ফসলের আদর্শ সীমার বাইরে গেলে সতর্কতা আসে",
                        ("আজকের গড়", f"{bn(t, 1)}°সে"), ("আদর্শ সীমা", f"{bn(lo)}–{bn(hi)}°সে")))
    if s["ec"] > tol:
        _alert(s, events, "salt", "warn", "মাটিতে লবণাক্ততা বেশি",
               f"EC {bn(s['ec'], 1)} dS/m (সহনসীমা {bn(tol, 1)}); মিঠা পানি দিয়ে ধুয়ে দিন।", 10,
               why=_why("মাটির EC ফসলের সহনসীমা ছাড়ালে সতর্কতা আসে", ("EC", f"{bn(s['ec'], 1)} dS/m"),
                        ("সহনসীমা", f"{bn(tol, 1)} dS/m")))
    if s["wl_days"] >= 2:
        _alert(s, events, "waterlog", "warn", "জলাবদ্ধতা", "জমিতে পানি জমে আছে। নালা কেটে নিকাশ করুন।", 5,
               why=_why("মাটির আর্দ্রতা ১১৫% এর বেশি টানা ২ দিন থাকলে জলাবদ্ধতার সতর্কতা আসে",
                        ("মাটির আর্দ্রতা", f"{bn(aw)}%"), ("টানা দিন", bn(s["wl_days"]))))

    # ---- questions (max 3 open at once) ----
    ctx = {"crop": crop, "idx": idx, "st": st, "stages": cs.stages(crop.id), "aw": aw, "wx": wx, "rice": rice, "day": d}
    tq.expire(s)
    for qid in tq.raise_due(s, ctx):
        _event(events, s, "question", id=qid, text_bn=tq.BY_ID[qid].text_bn)

    # ---- lifecycle transitions ----
    s["last_wx"] = wx
    if s["health"] <= 0:
        worst = min(factors, key=factors.get)
        cause = {"water": "জলাবদ্ধতা" if aw > 100 else "পানির অভাব (খরা)", "nutrient": "পুষ্টির অভাব",
                 "ph": "মাটির pH অনুপযোগী", "temp": "চরম তাপমাত্রা", "salt": "লবণাক্ততা",
                 "disease": "রোগ/পোকার আক্রমণ", "light": "আলোর অভাব"}[worst]
        _finish(s, "dead", cause, events)
    elif s["status"] == "growing" and d >= crop.duration_days:
        s["status"] = "ready"
        s["pump_on"] = False
        _alert(s, events, "harvest", "action", "ফসল কাটার সময় হয়েছে",
               f"ফসল পরিপক্ব। {bn(HARVEST_WINDOW)} দিনের মধ্যে কাটুন, নইলে ফলন কমবে।", 99, {"type": "harvest"},
               why=_why("গাছের বয়স ফসলের জীবনকালের সমান হলে কর্তনের সময় হয়", ("বয়স", f"{bn(d)} দিন"),
                        ("জীবনকাল", f"{bn(crop.duration_days)} দিন")))
    elif s["status"] == "ready" and d >= crop.duration_days + DEATH_AFTER_READY:
        _finish(s, "dead", "কর্তনের সময় পার হয়ে গিয়ে স্বাভাবিক মৃত্যু", events)

    log = {
        "day": d, "date": today.isoformat(), "stage": st.id, "stage_bn": st.name_bn, "status": s["status"],
        "wx": wx, "aw": round(aw, 1), "w_mm": round(s["w_mm"], 1), "ph": round(s["ph"], 2), "ec": round(s["ec"], 2),
        "N": round(s["N"], 1), "P": round(s["P"], 1), "K": round(s["K"], 1), "dis": round(s["dis"]),
        "pump_on": s["pump_on"], "irrigation_mm": round(irr, 1), "health": round(s["health"], 1),
        "factors": s["last_factors"], "est_yield_kg": _estimate(s, crop)["yield_kg"] if s["status"] != "dead" else 0,
    }
    return log, events


def advance(s, days: int, stop_on_alert=True, auto_harvest=False) -> dict:
    logs, events, stopped = [], [], None
    for _ in range(days):
        if s["status"] not in ACTIVE:
            break
        if s["status"] == "ready" and auto_harvest:
            events.append(apply_action(s, "harvest"))
            break
        log, ev = step(s)
        logs.append(log)
        events.extend(ev)
        urgent = [e for e in ev if e["kind"] == "alert" and e["payload"]["level"] in ("action", "critical")]
        if s["status"] == "ready" and auto_harvest:
            continue
        if stop_on_alert and urgent:
            stopped = urgent[0]["payload"]["title_bn"]
            break
    if s["status"] == "ready" and auto_harvest:
        events.append(apply_action(s, "harvest"))
    return {"logs": logs, "events": events, "stopped_for": stopped}


# ---------------------------------------------------------------- answers, photos, expert review
def answer(s, answers: dict) -> list:
    _migrate(s)
    events: list = []
    crop = crops()[s["crop_id"]]
    idx, st = cs.stage_at(crop.id, max(s["day"], 1), crop.duration_days)
    ctx = {"crop": crop, "idx": idx, "st": st, "stages": cs.stages(crop.id), "aw": _aw(s),
           "wx": s["last_wx"] or {}, "rice": cs.template_of(crop.id) == "rice", "day": s["day"]}
    for qid, val in answers.items():
        q = tq.BY_ID.get(qid)
        if not q or qid not in s["open_q"]:
            continue
        if val not in [v for v, _ in q.options]:
            raise ValueError("ভুল উত্তর")
        note = q.apply(s, val, ctx)
        s["answers"][qid] = {"value": val, "day": s["day"]}
        del s["open_q"][qid]
        _event(events, s, "answer", id=qid, value=val, text_bn=note)
    return events


def apply_reading(s, ph=None, ec=None, moisture_pct=None, source="manual") -> dict:
    """Real measurement (pH strip, EC meter, soil-moisture probe/ESP32) replaces the simulated hidden state.
    moisture_pct is plant-available water in % (same scale as soil_now.aw; 100 = field capacity)."""
    _migrate(s)
    got = {}
    if ph is not None:
        s["ph"] = round(_clamp(float(ph), 3.5, 9.5), 2)
        got["ph"] = s["ph"]
    if ec is not None:
        s["ec"] = round(_clamp(float(ec), 0, 20), 2)
        got["ec"] = s["ec"]
    if moisture_pct is not None:
        s["w_mm"] = _clamp(float(moisture_pct), 0, 160) / 100 * s["awc"]
        got["aw"] = round(_aw(s), 1)
    if not got:
        raise ValueError("কোনো মান দেওয়া হয়নি")
    ev: list = []
    parts = []
    if "ph" in got:
        parts.append(f"pH {bn(got['ph'], 1)}")
    if "ec" in got:
        parts.append(f"লবণাক্ততা {bn(got['ec'], 1)} dS/m")
    if "aw" in got:
        parts.append(f"মাটির আর্দ্রতা {bn(got['aw'])}%")
    _event(ev, s, "reading", source=source, values=got, text_bn="মাপা মান নেওয়া হয়েছে: " + ", ".join(parts) + "।")
    return ev[0]


def _open_question(s, events, qid):
    if qid not in s["open_q"]:
        s["open_q"][qid] = {"day": s["day"]}
        s["q_last"][qid] = s["day"]
        _event(events, s, "question", id=qid, text_bn=tq.BY_ID[qid].text_bn)


def record_photo(s, pred: dict) -> list:
    """Apply a disease-model result. ADVISORY ONLY: raises a warning, opens a confirmation question and may queue an
    expert review. It never changes disease risk, the pump or any dose."""
    _migrate(s)
    events: list = []
    status = pred["status"]
    if status == "no_model":
        _event(events, s, "photo", status=status,
               text_bn="এই ফসলের জন্য ছবি-ভিত্তিক রোগ শনাক্তকারী মডেল এখনো নেই। নিচের প্রশ্নের উত্তর দিয়ে অবস্থা জানান।")
        _open_question(s, events, "leaf_spots")
        return events
    item = {"id": uuid.uuid4().hex[:8], "day": s["day"], "label": pred.get("label"), "label_bn": pred.get("label_bn"),
            "score": pred.get("score"), "status": "pending"}
    if status == "unknown":
        item["reason"] = "unknown"
        s["review_pending"] = (s["review_pending"] + [item])[-20:]
        _event(events, s, "photo", status=status, review_id=item["id"],
               text_bn="ছবি থেকে নিশ্চিত হওয়া গেল না। বিশেষজ্ঞের কাছে পাঠানো হয়েছে; আরও স্পষ্ট ছবি তুলতে পারেন।")
        _open_question(s, events, "leaf_spots")
        return events
    pct = bn(pred["score"] * 100)
    if pred.get("healthy"):
        _event(events, s, "photo", status=status, label=pred["label"], score=pred["score"],
               text_bn=f"ছবিতে গাছ সুস্থ মনে হচ্ছে ({pct}% নিশ্চয়তা)।")
        return events
    if pred.get("needs_review"):
        item["reason"] = "low_confidence"
        s["review_pending"] = (s["review_pending"] + [item])[-20:]
    _event(events, s, "photo", status=status, label=pred["label"], score=pred["score"], review_id=item["id"] if pred.get("needs_review") else None,
           text_bn=f"ছবি অনুযায়ী সম্ভাব্য সমস্যা: {pred.get('label_bn') or pred['label']} ({pct}% নিশ্চয়তা)। এটি শুধু পরামর্শ।")
    _alert(s, events, "photo_disease", "warn", f"ছবিতে সম্ভাব্য রোগ: {pred.get('label_bn') or pred['label']}",
           f"মডেলের নিশ্চয়তা {pct}%। নিশ্চিত হতে প্রশ্নের উত্তর দিন বা কৃষি অফিসের পরামর্শ নিন।", 3,
           why=_why("ছবির মডেল রোগের লক্ষণ ধরলে সতর্কতা আসে; মডেল শুধু পরামর্শ দেয়, নিজে কোনো স্প্রে/সেচ চালায় না",
                    ("সম্ভাব্য রোগ", pred.get("label_bn") or pred["label"]), ("নিশ্চয়তা", f"{pct}%"),
                    ("বিশেষজ্ঞ রিভিউ", "পাঠানো হয়েছে" if pred.get("needs_review") else "দরকার নেই")))
    _open_question(s, events, "leaf_spots")
    return events


def resolve_review(s, review_id: str, verdict: str, label: str, note: str, by: str) -> dict:
    _migrate(s)
    item = next((r for r in s["review_pending"] if r["id"] == review_id and r["status"] == "pending"), None)
    if not item:
        raise ValueError("রিভিউ পাওয়া যায়নি")
    item.update(status="reviewed", verdict=verdict, expert_label=label, note=note, by=by)
    if verdict == "disease":
        s["protect_needed"] = True       # expert-confirmed, so the normal spray recommendation may now fire
    elif verdict == "healthy":
        s["dis"] = max(0.0, s["dis"] - 25)
        s["protect_needed"] = False
    events: list = []
    return _event(events, s, "review", review_id=review_id, verdict=verdict, label=label,
                  text_bn={"disease": f"বিশেষজ্ঞ নিশ্চিত করেছেন: {label or 'রোগ আছে'}।",
                           "healthy": "বিশেষজ্ঞের মতে গাছ সুস্থ।", "unsure": "বিশেষজ্ঞ নিশ্চিত হতে পারেননি; জমি সরেজমিনে দেখা দরকার।"}[verdict])


# ---------------------------------------------------------------- public view
def snapshot(s) -> dict:
    _migrate(s)
    crop = crops()[s["crop_id"]]
    prof = cs.profile(crop.id, crop.water_need)
    idx, st = cs.stage_at(crop.id, max(s["day"], 0), crop.duration_days)
    st_list, prev = [], 0
    for x in cs.stages(crop.id):
        end = round(x.end * crop.duration_days)
        st_list.append({"id": x.id, "name_bn": x.name_bn, "start_day": prev, "end_day": end})
        prev = end
    fc = wsim.forecast(s["seed"], _today(s) + timedelta(days=1), 5) if s["status"] in ACTIVE else []
    cfg = s["config"]
    phone = cfg.get("phone") or ""
    return {
        "id": s["id"], "name": s["name"], "crop": {"id": crop.id, "name_bn": crop.name_bn},
        "soil": s["soil"], "area": s["area"], "day": s["day"], "date": _today(s).isoformat(),
        "duration": crop.duration_days, "status": s["status"], "end_reason": s["end_reason"], "result": s["result"],
        "stage": {"id": st.id, "name_bn": st.name_bn, "idx": idx}, "stages": st_list,
        "health": round(s["health"]), "pump_on": s["pump_on"],
        "pump": {"on": s["pump_on"], "manual": s["pump_manual"], "days_running": s["pump_days"],
                 "max_days": MANUAL_PUMP_MAX_DAYS if s["pump_manual"] else AUTO_PUMP_MAX_DAYS},
        "config": {"auto_irrigation": cfg["auto_irrigation"], "auto_inputs": cfg["auto_inputs"],
                   "sms_enabled": cfg["sms_enabled"], "phone_set": bool(phone),
                   "phone_masked": (phone[:4] + "****" + phone[-2:]) if phone else ""},
        "warnings": s["warnings"],
        "soil_now": {"aw": round(_aw(s)), "ph": round(s["ph"], 2), "ec": round(s["ec"], 2), "N": round(s["N"]),
                     "P": round(s["P"]), "K": round(s["K"]), "disease_risk": round(s["dis"])},
        "thresholds": {"irrigate_below": round(prof["trigger"]), "emergency_below": round(prof["emergency"]),
                       "stop_at": round(prof["target"]), "ph_min": crop.ph_min, "ph_max": crop.ph_max,
                       "ec_tol": cs.SALT_TOL.get(crop.id, 3.0), "low_level": LOW_LEVEL,
                       "light_need_h": cs.LIGHT_NEED[cs.template_of(crop.id)]},
        "weather": s["last_wx"] or wsim.day_weather(s["seed"], _today(s)), "forecast": fc, "factors": s["last_factors"], "totals": s["totals"],
        "estimate": _estimate(s, crop) if s["status"] in ACTIVE else None,
        "pending_actions": list(s["pending_actions"].values()), "alerts": s["alerts"][-8:][::-1],
        "questions": [tq.public(tq.BY_ID[q], v["day"]) for q, v in s["open_q"].items()],
        "photo_reviews": [r for r in s["review_pending"] if r["status"] == "pending"],
    }
