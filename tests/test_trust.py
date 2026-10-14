import asyncio

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.twin_store import get_twin_store
from app.main import app

client = TestClient(app)


def put(uid, profit, outcome="harvested", crop="jute"):
    asyncio.run(get_twin_store().save_harvest({
        "user_id": uid, "plot_id": f"{uid}-{crop}", "crop_id": crop, "area": 10, "yield_kg": 0 if outcome == "dead" else 100,
        "yield_kg_per_decimal": 0 if outcome == "dead" else 10, "revenue": 0, "cost": 1000, "profit": profit, "days": 120,
        "health": 80, "start_date": "2026-03-01", "outcome": outcome, "source": "simulation"}))


def test_hidden_until_enough_farmers(monkeypatch):
    monkeypatch.setattr(get_settings(), "trust_min_farmers", 99)
    put("t-a", 500)
    d = client.get("/trust/crop/jute", headers={"X-Dev-User": "t-a"}).json()
    assert d["enough"] is False and "hist" not in d and "median_profit_per_decimal" not in d and d["n_farmers"] >= 1
    assert "user_id" not in str(d)


def test_distribution_includes_failures_and_my_rank(monkeypatch):
    monkeypatch.setattr(get_settings(), "trust_min_farmers", 5)
    for i, pr in enumerate([-800, -200, 100, 400, 900, 1500]):
        put(f"t-u{i}", pr)
    put("t-dead", -1000, "dead")
    d = client.get("/trust/crop/jute", headers={"X-Dev-User": "t-u5"}).json()
    assert d["enough"] and d["failed"] >= 1 and 0 < d["profit_share"] < 1
    assert sum(d["hist"]["counts"]) == d["n_plots"]
    assert d["mine"][0]["better_than"] == 1.0                       # best of everyone else
    assert d["sources"].get("simulation")


def test_unknown_crop_404():
    assert client.get("/trust/crop/nope", headers={"X-Dev-User": "x"}).status_code == 404
