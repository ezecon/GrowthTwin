"""Slots: what we need to know, how to normalise answers, what to ask, how confident we are."""
from datetime import date

from ..data import IRRIGATION_BN, SEASONS_BN, SOILS_BN, crops
from .lexicon import find_crops, normalize

# Slots we ASK about if missing (priority order). Everything else is silently defaulted.
ASK_ORDER = ["target_crop", "land_decimal", "last_crop", "season", "irrigation"]

# How much each assumed slot lowers confidence.
ASSUMED_WEIGHT = {
    "target_crop": 0.10, "land_decimal": 0.10, "last_crop": 0.15, "season": 0.20,
    "irrigation": 0.20, "soil_type": 0.15, "ph": 0.05, "years_same": 0.05, "location": 0.05,
}

SLOT_LABEL_BN = {
    "target_crop": "চাষ করতে চান", "land_decimal": "জমির পরিমাণ", "last_crop": "আগের ফসল",
    "season": "মৌসুম", "irrigation": "সেচ", "soil_type": "মাটি", "ph": "মাটির pH",
    "years_same": "একই ফসল (বছর)", "location": "এলাকা",
}


def infer_season(today: date | None = None) -> str:
    m = (today or date.today()).month
    if m in (10, 11, 12, 1, 2):
        return "rabi"
    return "kharif1" if m in (3, 4, 5, 6) else "kharif2"


def defaults(today: date | None = None) -> dict:
    return {
        "target_crop": "any", "land_decimal": 33.0, "last_crop": "none", "season": infer_season(today),
        "irrigation": "partial", "soil_type": "doash", "ph": 6.3, "years_same": 1, "location": None,
    }


def normalize_slot(name: str, raw):
    """Return a clean value, or None if raw is unusable."""
    if raw is None:
        return None
    try:
        if name == "land_decimal":
            v = float(raw)
            return v if 1 <= v <= 5000 else None
        if name in ("target_crop", "last_crop"):
            s = str(raw).strip()
            if s in crops() or s in ("rice", "none") or (name == "target_crop" and s == "any"):
                return s
            f = find_crops(normalize(s))
            return f[0] if f else None
        if name == "season":
            s = str(raw).strip().lower()
            return s if s in SEASONS_BN else None
        if name == "irrigation":
            s = str(raw).strip().lower()
            return s if s in IRRIGATION_BN else None
        if name == "soil_type":
            s = str(raw).strip().lower()
            return s if s in SOILS_BN else None
        if name == "ph":
            v = float(raw)
            return v if 3.0 <= v <= 10.0 else None
        if name == "years_same":
            v = int(float(raw))
            return v if 0 <= v <= 60 else None
        if name == "location":
            s = str(raw).strip()
            return s[:80] or None
    except (TypeError, ValueError):
        return None
    return None


def set_slot(slots: dict, name: str, raw, source: str = "user") -> bool:
    if raw == "unknown":  # "জানি না": take the default, mark as assumed
        slots[name] = {"value": defaults()[name], "source": "assumed"}
        return True
    v = normalize_slot(name, raw)
    if v is None:
        return False
    slots[name] = {"value": v, "source": source}
    return True


def missing_required(slots: dict, asked: list[str]) -> list[str]:
    return [s for s in ASK_ORDER if s not in slots and s not in asked]


def apply_defaults(slots: dict, today: date | None = None) -> dict:
    out = {k: dict(v) for k, v in slots.items()}
    for k, v in defaults(today).items():
        out.setdefault(k, {"value": v, "source": "assumed"})
    return out


def confidence(slots: dict) -> float:
    pen = sum(ASSUMED_WEIGHT.get(k, 0) for k, v in slots.items() if v["source"] == "assumed")
    return round(max(0.0, 1.0 - pen), 2)


def build_questions(slot_names: list[str]) -> list[dict]:
    cs = crops()
    crop_opts = [{"value": c.id, "label_bn": c.name_bn} for c in cs.values()]
    q = {
        "target_crop": ("আপনি এখন কোন ফসল চাষ করতে চান?",
                        crop_opts + [{"value": "any", "label_bn": "ঠিক করিনি, পরামর্শ দিন"}]),
        "land_decimal": ("আপনার জমির পরিমাণ কত?",
                         [{"value": 15, "label_bn": "১৫ শতাংশ"}, {"value": 33, "label_bn": "১ বিঘা (৩৩ শতাংশ)"},
                          {"value": 66, "label_bn": "২ বিঘা (৬৬ শতাংশ)"}, {"value": 100, "label_bn": "৩ বিঘা বা বেশি (১০০ শতাংশ)"},
                          {"value": "unknown", "label_bn": "জানি না"}]),
        "last_crop": ("জমিতে সর্বশেষ কোন ফসল চাষ করেছিলেন?",
                      crop_opts + [{"value": "none", "label_bn": "পতিত ছিল / কিছু চাষ হয়নি"},
                                   {"value": "unknown", "label_bn": "মনে নেই"}]),
        "season": ("কোন মৌসুমে রোপণ/বপন করবেন?",
                   [{"value": k, "label_bn": v} for k, v in SEASONS_BN.items()] + [{"value": "unknown", "label_bn": "জানি না"}]),
        "irrigation": ("সেচের ব্যবস্থা কেমন?",
                       [{"value": k, "label_bn": v} for k, v in IRRIGATION_BN.items()] + [{"value": "unknown", "label_bn": "জানি না"}]),
    }
    return [{"slot": s, "text_bn": q[s][0], "options": q[s][1]} for s in slot_names if s in q]
