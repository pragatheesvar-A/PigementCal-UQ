"""Session-CSV quality checker (hardware/check_session_csv.py). Test-only signals; no hardware was involved."""

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

spec = importlib.util.spec_from_file_location("check_session_csv", Path(__file__).resolve().parents[2] / "hardware" / "check_session_csv.py")
chk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(chk)


def session(n=500, fs=100, seed=0):
    rng = np.random.default_rng(seed)
    t = np.arange(n) / fs
    return pd.DataFrame({"participant_id": "P001", "session_id": "P001_S01", "timestamp": t.round(3),
                         "red": (80000 + 500 * np.sin(2 * np.pi * 1.2 * t) + rng.normal(0, 20, n)).round(), "ir": (100000 + 700 * np.sin(2 * np.pi * 1.2 * t) + rng.normal(0, 20, n)).round(),
                         "accelerometer_x": np.nan, "accelerometer_y": np.nan, "accelerometer_z": np.nan})


def test_clean_session_has_no_problems():
    r = chk.check(session(), fs=100)
    assert r["problems"] == [] and r["n"] == 500 and abs(r["fs_measured"] - 100) < 1
    assert any("accelerometer" in n for n in r["notes"])


def test_detects_gaps_flatline_saturation_and_repeated_timestamps():
    d = session().drop(index=range(100, 120)).reset_index(drop=True)
    assert any("gap" in p and "20 missing" in p for p in chk.check(d, fs=100)["problems"])
    f = session(); f["ir"] = 100000.0
    assert any("ir is flat" in p for p in chk.check(f)["problems"])
    s = session(); s.loc[:50, "red"] = chk.ADC_MAX
    assert any("red is saturated" in p for p in chk.check(s)["problems"])
    r = session(); r.loc[10, "timestamp"] = r.loc[9, "timestamp"]
    assert any("repeated or go backwards" in p for p in chk.check(r)["problems"])


def test_missing_columns_and_empty_files_are_reported_not_guessed():
    assert "missing column(s): ir" in chk.check(session().drop(columns=["ir"]))["problems"][0]
    assert chk.check(session().iloc[:0])["problems"] == ["the file has no samples"]


def test_non_constant_ids_and_nonnumeric_values_are_flagged():
    d = session(); d.loc[5, "participant_id"] = "P002"; d["red"] = d["red"].astype(object); d.loc[7, "red"] = "abc"
    p = " ".join(chk.check(d)["problems"])
    assert "participant_id is not constant" in p and "non-numeric red" in p


def test_command_line_exit_codes(tmp_path):
    good, bad = tmp_path / "good.csv", tmp_path / "bad.csv"
    session().to_csv(good, index=False)
    f = session(); f["ir"] = 5.0
    f.to_csv(bad, index=False)
    assert chk.main([str(good)]) == 0 and chk.main([str(bad)]) == 1 and chk.main([str(tmp_path / "missing.csv")]) == 2
