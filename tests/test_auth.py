from fastapi.testclient import TestClient

from app.api import auth as auth_api
from app.main import app

client = TestClient(app)
SESSION = {"access_token": "a" * 40, "refresh_token": "r" * 20, "expires_in": 3600,
           "user": {"id": "u1", "email": "a@b.com", "app_metadata": {"role": "farmer"},
                    "user_metadata": {"full_name": "রহিম", "phone": ""}}}


def patch(monkeypatch, result):
    calls = []

    async def fake(method, path, **kw):
        calls.append((method, path, kw))
        return result

    monkeypatch.setattr(auth_api, "_gotrue", fake)
    return calls


def test_config_public():
    r = client.get("/auth/config")
    assert r.status_code == 200 and set(r.json()["roles"]) == {"farmer", "expert", "admin"}


def test_login_returns_session(monkeypatch):
    calls = patch(monkeypatch, SESSION)
    r = client.post("/auth/login", json={"email": "A@B.com ", "password": "x"})
    assert r.status_code == 200 and r.json()["user"]["role"] == "farmer"
    assert calls[0][2]["json"]["email"] == "a@b.com"


def test_register_never_sends_a_role(monkeypatch):
    calls = patch(monkeypatch, SESSION)
    r = client.post("/auth/register", json={"email": "x@y.com", "password": "abcd1234", "full_name": "রহিম",
                                            "role_request": "admin"})
    assert r.status_code == 200
    body = calls[0][2]["json"]
    assert "app_metadata" not in body and body["data"]["role_request"] == "farmer"   # admin cannot be self-requested


def test_register_confirm_email_flow(monkeypatch):
    patch(monkeypatch, {"id": "u2"})
    r = client.post("/auth/register", json={"email": "n@y.com", "password": "abcd1234", "full_name": "করিম"})
    assert r.json()["status"] == "confirm_email"


def test_register_validation(monkeypatch):
    patch(monkeypatch, SESSION)
    assert client.post("/auth/register", json={"email": "bad", "password": "abcd1234", "full_name": "রহিম"}).status_code == 422
    assert client.post("/auth/register", json={"email": "x@y.com", "password": "abcdefgh", "full_name": "রহিম"}).status_code == 422
    assert client.post("/auth/register", json={"email": "x@y.com", "password": "abcd1234", "full_name": "রহিম",
                                               "phone": "123"}).status_code == 422


def test_admin_endpoints_need_admin_role():
    assert client.get("/admin/users", headers={"X-Dev-Role": "farmer"}).status_code == 403
    assert client.post("/admin/users/u1/role", json={"role": "expert"}, headers={"X-Dev-Role": "expert"}).status_code == 403


def test_readings_replace_simulated_values():
    H = {"X-Dev-User": "farmer9"}
    p = client.post("/twin/plots", json={"crop_id": "maize", "area_decimal": 30, "seed": 5,
                                         "start_date": "2026-11-20"}, headers=H).json()
    r = client.post(f"/twin/plots/{p['id']}/readings", json={"ph": 4.8, "moisture_pct": 60}, headers=H)
    assert r.status_code == 200 and r.json()["plot"]["soil_now"]["ph"] == 4.8
    assert client.post(f"/twin/plots/{p['id']}/readings", json={}, headers=H).status_code == 400


def test_own_yields_attached_to_report():
    from app.api.advisor import _with_own_yields
    import asyncio
    from app.core.twin_store import get_twin_store
    asyncio.run(get_twin_store().save_harvest({"user_id": "h1", "plot_id": "p1", "crop_id": "maize", "area": 30,
                                               "yield_kg": 600, "yield_kg_per_decimal": 20, "days": 110}))
    rep = asyncio.run(_with_own_yields({"target": {"crop_id": "maize"}, "comparison": None}, "h1"))
    assert rep["own_yields"][0]["avg"] == 20.0
    other = asyncio.run(_with_own_yields({"target": {"crop_id": "maize"}}, "someone_else"))
    assert other["own_yields"] == []
