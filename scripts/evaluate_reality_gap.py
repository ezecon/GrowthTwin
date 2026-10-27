"""Evaluate baseline vs Reality Gap estimates from a held-out CSV.

Required CSV columns:
  reference_moisture_pct, predicted_moisture_pct, corrected_moisture_pct

Each row must represent the same timestamp/plot measurement. Use a held-out set
that was not used to tune alpha or calibrate the estimator. This script reports
error metrics; it does not assume correction is better.
"""
import argparse
import csv
import math
from pathlib import Path


def metrics(reference, estimate):
    errors = [float(p) - float(y) for y, p in zip(reference, estimate)]
    if not errors:
        raise ValueError("No usable evaluation rows")
    return {
        "n": len(errors),
        "mae": sum(abs(e) for e in errors) / len(errors),
        "rmse": math.sqrt(sum(e * e for e in errors) / len(errors)),
        "bias": sum(errors) / len(errors),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path)
    args = parser.parse_args()
    with args.csv_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        required = {"reference_moisture_pct", "predicted_moisture_pct", "corrected_moisture_pct"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            parser.error("Missing CSV columns: " + ", ".join(sorted(missing)))
        rows = []
        for row_num, row in enumerate(reader, start=2):
            try:
                values = [float(row[k]) for k in required]
            except (TypeError, ValueError):
                print(f"Skipping row {row_num}: missing/non-numeric evaluation value")
                continue
            if not all(math.isfinite(v) for v in values):
                print(f"Skipping row {row_num}: non-finite evaluation value")
                continue
            rows.append({k: float(row[k]) for k in required})
    if not rows:
        parser.error("No valid rows found")
    reference = [r["reference_moisture_pct"] for r in rows]
    baseline = [r["predicted_moisture_pct"] for r in rows]
    corrected = [r["corrected_moisture_pct"] for r in rows]
    b, c = metrics(reference, baseline), metrics(reference, corrected)
    print(f"Rows evaluated: {len(rows)}")
    print("Metric units: moisture percentage points")
    print(f"Baseline  MAE={b['mae']:.3f}  RMSE={b['rmse']:.3f}  bias={b['bias']:.3f}")
    print(f"Corrected MAE={c['mae']:.3f}  RMSE={c['rmse']:.3f}  bias={c['bias']:.3f}")
    delta = b["mae"] - c["mae"]
    print(f"MAE change (baseline - corrected): {delta:+.3f} percentage points")
    if delta > 0:
        print("On this supplied evaluation set, corrected estimates have lower MAE.")
    elif delta < 0:
        print("On this supplied evaluation set, corrected estimates have higher MAE.")
    else:
        print("On this supplied evaluation set, MAE is unchanged.")
    print("Do not claim general improvement from a small or non-independent test set.")


if __name__ == "__main__":
    main()
