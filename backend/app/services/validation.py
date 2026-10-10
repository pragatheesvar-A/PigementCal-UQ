"""Input validation. Invalid input is never silently accepted or clamped."""

import math
from dataclasses import dataclass

from ..config import DEVICES, MOTION_LEVELS, RELIABILITY_CONFIG, SIGNAL_LEVELS, ReliabilityConfig


@dataclass(frozen=True)
class ValidatedInput:
    spo2: float
    pi: float
    ita: float
    signal_quality: str
    motion: str
    device: str
    sqi: float | None = None


class InputValidationError(Exception):
    def __init__(self, errors: list[dict]):
        super().__init__("invalid input")
        self.errors = errors


def _err(field: str, code: str, message: str) -> dict:
    return {"field": field, "code": code, "message": message}


def _number(raw, field: str, label: str, errors: list[dict], missing_msg: str):
    """Return a finite float or None (recording an error)."""
    if raw is None:
        errors.append(_err(field, "missing", missing_msg))
        return None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw):
        errors.append(_err(field, "invalid_type", f"{label} must be a finite number."))
        return None
    return float(raw)


def _choice(raw, field: str, label: str, allowed: tuple, errors: list[dict], upper: bool):
    if raw is None or not str(raw).strip():
        errors.append(_err(field, "missing", f"{label} is required."))
        return None
    value = str(raw).strip()
    value = value.upper() if upper else value
    if value not in allowed:
        errors.append(_err(field, "invalid_choice", f"{label} must be one of: {', '.join(allowed)}."))
        return None
    return value


def validate_inputs(raw: dict, cfg: ReliabilityConfig = RELIABILITY_CONFIG) -> ValidatedInput:
    """Validate every field and raise one InputValidationError listing all problems."""
    errors: list[dict] = []

    spo2 = _number(raw.get("spo2"), "spo2", "SpO₂", errors, "SpO₂ is required.")
    if spo2 is not None and not (cfg.spo2_min <= spo2 <= cfg.spo2_max):
        errors.append(_err("spo2", "out_of_range",
                           f"OUTSIDE SUPPORTED RANGE: SpO₂ must be between {cfg.spo2_min:g} and {cfg.spo2_max:g}%."))

    pi = _number(raw.get("pi"), "pi", "PI", errors, "Perfusion index is required.")
    if pi is not None:
        if pi <= 0:
            errors.append(_err("pi", "invalid_pi", "INVALID PI: perfusion index must be greater than 0%."))
        elif pi > cfg.pi_max:
            errors.append(_err("pi", "out_of_range",
                               f"OUTSIDE SUPPORTED RANGE: PI must be at most {cfg.pi_max:g}%."))

    ita = _number(raw.get("ita"), "ita", "ITA", errors, "OBJECTIVE PIGMENTATION VALUE REQUIRED: enter an ITA value.")
    if ita is not None and not (cfg.ita_min <= ita <= cfg.ita_max):
        errors.append(_err("ita", "out_of_range",
                           f"OUTSIDE SUPPORTED RANGE: ITA must be between {cfg.ita_min:g}° and {cfg.ita_max:g}°."))

    signal = _choice(raw.get("signal_quality"), "signal_quality", "Signal quality", SIGNAL_LEVELS, errors, True)
    motion = _choice(raw.get("motion"), "motion", "Motion", MOTION_LEVELS, errors, True)
    device = _choice(raw.get("device"), "device", "Device", DEVICES, errors, False)

    sqi = None
    if raw.get("sqi") is not None:
        sqi = _number(raw["sqi"], "sqi", "SQI", errors, "")
        if sqi is not None and not (0 <= sqi <= 100):
            errors.append(_err("sqi", "out_of_range", "SQI must be between 0 and 100."))

    if errors:
        raise InputValidationError(errors)
    return ValidatedInput(spo2, pi, ita, signal, motion, device, sqi)  # type: ignore[arg-type]
