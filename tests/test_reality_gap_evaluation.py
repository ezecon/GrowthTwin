import pytest

from scripts.evaluate_reality_gap import metrics


def test_metrics_compute_error_and_bias():
    result = metrics([10, 20, 30], [12, 18, 30])
    assert result["n"] == 3
    assert result["mae"] == pytest.approx(4 / 3)
    assert result["rmse"] == pytest.approx((8 / 3) ** 0.5)
    assert result["bias"] == pytest.approx(0)


def test_metrics_reject_empty_data():
    with pytest.raises(ValueError, match="No usable"):
        metrics([], [])
