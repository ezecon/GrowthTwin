# GrowthTwin SolarFlow AI (prototype)

SolarFlow is an additive module; the existing GrowthTwin dashboard and irrigation controls remain in place. The new `SolarFlow AI` sidebar link opens `/solarflow.html`.

## Included

- `POST /solarflow/plan`: authenticated, advisory-only planning endpoint.
- Transparent root-zone water-balance estimate with expected-rain adjustment.
- Candidate comparison: solar-first pumping, battery-supported pumping, and waiting.
- Explicit tank limit, battery reserve, estimated energy/water delivery, uncertainty band, reasons, flags, and assumptions.
- Browser UI styled to match GrowthTwin's existing dark green/lime interface.
- Unit tests for wet soil, solar-first operation, battery reserve, tank limit, and uncertainty output.

## Important model status

This is a deterministic model-based optimizer, **not a trained machine-learning model**. The word AI describes the decision-support direction, not evidence of learned predictive performance. Water demand and candidate scores use illustrative assumptions and must be calibrated with local soil/crop data and measured hardware performance. The endpoint never operates a pump.

## Input units

- `soil_moisture_pct`, `target_moisture_pct`: calibrated percentages (must represent the same soil-moisture scale).
- `area_m2`: irrigated area in square metres.
- `root_zone_available_mm`: approximate plant-available root-zone water depth.
- `daily_crop_water_mm`: crop water use in millimetres per day.
- `forecast_rain_mm`: forecast precipitation over the selected horizon.
- `rain_probability`: 0–1 probability.
- `solar_power_w`: currently usable solar power at the pump controller.
- `pump_power_w`: measured pump electrical draw.
- `battery_capacity_wh`, `battery_pct`, `battery_reserve_pct`: battery specifications and state of charge.
- `tank_water_l`: usable water remaining.
- `pump_flow_l_min`: measured flow rate.

## Before field use

1. Calibrate moisture probes for the soil and install location.
2. Measure actual pump wattage and flow rate at operating head/pressure.
3. Connect verified solar/battery telemetry and a real weather forecast; do not treat demo form defaults as measurements.
4. Add independent low-tank, dry-run, over-current, battery-management, stale-sensor, manual-stop and maximum-runtime interlocks.
5. Keep the advisory planner separate from any actuator service. Require explicit farmer/operator enablement and hardware safety checks for future automation.
6. Collect labelled field data and compare against a simple threshold-control baseline before claiming AI accuracy or savings.

## Run

From `backend/`:

```bash
uvicorn app.main:app --reload
```

Open `/` for the original GrowthTwin UI and choose **SolarFlow AI**, or open `/solarflow.html` directly. API documentation is available at `/docs`.
