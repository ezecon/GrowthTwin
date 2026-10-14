"""Build a self-contained field-trial evidence report from paired CSV observations.

No agronomic impact is inferred; only observed data and data-quality checks are shown.
"""
from __future__ import annotations
import argparse, csv, html, json
from pathlib import Path
from evaluate_sensor_accuracy import evaluate_csv

REQUIRED = ("reference_moisture_pct", "calibrated_moisture_pct")
OPTIONAL = ("timestamp", "plot_id", "device_id", "quality", "soil_type", "probe_depth_cm", "reference_method", "calibration_version")

def build_report(csv_path: str | Path, out_path: str | Path, *, trial_name: str = "Field trial", tolerance: float = 5.0, notes: str = "") -> dict:
    csv_path = Path(csv_path)
    with csv_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames or []
        missing = [x for x in REQUIRED if x not in fields]
        if missing: raise ValueError("CSV missing required columns: " + ", ".join(missing))
        rows = list(reader)
    metrics = evaluate_csv(csv_path, tolerance)
    missingness = {field: sum(not str(r.get(field, "")).strip() for r in rows) for field in (*REQUIRED, *OPTIONAL) if field in fields}
    distinct = {field: len({str(r.get(field, "")).strip() for r in rows if str(r.get(field, "")).strip()}) for field in ("plot_id", "device_id", "soil_type", "calibration_version") if field in fields}
    esc = html.escape
    metric_rows = "".join(f"<tr><th>{esc(k.replace('_',' ').title())}</th><td>{esc(str(v))}</td></tr>" for k,v in metrics["overall"].items())
    quality_rows = "".join(f"<tr><th>{esc(k)}</th><td>{v.get('n',0)}</td><td>{esc(str(v.get('mae')))}</td><td>{esc(str(v.get('rmse')))}</td><td>{esc(str(v.get('bias')))}</td></tr>" for k,v in metrics["by_quality"].items()) or '<tr><td colspan="5">No groups available</td></tr>'
    missing_rows = "".join(f"<tr><th>{esc(k)}</th><td>{v}</td><td>{(100*v/len(rows)) if rows else 0:.1f}%</td></tr>" for k,v in missingness.items())
    distinct_rows = "".join(f"<li>{esc(k.replace('_',' '))}: {v} distinct values</li>" for k,v in distinct.items()) or '<li>No grouping metadata supplied</li>'
    note_html = esc(notes) if notes else "No trial notes supplied."
    html_doc = f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(trial_name)} — Evidence report</title>
<style>body{{font:16px/1.5 system-ui,sans-serif;max-width:1000px;margin:32px auto;padding:0 18px;color:#17202a}}h1,h2{{line-height:1.2}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}}.card{{border:1px solid #ccd3d8;border-radius:12px;padding:14px}}table{{border-collapse:collapse;width:100%;margin:12px 0 24px}}th,td{{border-bottom:1px solid #ddd;text-align:left;padding:8px}}.muted{{color:#59636e}}.warn{{background:#fff7e6;padding:12px;border-radius:8px}}code{{overflow-wrap:anywhere}}</style>
<body><h1>{esc(trial_name)}</h1><p class="muted">Evidence report generated from <code>{esc(csv_path.name)}</code>. Observations only; no unsupported impact claims.</p>
<div class="grid"><div class="card"><strong>Rows read</strong><h2>{metrics['rows_read']}</h2></div><div class="card"><strong>Valid paired readings</strong><h2>{metrics['valid_pairs']}</h2></div><div class="card"><strong>Excluded / incomplete pairs</strong><h2>{metrics['excluded_rows']}</h2></div><div class="card"><strong>Absolute-error tolerance</strong><h2>{tolerance:g} pp</h2></div></div>
<h2>Overall sensor agreement</h2><table>{metric_rows}</table><h2>Results by reading quality</h2><table><thead><tr><th>Quality</th><th>n</th><th>MAE</th><th>RMSE</th><th>Bias</th></tr></thead><tbody>{quality_rows}</tbody></table>
<h2>Data completeness</h2><table><thead><tr><th>Field</th><th>Blank values</th><th>Blank share</th></tr></thead><tbody>{missing_rows}</tbody></table>
<h2>Trial coverage</h2><ul>{distinct_rows}</ul><h2>Trial notes</h2><p>{note_html}</p>
<div class="warn"><strong>Interpretation limits:</strong> MAE/RMSE/bias describe agreement with the supplied reference measurements only. Results depend on reference method, soil type, probe depth, sampling conditions, calibration and sample selection. These metrics do not prove yield gains, water savings, or better crop outcomes. Use held-out plots/devices and report the protocol.</div>
</body></html>'''
    Path(out_path).write_text(html_doc, encoding="utf-8")
    return {"output": str(out_path), "rows_read": metrics["rows_read"], "valid_pairs": metrics["valid_pairs"], "excluded_rows": metrics["excluded_rows"], "missingness": missingness, "distinct_values": distinct}

def main() -> int:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("csv_path"); ap.add_argument("--out",default="field_trial_report.html"); ap.add_argument("--name",default="Field trial"); ap.add_argument("--tolerance",type=float,default=5.0); ap.add_argument("--notes",default="")
    a=ap.parse_args(); result=build_report(a.csv_path,a.out,trial_name=a.name,tolerance=a.tolerance,notes=a.notes); print(json.dumps(result,indent=2)); return 0
if __name__ == "__main__": raise SystemExit(main())
