"""Fit the quantile models (TRAIN), calibrate (CALIBRATION), evaluate coverage (TEST). Nothing else touches these splits.

  TRAIN        -> quantile regressors q(alpha/2), q(0.5), q(1-alpha/2); hyperparameters by participant-grouped CV inside TRAIN
  CALIBRATION  -> CQR scores, Mondrian cell quantiles Q
  TEST         -> final coverage / width evaluation only (never used to fit or calibrate)
"""

import json
import platform
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import sklearn
from sklearn.metrics import make_scorer, mean_pinball_loss
from sklearn.model_selection import GridSearchCV, GroupKFold

from ..config import CONFORMAL_CONFIG, COVERAGE_WORDING, RELIABILITY_CONFIG, ConformalConfig
from ..ml.data import GROUP_COL, TARGET_COL, ModelError, save_artifact, current_hashes, load_splits, select_features, split_summary
from ..ml.paths import Paths, get_paths
from ..ml.train import FEATURE_VERSION, _require_lightgbm, dataset_version, lightgbm_available, require_trainable_dataset
from . import core

MODELS_FILE = "cqr_models.joblib"
CONFORMAL_MODEL_VERSION = "cqr-lightgbm-mondrian-v1"
CALIBRATION_FILE = "conformal_calibration.json"
METRICS_FILE = "conformal_metrics.json"
PREDICTIONS_FILE = "conformal_test_predictions.csv"


def _fit_quantile(X, y, groups, q: float, folds: int, cfg: ConformalConfig):
    from lightgbm import LGBMRegressor
    base = LGBMRegressor(objective="quantile", alpha=q, learning_rate=cfg.lgbm_learning_rate, min_child_samples=cfg.lgbm_min_child_samples,
                         random_state=cfg.seed, n_jobs=1, verbose=-1, deterministic=True, force_row_wise=True)
    gs = GridSearchCV(base, {"num_leaves": list(cfg.lgbm_num_leaves), "n_estimators": list(cfg.lgbm_n_estimators)},
                      cv=GroupKFold(n_splits=folds), scoring=make_scorer(mean_pinball_loss, alpha=q, greater_is_better=False), refit=True, n_jobs=1)
    gs.fit(X, y, groups=groups)
    return gs


def _predict_quantiles(models: dict, X: pd.DataFrame):
    lo, hi = core.order_quantiles(models["lo"].predict(X), models["hi"].predict(X))
    return lo, np.asarray(models["median"].predict(X), dtype=float), hi


def _intervals(lo, hi, ita_groups, pi_groups, calibration: dict, marginal: bool = False):
    """Per-row [lower, upper] using the Mondrian Q of each row's cell (NaN where the cell is INSUFFICIENT)."""
    lower, upper = np.full(len(lo), np.nan), np.full(len(lo), np.nan)
    status = []
    for i, (a, b) in enumerate(zip(ita_groups, pi_groups)):
        if marginal:
            q, st = calibration["marginal"]["q"], ("CALIBRATED" if calibration["marginal"]["sufficient"] else core.INSUFFICIENT)
            q = q if st != core.INSUFFICIENT else None
        else:
            q, cell = core.q_for(calibration, a, b)
            st = cell["status"]
        status.append(st)
        if q is not None:
            l, u = core.make_interval(lo[i:i + 1], hi[i:i + 1], q)
            lower[i], upper[i] = l[0], u[0]
    return lower, upper, status


def _json_safe(o):
    if isinstance(o, dict):
        return {k: _json_safe(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_json_safe(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def fit_conformal(paths: Paths | None = None, cfg: ConformalConfig = CONFORMAL_CONFIG) -> dict:
    paths = paths or get_paths()
    _require_lightgbm()
    provenance = require_trainable_dataset(paths)
    frames = load_splits(paths)
    features, excluded = select_features(frames)
    train, cal, test = frames["train"], frames["calibration"], frames["test"]
    folds = min(cfg.cv_folds, int(train[GROUP_COL].nunique()))
    if folds < 2:
        raise ModelError("too_few_participants", "At least 2 training participants are needed for grouped cross-validation.", "train")

    # ---- 1. TRAIN only: quantile models
    qs = {"lo": cfg.alpha / 2, "median": 0.5, "hi": 1 - cfg.alpha / 2}
    searches = {name: _fit_quantile(train[features], train[TARGET_COL].to_numpy(float), train[GROUP_COL], q, folds, cfg) for name, q in qs.items()}
    models = {name: gs.best_estimator_ for name, gs in searches.items()}

    # ---- 2. CALIBRATION only: CQR scores and Mondrian cell quantiles
    c_lo, _, c_hi = _predict_quantiles(models, cal[features])
    scores = core.cqr_scores(cal[TARGET_COL].to_numpy(float), c_lo, c_hi)
    c_ig, c_pg = core.assign_groups(cal["ita"], cal["pi"])
    calibration = core.calibrate(scores, c_ig, c_pg, cal[GROUP_COL], cfg)

    # ---- 3. TEST only: coverage
    t_lo, t_med, t_hi = _predict_quantiles(models, test[features])
    t_ig, t_pg = core.assign_groups(test["ita"], test["pi"])
    y = test[TARGET_COL].to_numpy(float)
    lower, upper, status = _intervals(t_lo, t_hi, t_ig, t_pg, calibration)
    m_lower, m_upper, _ = _intervals(t_lo, t_hi, t_ig, t_pg, calibration, marginal=True)
    base = pd.DataFrame({"participant_id": test[GROUP_COL].to_numpy(), "y": y, "ita_group": t_ig, "pi_group": t_pg})
    mondrian = core.coverage_report(base.assign(lower=lower, upper=upper), cfg)
    marginal = core.coverage_report(base.assign(lower=m_lower, upper=m_upper), cfg)
    raw = core.coverage_report(base.assign(lower=np.clip(t_lo, 0, 100), upper=np.clip(t_hi, 0, 100)), cfg)

    preds = pd.DataFrame({
        "participant_id": test[GROUP_COL].to_numpy(), "spo2": test["spo2"].to_numpy(float), "sao2": y,
        "predicted_sao2": np.where(np.isnan(lower), np.nan, t_med), "lower_bound": lower, "upper_bound": upper, "interval_width": upper - lower,
        "covered": np.where(np.isnan(lower), "", ((y >= lower) & (y <= upper)).astype(str)),
        "ita_group": t_ig, "pi_group": t_pg, "calibration_status": status})

    result = {
        "status": "fitted", "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data_provenance": provenance,
        "dataset": {"splits": split_summary(paths, frames), "test_use": "final evaluation only; never used to fit or calibrate"},
        "features": features, "excluded_features": excluded,
        "feature_ranges": {c: [float(train[c].min()), float(train[c].max())] for c in features},
        "config": cfg.as_dict(), "target_coverage": 1 - cfg.alpha,
        "versions": {"dataset_version": dataset_version(paths), "feature_version": FEATURE_VERSION, "model_version": CONFORMAL_MODEL_VERSION},
        "cell_definitions": {"ita_groups": {"Light": f"ITA > {RELIABILITY_CONFIG.ita_light_above:g}", "Medium": "otherwise", "Dark": f"ITA <= {RELIABILITY_CONFIG.ita_dark_at_most:g}"},
                             "pi_groups": {"Low": f"PI < {RELIABILITY_CONFIG.pi_low_below:g}", "Normal": f"PI >= {RELIABILITY_CONFIG.pi_low_below:g}"},
                             "cells": [core.cell_label(a, b) for a, b in core.CELLS], "source": "services/features.py (shared with the reliability engine)"},
        "calibration_sample_counts": {"rows": int(len(cal)), "participants": int(cal[GROUP_COL].nunique())},
        "quantile_models": {name: {"quantile": qs[name], "best_params": {k: (v.item() if hasattr(v, "item") else v) for k, v in gs.best_params_.items()},
                                   "cv_pinball_loss": float(-gs.best_score_), "cv_scheme": f"GroupKFold({folds}) by participant, TRAIN split only"}
                            for name, gs in searches.items()},
        "calibration": calibration,
        "coverage": {"target_coverage": 1 - cfg.alpha, "mondrian": mondrian, "marginal": marginal, "uncalibrated_quantiles": raw},
        "wording": COVERAGE_WORDING,
        "software": {"python": sys.version.split()[0], "platform": platform.system(), "scikit_learn": sklearn.__version__,
                     "lightgbm": __import__("lightgbm").__version__, "pandas": pd.__version__, "numpy": np.__version__},
        "notes": ["Quantile models use the TRAIN split; Q uses the CALIBRATION split; coverage uses the TEST split only.",
                  "Cells without enough calibration participants are merged by the documented rule or reported as INSUFFICIENT CALIBRATION DATA — never filled in.",
                  "Not clinically validated."],
    }
    paths.models.mkdir(parents=True, exist_ok=True)
    paths.results.mkdir(parents=True, exist_ok=True)
    save_artifact({"models": models, "features": features, "alpha": cfg.alpha, "trained_at": result["trained_at"]}, paths.models / MODELS_FILE)
    preds.to_csv(paths.results / PREDICTIONS_FILE, index=False)
    (paths.results / CALIBRATION_FILE).write_text(json.dumps(_json_safe({"calibration": calibration, "alpha": cfg.alpha, "features": features,
                                                                         "trained_at": result["trained_at"]}), indent=2, allow_nan=False), encoding="utf-8")
    (paths.results / METRICS_FILE).write_text(json.dumps(_json_safe(result), indent=2, allow_nan=False), encoding="utf-8")
    return result


# ------------------------------------------------------------------ reading
def read_metrics(paths: Paths | None = None) -> dict:
    paths = paths or get_paths()
    f = paths.results / METRICS_FILE
    if not f.exists():
        raise ModelError("not_calibrated", "CONFORMAL MODEL NOT AVAILABLE. The conformal reliability layer has not been fitted and calibrated on a real research dataset yet.")
    try:
        m = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ModelError("metrics_unreadable", "The saved conformal metrics could not be read. Fit again.")
    if m.get("data_provenance", {}).get("kind") != "LOADED":
        raise ModelError("not_calibrated", "CONFORMAL MODEL NOT AVAILABLE. The saved conformal layer was not fitted on a verified research dataset and is ignored.")
    return m


def status(paths: Paths | None = None) -> dict:
    paths = paths or get_paths()
    arts = {"models": (paths.models / MODELS_FILE).exists(), "calibration": (paths.results / CALIBRATION_FILE).exists(),
            "metrics": (paths.results / METRICS_FILE).exists(), "test_predictions": (paths.results / PREDICTIONS_FILE).exists()}
    blockers: list[str] = []
    try:
        require_trainable_dataset(paths)
        if not all((paths.processed / f"{n}.csv").exists() for n in ("train", "calibration", "test")):
            blockers.append("The research dataset has not been validated and split yet (Dataset page).")
    except ModelError as exc:
        blockers.append(exc.message)
    if not lightgbm_available():
        blockers.append("LightGBM is not installed (pip install lightgbm).")
    out = {"available": False, "message": "CONFORMAL MODEL NOT AVAILABLE", "fitted": False, "artifacts": arts, "can_fit": not blockers, "blockers": blockers, "stale": None, "alpha": CONFORMAL_CONFIG.alpha,
           "target_coverage": 1 - CONFORMAL_CONFIG.alpha, "calibration_summary": None, "fitted_at": None}
    if all(arts.values()):
        try:
            m = read_metrics(paths)
        except ModelError:
            return out
        out["available"], out["message"] = True, None
        out["fitted"], out["fitted_at"], out["alpha"], out["target_coverage"] = True, m["trained_at"], m["config"]["alpha"], m["target_coverage"]
        cells = m["calibration"]["cells"].values()
        out["calibration_summary"] = {"calibrated": sum(c["status"] == core.CALIBRATED for c in cells), "merged": sum(c["status"] == core.MERGED for c in cells),
                                      "insufficient": sum(c["status"] == core.INSUFFICIENT for c in cells)}
        out["stale"] = current_hashes(paths) != {k: v["sha256"] for k, v in m["dataset"]["splits"].items()}
    return out
