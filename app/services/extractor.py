"""Prompt -> slots. Regex baseline always runs; LLM (if configured) overrides/adds."""
import json
import re

from . import llm
from .lexicon import find_crops, normalize
from .slot_manager import normalize_slot

UNIT_TO_DECIMAL = {"বিঘা": 33.0, "bigha": 33.0, "শতাংশ": 1.0, "শতক": 1.0, "decimal": 1.0, "decimals": 1.0,
                   "একর": 100.0, "acre": 100.0, "acres": 100.0}
LAND_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(বিঘা|bigha|শতাংশ|শতক|decimals?|একর|acres?)", re.I)
YEARS_RE = re.compile(r"(\d+)\s*(?:বছর|বৎসর|years?|yrs?)", re.I)
PH_RE = re.compile(r"(?:ph|পিএইচ)\s*[:=]?\s*(\d+(?:\.\d+)?)", re.I)
LOC_RE = re.compile(r"([\u0980-\u09FFA-Za-z]+)\s*(?:উপজেলা|জেলা|upazila|district)", re.I)
SPLIT_RE = re.compile(r"[,،;।\.\n]|কিন্তু|এখন|এবার|তারপর|\bnow\b|\bbut\b", re.I)
HIST_CUES = ("গত", "আগে", "করেছি", "করেছিলাম", "করেছিলেন", "ছিল", "last", "previous", "grew", "planted")
TGT_CUES = ("চাই", "করতে", "করব", "লাগাতে", "লাগাব", "want", "plan", "next", "would like")

SOIL_KW = {"doash": ("দোআঁশ", "দো-আঁশ", "loam"), "entel": ("এঁটেল", "এটেল", "clay"), "beley": ("বেলে", "sandy")}
IRR_KW = [
    ("none", ("সেচ নেই", "সেচের ব্যবস্থা নেই", "বৃষ্টিনির্ভর", "rainfed", "no irrigation")),
    ("partial", ("আংশিক সেচ", "কিছু সেচ")),
    ("good", ("সেচের ব্যবস্থা আছে", "গভীর নলকূপ", "শ্যালো", "পাম্প আছে", "good irrigation")),
]
SEASON_KW = [
    ("kharif1", ("খরিফ-১", "খরিফ ১", "kharif-1", "kharif1")),
    ("kharif2", ("খরিফ-২", "খরিফ ২", "kharif-2", "kharif2")),
    ("rabi", ("রবি", "rabi")),
]


def regex_extract(prompt: str) -> dict:
    t = normalize(prompt)
    low = t.lower()
    out: dict = {}

    if m := LAND_RE.search(t):
        out["land_decimal"] = float(m.group(1)) * UNIT_TO_DECIMAL[m.group(2).lower()]
    if m := PH_RE.search(t):
        out["ph"] = float(m.group(1))
    if m := LOC_RE.search(t):
        out["location"] = m.group(1)
    for k, kws in SOIL_KW.items():
        if any(w in low for w in kws):
            out["soil_type"] = k
    for k, kws in IRR_KW:
        if any(w in low for w in kws):
            out["irrigation"] = k
            break
    for k, kws in SEASON_KW:
        if any(w in low for w in kws):
            out["season"] = k
            break

    target = last = None
    for clause in SPLIT_RE.split(t):
        found = find_crops(clause)
        if not found:
            continue
        hist = any(c in clause.lower() for c in HIST_CUES)
        tgt = any(c in clause.lower() for c in TGT_CUES)
        if hist and not tgt:
            last = last or found[0]
            if m := YEARS_RE.search(clause):
                out["years_same"] = int(m.group(1))
        elif tgt and not hist:
            target = target or found[0]
    if target is None and last is None:
        all_found = find_crops(t)
        if len(all_found) == 1:
            target = all_found[0]
    if target:
        out["target_crop"] = target
    if last:
        out["last_crop"] = last
    return out


_SYSTEM = (
    "You extract farm details from a Bengali/English message. Reply with ONLY a JSON object with keys: "
    "land_value (number|null), land_unit ('bigha'|'decimal'|'acre'|null), target_crop, last_crop, years_same (int|null), "
    "season ('rabi'|'kharif1'|'kharif2'|null), soil_type ('doash'|'entel'|'beley'|null), "
    "irrigation ('good'|'partial'|'none'|null), location (string|null). "
    "Crop values must be one of: boro, aman, aus, rice (rice but variety unclear), wheat, maize, potato, tomato, mustard, lentil, jute, or null. "
    "target_crop = what they WANT to grow now; last_crop = what they grew before. Use null when not stated. Never guess."
)


async def llm_extract(prompt: str) -> dict:
    text = await llm.chat([{"role": "system", "content": _SYSTEM}, {"role": "user", "content": prompt}],
                          max_tokens=300, temperature=0.0)
    if not text:
        return {}
    try:
        data = json.loads(text[text.index("{"): text.rindex("}") + 1])
    except ValueError:
        return {}
    out = {}
    if data.get("land_value") and data.get("land_unit") in ("bigha", "decimal", "acre"):
        try:
            out["land_decimal"] = float(data["land_value"]) * UNIT_TO_DECIMAL[data["land_unit"]]
        except (TypeError, ValueError):
            pass
    for k in ("target_crop", "last_crop", "years_same", "season", "soil_type", "irrigation", "location"):
        if data.get(k) is not None:
            out[k] = data[k]
    return out


async def extract(prompt: str) -> dict:
    """Returns {slot: clean_value}; invalid values are dropped."""
    raw = regex_extract(prompt)
    if llm.available():
        raw.update(await llm_extract(prompt))
    clean = {}
    for k, v in raw.items():
        nv = normalize_slot(k, v)
        if nv is not None:
            clean[k] = nv
    return clean
