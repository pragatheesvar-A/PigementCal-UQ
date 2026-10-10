"""TEST-ONLY synthetic PPG used to unit-test signal processing with known ground truth.

This is not part of the application: no page, endpoint or result uses it."""

import numpy as np

KINDS = {
    "clean": "Clean pulse",
    "moderate": "Baseline drift + noise",
    "noisy": "Heavy noise",
    "motion": "Motion artifacts",
    "nopulse": "No usable pulse",
}

# Default seeds. The "moderate" seed was chosen so the demo illustrates the MODERATE state:
# for mildly noisy signals the SQI varies with the noise realisation (see tests).
DEMO_SEEDS = {"moderate": 3}
DEFAULT_SEED = 7

DC = 100.0  # arbitrary baseline level (unitless)
AC = 2.0    # arbitrary pulse amplitude (unitless)


def generate_demo_ppg(kind: str = "clean", fs: float = 100.0, duration: float = 10.0,
                      seed: int | None = None, heart_rate: float = 72.0) -> np.ndarray:
    """Deterministic PPG-like waveform: systolic peak + dicrotic bump per beat.

    Beat phase is integrated from a slowly varying heart rate so inter-beat intervals
    are mildly irregular (as in real signals).
    """
    if kind not in KINDS:
        raise ValueError(f"Unknown demo signal kind: {kind}")
    rng = np.random.default_rng(DEMO_SEEDS.get(kind, DEFAULT_SEED) if seed is None else seed)
    n = int(round(fs * duration))
    t = np.arange(n) / fs
    inst_hz = heart_rate / 60.0 * (1.0 + 0.03 * np.sin(2 * np.pi * 0.1 * t + 0.5))
    phase = (np.cumsum(inst_hz) / fs) % 1.0
    beat = np.exp(-(((phase - 0.18) / 0.07) ** 2)) + 0.35 * np.exp(-(((phase - 0.45) / 0.10) ** 2))
    beat = beat / beat.max()

    wander_amp, noise_sd, pulse_gain = {
        "clean": (0.15, 0.03, 1.0),
        "moderate": (0.5, 0.15, 1.0),
        "noisy": (0.5, 0.9, 1.0),
        "motion": (0.3, 0.2, 1.0),
        "nopulse": (0.3, 0.12, 0.0),
    }[kind]
    x = DC + AC * pulse_gain * beat
    x += AC * wander_amp * np.sin(2 * np.pi * 0.15 * t + 1.0)
    x += AC * noise_sd * rng.standard_normal(n)

    if kind == "motion":
        # Two bursts of large, low-frequency movement artifacts plus a baseline shift
        for start in (0.2, 0.6):
            i0 = int(start * n)
            i1 = min(n, i0 + int(1.8 * fs))
            tt = np.arange(i1 - i0) / fs
            x[i0:i1] += AC * 4.0 * np.sin(2 * np.pi * (1.5 + rng.random()) * tt) * np.hanning(i1 - i0)
        x[int(0.45 * n):] += AC * 1.5
    return x


def reflective_recording(seconds=40, fs=100, r=0.5, seed=7, ai_rel=0.01, dc_ir=100000.0, dc_red=80000.0, motion_std=0.005):
    """TEST-ONLY: what an ESP32 + MAX30102 Live Monitor CSV looks like (t_s, ir, red, ax, ay, az), with a chosen ratio of
    ratios R so the SpO2 estimate has a known expected value. Reflective polarity (counts fall at systole)."""
    import pandas as pd
    from app.services.ppg import bandpass
    x = generate_demo_ppg("clean", fs=fs, duration=seconds, seed=seed)
    p = x - x.mean()
    f = bandpass(p, fs)
    p = p / (np.percentile(f, 95) - np.percentile(f, 5))
    n = len(p)
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "t_s": np.round(np.arange(n) / fs, 4),
        "ir": np.round(dc_ir - ai_rel * dc_ir * p).astype(int),
        "red": np.round(dc_red - r * ai_rel * dc_red * p).astype(int),
        "ax": np.round(rng.normal(0, motion_std, n), 4), "ay": np.round(rng.normal(0, motion_std, n), 4),
        "az": np.round(1 + rng.normal(0, motion_std, n), 4),
    })
