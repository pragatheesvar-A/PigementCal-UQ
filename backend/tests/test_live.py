"""Real-time analysis tests.

Test-only signals with a KNOWN ground truth (a chosen ratio-of-ratios R, polarity, accelerometer noise level, timing jitter)
check the maths exactly. They are not application data; no external dataset is used anywhere in this project.
"""

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.config import LIVE_CONFIG
from app.main import app
from app.services.live import analyze_live, spo2_from_ratio
from app.services.ppg import bandpass
from app.services.validation import InputValidationError
from tests.synthetic import generate_demo_ppg

client = TestClient(app)


def pulse_shape(fs=100, seconds=30, seed=7):
    """Unit pulse waveform (zero mean-ish, peak up) from the test-only generator."""
    x = generate_demo_ppg("clean", fs=fs, duration=seconds, seed=seed)
    x = x - x.mean()
    f = bandpass(x, fs)                                  # PI is defined on the band-passed (pulsatile) signal
    return x / (np.percentile(f, 95) - np.percentile(f, 5))


def two_channel(r_target, fs=100, seconds=15, dc_ir=100000.0, dc_red=80000.0, ai_rel=0.01, invert=False):
    """IR + red with a chosen ratio of ratios R: (AC_red/DC_red) / (AC_ir/DC_ir) == r_target."""
    p = pulse_shape(fs, seconds)
    ir = dc_ir + ai_rel * dc_ir * p
    red = dc_red + (r_target * ai_rel) * dc_red * p
    if invert:
        ir, red = 2 * ir.mean() - ir, 2 * red.mean() - red
    return ir.tolist(), red.tolist()


def errs(**kw):
    with pytest.raises(InputValidationError) as e:
        analyze_live(kw)
    return {x["field"]: x for x in e.value.errors}


# ------------------------------------------------------------------ collecting / status
def test_collecting_until_enough_signal_is_available():
    ir, _ = two_channel(0.5, seconds=15)
    r = analyze_live({"ir": ir[:300], "fs": 100, "source": "file"})
    assert r["status"] == "collecting" and r["seconds_collected"] == 3.0 and r["seconds_needed"] == LIVE_CONFIG.min_window_seconds


# ------------------------------------------------------------------ SpO2: ratio of ratios
@pytest.mark.parametrize("r_target", [0.4, 0.5, 0.6, 0.8, 1.0])
def test_spo2_estimate_follows_the_ratio_of_ratios(r_target):
    ir, red = two_channel(r_target)
    out = analyze_live({"ir": ir, "red": red, "fs": 100, "source": "file"})
    assert out["spo2"]["ratio_r"] == pytest.approx(r_target, rel=0.03)
    assert out["spo2"]["estimate"] == pytest.approx(spo2_from_ratio(r_target), abs=0.6)
    assert out["spo2"]["available"] and "Uncalibrated" in out["spo2"]["note"]


def test_spo2_formula_is_the_documented_polynomial():
    assert spo2_from_ratio(0.5) == pytest.approx(-45.060 * 0.25 + 30.354 * 0.5 + 94.845)
    assert spo2_from_ratio(1.0) == pytest.approx(80.139)


def test_implausible_ratio_gives_no_estimate_instead_of_a_wrong_number():
    ir, red = two_channel(2.5)
    out = analyze_live({"ir": ir, "red": red, "fs": 100, "source": "file"})
    assert out["spo2"]["available"] is False and out["spo2"]["estimate"] is None and "out of the supported range" in out["spo2"]["note"]


def test_spo2_is_withheld_when_the_signal_is_poor():
    rng = np.random.default_rng(0)
    ir = (100000 + rng.normal(0, 800, 1500)).tolist()
    red = (80000 + rng.normal(0, 800, 1500)).tolist()
    out = analyze_live({"ir": ir, "red": red, "fs": 100, "source": "file"})
    assert out["signal_quality"] == "POOR" and out["spo2"]["estimate"] is None and "withheld" in out["spo2"]["note"]
    assert out["reliability_impact"]["state_hint"] == "ABSTAIN"


def test_camera_source_gives_no_spo2():
    ir, _ = two_channel(0.5)
    out = analyze_live({"ir": ir, "fs": 100, "source": "camera"})
    assert out["spo2"]["available"] is False and "one channel" in out["spo2"]["note"]


# ------------------------------------------------------------------ polarity
def test_reflective_sensor_polarity_is_corrected_by_default():
    ir, red = two_channel(0.5, invert=True)                      # what a MAX30102 reports: lower at systole
    good = analyze_live({"ir": ir, "red": red, "fs": 100, "source": "esp32"})
    wrong = analyze_live({"ir": ir, "red": red, "fs": 100, "source": "esp32", "invert": False})
    assert good["polarity_inverted"] is True and good["signal_quality"] == "GOOD" and good["sqi"] > wrong["sqi"] + 15
    assert good["spo2"]["estimate"] == pytest.approx(spo2_from_ratio(0.5), abs=0.6)       # AC/DC survive the flip
    assert good["pi_estimate"] == pytest.approx(1.0, rel=0.1)                                # PI = AC/DC x 100 = 1 %


def test_file_source_is_not_inverted_by_default():
    ir, _ = two_channel(0.5)
    assert analyze_live({"ir": ir, "fs": 100, "source": "file"})["polarity_inverted"] is False


# ------------------------------------------------------------------ irregular timestamps (camera)
def test_irregular_timestamps_are_resampled():
    rng = np.random.default_rng(1)
    t = np.cumsum(rng.uniform(0.025, 0.045, 480))                  # ~29 Hz with heavy jitter
    base = generate_demo_ppg("clean", fs=300, duration=float(t[-1]) + 1, seed=7)
    ir = np.interp(t, np.arange(len(base)) / 300, base)
    out = analyze_live({"ir": ir.tolist(), "t": t.tolist(), "source": "camera", "invert": False})
    assert out["status"] == "ok" and out["resampled"] is True and 25 <= out["fs_used"] <= 35
    assert out["pulse_rate_estimate"] == pytest.approx(72, abs=6)


def test_regular_timestamps_are_used_as_is():
    ir, _ = two_channel(0.5)
    t = (np.arange(len(ir)) / 100.0).tolist()
    out = analyze_live({"ir": ir, "t": t, "source": "file"})
    assert out["resampled"] is False and out["fs_used"] == pytest.approx(100.0, abs=0.1)


# ------------------------------------------------------------------ accelerometer
@pytest.mark.parametrize("std,state", [(0.005, "LOW"), (0.06, "MEDIUM"), (0.3, "HIGH")])
def test_accelerometer_sets_motion(std, state):
    ir, _ = two_channel(0.5)
    rng = np.random.default_rng(2)
    acc = np.column_stack([rng.normal(0, std, len(ir)), rng.normal(0, std, len(ir)), 1.0 + rng.normal(0, std, len(ir))])
    out = analyze_live({"ir": ir, "fs": 100, "source": "esp32", "accel": acc.tolist(), "invert": False})
    assert out["motion_state"] == state and out["motion_source"] == "accelerometer" and 0 <= out["motion_score"] <= 100
    assert (out["reliability_impact"]["state_hint"] == "ABSTAIN") == (state == "HIGH")


def test_accelerometer_magnitude_list_is_accepted():
    ir, _ = two_channel(0.5)
    out = analyze_live({"ir": ir, "fs": 100, "source": "esp32", "accel": [1.0] * len(ir), "invert": False})
    assert out["motion_state"] == "LOW"


# ------------------------------------------------------------------ validation
def test_validation_errors():
    ir, _ = two_channel(0.5)
    assert errs(fs=100)["ir"]["code"] == "missing"
    assert errs(ir=ir)["fs"]["code"] == "missing"
    assert errs(ir=ir[:10] + ["x"] + ir[11:], fs=100)["ir"]["code"] == "invalid_samples"
    assert errs(ir=ir, red=ir[:-5], fs=100)["red"]["code"] == "length_mismatch"
    assert errs(ir=ir, t=list(range(len(ir)))[::-1])["t"]["code"] == "not_increasing"
    assert errs(ir=ir, fs=100, source="drone")["source"]["code"] == "invalid_choice"
    assert errs(ir=ir, fs=-5)["fs"]["code"] == "invalid_type"
    assert errs(ir=[1.0] * (LIVE_CONFIG.max_samples + 1), fs=100)["ir"]["code"] == "too_long"
    assert errs(ir=ir, fs=100, accel=[[1, 2]] * len(ir))["accel"]["code"] == "invalid_samples"
    assert errs(ir=ir, fs=float("nan"))["fs"]["code"] == "invalid_type"


def test_constant_signal_is_poor_not_a_crash():
    out = analyze_live({"ir": [5000.0] * 1000, "fs": 100, "source": "esp32"})
    assert out["signal_quality"] == "POOR" and out["pulse_rate_estimate"] is None and out["pi_estimate"] is None


# ------------------------------------------------------------------ API
def test_api_shape_and_errors():
    ir, red = two_channel(0.5)
    r = client.post("/api/live/analyze", json={"ir": ir, "red": red, "fs": 100, "source": "esp32", "invert": False})
    assert r.status_code == 200
    b = r.json()
    for k in ("status", "sqi", "signal_quality", "motion_state", "motion_score", "pulse_rate_estimate", "pi_estimate", "spo2",
              "device", "fs_used", "t0", "filtered_ppg", "peaks", "reasons", "reliability_impact"):
        assert k in b
    assert "raw_ppg" not in b and b["device"] == "ESP32 + MAX30102"
    bad = client.post("/api/live/analyze", json={"ir": [], "fs": 100})
    assert bad.status_code == 422 and bad.json()["errors"][0]["field"] == "ir"
    assert client.post("/api/live/analyze", json={"ir": "abc", "fs": 100}).status_code == 422
    assert client.get("/api/live/config").json()["window_seconds"] == LIVE_CONFIG.window_seconds


def test_live_output_feeds_the_reliability_engine_end_to_end():
    ir, red = two_channel(0.5)
    live = client.post("/api/live/analyze", json={"ir": ir, "red": red, "fs": 100, "source": "esp32", "invert": False}).json()
    body = {"spo2": live["spo2"]["estimate"], "pi": live["pi_estimate"], "ita": 30, "signal_quality": live["signal_quality"],
            "motion": live["motion_state"], "device": live["device"], "sqi": live["sqi"], "signal_source": "live", "pi_source": "ppg"}
    r = client.post("/api/reliability/predict", json=body).json()
    assert r["reliability_state"] in ("GREEN", "AMBER") and r["device"] == "ESP32 + MAX30102" and r["pi_source"] == "ppg"


def test_virtual_simulation_source_is_labelled_as_such_and_analysed_exactly_like_a_real_board():
    ir, red = two_channel(0.5)
    body = {"ir": ir, "red": red, "fs": 100, "invert": False}
    real = client.post("/api/live/analyze", json={**body, "source": "esp32"}).json()
    virt = client.post("/api/live/analyze", json={**body, "source": "virtual"}).json()
    assert virt["device"] == "Virtual ESP32 + Virtual MAX30102 (simulation)" and real["device"] == "ESP32 + MAX30102"
    for k in ("sqi", "signal_quality", "motion_state", "pi_estimate", "pulse_rate_estimate", "spo2", "polarity_inverted"):
        assert virt[k] == real[k]                                        # same processing, same thresholds; only the label differs
    ok = {"spo2": 94, "pi": 2.0, "ita": 25, "signal_quality": "GOOD", "motion": "LOW"}
    a = client.post("/api/reliability/predict", json={**ok, "device": "ESP32 + MAX30102"}).json()
    b = client.post("/api/reliability/predict", json={**ok, "device": "Virtual ESP32 + Virtual MAX30102 (simulation)"})
    assert b.status_code == 200 and b.json()["reliability_state"] == a["reliability_state"]            # the device is recorded; it never changes the rules
    assert client.post("/api/reliability/predict", json={**ok, "device": "Some other board"}).status_code == 422


def test_pi_is_computed_from_the_infrared_channel_only():
    ir, red = two_channel(0.5)
    a = analyze_live({"ir": ir, "red": red, "fs": 100, "source": "esp32", "invert": False})
    red2 = [v * 1.7 + 3000 for v in red]                                   # different RED channel, same IR
    b = analyze_live({"ir": ir, "red": red2, "fs": 100, "source": "esp32", "invert": False})
    assert a["pi_estimate"] == b["pi_estimate"] and a["ac_ir"] == b["ac_ir"] and a["dc_ir"] == b["dc_ir"]
    assert a["pi_estimate"] == pytest.approx(100.0 * a["ac_ir"] / a["dc_ir"], rel=0.02)     # PI = AC_IR / DC_IR x 100 (rounded fields)
