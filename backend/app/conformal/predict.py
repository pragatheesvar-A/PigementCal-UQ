"""Conformal prediction for one reading and the reliability state built on it.

Core principle: when the system does not have enough evidence to be reliable, it does not pretend to be confident.
ABSTAIN is returned (with the reasons) for: poor signal, high motion, input outside the range the models were fitted on,
model inputs that were not supplied, and a calibration cell with INSUFFICIENT CALIBRATION DATA. No interval is produced then.
"""

import numpy as np
import pandas as pd

from ..config import CONFORMAL_CONFIG, COVERAGE_WORDING, DISCLAIMER, ConformalConfig
from ..ml.data import ModelError, load_artifact, readable
from ..ml.paths import Paths, get_paths
from ..pipeline.features import engineer_features
from ..services.reliability import STATUS_TEXT, assess
from . import core
from .fit import MODELS_FILE, read_metrics

LEVEL = {"GREEN": 0, "AMBER": 1, "RED": 2}
NAME = {0: "GREEN", 1: "AMBER", 2: "RED"}


def _reason(code: str, severity: str, title: str, text: str) -> dict:
    return {"code": code, "severity": severity, "title": title, "text": text}


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and np.isfinite(v) else None


def _abstain(res: dict, reasons: list[dict], extra: str | None = None) -> dict:
    reasons = list(reasons)
    reasons.append(_reason("abstain", "critical", "Abstaining",
                           extra or "There is not enough evidence to give a reliable, calibrated answer, so the system abstains instead of guessing."))
    return {**res, "reliability_state": "ABSTAIN", "status": STATUS_TEXT["ABSTAIN"], "reasons": reasons,
            "predicted_sao2": None, "interval": None, "lower_bound": None, "upper_bound": None, "interval_width": None}


def predict_one(raw: dict, paths: Paths | None = None, cfg: ConformalConfig = CONFORMAL_CONFIG) -> dict:
    """raw: spo2, pi, ita, signal_quality, motion (LOW/MEDIUM/HIGH), device, and — when the fitted models use them —
    sqi and motion_score (0-100). Raises InputValidationError for invalid values and ModelError('not_calibrated')."""
    paths = paths or get_paths()
    meta = read_metrics(paths)                                    # also proves the layer was fitted on verified data
    base = assess(raw)                                            # validates every input; rule engine on signal/motion/perfusion
    with readable("conformal models", "Fit and calibrate the conformal layer again."):
        art = load_artifact(paths.models / MODELS_FILE) if (paths.models / MODELS_FILE).exists() else None
    if art is None:
        raise ModelError("not_calibrated", "CONFORMAL MODEL NOT AVAILABLE. The conformal models are missing. Fit the conformal layer again.")
    features = art["features"]

    ig, pg = base["pigmentation_group"], base["perfusion_group"]
    calib = meta["calibration"]
    _, cell = core.q_for(calib, ig, pg)
    res = {"spo2": base["spo2"], "pi": base["pi"], "ita": base["ita"], "ita_group": ig, "pi_group": pg, "cell": {
               "label": cell["label"], "status": cell["status"], "n_participants": cell["n_participants"], "n_rows": cell["n_rows"],
               "source": cell["source"], "requirement": cell["requirement"]},
           "signal_quality": base["signal_quality"], "motion": base["motion"], "device": base["device"],
           "target_coverage": meta["target_coverage"], "method": "CQR + Mondrian (ITA group × PI group)",
           "wording": COVERAGE_WORDING, "disclaimer": DISCLAIMER, "base_state": base["reliability_state"]}

    base_reasons = [r for r in base["reasons"] if r["code"] not in ("subgroup_info", "good_conditions", "abstain")]
    if base["reliability_state"] == "ABSTAIN":                    # poor signal / high motion
        return _abstain(res, base_reasons, "The signal is not good enough for a reliable assessment. Consider reacquiring it.")

    # ---- supported range: the models only speak for the range they were fitted on
    sqi, motion_score = _num(raw.get("sqi")), _num(raw.get("motion_score"))
    inputs = {"spo2": base["spo2"], "pi": base["pi"], "ita": base["ita"]}
    missing = []
    if "sqi" in features:
        inputs["sqi"] = sqi
        missing += ["SQI"] if sqi is None else []
    if "motion" in features:
        inputs["motion"] = motion_score
        missing += ["motion score"] if motion_score is None else []
    if missing:
        return _abstain(res, base_reasons + [_reason("missing_inputs", "critical", "Model inputs missing",
                        f"The calibrated models also use {' and '.join(missing)} (from the live sensor or a recorded file), which was not provided.")])
    outside = [f"{k} = {v:g} (fitted range {lo:.3g}–{hi:.3g})" for k, v in inputs.items()
               for lo, hi in [meta["feature_ranges"][k]] if not (lo <= v <= hi)]
    if outside:
        return _abstain(res, base_reasons + [_reason("outside_range", "critical", "OUTSIDE VALIDATION RANGE",
                        "The calibrated models were not fitted on values like these: " + "; ".join(outside) + ".")])

    # ---- calibration availability for this ITA x PI cell
    q, cell = core.q_for(calib, ig, pg)
    if q is None:
        return _abstain(res, base_reasons + [_reason("insufficient_calibration", "critical", core.INSUFFICIENT_TEXT,
                        f"{cell['label']} has {cell['n_participants']} calibration participant(s) and {cell['n_rows']} row(s); the rule requires {cell['requirement']}. "
                        "No data were invented to fill the gap.")])

    # ---- conformal interval
    row = pd.DataFrame([engineer_features({k: v for k, v in {"spo2": inputs["spo2"], "pi": inputs["pi"], "ita": inputs["ita"],
                                                              "sqi": inputs.get("sqi"), "motion": inputs.get("motion")}.items() if v is not None})])[features]
    lo, med, hi = (float(models.predict(row)[0]) for models in (art["models"]["lo"], art["models"]["median"], art["models"]["hi"]))
    lo, hi = min(lo, hi), max(lo, hi)
    lower, upper = (float(x[0]) for x in core.make_interval(np.array([lo]), np.array([hi]), q))
    width, gap = upper - lower, base["spo2"] - lower

    reasons = list(base_reasons)
    if cell["status"] == core.MERGED:
        reasons.append(_reason("merged_cell", "warning", "Merged calibration cell",
                               f"{cell['label']} had too few calibration participants of its own; its interval uses the {ig} group pooled over PI "
                               "(documented merge rule). This is not a per-cell guarantee."))
    else:
        reasons.append(_reason("calibrated_cell", "info", "Calibrated cell",
                               f"{cell['label']}: calibrated on {cell['n_participants']} participants ({cell['n_rows']} readings)."))
    w_level = 2 if width > cfg.width_red else 1 if width > cfg.width_amber else 0
    g_level = 2 if gap > cfg.gap_red else 1 if gap > cfg.gap_amber else 0
    if w_level:
        reasons.append(_reason("wide_interval", "critical" if w_level == 2 else "warning", "Wide calibrated interval",
                               f"The calibrated interval is {width:.1f} points wide (configured thresholds {cfg.width_amber:g} / {cfg.width_red:g})."))
    if g_level:
        reasons.append(_reason("low_lower_bound", "critical" if g_level == 2 else "warning", "Conservative lower bound below the reading",
                               f"The conformal lower bound ({lower:.1f}%) is {gap:.1f} points below the displayed SpO₂ ({base['spo2']:g}%). "
                               "It is a conservative reliability signal, not a diagnosis."))
    level = max(LEVEL[base["reliability_state"]], w_level, g_level)
    if level == 0:
        reasons.append(_reason("good_conditions", "info", "Favorable conditions", "Signal, motion, perfusion and the calibrated interval raise no flags."))
    state = NAME[level]
    return {**res, "reliability_state": state, "status": STATUS_TEXT[state], "reasons": reasons,
            "predicted_sao2": round(float(np.clip(med, lower, upper)), 2),
            "interval": {"lower": round(lower, 2), "upper": round(upper, 2), "width": round(width, 2)},
            "lower_bound": round(lower, 2), "upper_bound": round(upper, 2), "interval_width": round(width, 2)}
