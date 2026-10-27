"""Deterministic synthetic Bangladesh weather + imperfect forecast (simulation mode).

Same (seed, date) always gives the same weather, so the 'forecast' is the true future weather plus error:
this lets the twin be replayed, and a real weather API (Open-Meteo) can later replace day_weather/forecast.
Monthly climate numbers are SAMPLE-VERIFY (rough Dhaka/Chattogram normals).
"""
import calendar
import math
import random
from datetime import date, timedelta

TMEAN = [19, 22, 26, 28, 29, 29, 29, 29, 29, 28, 24, 20]
RAIN_MM = [8, 25, 60, 130, 270, 500, 560, 400, 300, 160, 30, 8]
WET_MEAN = [6, 8, 10, 14, 20, 24, 24, 22, 20, 18, 10, 6]     # mean mm on a wet day
RH = [68, 62, 60, 68, 76, 84, 86, 86, 84, 80, 72, 70]


def _interp(table, d: date) -> float:
    """Linear interpolation between month centres."""
    dim = calendar.monthrange(d.year, d.month)[1]
    pos = d.month - 1 + (d.day - 0.5) / dim - 0.5
    i = math.floor(pos) % 12
    f = pos - math.floor(pos)
    return table[i] * (1 - f) + table[(i + 1) % 12] * f


def normal_rain(d: date) -> float:
    """Normal mm per day for that month."""
    return RAIN_MM[d.month - 1] / calendar.monthrange(d.year, d.month)[1]


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def day_weather(seed, d: date) -> dict:
    m = d.month - 1
    p = _clamp(RAIN_MM[m] / (calendar.monthrange(d.year, d.month)[1] * WET_MEAN[m]), 0.03, 0.9)
    q = _clamp((p - 0.1) / 0.6, 0, 1)
    block = d.timetuple().tm_yday // 4
    block_wet = random.Random(f"{seed}|blk|{d.year}|{block}").random() < q
    r = random.Random(f"{seed}|{d.isoformat()}")
    wet = r.random() < (0.7 if block_wet else 0.1)
    rain, storm = 0.0, False
    if wet:
        rain = min(120.0, max(0.5, r.expovariate(1 / WET_MEAN[m])))
    if 3 <= m <= 10 and random.Random(f"{seed}|storm|{d.isoformat()}").random() < 0.012:
        rain, storm, wet = 70 + r.random() * 70, True, True
    tmean = _interp(TMEAN, d) + r.gauss(0, 1.5) - (1.5 if wet else 0)
    half = 2.2 if wet else 4.2
    tmax, tmin = tmean + half, tmean - half
    rh = _clamp(_interp(RH, d) + (8 if wet else -5) + r.gauss(0, 4), 35, 98)
    doy = d.timetuple().tm_yday
    daylight = 12.1 + 1.4 * math.sin(2 * math.pi * (doy - 80) / 365)          # ~24 deg N
    cloud = _clamp(0.15 + (rh - 60) / 100 + (0.4 if wet else 0), 0.05, 0.95)
    sun_h = daylight * (1 - 0.85 * cloud)
    ra = 14.2 + 2.3 * math.cos(2 * math.pi * (doy - 172) / 365)
    et0 = 0.0023 * (tmean + 17.8) * math.sqrt(max(tmax - tmin, 2.0)) * ra     # Hargreaves
    return {"date": d.isoformat(), "tmax": round(tmax, 1), "tmin": round(tmin, 1), "tmean": round(tmean, 1),
            "rain_mm": round(rain, 1), "rh": round(rh), "et0": round(et0, 2), "storm": storm,
            "daylight_h": round(daylight, 1), "sun_h": round(sun_h, 1)}


def forecast(seed, from_date: date, n: int = 5) -> list[dict]:
    """Forecast for from_date .. from_date+n-1 (error grows with lead time)."""
    out = []
    for k in range(n):
        d = from_date + timedelta(days=k)
        wx = day_weather(seed, d)
        actual = wx["rain_mm"]
        r = random.Random(f"{seed}|fc|{d.isoformat()}|{k}")
        sigma = 0.25 + 0.1 * k
        if actual > 0:
            rain = actual * math.exp(r.gauss(0, sigma))
            prob = _clamp(62 + min(25, rain * 1.5) - 4 * k + r.gauss(0, 4), 20, 97)
        elif r.random() < 0.08 + 0.03 * k:
            rain, prob = r.uniform(2, 8), _clamp(35 + r.gauss(0, 6), 15, 55)
        else:
            rain, prob = 0.0, _clamp(8 + 3 * k + r.gauss(0, 3), 2, 30)
        normal = normal_rain(d)
        rel = "more" if rain >= max(10, 1.3 * normal) else "less" if rain < max(1.0, 0.3 * normal) else "normal"
        tmax_f = wx["tmax"] + r.gauss(0, 1.0 + 0.4 * k)
        out.append({"date": d.isoformat(), "lead_days": k, "rain_mm": round(rain, 1), "prob": round(prob),
                    "tmax": round(tmax_f, 1),
                    "normal_mm": round(normal, 1), "vs_normal": rel})
    return out
