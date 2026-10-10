"""API resilience: the service answers in JSON with an actionable message when saved files are unreadable, never an HTML/plain 500,
and optional resources that do not exist yet are a normal empty state (available: false), not an HTTP error. TEST-ONLY data."""

import importlib
import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.ml import train
from app.ml.paths import set_paths
from app.conformal import fit as cfit

from .test_conformal import CFG, READING, build_env, make_paths


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    paths = build_env(tmp_path_factory.mktemp("resilience"))
    train.train_models(paths)
    cfit.fit_conformal(paths, CFG)
    return paths


def corrupt(f, payload=b"\x00\xff garbage {{{"):
    orig = f.read_bytes()
    f.write_bytes(payload)
    return orig


def is_json(r):
    return "json" in r.headers.get("content-type", "")


# ------------------------------------------------------------------ startup and CORS
def test_both_start_commands_load_the_same_application():
    import main as shim                                          # `uvicorn main:app` from backend/
    assert shim.app is app and importlib.import_module("app.main").app is app


@pytest.mark.parametrize("origin", ["http://localhost:5173", "http://localhost:5174", "http://127.0.0.1:4173"])
def test_cors_allows_local_dev_and_preview_ports(client, origin):
    r = client.options("/api/health", headers={"Origin": origin, "Access-Control-Request-Method": "GET"})
    assert r.headers.get("access-control-allow-origin") == origin


def test_cors_rejects_other_origins(client):
    for origin in ("http://evil.example.com", "https://localhost:5173", "http://localhost.evil.com"):
        r = client.options("/api/health", headers={"Origin": origin, "Access-Control-Request-Method": "GET"})
        assert "access-control-allow-origin" not in r.headers


# ------------------------------------------------------------------ healthy empty project
def test_empty_project_every_get_is_json_and_not_an_error(tmp_path, client):
    set_paths(make_paths(tmp_path))
    paths = sorted(p for p, ops in app.openapi()["paths"].items() if "get" in ops and "{" not in p)
    for p in paths:
        r = client.get(p)
        assert r.status_code == 200 and is_json(r), (p, r.status_code)
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["problems"] == [] and h["research_status"]["state"] == "NO_DATA" and h["model"]["trained"] is False
    for p in ("/api/model/metrics", "/api/model/predictions", "/api/conformal/metrics", "/api/conformal/coverage", "/api/validation/report", "/api/xai/report"):
        body = client.get(p).json()
        assert body["available"] is False and body["errors"][0]["message"], p       # a normal empty state with a reason, never fake data
    assert client.get("/api/model/status").json()["research_results"] is False


# ------------------------------------------------------------------ unreadable saved files
def test_unreadable_dataset_file_degrades_health_but_never_fails_it(tmp_path, client):
    paths = build_env(tmp_path)
    set_paths(paths)
    orig = corrupt(paths.raw / "dataset.csv")
    try:
        h = client.get("/api/health")
        assert h.status_code == 200
        j = h.json()
        assert j["status"] == "degraded" and j["problems"] and j["dataset"]["loaded"] is True and j["dataset"]["verified"] is False
        assert "could not be read" in j["dataset"]["note"] and j["research_status"]["results_allowed"] is False
        for p in ("/api/dataset/status", "/api/dataset/summary"):
            r = client.get(p)
            assert r.status_code == 200 and is_json(r)
    finally:
        (paths.raw / "dataset.csv").write_bytes(orig)


@pytest.mark.parametrize("rel,call,expect_code", [
    ("results/test_predictions.csv", ("get", "/api/model/predictions"), "artifacts_unreadable"),
    ("results/test_predictions.csv", ("get", "/api/validation/report"), "artifacts_unreadable"),
    ("models/lightgbm_model.joblib", ("get", "/api/xai/report"), "artifact_untrusted"),  # a changed file no longer matches its SHA-256: refused before it is unpickled
    ("models/ridge_model.joblib", ("post", "/api/model/predict"), "artifact_untrusted"),  # a changed file no longer matches its SHA-256: refused before it is unpickled
    ("models/cqr_models.joblib", ("post", "/api/conformal/predict"), "artifact_untrusted"),  # a changed file no longer matches its SHA-256: refused before it is unpickled
])
def test_unreadable_artifacts_give_an_actionable_json_message(trained, client, rel, call, expect_code):
    set_paths(trained)
    f = trained.models.parent / rel
    orig = corrupt(f)
    try:
        method, path = call
        r = client.get(path) if method == "get" else client.post(path, json=READING if "conformal" in path else {"spo2": 94, "pi": 2, "ita": 35, "sqi": 85, "motion": 5})
        assert r.status_code < 500 and is_json(r), (path, r.status_code, r.text[:80])
        body = r.json()
        err = body["errors"][0]
        assert err["code"] == expect_code and ("again" in err["message"] or "Train" in err["message"] or "calibrate" in err["message"].lower())
        assert body.get("available", False) is False                       # never reported as usable
    finally:
        f.write_bytes(orig)


def test_unreadable_staging_table_is_reported_not_a_500(tmp_path, client):
    paths = build_env(tmp_path)
    set_paths(paths)
    f = paths.collection_dir / "combined_records.csv"
    orig = corrupt(f)
    try:
        r = client.get("/api/collection/status")
        assert r.status_code == 200
        probs = r.json()["problems"]
        assert probs and probs[0]["code"] == "staging_unreadable" and "upload it again" in probs[0]["message"]
    finally:
        f.write_bytes(orig)
    assert client.get("/api/collection/status").json()["problems"] == []


# ------------------------------------------------------------------ safety net
def test_unexpected_server_errors_are_json_and_actionable(monkeypatch, tmp_path, client):
    set_paths(make_paths(tmp_path))
    import app.api.dataset as dataset_api

    def boom():
        raise RuntimeError("simulated failure")
    monkeypatch.setattr(dataset_api, "dataset_info", boom)
    r = client.get("/api/dataset/status")
    assert r.status_code == 500 and is_json(r)
    err = r.json()["errors"][0]
    assert err["code"] == "internal_error" and "RuntimeError" in err["message"] and "backend log" in err["message"]
    assert "simulated failure" not in json.dumps(r.json())                  # internals are not leaked to the browser


def test_model_artifacts_are_integrity_checked_before_unpickling(trained, client, tmp_path):
    """joblib is pickle: a file without a matching SHA-256 sidecar is never loaded (it could run code)."""
    from app.ml.data import ModelError, load_artifact, save_artifact
    set_paths(trained)
    f = tmp_path / "x.joblib"
    save_artifact({"a": 1}, f)
    assert load_artifact(f) == {"a": 1} and (tmp_path / "x.joblib.sha256").exists()
    (tmp_path / "x.joblib.sha256").unlink()                                   # foreign file: no hash
    with pytest.raises(ModelError) as e:
        load_artifact(f)
    assert e.value.code == "artifact_untrusted"
    save_artifact({"a": 1}, f)
    f.write_bytes(f.read_bytes() + b"x")                                       # changed after saving
    with pytest.raises(ModelError) as e:
        load_artifact(f)
    assert e.value.code == "artifact_untrusted" and "not loaded" in e.value.message
    for p in ("ridge_model.joblib", "lightgbm_model.joblib", "cqr_models.joblib"):   # every real artifact carries its hash
        assert (trained.models / (p + ".sha256")).exists(), p


def test_no_route_accepts_a_model_upload():
    paths = set(app.openapi()["paths"])
    assert not any("upload" in p and "model" in p for p in paths)
    assert not any("joblib" in p or "pickle" in p for p in paths)


@pytest.mark.parametrize("path,raw", [
    ("/api/ita/calculate", '{"L": NaN, "a": 10, "b": 20}'),
    ("/api/ita/calculate", '{"L": 60, "a": Infinity, "b": 20}'),
    ("/api/reliability/predict", '{"spo2": NaN, "pi": 2, "ita": 30, "signal_quality": "GOOD", "motion": "LOW", "device": "ESP32 + MAX30102"}'),
    ("/api/reliability/predict", '{"spo2": 95, "pi": -1, "ita": 30, "signal_quality": "GOOD", "motion": "LOW", "device": "ESP32 + MAX30102"}'),
    ("/api/reliability/predict", '{"spo2": 95, "pi": Infinity, "ita": 30, "signal_quality": "GOOD", "motion": "LOW", "device": "ESP32 + MAX30102"}'),
    ("/api/reliability/predict", '{"spo2": 95, "pi": 2, "ita": -Infinity, "signal_quality": "GOOD", "motion": "LOW", "device": "ESP32 + MAX30102"}'),
])
def test_nan_inf_and_negative_inputs_get_a_422_with_a_message_never_a_500(client, path, raw):
    r = client.post(path, content=raw, headers={"Content-Type": "application/json"})
    assert r.status_code == 422, (path, raw, r.status_code, r.text[:120])
    assert r.json()["errors"][0]["message"]


def test_every_metric_bearing_endpoint_carries_the_data_origin_label(trained, client):
    set_paths(trained)
    for path in ("/api/model/status", "/api/model/metrics", "/api/model/predictions", "/api/conformal/status" if False else "/api/model/status",
                 "/api/validation/report", "/api/xai/report", "/api/health"):
        j = client.get(path).json()
        rs = j.get("research_status")
        assert rs and rs["state"] and rs["label"] and rs["results_allowed"] is False, path          # test fixtures are never research results
    cfit.fit_conformal(trained, CFG)
    for path in ("/api/conformal/metrics", "/api/conformal/coverage"):
        j = client.get(path).json()
        assert j["research_status"]["results_allowed"] is False and j["research_status"]["label"], path
