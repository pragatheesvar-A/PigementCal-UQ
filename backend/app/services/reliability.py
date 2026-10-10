"""Reliability service: a transparent rule engine over signal quality, motion, perfusion and pigmentation.

It reports a STATE and the REASONS behind it. It deliberately produces NO uncertainty range:
a calibrated range (CQR / ITA x PI Mondrian conformal calibration) needs a real dataset with
arterial SaO2 ground truth, and none is invented here. When such a model exists it will populate
`uncertainty_range`; until then that field is None and `uncertainty_note` says why.
"""

from ..config import DISCLAIMER, RELIABILITY_CONFIG, ReliabilityConfig
from .features import classify_ita, classify_pi, engineer_features
from .validation import validate_inputs

STATUS_TEXT = {
    "GREEN": "NO RELIABILITY FLAGS RAISED",
    "AMBER": "USE CAUTION",
    "RED": "LOW RELIABILITY",
    "ABSTAIN": "ABSTAIN — REACQUIRE SIGNAL",
}
UNCERTAINTY_NOTE = ("No calibrated uncertainty range is shown. It requires a real dataset with arterial SaO₂ "
                    "ground truth (conformal calibration), which has not been loaded and calibrated.")


def _reason(code: str, severity: str, title: str, text: str) -> dict:
    return {"code": code, "severity": severity, "title": title, "text": text}


def assess(raw: dict, cfg: ReliabilityConfig = RELIABILITY_CONFIG) -> dict:
    """Validate, engineer features and decide the reliability state. Raises InputValidationError on bad input."""
    x = validate_inputs(raw, cfg)
    pigmentation = classify_ita(x.ita, cfg)
    perfusion = classify_pi(x.pi, cfg)
    features = engineer_features(x.spo2, x.pi, x.ita)

    reasons: list[dict] = []
    abstain = False
    if x.signal_quality == "POOR":
        abstain = True
        reasons.append(_reason("poor_signal", "critical", "Poor signal",
                               "Signal quality is insufficient for a reliable assessment."))
    if x.motion == "HIGH":
        abstain = True
        reasons.append(_reason("high_motion", "critical", "High motion", "Motion may introduce PPG artifacts."))

    base = {
        "spo2": x.spo2, "pi": x.pi, "ita": x.ita,
        "pigmentation_group": pigmentation, "perfusion_group": perfusion, "perfusion_state": perfusion.upper(),
        "signal_quality": x.signal_quality, "motion": x.motion, "device": x.device, "sqi": x.sqi,
        "signal_source": raw.get("signal_source") or "manual", "ita_source": raw.get("ita_source") or "manual",
        "pi_source": raw.get("pi_source") or "manual",
        "features": features, "config": cfg.as_dict(), "disclaimer": DISCLAIMER,
        "uncertainty_range": None, "uncertainty_note": UNCERTAINTY_NOTE,
    }

    if abstain:
        reasons.append(_reason("abstain", "critical", "Abstaining",
                               "The system does not attempt to repair a poor signal. Consider reacquiring the reading."))
        return {**base, "reliability_state": "ABSTAIN", "status": STATUS_TEXT["ABSTAIN"], "points": None, "reasons": reasons}

    points = 0
    if perfusion == "Low":
        very_low = x.pi < cfg.pi_very_low_below
        points += cfg.points_very_low_pi if very_low else cfg.points_low_pi
        reasons.append(_reason("low_pi", "warning", "Low perfusion",
                               "Low perfusion may reduce signal strength and can increase measurement uncertainty."))
        if very_low:
            reasons.append(_reason("very_low_pi", "warning", "Very low perfusion",
                                   f"PI is below {cfg.pi_very_low_below:g}% (configured threshold), which counts more heavily."))
    if x.signal_quality == "MODERATE":
        points += cfg.points_moderate_signal
        reasons.append(_reason("moderate_signal", "warning", "Moderate signal quality",
                               "Moderate signal quality may increase uncertainty."))
    if x.motion == "MEDIUM":
        points += cfg.points_medium_motion
        reasons.append(_reason("medium_motion", "warning", "Some motion", "Motion may introduce PPG artifacts."))

    state = "RED" if points >= cfg.red_points else "AMBER" if points > 0 else "GREEN"
    if state == "RED":
        reasons.append(_reason("multiple_factors", "critical", "Several conditions at once",
                               f"Concurrent degrading conditions total {points} points (RED from {cfg.red_points})."))
    reasons.append(_reason("subgroup_info", "info", "Pigmentation × perfusion group",
                           f"Current objective pigmentation × perfusion group: {pigmentation} × {perfusion} PI. "
                           "Subgroup-specific calibrated uncertainty is not available until a real dataset is loaded and calibrated."))
    if state == "GREEN":
        reasons.append(_reason("good_conditions", "info", "Favorable conditions",
                               "Current signal-quality, motion and perfusion conditions are favorable."))
    return {**base, "reliability_state": state, "status": STATUS_TEXT[state], "points": points, "reasons": reasons}
