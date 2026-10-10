"""Model training: Ridge (interpretable baseline) and LightGBM (nonlinear comparator).

Data discipline
  * Both models are fitted on the TRAIN split only.
  * Hyperparameters are chosen by participant-grouped cross-validation INSIDE the train split.
  * The CALIBRATION split is validated but not used at all here — it is reserved for conformal
    conformal calibration.
  * The TEST split is used once, after fitting, for evaluation only.
"""

import json
import platform
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import sklearn
from sklearn.linear_model import Ridge
from sklearn.model_selection import GridSearchCV, GroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ..config import MODEL_CONFIG, ModelConfig
from .data import (
    save_artifact,
    GROUP_COL, TARGET_COL, ModelError, dataset_provenance, load_splits, manifest_seed, select_features, split_summary,
)
from .metrics import regression_metrics, subgroup_errors
from .paths import Paths, get_paths

RIDGE_FILE = "ridge_model.joblib"
LGBM_FILE = "lightgbm_model.joblib"
METRICS_FILE = "model_metrics.json"
PREDICTIONS_FILE = "test_predictions.csv"
FEATURE_VERSION = "features-v1"          # bump when the feature definitions in services/features.py change
MODEL_VERSION = "ridge+lightgbm-v1"
NOT_READY_MESSAGE = "Training unavailable \u2014 real research dataset is not ready."
PREDICTION_COLUMNS = ["participant_id", "session_id", "spo2", "sao2", "ridge_prediction", "lightgbm_prediction",
                      "ridge_error", "lightgbm_error"]
ERROR_DEFINITION = "error = prediction - sao2 (positive = over-estimates SaO2)"


def dataset_version(paths: Paths) -> str | None:
    """Short content hash of the research dataset the splits were made from (None if unavailable)."""
    try:
        return json.loads((paths.raw / "dataset_meta.json").read_text(encoding="utf-8"))["sha256"][:16]
    except (OSError, ValueError, KeyError):
        return None


def lightgbm_available() -> bool:
    try:
        import lightgbm  # noqa: F401
        return True
    except ImportError:
        return False


def _require_lightgbm() -> None:
    """LightGBM is required. If it is missing we stop with an installation message — we never
    quietly substitute another model."""
    if not lightgbm_available():
        raise ModelError("lightgbm_missing",
                         "LightGBM is not installed, so no models were trained (Ridge is not used as a substitute). "
                         "Install it with:  pip install lightgbm  (it is listed in backend/requirements.txt).")


def _plain(v):
    return v.item() if hasattr(v, "item") else v


def _search(estimator, grid: dict, X, y, groups, folds: int) -> GridSearchCV:
    """Grouped CV on the TRAIN split only; the best configuration is refit on all training rows."""
    gs = GridSearchCV(estimator, grid, cv=GroupKFold(n_splits=folds), scoring="neg_mean_absolute_error",
                      refit=True, n_jobs=1)
    gs.fit(X, y, groups=groups)
    return gs


def _tuning_info(gs: GridSearchCV) -> dict:
    return {"best_params": {k: _plain(v) for k, v in gs.best_params_.items()},
            "cv_mae": float(-gs.best_score_), "cv_scheme": f"GroupKFold({gs.cv.n_splits}) by participant, train split only"}


def _training_gate(paths: Paths) -> list[str]:
    """Blockers recorded when the research dataset was built (too few valid participants, no valid records...)."""
    try:
        q = json.loads((paths.processed / "research_data_quality.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []              # no build record (e.g. a dataset prepared another way): the processing step still enforces minimums
    mt = q.get("model_training", {})
    reasons = [r for r in mt.get("reasons", []) if "never started automatically" not in r] if mt.get("blocked") else []
    if not reasons and q.get("readiness", {}).get("status", "READY FOR TRAINING") != "READY FOR TRAINING":
        reasons = list(q["readiness"].get("reasons") or ["The dataset is not ready."])
    return reasons


def require_trainable_dataset(paths: Paths) -> dict:
    """Shared gate for everything that fits a model (point models and the conformal layer): a dataset built on Data
    Collection from attested real uploads, matching the processed splits, with enough valid participants."""
    provenance = dataset_provenance(paths)
    if provenance["kind"] == "NONE":
        raise ModelError("no_dataset", NOT_READY_MESSAGE + " No research dataset is loaded, so there is nothing to train on. "
                         "Upload a dataset on the Dataset page and run the processing step first.")
    if provenance["kind"] == "UNVERIFIED":
        raise ModelError("unverified_data", NOT_READY_MESSAGE + " " + provenance["label"] + ". " + provenance["reason"])
    if provenance["kind"] == "MISMATCH":
        raise ModelError("data_mismatch", NOT_READY_MESSAGE + " " + provenance["reason"])
    gate = _training_gate(paths)
    if gate:
        raise ModelError("training_blocked", NOT_READY_MESSAGE + " Model training is blocked: " + " ".join(gate))
    return provenance


def train_models(paths: Paths | None = None, cfg: ModelConfig = MODEL_CONFIG) -> dict:
    paths = paths or get_paths()
    _require_lightgbm()
    from lightgbm import LGBMRegressor

    provenance = require_trainable_dataset(paths)
    frames = load_splits(paths)
    FEATURES, excluded_features = select_features(frames)      # also runs the target-leakage guard
    train, test = frames["train"], frames["test"]

    X_train, y_train, g_train = train[FEATURES], train[TARGET_COL].to_numpy(float), train[GROUP_COL]
    folds = min(cfg.cv_folds, int(g_train.nunique()))
    if folds < 2:
        raise ModelError("too_few_participants", "At least 2 training participants are needed for grouped cross-validation.", "train")

    ridge_gs = _search(Pipeline([("scale", StandardScaler()), ("ridge", Ridge())]),
                       {"ridge__alpha": list(cfg.ridge_alphas)}, X_train, y_train, g_train, folds)
    lgbm_gs = _search(
        LGBMRegressor(learning_rate=cfg.lgbm_learning_rate, min_child_samples=cfg.lgbm_min_child_samples,
                      random_state=cfg.seed, n_jobs=1, verbose=-1, deterministic=True, force_row_wise=True),
        {"num_leaves": list(cfg.lgbm_num_leaves), "n_estimators": list(cfg.lgbm_n_estimators)},
        X_train, y_train, g_train, folds)
    ridge, lgbm = ridge_gs.best_estimator_, lgbm_gs.best_estimator_

    # ---- evaluation on TEST only (first and only use of the test split) ----
    X_test, y_test, g_test = test[FEATURES], test[TARGET_COL].to_numpy(float), test[GROUP_COL]
    ridge_pred, lgbm_pred = ridge.predict(X_test), lgbm.predict(X_test)
    m_ridge = regression_metrics(y_test, ridge_pred, g_test)
    m_lgbm = regression_metrics(y_test, lgbm_pred, g_test)
    m_ref = regression_metrics(y_test, test["spo2"].to_numpy(float), g_test)

    preds = pd.DataFrame({
        "participant_id": test[GROUP_COL].to_numpy(), "session_id": test["session_id"].fillna("").astype(str).to_numpy() if "session_id" in test else "",
        "spo2": test["spo2"].to_numpy(float), "sao2": y_test,
        "ridge_prediction": ridge_pred, "lightgbm_prediction": lgbm_pred,
        "ridge_error": ridge_pred - y_test, "lightgbm_error": lgbm_pred - y_test,
    })[PREDICTION_COLUMNS]

    sub_frame = pd.DataFrame({
        GROUP_COL: test[GROUP_COL].to_numpy(), "ita": test["ita"].to_numpy(float), "pi": test["pi"].to_numpy(float),
        "sao2": y_test, "ridge": ridge_pred, "lightgbm": lgbm_pred, "spo2_as_is": test["spo2"].to_numpy(float),
    })
    subgroups = subgroup_errors(sub_frame, {"ridge": "ridge", "lightgbm": "lightgbm", "spo2_as_is": "spo2_as_is"})

    best = "ridge" if m_ridge["mae"] <= m_lgbm["mae"] else "lightgbm"
    other = "lightgbm" if best == "ridge" else "ridge"
    maes = {"ridge": m_ridge["mae"], "lightgbm": m_lgbm["mae"]}

    result = {
        "status": "trained", "phase": 13,
        "versions": {"dataset_version": dataset_version(paths), "feature_version": FEATURE_VERSION, "model_version": MODEL_VERSION},
        "counts": {k: {"participants": int(frames[k][GROUP_COL].nunique()), "observations": int(len(frames[k]))} for k in ("train", "calibration", "test")},
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data_provenance": provenance,
        "dataset": {"splits": split_summary(paths, frames), "split_seed": manifest_seed(paths),
                    "calibration_use": "Validated for participant leakage but NOT used for fitting the point models (reserved for conformal calibration)."},
        "features": FEATURES, "excluded_features": excluded_features, "target": f"sao2 (column '{TARGET_COL}')",
        "feature_ranges": {c: [float(train[c].min()), float(train[c].max())] for c in FEATURES},
        "error_definition": ERROR_DEFINITION,
        "models": {
            "ridge": {"label": "Ridge regression (interpretable baseline)", "metrics": m_ridge, **_tuning_info(ridge_gs), "file": RIDGE_FILE},
            "lightgbm": {"label": "LightGBM (nonlinear comparator)", "metrics": m_lgbm, **_tuning_info(lgbm_gs), "file": LGBM_FILE},
        },
        "reference": {"label": "SpO2 reading used as-is (no model)", "metrics": m_ref},
        "best_model": {"name": best, "criterion": "lowest test-set MAE", "mae": maes[best], "other_mae": maes[other],
                       "mae_difference": maes[other] - maes[best],
                       "note": "Selected by test-set MAE only. This is an empirical comparison on this dataset, not a claim of clinical superiority."},
        "subgroups": subgroups,
        "config": cfg.as_dict(),
        "software": {"python": sys.version.split()[0], "platform": platform.system(), "scikit_learn": sklearn.__version__,
                     "lightgbm": __import__("lightgbm").__version__, "pandas": pd.__version__, "numpy": np.__version__},
        "notes": ["Hyperparameters were tuned by participant-grouped cross-validation on the training split only.",
                  "The test split was used once, for evaluation after fitting.",
                  "Model performance is an empirical evaluation, not clinical accuracy."],
    }

    # ---- save artifacts (only after everything above succeeded) ----
    paths.models.mkdir(parents=True, exist_ok=True)
    paths.results.mkdir(parents=True, exist_ok=True)
    stamp = result["trained_at"]
    save_artifact({"model": ridge, "features": FEATURES, "name": "ridge", "trained_at": stamp}, paths.models / RIDGE_FILE)
    save_artifact({"model": lgbm, "features": FEATURES, "name": "lightgbm", "trained_at": stamp}, paths.models / LGBM_FILE)
    preds.to_csv(paths.results / PREDICTIONS_FILE, index=False)
    (paths.results / METRICS_FILE).write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    return result
