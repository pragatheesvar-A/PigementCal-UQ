import math

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.features import classify_ita, classify_pi, engineer_features
from app.services.reliability import assess
from app.services.validation import InputValidationError, validate_inputs

client = TestClient(app)
DEV = "ESP32 + MAX30102"
OK = {"spo2": 94, "pi": 0.8, "ita": 12.4, "signal_quality": "MODERATE", "motion": "LOW", "device": DEV}


def errors_for(**changes):
    with pytest.raises(InputValidationError) as e:
        validate_inputs({**OK, **changes})
    return {x["field"]: x for x in e.value.errors}


# ---- validation ----
@pytest.mark.parametrize("v", [69.9, 100.1, -5])
def test_spo2_out_of_range(v):
    assert "OUTSIDE SUPPORTED RANGE" in errors_for(spo2=v)["spo2"]["message"] or "OUTSIDE SUPPORTED" in errors_for(spo2=v)["spo2"]["message"]


@pytest.mark.parametrize("v", [70, 100])
def test_spo2_boundaries_ok(v):
    assert validate_inputs({**OK, "spo2": v}).spo2 == v


@pytest.mark.parametrize("v", [0, -1])
def test_pi_must_be_positive(v):
    assert "INVALID PI" in errors_for(pi=v)["pi"]["message"]


def test_missing_ita_required():
    assert "OBJECTIVE PIGMENTATION VALUE REQUIRED" in errors_for(ita=None)["ita"]["message"]


def test_nan_rejected_and_all_errors_reported_together():
    assert errors_for(spo2=math.nan)["spo2"]["code"] == "invalid_type"
    assert set(errors_for(signal_quality="AWESOME", motion=None, device="Device Z", spo2=None)) == {"signal_quality", "motion", "device", "spo2"}


def test_device_must_be_a_registered_source():
    assert validate_inputs({**OK, "device": "Phone camera"}).device == "Phone camera"
    assert errors_for(device="Device A")["device"]["code"] == "invalid_choice"


# ---- classification / features ----
@pytest.mark.parametrize("ita,g", [(60, "Light"), (41.1, "Light"), (41, "Medium"), (10.1, "Medium"), (10, "Dark"), (-40, "Dark")])
def test_classify_ita(ita, g):
    assert classify_ita(ita) == g


@pytest.mark.parametrize("pi,g", [(0.3, "Low"), (0.99, "Low"), (1.0, "Normal"), (3, "Normal")])
def test_classify_pi(pi, g):
    assert classify_pi(pi) == g


def test_feature_values():
    f = engineer_features(94, math.e, 10)
    assert f["d"] == 6 and f["log_pi"] == pytest.approx(1.0) and f["ita_x_d"] == 60
    assert f["log_pi_x_d"] == pytest.approx(6.0) and f["ita_x_log_pi"] == pytest.approx(10.0)


# ---- the engine: a state and reasons, never an invented range ----
def codes(r):
    return {x["code"] for x in r["reasons"]}


def test_no_uncertainty_range_is_produced():
    r = assess(OK)
    assert r["uncertainty_range"] is None and "No calibrated uncertainty range" in r["uncertainty_note"]
    assert "interval" not in r and "lower_bound" not in r


def test_poor_signal_abstains():
    r = assess({**OK, "signal_quality": "POOR"})
    assert r["reliability_state"] == "ABSTAIN" and "REACQUIRE" in r["status"] and codes(r) >= {"poor_signal", "abstain"}


def test_high_motion_abstains():
    r = assess({**OK, "motion": "HIGH", "signal_quality": "GOOD"})
    assert r["reliability_state"] == "ABSTAIN" and "high_motion" in codes(r)


def test_green_when_everything_is_favorable():
    r = assess({**OK, "pi": 2.0, "signal_quality": "GOOD"})
    assert r["reliability_state"] == "GREEN" and r["points"] == 0 and "good_conditions" in codes(r)


@pytest.mark.parametrize("changes,points", [({"pi": 0.8, "signal_quality": "GOOD"}, 1), ({"pi": 2, "signal_quality": "MODERATE"}, 1),
                                             ({"pi": 2, "signal_quality": "GOOD", "motion": "MEDIUM"}, 1), ({"pi": 0.8, "signal_quality": "MODERATE"}, 2)])
def test_amber_from_one_or_two_points(changes, points):
    r = assess({**OK, **changes})
    assert r["reliability_state"] == "AMBER" and r["points"] == points


@pytest.mark.parametrize("changes", [
    {"pi": 0.3, "signal_quality": "MODERATE"},                       # very low PI (2) + moderate signal (1)
    {"pi": 0.8, "signal_quality": "MODERATE", "motion": "MEDIUM"},   # 1 + 1 + 1
])
def test_red_when_degrading_conditions_add_up(changes):
    r = assess({**OK, **changes})
    assert r["reliability_state"] == "RED" and r["points"] >= 3 and "multiple_factors" in codes(r)


def test_red_threshold_is_configurable():
    from dataclasses import replace
    from app.config import RELIABILITY_CONFIG
    cfg = replace(RELIABILITY_CONFIG, red_points=2)
    assert assess({**OK, "pi": 0.8, "signal_quality": "MODERATE"}, cfg)["reliability_state"] == "RED"
    assert assess({**OK, "pi": 0.8, "signal_quality": "MODERATE"})["reliability_state"] == "AMBER"


def test_low_pi_wording_never_claims_inaccuracy():
    r = assess({**OK, "pi": 0.3, "signal_quality": "GOOD"})
    low = next(x for x in r["reasons"] if x["code"] == "low_pi")
    assert "may reduce signal strength and can increase measurement uncertainty" in low["text"]
    assert "very_low_pi" in codes(r)


def test_reasons_never_blame_skin_and_report_the_subgroup_honestly():
    r = assess({**OK, "ita": 0, "pi": 0.4})
    text = " ".join(x["text"] for x in r["reasons"]).lower()
    assert "dark skin" not in text and "caused" not in text
    sub = next(x for x in r["reasons"] if x["code"] == "subgroup_info")
    assert "Dark × Low PI" in sub["text"] and "not available until a real dataset is loaded" in sub["text"]


def test_sources_are_echoed():
    r = assess({**OK, "signal_source": "live", "ita_source": "pigmentation_module", "pi_source": "ppg", "sqi": 71.0})
    assert (r["signal_source"], r["ita_source"], r["pi_source"], r["sqi"]) == ("live", "pigmentation_module", "ppg", 71.0)


# ---- API ----
def test_api_predict_shape():
    r = client.post("/api/reliability/predict", json=OK)
    assert r.status_code == 200
    b = r.json()
    for k in ("spo2", "pi", "ita", "pigmentation_group", "perfusion_state", "signal_quality", "motion", "device", "features",
              "reliability_state", "status", "reasons", "uncertainty_range", "uncertainty_note"):
        assert k in b
    assert b["pigmentation_group"] == "Medium" and b["perfusion_state"] == "LOW"


def test_api_validation_error_is_human_readable():
    r = client.post("/api/reliability/predict", json={**OK, "spo2": 105})
    assert r.status_code == 422 and "OUTSIDE SUPPORTED" in r.json()["errors"][0]["message"]
    assert client.post("/api/reliability/predict", json={**OK, "spo2": "abc"}).json()["errors"][0]["field"] == "spo2"
    assert {e["field"] for e in client.post("/api/reliability/predict", json={}).json()["errors"]} == {"spo2", "pi", "ita", "signal_quality", "motion", "device"}


def test_reliability_rejects_bad_sqi():
    r = client.post("/api/reliability/predict", json={**OK, "signal_quality": "GOOD", "sqi": 150})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "sqi"


# ---- demo modes are gone ----
@pytest.mark.parametrize("path", ["/api/demo/snapshot", "/api/reliability/scenarios", "/api/perfusion/scenarios",
                                  "/api/signal/demo/kinds"])
def test_demo_endpoints_removed(path):
    assert client.get(path).status_code == 404


def test_no_synthetic_signal_endpoint():
    assert client.post("/api/signal/demo", json={"kind": "clean"}).status_code in (404, 405)


def test_health_reports_real_state_only():
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and "mode" not in h and set(h["dataset"]) >= {"loaded", "note"}
