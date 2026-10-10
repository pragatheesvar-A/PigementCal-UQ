"""Reliability-state truth table (GREEN / AMBER / RED / ABSTAIN).

EXPECTED values come from the documented design (README / config.py: points system, abstain rules, calibration minimums), written
BEFORE looking at the output; each row is then compared with what the engines ACTUALLY return. All data are test-only fixtures
in temporary folders. A failing row means the code and the design disagree: it must be investigated, never "fixed" by editing the expectation.
"""
import pytest
from fastapi.testclient import TestClient

from app.conformal import predict as cpredict
from app.main import app
from tests.test_conformal import CFG, READING, env  # noqa: F401  (module-scoped fixture: test-only fitted conformal layer)

DEV = "ESP32 + MAX30102"
OK = {"spo2": 94.0, "pi": 2.0, "ita": 35.0, "signal_quality": "GOOD", "motion": "LOW", "device": DEV, "sqi": 85, "motion_score": 5}

# name, input changes, expected RULE-ENGINE state (api/reliability/predict), expected CONFORMAL relation
# The conformal layer = rule engine + the calibrated interval (config: width_amber/red, gap_amber/red), so its state may only be EQUAL or MORE
# CAUTIOUS than the rule engine's, and must ABSTAIN (no interval) when the rule engine abstains or an input is outside the fitted range.
# (My first draft expected conformal == rule for every row; that was wrong because the interval criteria were left out, not a code defect.)
ORDER = {"GREEN": 0, "AMBER": 1, "RED": 2, "ABSTAIN": 3}
ROWS = [
    ("normal",                    {},                                                                           "GREEN"),
    ("low PI (0.8)",              {"pi": 0.8},                                                                  "AMBER"),
    ("very low PI (0.3)",         {"pi": 0.3},                                                                  "AMBER"),
    ("high motion",               {"motion": "HIGH"},                                                           "ABSTAIN"),
    ("poor signal quality",       {"signal_quality": "POOR", "sqi": 20},                                        "ABSTAIN"),
    ("high noise (MODERATE sqi)", {"signal_quality": "MODERATE", "sqi": 55},                                    "AMBER"),
    ("combined (low PI+MODERATE+MEDIUM motion)", {"pi": 0.8, "signal_quality": "MODERATE", "motion": "MEDIUM", "motion_score": 25}, "RED"),
]


@pytest.mark.parametrize("name,changes,rule_expected", ROWS, ids=[r[0] for r in ROWS])
def test_truth_table_rows(env, name, changes, rule_expected):  # noqa: F811
    body = {**OK, **changes}
    rule = TestClient(app).post("/api/reliability/predict", json=body)
    assert rule.status_code == 200, (name, rule.text)
    assert rule.json()["reliability_state"] == rule_expected, f"{name}: rule engine returned {rule.json()['reliability_state']}"
    conf = cpredict.predict_one(body, env[0], CFG)
    assert ORDER[conf["reliability_state"]] >= ORDER[rule_expected], f"{name}: conformal layer {conf['reliability_state']} is LESS cautious than the rule engine {rule_expected}"
    if rule_expected == "ABSTAIN":
        assert conf["reliability_state"] == "ABSTAIN"
    if conf["reliability_state"] == "ABSTAIN":
        assert conf["interval"] is None and conf["lower_bound"] is None               # an abstention never carries an interval
        assert any(r["code"] == "abstain" for r in conf["reasons"])
    else:
        assert conf["interval"] is not None and conf["interval"]["lower"] <= conf["lower_bound"] + 1e-9 or conf["lower_bound"] is not None


def test_unsupported_ita_is_rejected_not_assessed(env):  # noqa: F811
    for ita in (140.0, -95.0):
        r = TestClient(app).post("/api/reliability/predict", json={**OK, "ita": ita})
        assert r.status_code == 422 and "OUTSIDE SUPPORTED RANGE" in r.json()["errors"][0]["message"]
        with pytest.raises(Exception):
            cpredict.predict_one({**OK, "ita": ita}, env[0], CFG)


def test_missing_inputs_rule_engine_rejects_and_conformal_abstains(env):  # noqa: F811
    r = TestClient(app).post("/api/reliability/predict", json={k: v for k, v in OK.items() if k != "ita"})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "ita"
    c = cpredict.predict_one({k: v for k, v in OK.items() if k != "sqi"}, env[0], CFG)
    assert c["reliability_state"] == "ABSTAIN" and any(x["code"] == "missing_inputs" for x in c["reasons"])


def test_insufficient_calibration_cell_abstains_with_its_reason(env):  # noqa: F811
    c = cpredict.predict_one({**OK, "ita": -10.0}, env[0], CFG)      # the test fixture has no Dark participants at all
    assert c["reliability_state"] == "ABSTAIN" and c["interval"] is None
    assert any(x["code"] == "insufficient_calibration" for x in c["reasons"]) or any(x["code"] == "outside_range" for x in c["reasons"])


def test_no_model_means_no_conformal_answer_but_the_rule_engine_still_works(tmp_path):
    from app.ml.paths import set_paths
    from tests.test_conformal import make_paths
    set_paths(make_paths(tmp_path))
    c = TestClient(app).post("/api/conformal/predict", json=OK)
    assert c.status_code == 200 and c.json()["available"] is False and "CONFORMAL MODEL NOT AVAILABLE" in c.json()["errors"][0]["message"]
    assert TestClient(app).post("/api/reliability/predict", json=OK).json()["reliability_state"] == "GREEN"


# ---------------------------------------------------------------- second-pass additions (expectations written from the design, then compared)
from dataclasses import replace  # noqa: E402

from app.config import CONFORMAL_CONFIG  # noqa: E402


@pytest.mark.parametrize("drop,field", [("pi", "pi"), ("spo2", "spo2"), ("ita", "ita")])
def test_missing_core_inputs_are_rejected_by_the_rule_engine_with_the_field_named(drop, field):
    r = TestClient(app).post("/api/reliability/predict", json={k: v for k, v in OK.items() if k != drop})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == field


def test_motion_zero_is_a_measured_value_and_missing_is_a_different_thing(env):  # noqa: F811
    zero = cpredict.predict_one({**OK, "motion_score": 0.0}, env[0], CFG)
    assert not any(r["code"] == "missing_inputs" for r in zero["reasons"])           # 0.0 is NOT treated as missing
    blank = cpredict.predict_one({k: v for k, v in OK.items() if k != "motion_score"}, env[0], CFG)
    assert blank["reliability_state"] == "ABSTAIN" and any(r["code"] == "missing_inputs" for r in blank["reasons"])
    far = cpredict.predict_one({**OK, "motion_score": 95.0}, env[0], CFG)             # beyond the fitted range of the fixture
    assert far["reliability_state"] == "ABSTAIN" and any(r["code"] == "outside_range" for r in far["reasons"])


def test_interval_width_and_gap_map_to_amber_and_red_through_the_configured_thresholds_only(env):  # noqa: F811
    narrow = replace(CFG, width_amber=1e6, width_red=1e6, gap_amber=1e6, gap_red=1e6)
    assert cpredict.predict_one(OK, env[0], narrow)["reliability_state"] == "GREEN"           # nothing can flag: GREEN
    amber = cpredict.predict_one(OK, env[0], replace(narrow, width_amber=0.0001))
    assert amber["reliability_state"] == "AMBER" and any(r["code"] == "wide_interval" for r in amber["reasons"])
    red = cpredict.predict_one(OK, env[0], replace(narrow, width_amber=0.0001, width_red=0.0002))
    assert red["reliability_state"] == "RED"
    red_gap = cpredict.predict_one(OK, env[0], replace(narrow, gap_amber=-1e6, gap_red=-1e6 + 1))
    assert red_gap["reliability_state"] == "RED" and any(r["code"] == "low_lower_bound" for r in red_gap["reasons"])


def test_the_device_label_never_changes_the_state_or_the_interval(env):  # noqa: F811
    real = cpredict.predict_one({**OK, "device": "ESP32 + MAX30102"}, env[0], CFG)
    virt = cpredict.predict_one({**OK, "device": "Virtual ESP32 + Virtual MAX30102 (simulation)"}, env[0], CFG)
    other = cpredict.predict_one({**OK, "device": "Other"}, env[0], CFG)
    for k in ("reliability_state", "interval", "lower_bound", "predicted_sao2", "cell", "reasons"):
        assert real[k] == virt[k] == other[k], k
    assert virt["device"].startswith("Virtual") and real["device"] == "ESP32 + MAX30102"
