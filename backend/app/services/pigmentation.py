"""Objective pigmentation from CIELAB colorimetry (ITA).

ITA is an objective colorimetric descriptor. The Light/Medium/Dark output is an
"objective pigmentation category" — NOT race or ethnicity.
"""

import math
import statistics

from ..config import (
    LOCATIONS, NOT_SPECIFIED, PIGMENTATION_CONFIG, RELIABILITY_CONFIG, PigmentationConfig, ReliabilityConfig,
)
from .features import classify_ita
from .validation import InputValidationError, _err, _number

LABEL = "Objective pigmentation category — not race or ethnicity."


def compute_ita(L: float, b: float) -> float:
    """THE ITA definition for the whole project (the only place it is computed):

        ITA = arctan((L* - 50) / b*) x 180/pi      (degrees, range (-90, 90))

    b* = 0 is handled explicitly: ITA = +90 if L* > 50, -90 if L* < 50. L* = 50 together with b* = 0 is undefined and raises ValueError.
    Non-finite inputs raise ValueError. (atan2 was used before; it differs from this only when b* < 0, where it can leave (-90, 90).)
    """
    if not (math.isfinite(L) and math.isfinite(b)):
        raise ValueError("ITA needs finite L* and b* values.")
    if b == 0.0:
        if L == 50.0:
            raise ValueError("ITA is undefined when L* = 50 and b* = 0.")
        return 90.0 if L > 50.0 else -90.0
    return math.degrees(math.atan((L - 50.0) / b))


def _location(raw, field: str, errors: list[dict]):
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    if raw not in LOCATIONS:
        errors.append(_err(field, "invalid_choice", f"Measurement location must be one of: {', '.join(LOCATIONS)}."))
        return None
    return raw


def _lab(raw: dict, prefix: str, errors: list[dict], cfg: PigmentationConfig):
    """Validate L*, a*, b*. Missing / non-numeric / non-finite / out-of-range values are errors,
    never replaced."""
    L = _number(raw.get("L"), f"{prefix}L", "L*", errors, "L* is required.")
    a = _number(raw.get("a"), f"{prefix}a", "a*", errors, "a* is required.")
    b = _number(raw.get("b"), f"{prefix}b", "b*", errors, "b* is required.")
    if L is not None and not (cfg.L_min <= L <= cfg.L_max):
        errors.append(_err(f"{prefix}L", "out_of_range", f"L* must be between {cfg.L_min:g} and {cfg.L_max:g}."))
        L = None
    for name, v, key in (("a*", a, "a"), ("b*", b, "b")):
        if v is not None and not (cfg.ab_min <= v <= cfg.ab_max):
            errors.append(_err(f"{prefix}{key}", "out_of_range", f"{name} must be between {cfg.ab_min:g} and {cfg.ab_max:g}."))
            if key == "a":
                a = None
            else:
                b = None
    if L is not None and b is not None and L == 50.0 and b == 0.0:
        errors.append(_err(f"{prefix}b", "undefined_ita", "ITA is undefined when L* = 50 and b* = 0. Check the measurement."))
        b = None
    return L, a, b


def _thresholds(rcfg: ReliabilityConfig) -> dict:
    return {"light_above": rcfg.ita_light_above, "dark_at_most": rcfg.ita_dark_at_most,
            "note": "Configured ITA cut-offs."}


def _usable(ita: float, rcfg: ReliabilityConfig) -> bool:
    return rcfg.ita_min <= ita <= rcfg.ita_max


def _one(L: float, a: float, b: float, location, rcfg: ReliabilityConfig) -> dict:
    ita = round(compute_ita(L, b), 3)
    warnings = []
    if b <= 0:
        warnings.append("b* is zero or negative, which is unusual for skin colorimetry. ITA was computed with the standard "
                        "arctan((L* - 50) / b*) definition, but the measurement should be checked.")
    usable = _usable(ita, rcfg)
    if not usable:
        warnings.append(f"ITA {ita}° is outside the range the Live Reliability Check supports "
                        f"({rcfg.ita_min:g}° to {rcfg.ita_max:g}°) and cannot be sent there.")
    return {"L": L, "a": a, "b": b, "ita": ita, "pigmentation_group": classify_ita(ita, rcfg),
            "location": location or NOT_SPECIFIED, "usable_for_reliability": usable, "warnings": warnings}


def calculate_ita(raw: dict, cfg: PigmentationConfig = PIGMENTATION_CONFIG,
                  rcfg: ReliabilityConfig = RELIABILITY_CONFIG) -> dict:
    errors: list[dict] = []
    L, a, b = _lab(raw, "", errors, cfg)
    loc = _location(raw.get("location"), "location", errors)
    if errors:
        raise InputValidationError(errors)
    return {**_one(L, a, b, loc, rcfg), "thresholds": _thresholds(rcfg), "label": LABEL}


def summarize_participant(measurements, location: str | None = None, cfg: PigmentationConfig = PIGMENTATION_CONFIG,
                          rcfg: ReliabilityConfig = RELIABILITY_CONFIG) -> dict:
    """Participant-level ITA = MEDIAN of the per-measurement ITA values.

    Measurements from different body locations are not interchangeable: if locations are mixed
    and none is selected, no single participant value is produced (per-location medians are
    returned instead). Invalid rows are reported with their row number, never dropped.
    """
    errors: list[dict] = []
    if not isinstance(measurements, list) or len(measurements) == 0:
        raise InputValidationError([_err("measurements", "missing", "At least one measurement is required.")])
    rows = []
    for i, m in enumerate(measurements):
        prefix = f"measurements[{i}]."
        if not isinstance(m, dict):
            errors.append(_err(f"measurements[{i}]", "invalid_type", f"Measurement {i + 1} is not valid."))
            continue
        L, a, b = _lab(m, prefix, errors, cfg)
        loc = _location(m.get("location"), f"{prefix}location", errors)
        if None not in (L, a, b):
            rows.append((i, L, a, b, loc))
    if location is not None and location != NOT_SPECIFIED and location not in LOCATIONS:
        errors.append(_err("location", "invalid_choice", f"Location filter must be one of: {', '.join(LOCATIONS)}, {NOT_SPECIFIED}."))
    if errors:
        for e in errors:  # make row numbers human readable
            if e["field"].startswith("measurements["):
                idx = int(e["field"].split("[")[1].split("]")[0]) + 1
                e["message"] = f"Measurement {idx}: {e['message']}"
        raise InputValidationError(errors)

    items = [{"index": i + 1, **_one(L, a, b, loc, rcfg)} for i, L, a, b, loc in rows]
    locations = sorted({it["location"] for it in items})
    by_location = {}
    for loc in locations:
        itas = [it["ita"] for it in items if it["location"] == loc]
        med = round(statistics.median(itas), 3)
        by_location[loc] = {"n": len(itas), "median_ita": med, "pigmentation_group": classify_ita(med, rcfg),
                            "usable_for_reliability": _usable(med, rcfg)}

    warnings: list[str] = []
    mixed = len(locations) > 1
    selected = [it for it in items if location is None or it["location"] == location]
    if location is not None and not selected:
        raise InputValidationError([_err("location", "no_measurements", f"No measurements were taken at '{location}'.")])

    median_ita = group = used_loc = None
    usable = False
    if mixed and location is None:
        warnings.append("Measurements come from different locations, which are not interchangeable. "
                        "Select one location to obtain a participant-level value.")
    else:
        vals = [it["ita"] for it in selected]
        median_ita = round(statistics.median(vals), 3)
        group = classify_ita(median_ita, rcfg)
        used_loc = selected[0]["location"]
        usable = _usable(median_ita, rcfg)
        if len(vals) > 1 and max(vals) - min(vals) > cfg.repeat_spread_warn_deg:
            warnings.append(f"Repeated measurements differ by more than {cfg.repeat_spread_warn_deg:g}° "
                            f"(range {min(vals):.1f}° to {max(vals):.1f}°). Check contact, ambient light and placement.")
        if not usable:
            warnings.append(f"Median ITA is outside the range the Live Reliability Check supports "
                            f"({rcfg.ita_min:g}° to {rcfg.ita_max:g}°).")
    return {"n": len(items), "n_used": len(selected), "measurements": items, "median_ita": median_ita,
            "pigmentation_group": group, "location": used_loc, "mixed_locations": mixed,
            "by_location": by_location, "usable_for_reliability": usable, "warnings": warnings,
            "thresholds": _thresholds(rcfg), "label": LABEL,
            "note": "Participant-level ITA is the median of repeated measurements."}
