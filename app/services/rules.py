"""Hard rules: season, pH, soil, water, crop rotation. Pure functions, no AI."""
from ..data import SEASONS_BN, SOILS_BN, Crop, family_of, name_bn, rotation_rules


def evaluate(crop: Crop, ctx: dict) -> dict:
    """ctx: season, soil, ph, irrigation, last_crop, years_same, assumed(set of slot names).
    Facts the farmer did not give us (assumed) can warn but never block."""
    status, reasons, penalty = "ok", [], 0.0
    assumed = ctx["assumed"]

    def block(msg, slot=None):
        nonlocal status
        if slot in assumed:
            warn(msg + " (এই তথ্য অনুমান করা, তাই যাচাই করুন)", 8.0)
        else:
            status = "blocked"
            reasons.append(msg)

    def warn(msg, pct=0.0):
        nonlocal status, penalty
        if status != "blocked":
            status = "warn"
        penalty += pct
        reasons.append(msg)

    if ctx["season"] not in crop.seasons:
        ok = "/".join(SEASONS_BN[s] for s in crop.seasons)
        block(f"{crop.name_bn} {SEASONS_BN[ctx['season']]} মৌসুমের ফসল নয় (উপযুক্ত: {ok})", "season")

    ph = ctx["ph"]
    if ph < crop.ph_min - 1 or ph > crop.ph_max + 1:
        block(f"মাটির pH {ph} এই ফসলের জন্য অনেক বেমানান (দরকার {crop.ph_min}-{crop.ph_max})", "ph")
    elif ph < crop.ph_min or ph > crop.ph_max:
        warn(f"মাটির pH {ph} আদর্শ সীমার (প্রয়োজন {crop.ph_min}-{crop.ph_max}) বাইরে", 5.0)

    if ctx["soil"] not in crop.soils:
        ok = "/".join(SOILS_BN[s] for s in crop.soils)
        warn(f"{SOILS_BN[ctx['soil']]} মাটি আদর্শ নয় (ভালো: {ok})", 8.0)

    irr, need = ctx["irrigation"], crop.water_need
    if need == "high" and irr == "none":
        block(f"{crop.name_bn}-এ প্রচুর পানি লাগে, কিন্তু সেচের ব্যবস্থা নেই", "irrigation")
    elif need == "high" and irr == "partial":
        warn(f"{crop.name_bn}-এ প্রচুর পানি লাগে, আংশিক সেচে ঘাটতির ঝুঁকি আছে", 10.0)
    elif need == "medium" and irr == "none":
        warn(f"{crop.name_bn}-এ মাঝারি সেচ লাগে, বৃষ্টিনির্ভর হলে ফলন কমতে পারে", 10.0)

    last = ctx["last_crop"]
    prev_fam = family_of(last)
    if prev_fam:
        sev, pct, note = rotation_rules().get((prev_fam, crop.family), (None, 0.0, ""))
        if sev == "block":
            block(f"আগের ফসল {name_bn(last)}: {note}", "last_crop")
        elif sev == "warn":
            warn(f"আগের ফসল {name_bn(last)}: {note}", pct)
        elif sev == "ok" and pct < 0:
            penalty += pct  # rotation bonus (negative penalty)
            reasons.append(f"ভালো দিক: {note}")
        if prev_fam == crop.family and ctx["years_same"] >= 3:
            extra = min(15.0, (ctx["years_same"] - 2) * 5.0)
            warn(f"একই ধরনের ফসল টানা {ctx['years_same']} বছর হয়েছে, মাটির স্বাস্থ্য ও রোগের চাপ বাড়ছে", extra)

    return {"status": status, "reasons": reasons, "penalty_pct": max(-10.0, min(penalty, 60.0))}
