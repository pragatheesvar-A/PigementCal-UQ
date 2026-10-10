"""Real-time analysis of a rolling window of sensor samples.

Sources: an ESP32 + MAX30102 streaming red and infrared (and optionally an accelerometer) over USB serial,
a phone camera (one channel), or a recorded file replayed as a stream. The client sends the most recent
window every second; this module returns signal quality, perfusion, motion, pulse rate and — when a red
channel is present — a ratio-of-ratios SpO2 ESTIMATE.

The SpO2 here uses generic, uncalibrated coefficients: it is a research estimate, never a measurement,
and it is withheld whenever the signal is POOR.
"""

import math

import numpy as np

from ..config import LIVE_CONFIG, LiveConfig, ReliabilityConfig, RELIABILITY_CONFIG
from .ppg import analyze_ppg, bandpass
from .validation import InputValidationError, _err

SOURCES = ("esp32", "virtual", "camera", "file")
DEVICE_FOR_SOURCE = {"esp32": "ESP32 + MAX30102", "virtual": "Virtual ESP32 + Virtual MAX30102 (simulation)", "camera": "Phone camera", "file": "Recorded file"}


def _array(values, name: str, errors: list[dict], required: bool = False):
    """Strictly numeric 1-D array (a live stream should never contain NaN/text); problems are reported."""
    if values is None:
        if required:
            errors.append(_err(name, "missing", f"{name} samples are required."))
        return None
    if not isinstance(values, list) or len(values) == 0:
        errors.append(_err(name, "missing", f"{name} must be a non-empty list of numbers."))
        return None
    out = np.full(len(values), np.nan)
    for i, v in enumerate(values):
        if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
            out[i] = v
    bad = int((~np.isfinite(out)).sum())
    if bad:
        errors.append(_err(name, "invalid_samples", f"{name} contains {bad} invalid (non-numeric or non-finite) sample(s)."))
        return None
    return out


def _orient(x: np.ndarray, invert: bool) -> np.ndarray:
    """Flip about the mean so systolic peaks point up while the DC level (needed for PI) is preserved."""
    return 2.0 * x.mean() - x if invert else x


def _ac_dc(x: np.ndarray, fs: float) -> tuple[float, float]:
    f = bandpass(x, fs)
    return float(np.percentile(f, 95) - np.percentile(f, 5)), float(np.mean(x))   # same AC definition as the PI estimate


def spo2_from_ratio(r: float, cfg: LiveConfig = LIVE_CONFIG) -> float:
    a, b, c = cfg.spo2_poly
    return a * r * r + b * r + c


def _motion_from_accel(acc: np.ndarray, cfg: LiveConfig) -> tuple[float, str]:
    """acc: (n,) magnitude or (n,3) in g. Score from the std of |a| over the window."""
    mag = np.linalg.norm(acc, axis=1) if acc.ndim == 2 else np.abs(acc)
    s = float(np.std(mag))
    score = round(100.0 * min(1.0, s / cfg.accel_high_from_g), 1)
    state = "LOW" if s < cfg.accel_low_below_g else "HIGH" if s >= cfg.accel_high_from_g else "MEDIUM"
    return score, state


def analyze_live(raw: dict, cfg: LiveConfig = LIVE_CONFIG, rcfg: ReliabilityConfig = RELIABILITY_CONFIG) -> dict:
    errors: list[dict] = []
    source = raw.get("source") or "esp32"
    if source not in SOURCES:
        errors.append(_err("source", "invalid_choice", f"source must be one of: {', '.join(SOURCES)}."))
    ir = _array(raw.get("ir"), "ir", errors, required=True)
    red = _array(raw.get("red"), "red", errors)
    t = _array(raw.get("t"), "t", errors)
    acc_raw = raw.get("accel")
    acc = None
    if acc_raw is not None:
        try:
            acc = np.asarray(acc_raw, dtype=float)
            if acc.ndim not in (1, 2) or (acc.ndim == 2 and acc.shape[1] != 3) or not np.isfinite(acc).all():
                raise ValueError
        except (TypeError, ValueError):
            errors.append(_err("accel", "invalid_samples", "accel must be numbers: either a magnitude per sample or [ax, ay, az] in g."))
            acc = None
    if ir is not None:
        for name, arr in (("red", red), ("t", t), ("accel", acc)):
            if arr is not None and len(arr) != len(ir):
                errors.append(_err(name, "length_mismatch", f"{name} has {len(arr)} samples but ir has {len(ir)}."))
    fs = raw.get("fs")
    if fs is not None and (isinstance(fs, bool) or not isinstance(fs, (int, float)) or not math.isfinite(fs) or fs <= 0):
        errors.append(_err("fs", "invalid_type", "fs must be a positive number."))
    if t is None and fs is None:
        errors.append(_err("fs", "missing", "Provide either per-sample times (t, in seconds) or the sampling rate (fs)."))
    if ir is not None and len(ir) > cfg.max_samples:
        errors.append(_err("ir", "too_long", f"Window is too long (maximum {cfg.max_samples} samples)."))
    if errors:
        raise InputValidationError(errors)

    resampled = False
    if t is not None:
        if len(t) < 2 or np.any(np.diff(t) <= 0):
            raise InputValidationError([_err("t", "not_increasing", "Sample times must be strictly increasing.")])
        dt = np.diff(t)
        fs_est = 1.0 / float(np.median(dt))
        jitter = float(np.std(dt) / np.mean(dt))
        if jitter > 0.05 or abs(fs_est - round(fs_est)) > 0.5 and jitter > 0.01:
            fs_use = float(min(round(fs_est), cfg.resample_fs_max))
            grid = np.arange(t[0], t[-1], 1.0 / fs_use)
            ir = np.interp(grid, t, ir)
            red = np.interp(grid, t, red) if red is not None else None
            if acc is not None:
                acc = (np.stack([np.interp(grid, t, acc[:, k]) for k in range(3)], axis=1) if acc.ndim == 2 else np.interp(grid, t, acc))
            t0, resampled = float(t[0]), True
        else:
            fs_use, t0 = fs_est, float(t[0])
    else:
        fs_use, t0 = float(fs), 0.0

    n_keep = int(cfg.window_seconds * fs_use)
    if len(ir) > n_keep:                     # analyze the most recent window only
        cut = len(ir) - n_keep
        t0 += cut / fs_use
        ir = ir[cut:]
        red = red[cut:] if red is not None else None
        acc = acc[cut:] if acc is not None else None
    seconds = len(ir) / fs_use
    if seconds < cfg.min_window_seconds:
        return {"status": "collecting", "seconds_collected": round(seconds, 1), "seconds_needed": cfg.min_window_seconds,
                "source": source, "fs_used": round(fs_use, 2)}

    invert = raw.get("invert")
    invert = cfg.invert_default.get(source, False) if invert is None else bool(invert)
    ir_o = _orient(ir, invert)

    motion_override = score_override = None
    if acc is not None:
        score_override, motion_override = _motion_from_accel(acc, cfg)
    res = analyze_ppg(ir_o.tolist(), fs_use, motion_override)
    res.pop("raw_ppg", None)
    if acc is not None:
        res["motion_score"], res["motion_source"] = score_override, "accelerometer"

    spo2 = {"available": False, "estimate": None, "ratio_r": None, "note": cfg.spo2_note}
    if red is None:
        spo2["note"] = "SpO₂ needs both red and infrared channels; this source provides one channel."
    elif res["signal_quality"] == "POOR":
        spo2["note"] = "SpO₂ estimate withheld: signal quality is POOR."
    else:
        red_o = _orient(red, invert)
        ac_i, dc_i = _ac_dc(ir_o, fs_use)
        ac_r, dc_r = _ac_dc(red_o, fs_use)
        if min(ac_i, ac_r, dc_i, dc_r) <= 0:
            spo2["note"] = "SpO₂ estimate unavailable: non-positive AC or DC component."
        else:
            r = (ac_r / dc_r) / (ac_i / dc_i)
            est = spo2_from_ratio(r, cfg)
            spo2["ratio_r"] = round(r, 4)
            if rcfg.spo2_min <= est <= rcfg.spo2_max:
                spo2.update(available=True, estimate=round(est, 1))
            else:
                spo2["note"] = f"SpO₂ estimate out of the supported range ({est:.1f}% from R = {r:.3f}); likely a sensor-contact or calibration issue."
    return {"status": "ok", **res, "spo2": spo2, "source": source, "device": DEVICE_FOR_SOURCE[source],
            "fs_used": round(fs_use, 3), "t0": round(t0, 4), "window_seconds": round(seconds, 2),
            "resampled": resampled, "polarity_inverted": invert}
