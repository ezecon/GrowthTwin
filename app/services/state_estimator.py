"""GrowthTwin Sentinel: transparent sensor-to-twin state correction.

The estimator is intentionally independent of FastAPI and persistence so that
its behavior can be tested and replayed reproducibly.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
from typing import Any


ESTIMATOR_VERSION = "reality-gap-v1"
VALID_QUALITY = {"valid", "suspect", "invalid", "stale"}


@dataclass(frozen=True)
class StateEstimate:
    predicted_value: float
    measured_value: float | None
    residual: float | None
    estimated_value: float
    alpha: float
    measurement_used: bool
    quality: str
    reason: str
    estimator_version: str = ESTIMATOR_VERSION

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def correct_state(
    predicted_value: float,
    measured_value: float | None,
    *,
    alpha: float = 0.65,
    minimum: float = 0.0,
    maximum: float = 100.0,
    quality: str = "valid",
) -> StateEstimate:
    """Blend a prediction with a quality-approved measurement.

    residual is measured - predicted. A suspect, invalid, stale, or missing
    measurement never changes the estimate. Select alpha using calibration
    data before making performance claims.
    """
    if not isfinite(predicted_value):
        raise ValueError("predicted_value must be finite")
    if not isfinite(alpha) or not 0.0 <= alpha <= 1.0:
        raise ValueError("alpha must be between 0 and 1")
    if not isfinite(minimum) or not isfinite(maximum) or minimum > maximum:
        raise ValueError("minimum and maximum must be finite and minimum <= maximum")
    if quality not in VALID_QUALITY:
        raise ValueError("quality must be valid, suspect, invalid, or stale")
    if measured_value is not None and not isfinite(measured_value):
        raise ValueError("measured_value must be finite or None")

    residual = None if measured_value is None else float(measured_value - predicted_value)
    usable = measured_value is not None and quality == "valid"
    if usable:
        estimate = predicted_value + alpha * (measured_value - predicted_value)
        reason = "valid_measurement_blended_with_prediction"
    else:
        estimate = predicted_value
        reason = "prediction_retained_without_valid_measurement"

    estimate = min(maximum, max(minimum, estimate))
    return StateEstimate(
        predicted_value=float(predicted_value),
        measured_value=None if measured_value is None else float(measured_value),
        residual=residual,
        estimated_value=float(estimate),
        alpha=float(alpha),
        measurement_used=usable,
        quality=quality if measured_value is not None else "missing",
        reason=reason,
    )
