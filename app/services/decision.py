"""Decision layer: hard rules -> 3-scenario economics -> rating + ranking. No trained model involved."""
from ..core.config import Settings
from ..data import crops
from . import economics, rules

RATING_BN = {"go": "এগিয়ে যান", "caution": "সতর্কতাসহ", "no": "সুপারিশ নয়"}


def build_ctx(slots: dict) -> dict:
    v = lambda k: slots[k]["value"]
    return {
        "season": v("season"), "soil": v("soil_type"), "ph": float(v("ph")), "irrigation": v("irrigation"),
        "last_crop": v("last_crop"), "years_same": int(v("years_same")),
        "assumed": {k for k, s in slots.items() if s["source"] == "assumed"},
    }


def rate(status: str, econ: dict, confidence: float, cfg: Settings) -> str:
    if status == "blocked" or econ["base"]["profit"] <= 0:
        return "no"
    cost = econ["cost"] or 1
    healthy = (
        status == "ok"
        and econ["base"]["profit"] / cost >= cfg.go_margin
        and econ["bad"]["profit"] >= -cfg.max_loss_share * cost
    )
    if healthy and confidence >= cfg.min_confidence_for_go:
        return "go"
    return "caution"


def assess(crop, ctx: dict, land: float, confidence: float, cfg: Settings) -> dict:
    r = rules.evaluate(crop, ctx)
    econ = economics.scenarios(crop, land, r["penalty_pct"])
    rating = rate(r["status"], econ, confidence, cfg)
    score = cfg.w_base * econ["base"]["profit"] + cfg.w_worst * econ["bad"]["profit"]
    return {
        "crop_id": crop.id, "name_bn": crop.name_bn, "status": r["status"], "rating": rating,
        "rating_bn": RATING_BN[rating], "reasons_bn": r["reasons"], "penalty_pct": r["penalty_pct"],
        "scenarios": econ, "score": round(score),
    }


def resolve_target(target: str, season: str) -> str:
    """Generic 'rice' -> the rice that fits the season."""
    if target == "rice":
        return {"rabi": "boro", "kharif1": "aus", "kharif2": "aman"}[season]
    return target


def decide(slots: dict, confidence: float, cfg: Settings) -> dict:
    ctx = build_ctx(slots)
    land = float(slots["land_decimal"]["value"])
    target_id = resolve_target(slots["target_crop"]["value"], ctx["season"])
    cs = crops()

    target = assess(cs[target_id], ctx, land, confidence, cfg) if target_id in cs else None
    pool = [c for c in cs.values() if ctx["season"] in c.seasons and c.id != target_id]
    ranked = sorted((assess(c, ctx, land, confidence, cfg) for c in pool),
                    key=lambda a: a["score"], reverse=True)
    alternatives = [a for a in ranked if a["rating"] != "no"][:3]

    best = target if (target and target["rating"] != "no") else (alternatives[0] if alternatives else None)
    review = confidence < cfg.review_confidence_threshold or bool(
        target and target["scenarios"]["bad"]["profit"] < -0.5 * target["scenarios"]["cost"]
    )
    return {"target": target, "alternatives": alternatives, "best": best,
            "confidence": confidence, "review_recommended": review, "ctx": ctx}
