import csv
import pytest
from scripts.evaluate_sensor_accuracy import evaluate_csv, metrics


def test_metrics_signed_bias_and_tolerance():
    result = metrics([
        {"reference_moisture_pct": "40", "calibrated_moisture_pct": "42"},
        {"reference_moisture_pct": "60", "calibrated_moisture_pct": "55"},
    ], tolerance=5)
    assert result["n"] == 2
    assert result["mae"] == 3.5
    assert result["bias"] == -1.5
    assert result["within_tolerance_pct"] == 100.0


def test_csv_groups_quality_and_excludes_bad_pairs(tmp_path):
    path = tmp_path / "paired.csv"
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["reference_moisture_pct", "calibrated_moisture_pct", "quality", "device_id"])
        writer.writeheader()
        writer.writerows([
            {"reference_moisture_pct": 50, "calibrated_moisture_pct": 52, "quality": "valid", "device_id": "d1"},
            {"reference_moisture_pct": 40, "calibrated_moisture_pct": 70, "quality": "suspect", "device_id": "d1"},
            {"reference_moisture_pct": "bad", "calibrated_moisture_pct": 20, "quality": "valid", "device_id": "d2"},
        ])
    report = evaluate_csv(path, tolerance=5)
    assert report["rows_read"] == 3
    assert report["valid_pairs"] == 2
    assert report["excluded_rows"] == 1
    assert report["by_quality"]["suspect"]["mae"] == 30.0
    assert report["by_device"]["d1"]["n"] == 2


def test_missing_columns_and_negative_tolerance_fail(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("a,b\n1,2\n")
    with pytest.raises(ValueError, match="missing required columns"):
        evaluate_csv(path)
    with pytest.raises(ValueError, match="non-negative"):
        metrics([], -1)
