"""Final validation report and explainability, built ONLY from saved artifacts of real, verified runs."""

from datetime import datetime, timezone

import numpy as np
import pandas as pd

from ..config import CONFORMAL_CONFIG, MODEL_CONFIG, VALIDATION_CONFIG, XAI_NOTICE, ValidationConfig
from ..conformal import core as ccore
from ..conformal import fit as cfit
from ..ml import service as mservice
from ..ml.data import GROUP_COL, ModelError, current_hashes, load_artifact, readable
from ..ml.paths import Paths, get_paths
from ..ml.train import LGBM_FILE, PREDICTIONS_FILE, RIDGE_FILE
from ..governance import research_gate
from . import stats

FEATURE_TEXT = {
    "spo2": "SpO₂ reading", "d": "100 − SpO₂ (desaturation)", "pi": "Perfusion index", "log_pi": "log(PI)", "ita": "ITA (objective pigmentation)",
    "ita_x_d": "ITA × desaturation", "log_pi_x_d": "log(PI) × desaturation", "ita_x_log_pi": "ITA × log(PI)", "sqi": "Signal quality (SQI)", "motion": "Motion score",
}


def _groups(test: pd.DataFrame):
    ig, pg = ccore.assign_groups(test["ita"], test["pi"])
    return pd.Series(ig, index=test.index), pd.Series(pg, index=test.index)


def _load(paths: Paths):
    metrics = mservice.read_metrics(paths)                       # raises model_not_trained for missing / non-verified runs
    if not mservice._is_valid_run(metrics):
        raise ModelError("model_not_trained", mservice.LEGACY_NOTE)
    pred = pd.read_csv(paths.results / PREDICTIONS_FILE)
    test = pd.read_csv(paths.processed / "test.csv")
    if len(pred) != len(test) or not (pred["participant_id"].astype(str).to_numpy() == test[GROUP_COL].astype(str).to_numpy()).all():
        raise ModelError("inconsistent_artifacts", "The saved predictions do not match the current test split. Train the models again.")
    return metrics, pred, test


def _hist(series: dict[str, np.ndarray], bins: int) -> dict:
    allv = np.concatenate([v for v in series.values() if len(v)])
    edges = np.linspace(float(allv.min()), float(allv.max()), bins + 1) if len(allv) and allv.min() < allv.max() else np.array([0.0, 1.0])
    return {"edges": [round(float(e), 3) for e in edges], "counts": {k: np.histogram(v, bins=edges)[0].astype(int).tolist() for k, v in series.items()}}


def build_report(paths: Paths | None = None, cfg: ValidationConfig = VALIDATION_CONFIG) -> dict:
    paths = paths or get_paths()
    with readable("results and test split"):
        metrics, pred, test = _load(paths)
    ig, pg = _groups(test)
    pred = pred.assign(ita_group=ig.to_numpy(), pi_group=pg.to_numpy(), cell=(ig + "|" + pg).to_numpy())
    models = {"ridge": "ridge_prediction", "lightgbm": "lightgbm_prediction", "spo2_as_is": "spo2"}

    overall = {name: stats.error_metrics(pred, col, cfg=cfg) for name, col in models.items()}

    def by(mask_fn, labels):
        out = []
        for lab in labels:
            sub = pred[mask_fn(lab)]
            n_part = int(sub["participant_id"].nunique())
            enough = n_part >= MODEL_CONFIG.min_subgroup_participants        # below this, no value is produced at all
            out.append({"group": lab if isinstance(lab, str) else f"{lab[0]} × {lab[1]} PI", "n_obs": int(len(sub)), "n_participants": n_part,
                        "status": "OK" if enough else "INSUFFICIENT DATA",
                        **{name: (stats.error_metrics(sub, col, names=("MAE", "Bias"), cfg=cfg) if len(sub) and enough else []) for name, col in models.items()}})
        return out

    subgroups = {"ita": by(lambda g: pred["ita_group"] == g, ccore.ITA_GROUPS), "pi": by(lambda g: pred["pi_group"] == g, ccore.PI_GROUPS),
                 "ita_x_pi": by(lambda c: (pred["ita_group"] == c[0]) & (pred["pi_group"] == c[1]), ccore.CELLS)}

    conformal = {"available": False}
    cpred = None
    try:
        cm = cfit.read_metrics(paths)
        cpred = pd.read_csv(paths.results / cfit.PREDICTIONS_FILE)
        if len(cpred) == len(test):
            def cby(mask, lab):
                sub = cpred[mask]
                have = sub[sub["lower_bound"].notna()]
                n_part = int(have["participant_id"].nunique())
                enough = n_part >= CONFORMAL_CONFIG.min_test_participants
                w = (have["upper_bound"] - have["lower_bound"])
                return {"group": lab, "n_total": int(len(sub)), "n_abstained": int(sub["lower_bound"].isna().sum()), "n_participants": n_part, "n_obs": int(len(have)),
                        "status": "OK" if enough else "INSUFFICIENT DATA", "median_width": float(w.median()) if len(w) and enough else None,
                        "metrics": stats.coverage_metrics(sub, cfg) if len(have) and enough else []}
            conformal = {"available": True, "target_coverage": cm["target_coverage"], "alpha": cm["config"]["alpha"],
                         "overall": {"group": "All test readings", "n_total": int(len(cpred)), "n_abstained": int(cpred["lower_bound"].isna().sum()),
                                 "n_participants": int(cpred[cpred["lower_bound"].notna()]["participant_id"].nunique()), "n_obs": int(cpred["lower_bound"].notna().sum()), "status": "OK",
                                 "median_width": float((cpred["upper_bound"] - cpred["lower_bound"]).median()) if cpred["lower_bound"].notna().any() else None,
                                 "metrics": stats.coverage_metrics(cpred, cfg)},
                         "ita": [cby(cpred["ita_group"] == g, g) for g in ccore.ITA_GROUPS], "pi": [cby(cpred["pi_group"] == g, g) for g in ccore.PI_GROUPS],
                         "ita_x_pi": [cby((cpred["ita_group"] == a) & (cpred["pi_group"] == b), ccore.cell_label(a, b)) for a, b in ccore.CELLS],
                         "calibration_cells": [{"label": c["label"], "status": c["status"], "n_participants": c["n_participants"], "n_rows": c["n_rows"]} for c in cm["calibration"]["cells"].values()],
                         "wording": cm["wording"]}
    except (ModelError, OSError, ValueError):
        pass

    n = min(cfg.plot_max_points, len(pred))
    idx = np.linspace(0, len(pred) - 1, n).astype(int) if len(pred) else []
    sc = pred.iloc[idx]
    plots = {"scatter": [{"sao2": float(r.sao2), "spo2": float(r.spo2), "ridge": float(r.ridge_prediction), "lightgbm": float(r.lightgbm_prediction)} for r in sc.itertuples()],
             "error_hist": _hist({"SpO₂ reading": (pred["spo2"] - pred["sao2"]).to_numpy(), "Ridge": pred["ridge_error"].to_numpy(), "LightGBM": pred["lightgbm_error"].to_numpy()}, cfg.hist_bins)}
    if conformal["available"] and cpred is not None and cpred["interval_width"].notna().any():
        plots["width_hist"] = _hist({"Interval width": cpred["interval_width"].dropna().to_numpy()}, cfg.hist_bins)

    stale = current_hashes(paths) != {k: v["sha256"] for k, v in metrics["dataset"]["splits"].items()}
    gate = research_gate.evaluate(paths)
    return {"available": True, "research_status": {k: gate[k] for k in ("state", "label", "results_allowed", "failed_checks")}, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "data_provenance": metrics["data_provenance"],
            "stale": bool(stale), "split": "TEST split only (never used for fitting, tuning or calibration)",
            "sample": {"test_participants": int(pred["participant_id"].nunique()), "test_observations": int(len(pred))},
            "bootstrap": {"method": "participant-level (cluster) percentile bootstrap", "replicates": cfg.bootstrap_reps, "seed": cfg.seed,
                          "level": cfg.level, "min_participants_for_ci": cfg.min_ci_participants},
            "error_definition": metrics["error_definition"], "overall": overall, "subgroups": subgroups, "conformal": conformal, "plots": plots,
            "notes": ["Confidence intervals are reported only where enough test participants exist; otherwise they are omitted, never estimated from too little data.",
                      "Estimates describe this dataset and these models. They are not clinical validation and do not show bias elimination, fairness or guaranteed accuracy."]}


# ------------------------------------------------------------------ explainability
def _gain(model) -> np.ndarray:
    g = np.asarray(model.booster_.feature_importance("gain"), dtype=float)
    return g / g.sum() if g.sum() > 0 else g


def build_xai(paths: Paths | None = None) -> dict:
    paths = paths or get_paths()
    with readable("models and test split"):
        metrics, _, test = _load(paths)
        feats = metrics["features"]
        ridge_art, lgbm_art = load_artifact(paths.models / RIDGE_FILE), load_artifact(paths.models / LGBM_FILE)
    pipe = ridge_art["model"]
    scaler, ridge = pipe.named_steps["scale"], pipe.named_steps["ridge"]
    std_coef = np.asarray(ridge.coef_, dtype=float)
    unit_coef = std_coef / np.asarray(scaler.scale_, dtype=float)
    ridge_rows = [{"feature": f, "description": FEATURE_TEXT.get(f, f), "coef_standardized": float(c), "coef_per_unit": float(u),
                   "direction": "raises predicted SaO₂" if c > 0 else "lowers predicted SaO₂" if c < 0 else "no effect"}
                  for f, c, u in zip(feats, std_coef, unit_coef)]
    ridge_rows.sort(key=lambda r: -abs(r["coef_standardized"]))

    model = lgbm_art["model"]
    X = test[feats]
    contrib = np.asarray(model.booster_.predict(X, pred_contrib=True), dtype=float)           # exact TreeSHAP values, last column = expected value
    shap_abs, shap_mean = np.abs(contrib[:, :-1]).mean(axis=0), contrib[:, :-1].mean(axis=0)
    gain = _gain(model)
    lgbm_rows = [{"feature": f, "description": FEATURE_TEXT.get(f, f), "gain_importance": float(g), "mean_abs_shap": float(a), "mean_shap": float(m)}
                 for f, g, a, m in zip(feats, gain, shap_abs, shap_mean)]
    lgbm_rows.sort(key=lambda r: -r["mean_abs_shap"])

    interval = None
    try:
        art = load_artifact(paths.models / cfit.MODELS_FILE)
        interval = {name: sorted([{"feature": f, "description": FEATURE_TEXT.get(f, f), "gain_importance": float(g)} for f, g in zip(art["features"], _gain(art["models"][name]))],
                                 key=lambda r: -r["gain_importance"]) for name in ("lo", "hi")}
    except (OSError, KeyError, ValueError):
        pass
    gate = research_gate.evaluate(paths)
    return {"available": True, "research_status": {k: gate[k] for k in ("state", "label", "results_allowed", "failed_checks")}, "data_provenance": metrics["data_provenance"], "notice": XAI_NOTICE, "features": feats,
            "ridge": {"intercept": float(ridge.intercept_), "alpha": float(ridge.alpha), "rows": ridge_rows,
                      "note": "Coefficients are for standardized features (change in predicted SaO₂ per 1 SD); per-unit coefficients use original units."},
            "lightgbm": {"rows": lgbm_rows, "shap_data": f"TEST split ({len(X)} readings), exact TreeSHAP via LightGBM pred_contrib",
                         "note": "Mean |SHAP| = average size of a feature's contribution to the predicted SaO₂ (percentage points); gain = share of split gain."},
            "interval_models": interval,
            "explanation": "Feature importance and coefficients describe what the fitted models rely on, not what causes differences in SaO₂. " + XAI_NOTICE}
