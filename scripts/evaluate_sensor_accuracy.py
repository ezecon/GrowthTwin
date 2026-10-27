"""Evaluate calibrated soil-moisture observations against independent references.

CSV required columns: reference_moisture_pct, calibrated_moisture_pct.
Optional columns: plot_id, device_id, quality, timestamp.
Metrics are descriptive and do not establish agronomic or water-saving impact.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

REQUIRED = ("reference_moisture_pct", "calibrated_moisture_pct")


def _float(value: str | None) -> float | None:
    try:
        number = float(value) if value not in (None, "") else math.nan
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def metrics(rows: list[dict], tolerance: float = 5.0) -> dict:
    if tolerance < 0:
        raise ValueError("tolerance must be non-negative")
    pairs = []
    for row in rows:
        ref = _float(row.get("reference_moisture_pct"))
        measured = _float(row.get("calibrated_moisture_pct"))
        if ref is not None and measured is not None:
            pairs.append((ref, measured))
    if not pairs:
        return {"n": 0, "mae": None, "rmse": None, "bias": None,
                "median_absolute_error": None, "within_tolerance_pct": None}
    errors = [measured - ref for ref, measured in pairs]
    absolute = [abs(e) for e in errors]
    return {
        "n": len(pairs),
        "mae": round(statistics.mean(absolute), 4),
        "rmse": round(math.sqrt(statistics.mean(e * e for e in errors)), 4),
        "bias": round(statistics.mean(errors), 4),
        "median_absolute_error": round(statistics.median(absolute), 4),
        "within_tolerance_pct": round(100 * sum(e <= tolerance for e in absolute) / len(absolute), 2),
    }


def evaluate_csv(path: str | Path, tolerance: float = 5.0) -> dict:
    if tolerance < 0:
        raise ValueError("tolerance must be non-negative")
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = [name for name in REQUIRED if name not in (reader.fieldnames or [])]
        if missing:
            raise ValueError("CSV missing required columns: " + ", ".join(missing))
        rows = list(reader)
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        groups[str(row.get("quality") or "unspecified")].append(row)
    by_device: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        device = str(row.get("device_id") or "unspecified")
        by_device[device].append(row)
    valid_count = sum(metrics([r], tolerance)["n"] for r in rows)
    return {
        "dataset": str(path), "rows_read": len(rows), "valid_pairs": valid_count,
        "excluded_rows": len(rows) - valid_count, "tolerance_percentage_points": tolerance,
        "overall": metrics(rows, tolerance),
        "by_quality": {k: metrics(v, tolerance) for k, v in sorted(groups.items())},
        "by_device": {k: metrics(v, tolerance) for k, v in sorted(by_device.items())},
        "interpretation": "Reference-paired descriptive metrics only; use held-out plots/devices and field trials before agronomic claims.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", help="CSV containing paired reference and calibrated measurements")
    parser.add_argument("--tolerance", type=float, default=5.0, help="absolute-error tolerance in percentage points (default: 5)")
    parser.add_argument("--out", help="optional path for JSON report; prints to stdout if omitted")
    args = parser.parse_args()
    report = evaluate_csv(args.csv_path, args.tolerance)
    output = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        Path(args.out).write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
