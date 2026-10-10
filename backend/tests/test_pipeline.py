"""Dataset processing tests (validation, cleaning, features, participant-level splits).
The data is entered through the Data Collection page; here a loaded dataset is written directly in its canonical form.
Everything runs in temporary directories (never real data)."""

import json
import os
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.ml.paths import Paths, set_paths
from app.pipeline import pipeline as pl
from app.pipeline.features import engineer_features
from app.pipeline.schema import PipelineError
from app.services.pigmentation import compute_ita


def make_paths(root) -> Paths:
    return Paths(processed=root / "processed", raw=root / "raw", models=root / "models", results=root / "results")


def research_df(n_participants=30, rows=6, seed=0, **overrides) -> pd.DataFrame:
    """Canonical research records (participant_id, spo2, sao2, pi, ita, device_id)."""
    rng = np.random.default_rng(seed)
    recs = []
    for p in range(n_participants):
        L, b = rng.uniform(35, 75), rng.uniform(8, 30)
        for _ in range(rows):
            spo2 = rng.uniform(88, 100)
            recs.append({"participant_id": f"P{p:03d}", "session_id": f"P{p:03d}_S01", "spo2": spo2,
                         "sao2": float(np.clip(spo2 + rng.normal(0, 1), 50, 100)),
                         "pi": float(np.exp(rng.uniform(np.log(0.3), np.log(5)))), "ita": compute_ita(L + rng.normal(0, 0.5), b),
                         "device_id": "OximeterX"})
    df = pd.DataFrame(recs)
    for k, v in overrides.items():
        df[k] = v
    return df


def load(paths: Paths, df: pd.DataFrame) -> None:
    """What building the research dataset leaves for the processing step."""
    paths.raw.mkdir(parents=True, exist_ok=True)
    df.to_csv(paths.raw / "dataset.csv", index=False)
    (paths.raw / "dataset_meta.json").write_text(json.dumps({"source_filename": "research_dataset.csv", "sha256": "x"}))


@pytest.fixture
def paths(tmp_path):
    return make_paths(tmp_path)


# ---------------------------------------------------------------- the old single-file upload is gone
def test_there_is_a_single_data_entry_point():
    assert not hasattr(pl, "ingest_csv") and not hasattr(pl, "generate_demo_dataset")
    c = TestClient(app)
    assert c.post("/api/dataset/upload", content=b"x").status_code in (404, 405)


def test_processing_without_a_dataset_points_to_data_collection(paths):
    with pytest.raises(PipelineError) as e:
        pl.process_dataset(paths)
    assert e.value.code == "no_dataset" and "Data Collection" in e.value.message


# ---------------------------------------------------------------- cleaning: every dropped row is counted
def test_dropped_rows_are_reported_by_reason_and_never_silent(paths):
    df = research_df(n_participants=20, rows=5)
    df.loc[0, "spo2"] = np.nan
    df.loc[1, "sao2"] = 140.0
    df.loc[2, "pi"] = -1.0
    df.loc[3, "participant_id"] = np.nan
    df = pd.concat([df, df.iloc[[10]]], ignore_index=True)
    load(paths, df)
    q = pl.process_dataset(paths)
    d = q["dropped_by_reason"]
    assert d["missing_participant_id"] == 1 and d["missing_or_invalid_spo2"] == 1
    assert d["spo2_or_sao2_out_of_range"] == 1 and d["pi_not_positive_or_above_max"] == 1 and d["exact_duplicate_row"] == 1
    assert q["rows_in"] == 101 and q["rows_kept"] + q["rows_dropped"] == q["rows_in"] and q["rows_dropped"] == 5
    assert sum(s["rows"] for s in q["splits"].values()) == q["rows_kept"]
    assert json.loads((paths.processed / "data_quality.json").read_text())["rows_dropped"] == 5


def test_too_few_participants(paths):
    load(paths, research_df(n_participants=6))
    with pytest.raises(PipelineError) as e:
        pl.process_dataset(paths)
    assert e.value.code == "too_few_participants"


# ---------------------------------------------------------------- splits
def test_split_is_participant_disjoint_stratified_and_close_to_60_20_20(paths):
    load(paths, research_df(n_participants=60))
    q = pl.process_dataset(paths)
    m = json.loads((paths.processed / "split_manifest.json").read_text())
    tr, ca, te = (set(m[f"{k}_participants"]) for k in ("train", "calibration", "test"))
    assert not (tr & ca) and not (tr & te) and not (ca & te) and len(tr | ca | te) == 60
    assert len(tr) == pytest.approx(36, abs=3) and len(ca) == pytest.approx(12, abs=3) and len(te) == pytest.approx(12, abs=3)
    assert "ITA" in m["stratified_by"]
    ita = pd.read_csv(paths.raw / "dataset.csv").groupby("participant_id")["ita"].median()
    t1, t2 = ita.quantile([1 / 3, 2 / 3])
    for ids in (ca, te):
        v = ita[list(ids)]
        assert (v <= t1).any() and (v >= t2).any()
    assert q["splits"]["train"]["participants"] == len(tr)


def test_sessions_of_one_participant_never_straddle_splits(paths):
    df = research_df(n_participants=30)
    extra = df.copy()
    extra["session_id"] = extra["participant_id"] + "_S02"
    load(paths, pd.concat([df, extra], ignore_index=True))
    pl.process_dataset(paths)
    sets = [set(pd.read_csv(paths.processed / f"{n}.csv")["participant_id"]) for n in ("train", "calibration", "test")]
    assert not (sets[0] & sets[1]) and not (sets[0] & sets[2]) and not (sets[1] & sets[2])


def test_split_is_reproducible(paths, tmp_path_factory):
    other = make_paths(tmp_path_factory.mktemp("again"))
    df = research_df(n_participants=40)
    for p in (paths, other):
        load(p, df)
        pl.process_dataset(p)
    assert (paths.processed / "split_manifest.json").read_text() == (other.processed / "split_manifest.json").read_text()


# ---------------------------------------------------------------- features
def test_processed_features_come_from_the_central_function(paths):
    load(paths, research_df(n_participants=20))
    pl.process_dataset(paths)
    df = pd.read_csv(paths.processed / "train.csv")
    row = df.iloc[0]
    expect = engineer_features({"spo2": row["spo2"], "pi": row["pi"], "ita": row["ita"]})
    for k, v in expect.items():
        assert row[k] == pytest.approx(v)
    assert "sao2_target" in df.columns and df["participant_id"].dtype != float
    assert not any("sao2" in c for c in df.columns if c != "sao2_target")
    assert set(df.columns) >= {"spo2", "d", "pi", "log_pi", "ita", "ita_x_d", "log_pi_x_d", "ita_x_log_pi", "device_id"}
    assert "sqi" not in df.columns and "motion" not in df.columns            # not in this dataset -> not invented


def test_optional_predictors_included_only_when_complete(paths):
    df = research_df(n_participants=20)
    df["sqi"] = np.random.default_rng(0).uniform(0, 100, len(df))
    df["motion"] = np.random.default_rng(1).uniform(0, 100, len(df))
    df.loc[3, "motion"] = np.nan
    load(paths, df)
    q = pl.process_dataset(paths)
    assert "sqi" in q["predictors"] and "motion" not in q["predictors"] and "motion" in q["excluded_optional_predictors"]


def test_pipeline_uses_no_shell_commands_and_no_demo_generator():
    src = open(pl.__file__, encoding="utf-8").read()
    assert "os.system" not in src and "generate_demo" not in src and "np.random.seed" not in src


# ---------------------------------------------------------------- API
@pytest.fixture
def client(tmp_path):
    set_paths(make_paths(tmp_path))
    yield TestClient(app)
    set_paths(None)


def test_api_status_and_processing_flow(client, tmp_path):
    assert client.get("/api/dataset/status").json()["loaded"] is False
    assert client.post("/api/dataset/process").json()["errors"][0]["code"] == "no_dataset"
    load(make_paths(tmp_path), research_df(n_participants=30))
    st = client.get("/api/dataset/status").json()
    assert st["loaded"] and st["file"] == "research_dataset.csv" and st["processed"] is False and st["type"] == "LOADED DATASET"
    pr = client.post("/api/dataset/process").json()
    assert pr["status"] == "success" and pr["rows_kept"] == 180
    assert client.get("/api/dataset/status").json()["processed"] is True
    assert client.get("/api/dataset/quality").json()["rows_in"] == 180
    assert client.get("/api/dataset/summary").json() == {"Rows": 180, "Participants": 30, "Devices": 1}
    assert "Data Collection" in client.get("/api/dataset/limits").json()["data_source"]


def test_features_endpoint_still_works(client):
    r = client.post("/api/features/engineer", json={"spo2": 95, "pi": 2.0, "ita": 30})
    assert r.status_code == 200 and r.json()["d"] == 5


def test_pigmentcal_home_relocates_data_models_and_results(tmp_path):
    """PIGMENTCAL_HOME keeps data out of the project (deployments, experiments); the default is the backend folder."""
    code = "from app.ml.paths import DEFAULT_PATHS as p, BACKEND_DIR; print(p.raw); print(p.models); print(p.results); print(p.collection_dir); print(BACKEND_DIR)"
    cwd = os.path.dirname(os.path.dirname(__file__))
    env = {**os.environ, "PIGMENTCAL_HOME": str(tmp_path)}
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, check=True, cwd=cwd).stdout.split("\n")
    assert out[0] == str(tmp_path / "data" / "raw") and out[1] == str(tmp_path / "models") and out[2] == str(tmp_path / "results")
    assert out[3] == str(tmp_path / "data" / "collection")
    env.pop("PIGMENTCAL_HOME")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, check=True, cwd=cwd).stdout.split("\n")
    assert out[0] == os.path.join(out[4], "data", "raw")
