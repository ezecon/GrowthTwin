"""Section 4 "কৃষকের ভরসা": what happened when OTHER farmers grew the same crop (anonymous aggregates only).

Rules that keep it honest:
- no names / user ids leave this module;
- distributions are shown only when >= TRUST_MIN_FARMERS different farmers finished the crop (else just counts);
- failed (dead) plots are included, so the profit share is not flattering;
- every record carries its source ("simulation" now); the UI labels it, so simulated results are never passed off as real fields.
"""
from collections import Counter
from statistics import median

from fastapi import APIRouter, Depends, HTTPException

from ..core.auth import User, current_user
from ..core.config import get_settings
from ..core.twin_store import get_twin_store
from ..data import crops

router = APIRouter(prefix="/trust", tags=["trust"])
BINS = 8


def _ppd(r) -> float:                      # profit per decimal (BDT)
    return float(r["profit"] or 0) / max(float(r["area"]), 0.01)


def _q(vals: list[float], p: float) -> float:
    v = sorted(vals)
    return v[min(len(v) - 1, int(p * (len(v) - 1) + 0.5))]


@router.get("/crop/{crop_id}")
async def crop_trust(crop_id: str, user: User = Depends(current_user)):
    cs = crops()
    if crop_id not in cs:
        raise HTTPException(404, "অজানা ফসল")
    store = get_twin_store()
    rows = await store.list_harvests_by_crop(crop_id)
    mine = [r for r in rows if r["user_id"] == user.id]
    others = [r for r in rows if r["user_id"] != user.id]
    farmers = len({r["user_id"] for r in rows})
    need = max(1, get_settings().trust_min_farmers)
    c = cs[crop_id]
    out = {"crop_id": crop_id, "n_farmers": farmers, "n_plots": len(rows), "growing_now": await store.count_active(crop_id),
           "min_farmers": need, "enough": farmers >= need,
           "sources": dict(Counter(r.get("source") or "simulation" for r in rows)),
           "table": {"bad": c.y[0], "base": c.y[1], "good": c.y[2], "cost_per_decimal": c.cost}}
    if farmers < need:
        out["mine"] = []                    # nothing to compare against yet; no distribution leaks for tiny groups
        return out

    allp = [_ppd(r) for r in rows]
    ok = [r for r in rows if (r.get("outcome") or "harvested") == "harvested"]
    lo, hi = min(allp), max(allp)
    width = (hi - lo) / BINS or 1.0
    counts = [0] * BINS
    for v in allp:
        counts[min(BINS - 1, int((v - lo) / width))] += 1
    out.update({
        "profit_share": round(sum(1 for v in allp if v > 0) / len(allp), 3),
        "failed": sum(1 for r in rows if (r.get("outcome") or "harvested") == "dead"),
        "median_profit_per_decimal": round(median(allp)),
        "p25": round(_q(allp, .25)), "p75": round(_q(allp, .75)), "best": round(hi), "worst": round(lo),
        "median_yield_per_decimal": round(median(float(r["yield_kg_per_decimal"]) for r in ok), 1) if ok else None,
        "median_days": round(median(float(r["days"] or 0) for r in ok)) if ok else None,
        "hist": {"lo": round(lo), "hi": round(hi), "counts": counts},
    })
    op = [_ppd(r) for r in others]
    out["mine"] = [{"profit_per_decimal": round(_ppd(r)), "yield_per_decimal": round(float(r["yield_kg_per_decimal"]), 1),
                    "outcome": r.get("outcome") or "harvested", "start_date": r.get("start_date"),
                    "better_than": round(sum(1 for v in op if v < _ppd(r)) / len(op), 3) if op else None} for r in mine]
    return out
