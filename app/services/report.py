"""Facts for the LLM + deterministic Bengali fallback narrative."""
from ..data import IRRIGATION_BN, SEASONS_BN, SOILS_BN, name_bn
from .lexicon import bn_num
from .slot_manager import SLOT_LABEL_BN

RATING_ORDER = {"go": 0, "caution": 1, "no": 2}


def display_value(slot: str, v) -> str:
    if v is None:
        return "অজানা"
    if slot in ("target_crop", "last_crop"):
        return "যেকোনো (পরামর্শ চান)" if v == "any" else name_bn(v)
    if slot == "land_decimal":
        return f"{bn_num(v, 0)} শতাংশ"
    if slot == "season":
        return SEASONS_BN[v]
    if slot == "soil_type":
        return SOILS_BN[v]
    if slot == "irrigation":
        return IRRIGATION_BN[v]
    if slot == "ph":
        return bn_num(float(v), 1)
    if slot == "years_same":
        return f"{bn_num(int(v))} বছর"
    return str(v)


def inputs_view(slots: dict) -> dict:
    return {k: {"label_bn": SLOT_LABEL_BN[k], "value": s["value"], "display_bn": display_value(k, s["value"]),
                "source": s["source"]} for k, s in slots.items() if k in SLOT_LABEL_BN}


def headline(decision: dict) -> str:
    t, best = decision["target"], decision["best"]
    if t is None:
        return f"আপনার জমির জন্য সবচেয়ে উপযুক্ত ফসল: {best['name_bn']}" if best else "এই অবস্থায় কোনো ফসলের নিরাপদ সুপারিশ নেই"
    if t["rating"] == "go":
        return f"{t['name_bn']} চাষে এগিয়ে যাওয়া যায়"
    if t["rating"] == "caution":
        return f"{t['name_bn']} চাষ সম্ভব, তবে সতর্ক থাকতে হবে"
    alt = f" বরং {best['name_bn']} বিবেচনা করুন" if best else ""
    return f"{t['name_bn']} এই অবস্থায় সুপারিশ করা হচ্ছে না;{alt}"


def facts(slots: dict, decision: dict, evidence: list[dict], cmp: dict | None = None) -> dict:
    return {
        "inputs": {k: {"value": v["display_bn"], "source": v["source"]} for k, v in inputs_view(slots).items()},
        "confidence": decision["confidence"],
        "target": decision["target"],
        "alternatives": decision["alternatives"],
        "comparison": cmp,
        "evidence": evidence,
    }


def _scen_line(a: dict) -> str:
    s = a["scenarios"]
    return (f"ভালো পরিস্থিতিতে {bn_num(s['good']['profit'])} টাকা, গড়ে {bn_num(s['base']['profit'])} টাকা, "
            f"খারাপ পরিস্থিতিতে {bn_num(s['bad']['profit'])} টাকা (খরচ {bn_num(s['cost'])} টাকা)")


def template_narrative(slots: dict, decision: dict, evidence: list[dict], cmp: dict | None = None) -> str:
    lines = [f"**{headline(decision)}**", ""]
    t = decision["target"]
    if t:
        lines += [f"**{t['name_bn']} — {t['rating_bn']}**", f"সম্ভাব্য লাভ/লোকসান: {_scen_line(t)}।"]
        if t["scenarios"]["breakeven_price"]:
            lines.append(f"লোকসান এড়াতে প্রতি কেজি অন্তত {bn_num(t['scenarios']['breakeven_price'], 1)} টাকা দাম পেতে হবে।")
        if t["reasons_bn"]:
            lines += ["", "**মূল ঝুঁকি/বিবেচ্য বিষয়:**"] + [f"- {r}" for r in t["reasons_bn"]]
    if cmp:
        lines += ["", "**বর্তমান ফসল বনাম নতুন ফসল:**", f"- {cmp['verdict_bn']}"]
    if decision["alternatives"]:
        lines += ["", "**বিকল্প ফসল:**"]
        for a in decision["alternatives"]:
            lines.append(f"- {a['name_bn']} ({a['rating_bn']}): {_scen_line(a)}")
    if evidence:
        lines += ["", "**সূত্র:**"] + [f"- {e['source']}" + (f", পৃষ্ঠা {e['page']}" if e.get("page") else "") for e in evidence]
    assumed = [v["label_bn"] for v in inputs_view(slots).values() if v["source"] == "assumed"]
    lines += ["", "**মনে রাখুন:**"]
    if assumed:
        lines.append(f"- এই তথ্যগুলো অনুমান করা হয়েছে: {', '.join(assumed)}। সঠিক তথ্য দিলে ফল আরও নির্ভরযোগ্য হবে।")
    lines += ["- এটি পরামর্শ মাত্র; চূড়ান্ত সিদ্ধান্ত আপনার। বীজ, সার ও কীটনাশকের মাত্রা স্থানীয় উপ-সহকারী কৃষি কর্মকর্তার সাথে যাচাই করুন।"]
    return "\n".join(lines)
