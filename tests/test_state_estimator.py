import pytest

from app.services.state_estimator import correct_state


def test_valid_measurement_blends_prediction_and_measurement():
    result = correct_state(80, 20, alpha=0.5, minimum=0, maximum=160)
    assert result.predicted_value == 80
    assert result.measured_value == 20
    assert result.residual == -60
    assert result.estimated_value == 50
    assert result.measurement_used is True


@pytest.mark.parametrize("quality", ["suspect", "invalid", "stale"])
def test_untrusted_measurement_does_not_change_estimate(quality):
    result = correct_state(80, 20, alpha=0.5, minimum=0, maximum=160, quality=quality)
    assert result.estimated_value == 80
    assert result.measurement_used is False
    assert result.residual == -60


def test_missing_measurement_retains_prediction():
    result = correct_state(42, None)
    assert result.estimated_value == 42
    assert result.residual is None
    assert result.quality == "missing"


def test_estimate_is_bounded():
    result = correct_state(90, 160, alpha=1, minimum=0, maximum=100)
    assert result.estimated_value == 100


@pytest.mark.parametrize("alpha", [-0.1, 1.1])
def test_invalid_alpha_rejected(alpha):
    with pytest.raises(ValueError):
        correct_state(50, 40, alpha=alpha)
