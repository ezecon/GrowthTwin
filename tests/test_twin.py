import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import twin_engine as te

client = TestClient(app)
H = {"X-Dev-User": "farmer1"}


def mk(**kw):
    base = dict(crop_id="boro", soil_type="doash", area_decimal=30, seed=3, start_date="2026-11-20")
    base.update(kw)
    return client.post("/twin/plots", json=base, headers=H).json()


def test_full_life_cycle_auto_harvest():
    s = te.new_plot("u", "t", "wheat", "doash", 30, seed=3, start_date="2026-11-25", config={"auto_inputs": True})
    te.advance(s, 400, stop_on_alert=False, auto_harvest=True)
    assert s["status"] == "harvested" and s["result"]["yield_kg"] > 0 and s["day"] == 110


def test_deterministic_replay():
    a = te.new_plot("u", "t", "potato", "doash", 10, seed=7, start_date="2026-11-15")
    b = te.new_plot("u", "t", "potato", "doash", 10, seed=7, start_date="2026-11-15")
    la = te.advance(a, 30, stop_on_alert=False)["logs"]
    lb = te.advance(b, 30, stop_on_alert=False)["logs"]
    assert la == lb


def test_emergency_pump_turns_on_then_off():
    s = te.new_plot("u", "t", "maize", "beley", 30, seed=5, start_date="2026-11-20")
    s["w_mm"] = s["awc"] * 0.15                      # very dry
    r = te.advance(s, 6, stop_on_alert=False)
    kinds = [(e["payload"].get("type"), e["payload"].get("reason")) for e in r["events"] if e["kind"] == "auto_action"]
    assert ("pump_on", "emergency") in kinds and ("pump_off", "target") in kinds
    assert not s["pump_on"]


def test_no_irrigation_means_drought_death():
    s = te.new_plot("u", "t", "maize", "doash", 30, seed=5, start_date="2026-11-20", config={"auto_irrigation": False})
    te.advance(s, 300, stop_on_alert=False)
    assert s["status"] == "dead" and "খরা" in s["end_reason"]


def test_low_ph_triggers_lime_recommendation_and_fixes_it():
    s = te.new_plot("u", "t", "maize", "doash", 30, ph=4.8, seed=5, start_date="2026-11-20")
    r = te.advance(s, 3)
    assert "lime" in s["pending_actions"]
    te.apply_action(s, "lime")
    assert s["ph"] >= 5.8 and "lime" not in s["pending_actions"]


def test_questions_calibrate_belief():
    s = te.new_plot("u", "t", "maize", "doash", 30, seed=5, start_date="2026-11-20")
    s["N"] = 44.0
    te.advance(s, 14, stop_on_alert=False)
    assert "leaf_color" in s["open_q"]
    before = s["N"]
    te.answer(s, {"leaf_color": "lower_yellow"})
    assert s["N"] < before and "leaf_color" not in s["open_q"]


def test_harvest_only_when_ready():
    s = te.new_plot("u", "t", "mustard", "doash", 10, seed=1, start_date="2026-11-10")
    try:
        te.apply_action(s, "harvest")
        assert False
    except ValueError:
        pass


def test_api_flow_and_ownership():
    p = mk()
    pid = p["id"]
    assert p["day"] == 0 and p["status"] == "growing"
    r = client.post(f"/twin/plots/{pid}/advance", json={"days": 20, "stop_on_alert": False}, headers=H).json()
    assert r["days_run"] == 20 and len(r["logs"]) == 20
    assert len(client.get(f"/twin/plots/{pid}/logs", headers=H).json()) == 20
    assert client.get(f"/twin/plots/{pid}", headers={"X-Dev-User": "other"}).status_code == 404
    assert client.get("/twin/plots", headers=H).status_code == 200
    s = client.get(f"/twin/plots/{pid}/summary", headers=H).json()
    assert s["source"] == "template" and "বোরো" in s["text"]
    assert client.post(f"/twin/plots/{pid}/action", json={"type": "bogus"}, headers=H).status_code == 400
    assert client.delete(f"/twin/plots/{pid}", headers=H).status_code == 200


def test_forecast_has_vs_normal_label():
    p = mk()
    f = p["forecast"]
    assert len(f) == 7 and all(x["vs_normal"] in ("more", "less", "normal") for x in f)


def test_single_page_ui_has_both_sections_and_login():
    r = client.get("/")
    assert r.status_code == 200 and 'id="s1"' in r.text and 'id="s2"' in r.text and 'id="auth"' in r.text


def test_sentinel_dashboard_is_served():
    r = client.get("/sentinel.html")
    assert r.status_code == 200
    assert "Reality Gap Engine" in r.text and "/sensor-readings?limit=100" in r.text


# ---------------- combined-workflow additions ----------------
from app.services import disease_models as dm
from app.services import twin_questions as tq


def test_alerts_carry_why_and_light_factor_exists():
    s = te.new_plot("u", "t", "maize", "beley", 30, seed=5, start_date="2026-11-20")
    s["w_mm"] = s["awc"] * 0.15
    r = te.advance(s, 2, stop_on_alert=False)
    emerg = [e for e in r["events"] if e["kind"] == "alert" and e["payload"]["key"] == "emergency"][0]
    assert emerg["payload"]["why"]["rule_bn"] and len(emerg["payload"]["why"]["facts"]) >= 3
    auto = [e for e in r["events"] if e["kind"] == "auto_action" and e["payload"]["key"] == "pump_on"][0]
    assert auto["payload"]["why"]
    assert "light" in s["last_factors"] and "sun_h" in s["last_wx"]


def test_question_cap_is_three():
    s = te.new_plot("u", "t", "maize", "doash", 30, seed=5, start_date="2026-11-20")
    s["day"], s["N"], s["dis"] = 20, 30.0, 50.0
    crop = te.crops()["maize"]
    idx, st = te.cs.stage_at("maize", 20, crop.duration_days)
    ctx = {"crop": crop, "idx": idx, "st": st, "stages": te.cs.stages("maize"), "aw": 40.0, "wx": {"tmax": 30},
           "rice": False, "day": 20}
    assert len(tq.raise_due(s, ctx)) == 3 and len(s["open_q"]) == 3


def test_manual_pump_has_max_runtime_failsafe():
    s = te.new_plot("u", "t", "maize", "doash", 30, seed=5, start_date="2026-11-20", config={"auto_irrigation": False})
    s["w_mm"] = s["awc"] * 0.1
    te.apply_action(s, "pump", on=True)
    r = te.advance(s, 2, stop_on_alert=False)
    assert not s["pump_on"]
    assert any(e["payload"].get("reason") == "failsafe" for e in r["events"] if e["kind"] == "auto_action")


def test_photo_is_advisory_only_and_goes_to_review():
    dm.register("maize", lambda img: ("leaf_blight", "পাতা ঝলসানো", 0.78, False))
    try:
        s = te.new_plot("u", "t", "maize", "doash", 30, seed=5, start_date="2026-11-20")
        te.advance(s, 3, stop_on_alert=False)
        dis_before, pump_before = s["dis"], s["pump_on"]
        pred = dm.predict("maize", b"\xff\xd8\xff-fake")
        assert pred["status"] == "ok" and pred["needs_review"]
        te.record_photo(s, pred)
        assert s["dis"] == dis_before and s["pump_on"] == pump_before and not s["protect_needed"]
        assert [a["key"] for a in s["alerts"]][-1] == "photo_disease"
        rid = s["review_pending"][0]["id"]
        te.resolve_review(s, rid, "disease", "leaf_blight", "", "expert1")
        assert s["protect_needed"] and not [r for r in s["review_pending"] if r["status"] == "pending"]
    finally:
        dm.unregister("maize")


def test_low_confidence_photo_is_unknown_and_no_model_falls_back():
    assert dm.predict("jute", b"\xff\xd8\xff")["status"] == "no_model"
    dm.register("jute", lambda img: ("x", None, 0.4, False))
    try:
        assert dm.predict("jute", b"\xff\xd8\xff")["status"] == "unknown"
    finally:
        dm.unregister("jute")
    s = te.new_plot("u", "t", "jute", "doash", 10, seed=1, start_date="2027-03-20")
    te.record_photo(s, {"status": "no_model"})
    assert "leaf_spots" in s["open_q"]


def test_harvest_record_per_decimal():
    s = te.new_plot("u", "t", "wheat", "doash", 20, seed=3, start_date="2026-11-25", config={"auto_inputs": True})
    te.advance(s, 400, stop_on_alert=False, auto_harvest=True)
    rec = te.harvest_record(s)
    assert rec["plot_id"] == s["id"] and abs(rec["yield_kg_per_decimal"] - rec["yield_kg"] / 20) < 0.01


def test_api_photo_why_sms_harvest_and_expert():
    import base64
    dm.register("boro", lambda img: ("blast", "ব্লাস্ট", 0.75, False))
    try:
        p = mk(sms_enabled=True, phone="01712345678", seed=11)
        pid = p["id"]
        assert p["config"]["sms_enabled"] and p["config"]["phone_masked"] == "0171****78" and "phone" not in p["config"]
        assert client.post("/twin/plots", json={"crop_id": "boro", "area_decimal": 5, "phone": "123"}, headers=H).status_code == 400
        bad = client.post(f"/twin/plots/{pid}/photo", json={"image_b64": base64.b64encode(b"not an image").decode()}, headers=H)
        assert bad.status_code == 400
        ok = client.post(f"/twin/plots/{pid}/photo", json={"image_b64": base64.b64encode(b"\xff\xd8\xff" + b"0" * 50).decode()}, headers=H)
        assert ok.status_code == 200 and ok.json()["prediction"]["needs_review"]
        reviews = client.get("/twin/expert/reviews", headers={**H, "X-Dev-Role": "expert"}).json()
        assert any(r["plot_id"] == pid for r in reviews)
        assert client.get("/twin/expert/reviews", headers=H).status_code == 403
        rid = [r for r in reviews if r["plot_id"] == pid][0]["review_id"]
        res = client.post(f"/twin/expert/reviews/{pid}/{rid}", json={"verdict": "healthy"}, headers={**H, "X-Dev-Role": "expert"})
        assert res.status_code == 200
        client.post(f"/twin/plots/{pid}/advance", json={"days": 400, "stop_on_alert": False, "auto_harvest": True}, headers=H)
        hs = client.get("/twin/harvests", headers=H).json()
        stats = client.get("/twin/harvests/stats", headers=H).json()
        assert hs and hs[0]["crop_id"] == "boro"
        # This deterministic boro scenario can end in crop failure. Failed crops
        # must remain visible in history but must not contaminate harvested-yield
        # averages used as real outcome evidence.
        if hs[0].get("outcome", "harvested") == "harvested":
            assert stats and stats[0]["crop_id"] == "boro"
        else:
            assert hs[0]["outcome"] == "dead"
            assert stats == []
    finally:
        dm.unregister("boro")


def test_reality_gap_endpoint_corrects_state_and_retains_measurement():
    p = mk()
    pid = p["id"]
    before = client.get(f"/twin/plots/{pid}", headers=H).json()["soil_now"]["aw"]
    response = client.post(
        f"/twin/plots/{pid}/readings",
        json={"moisture_pct": 20, "source": "sensor", "moisture_quality": "valid"},
        headers=H,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    gap = data["reality_gap"]
    assert gap["estimator_version"] == "reality-gap-v1"
    assert gap["measured_value"] == 20
    assert gap["predicted_value"] == pytest.approx(before, abs=1)
    assert gap["measurement_used"] is True
    assert data["event"]["payload"]["measured_moisture_pct"] == 20
    history = client.get(f"/twin/plots/{pid}/reality-gap", headers=H)
    assert history.status_code == 200
    assert history.json()["latest"]["measured_value"] == 20


def test_suspect_sensor_reading_does_not_change_twin_moisture():
    p = mk()
    pid = p["id"]
    before = client.get(f"/twin/plots/{pid}", headers=H).json()["soil_now"]["aw"]
    response = client.post(
        f"/twin/plots/{pid}/readings",
        json={"moisture_pct": 5, "source": "sensor", "moisture_quality": "suspect"},
        headers=H,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["reality_gap"]["measurement_used"] is False
    assert data["plot"]["soil_now"]["aw"] == before


def test_readings_reject_out_of_range_moisture():
    p = mk()
    response = client.post(
        f"/twin/plots/{p['id']}/readings",
        json={"moisture_pct": 200, "source": "sensor"},
        headers=H,
    )
    assert response.status_code == 422


def test_sensor_calibration_and_device_ingestion(monkeypatch):
    from types import SimpleNamespace
    from datetime import datetime, timezone
    from app.api import twin as twin_api

    monkeypatch.setattr(twin_api, "get_settings", lambda: SimpleNamespace(sensor_ingest_token="test-device-secret"))
    p = mk()
    pid = p["id"]
    calibration = client.post(
        f"/twin/plots/{pid}/sensor-calibration",
        json={"device_id": "esp32-plot-1", "adc_at_wilting_point": 3000, "adc_at_field_capacity": 1500},
        headers=H,
    )
    assert calibration.status_code == 200, calibration.text
    device_token = calibration.json()["device_token"]

    payload = {
        "plot_id": pid,
        "device_id": "esp32-plot-1",
        "sequence": 1,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "raw_moisture_adc": 2250,
        "temperature_c": 29.5,
        "humidity_pct": 74,
    }
    rejected = client.post("/twin/device/readings", json=payload, headers={"X-Sensor-Token": "wrong"})
    assert rejected.status_code == 401
    response = client.post("/twin/device/readings", json=payload, headers={"X-Sensor-Token": device_token})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["accepted"] is True
    assert data["calibrated_moisture_pct"] == 50
    assert data["quality"] == "valid"

    duplicate = client.post("/twin/device/readings", json=payload, headers={"X-Sensor-Token": device_token})
    assert duplicate.status_code == 409
    reality = client.get(f"/twin/plots/{pid}/reality-gap", headers=H).json()
    assert reality["latest_device_reading"]["raw_moisture_adc"] == 2250
    assert reality["latest_device_reading"]["calibrated_moisture_pct"] == 50


def test_sensor_ingestion_disabled_without_secret(monkeypatch):
    from types import SimpleNamespace
    from app.api import twin as twin_api

    monkeypatch.setattr(twin_api, "get_settings", lambda: SimpleNamespace(sensor_ingest_token=""))
    response = client.post("/twin/device/readings", json={
        "plot_id": "missing", "device_id": "esp32", "sequence": 1,
        "timestamp": "2026-10-13T12:00:00Z", "raw_moisture_adc": 2000,
    }, headers={"X-Sensor-Token": "anything"})
    assert response.status_code == 503


def test_device_ingestion_is_exposed_in_durable_sensor_history(monkeypatch):
    from types import SimpleNamespace
    from datetime import datetime, timezone
    from app.api import twin as twin_api

    monkeypatch.setattr(twin_api, "get_settings", lambda: SimpleNamespace(sensor_ingest_token="history-secret"))
    p = mk()
    pid = p["id"]
    cal = client.post(f"/twin/plots/{pid}/sensor-calibration", json={
        "device_id": "esp32-history", "adc_at_wilting_point": 3000,
        "adc_at_field_capacity": 1500,
    }, headers=H)
    assert cal.status_code == 200, cal.text
    device_token = cal.json()["device_token"]
    reading = client.post("/twin/device/readings", json={
        "plot_id": pid, "device_id": "esp32-history", "sequence": 44,
        "timestamp": datetime.now(timezone.utc).isoformat(), "raw_moisture_adc": 2250,
    }, headers={"X-Sensor-Token": device_token})
    assert reading.status_code == 200, reading.text

    history = client.get(f"/twin/plots/{pid}/sensor-readings?limit=10", headers=H)
    assert history.status_code == 200, history.text
    body = history.json()
    assert body["count"] == 1
    assert body["readings"][0]["sequence"] == 44
    assert body["readings"][0]["calibrated_moisture_pct"] == 50
    assert client.get(f"/twin/plots/{pid}/sensor-readings", headers={"X-Dev-User": "someone-else"}).status_code == 404


def test_sensor_history_limit_validation():
    p = mk()
    assert client.get(f"/twin/plots/{p['id']}/sensor-readings?limit=0", headers=H).status_code == 422


def test_sensor_simulation_generates_labelled_readings_without_changing_plot():
    p = mk()
    pid = p["id"]
    before = client.get(f"/twin/plots/{pid}", headers=H).json()
    response = client.post(f"/twin/plots/{pid}/sensor-simulation", json={"count": 5}, headers=H)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["created"] == 5
    assert result["source"] == "simulation"
    assert all(r["source"] == "simulation" for r in result["readings"])
    history = client.get(f"/twin/plots/{pid}/sensor-readings?limit=10", headers=H).json()
    assert history["count"] == 5
    assert all(r["source"] == "simulation" for r in history["readings"])
    after = client.get(f"/twin/plots/{pid}", headers=H).json()
    assert after["day"] == before["day"]
    assert after["health"] == before["health"]
