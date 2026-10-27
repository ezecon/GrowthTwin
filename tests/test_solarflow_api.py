from fastapi.testclient import TestClient
from app.main import app
from app.core.auth import current_user, User

app.dependency_overrides[current_user] = lambda: User(id="solarflow-test", role="farmer")
client = TestClient(app)


def test_solarflow_plan_is_advisory_and_returns_candidates():
    response = client.post("/solarflow/plan", json={
        "soil_moisture_pct": 15, "target_moisture_pct": 40,
        "area_m2": 100, "solar_power_w": 100, "pump_power_w": 60,
        "battery_capacity_wh": 240, "battery_pct": 80,
        "battery_reserve_pct": 25, "tank_water_l": 1000,
        "pump_flow_l_min": 5, "forecast_rain_mm": 0, "rain_probability": 0,
    })
    assert response.status_code == 200
    body = response.json()
    assert body["advisory_only"] is True
    assert body["trained_ml_model"] is False
    assert body["recommendation"] == "solar_now"
    assert {x["action"] for x in body["candidates"]} == {"solar_now", "battery_now", "wait"}


def test_solarflow_rejects_invalid_probability():
    response = client.post("/solarflow/plan", json={"rain_probability": 1.5})
    assert response.status_code == 422


def teardown_module():
    app.dependency_overrides.clear()


def test_solarflow_page_is_served_and_main_ui_has_nav_link():
    page = client.get("/solarflow.html")
    home = client.get("/")
    assert page.status_code == 200 and "SolarFlow AI" in page.text
    assert home.status_code == 200 and "/solarflow.html" in home.text
