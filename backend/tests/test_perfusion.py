import math

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.perfusion import calculate_pi, cell_for, direct_pi, ita_pi_matrix
from app.services.ppg import analyze_ppg
from tests.synthetic import generate_demo_ppg
from app.services.validation import InputValidationError

client = TestClient(app)


def errs(fn, raw):
    with pytest.raises(InputValidationError) as e:
        fn(raw)
    return {x["field"]: x for x in e.value.errors}


# ---- 1. normal AC/DC ----
def test_normal_ac_dc():
    r = calculate_pi({"ac_ir": 2.0, "dc_ir": 100.0})
    assert r["pi"] == pytest.approx(2.0) and r["perfusion_state"] == "NORMAL"
    assert r["ac_ir"] == 2.0 and r["dc_ir"] == 100.0 and r["source"] == "ac_dc" and r["warnings"] == []
    assert "not clinically validated" in r["thresholds"]["label"]


def test_formula_is_ac_over_dc_times_100():
    r = calculate_pi({"ac_ir": 1.234, "dc_ir": 56.78})
    assert r["pi"] == pytest.approx(100 * 1.234 / 56.78, abs=1e-3)


# ---- 2. low AC ----
def test_low_ac_is_low_with_warning():
    r = calculate_pi({"ac_ir": 0.3, "dc_ir": 100})
    assert r["perfusion_state"] == "LOW" and r["very_low"] is True
    assert any("Low perfusion may reduce PPG signal strength and increase measurement uncertainty" in w for w in r["warnings"])


# ---- 3. DC = 0 ----
def test_dc_zero_no_crash():
    e = errs(calculate_pi, {"ac_ir": 1, "dc_ir": 0})
    assert e["dc_ir"]["message"] == "DC_IR must be greater than zero."


# ---- 4/5. negative ----
def test_negative_ac():
    assert errs(calculate_pi, {"ac_ir": -1, "dc_ir": 100})["ac_ir"]["message"] == "AC_IR must be zero or greater."


def test_negative_dc():
    assert errs(calculate_pi, {"ac_ir": 1, "dc_ir": -5})["dc_ir"]["code"] == "not_positive"


# ---- 6/7. missing ----
def test_missing_ac():
    assert errs(calculate_pi, {"dc_ir": 100})["ac_ir"]["code"] == "missing"


def test_missing_dc():
    assert errs(calculate_pi, {"ac_ir": 1})["dc_ir"]["code"] == "missing"


def test_all_problems_reported_together():
    assert set(errs(calculate_pi, {"ac_ir": "x", "dc_ir": 0})) == {"ac_ir", "dc_ir"}


# ---- AC = 0 ----
def test_ac_zero_is_reported_not_crashed():
    e = errs(calculate_pi, {"ac_ir": 0, "dc_ir": 100})
    assert e["ac_ir"]["code"] == "no_pulsatile_signal" and "reacquiring" in e["ac_ir"]["message"]


# ---- 8. direct PI ----
def test_direct_pi():
    r = direct_pi({"pi": 0.8})
    assert r["pi"] == 0.8 and r["source"] == "manual" and r["perfusion_state"] == "LOW" and r["ac_ir"] is None


@pytest.mark.parametrize("v,state", [(0.3, "LOW"), (0.99, "LOW"), (1.0, "NORMAL"), (2.0, "NORMAL"), (3.0, "NORMAL"), (1.5, "NORMAL")])
def test_classification(v, state):
    assert direct_pi({"pi": v})["perfusion_state"] == state


# ---- 9/10/11. invalid, NaN, Infinity ----
@pytest.mark.parametrize("bad", [0, -0.5, "abc", "", [], True, math.nan, math.inf, -math.inf])
def test_invalid_direct_pi(bad):
    assert errs(direct_pi, {"pi": bad})["pi"]["message"] == "PI must be a positive finite value."


def test_direct_missing():
    assert errs(direct_pi, {})["pi"]["code"] == "missing"


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, "1", True])
def test_nan_inf_ac_dc(bad):
    assert errs(calculate_pi, {"ac_ir": bad, "dc_ir": 100})["ac_ir"]["code"] in ("invalid_type", "negative")
    assert errs(calculate_pi, {"ac_ir": 1, "dc_ir": bad})["dc_ir"]["code"] in ("invalid_type", "not_positive")


# ---- extreme magnitudes ----
def test_overflow_is_an_error_not_a_crash():
    assert "dc_ir" in errs(calculate_pi, {"ac_ir": 1e308, "dc_ir": 1e-300})


def test_extremely_small_dc_warns():
    r = calculate_pi({"ac_ir": 1e-9, "dc_ir": 1e-7})
    assert any("extremely small" in w for w in r["warnings"])


def test_ac_larger_than_dc_warns():
    r = calculate_pi({"ac_ir": 5, "dc_ir": 2})
    assert any("physically unusual" in w for w in r["warnings"])


# ---- 13. warnings ----
def test_unusual_high_pi_is_warning_not_error():
    r = direct_pi({"pi": 15})
    assert any("outside the typical range" in w for w in r["warnings"]) and r["usable_for_reliability"] is True


def test_pi_above_reliability_range_not_usable():
    r = direct_pi({"pi": 40})
    assert r["usable_for_reliability"] is False and any("cannot be sent" in w for w in r["warnings"])


def test_normal_pi_has_no_warning_and_normal_text():
    r = direct_pi({"pi": 2})
    assert r["warnings"] == [] and "within the configured normal range" in r["impact"]


def test_wording_never_claims_inaccuracy():
    for pi in (0.1, 0.8, 2):
        text = " ".join(direct_pi({"pi": pi})["warnings"]).lower() + direct_pi({"pi": pi})["impact"].lower()
        assert "inaccurate" not in text and "proves" not in text and "guarantee" not in text


def test_source_validation():
    assert errs(calculate_pi, {"ac_ir": 1, "dc_ir": 100, "source": "magic"})["source"]["code"] == "invalid_choice"
    assert calculate_pi({"ac_ir": 1, "dc_ir": 100, "source": "ppg"})["pi_source"] == "ppg"


# ---- 14. API ----
def test_api_calculate():
    r = client.post("/api/perfusion/calculate", json={"ac_ir": 0.8, "dc_ir": 100})
    b = r.json()
    assert r.status_code == 200
    for k in ("ac_ir", "dc_ir", "pi", "perfusion_state", "warnings", "thresholds", "source"):
        assert k in b
    assert b["source"] == "ac_dc" and b["perfusion_state"] == "LOW"


def test_api_direct():
    r = client.post("/api/perfusion/direct", json={"pi": 2.0})
    b = r.json()
    assert r.status_code == 200 and b["source"] == "manual" and b["perfusion_state"] == "NORMAL" and b["pi"] == 2.0


def test_api_errors_are_human_readable():
    r = client.post("/api/perfusion/calculate", json={"ac_ir": 1, "dc_ir": 0})
    assert r.status_code == 422 and r.json()["errors"][0]["message"] == "DC_IR must be greater than zero."
    r = client.post("/api/perfusion/direct", json={"pi": "x"})
    assert r.status_code == 422 and r.json()["errors"][0]["message"] == "PI must be a positive finite value."
    assert client.post("/api/perfusion/direct", json={}).status_code == 422
    assert client.post("/api/perfusion/calculate", json={}).status_code == 422


# ---- PPG integration ----
def test_ppg_exposes_ac_dc_consistent_with_pi_estimate():
    s = analyze_ppg(generate_demo_ppg("clean").tolist(), 100)
    assert s["ac_ir"] > 0 and s["dc_ir"] > 0
    api = calculate_pi({"ac_ir": s["ac_ir"], "dc_ir": s["dc_ir"], "source": "ppg"})
    assert api["pi"] == pytest.approx(s["pi_estimate"], abs=1e-3) and api["pi_source"] == "ppg"


def test_poor_ppg_withholds_pi_estimate():
    s = analyze_ppg(generate_demo_ppg("noisy").tolist(), 100)
    assert s["pi_estimate"] is None


# ---- ITA x PI structure ----
def test_matrix_structure_is_3x2_preview_only():
    m = client.get("/api/perfusion/matrix").json()
    assert len(m["cells"]) == 6 and [g["id"] for g in m["ita_groups"]] == ["Light", "Medium", "Dark"]
    assert [g["id"] for g in m["pi_groups"]] == ["Low", "Normal"] and "PREVIEW ONLY" in m["status"]
    assert "coverage" not in {k for c in m["cells"] for k in c}


def test_cell_for():
    assert cell_for(25, 0.5) == {"ita_group": "Medium", "pi_group": "Low"}
    assert cell_for(60, 2) == {"ita_group": "Light", "pi_group": "Normal"}
    assert cell_for(None, 2) is None


def test_matrix_ranges_follow_config():
    m = ita_pi_matrix()
    assert "41" in m["ita_groups"][0]["range"] and "1%" in m["pi_groups"][0]["range"]


# ---- 15. reliability API integration ----
BASE = {"spo2": 94, "ita": 25, "device": "ESP32 + MAX30102"}


def rel(**kw):
    r = client.post("/api/reliability/predict", json={**BASE, **kw})
    return r.json()


def test_reliability_returns_perfusion_fields():
    r = rel(pi=0.3, signal_quality="GOOD", motion="LOW", pi_source="ppg")
    for k in ("pi", "perfusion_state", "ita", "pigmentation_group", "signal_quality", "motion", "reliability_state", "reasons"):
        assert k in r
    assert r["perfusion_state"] == "LOW" and r["pi_source"] == "ppg"


def test_reliability_pi_source_defaults_to_manual():
    assert rel(pi=2, signal_quality="GOOD", motion="LOW")["pi_source"] == "manual"


def test_low_pi_moderate_signal_is_amber_with_reason():
    r = rel(pi=0.8, signal_quality="MODERATE", motion="LOW")
    assert r["reliability_state"] == "AMBER"
    low = next(x for x in r["reasons"] if x["code"] == "low_pi")
    assert "may reduce signal strength and can increase measurement uncertainty" in low["text"]


def test_very_low_pi_reason_and_heavier_weight():
    a = rel(pi=0.8, signal_quality="GOOD", motion="LOW")
    b = rel(pi=0.3, signal_quality="GOOD", motion="LOW")
    assert any(x["code"] == "very_low_pi" for x in b["reasons"]) and not any(x["code"] == "very_low_pi" for x in a["reasons"])
    assert b["points"] > a["points"] and "interval" not in b


def test_poor_signal_low_pi_high_motion_abstains():
    assert rel(pi=0.2, signal_quality="POOR", motion="HIGH")["reliability_state"] == "ABSTAIN"


def test_normal_pi_good_signal_green():
    assert rel(pi=2, signal_quality="GOOD", motion="LOW")["reliability_state"] == "GREEN"


def test_reliability_still_validates_pi():
    r = client.post("/api/reliability/predict", json={**BASE, "pi": 0, "signal_quality": "GOOD", "motion": "LOW"})
    assert r.status_code == 422
