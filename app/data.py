import csv
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).parent / "csv_data"

SEASONS_BN = {"rabi": "রবি", "kharif1": "খরিফ-১", "kharif2": "খরিফ-২"}
SOILS_BN = {"doash": "দোআঁশ", "entel": "এঁটেল", "beley": "বেলে"}
IRRIGATION_BN = {"good": "ভালো", "partial": "আংশিক", "none": "নেই (বৃষ্টিনির্ভর)"}


@dataclass(frozen=True)
class Crop:
    id: str
    name_bn: str
    name_en: str
    family: str
    seasons: tuple
    ph_min: float
    ph_max: float
    duration_days: int
    soils: tuple
    water_need: str
    y: tuple   # (bad, base, good) kg per decimal
    p: tuple   # (bad, base, good) BDT per kg
    cost: float  # BDT per decimal


def _rows(name):
    with open(DATA / name, encoding="utf-8") as f:
        return list(csv.DictReader(f))


@lru_cache
def crops() -> dict[str, Crop]:
    econ = {r["crop_id"]: r for r in _rows("prices_costs.csv")}
    out = {}
    for r in _rows("crop_requirements.csv"):
        e = econ[r["id"]]
        out[r["id"]] = Crop(
            id=r["id"], name_bn=r["name_bn"], name_en=r["name_en"], family=r["family"],
            seasons=tuple(r["seasons"].split("|")), ph_min=float(r["ph_min"]), ph_max=float(r["ph_max"]),
            duration_days=int(r["duration_days"]), soils=tuple(r["soils"].split("|")),
            water_need=r["water_need"],
            y=(float(e["yield_bad"]), float(e["yield_base"]), float(e["yield_good"])),
            p=(float(e["price_bad"]), float(e["price_base"]), float(e["price_good"])),
            cost=float(e["cost_per_decimal"]),
        )
    return out


@lru_cache
def rotation_rules() -> dict[tuple, tuple]:
    return {
        (r["prev_family"], r["next_family"]): (r["severity"], float(r["yield_penalty_pct"]), r["note_bn"])
        for r in _rows("rotation_rules.csv")
    }


def family_of(crop_id: str | None) -> str | None:
    if crop_id in (None, "none"):
        return None
    if crop_id == "rice":  # generic "ধান" when the farmer didn't say which rice
        return "cereal"
    c = crops().get(crop_id)
    return c.family if c else None


def name_bn(crop_id: str) -> str:
    if crop_id == "rice":
        return "ধান"
    if crop_id == "none":
        return "কিছু নয়"
    c = crops().get(crop_id)
    return c.name_bn if c else crop_id
