"""Daily 'what should I do now' advice for one plot, built from the public snapshot.

Pure function: takes the dict returned by twin_engine.snapshot() and returns a list of advice items,
most urgent first. Each item may carry a one-click `action` that the UI posts to /twin/plots/{id}/action.
All thresholds come from the snapshot (crop profile), so nothing here is hard-coded per crop.
Numbers used only here (rain/disease cut-offs) are SAMPLE-VERIFY: confirm with BRRI / DAE before field use.
"""
from __future__ import annotations

RAIN_SOON_MM = 10        # expected rain (prob-weighted) in the next 2 days that makes us delay irrigation
HEAVY_RAIN_MM = 40       # a single forecast day at/above this = heavy rain / flooding risk
DISEASE_ACT = 60         # disease-risk index at/above which spraying is advised
DISEASE_WATCH = 40
_ORDER = {"critical": 0, "action": 1, "warn": 2, "info": 3, "ok": 4}

_BN = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")


def _bn(x) -> str:
    return str(int(round(x))).translate(_BN)


def _item(id_, level, icon, title, text, action=None, btn=None):
    return {"id": id_, "level": level, "icon": icon, "title_bn": title, "text_bn": text,
            "action": action, "btn_bn": btn}


def _rain_outlook(fc: list[dict]) -> dict:
    """Expected rain (prob-weighted) for the next 2 days, heaviest day in the next 3, and 7-day total."""
    soon = sum(f["rain_mm"] * f["prob"] / 100 for f in fc[:2])
    heavy = next((f for f in fc[:3] if f["rain_mm"] >= HEAVY_RAIN_MM and f["prob"] >= 50), None)
    return {"soon_mm": soon, "heavy": heavy, "total_mm": sum(f["rain_mm"] for f in fc)}


def advise(v: dict, template: str = "") -> list[dict]:
    """v = twin_engine.snapshot(...). template = crop template id ('rice', 'veg', ...), used for water logic."""
    if v["status"] not in ("growing", "ready"):
        return []
    out: list[dict] = []
    sn, th, fc = v["soil_now"], v["thresholds"], v.get("forecast") or []
    rain = _rain_outlook(fc)
    stage_id = v["stage"]["id"]
    ripening = stage_id == "ripen"
    is_rice = template == "rice"

    # ---- harvest
    if v["status"] == "ready":
        out.append(_item("harvest", "action", "🌾", "ফসল কাটার সময় হয়েছে",
                         "ফসল পরিপক্ব। আবহাওয়া ভালো থাকতে থাকতে কেটে নিন।",
                         {"type": "harvest"}, "কর্তন করুন"))

    # ---- water
    aw, trig, emerg, stop = sn["aw"], th["irrigate_below"], th["emergency_below"], th["stop_at"]
    if v["pump_on"]:
        if aw >= stop:
            out.append(_item("pump_off", "action", "🛑", "পাম্প বন্ধ করুন",
                             f"মাটিতে পানি যথেষ্ট ({_bn(aw)}%)। আর চালালে পানি ও খরচ দুটোই নষ্ট।",
                             {"type": "pump", "on": False}, "পাম্প বন্ধ করুন"))
        else:
            out.append(_item("pump_run", "info", "💧", "পাম্প চলছে",
                             f"মাটির পানি এখন {_bn(aw)}%, লক্ষ্য {_bn(stop)}%। লক্ষ্যে পৌঁছালে বন্ধ করবেন।"))
    elif aw < emerg:
        out.append(_item("irrigate", "critical", "🚨", "এখনই সেচ দিন",
                         f"মাটির পানি মাত্র {_bn(aw)}%, জরুরি সীমা {_bn(emerg)}%-এর নিচে। দেরি হলে গাছ মারা যেতে পারে।",
                         {"type": "irrigate"}, "এখনই সেচ দিন"))
    elif aw < trig and not ripening:
        if rain["soon_mm"] >= RAIN_SOON_MM:
            out.append(_item("irrigate_wait", "info", "⛅", "সেচ একটু অপেক্ষা করুন",
                             f"পানি কমে {_bn(aw)}%, কিন্তু আগামী ২ দিনে প্রায় {_bn(rain['soon_mm'])} মিমি বৃষ্টির সম্ভাবনা। "
                             "বৃষ্টি না হলে কাল সেচ দিন।"))
        else:
            out.append(_item("irrigate", "action", "💧", "আজ সেচ দিন",
                             f"মাটির পানি {_bn(aw)}%, সীমা {_bn(trig)}%-এর নিচে। আগামী ২ দিনে বড় বৃষ্টির আশা নেই।",
                             {"type": "irrigate"}, "সেচ দিন"))
    if rain["heavy"] and not is_rice:
        out.append(_item("drain", "warn", "🌧️", "পানি নিষ্কাশনের ব্যবস্থা রাখুন",
                         f"{rain['heavy']['date'][5:]} তারিখে প্রায় {_bn(rain['heavy']['rain_mm'])} মিমি বৃষ্টির পূর্বাভাস। "
                         "নালা পরিষ্কার রাখুন, জমিতে পানি জমতে দেবেন না।"))
    elif rain["heavy"] and is_rice:
        out.append(_item("drain", "warn", "🌧️", "আইল ও পানির স্তর দেখুন",
                         f"{rain['heavy']['date'][5:]} তারিখে প্রায় {_bn(rain['heavy']['rain_mm'])} মিমি বৃষ্টির পূর্বাভাস। "
                         "জমির পানি উপচে যাওয়ার আগে নিকাশ-মুখ ঠিক রাখুন।"))

    # ---- nutrients (skip while ripening; hold off if heavy rain would wash it away)
    low = th["low_level"]
    names = {"N": ("ইউরিয়া", "নাইট্রোজেন"), "P": ("টিএসপি", "ফসফরাস"), "K": ("এমওপি", "পটাশ")}
    if not ripening:
        for n in ("N", "P", "K"):
            if sn[n] < low:
                if rain["heavy"] or rain["soon_mm"] >= 25:
                    out.append(_item(f"fert_{n}_wait", "info", "⏳", f"{names[n][0]} একটু পরে দিন",
                                     f"{names[n][1]} কম ({_bn(sn[n])}), কিন্তু শিগগির ভারী বৃষ্টি আসছে। এখন দিলে ধুয়ে যাবে।"))
                else:
                    out.append(_item(f"fert_{n}", "action", "🌱", f"{names[n][0]} দিন",
                                     f"{names[n][1]} কমে {_bn(sn[n])}-এ নেমেছে (সীমা {_bn(low)})।",
                                     {"type": "fertilize", "nutrient": n}, f"{names[n][0]} দিন"))

    # ---- soil chemistry
    if sn["ph"] < th["ph_min"]:
        out.append(_item("lime", "action", "🧪", "মাটি অম্লীয়, চুন দিন",
                         f"pH {sn['ph']}, এই ফসলের জন্য চাই {th['ph_min']}–{th['ph_max']}।",
                         {"type": "lime"}, "চুন দিন"))
    elif sn["ph"] > th["ph_max"]:
        out.append(_item("ph_high", "warn", "🧪", "মাটির pH বেশি",
                         f"pH {sn['ph']}, সীমা {th['ph_max']}। জৈব সার বাড়ান এবং স্থানীয় কৃষি অফিসে পরামর্শ নিন।"))
    if sn["ec"] > th["ec_tol"]:
        out.append(_item("salt", "warn", "🧂", "মাটিতে লবণ বেশি",
                         f"লবণাক্ততা {sn['ec']} dS/m, এই ফসলের সহনসীমা {th['ec_tol']}। সম্ভব হলে মিঠা পানিতে সেচ দিন।"))

    # ---- disease
    dr = sn["disease_risk"]
    if dr >= DISEASE_ACT:
        out.append(_item("spray", "action", "🛡️", "রোগের ঝুঁকি বেশি, স্প্রে করুন",
                         f"রোগের ঝুঁকি {_bn(dr)}। পাতায় দাগ বা ছত্রাক দেখলে ছবি তুলে পাঠান, স্প্রের মাত্রা কৃষি অফিস থেকে জেনে নিন।",
                         {"type": "spray"}, "স্প্রে করুন"))
    elif dr >= DISEASE_WATCH:
        out.append(_item("disease_watch", "warn", "🔍", "রোগের দিকে নজর রাখুন",
                         f"ঝুঁকি {_bn(dr)} (মাঝারি)। আজ জমি ঘুরে পাতা দেখুন, দাগ পেলে ছবি দিন।"))

    # ---- heat / forecast
    hot = next((f for f in fc[:3] if f["tmax"] >= 38), None)
    if hot:
        out.append(_item("heat", "warn", "🔥", "গরমের চাপ আসছে",
                         f"{hot['date'][5:]} তারিখে সর্বোচ্চ তাপ প্রায় {_bn(hot['tmax'])}°সে। সকাল বা সন্ধ্যায় সেচ দিন।"))

    # ---- what is coming next
    cur = next((s for s in v["stages"] if s["id"] == stage_id), None)
    if cur and not ripening:
        left = cur["end_day"] - v["day"]
        nxt = v["stages"][v["stages"].index(cur) + 1] if cur is not v["stages"][-1] else None
        if nxt and 0 < left <= 7:
            out.append(_item("next_stage", "info", "📅", f"{_bn(left)} দিনে '{nxt['name_bn']}' পর্যায় শুরু",
                             "নতুন পর্যায়ে পানি ও সারের চাহিদা বদলায়। আগে থেকে সার ও পানি ঠিক রাখুন।"))

    # ---- open questions
    if v.get("questions"):
        out.append(_item("questions", "info", "❓", f"টুইনের {_bn(len(v['questions']))}টি প্রশ্নের উত্তর দিন",
                         "আপনার উত্তর পেলে টুইন আরও নির্ভুল পরামর্শ দিতে পারবে।"))

    if not any(i["level"] in ("critical", "action", "warn") for i in out):
        out.insert(0, _item("all_ok", "ok", "✅", "আজ বাড়তি কিছু করতে হবে না",
                            "পানি, সার ও রোগের ঝুঁকি ঠিক আছে। ছবি তুলে দৈনিক চেক-ইন করে রাখুন।"))
    out.sort(key=lambda i: _ORDER[i["level"]])
    return out
