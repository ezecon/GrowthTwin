from app.services.sensor_health import assess_reading


def test_flatline_is_flagged_after_five_identical_readings():
    state = {}
    results = []
    for _ in range(5):
        result = assess_reading(2100, state, "valid")
        results.append(result)
        state = {"last_raw_moisture_adc": 2100,
                 "consecutive_identical": result.consecutive_identical}
    assert [r.quality for r in results] == ["valid", "valid", "valid", "valid", "suspect"]
    assert "possible_sensor_flatline" in results[-1].reasons


def test_large_adc_jump_is_flagged_without_changing_raw_value():
    result = assess_reading(3500, {"last_raw_moisture_adc": 1000,
                                   "consecutive_identical": 1}, "valid")
    assert result.quality == "suspect"
    assert result.adc_delta == 2500
    assert "implausible_adc_jump" in result.reasons


def test_out_of_calibration_range_is_suspect():
    result = assess_reading(4095, None, "suspect")
    assert result.quality == "suspect"
    assert result.reasons == ["outside_calibrated_span"]
