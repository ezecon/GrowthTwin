from datetime import datetime, timezone

import pytest

from app.services.sensor_calibration import MoistureCalibration


def test_calibration_supports_adc_that_decreases_when_wet():
    result = MoistureCalibration(
        adc_at_wilting_point=3000,
        adc_at_field_capacity=1500,
    ).convert(2250)
    assert result["moisture_pct"] == 50
    assert result["quality"] == "valid"


def test_calibration_supports_adc_that_increases_when_wet():
    result = MoistureCalibration(
        adc_at_wilting_point=1200,
        adc_at_field_capacity=3200,
    ).convert(2200)
    assert result["moisture_pct"] == 50


def test_values_outside_calibration_span_are_suspect_and_clamped():
    result = MoistureCalibration(3000, 1500).convert(3500)
    assert result["moisture_pct"] == 0
    assert result["quality"] == "suspect"


def test_rejects_near_identical_calibration_points():
    with pytest.raises(ValueError, match="differ by at least 20"):
        MoistureCalibration(2000, 2010).validate()


def test_rejects_adc_outside_hardware_range():
    with pytest.raises(ValueError, match="raw_adc"):
        MoistureCalibration(3000, 1500).convert(5000)
