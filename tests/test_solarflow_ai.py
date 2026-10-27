from app.services.solarflow_ai import SolarFlowInput, recommend


def test_wet_soil_prefers_waiting():
    result = recommend(SolarFlowInput(soil_moisture_pct=48, target_moisture_pct=35,
                                      forecast_rain_mm=0, rain_probability=0,
                                      tank_water_l=500))
    assert result["recommendation"] == "wait"
    assert result["pump_minutes"] == 0
    assert result["trained_ml_model"] is False


def test_solar_first_when_demand_and_solar_available():
    result = recommend(SolarFlowInput(soil_moisture_pct=15, target_moisture_pct=40,
                                      forecast_rain_mm=0, rain_probability=0,
                                      solar_power_w=100, pump_power_w=60,
                                      tank_water_l=1000, area_m2=100))
    assert result["recommendation"] == "solar_now"
    assert result["energy_source"] == "solar"
    assert result["estimated_water_l"] > 0
    assert result["trained_ml_model"] is False


def test_battery_reserve_is_respected():
    result = recommend(SolarFlowInput(soil_moisture_pct=10, target_moisture_pct=40,
                                      forecast_rain_mm=0, rain_probability=0,
                                      solar_power_w=0, battery_pct=20,
                                      battery_reserve_pct=25, tank_water_l=1000))
    battery = next(c for c in result["candidates"] if c["action"] == "battery_now")
    assert battery["pump_minutes"] == 0
    assert "battery_at_reserve" in result["flags"]


def test_tank_caps_water_delivery():
    result = recommend(SolarFlowInput(soil_moisture_pct=5, target_moisture_pct=60,
                                      forecast_rain_mm=0, rain_probability=0,
                                      solar_power_w=200, tank_water_l=10,
                                      pump_flow_l_min=5, area_m2=100))
    assert result["estimated_water_l"] <= 10
    assert "tank_limited" in result["flags"]


def test_uncertainty_range_is_ordered_and_advisory_engine_identified():
    result = recommend(SolarFlowInput())
    low, high = result["water_demand_range_mm"]
    assert low <= result["water_demand_mm"] <= high
    assert result["engine"] == "model_based_optimizer_v1"
    assert result["trained_ml_model"] is False


def test_no_available_power_recommends_wait_not_zero_minute_pump():
    result = recommend(SolarFlowInput(soil_moisture_pct=10, target_moisture_pct=40,
                                      forecast_rain_mm=0, rain_probability=0,
                                      solar_power_w=0, battery_pct=25,
                                      battery_reserve_pct=25, tank_water_l=1000))
    assert result["recommendation"] == "wait"
    assert result["pump_minutes"] == 0
