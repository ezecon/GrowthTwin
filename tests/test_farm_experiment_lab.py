from fastapi.testclient import TestClient

from app.main import app
from app.core.twin_store import get_twin_store

client = TestClient(app)
H = {"X-Dev-User": "experiment-farmer"}


def make_plot():
    response = client.post("/twin/plots", json={
        "crop_id": "boro", "area_decimal": 20, "soil_type": "doash",
        "seed": 42, "start_date": "2026-11-20", "auto_irrigation": True,
    }, headers=H)
    assert response.status_code == 200, response.text
    return response.json()


def test_irrigation_experiment_is_saved_and_does_not_change_live_plot():
    plot = make_plot()
    pid = plot["id"]
    before = client.get(f"/twin/plots/{pid}", headers=H).json()
    response = client.post(f"/twin/plots/{pid}/experiments", json={
        "name": "Compare irrigation", "horizon_days": 14,
        "intervention": "irrigation", "irrigation_auto": False,
    }, headers=H)
    assert response.status_code == 200, response.text
    experiment = response.json()
    after = client.get(f"/twin/plots/{pid}", headers=H).json()
    assert experiment["assumptions"]["same_starting_state"] is True
    assert experiment["assumptions"]["same_weather_seed"] is True
    assert experiment["assumptions"]["live_plot_modified"] is False
    assert experiment["baseline"]["days_simulated"] == 14
    assert experiment["scenario"]["days_simulated"] == 14
    assert after["day"] == before["day"]
    assert after["soil_now"] == before["soil_now"]
    history = client.get(f"/twin/plots/{pid}/experiments", headers=H)
    assert history.status_code == 200
    assert history.json()["experiments"][0]["id"] == experiment["id"]


def test_fertilizer_experiment_and_validation():
    plot = make_plot()
    pid = plot["id"]
    response = client.post(f"/twin/plots/{pid}/experiments", json={
        "horizon_days": 7, "intervention": "fertilizer", "nutrient": "N",
    }, headers=H)
    assert response.status_code == 200, response.text
    assert response.json()["intervention_bn"]
    invalid = client.post(f"/twin/plots/{pid}/experiments", json={
        "horizon_days": 7, "intervention": "fertilizer",
    }, headers=H)
    assert invalid.status_code == 400


def test_experiment_requires_plot_ownership():
    plot = make_plot()
    response = client.post(f"/twin/plots/{plot['id']}/experiments", json={
        "horizon_days": 7, "intervention": "irrigation", "irrigation_auto": False,
    }, headers={"X-Dev-User": "someone-else"})
    assert response.status_code == 404
