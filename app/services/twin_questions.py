"""Questions the twin asks the farmer to correct its belief about the plant.

Rule-triggered (not LLM): each question fires only when the simulated/sensor state is uncertain or risky, and the answer
adjusts the hidden state (calibration). Keeps behaviour auditable.
ctx = {"crop","idx","st","aw","wx","rice","day"}
"""
from dataclasses import dataclass
from typing import Callable

OPEN_TTL_DAYS = 10


@dataclass(frozen=True)
class Q:
    id: str
    text_bn: str
    options: tuple              # ((value, label_bn), ...)
    cooldown: int
    when: Callable
    apply: Callable             # (state, value, ctx) -> note_bn


def _germ_when(s, c):
    return 6 <= s["day"] <= 12


def _germ_apply(s, v, c):
    s["stand"] = {"high": 1.0, "mid": 0.85, "low": 0.6}[v]
    return {"high": "চারা সংখ্যা ভালো, চালিয়ে যান।",
            "mid": "চারা কিছুটা কম, ফাঁকা জায়গায় নতুন চারা/বীজ বসানো যায়।",
            "low": "চারা অনেক কম। ফাঁকা জায়গায় আবার বীজ/চারা বসানো বিবেচনা করুন, ফলন কমার ঝুঁকি আছে।"}[v]


def _color_when(s, c):
    return c["idx"] >= 1 and c["day"] >= 12 and (s["N"] < 50 or s["P"] < 40)


def _color_apply(s, v, c):
    if v == "pale":
        s["N"] = max(0.0, s["N"] - 8)
        return "ফ্যাকাশে পাতা নাইট্রোজেন কমের লক্ষণ হতে পারে; নাইট্রোজেনের অনুমান কমিয়ে নিলাম।"
    if v == "lower_yellow":
        s["N"] = max(0.0, s["N"] - 12)
        return "নিচের পাতা হলুদ হলে নাইট্রোজেনের অভাব প্রায় নিশ্চিত; অনুমান সংশোধন করলাম।"
    if v == "purple":
        s["P"] = max(0.0, s["P"] - 12)
        return "বেগুনি/লালচে পাতা ফসফরাসের অভাবের লক্ষণ; অনুমান সংশোধন করলাম।"
    if s["N"] < 35:
        s["N"] = min(100.0, s["N"] + 8)
        return "পাতা সবুজ, তাই নাইট্রোজেন আসলে একটু ভালো আছে ধরে নিলাম।"
    return "পাতা সবুজ, ঠিক আছে।"


def _wilt_when(s, c):
    return c["day"] >= 5 and (c["aw"] < 55 or c["wx"].get("tmax", 0) >= 34)


def _wilt_apply(s, v, c):
    if v == "allday" and c["aw"] >= 60:
        s["ec"] = round(s["ec"] + 0.5, 2)
        return "মাটিতে পানি থাকা সত্ত্বেও সারাদিন ঝিমালে মূলের সমস্যা বা লবণাক্ততা সন্দেহ। সেন্সর ও মাটি পরীক্ষা করুন।"
    if v == "allday":
        return "পানির অভাব নিশ্চিত হলো। সেচ জরুরি।"
    if v == "noon":
        return "দুপুরে ঝিমানো গরমের কারণে স্বাভাবিক; সকালে ঠিক থাকলে চিন্তা নেই।"
    return "ঠিক আছে।"


def _spots_when(s, c):
    return s["dis"] >= 35


def _spots_apply(s, v, c):
    if v == "many":
        s["dis"] = max(s["dis"], 70.0)
        s["protect_needed"] = True
        return "রোগ নিশ্চিত। ছত্রাকনাশক স্প্রে ও কৃষি অফিসের পরামর্শ নিন।"
    if v == "few":
        s["dis"] = max(s["dis"], 45.0)
        return "অল্প দাগ, নজরে রাখুন ও আক্রান্ত পাতা সরান।"
    s["dis"] = max(0.0, s["dis"] - 25)
    return "রোগের লক্ষণ নেই, ঝুঁকির অনুমান কমালাম।"


def _pest_when(s, c):
    return c["idx"] >= 1 and c["idx"] < len(c["stages"]) - 1 and c["day"] >= 15


def _pest_apply(s, v, c):
    if v == "many":
        s["protect_needed"] = True
        return "পোকার আক্রমণ বেশি। দ্রুত ব্যবস্থা নিন (কৃষি অফিসের পরামর্শে)।"
    if v == "few":
        return "অল্প পোকা। ২-৩ দিন পর আবার দেখুন।"
    return "পোকার সমস্যা নেই।"


def _water_when(s, c):
    return (not c["rice"]) and (sum(s["last_rain"][-2:]) >= 40 or c["aw"] > 110)


def _water_apply(s, v, c):
    if v == "yes":
        s["wl_days"] += 1
        if c["aw"] < 100:
            s["w_mm"] = s["awc"] * 1.15
        return "জলাবদ্ধতা নিশ্চিত। নালা কেটে পানি বের করুন, নইলে শিকড় পচতে পারে।"
    return "জল জমেনি, ঠিক আছে।"


_NO_FEW_MANY = (("none", "না"), ("few", "অল্প"), ("many", "অনেক"))

QUESTIONS = (
    Q("leaf_spots", "পাতায় দাগ বা ছত্রাক দেখা যাচ্ছে?", _NO_FEW_MANY, 10, _spots_when, _spots_apply),
    Q("wilting", "দুপুরে গাছের পাতা কি ঝিমিয়ে পড়ছে?",
      (("no", "না"), ("noon", "দুপুরে ঝিমায়, সকালে ঠিক"), ("allday", "সারাদিন ঝিমিয়ে থাকে")), 10, _wilt_when, _wilt_apply),
    Q("standing_water", "জমিতে কি পানি জমে আছে?", (("no", "না"), ("yes", "হ্যাঁ")), 7, _water_when, _water_apply),
    Q("germination", "প্রায় কত শতাংশ বীজ/চারা গজিয়েছে?",
      (("high", "৮০% এর বেশি"), ("mid", "৫০–৮০%"), ("low", "৫০% এর কম")), 10_000, _germ_when, _germ_apply),
    Q("leaf_color", "পাতার রং কেমন?",
      (("green", "গাঢ় সবুজ"), ("pale", "ফ্যাকাশে/হালকা সবুজ"), ("lower_yellow", "নিচের পাতা হলুদ"),
       ("purple", "বেগুনি/লালচে")), 14, _color_when, _color_apply),
    Q("pests", "পোকা বা পোকার ক্ষতির চিহ্ন আছে?", _NO_FEW_MANY, 14, _pest_when, _pest_apply),
)
BY_ID = {q.id: q for q in QUESTIONS}


def public(q: Q, day_asked: int) -> dict:
    return {"id": q.id, "text_bn": q.text_bn, "day_asked": day_asked,
            "options": [{"value": v, "label_bn": l} for v, l in q.options]}


MAX_OPEN = 3   # "3 taps a day": never more than 3 unanswered questions at once


def raise_due(s: dict, ctx: dict) -> list[str]:
    """Open newly-due questions (priority = QUESTIONS order, max MAX_OPEN open); returns their ids."""
    new = []
    for q in QUESTIONS:
        if len(s["open_q"]) >= MAX_OPEN:
            break
        if q.id in s["open_q"]:
            continue
        last = s["q_last"].get(q.id)
        if last is not None and s["day"] - last < q.cooldown:
            continue
        if q.when(s, ctx):
            s["open_q"][q.id] = {"day": s["day"]}
            s["q_last"][q.id] = s["day"]
            new.append(q.id)
    return new


def expire(s: dict) -> None:
    for qid in [k for k, v in s["open_q"].items() if s["day"] - v["day"] > OPEN_TTL_DAYS]:
        del s["open_q"][qid]
