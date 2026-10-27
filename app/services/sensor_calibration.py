"""Convert raw ADC readings into GrowthTwin's calibrated soil-water scale.

The two-point mapping is a prototype calibration. For defensible agronomic values,
calibration endpoints must be measured for the installed probe and target soil.
"""
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class MoistureCalibration:
    adc_at_wilting_point: int
    adc_at_field_capacity: int
    adc_max: int = 4095
    adc_min: int = 0

    def validate(self) -> None:
        if not (0 <= self.adc_min < self.adc_max <= 65535):
            raise ValueError("ADC bounds must satisfy 0 <= adc_min < adc_max <= 65535")
        for name, value in (("wilting point", self.adc_at_wilting_point),
                            ("field capacity", self.adc_at_field_capacity)):
            if not self.adc_min <= value <= self.adc_max:
                raise ValueError(f"ADC value at {name} is outside the configured ADC range")
        if abs(self.adc_at_field_capacity - self.adc_at_wilting_point) < 20:
            raise ValueError("Wilting-point and field-capacity ADC values must differ by at least 20 counts")

    def convert(self, raw_adc: int) -> dict:
        self.validate()
        if not self.adc_min <= raw_adc <= self.adc_max:
            raise ValueError(f"raw_adc must be between {self.adc_min} and {self.adc_max}")
        low = min(self.adc_at_wilting_point, self.adc_at_field_capacity)
        high = max(self.adc_at_wilting_point, self.adc_at_field_capacity)
        in_calibrated_span = low <= raw_adc <= high
        fraction = (raw_adc - self.adc_at_wilting_point) / (
            self.adc_at_field_capacity - self.adc_at_wilting_point
        )
        # Keep the output in the calibrated 0..100% plant-available-water interval.
        moisture_pct = round(max(0.0, min(100.0, fraction * 100.0)), 2)
        return {
            "raw_adc": raw_adc,
            "moisture_pct": moisture_pct,
            "quality": "valid" if in_calibrated_span else "suspect",
            "calibration": asdict(self),
            "calibration_note": "Two-point probe/soil calibration; verify against gravimetric or reference measurements.",
        }
