import csv
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_field_trial_report import build_report

def test_report_has_observed_metrics_and_limits(tmp_path):
    source=tmp_path/"trial.csv"
    with source.open("w", newline="") as f:
        w=csv.DictWriter(f, fieldnames=["reference_moisture_pct","calibrated_moisture_pct","device_id","plot_id","quality"])
        w.writeheader(); w.writerow({"reference_moisture_pct":"30","calibrated_moisture_pct":"32","device_id":"d1","plot_id":"p1","quality":"good"}); w.writerow({"reference_moisture_pct":"","calibrated_moisture_pct":"45","device_id":"d2","plot_id":"p2","quality":"suspect"})
    out=tmp_path/"report.html"
    result=build_report(source,out,trial_name="Spring trial",notes="AM sampling")
    page=out.read_text()
    assert result["rows_read"] == 2 and result["valid_pairs"] == 1 and result["excluded_rows"] == 1
    assert "Spring trial" in page and "MAE" in page and "do not prove" in page and "AM sampling" in page
    assert "device_id" in result["missingness"]

def test_rejects_missing_required_column(tmp_path):
    source=tmp_path/"bad.csv"; source.write_text("device_id\nd1\n")
    try: build_report(source,tmp_path/"x.html")
    except ValueError as e: assert "missing required columns" in str(e)
    else: raise AssertionError("expected schema validation failure")
