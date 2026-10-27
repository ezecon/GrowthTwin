"""Transparent SolarFlow decision engine.

This is a model-based prototype, not a trained machine-learning model. It combines a
root-zone water-balance estimate with a constrained candidate-action scorer. Replace
its estimates with calibrated field models once enough verified data exists.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any


@dataclass
class SolarFlowInput:
    soil_moisture_pct: float = 24.0
    target_moisture_pct: float = 35.0
    area_m2: float = 100.0
    root_zone_available_mm: float = 60.0
    daily_crop_water_mm: float = 4.0
    forecast_rain_mm: float = 8.0
    rain_probability: float = 0.6
    solar_power_w: float = 80.0
    pump_power_w: float = 60.0
    battery_capacity_wh: float = 240.0
    battery_pct: float = 42.0
    battery_reserve_pct: float = 25.0
    tank_water_l: float = 500.0
    pump_flow_l_min: float = 5.0
    horizon_hours: float = 6.0


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(v)))


def recommend(data: SolarFlowInput) -> dict[str, Any]:
    d = data
    moisture = _clamp(d.soil_moisture_pct, 0, 100)
    target = _clamp(d.target_moisture_pct, 1, 100)
    rain_prob = _clamp(d.rain_probability, 0, 1)
    battery_pct = _clamp(d.battery_pct, 0, 100)
    reserve_pct = _clamp(d.battery_reserve_pct, 0, 95)
    area = max(0.1, d.area_m2)
    root_mm = max(1.0, d.root_zone_available_mm)
    daily_need = max(0.0, d.daily_crop_water_mm)
    horizon = _clamp(d.horizon_hours, 1, 24)
    flow = max(0.1, d.pump_flow_l_min)
    pump_w = max(1.0, d.pump_power_w)
    solar_w = max(0.0, d.solar_power_w)
    tank_l = max(0.0, d.tank_water_l)

    # Soil moisture is assumed to be a calibrated fraction of plant-available water.
    deficit_mm = max(0.0, (target - moisture) / 100.0 * root_mm)
    crop_need_mm = daily_need * horizon / 24.0
    expected_rain_mm = max(0.0, d.forecast_rain_mm) * rain_prob * 0.75
    demand_mm = 0.0 if moisture >= target else max(0.0, max(deficit_mm, crop_need_mm) - expected_rain_mm)
    requested_l = demand_mm * area  # 1 mm water depth on 1 m² = 1 litre
    tank_limited_l = min(requested_l, tank_l)
    requested_minutes = tank_limited_l / flow
    max_minutes = min(60.0, requested_minutes)
    required_wh = max_minutes / 60.0 * pump_w
    solar_fraction = _clamp(solar_w / pump_w, 0, 1)
    solar_supported_minutes = max_minutes if solar_fraction >= 0.95 else max_minutes * solar_fraction
    battery_available_wh = max(0.0, d.battery_capacity_wh * (battery_pct - reserve_pct) / 100.0)
    battery_supported_minutes = min(max_minutes, battery_available_wh / pump_w * 60.0)

    reasons: list[str] = []
    flags: list[str] = []
    if requested_l > tank_l:
        flags.append("tank_limited")
        reasons.append("Available tank water limits the requested irrigation volume.")
    if moisture >= target:
        reasons.append("Soil moisture is at or above the configured target.")
    if rain_prob >= 0.65 and d.forecast_rain_mm >= 3:
        reasons.append("Meaningful rain is forecast, so expected rainfall reduces the irrigation target.")
    if battery_pct <= reserve_pct:
        flags.append("battery_at_reserve")
        reasons.append("Battery is at or below its protected reserve; battery pumping is not recommended.")

    candidates: list[dict[str, Any]] = []
    # Score is intentionally interpretable: unmet water demand dominates; then energy and battery wear.
    for action, minutes, energy_source, cost in [
        ("solar_now", min(max_minutes, solar_supported_minutes), "solar", 0.02),
        ("battery_now", min(max_minutes, battery_supported_minutes), "battery", 0.25),
        ("wait", 0.0, "none", 0.0),
    ]:
        delivered_l = min(tank_l, minutes * flow)
        delivered_mm = delivered_l / area
        unmet_mm = max(0.0, demand_mm - delivered_mm)
        energy_wh = minutes / 60.0 * pump_w
        battery_wh = energy_wh if energy_source == "battery" else max(0.0, energy_wh * (1 - solar_fraction)) if energy_source == "solar" else 0.0
        # Penalty scale is tuned for readable demo ranking, not an empirically validated utility.
        score = unmet_mm * 10.0 + energy_wh * cost + battery_wh * 0.08
        if energy_source == "battery" and battery_pct <= reserve_pct:
            score += 10000
        candidates.append({"action": action, "energy_source": energy_source,
                           "pump_minutes": round(minutes, 1), "water_l": round(delivered_l, 1),
                           "energy_wh": round(energy_wh, 1), "unmet_water_mm": round(unmet_mm, 2),
                           "score": round(score, 2)})

    # If no irrigation is needed, wait; otherwise choose feasible lowest-score candidate.
    if demand_mm <= 0.25 or tank_l < 0.5:
        chosen = candidates[2]
        recommendation = "wait"
        reasons.append("Estimated irrigation demand is negligible or usable tank water is unavailable.")
    else:
        chosen = min(candidates, key=lambda x: x["score"])
        # A zero-runtime candidate is not an executable recommendation; prefer waiting.
        if chosen["pump_minutes"] <= 0:
            chosen = candidates[2]
        recommendation = chosen["action"]
    if recommendation == "solar_now":
        reasons.append("Solar-first pumping is preferred for the currently estimated conditions.")
    elif recommendation == "battery_now":
        reasons.append("Battery pumping is selected only within the configured reserve constraint.")
    else:
        reasons.append("Wait and reassess with fresh sensor and weather observations.")

    # Lightweight sensitivity band communicates input uncertainty rather than false precision.
    demand_low = max(0.0, demand_mm * 0.8)
    demand_high = demand_mm * 1.2 + (1.0 if rain_prob > 0 else 0.0)
    return {
        "engine": "model_based_optimizer_v1",
        "status": "prototype_not_field_validated",
        "trained_ml_model": False,
        "recommendation": recommendation,
        "energy_source": chosen["energy_source"],
        "pump_minutes": chosen["pump_minutes"],
        "estimated_water_l": chosen["water_l"],
        "estimated_energy_wh": chosen["energy_wh"],
        "water_demand_mm": round(demand_mm, 2),
        "water_demand_range_mm": [round(demand_low, 2), round(demand_high, 2)],
        "estimated_battery_after_pct": round(max(0.0, battery_pct - (chosen["energy_wh"] / max(1.0, d.battery_capacity_wh) * 100 if chosen["energy_source"] == "battery" else 0)), 1),
        "candidates": sorted(candidates, key=lambda x: x["score"]),
        "reasons": reasons,
        "flags": flags,
        "assumptions": [
            "Soil-moisture percentage is calibrated to plant-available water; verify this for the installed probe and soil.",
            "Solar power is the current usable power at the pump controller, not a weather-only estimate.",
            "Rain effectiveness is approximated at 75%; calibrate with local rainfall and infiltration observations.",
            "Pump flow and wattage must be measured on the actual hardware before field operation.",
            "This is transparent model-based decision support, not a trained or field-validated AI model.",
        ],
    }
