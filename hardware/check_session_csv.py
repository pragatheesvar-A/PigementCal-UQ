"""Quality check for a session CSV saved by the Live Monitor (participant_id, session_id, timestamp, red, ir, accelerometer_x/y/z).

    python hardware/check_session_csv.py P001_P001_S01.csv [--fs 100]

It only REPORTS what the file contains. It does not repair, resample or invent samples, and it says nothing about medical accuracy.
Exit code 0 = no problems found, 1 = problems found, 2 = the file could not be read.
"""

import argparse
import sys

import numpy as np
import pandas as pd

REQUIRED = ["participant_id", "session_id", "timestamp", "red", "ir"]
ADC_MAX = 262143          # 18-bit MAX30102 ADC full scale


def check(df: pd.DataFrame, fs: float | None = None) -> dict:
    """Return {'n', 'duration_s', 'fs_measured', 'problems': [...], 'notes': [...]} for a session table."""
    problems, notes = [], []
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        return {"n": int(len(df)), "problems": [f"missing column(s): {', '.join(missing)}"], "notes": [], "duration_s": None, "fs_measured": None}
    n = int(len(df))
    if n == 0:
        return {"n": 0, "problems": ["the file has no samples"], "notes": [], "duration_s": None, "fs_measured": None}
    for c in ("timestamp", "red", "ir"):
        bad = int(pd.to_numeric(df[c], errors="coerce").isna().sum())
        if bad:
            problems.append(f"{bad} row(s) have a missing or non-numeric {c}")
    t = pd.to_numeric(df["timestamp"], errors="coerce").to_numpy(float)
    red, ir = pd.to_numeric(df["red"], errors="coerce").to_numpy(float), pd.to_numeric(df["ir"], errors="coerce").to_numpy(float)
    for col in ("participant_id", "session_id"):
        if df[col].nunique() != 1:
            problems.append(f"{col} is not constant ({df[col].nunique()} different values)")
    dt = np.diff(t[np.isfinite(t)])
    duration = float(np.nanmax(t) - np.nanmin(t)) if np.isfinite(t).any() else None
    fs_meas = float(1.0 / np.median(dt)) if len(dt) and np.median(dt) > 0 else None
    if (dt <= 0).any():
        problems.append(f"{int((dt <= 0).sum())} timestamp(s) are repeated or go backwards")
    ref = fs or fs_meas
    if ref and len(dt):
        gaps = dt[dt > 1.5 / ref]
        if len(gaps):
            lost = int(round(float(np.sum(gaps * ref - 1))))
            problems.append(f"{len(gaps)} gap(s) in the stream (about {lost} missing sample(s); longest {gaps.max():.3f} s)")
    for name, x in (("ir", ir), ("red", red)):
        ok = x[np.isfinite(x)]
        if len(ok) < 2:
            continue
        if np.ptp(ok) == 0:
            problems.append(f"{name} is flat (constant value {ok[0]:g}): no signal")
        elif np.std(ok) < 1e-3 * max(abs(np.mean(ok)), 1):
            notes.append(f"{name} varies very little (SD {np.std(ok):.3g}); check finger placement")
        if (ok >= ADC_MAX).mean() > 0.01:
            problems.append(f"{name} is saturated (at the 18-bit maximum) in {100 * (ok >= ADC_MAX).mean():.1f}% of samples; lower the LED brightness")
        if (ok <= 0).mean() > 0.01:
            problems.append(f"{name} is zero or negative in {100 * (ok <= 0).mean():.1f}% of samples")
        if np.mean(ok) < 30000:
            notes.append(f"{name} mean is {np.mean(ok):.0f}: usually means no finger on the sensor")
    if fs and fs_meas and abs(fs_meas - fs) / fs > 0.05:
        problems.append(f"measured rate {fs_meas:.1f} Hz differs from the expected {fs:g} Hz by more than 5%")
    acc = [c for c in ("accelerometer_x", "accelerometer_y", "accelerometer_z") if c in df.columns]
    if acc and df[acc].isna().all().all():
        notes.append("accelerometer columns are empty (no accelerometer)")
    elif acc and df[acc].isna().any().any():
        problems.append("some accelerometer cells are empty")
    return {"n": n, "duration_s": duration, "fs_measured": fs_meas, "problems": problems, "notes": notes}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("csv")
    ap.add_argument("--fs", type=float, default=None, help="expected sampling rate in Hz (default: measured from the timestamps)")
    a = ap.parse_args(argv)
    try:
        df = pd.read_csv(a.csv, comment="#")           # '#' lines are metadata (e.g. the virtual-simulation marker), not samples
    except (OSError, ValueError) as e:
        print(f"Could not read {a.csv}: {e}")
        return 2
    r = check(df, a.fs)
    print(f"samples: {r['n']}   duration: {r['duration_s'] if r['duration_s'] is None else round(r['duration_s'], 2)} s   measured rate: {r['fs_measured'] if r['fs_measured'] is None else round(r['fs_measured'], 1)} Hz")
    for p in r["problems"]:
        print("PROBLEM:", p)
    for n in r["notes"]:
        print("note:", n)
    print("RESULT:", "no problems found (this says nothing about medical accuracy)" if not r["problems"] else f"{len(r['problems'])} problem(s) found")
    return 1 if r["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
