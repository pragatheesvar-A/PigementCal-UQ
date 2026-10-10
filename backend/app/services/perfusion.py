"""Perfusion index (PI) from AC/DC components or direct entry.

PI = (AC_IR / DC_IR) x 100
  AC_IR - pulsatile (AC) component of the infrared PPG
  DC_IR - non-pulsatile (DC / baseline) component of the infrared PPG

PI is used here as a signal/perfusion FEATURE for reliability assessment, not as a standalone
diagnostic measurement. Low perfusion may reduce signal strength and can increase measurement
uncertainty; it does not by itself mean a reading is inaccurate.
"""

import math

from ..config import (
    PERFUSION_CONFIG, PI_THRESHOLD_LABEL, RELIABILITY_CONFIG, PerfusionConfig, ReliabilityConfig,
)
from .features import classify_ita, classify_pi
from .validation import InputValidationError, _err

SOURCES = ("ac_dc", "ppg")
LOW_TEXT = "Low perfusion may reduce PPG signal strength and increase measurement uncertainty."
UNUSUAL_TEXT = "Value is outside the typical range. Verify the input or signal."
NORMAL_TEXT = "Perfusion is currently within the configured normal range."


def _finite(raw):
    """float if raw is a real finite number (not bool / text / NaN / inf), else None."""
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw):
        return None
    return float(raw)


def thresholds(rcfg: ReliabilityConfig = RELIABILITY_CONFIG, pcfg: PerfusionConfig = PERFUSION_CONFIG) -> dict:
    return {"pi_low_below": rcfg.pi_low_below, "pi_very_low_below": rcfg.pi_very_low_below,
            "pi_typical_high": pcfg.pi_typical_high, "pi_max": rcfg.pi_max, "label": PI_THRESHOLD_LABEL}


def _result(pi: float, ac, dc, source: str, rcfg: ReliabilityConfig, pcfg: PerfusionConfig) -> dict:
    low = classify_pi(pi, rcfg) == "Low"
    very_low = pi < rcfg.pi_very_low_below
    warnings: list[str] = []
    if low:
        warnings.append(LOW_TEXT)
    if pi > pcfg.pi_typical_high:
        warnings.append(UNUSUAL_TEXT)
    usable = pi <= rcfg.pi_max
    if not usable:
        warnings.append(f"PI above {rcfg.pi_max:g}% is outside the range the Live Reliability Check supports, "
                        "so it cannot be sent there.")
    if ac is not None and dc is not None:
        if ac > dc:
            warnings.append("AC_IR is larger than DC_IR (PI above 100%), which is physically unusual. Verify the input or signal.")
        if dc < pcfg.dc_tiny:
            warnings.append("DC_IR is extremely small, so PI may be numerically unstable. Verify the input or signal.")
    return {
        "pi": pi, "pi_source": source, "source": source,
        "ac_ir": ac, "dc_ir": dc,
        "perfusion_state": "LOW" if low else "NORMAL", "very_low": very_low,
        "usable_for_reliability": usable,
        "warnings": warnings,
        "impact": LOW_TEXT.replace("PPG signal strength and increase measurement uncertainty",
                                   "signal strength and can increase measurement uncertainty") if low else NORMAL_TEXT,
        "thresholds": thresholds(rcfg, pcfg),
        "note": "PI is used as a signal/perfusion feature, not as a standalone diagnostic measurement.",
    }


def calculate_pi(raw: dict, rcfg: ReliabilityConfig = RELIABILITY_CONFIG,
                 pcfg: PerfusionConfig = PERFUSION_CONFIG) -> dict:
    """PI from AC_IR and DC_IR. Reports every input problem together; never divides by zero."""
    errors: list[dict] = []
    ac_raw, dc_raw = raw.get("ac_ir"), raw.get("dc_ir")
    source = raw.get("source") or "ac_dc"
    if source not in SOURCES:
        errors.append(_err("source", "invalid_choice", f"Source must be one of: {', '.join(SOURCES)}."))

    ac = dc = None
    if ac_raw is None:
        errors.append(_err("ac_ir", "missing", "AC_IR is required."))
    elif (ac := _finite(ac_raw)) is None:
        errors.append(_err("ac_ir", "invalid_type", "AC_IR must be a finite number."))
    elif ac < 0:
        errors.append(_err("ac_ir", "negative", "AC_IR must be zero or greater."))
        ac = None
    if dc_raw is None:
        errors.append(_err("dc_ir", "missing", "DC_IR is required."))
    elif (dc := _finite(dc_raw)) is None:
        errors.append(_err("dc_ir", "invalid_type", "DC_IR must be a finite number."))
    elif dc <= 0:
        errors.append(_err("dc_ir", "not_positive", "DC_IR must be greater than zero."))
        dc = None
    if errors:
        raise InputValidationError(errors)

    if ac == 0:
        raise InputValidationError([_err("ac_ir", "no_pulsatile_signal",
            "AC_IR is zero, so PI is 0%: no pulsatile component is present. PI must be positive to be "
            "assessed — consider reacquiring the signal.")])
    pi = 100.0 * ac / dc
    if not math.isfinite(pi) or pi <= 0:
        raise InputValidationError([_err("dc_ir", "numeric_range",
            "AC_IR and DC_IR give a PI that cannot be represented. Check the units and magnitudes.")])
    return _result(round(pi, 4), ac, dc, source, rcfg, pcfg)


def direct_pi(raw: dict, rcfg: ReliabilityConfig = RELIABILITY_CONFIG,
              pcfg: PerfusionConfig = PERFUSION_CONFIG) -> dict:
    """Validate a directly entered PI (manual mode)."""
    v = raw.get("pi")
    if v is None:
        raise InputValidationError([_err("pi", "missing", "PI is required.")])
    pi = _finite(v)
    if pi is None or pi <= 0:
        raise InputValidationError([_err("pi", "invalid_pi", "PI must be a positive finite value.")])
    return _result(pi, None, None, "manual", rcfg, pcfg)


def ita_pi_matrix(rcfg: ReliabilityConfig = RELIABILITY_CONFIG) -> dict:
    """STRUCTURE of the planned ITA x PI Mondrian cells (3 x 2). No coverage or calibration is
    computed by the perfusion module — this only describes how cells are defined from the configuration."""
    ita_groups = [
        {"id": "Light", "range": f"ITA > {rcfg.ita_light_above:g}°"},
        {"id": "Medium", "range": f"{rcfg.ita_dark_at_most:g}° < ITA ≤ {rcfg.ita_light_above:g}°"},
        {"id": "Dark", "range": f"ITA ≤ {rcfg.ita_dark_at_most:g}°"},
    ]
    pi_groups = [
        {"id": "Low", "range": f"PI < {rcfg.pi_low_below:g}%"},
        {"id": "Normal", "range": f"PI ≥ {rcfg.pi_low_below:g}%"},
    ]
    return {"ita_groups": ita_groups, "pi_groups": pi_groups,
            "cells": [{"ita_group": a["id"], "pi_group": b["id"]} for a in ita_groups for b in pi_groups],
            "status": "STRUCTURAL PREVIEW ONLY — no subgroup coverage or conformal calibration has been computed.",
            "thresholds_label": PI_THRESHOLD_LABEL}


def cell_for(ita: float | None, pi: float | None, rcfg: ReliabilityConfig = RELIABILITY_CONFIG) -> dict | None:
    if ita is None or pi is None:
        return None
    return {"ita_group": classify_ita(ita, rcfg), "pi_group": classify_pi(pi, rcfg)}
