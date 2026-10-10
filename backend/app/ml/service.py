"""Read side of model training: status, saved metrics, saved test predictions, and single-reading prediction."""

import json
import math

import pandas as pd

from ..config import RELIABILITY_CONFIG
from ..pipeline.features import engineer_features  # the centralized feature pipeline
from ..services.validation import InputValidationError, _err
from .data import ModelError, load_artifact, current_hashes, dataset_provenance, readable, research_quality
from .paths import Paths, get_paths
from .train import LGBM_FILE, METRICS_FILE, PREDICTIONS_FILE, RIDGE_FILE, lightgbm_available

CORE_INPUTS = ("spo2", "pi", "ita")
OPTIONAL_INPUTS = ("sqi", "motion")
DISCLAIMER = "A model estimate for evaluation, not a measurement or a diagnosis."


def _artifacts(paths: Paths) -> dict:
    return {"ridge_model": (paths.models / RIDGE_FILE).exists(), "lightgbm_model": (paths.models / LGBM_FILE).exists(),
            "model_metrics": (paths.results / METRICS_FILE).exists(), "test_predictions": (paths.results / PREDICTIONS_FILE).exists()}


def read_metrics(paths: Paths | None = None) -> dict:
    paths = paths or get_paths()
    f = paths.results / METRICS_FILE
    if not f.exists():
        raise ModelError("model_not_trained", "No trained models yet. Train them first (POST /api/model/train).")
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ModelError("metrics_unreadable", "The saved metrics file could not be read. Retrain the models.")


LEGACY_NOTE = ("The models on disk were not trained on a loaded research dataset (for example an earlier "
               "synthetic run), so they are ignored. Load a dataset, process it and train again.")


def _is_valid_run(m: dict) -> bool:
    """Only models trained on a LOADED research dataset count as trained."""
    return m.get("data_provenance", {}).get("kind") == "LOADED"


def status(paths: Paths | None = None) -> dict:
    paths = paths or get_paths()
    arts = _artifacts(paths)
    trained = all(arts.values())
    cur = dataset_provenance(paths)
    out = {"trained": trained, "artifacts": arts, "lightgbm_available": lightgbm_available(),
           "processed_data_available": all((paths.processed / f"{n}.csv").exists() for n in ("train", "calibration", "test")),
           "current_data_provenance": cur, "trained_at": None, "stale": None, "stale_reason": None,
           "data_provenance": cur, "dataset": None}
    q = research_quality(paths)
    out["readiness"] = (q or {}).get("readiness", {"status": "NOT READY", "reasons": ["There are no valid real records."]})
    from ..governance import research_gate
    out["research_status"] = {k: v for k, v in research_gate.evaluate(paths).items() if k in ("state", "label", "results_allowed", "failed_checks")}
    out["research_results"] = out["research_status"]["results_allowed"]      # decided by the backend gate only
    out["research_data"] = ({"records": q["valid_records"], "participants": q["participants"], "sessions": q["sessions"],
                             "blocked": q["model_training"]["blocked"], "reasons": q["model_training"]["reasons"]} if q else
                            {"records": 0, "participants": 0, "sessions": 0, "blocked": True,
                             "reasons": ["There are no valid real records.", "Model training is never started automatically."]})
    if trained:
        try:
            m = read_metrics(paths)
        except ModelError:
            out["trained"] = False
            return out
        if not _is_valid_run(m):
            out["trained"] = False
            out["stale"], out["stale_reason"] = True, LEGACY_NOTE
            return out
        out["trained_at"] = m["trained_at"]
        out["data_provenance"] = m["data_provenance"]   # provenance at TRAINING time governs the result label
        out["dataset"] = m["dataset"]
        hashes = current_hashes(paths)
        trained_hashes = {k: v["sha256"] for k, v in m["dataset"]["splits"].items()}
        out["stale"] = hashes != trained_hashes
        if out["stale"]:
            out["stale_reason"] = "The processed data changed after these models were trained. Retrain to refresh the results."
        elif cur["kind"] != m["data_provenance"]["kind"]:
            out["stale"] = True
            out["stale_reason"] = "The dataset provenance changed since training. Retrain to refresh the results."
    return out


def read_predictions(limit: int = 100, offset: int = 0, paths: Paths | None = None) -> dict:
    paths = paths or get_paths()
    f = paths.results / PREDICTIONS_FILE
    if not f.exists():
        raise ModelError("model_not_trained", "No saved test predictions yet. Train the models first (POST /api/model/train).")
    with readable("test predictions"):
        df = pd.read_csv(f)
    if "session_id" in df:
        df["session_id"] = df["session_id"].fillna("")          # empty identifiers are blanks, not NaN (not JSON-safe)
    page = df.iloc[offset: offset + limit]
    return {"total": int(len(df)), "offset": offset, "limit": limit, "columns": list(df.columns),
            "rows": page.to_dict(orient="records")}


def _finite(v):
    return None if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) else float(v)


def required_inputs(features: list[str]) -> tuple[str, ...]:
    """Raw inputs needed by the trained models: SpO2, PI and ITA always, plus SQI / motion if the models use them."""
    return CORE_INPUTS + tuple(k for k in OPTIONAL_INPUTS if k in features)


def validate_predict_input(raw: dict, inputs: tuple[str, ...] = CORE_INPUTS) -> dict:
    """Every problem is reported together; nothing is imputed."""
    errors, vals = [], {}
    for k in inputs:
        v = raw.get(k)
        if v is None:
            errors.append(_err(k, "missing", f"{k} is required."))
        elif (f := _finite(v)) is None:
            errors.append(_err(k, "invalid_type", f"{k} must be a finite number."))
        else:
            vals[k] = f
    c = RELIABILITY_CONFIG
    if "spo2" in vals and not (c.spo2_min <= vals["spo2"] <= c.spo2_max):
        errors.append(_err("spo2", "out_of_range", f"OUTSIDE SUPPORTED RANGE: spo2 must be between {c.spo2_min:g} and {c.spo2_max:g}."))
    if "pi" in vals and not (0 < vals["pi"] <= c.pi_max):
        errors.append(_err("pi", "out_of_range", f"pi must be greater than 0 and at most {c.pi_max:g}."))
    if "ita" in vals and not (c.ita_min <= vals["ita"] <= c.ita_max):
        errors.append(_err("ita", "out_of_range", f"ita must be between {c.ita_min:g} and {c.ita_max:g}."))
    which = raw.get("model") or "both"
    if which not in ("ridge", "lightgbm", "both"):
        errors.append(_err("model", "invalid_choice", "model must be one of: ridge, lightgbm, both."))
    if errors:
        raise InputValidationError(errors)
    return {**vals, "model": which}


def predict_one(raw: dict, paths: Paths | None = None) -> dict:
    paths = paths or get_paths()
    metrics = read_metrics(paths)                      # also proves the models were trained
    if not _is_valid_run(metrics):
        raise ModelError("model_not_trained", LEGACY_NOTE)
    FEATURES = metrics["features"]
    inputs = required_inputs(FEATURES)
    x = validate_predict_input(raw, inputs)
    feats = engineer_features({k: x[k] for k in inputs})
    missing = [f for f in FEATURES if feats.get(f) is None]
    if missing:                                         # cannot happen after validation; guards the contract
        raise InputValidationError([_err("features", "missing_features", f"Could not build feature(s): {', '.join(missing)}.")])
    row = pd.DataFrame([{f: feats[f] for f in FEATURES}])[FEATURES]

    preds = {}
    for name, fname in (("ridge", RIDGE_FILE), ("lightgbm", LGBM_FILE)):
        if x["model"] in (name, "both"):
            f = paths.models / fname
            if not f.exists():
                raise ModelError("model_not_trained", f"The {name} model file is missing. Retrain the models.")
            with readable(f"{name} model"):
                art = load_artifact(f)                    # local, self-produced artifacts only
                preds[name] = float(art["model"].predict(row[art["features"]])[0])

    warnings = []
    for k in inputs:
        lo, hi = metrics["feature_ranges"][k]
        if not (lo <= x[k] <= hi):
            warnings.append(f"OUTSIDE TRAINING RANGE: {k} = {x[k]:g} (training range {lo:.3g}–{hi:.3g}). The estimate may not generalize.")
    return {"predictions": preds, "features": {f: float(feats[f]) for f in FEATURES}, "required_inputs": list(inputs), "warnings": warnings,
            "data_provenance": metrics["data_provenance"], "disclaimer": DISCLAIMER}


def health_brief(paths: Paths | None = None) -> dict:
    """Small summary for /api/health."""
    paths = paths or get_paths()
    trained = all(_artifacts(paths).values())
    if trained:
        try:
            trained = _is_valid_run(read_metrics(paths))
        except ModelError:
            trained = False
    return {"trained": trained, "note": "Ridge and LightGBM trained (see /api/model/status)." if trained else "No models trained yet."}
