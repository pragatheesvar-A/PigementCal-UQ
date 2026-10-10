"""Phase 7 tests. Everything runs in temporary directories: real data/processed, models/ and results/
are never read or written here."""

import json
import shutil

import joblib
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from dataclasses import replace

from app.config import MODEL_CONFIG
from app.main import app
from app.ml import service, train
from app.ml.data import (
    CORE_FEATURES, FEATURES, GROUP_COL, TARGET_COL, ModelError, assert_no_target_leakage, dataset_provenance, load_splits,
)
from app.ml.metrics import regression_metrics, subgroup_errors
from app.ml.paths import Paths, set_paths
from app.pipeline.features import engineer_features
from app.services.validation import InputValidationError


# ------------------------------------------------------------------ helpers
def make_paths(root) -> Paths:
    return Paths(processed=root / "processed", raw=root / "raw", models=root / "models", results=root / "results")


def make_processed(paths: Paths, seed=0, n_train=30, n_cal=10, n_test=12, rows=5, motion_constant=False, write_raw=True, verified=True):
    """Synthetic processed splits with real structure (SaO2 depends on d and ITA) and all ITA x PI cells present."""
    rng = np.random.default_rng(seed)
    paths.processed.mkdir(parents=True, exist_ok=True)
    manifest, k = {}, 0
    for split, n in (("train", n_train), ("calibration", n_cal), ("test", n_test)):
        recs, ids = [], []
        for _ in range(n):
            pid = f"S{k:03d}"; k += 1; ids.append(pid)
            ita = rng.uniform(-30, 65)
            for _ in range(rows):
                spo2 = rng.uniform(88, 100)
                pi = float(np.exp(rng.uniform(np.log(0.3), np.log(5))))
                sqi = rng.uniform(0.5, 1.0)
                f = engineer_features({"spo2": spo2, "pi": pi, "ita": ita, "sqi": sqi, "motion": 0.0 if motion_constant else rng.uniform(0, 1)})
                f[GROUP_COL] = pid
                f[TARGET_COL] = spo2 - 0.12 * f["d"] * (1 if ita < 10 else 0) + rng.normal(0, 0.3)
                recs.append(f)
        pd.DataFrame(recs).to_csv(paths.processed / f"{split}.csv", index=False)
        manifest[f"{split}_participants"] = ids
    manifest["random_seed"] = seed
    (paths.processed / "split_manifest.json").write_text(json.dumps(manifest))
    if write_raw:       # a loaded research dataset that the processed splits were derived from
        ids = sum((manifest[f"{k}_participants"] for k in ("train", "calibration", "test")), [])
        paths.raw.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({GROUP_COL: ids}).to_csv(paths.raw / "dataset.csv", index=False)
        (paths.raw / "dataset_meta.json").write_text(json.dumps({"source_filename": "study.csv", "sha256": "abc"}))
        if verified:   # the record Data Collection writes when it builds the research dataset from attested uploads
            (paths.processed / "research_data_quality.json").write_text(json.dumps({
                "valid_records": len(ids), "participants": len(ids), "sessions": len(ids), "sources": [{"id": "U001", "kind": "combined", "filename": "study.csv", "staged_rows": len(ids)}],
                "model_training": {"blocked": False, "reasons": ["Model training is never started automatically."]}}))


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    paths = make_paths(tmp_path_factory.mktemp("phase7"))
    make_processed(paths)
    result = train.train_models(paths)
    return paths, result


@pytest.fixture
def api(env):
    """TestClient whose endpoints use the temporary trained environment."""
    set_paths(env[0])
    yield TestClient(app)
    set_paths(None)


@pytest.fixture
def untrained(tmp_path):
    paths = make_paths(tmp_path)
    make_processed(paths)
    set_paths(paths)
    yield paths, TestClient(app)
    set_paths(None)


# ------------------------------------------------------------------ training + artifacts
def test_training_produces_all_artifacts(env):
    paths, r = env
    assert (paths.models / "ridge_model.joblib").exists() and (paths.models / "lightgbm_model.joblib").exists()
    assert (paths.results / "model_metrics.json").exists() and (paths.results / "test_predictions.csv").exists()
    assert r["status"] == "trained" and set(r["models"]) == {"ridge", "lightgbm"}
    saved = json.loads((paths.results / "model_metrics.json").read_text())
    assert saved["models"]["ridge"]["metrics"]["mae"] == pytest.approx(r["models"]["ridge"]["metrics"]["mae"])


def test_saved_models_load_and_predict(env):
    paths, _ = env
    for f in ("ridge_model.joblib", "lightgbm_model.joblib"):
        art = joblib.load(paths.models / f)
        X = pd.DataFrame([{c: 1.0 for c in FEATURES}, {c: 2.0 for c in FEATURES}])[art["features"]]
        assert art["model"].predict(X).shape == (2,)


def test_metrics_report_counts_and_all_metric_fields(env):
    _, r = env
    for name in ("ridge", "lightgbm"):
        m = r["models"][name]["metrics"]
        assert m["n_obs"] == 60 and m["n_participants"] == 12
        assert all(m[k] is not None for k in ("mae", "rmse", "bias", "r2"))
        assert m["rmse"] >= m["mae"] >= 0
    assert r["reference"]["metrics"]["n_obs"] == 60


def test_hyperparameters_tuned_inside_train_only(env):
    _, r = env
    for name in ("ridge", "lightgbm"):
        assert "GroupKFold" in r["models"][name]["cv_scheme"] and "train split only" in r["models"][name]["cv_scheme"]
    assert "NOT used" in r["dataset"]["calibration_use"]


def test_training_is_reproducible(env):
    paths, r = env
    again = train.train_models(paths)
    for name in ("ridge", "lightgbm"):
        assert again["models"][name]["metrics"] == r["models"][name]["metrics"]
        assert again["models"][name]["best_params"] == r["models"][name]["best_params"]


# ------------------------------------------------------------------ leakage and data guards
def test_features_exclude_target_and_participant():
    assert TARGET_COL not in FEATURES and GROUP_COL not in FEATURES and not any("sao2" in f for f in FEATURES)
    assert FEATURES == ["spo2", "d", "pi", "log_pi", "ita", "ita_x_d", "log_pi_x_d", "ita_x_log_pi", "sqi", "motion"]


@pytest.mark.parametrize("bad", ["sao2_target", "participant_id", "sao2_copy", "SaO2_lag"])
def test_leakage_guard_rejects(bad):
    with pytest.raises(ModelError) as e:
        assert_no_target_leakage(FEATURES + [bad])
    assert e.value.code == "target_leakage"


def test_fitted_models_only_saw_the_declared_features(env):
    paths, _ = env
    ridge = joblib.load(paths.models / "ridge_model.joblib")["model"]
    lgbm = joblib.load(paths.models / "lightgbm_model.joblib")["model"]
    assert list(ridge.feature_names_in_) == FEATURES and list(lgbm.feature_names_in_) == FEATURES


def test_extra_columns_in_csv_are_not_predictors(tmp_path):
    paths = make_paths(tmp_path)
    make_processed(paths)
    df = pd.read_csv(paths.processed / "train.csv")
    df["sao2_copy"] = df[TARGET_COL]            # a would-be leak sitting in the file
    df.to_csv(paths.processed / "train.csv", index=False)
    r = train.train_models(paths)
    assert r["features"] == FEATURES
    assert list(joblib.load(paths.models / "ridge_model.joblib")["model"].feature_names_in_) == FEATURES


def test_participant_overlap_between_splits_is_blocked(tmp_path):
    paths = make_paths(tmp_path)
    make_processed(paths)
    train_df = pd.read_csv(paths.processed / "train.csv")
    test_df = pd.read_csv(paths.processed / "test.csv")
    test_df.loc[0, GROUP_COL] = train_df.loc[0, GROUP_COL]        # one shared participant
    test_df.to_csv(paths.processed / "test.csv", index=False)
    with pytest.raises(ModelError) as e:
        train.train_models(paths)
    assert e.value.code == "participant_leakage" and "LEAKAGE" in e.value.message
    assert not (paths.models / "ridge_model.joblib").exists()      # nothing saved after a failure


@pytest.mark.parametrize("col", ["spo2", "pi", "ita_x_d", "log_pi", TARGET_COL])
def test_missing_required_column_blocks_training(tmp_path, col):
    paths = make_paths(tmp_path)
    make_processed(paths)
    pd.read_csv(paths.processed / "train.csv").drop(columns=[col]).to_csv(paths.processed / "train.csv", index=False)
    with pytest.raises(ModelError) as e:
        train.train_models(paths)
    assert e.value.code == "missing_columns" and col in e.value.message


def test_optional_predictors_may_be_absent_or_constant_and_are_excluded_openly(tmp_path):
    paths = make_paths(tmp_path)
    make_processed(paths, motion_constant=True)                          # motion carries no information
    for split in ("train", "calibration", "test"):                       # sqi not present at all
        pd.read_csv(paths.processed / f"{split}.csv").drop(columns=["sqi"]).to_csv(paths.processed / f"{split}.csv", index=False)
    r = train.train_models(paths)
    assert r["features"] == CORE_FEATURES
    assert "not present" in r["excluded_features"]["sqi"] and "constant" in r["excluded_features"]["motion"]
    out = service.predict_one({"spo2": 94, "pi": 1.5, "ita": 30}, paths)             # only the inputs the models use
    assert out["required_inputs"] == ["spo2", "pi", "ita"]
    with pytest.raises(InputValidationError):
        service.predict_one({"spo2": 94, "pi": 1.5}, paths)


def test_missing_participant_ids_cannot_be_verified_and_block_training(tmp_path):
    paths = make_paths(tmp_path)
    make_processed(paths)
    pd.read_csv(paths.processed / "train.csv").drop(columns=[GROUP_COL]).to_csv(paths.processed / "train.csv", index=False)
    with pytest.raises(ModelError) as e:
        train.train_models(paths)
    assert e.value.code == "data_mismatch"


def test_missing_values_are_reported_not_imputed(tmp_path):
    paths = make_paths(tmp_path)
    make_processed(paths)
    df = pd.read_csv(paths.processed / "test.csv")
    df.loc[3, "pi"] = np.nan
    df.to_csv(paths.processed / "test.csv", index=False)
    with pytest.raises(ModelError) as e:
        load_splits(paths)
    assert e.value.code == "missing_values" and "pi" in e.value.message


def test_no_dataset_means_no_training(tmp_path):
    with pytest.raises(ModelError) as e:
        train.train_models(make_paths(tmp_path))
    assert e.value.code == "no_dataset" and "Upload a dataset" in e.value.message


def test_dataset_loaded_but_not_processed(tmp_path):
    paths = make_paths(tmp_path)
    paths.raw.mkdir()
    pd.DataFrame({GROUP_COL: ["a", "b"]}).to_csv(paths.raw / "dataset.csv", index=False)
    paths.processed.mkdir(parents=True)
    (paths.processed / "research_data_quality.json").write_text(json.dumps({"valid_records": 2, "participants": 2, "sessions": 2, "sources": [{"id": "U001"}],
                                                                           "model_training": {"blocked": False, "reasons": []}}))
    with pytest.raises(ModelError) as e:
        train.train_models(paths)
    assert e.value.code == "no_processed_data"


def test_processed_data_that_the_loaded_dataset_cannot_account_for_is_blocked(tmp_path):
    paths = make_paths(tmp_path)
    make_processed(paths)
    pd.DataFrame({GROUP_COL: ["only_one"]}).to_csv(paths.raw / "dataset.csv", index=False)
    with pytest.raises(ModelError) as e:
        train.train_models(paths)
    assert e.value.code == "data_mismatch"


def test_test_and_calibration_never_influence_the_models(env, tmp_path):
    """Corrupt the test and calibration targets completely: the fitted models must not change."""
    paths_a, _ = env
    paths_b = make_paths(tmp_path)
    shutil.copytree(paths_a.processed, paths_b.processed)
    shutil.copytree(paths_a.raw, paths_b.raw)
    rng = np.random.default_rng(1)
    for split in ("test", "calibration"):
        df = pd.read_csv(paths_b.processed / f"{split}.csv")
        df[TARGET_COL] = rng.permutation(df[TARGET_COL].to_numpy()) + 5.0
        df.to_csv(paths_b.processed / f"{split}.csv", index=False)
    r_b = train.train_models(paths_b)
    X = pd.read_csv(paths_a.processed / "train.csv")[FEATURES].head(25)
    for f in ("ridge_model.joblib", "lightgbm_model.joblib"):
        a = joblib.load(paths_a.models / f)["model"].predict(X)
        b = joblib.load(paths_b.models / f)["model"].predict(X)
        assert np.allclose(a, b)
    # ...while the test metrics DO reflect the corrupted test targets (so they are really being evaluated on it)
    assert r_b["models"]["ridge"]["metrics"]["mae"] > 3


# ------------------------------------------------------------------ metrics
def test_regression_metrics_known_values():
    y = [10.0, 20.0, 30.0, 40.0]
    p = [11.0, 19.0, 33.0, 38.0]            # errors +1, -1, +3, -2
    m = regression_metrics(y, p, ["a", "a", "b", "c"])
    assert m["mae"] == pytest.approx(1.75)
    assert m["rmse"] == pytest.approx(np.sqrt((1 + 1 + 9 + 4) / 4))
    assert m["bias"] == pytest.approx(0.25)
    assert m["r2"] == pytest.approx(1 - 15 / 500)
    assert m["n_obs"] == 4 and m["n_participants"] == 3


def test_regression_metrics_perfect_and_edge_cases():
    m = regression_metrics([1, 2, 3], [1, 2, 3])
    assert m["mae"] == 0 and m["rmse"] == 0 and m["bias"] == 0 and m["r2"] == pytest.approx(1.0)
    assert regression_metrics([5, 5, 5], [4, 5, 6])["r2"] is None          # constant truth: R2 undefined
    empty = regression_metrics([], [])
    assert empty["n_obs"] == 0 and empty["mae"] is None
    with pytest.raises(ValueError):
        regression_metrics([1, 2], [1])


def test_error_sign_convention(env):
    paths, _ = env
    p = pd.read_csv(paths.results / "test_predictions.csv")
    assert list(p.columns) == ["participant_id", "session_id", "spo2", "sao2", "ridge_prediction", "lightgbm_prediction", "ridge_error", "lightgbm_error"]
    assert np.allclose(p.ridge_error, p.ridge_prediction - p.sao2) and np.allclose(p.lightgbm_error, p.lightgbm_prediction - p.sao2)
    assert len(p) == 60


def test_best_model_is_the_lower_test_mae(env):
    _, r = env
    maes = {k: r["models"][k]["metrics"]["mae"] for k in ("ridge", "lightgbm")}
    assert r["best_model"]["name"] == min(maes, key=maes.get) and r["best_model"]["criterion"] == "lowest test-set MAE"
    assert "not a claim of clinical superiority" in r["best_model"]["note"]


# ------------------------------------------------------------------ subgroup errors
def _frame(rows):
    return pd.DataFrame(rows, columns=["participant_id", "ita", "pi", "sao2", "m"])


def test_subgroup_errors_known_values():
    f = _frame([
        ("a", 60, 2.0, 95.0, 96.0),    # Light, Normal, err +1
        ("b", 60, 0.5, 95.0, 93.0),    # Light, Low,    err -2
        ("c", 25, 2.0, 95.0, 95.5),    # Medium, Normal err +0.5
        ("c", 25, 2.0, 95.0, 94.0),    # Medium, Normal err -1
        ("d", 5, 0.5, 90.0, 92.0),     # Dark, Low      err +2
    ])
    s = subgroup_errors(f, {"m": "m"}, cfg=replace(MODEL_CONFIG, min_subgroup_participants=1))
    ita = {c["group"]: c for c in s["ita"]}
    assert ita["Light"]["models"]["m"]["mae"] == pytest.approx(1.5) and ita["Light"]["n_participants"] == 2
    assert ita["Medium"]["models"]["m"]["mae"] == pytest.approx(0.75) and ita["Medium"]["n_obs"] == 2 and ita["Medium"]["n_participants"] == 1
    assert ita["Dark"]["models"]["m"]["mae"] == pytest.approx(2.0)
    pi = {c["group"]: c for c in s["pi"]}
    assert pi["Low"]["models"]["m"]["mae"] == pytest.approx(2.0) and pi["Low"]["n_obs"] == 2
    assert pi["Normal"]["models"]["m"]["mae"] == pytest.approx((1 + 0.5 + 1) / 3)
    cells = {(c["ita_group"], c["pi_group"]): c for c in s["ita_x_pi"]}
    assert len(cells) == 6 and cells[("Light", "Low")]["models"]["m"]["bias"] == pytest.approx(-2.0)
    assert cells[("Medium", "Normal")]["models"]["m"]["mae"] == pytest.approx(0.75)


def test_empty_subgroups_are_listed_not_invented():
    s = subgroup_errors(_frame([("a", 25, 2.0, 95.0, 95.5)]), {"m": "m"})
    cells = {(c["ita_group"], c["pi_group"]): c for c in s["ita_x_pi"]}
    assert cells[("Dark", "Low")]["n_obs"] == 0 and cells[("Dark", "Low")]["models"]["m"]["mae"] is None
    assert cells[("Medium", "Normal")]["sufficient"] is False         # 1 participant < minimum


def test_subgroup_boundaries_follow_shared_thresholds():
    f = _frame([("a", 41.0, 1.0, 95.0, 95.0), ("b", 41.1, 0.99, 95.0, 95.0), ("c", 10.0, 1.0, 95.0, 95.0), ("d", 10.1, 1.0, 95.0, 95.0)])
    s = subgroup_errors(f, {"m": "m"})
    ita = {c["group"]: c["n_obs"] for c in s["ita"]}
    assert ita == {"Light": 1, "Medium": 2, "Dark": 1}                # 41 -> Medium, 41.1 -> Light, 10 -> Dark
    assert {c["group"]: c["n_obs"] for c in s["pi"]} == {"Low": 1, "Normal": 3}


def test_trained_subgroups_cover_every_cell(env):
    _, r = env
    assert [c["group"] for c in r["subgroups"]["ita"]] == ["Light", "Medium", "Dark"]
    assert len(r["subgroups"]["ita_x_pi"]) == 6
    assert sum(c["n_obs"] for c in r["subgroups"]["ita"]) == 60
    assert "reported separately" in r["subgroups"]["note"]


# ------------------------------------------------------------------ provenance (is a dataset loaded?)
def test_provenance_none_without_a_dataset_and_nothing_is_generated(tmp_path):
    paths = make_paths(tmp_path)
    make_processed(paths, write_raw=False)
    p = dataset_provenance(paths)
    assert p["kind"] == "NONE" and p["label"] == "NO RESEARCH DATASET LOADED" and "nothing is generated or simulated" in p["reason"]


def test_provenance_loaded_only_when_processed_data_is_accounted_for(tmp_path):
    paths = make_paths(tmp_path)
    make_processed(paths)
    p = dataset_provenance(paths)
    assert p["kind"] == "LOADED" and p["file"] == "study.csv" and "not clinical evidence" in p["label"]
    pd.DataFrame({GROUP_COL: ["X1", "X2"]}).to_csv(paths.raw / "dataset.csv", index=False)
    assert dataset_provenance(paths)["kind"] == "MISMATCH"


def test_a_dataset_not_built_from_attested_uploads_is_demo_only_and_cannot_be_trained_on(tmp_path):
    paths = make_paths(tmp_path)
    make_processed(paths, verified=False)                      # a dataset file dropped in by hand
    p = dataset_provenance(paths)
    assert p["kind"] == "UNVERIFIED" and p["label"] == "UNVERIFIED DATA — NOT A RESEARCH RESULT"
    with pytest.raises(ModelError) as e:
        train.train_models(paths)
    assert e.value.code == "unverified_data" and "UNVERIFIED DATA — NOT A RESEARCH RESULT" in e.value.message
    assert not paths.models.exists() and not paths.results.exists()
    s = service.status(paths)
    assert s["current_data_provenance"]["kind"] == "UNVERIFIED" and s["trained"] is False


def test_an_empty_verification_record_does_not_count(tmp_path):
    paths = make_paths(tmp_path)
    make_processed(paths)
    (paths.processed / "research_data_quality.json").write_text(json.dumps({"valid_records": 0, "sources": [], "model_training": {"blocked": True, "reasons": []}}))
    assert dataset_provenance(paths)["kind"] == "UNVERIFIED"


def test_status_reports_the_real_data_counts_and_blockers(tmp_path):
    paths = make_paths(tmp_path)
    s0 = service.status(paths)
    assert s0["research_data"] == {"records": 0, "participants": 0, "sessions": 0, "blocked": True,
                                   "reasons": ["There are no valid real records.", "Model training is never started automatically."]}
    make_processed(paths)
    s1 = service.status(paths)
    assert s1["research_data"]["participants"] == 52 and s1["research_data"]["blocked"] is False


def test_trained_results_carry_loaded_provenance(env):
    _, r = env
    assert r["data_provenance"]["kind"] == "LOADED" and "DEMO" not in json.dumps(r)


def test_models_from_an_earlier_non_dataset_run_are_ignored(tmp_path):
    paths = make_paths(tmp_path)
    make_processed(paths)
    r = train.train_models(paths)
    assert service.status(paths)["trained"] is True
    r["data_provenance"] = {"kind": "DEMO", "label": "old"}               # what a legacy synthetic run left on disk
    (paths.results / "model_metrics.json").write_text(json.dumps(r))
    s = service.status(paths)
    assert s["trained"] is False and "ignored" in s["stale_reason"]
    assert service.health_brief(paths)["trained"] is False
    with pytest.raises(ModelError) as e:
        service.predict_one(GOOD, paths)
    assert e.value.code == "model_not_trained"


# ------------------------------------------------------------------ LightGBM availability
def test_missing_lightgbm_stops_with_install_message_and_saves_nothing(tmp_path, monkeypatch):
    paths = make_paths(tmp_path)
    make_processed(paths)
    monkeypatch.setattr(train, "lightgbm_available", lambda: False)
    with pytest.raises(ModelError) as e:
        train.train_models(paths)
    assert e.value.code == "lightgbm_missing" and "pip install lightgbm" in e.value.message
    assert not paths.models.exists() and not paths.results.exists()    # no silent fallback to Ridge-only


# ------------------------------------------------------------------ service: predict / status
GOOD = {"spo2": 94, "pi": 1.5, "ita": 30, "sqi": 0.8, "motion": 0.5}


def test_predict_shape_and_features_use_central_pipeline(env):
    paths, _ = env
    r = service.predict_one(GOOD, paths)
    assert set(r["predictions"]) == {"ridge", "lightgbm"} and all(isinstance(v, float) for v in r["predictions"].values())
    assert r["features"] == pytest.approx({k: float(v) for k, v in engineer_features(GOOD).items() if k in FEATURES})
    assert list(r["features"]) == FEATURES
    assert service.predict_one({**GOOD, "model": "ridge"}, paths)["predictions"].keys() == {"ridge"}


@pytest.mark.parametrize("missing", ["spo2", "pi", "ita", "sqi", "motion"])
def test_predict_missing_feature(env, missing):
    paths, _ = env
    body = {k: v for k, v in GOOD.items() if k != missing}
    with pytest.raises(InputValidationError) as e:
        service.predict_one(body, paths)
    assert [x["field"] for x in e.value.errors] == [missing] and e.value.errors[0]["code"] == "missing"


@pytest.mark.parametrize("field,bad", [("spo2", 105), ("spo2", "x"), ("pi", 0), ("pi", -1), ("ita", 500), ("sqi", float("nan")), ("motion", True)])
def test_predict_invalid_values(env, field, bad):
    paths, _ = env
    with pytest.raises(InputValidationError):
        service.predict_one({**GOOD, field: bad}, paths)


def test_predict_warns_outside_training_range(env):
    paths, _ = env
    r = service.predict_one({**GOOD, "ita": 80}, paths)
    assert any("OUTSIDE TRAINING RANGE" in w and "ita" in w for w in r["warnings"])
    assert service.predict_one(GOOD, paths)["warnings"] == []


def test_predict_before_training_is_a_clear_error(tmp_path):
    paths = make_paths(tmp_path)
    make_processed(paths)
    with pytest.raises(ModelError) as e:
        service.predict_one(GOOD, paths)
    assert e.value.code == "model_not_trained"


def test_status_lifecycle_and_staleness(tmp_path):
    paths = make_paths(tmp_path)
    make_processed(paths)
    s0 = service.status(paths)
    assert s0["trained"] is False and s0["processed_data_available"] is True and s0["lightgbm_available"] is True
    train.train_models(paths)
    s1 = service.status(paths)
    assert s1["trained"] is True and s1["stale"] is False and s1["data_provenance"]["kind"] == "LOADED"
    df = pd.read_csv(paths.processed / "train.csv"); df.loc[0, "spo2"] += 0.5; df.to_csv(paths.processed / "train.csv", index=False)
    s2 = service.status(paths)
    assert s2["stale"] is True and "Retrain" in s2["stale_reason"]


def test_read_predictions_paging(env):
    paths, _ = env
    page = service.read_predictions(10, 5, paths)
    assert page["total"] == 60 and len(page["rows"]) == 10 and page["offset"] == 5


# ------------------------------------------------------------------ API
def test_api_status_metrics_predictions(api):
    s = api.get("/api/model/status").json()
    assert s["trained"] is True and s["data_provenance"]["kind"] == "LOADED"
    m = api.get("/api/model/metrics").json()
    assert set(m["models"]) == {"ridge", "lightgbm"} and m["best_model"]["name"] in ("ridge", "lightgbm")
    p = api.get("/api/model/predictions", params={"limit": 5}).json()
    assert p["total"] == 60 and len(p["rows"]) == 5
    assert api.get("/api/model/predictions", params={"limit": 0}).status_code == 422


def test_api_predict(api):
    r = api.post("/api/model/predict", json=GOOD)
    assert r.status_code == 200 and set(r.json()["predictions"]) == {"ridge", "lightgbm"}
    assert "not a measurement or a diagnosis" in r.json()["disclaimer"]
    bad = api.post("/api/model/predict", json={"spo2": 94})
    assert bad.status_code == 422 and {e["field"] for e in bad.json()["errors"]} == {"pi", "ita", "sqi", "motion"}
    assert api.post("/api/model/predict", json={**GOOD, "model": "svm"}).status_code == 422
    assert api.post("/api/model/predict", json={**GOOD, "spo2": "abc"}).status_code == 422


def test_api_train_then_everything_available(untrained):
    paths, client = untrained
    assert client.get("/api/model/status").json()["trained"] is False
    assert client.get("/api/model/metrics").status_code == 200 and client.get("/api/model/metrics").json()["available"] is False
    assert client.post("/api/model/predict", json=GOOD).json()["errors"][0]["code"] == "model_not_trained"
    r = client.post("/api/model/train")
    assert r.status_code == 200 and r.json()["status"] == "trained"
    assert {"ridge", "lightgbm"} == set(r.json()["models"])
    assert client.get("/api/model/status").json()["trained"] is True
    assert client.post("/api/model/predict", json=GOOD).status_code == 200
    assert (paths.results / "model_metrics.json").exists()


def test_api_train_without_data_is_human_readable(tmp_path):
    set_paths(make_paths(tmp_path))
    try:
        r = TestClient(app).post("/api/model/train")
    finally:
        set_paths(None)
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "no_dataset"
    assert "Traceback" not in r.text


def test_health_reports_model_state(api):
    assert api.get("/api/health").json()["model"]["trained"] is True


def test_earlier_phase_endpoints_still_work(api):
    assert api.post("/api/perfusion/direct", json={"pi": 0.5}).status_code == 200
    assert api.post("/api/reliability/predict", json={"spo2": 94, "pi": 2, "ita": 25, "signal_quality": "GOOD", "motion": "LOW", "device": "ESP32 + MAX30102"}).status_code == 200


# ====================================================================== Phase 13: gate, leakage, insufficient data
def test_small_subgroups_report_insufficient_data_instead_of_a_number():
    s = subgroup_errors(_frame([("a", 60, 2.0, 95.0, 96.0), ("b", 25, 2.0, 95.0, 94.0)]), {"m": "m"})      # 1 participant per group, minimum is 5
    for g in s["ita"] + s["pi"] + s["ita_x_pi"]:
        assert g["status"] == "INSUFFICIENT DATA" and g["sufficient"] is False
        assert g["models"]["m"] == {"mae": None, "bias": None}
    assert s["ita"][0]["n_obs"] == 1                                # counts are still shown


def test_training_is_refused_when_the_dataset_is_not_ready(tmp_path):
    import json as _json
    from app.ml.train import NOT_READY_MESSAGE
    from tests.test_conformal import build_env
    paths = build_env(tmp_path)                                      # test-only synthetic folder
    q = _json.loads((paths.processed / "research_data_quality.json").read_text())
    q["readiness"] = {"status": "NOT READY", "reasons": ["forced for this test"]}
    (paths.processed / "research_data_quality.json").write_text(_json.dumps(q))
    with pytest.raises(ModelError) as e:
        train.train_models(paths)
    assert e.value.code == "training_blocked" and e.value.message.startswith(NOT_READY_MESSAGE) and "forced for this test" in e.value.message
    assert not (paths.models / "ridge_model.joblib").exists() and not (paths.results / "model_metrics.json").exists()


def test_dataset_status_endpoint_reports_the_gate(tmp_path):
    from tests.test_conformal import make_paths
    set_paths(make_paths(tmp_path))
    j = TestClient(app).get("/api/dataset/status").json()
    assert j["readiness"]["status"] == "NOT READY" and j["training_available"] is False and j["training_message"].startswith("Training unavailable")
    r = TestClient(app).post("/api/model/train")
    assert r.status_code == 422 and r.json()["errors"][0]["message"].startswith("Training unavailable")


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """A dataset built through Data Collection (test-only synthetic folder), then trained."""
    from tests.test_conformal import build_env
    paths = build_env(tmp_path_factory.mktemp("phase13"))
    return paths, train.train_models(paths)


def test_trained_run_records_versions_counts_session_ids_and_never_uses_ids_as_features(built):
    paths, r = built
    assert r["versions"]["feature_version"] and r["versions"]["model_version"] and r["versions"]["dataset_version"]
    assert r["counts"]["test"]["participants"] == r["dataset"]["splits"]["test"]["participants"]
    assert {"train", "calibration", "test"} == set(r["counts"])
    p = pd.read_csv(paths.results / "test_predictions.csv")
    assert p["session_id"].astype(str).str.len().gt(0).all()
    assert not any(("sao2" in f or "participant" in f or "session" in f) for f in r["features"])
    assert r["features"][:8] == ["spo2", "d", "pi", "log_pi", "ita", "ita_x_d", "log_pi_x_d", "ita_x_log_pi"]
    assert "calibration" not in str(r["models"]["ridge"]["cv_scheme"])


def test_status_exposes_readiness_and_research_results_flag(built, tmp_path):
    paths, _ = built
    st = service.status(paths)
    # trained on attested uploads, but NO provenance record: readiness is fine, the research-result flag stays closed
    assert st["readiness"]["status"] == "READY FOR TRAINING" and st["research_results"] is False
    assert st["research_status"]["state"] == "UNVERIFIED_DATA"
    from tests.test_conformal import make_paths
    empty = service.status(make_paths(tmp_path))
    assert empty["readiness"]["status"] == "NOT READY" and empty["research_results"] is False
