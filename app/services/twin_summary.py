"""Plain-language Bengali status summary. Deterministic template; Grok polishes it only if a key is set,
and the polished text is rejected if it contains any number not present in the facts."""
import re

from . import llm
from .twin_engine import bn

_BN2EN = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
STATUS_BN = {"growing": "বেড়ে উঠছে", "ready": "কাটার উপযুক্ত", "harvested": "ফসল কাটা হয়েছে", "dead": "মারা গেছে"}


def template(v: dict) -> str:
    so, est = v["soil_now"], v["estimate"]
    lines = [f"**{v['name']} ({v['crop']['name_bn']})**: দিন {bn(v['day'])}/{bn(v['duration'])}, পর্যায়: {v['stage']['name_bn']}, "
             f"অবস্থা: {STATUS_BN[v['status']]}। গাছের স্বাস্থ্য {bn(v['health'])}%।",
             f"মাটির আর্দ্রতা {bn(so['aw'])}%, pH {bn(so['ph'], 1)}, পাম্প {'চালু' if v['pump_on'] else 'বন্ধ'}।"]
    low = [n for n in "NPK" if so[n] < v["thresholds"]["low_level"]]
    if low:
        lines.append(f"সারের ঘাটতি: {', '.join(low)}।")
    if v["pending_actions"]:
        lines.append("এখন করণীয়: " + "; ".join(a["title_bn"] for a in v["pending_actions"]) + "।")
    if v["forecast"]:
        r2 = v["forecast"][1]
        rel = {"more": "স্বাভাবিকের চেয়ে বেশি", "less": "স্বাভাবিকের চেয়ে কম", "normal": "স্বাভাবিক"}[r2["vs_normal"]]
        lines.append(f"২ দিন পরের বৃষ্টির পূর্বাভাস: প্রায় {bn(r2['rain_mm'])} মিমি ({rel})।")
    if est:
        lines.append(f"বর্তমান অবস্থায় আনুমানিক ফলন {bn(est['yield_kg'])} কেজি, লাভ/লোকসান {bn(est['profit'])} টাকা।")
    if v["result"]:
        lines.append(f"চূড়ান্ত ফলাফল: ফলন {bn(v['result']['yield_kg'])} কেজি, লাভ/লোকসান {bn(v['result']['profit'])} টাকা।"
                     + (f" কারণ: {v['end_reason']}।" if v["status"] == "dead" else ""))
    return "\n".join("- " + l if i else l for i, l in enumerate(lines))


def _nums(t: str) -> set:
    return set(re.findall(r"\d+", t.translate(_BN2EN)))


async def summarize(v: dict) -> tuple[str, str]:
    base = template(v)
    if not llm.available():
        return base, "template"
    out = await llm.chat(
        [{"role": "system", "content": "তুমি কৃষকের সহকারী। শুধু নিচের তথ্য ব্যবহার করে ৪-৫ লাইনে সহজ বাংলায় অবস্থা ও করণীয় লেখো। "
                                       "কোনো নতুন সংখ্যা বা তথ্য বানাবে না।"},
         {"role": "user", "content": base}], max_tokens=400)
    if out and _nums(out) <= _nums(base):
        return out, "llm"
    return base, "template"
