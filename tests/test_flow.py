import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import economics, extractor, validator
from app.data import crops

client = TestClient(app)

PROMPT = "আমার ৩০ শতাংশ জমি আছে, গত ৪ বছর ধান চাষ করেছি, এখন ভুট্টা চাষ করতে চাই।"


def test_extractor_example_prompt():
    r = extractor.regex_extract(PROMPT)
    assert r["land_decimal"] == 30
    assert r["last_crop"] == "rice"
    assert r["years_same"] == 4
    assert r["target_crop"] == "maize"


def test_extractor_bigha_and_word_numbers():
    r = extractor.regex_extract("আমার দুই বিঘা জমি, আলু চাষ করতে চাই। সেচের ব্যবস্থা আছে, দোআঁশ মাটি")
    assert r["land_decimal"] == 66
    assert r["target_crop"] == "potato"
    assert r["irrigation"] == "good" and r["soil_type"] == "doash"


def test_followup_loop_and_report():
    r = client.post("/advisor/analyze", json={"prompt": PROMPT}).json()
    assert r["status"] == "need_info" and r["round"] == 1
    slots = [q["slot"] for q in r["questions"]]
    assert slots == ["season", "irrigation"]
    sid = r["session_id"]
    r2 = client.post("/advisor/analyze", json={"session_id": sid, "answers": {"season": "rabi", "irrigation": "good"}}).json()
    assert r2["status"] == "done"
    rep = r2["report"]
    assert rep["target"]["crop_id"] == "maize"
    assert any("আগের ফসল" in x for x in rep["target"]["reasons_bn"])  # cereal->cereal rotation warning
    assert rep["narrative_source"] == "template" and "সুপারিশ" in rep["narrative_bn"] or rep["narrative_bn"]
    again = client.get(f"/advisor/report/{sid}").json()
    assert again["report"]["summary"]["headline_bn"] == rep["summary"]["headline_bn"]


def test_unknown_answers_become_assumed_and_lower_confidence():
    r = client.post("/advisor/analyze", json={"prompt": PROMPT}).json()
    r2 = client.post("/advisor/analyze", json={"session_id": r["session_id"],
                     "answers": {"season": "unknown", "irrigation": "unknown"}}).json()
    s = r2["report"]["summary"]
    assert r2["status"] == "done" and s["confidence"] < 0.7
    assert r2["report"]["inputs"]["irrigation"]["source"] == "assumed"


def test_max_two_rounds_then_defaults():
    r = client.post("/advisor/analyze", json={"prompt": "জমি আছে"}).json()
    assert r["status"] == "need_info"
    r = client.post("/advisor/analyze", json={"session_id": r["session_id"], "answers": {}}).json()
    assert r["status"] == "need_info" and r["round"] == 2
    r = client.post("/advisor/analyze", json={"session_id": r["session_id"], "answers": {}}).json()
    assert r["status"] == "done"


def test_solanaceae_rotation_blocks_tomato_after_potato():
    r = client.post("/advisor/analyze", json={"prompt": "আলু চাষ করেছিলাম, এখন টমেটো করতে চাই", "answers": None}).json()
    sid = r["session_id"]
    r = client.post("/advisor/analyze", json={"session_id": sid, "answers": {
        "land_decimal": 33, "season": "rabi", "irrigation": "good"}}).json()
    assert r["status"] == "done"
    t = r["report"]["target"]
    assert t["status"] == "blocked" and t["rating"] == "no"
    assert r["report"]["alternatives"]


def test_wrong_season_blocks_when_user_stated():
    r = client.post("/advisor/analyze", json={"prompt": "বোরো ধান করতে চাই", "answers": None}).json()
    r = client.post("/advisor/analyze", json={"session_id": r["session_id"], "answers": {
        "land_decimal": 33, "last_crop": "none", "season": "kharif1", "irrigation": "good"}}).json()
    assert r["report"]["target"]["status"] == "blocked"


def test_review_flow_requires_expert_role():
    r = client.post("/advisor/analyze", json={"prompt": PROMPT}).json()
    sid = r["session_id"]
    client.post("/advisor/analyze", json={"session_id": sid, "answers": {"season": "unknown", "irrigation": "unknown"}})
    assert client.post(f"/advisor/report/{sid}/request-review").json()["review_status"] == "pending"
    assert client.get("/expert/queue").status_code == 403
    q = client.get("/expert/queue", headers={"x-dev-role": "expert"}).json()
    assert any(x["session_id"] == sid for x in q)
    ok = client.post(f"/expert/review/{sid}", json={"verdict": "agree", "note": "ok"}, headers={"x-dev-role": "expert"})
    assert ok.status_code == 200


def test_session_ownership():
    r = client.post("/advisor/analyze", json={"prompt": PROMPT}, headers={"x-dev-user": "alice"}).json()
    assert client.get(f"/advisor/report/{r['session_id']}", headers={"x-dev-user": "bob"}).status_code in (403, 404)


def test_economics_numbers():
    c = crops()["boro"]
    e = economics.scenarios(c, 10, 0)
    assert e["cost"] == 6000 and e["base"]["profit"] == 24 * 30 * 10 - 6000


def test_validator_rejects_invented_money_figures():
    facts = {"target": {"scenarios": {"base": {"profit": 1200}}}}
    good = "ভুট্টা চাষে গড়ে ১,২০০ টাকা লাভ হতে পারে, তবে সতর্ক থাকুন এবং স্থানীয় অফিসে যাচাই করুন।"
    bad = "ভুট্টা চাষে গড়ে ৯,৫০০ টাকা লাভ হতে পারে, তবে সতর্ক থাকুন এবং স্থানীয় অফিসে যাচাই করুন।"
    assert validator.validate(good, facts, "ভুট্টা")[0]
    assert not validator.validate(bad, facts, "ভুট্টা")[0]


def test_compare_verdict_logic():
    from app.services.compare import _verdict

    def a(base, bad, cost=1000, rating="caution", status="ok"):
        return {"status": status, "rating": rating,
                "scenarios": {"cost": cost, "base": {"profit": base}, "bad": {"profit": bad}}}

    assert _verdict(a(0, -500), a(400, -400)) == "switch_better"
    assert _verdict(a(0, -100), a(400, -600)) == "switch_riskier"
    assert _verdict(a(400, 0), a(0, -300)) == "stay_better"
    assert _verdict(a(100, 0), a(120, 0)) == "similar"
    assert _verdict(a(0, 0, status="blocked", rating="no"), a(100, 0)) == "current_not_feasible"
    assert _verdict(a(-5, -100, rating="no"), a(-5, -100, rating="no")) == "both_weak"
    assert _verdict(a(300, 0), a(-5, -100, rating="no")) == "stay_better"


def test_report_contains_comparison_for_switch():
    r = client.post("/advisor/analyze", json={"prompt": PROMPT}).json()
    r = client.post("/advisor/analyze", json={"session_id": r["session_id"],
                    "answers": {"season": "rabi", "irrigation": "good"}}).json()
    cmp = r["report"]["comparison"]
    assert cmp and cmp["current"]["crop_id"] == "boro" and cmp["new"]["crop_id"] == "maize"
    assert "বর্তমান ফসল বনাম নতুন ফসল" in r["report"]["narrative_bn"]


def test_no_comparison_without_current_crop():
    r = client.post("/advisor/analyze", json={"prompt": "ভুট্টা চাষ করতে চাই"}).json()
    r = client.post("/advisor/analyze", json={"session_id": r["session_id"], "answers": {
        "land_decimal": 33, "last_crop": "none", "season": "rabi", "irrigation": "good"}}).json()
    assert r["report"]["comparison"] is None


def test_ui_served_and_api_still_reachable():
    r = client.get("/")
    assert r.status_code == 200 and "GrowthTwin" in r.text
    assert client.get("/health").json()["ok"] is True
