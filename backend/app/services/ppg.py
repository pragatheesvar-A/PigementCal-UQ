"""PPG preprocessing, pulse detection and signal-quality index (lightweight DSP, no ML).

All thresholds are default values from config.SignalConfig - not clinically validated.
Pulse rate here is a signal-processing estimate, not a clinical heart-rate measurement.
"""

import math

import numpy as np
from scipy import signal as sps
from scipy import stats

from ..config import SIGNAL_CONFIG, SignalConfig
from .features import classify_pi
from .validation import InputValidationError, _err

MOTION_LEVELS = ("LOW", "MEDIUM", "HIGH")


def clean_ppg(values, cfg: SignalConfig = SIGNAL_CONFIG) -> tuple[np.ndarray, int]:
    """Invalid-value handling: non-numeric / NaN / inf samples are linearly interpolated and
    COUNTED (never silently dropped). Too many invalid samples -> error, not guesswork."""
    if values is None or len(values) == 0:
        raise InputValidationError([_err("ppg", "missing", "PPG signal is empty. Provide numeric samples.")])
    if len(values) > cfg.max_samples:
        raise InputValidationError([_err("ppg", "too_long", f"PPG signal is too long (maximum {cfg.max_samples} samples).")])
    arr = np.full(len(values), np.nan)
    for i, v in enumerate(values):
        if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
            arr[i] = v
    bad = ~np.isfinite(arr)
    n_bad = int(bad.sum())
    if n_bad == len(arr) or n_bad / len(arr) > cfg.max_invalid_fraction:
        raise InputValidationError([_err("ppg", "too_many_invalid",
            f"{n_bad} of {len(arr)} samples are invalid (non-numeric, NaN or infinite); at most "
            f"{cfg.max_invalid_fraction:.0%} are tolerated. Please check the file.")])
    if n_bad:
        idx = np.arange(len(arr))
        arr[bad] = np.interp(idx[bad], idx[~bad], arr[~bad])
    return arr, n_bad


def bandpass(x: np.ndarray, fs: float, cfg: SignalConfig = SIGNAL_CONFIG) -> np.ndarray:
    """Zero-phase Butterworth band-pass (0.5-5 Hz by default)."""
    high = min(cfg.band_high, 0.45 * fs)
    sos = sps.butter(cfg.filter_order, [cfg.band_low, high], btype="bandpass", fs=fs, output="sos")
    return sps.sosfiltfilt(sos, x)


def detect_pulses(f: np.ndarray, fs: float, cfg: SignalConfig = SIGNAL_CONFIG) -> np.ndarray:
    sd = float(np.std(f))
    if sd < 1e-9:
        return np.array([], dtype=int)
    peaks, _ = sps.find_peaks(f, distance=max(1, int(cfg.min_peak_distance_s * fs)),
                              prominence=cfg.peak_prominence_std * sd)
    return peaks


def _clip01(v: float) -> float:
    return float(min(1.0, max(0.0, v)))


def compute_sqi(raw: np.ndarray, f: np.ndarray, peaks: np.ndarray, fs: float,
                cfg: SignalConfig = SIGNAL_CONFIG) -> dict:
    """SQI 0-100 = weighted mean of four 0-1 components.

    skewness   - clean PPG pulses are asymmetric (positive skew); noise pushes skew to ~0.
    noise      - power above the pulse band relative to in-band power (Welch PSD of raw).
    amplitude  - beat-to-beat peak-height variability (CV).
    regularity - inter-beat-interval variability (CV).
    A signal with no detectable pulsatile structure scores 0 on all components.
    """
    comps = {"skewness": 0.0, "noise": 0.0, "amplitude": 0.0, "regularity": 0.0}
    info = {"skewness_value": 0.0, "hf_ratio": None, "amplitude_cv": None, "ibi_cv": None}
    if float(np.std(f)) >= 1e-9 and len(peaks) >= 3:
        skew = float(stats.skew(f))
        info["skewness_value"] = skew
        comps["skewness"] = _clip01(skew / cfg.skew_full)

        freqs, psd = sps.welch(raw - np.mean(raw), fs=fs, nperseg=min(len(raw), int(4 * fs)))
        inband = psd[(freqs >= cfg.band_low) & (freqs <= cfg.band_high)].sum()
        hf = psd[freqs > cfg.band_high].sum()
        if inband > 0:
            ratio = float(hf / inband)
            info["hf_ratio"] = ratio
            comps["noise"] = _clip01(1.0 - ratio / cfg.hf_ratio_zero)

        heights = f[peaks]
        if abs(np.mean(heights)) > 1e-9:
            cv = float(np.std(heights) / abs(np.mean(heights)))
            info["amplitude_cv"] = cv
            comps["amplitude"] = _clip01(1.0 - cv / cfg.amp_cv_zero)

        ibi = np.diff(peaks) / fs
        cv_ibi = float(np.std(ibi) / np.mean(ibi))
        info["ibi_cv"] = cv_ibi
        comps["regularity"] = _clip01(1.0 - cv_ibi / cfg.ibi_cv_zero)
    sqi = 100.0 * sum(cfg.weights[k] * v for k, v in comps.items())
    return {"sqi": round(sqi, 1), "components": {k: round(100 * v, 1) for k, v in comps.items()}, "info": info}


def classify_sqi(sqi: float, cfg: SignalConfig = SIGNAL_CONFIG) -> str:
    """Default SQI thresholds - not clinically validated."""
    return "GOOD" if sqi >= cfg.sqi_good_min else "MODERATE" if sqi >= cfg.sqi_moderate_min else "POOR"


def estimate_motion(f: np.ndarray, fs: float, cfg: SignalConfig = SIGNAL_CONFIG) -> tuple[float, str]:
    """Motion score 0-100 from the fraction of 1-s windows whose amplitude is a strong outlier.
    Placeholder for accelerometer integration."""
    w = int(cfg.motion_window_s * fs)
    n_win = len(f) // w
    if n_win < 3:
        return 0.0, "LOW"
    p2p = np.array([np.ptp(f[i * w:(i + 1) * w]) for i in range(n_win)])
    med = float(np.median(p2p))
    if med < 1e-9:
        return 0.0, "LOW"
    frac = float(np.mean(p2p > cfg.motion_outlier_factor * med))
    score = round(100.0 * _clip01(frac / cfg.motion_fraction_full), 1)
    state = "LOW" if score < cfg.motion_low_below else "HIGH" if score >= cfg.motion_high_from else "MEDIUM"
    return score, state


def _explain(quality: str, motion: str, comps: dict, n_bad: int, n_peaks: int) -> list[dict]:
    r = []
    if quality == "GOOD":
        r.append(("info", "Periodic pulse structure is clearly visible and estimated signal quality is favorable."))
    elif quality == "MODERATE":
        r.append(("warning", "Noise or baseline variation is present."))
    else:
        r.append(("critical", "Signal contains insufficient usable pulse information."))
    if n_peaks < 3:
        r.append(("critical", "Fewer than three pulse peaks were detected, so regularity cannot be assessed."))
    names = {"skewness": "Pulse-shape (skewness) component is low.", "noise": "High-frequency noise is elevated.",
             "amplitude": "Beat-to-beat amplitude varies strongly.", "regularity": "Pulse timing is irregular."}
    if quality != "GOOD":
        r += [("warning", names[k]) for k, v in comps.items() if v < 50]
    if motion != "LOW":
        r.append(("critical" if motion == "HIGH" else "warning",
                  "Motion-related artifacts may reduce signal reliability."))
    if n_bad:
        r.append(("warning", f"{n_bad} invalid sample(s) were interpolated."))
    return [{"severity": s, "text": t} for s, t in r]


def reliability_impact(quality: str, motion: str) -> dict:
    """How this signal feeds the reliability engine (mirrors its ABSTAIN/AMBER rules)."""
    if quality == "POOR" or motion == "HIGH":
        return {"state_hint": "ABSTAIN",
                "text": "Signal quality is insufficient for a reliable assessment. Consider reacquiring the signal."}
    if quality == "MODERATE" or motion == "MEDIUM":
        return {"state_hint": "AMBER", "text": "Reliability can be AMBER or worse; uncertainty is increased."}
    return {"state_hint": "GREEN",
            "text": "Reliability can remain GREEN if other conditions (perfusion, interval width) are favorable."}


def analyze_ppg(ppg, sampling_rate, motion: str | None = None, cfg: SignalConfig = SIGNAL_CONFIG) -> dict:
    errors: list[dict] = []
    fs = sampling_rate
    if fs is None:
        errors.append(_err("sampling_rate", "missing", "Sampling rate is required."))
    elif isinstance(fs, bool) or not isinstance(fs, (int, float)) or not math.isfinite(fs) or not (cfg.fs_min <= fs <= cfg.fs_max):
        errors.append(_err("sampling_rate", "out_of_range",
                           f"Sampling rate must be between {cfg.fs_min:g} and {cfg.fs_max:g} Hz."))
    if ppg is None or len(ppg) == 0:
        errors.append(_err("ppg", "missing", "PPG signal is empty. Provide numeric samples."))
    manual = None
    if motion is not None and str(motion).strip():
        manual = str(motion).strip().upper()
        if manual not in MOTION_LEVELS:
            errors.append(_err("motion", "invalid_choice", f"Motion must be one of: {', '.join(MOTION_LEVELS)}."))
    if errors:
        raise InputValidationError(errors)

    raw, n_bad = clean_ppg(ppg, cfg)
    if len(raw) < cfg.min_seconds * fs:
        raise InputValidationError([_err("ppg", "too_short",
            f"PPG signal is too short: at least {cfg.min_seconds:g} s ({int(cfg.min_seconds * fs)} samples at {fs:g} Hz) are needed.")])

    f = bandpass(raw, fs, cfg)
    peaks = detect_pulses(f, fs, cfg)
    q = compute_sqi(raw, f, peaks, fs, cfg)
    quality = classify_sqi(q["sqi"], cfg)

    pulse_rate = None  # withheld for POOR signals: peaks are not trustworthy
    if len(peaks) >= 3 and quality != "POOR":
        pr = 60.0 / float(np.median(np.diff(peaks) / fs))
        if cfg.pulse_rate_min <= pr <= cfg.pulse_rate_max:
            pulse_rate = round(pr, 1)

    est_score, est_state = estimate_motion(f, fs, cfg)
    motion_state = manual or est_state
    mean_raw = float(np.mean(raw))
    ac = float(np.percentile(f, 95) - np.percentile(f, 5))
    # PI = AC/DC x 100. AC = 5th-95th percentile range of the band-passed signal (robust pulsatile
    # amplitude); DC = mean of the cleaned raw signal. Withheld for POOR signals or non-positive DC.
    pi_est = round(100.0 * ac / mean_raw, 4) if mean_raw > 0 and quality != "POOR" else None

    return {
        "raw_ppg": raw.tolist(),
        "filtered_ppg": f.tolist(),
        "peaks": peaks.tolist(),
        "sampling_rate": float(fs),
        "sqi": q["sqi"],
        "sqi_components": q["components"],
        "signal_quality": quality,
        "motion_score": est_score,
        "motion_state": motion_state,
        "motion_source": "manual" if manual else "estimated",
        "estimated_motion_state": est_state,
        "pulse_rate_estimate": pulse_rate,
        "pulse_rate_note": "Signal-processing estimate — not a clinical heart-rate measurement.",
        "pi_estimate": pi_est,
        "perfusion_state": classify_pi(pi_est).upper() if pi_est is not None else None,
        "ac_ir": round(ac, 6),
        "dc_ir": round(mean_raw, 6),
        "metrics": {
            "sampling_rate_hz": float(fs),
            "n_samples": len(raw),
            "duration_s": round(len(raw) / fs, 2),
            "mean": round(mean_raw, 4),
            "std": round(float(np.std(raw)), 4),
            "amplitude_min": round(float(raw.min()), 4),
            "amplitude_max": round(float(raw.max()), 4),
            "amplitude_range": round(float(np.ptp(raw)), 4),
            "filtered_amplitude_range": round(float(np.ptp(f)), 4),
            "n_peaks": int(len(peaks)),
            "invalid_samples": n_bad,
            "skewness": round(q["info"]["skewness_value"], 3),
        },
        "reasons": _explain(quality, motion_state, q["components"], n_bad, len(peaks)),
        "reliability_impact": reliability_impact(quality, motion_state),
        "thresholds": {"sqi_good_min": cfg.sqi_good_min, "sqi_moderate_min": cfg.sqi_moderate_min,
                       "label": "Default SQI thresholds — not clinically validated."},
    }
