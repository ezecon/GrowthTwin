"""Conservative server-side quality checks for low-cost sensor telemetry."""
from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class SensorHealth:
    quality: str
    reasons: list[str]
    consecutive_identical: int
    adc_delta: int | None

    def as_dict(self):
        return asdict(self)


def assess_reading(raw_adc: int, previous: dict | None, calibration_quality: str,
                   *, flatline_limit: int = 5, jump_limit: int = 1500) -> SensorHealth:
    """Flag flatlined/jumping probes without silently correcting their readings."""
    reasons: list[str] = []
    prev = previous or {}
    old_adc = prev.get("last_raw_moisture_adc")
    delta = abs(raw_adc - int(old_adc)) if old_adc is not None else None
    identical = int(prev.get("consecutive_identical", 0)) + 1 if old_adc == raw_adc else 1
    if calibration_quality != "valid":
        reasons.append("outside_calibrated_span")
    if identical >= flatline_limit:
        reasons.append("possible_sensor_flatline")
    if delta is not None and delta > jump_limit:
        reasons.append("implausible_adc_jump")
    return SensorHealth("suspect" if reasons else "valid", reasons, identical, delta)
