"""Crop growth-stage tables + physiology profiles for the Section 2 twin.

ALL NUMBERS ARE SAMPLE-VERIFY: confirm with BRRI / DAE / BARC (Fertilizer Recommendation Guide) before field use.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Stage:
    id: str
    name_bn: str
    end: float        # stage ends at this fraction of duration_days
    kc: float         # crop coefficient (ETc = ET0 * kc)
    demand: float     # relative nutrient demand
    sens: float       # sensitivity of yield to stress in this stage
    irrigate: bool = True


def _S(rows):
    return tuple(Stage(*r) for r in rows)


TEMPLATES = {
    "rice": _S([
        ("germ", "বীজতলা ও অঙ্কুরোদগম", 0.10, 1.05, 0.3, 0.6),
        ("seedling", "চারা", 0.22, 1.10, 0.6, 0.7),
        ("tiller", "কুশি", 0.45, 1.15, 1.2, 1.0),
        ("panicle", "থোড়", 0.60, 1.20, 1.4, 1.3),
        ("flower", "ফুল আসা", 0.72, 1.20, 0.8, 2.0),
        ("fill", "দানা ভরা", 0.92, 1.10, 0.6, 1.5),
        ("ripen", "পরিপক্ব", 1.00, 0.90, 0.1, 0.5, False),
    ]),
    "cereal": _S([
        ("germ", "অঙ্কুরোদগম", 0.10, 0.40, 0.3, 0.6),
        ("seedling", "চারা", 0.25, 0.70, 0.7, 0.8),
        ("veg", "বৃদ্ধি", 0.55, 1.05, 1.3, 1.0),
        ("flower", "ফুল আসা", 0.70, 1.15, 0.9, 2.0),
        ("fill", "দানা ভরা", 0.90, 0.90, 0.5, 1.5),
        ("ripen", "পরিপক্ব", 1.00, 0.50, 0.1, 0.5, False),
    ]),
    "tuber": _S([
        ("germ", "অঙ্কুরোদগম", 0.12, 0.50, 0.3, 0.6),
        ("veg", "গাছের বৃদ্ধি", 0.40, 0.90, 1.2, 1.0),
        ("tuber_init", "আলু ধরা শুরু", 0.60, 1.10, 1.4, 1.8),
        ("bulk", "আলু বড় হওয়া", 0.90, 1.05, 0.8, 1.5),
        ("ripen", "পরিপক্ব", 1.00, 0.70, 0.1, 0.5, False),
    ]),
    "veg": _S([
        ("germ", "চারা তৈরি", 0.15, 0.50, 0.4, 0.7),
        ("veg", "বৃদ্ধি", 0.40, 0.90, 1.2, 1.0),
        ("flower", "ফুল ও ফল ধরা", 0.65, 1.15, 1.3, 2.0),
        ("fruit", "ফল বড় হওয়া", 0.92, 1.05, 0.9, 1.5),
        ("ripen", "পরিপক্ব", 1.00, 0.85, 0.1, 0.5, False),
    ]),
    "oil": _S([
        ("germ", "অঙ্কুরোদগম", 0.10, 0.40, 0.3, 0.6),
        ("veg", "বৃদ্ধি", 0.45, 0.95, 1.3, 1.0),
        ("flower", "ফুল আসা", 0.65, 1.10, 1.0, 2.0),
        ("pod", "শুঁটি ভরা", 0.90, 0.85, 0.6, 1.5),
        ("ripen", "পরিপক্ব", 1.00, 0.40, 0.1, 0.5, False),
    ]),
    "pulse": _S([
        ("germ", "অঙ্কুরোদগম", 0.10, 0.40, 0.2, 0.6),
        ("veg", "বৃদ্ধি", 0.45, 0.80, 1.0, 1.0),
        ("flower", "ফুল আসা", 0.65, 1.00, 1.0, 2.0),
        ("pod", "শুঁটি ভরা", 0.90, 0.80, 0.6, 1.5),
        ("ripen", "পরিপক্ব", 1.00, 0.40, 0.1, 0.5, False),
    ]),
    "fiber": _S([
        ("germ", "অঙ্কুরোদগম", 0.10, 0.50, 0.3, 0.6),
        ("veg", "দ্রুত বৃদ্ধি", 0.70, 1.10, 1.4, 1.2),
        ("bud", "কুঁড়ি আসা", 0.90, 1.00, 0.7, 1.5),
        ("ripen", "কর্তনযোগ্য", 1.00, 0.80, 0.1, 0.5, False),
    ]),
}
CROP_TEMPLATE = {"boro": "rice", "aman": "rice", "aus": "rice", "wheat": "cereal", "maize": "cereal",
                 "potato": "tuber", "tomato": "veg", "mustard": "oil", "lentil": "pulse", "jute": "fiber"}

# (opt_min, opt_max, crit_min, crit_max) deg C on daily mean
TEMP = {"rice": (18, 30, 12, 38), "cereal": (14, 30, 4, 38), "tuber": (12, 24, 4, 34), "veg": (18, 30, 10, 38),
        "oil": (12, 26, 4, 36), "pulse": (12, 26, 4, 36), "fiber": (24, 34, 16, 40)}

# sunshine hours/day for full growth; below this, growth slows a little (SAMPLE-VERIFY)
LIGHT_NEED = {"rice": 6.0, "cereal": 6.0, "tuber": 6.0, "veg": 6.0, "oil": 6.0, "pulse": 5.5, "fiber": 5.0}

SALT_TOL = {"boro": 3.0, "aman": 3.0, "aus": 3.0, "wheat": 6.0, "maize": 1.7, "potato": 1.7, "tomato": 2.5,
            "mustard": 4.0, "lentil": 1.5, "jute": 3.0}  # dS/m threshold

# fertilizer: nutrient -> (name_bn, kg per decimal per dose, level gain per dose)
FERT = {"N": ("ইউরিয়া", 0.35, 25.0), "P": ("টিএসপি", 0.25, 20.0), "K": ("এমওপি", 0.20, 20.0)}

AWC_MM = {"doash": 100.0, "entel": 120.0, "beley": 70.0}   # plant-available water in root zone
SOIL_BUFFER = {"doash": 1.0, "entel": 1.4, "beley": 0.7}   # liming buffer factor
LIME_KG_PER_DECIMAL_PER_PH = 3.0

SEASON_BN = {"rabi": "রবি", "kharif1": "খরিফ-১", "kharif2": "খরিফ-২"}


def season_of(month: int) -> str:
    return "rabi" if month in (11, 12, 1, 2) else "kharif1" if month in (3, 4, 5, 6) else "kharif2"


def template_of(crop_id: str) -> str:
    return CROP_TEMPLATE.get(crop_id, "cereal")


def stages(crop_id: str):
    return TEMPLATES[template_of(crop_id)]


def stage_at(crop_id: str, day: int, duration: int):
    st = stages(crop_id)
    frac = day / duration
    for i, s in enumerate(st):
        if frac <= s.end:
            return i, s
    return len(st) - 1, st[-1]


def profile(crop_id: str, water_need: str) -> dict:
    """Soil-water thresholds in % of plant-available water (100 = field capacity; >100 = saturated/ponded)."""
    if template_of(crop_id) == "rice":
        stress, wilt, trigger, target = 95.0, 40.0, 110.0, 130.0
    else:
        stress = {"high": 55.0, "medium": 45.0, "low": 35.0}.get(water_need, 45.0)
        wilt, trigger, target = 10.0, stress + 10.0, 95.0
    return {"stress": stress, "wilt": wilt, "trigger": trigger, "target": target,
            "emergency": wilt + 0.5 * (stress - wilt), "pump_mm": 25.0}
