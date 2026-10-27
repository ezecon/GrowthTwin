"""compare.py: 'switch to the new crop' vs 'keep growing the current one', same land, same season."""
from ..core.config import Settings
from ..data import crops
from . import decision
from .lexicon import bn_num

TOL_BASE = 0.05   # base-profit difference below this share of cost = "similar"
TOL_WORST = 0.10  # worst-case difference tolerated before calling a switch "riskier"


def _verdict(cur: dict, new: dict) -> str:
    cs, ns = cur["scenarios"], new["scenarios"]
    if cur["status"] == "blocked":
        return "current_not_feasible"
    if cur["rating"] == "no" and new["rating"] == "no":
        return "both_weak"
    if new["rating"] == "no":
        return "stay_better"
    cost = (cs["cost"] + ns["cost"]) / 2 or 1
    d_base = ns["base"]["profit"] - cs["base"]["profit"]
    d_worst = ns["bad"]["profit"] - cs["bad"]["profit"]
    if d_base > TOL_BASE * cost:
        return "switch_better" if d_worst >= -TOL_WORST * cost else "switch_riskier"
    if d_base < -TOL_BASE * cost:
        return "stay_better"
    return "similar"


def _text(v: str, cur: dict, new: dict, d: dict) -> str:
    c, n = cur["name_bn"], new["name_bn"]
    if v == "current_not_feasible":
        why = "; ".join(cur["reasons_bn"][:2])
        return f"{c} এই অবস্থায় আবার চাষ করা সম্ভব নয় ({why})।"
    if v == "both_weak":
        return f"{c} চালিয়ে যাওয়া ও {n}-এ যাওয়া, দুটোই এই অবস্থায় দুর্বল; বিকল্প ফসল দেখুন।"
    if v == "stay_better":
        return f"{c} চালিয়ে গেলে গড় লাভ {n}-এর চেয়ে {bn_num(abs(d['base']))} টাকা বেশি।"
    if v == "switch_better":
        return f"{c}-এর বদলে {n} চাষে গড় লাভ {bn_num(d['base'])} টাকা বেশি, খারাপ পরিস্থিতিতেও ক্ষতি বেশি বাড়ে না।"
    if v == "switch_riskier":
        return (f"{n}-এ গেলে গড় লাভ {bn_num(d['base'])} টাকা বেশি, কিন্তু খারাপ পরিস্থিতিতে "
                f"লোকসান {bn_num(abs(d['worst']))} টাকা বেশি। ঝুঁকি নিতে পারলে বিবেচনা করুন।")
    return f"{c} ও {n}-এর লাভের পার্থক্য সামান্য; মাটির স্বাস্থ্য ও দামের ঝুঁকি দেখে সিদ্ধান্ত নিন।"


def compare(slots: dict, dec: dict, confidence: float, cfg: Settings) -> dict | None:
    last = slots["last_crop"]["value"]
    new = dec["target"] or dec["best"]
    if last in (None, "none") or new is None:
        return None
    ctx = dec["ctx"]
    cur_id = decision.resolve_target(last, ctx["season"])
    if cur_id not in crops() or cur_id == new["crop_id"]:
        return None
    land = float(slots["land_decimal"]["value"])
    cur = decision.assess(crops()[cur_id], ctx, land, confidence, cfg)
    v = _verdict(cur, new)
    d = {"base": new["scenarios"]["base"]["profit"] - cur["scenarios"]["base"]["profit"],
         "worst": new["scenarios"]["bad"]["profit"] - cur["scenarios"]["bad"]["profit"],
         "good": new["scenarios"]["good"]["profit"] - cur["scenarios"]["good"]["profit"]}
    return {"verdict": v, "verdict_bn": _text(v, cur, new, d), "current": cur, "new": new, "profit_delta": d}
