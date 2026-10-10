import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.ppg import analyze_ppg, bandpass, classify_sqi, clean_ppg
from tests.synthetic import KINDS, generate_demo_ppg
from app.services.validation import InputValidationError

client = TestClient(app)
FS = 100


def sig(kind):
    return generate_demo_ppg(kind).tolist()


def err_fields(**kw):
    with pytest.raises(InputValidationError) as e:
        analyze_ppg(**kw)
    return {x["field"]: x for x in e.value.errors}


# ---- invalid / empty / degenerate input ----
def test_empty_ppg():
    assert err_fields(ppg=[], sampling_rate=FS)["ppg"]["code"] == "missing"


def test_missing_ppg_and_fs():
    assert set(err_fields(ppg=None, sampling_rate=None)) == {"ppg", "sampling_rate"}


def test_all_invalid_ppg():
    assert err_fields(ppg=["a", None, "b"] * 200, sampling_rate=FS)["ppg"]["code"] == "too_many_invalid"


def test_some_invalid_samples_interpolated_and_counted():
    x = sig("clean")
    x[100] = None
    x[200] = "bad"
    x[300] = float("nan")
    r = analyze_ppg(x, FS)
    assert r["metrics"]["invalid_samples"] == 3 and len(r["raw_ppg"]) == len(x)
    assert any("invalid" in q["text"] for q in r["reasons"])


def test_too_many_invalid_rejected():
    x = sig("clean")
    for i in range(0, 440, 2):
        x[i] = None
    assert err_fields(ppg=x, sampling_rate=FS)["ppg"]["code"] == "too_many_invalid"


def test_too_short():
    assert err_fields(ppg=sig("clean")[:200], sampling_rate=FS)["ppg"]["code"] == "too_short"


@pytest.mark.parametrize("fs", [5, 5000, 0, -1])
def test_bad_sampling_rate(fs):
    assert err_fields(ppg=sig("clean"), sampling_rate=fs)["sampling_rate"]["code"] == "out_of_range"


def test_bad_manual_motion():
    assert "motion" in err_fields(ppg=sig("clean"), sampling_rate=FS, motion="SHAKY")


def test_constant_signal_is_poor_not_a_crash():
    r = analyze_ppg([50.0] * 1000, FS)
    assert r["sqi"] == 0 and r["signal_quality"] == "POOR" and r["pulse_rate_estimate"] is None
    assert r["reliability_impact"]["state_hint"] == "ABSTAIN"


# ---- filtering ----
def test_filter_removes_dc_and_slow_drift_keeps_pulse_band():
    t = np.arange(0, 20, 1 / FS)
    drift = 5 * np.sin(2 * np.pi * 0.05 * t)
    pulse = np.sin(2 * np.pi * 1.2 * t)
    f = bandpass(100 + drift + pulse, FS)
    mid = slice(500, -500)  # ignore edge transients
    assert abs(np.mean(f[mid])) < 0.05
    assert np.std(f[mid] - pulse[mid]) < 0.35  # drift largely gone, pulse retained


def test_filter_attenuates_high_frequency_noise():
    t = np.arange(0, 20, 1 / FS)
    noise = np.sin(2 * np.pi * 25 * t)
    assert np.std(bandpass(noise, FS)[500:-500]) < 0.02


def test_clean_ppg_keeps_valid_values_unchanged():
    arr, n = clean_ppg([1.0, 2.0, 3.0])
    assert n == 0 and arr.tolist() == [1.0, 2.0, 3.0]


# ---- SQI / classification ----
def test_clean_signal_good_and_pulse_rate_plausible():
    r = analyze_ppg(sig("clean"), FS)
    assert r["signal_quality"] == "GOOD" and r["sqi"] >= 70
    assert abs(r["pulse_rate_estimate"] - 72) < 5
    assert r["motion_state"] == "LOW" and r["metrics"]["n_peaks"] >= 10
    assert r["pi_estimate"] is not None


def test_moderate_noise_signal_is_moderate():
    assert analyze_ppg(sig("moderate"), FS)["signal_quality"] == "MODERATE"


@pytest.mark.parametrize("kind", ["noisy", "nopulse"])
def test_noisy_or_pulseless_is_poor_and_withholds_estimates(kind):
    r = analyze_ppg(sig(kind), FS)
    assert r["signal_quality"] == "POOR"
    assert r["pulse_rate_estimate"] is None and r["pi_estimate"] is None
    assert r["reliability_impact"]["state_hint"] == "ABSTAIN"


def test_high_motion_signal_detected():
    r = analyze_ppg(sig("motion"), FS)
    assert r["motion_state"] == "HIGH" and r["motion_source"] == "estimated" and r["motion_score"] >= 60
    assert r["reliability_impact"]["state_hint"] == "ABSTAIN"


def test_quality_ordering_across_seeds():
    for seed in range(1, 8):
        clean = analyze_ppg(generate_demo_ppg("clean", seed=seed).tolist(), FS)["sqi"]
        noisy = analyze_ppg(generate_demo_ppg("noisy", seed=seed).tolist(), FS)["sqi"]
        assert clean > noisy + 40


def test_manual_motion_overrides_estimate():
    r = analyze_ppg(sig("clean"), FS, motion="high")
    assert r["motion_state"] == "HIGH" and r["motion_source"] == "manual" and r["estimated_motion_state"] == "LOW"
    assert r["reliability_impact"]["state_hint"] == "ABSTAIN"


@pytest.mark.parametrize("sqi,q", [(100, "GOOD"), (70, "GOOD"), (69.9, "MODERATE"), (40, "MODERATE"), (39.9, "POOR"), (0, "POOR")])
def test_classify_sqi(sqi, q):
    assert classify_sqi(sqi) == q


def test_other_sampling_rates_work():
    x = generate_demo_ppg("clean", fs=50).tolist()
    r = analyze_ppg(x, 50)
    assert r["signal_quality"] == "GOOD" and abs(r["pulse_rate_estimate"] - 72) < 6


def test_generator_is_deterministic_and_rejects_unknown_kind():
    assert np.array_equal(generate_demo_ppg("noisy"), generate_demo_ppg("noisy"))
    with pytest.raises(ValueError):
        generate_demo_ppg("???")


# ---- API ----
def test_api_analyze_shape():
    r = client.post("/api/signal/analyze", json={"ppg": sig("clean"), "sampling_rate": FS})
    assert r.status_code == 200
    b = r.json()
    for k in ("filtered_ppg", "sqi", "signal_quality", "motion_score", "motion_state", "pulse_rate_estimate", "metrics"):
        assert k in b
    assert len(b["filtered_ppg"]) == len(sig("clean")) and "not clinically validated" in b["thresholds"]["label"]


def test_api_errors_human_readable():
    r = client.post("/api/signal/analyze", json={"ppg": [], "sampling_rate": FS})
    assert r.status_code == 422 and "empty" in r.json()["errors"][0]["message"]
    r = client.post("/api/signal/analyze", json={"ppg": "notalist", "sampling_rate": FS})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "ppg"


def test_api_roundtrip_for_all_unit_test_signals():
    for k in KINDS:
        x = [round(float(v), 5) for v in generate_demo_ppg(k)]
        assert client.post("/api/signal/analyze", json={"ppg": x, "sampling_rate": FS}).status_code == 200


# ---- connection to the Phase 2 reliability engine ----
RELI = {"spo2": 96, "pi": 2.0, "ita": 25, "device": "ESP32 + MAX30102"}


def reliability_from_signal(kind):
    s = analyze_ppg(sig(kind), FS)
    body = {**RELI, "signal_quality": s["signal_quality"], "motion": s["motion_state"], "sqi": s["sqi"],
            "signal_source": "signal_module"}
    return client.post("/api/reliability/predict", json=body).json()


def test_poor_signal_flows_to_abstain():
    r = reliability_from_signal("noisy")
    assert r["reliability_state"] == "ABSTAIN" and r["signal_source"] == "signal_module"


def test_motion_signal_flows_to_abstain():
    assert reliability_from_signal("motion")["reliability_state"] == "ABSTAIN"


def test_moderate_signal_flows_to_amber():
    assert reliability_from_signal("moderate")["reliability_state"] == "AMBER"


def test_good_signal_can_be_green():
    r = reliability_from_signal("clean")
    assert r["reliability_state"] == "GREEN" and r["sqi"] > 70


def test_reliability_rejects_bad_sqi():
    r = client.post("/api/reliability/predict", json={**RELI, "signal_quality": "GOOD", "motion": "LOW", "sqi": 150})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "sqi"
