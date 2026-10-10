"""Own-data collection: staging uploads, matching, validation and research-dataset generation.

All data here is test-only and lives in temporary folders. Recordings come from tests/synthetic.py with a KNOWN ratio of
ratios, so the SpO2 estimate has a known expected value. Nothing is read from or written to real project data.
"""

import json

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.collection import ingest, merge, store
from app.collection.rules import CollectionError, id_problem, parse_times
from app.main import app
from app.ml.paths import Paths, set_paths
from app.services.live import spo2_from_ratio
from app.services.pigmentation import compute_ita
from tests.synthetic import reflective_recording

EXPECTED_SPO2 = spo2_from_ratio(0.5)
ATT = {"attested_real": True}


def make_paths(root) -> Paths:
    return Paths(processed=root / "processed", raw=root / "raw", models=root / "models", results=root / "results")


@pytest.fixture
def paths(tmp_path):
    return make_paths(tmp_path)


def csv(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode()


def ppg(r=0.5, seconds=40, seed=7) -> bytes:
    return csv(reflective_recording(seconds=seconds, r=r, seed=seed))


def add(paths, kind, data, **params):
    return ingest.add_upload(kind, data, {**ATT, "filename": f"{kind}.csv", **params}, paths)


def err(paths, kind, data, **params) -> CollectionError:
    with pytest.raises(CollectionError) as e:
        add(paths, kind, data, **params)
    return e.value


def stage_study(paths, pid="P001", sid="P001_S01", ref_times=(15.0, 30.0), refs=(97.5, 96.0), lab=(62, 12, 18), seed=7):
    """One participant: PPG recording (40 s -> 6 windows ending at 10,15,...,35 s), two reference SaO2 values, L*a*b*."""
    add(paths, "ppg", ppg(seed=seed), participant_id=pid, session_id=sid)
    add(paths, "reference", csv(pd.DataFrame({"participant_id": pid, "session_id": sid, "timestamp": list(ref_times), "sao2": list(refs)})))
    add(paths, "pigmentation", csv(pd.DataFrame({"participant_id": [pid], "session_id": [sid], "L": [lab[0]], "a": [lab[1]], "b": [lab[2]]})))


# =================================================================== uploads: PPG / Live Monitor CSV
def test_live_monitor_csv_is_staged_as_analysis_windows(paths):
    r = add(paths, "ppg", ppg(), participant_id="P001", session_id="P001_S01")
    s = r["upload"]["summary"]
    assert r["status"] == "staged" and s["windows"] == 6 and s["has_red"] and s["has_accelerometer"] and s["estimated_fs_hz"] == pytest.approx(100, abs=1)
    assert s["sessions"][0]["good"] == 6 and s["spo2_from"] == "red/IR estimate"
    w = store.table(paths, "ppg")
    assert list(w["signal_quality"].unique()) == ["GOOD"] and set(w["participant_id"]) == {"P001"} and set(w["session_id"]) == {"P001_S01"}
    assert w["spo2"].astype(float).between(EXPECTED_SPO2 - 0.8, EXPECTED_SPO2 + 0.8).all()
    assert w["spo2_source"].iloc[0] == "uncalibrated red/IR estimate" and (w["motion_state"] == "LOW").all()
    assert w["device_id"].iloc[0] == "ESP32 + MAX30102" and w["time_basis"].iloc[0] == "relative"
    assert list(w["timestamp_s"].astype(float).round(0)) == [10, 15, 20, 25, 30, 35]


def test_real_data_attestation_is_required(paths):
    e = err(paths, "ppg", ppg(), participant_id="P001", session_id="S1", attested_real=False)
    assert e.code == "not_attested"
    assert store.manifest(paths) == []


def test_exact_same_file_cannot_be_uploaded_twice(paths):
    add(paths, "ppg", ppg(), participant_id="P001", session_id="P001_S01")
    assert err(paths, "ppg", ppg(), participant_id="P002", session_id="P002_S01").code == "duplicate_file"


@pytest.mark.parametrize("data,code", [(b"", "empty_file"), (b"a,b\n", "unreadable_csv"), (b"\xff\xfe\x00bad", "unreadable_csv")])
def test_unreadable_uploads(paths, data, code):
    assert err(paths, "ppg", data, participant_id="P001", session_id="S1").code == code


def test_ppg_with_timestamps_in_milliseconds_and_no_red_uses_the_device_spo2_column(paths):
    df = reflective_recording(seconds=30).drop(columns=["red"])
    df["t_ms"] = (df.pop("t_s") * 1000).astype(int)
    df["spo2"] = 96.5
    r = add(paths, "ppg", csv(df), participant_id="P001", session_id="P001_S01")
    assert r["upload"]["summary"]["spo2_from"] == "device column" and r["upload"]["summary"]["estimated_fs_hz"] == pytest.approx(100, abs=1)
    w = store.table(paths, "ppg")
    assert (w["spo2"].astype(float) == 96.5).all() and w["spo2_source"].iloc[0] == "device column"


def test_ppg_without_time_column_needs_a_sampling_rate(paths):
    df = reflective_recording(seconds=30).drop(columns=["t_s"])
    assert err(paths, "ppg", csv(df), participant_id="P001", session_id="S1").code == "no_time"
    assert add(paths, "ppg", csv(df), participant_id="P001", session_id="S1", fs=100)["upload"]["summary"]["windows"] > 0


def test_ppg_too_short_or_with_bad_samples_is_rejected_clearly(paths):
    assert err(paths, "ppg", csv(reflective_recording(seconds=5)), participant_id="P001", session_id="S1").code == "no_windows"
    bad = reflective_recording(seconds=30).astype({"ir": float})
    bad.loc[100, "ir"] = np.nan
    assert err(paths, "ppg", csv(bad), participant_id="P001", session_id="S1").code == "invalid_samples"
    cut = reflective_recording(seconds=30)
    text = csv(cut).decode().rstrip("\n") + "\n30.0,\n"          # a truncated last line is ignored, and reported
    r = add(paths, "ppg", text.encode(), participant_id="P001", session_id="S1")
    assert "incomplete trailing row" in r["upload"]["summary"]["notes"][0]


def test_non_increasing_time_is_rejected(paths):
    df = reflective_recording(seconds=30)
    df.loc[500, "t_s"] = 0.0
    assert err(paths, "ppg", csv(df), participant_id="P001", session_id="S1").code == "not_increasing"


# =================================================================== schema validation / mapping interface
def test_column_names_are_never_assumed_the_person_can_map_them(paths):
    df = reflective_recording(seconds=30).rename(columns={"ir": "counts_a", "red": "counts_b", "t_s": "elapsed_s"})
    e = err(paths, "ppg", csv(df), participant_id="P001", session_id="S1")
    assert e.code == "missing_columns" and e.extra["missing_fields"] == ["ir"] and "counts_a" in e.extra["detected_columns"]
    assert e.extra["proposed_mapping"].get("timestamp") == "elapsed_s" and {f["id"] for f in e.extra["fields"]} >= {"ir", "red", "ax"}
    r = add(paths, "ppg", csv(df), participant_id="P001", session_id="S1", mapping={"ir": "counts_a", "red": "counts_b"})
    assert r["upload"]["mapping"]["ir"] == "counts_a" and r["upload"]["summary"]["windows"] > 0


def test_mapping_errors(paths):
    d = ppg()
    assert err(paths, "ppg", d, participant_id="P1", session_id="S1", mapping={"ir": "nope"}).code == "unknown_column"
    assert err(paths, "ppg", d, participant_id="P1", session_id="S1", mapping={"bogus": "ir"}).code == "unknown_field"
    partial = reflective_recording(seconds=30).drop(columns=["ay"])
    assert err(paths, "ppg", csv(partial), participant_id="P1", session_id="S1").extra["missing_fields"] == ["ax, ay and az together"]


def test_reference_requires_ids_and_sao2(paths):
    e = err(paths, "reference", csv(pd.DataFrame({"participant_id": ["P001"], "sao2": [97]})))
    assert e.code == "missing_columns" and e.extra["missing_fields"] == ["session_id"]
    e = err(paths, "reference", csv(pd.DataFrame({"participant_id": ["P001"], "session_id": ["S1"], "value": [97]})))
    assert "sao2" in e.extra["missing_fields"]
    assert add(paths, "reference", csv(pd.DataFrame({"participant_id": ["P001"], "session_id": ["S1"], "ABG": [97.0]})))["status"] == "staged"


def test_pigmentation_needs_ita_or_lab(paths):
    e = err(paths, "pigmentation", csv(pd.DataFrame({"participant_id": ["P001"], "L": [60], "a": [10]})))
    assert e.code == "missing_columns" and "ita (or L, a and b)" in e.extra["missing_fields"]


def test_personal_columns_are_never_stored_and_cannot_be_ids(paths):
    df = pd.DataFrame({"participant_id": ["P001"], "session_id": ["S1"], "L": [60], "a": [10], "b": [20],
                       "patient_name": ["Jane Doe"], "phone": ["9876543210"], "email": ["a@b.c"]})
    r = add(paths, "pigmentation", csv(df))
    assert sorted(r["ignored_personal_columns"]) == ["email", "patient_name", "phone"]
    t = store.table(paths, "pigmentation")
    assert not any(c in t.columns for c in ("patient_name", "phone", "email")) and "Jane" not in t.to_csv()
    e = err(paths, "pigmentation", csv(df.assign(sha=1)), mapping={"participant_id": "patient_name"})
    assert e.code == "personal_data"


# =================================================================== participant and session IDs
@pytest.mark.parametrize("value", ["P001", "P001_S01", "p-12.a", "7"])
def test_anonymous_ids_are_accepted(value):
    assert id_problem(value) is None


@pytest.mark.parametrize("value,needle", [("", "missing"), ("nan", "missing"), ("jane@example.com", "email"), ("+91 98765 43210", "phone"),
                                          ("Jane Doe", "no spaces"), ("x" * 80, "1–64")])
def test_personal_or_malformed_ids_are_rejected(value, needle):
    assert needle in id_problem(value)


def test_participant_and_session_are_required_for_every_recording(paths):
    assert err(paths, "ppg", ppg(), session_id="S1").code == "missing_id"
    assert err(paths, "ppg", ppg(), participant_id="P001").code == "missing_id"
    e = err(paths, "ppg", ppg(), participant_id="Jane Doe", session_id="S1")
    assert e.code == "bad_id" and "participant_id" in e.message
    assert err(paths, "ppg", ppg(), participant_id="P001", session_id="a b").code == "bad_id"


def test_ids_can_come_from_columns_for_multi_session_files(paths):
    a, b = reflective_recording(seconds=30), reflective_recording(seconds=30, seed=3)
    a["participant_id"], a["session_id"] = "P001", "P001_S01"
    b["participant_id"], b["session_id"] = "P002", "P002_S01"
    r = add(paths, "ppg", csv(pd.concat([a, b], ignore_index=True)))
    assert {s["session_id"] for s in r["upload"]["summary"]["sessions"]} == {"P001_S01", "P002_S01"}


# =================================================================== duplicate sessions
def test_same_participant_session_cannot_be_uploaded_twice(paths):
    add(paths, "ppg", ppg(seed=7), participant_id="P001", session_id="P001_S01")
    e = err(paths, "ppg", ppg(seed=8), participant_id="P001", session_id="P001_S01")
    assert e.code == "duplicate_session" and "already uploaded" in e.message and "Remove" in e.message


def test_a_session_belongs_to_one_participant(paths):
    add(paths, "ppg", ppg(seed=7), participant_id="P001", session_id="S01")
    e = err(paths, "ppg", ppg(seed=8), participant_id="P002", session_id="S01")
    assert e.code == "duplicate_session" and "one participant" in e.message
    assert err(paths, "reference", csv(pd.DataFrame({"participant_id": ["P002"], "session_id": ["S01"], "sao2": [97]}))).code == "duplicate_session"


def test_removing_an_upload_frees_its_session(paths):
    u = add(paths, "ppg", ppg(seed=7), participant_id="P001", session_id="S01")["upload"]["id"]
    assert store.remove_upload(paths, u)["id"] == u and store.table(paths, "ppg").empty
    assert add(paths, "ppg", ppg(seed=8), participant_id="P001", session_id="S01")["status"] == "staged"


# =================================================================== reference SaO2
def test_reference_rows_are_validated_and_flagged_not_dropped(paths):
    df = pd.DataFrame({"participant_id": ["P001"] * 6, "session_id": ["S1"] * 6, "timestamp": [10, 20, 30, 40, 50, 50],
                       "sao2": [97, 0, 101, "abc", "", 96]})
    r = add(paths, "reference", csv(df))
    t = store.table(paths, "reference")
    assert len(t) == 6 and r["upload"]["summary"]["flagged_rows"] == 5
    reasons = list(t["invalid_reason"])
    assert reasons[0] == "" and "out of range" in reasons[1] and "out of range" in reasons[2] and "not a number" in reasons[3] and "missing SaO₂" in reasons[4]
    assert "duplicate reference" in reasons[5]


def test_sao2_is_never_generated(paths):
    add(paths, "reference", csv(pd.DataFrame({"participant_id": ["P001"], "session_id": ["S1"], "sao2": [""]})))
    t = store.table(paths, "reference")
    assert t["sao2"].iloc[0] == "" and "missing SaO₂" in t["invalid_reason"].iloc[0]


def test_reference_timestamps_can_be_relative_seconds_or_datetimes(paths):
    r = add(paths, "reference", csv(pd.DataFrame({"participant_id": ["P001"], "session_id": ["S1"], "timestamp": ["2026-10-07T10:00:15Z"], "sao2": [97]})))
    assert r["upload"]["summary"]["time_basis"] == "absolute"
    r = add(paths, "reference", csv(pd.DataFrame({"participant_id": ["P002"], "session_id": ["S2"], "timestamp": [15], "sao2": [97]})))
    assert r["upload"]["summary"]["time_basis"] == "relative"
    assert err(paths, "reference", csv(pd.DataFrame({"participant_id": ["P003"], "session_id": ["S3"], "timestamp": ["tomorrow-ish"], "sao2": [97]}))).code == "bad_timestamp"
    x, basis = parse_times(pd.Series(["1790000000", "1790000001"]))
    assert basis == "absolute" and x[1] - x[0] == 1


# =================================================================== pigmentation / ITA (Phase 4 module, not duplicated)
def test_ita_is_computed_from_lab_with_the_phase4_module(paths):
    add(paths, "pigmentation", csv(pd.DataFrame({"participant_id": ["P001"], "session_id": ["S1"], "L": [62], "a": [12], "b": [18]})))
    t = store.table(paths, "pigmentation")
    assert float(t["ita"].iloc[0]) == pytest.approx(compute_ita(62, 18), abs=1e-3) and t["invalid_reason"].iloc[0] == ""
    import inspect
    from app.collection import ingest as ing
    assert "atan2" not in inspect.getsource(ing)             # the formula lives in services/pigmentation only


def test_supplied_ita_is_used_and_inconsistency_is_warned(paths):
    df = pd.DataFrame({"participant_id": ["P001", "P002"], "ITA": [33.7, 10.0], "L": [62, 62], "a": [12, 12], "b": [18, 18]})
    r = add(paths, "pigmentation", csv(df))
    t = store.table(paths, "pigmentation")
    assert float(t["ita"].iloc[0]) == pytest.approx(33.7) and t["warning"].iloc[0] == ""
    assert float(t["ita"].iloc[1]) == 10.0 and "differs" in t["warning"].iloc[1] and r["upload"]["summary"]["warnings"] == 1


def test_invalid_lab_rows_are_flagged(paths):
    df = pd.DataFrame({"participant_id": ["P001", "P002", "P003"], "L": [120, 60, 60], "a": [10, 10, ""], "b": [20, "x", 20]})
    add(paths, "pigmentation", csv(df))
    t = store.table(paths, "pigmentation")
    assert "L* must be between" in t["invalid_reason"].iloc[0] and t["invalid_reason"].iloc[1] != "" and "a* is required" in t["invalid_reason"].iloc[2]
    assert (t["ita"] == "").all()


# =================================================================== merge
def test_merge_pairs_each_reference_with_the_nearest_window(paths):
    stage_study(paths)
    q = merge.build_research_dataset(paths)
    ds = pd.read_csv(paths.processed / "research_dataset.csv")
    assert list(ds.columns) == ["participant_id", "session_id", "timestamp", "spo2", "sao2", "pi", "ita", "L", "a", "b", "sqi", "motion", "device_id"]
    assert len(ds) == 2 and q["valid_records"] == 2 and list(ds["sao2"]) == [97.5, 96.0]
    assert list(ds["timestamp"].round(0)) == [15, 30]                                   # relative seconds, window end times
    assert np.allclose(ds["ita"], compute_ita(62, 18), atol=1e-3) and (ds["L"] == 62).all() and (ds["b"] == 18).all()
    assert (ds["device_id"] == "ESP32 + MAX30102").all() and ds["pi"].gt(0).all() and ds["sqi"].gt(70).all()
    assert q["unmatched"] == {"ppg_records": 4, "sao2_records": 0, "pigmentation_records": 0}      # 6 windows - 2 matched; none discarded
    inv = pd.read_csv(paths.processed / "research_dataset_invalid.csv")
    assert len(inv) == 4 and inv["invalid_reason"].str.contains("missing SaO₂").all()


def test_each_reference_is_used_once_even_if_windows_are_close(paths):
    stage_study(paths, ref_times=(15.4,), refs=(97.0,))
    q = merge.build_research_dataset(paths)
    assert q["valid_records"] == 1 and q["unmatched"]["ppg_records"] == 5


def test_reference_outside_the_tolerance_is_unmatched_and_listed(paths):
    stage_study(paths, ref_times=(15.0, 200.0), refs=(97.5, 95.0))
    q = merge.build_research_dataset(paths)
    rep = merge.read_report(paths)
    assert q["valid_records"] == 1 and q["unmatched"]["sao2_records"] == 1
    assert "no PPG window ends within ±30 s" in rep["unmatched_sao2"][0]["reason"] and rep["unmatched_sao2"][0]["sao2"].startswith("95")


def test_session_level_reference_without_timestamps_applies_to_all_windows(paths):
    add(paths, "ppg", ppg(), participant_id="P001", session_id="P001_S01")
    add(paths, "reference", csv(pd.DataFrame({"participant_id": ["P001"], "session_id": ["P001_S01"], "sao2": [96.5]})))
    add(paths, "pigmentation", csv(pd.DataFrame({"participant_id": ["P001"], "L": [62], "a": [12], "b": [18]})))   # participant-level pigmentation
    q = merge.build_research_dataset(paths)
    assert q["valid_records"] == 6 and q["matching"]["matched_records"] == 6 and q["unmatched"]["ppg_records"] == 0


def test_several_references_without_timestamps_are_ambiguous_not_guessed(paths):
    add(paths, "ppg", ppg(), participant_id="P001", session_id="P001_S01")
    add(paths, "reference", csv(pd.DataFrame({"participant_id": ["P001"] * 2, "session_id": ["P001_S01"] * 2, "sao2": [96.5, 97.0]})))
    q = merge.build_research_dataset(paths)
    rep = merge.read_report(paths)
    assert q["valid_records"] == 0 and q["unmatched"]["sao2_records"] == 2 and "ambiguous" in rep["unmatched_sao2"][0]["reason"]


def test_time_basis_mismatch_is_reported_and_fixed_by_the_recording_start(paths):
    ref = csv(pd.DataFrame({"participant_id": ["P001"], "session_id": ["P001_S01"], "timestamp": ["2026-10-07T10:00:15Z"], "sao2": [97.5]}))
    pigm = csv(pd.DataFrame({"participant_id": ["P001"], "L": [62], "a": [12], "b": [18]}))
    add(paths, "ppg", ppg(), participant_id="P001", session_id="P001_S01")
    add(paths, "reference", ref)
    add(paths, "pigmentation", pigm)
    q = merge.build_research_dataset(paths)
    assert q["valid_records"] == 0 and "time bases differ" in merge.read_report(paths)["unmatched_sao2"][0]["reason"]
    store.clear_all(paths)
    add(paths, "ppg", ppg(), participant_id="P001", session_id="P001_S01", recording_start="2026-10-07T10:00:00Z")
    add(paths, "reference", ref)
    add(paths, "pigmentation", pigm)
    q = merge.build_research_dataset(paths)
    ds = pd.read_csv(paths.processed / "research_dataset.csv")
    assert q["valid_records"] == 1 and ds["timestamp"].iloc[0] == "2026-10-07T10:00:15.000Z"


def test_missing_sao2_means_no_research_data(paths):
    add(paths, "ppg", ppg(), participant_id="P001", session_id="P001_S01")
    add(paths, "pigmentation", csv(pd.DataFrame({"participant_id": ["P001"], "L": [62], "a": [12], "b": [18]})))
    q = merge.build_research_dataset(paths)
    assert q["valid_records"] == 0 and q["label"] == "NO RESEARCH DATA" and q["missing_sao2"] == 6 and q["invalid_records"] == 6
    assert not (paths.processed / "research_dataset.csv").exists() and not (paths.raw / "dataset.csv").exists()
    assert q["invalid_reasons"]["missing SaO₂"] == 6


def test_missing_ita_is_flagged(paths):
    add(paths, "ppg", ppg(), participant_id="P001", session_id="P001_S01")
    add(paths, "reference", csv(pd.DataFrame({"participant_id": ["P001"], "session_id": ["P001_S01"], "timestamp": [15.0], "sao2": [97.5]})))
    q = merge.build_research_dataset(paths)
    assert q["valid_records"] == 0 and q["missing_ita"] == 6
    inv = pd.read_csv(paths.processed / "research_dataset_invalid.csv")
    assert inv[inv["sao2"].notna()]["invalid_reason"].iloc[0].startswith("missing ITA")


def test_unmatched_pigmentation_and_unmatched_reference_sessions_are_listed(paths):
    stage_study(paths)
    add(paths, "pigmentation", csv(pd.DataFrame({"participant_id": ["P099"], "L": [50], "a": [8], "b": [15]})))
    add(paths, "reference", csv(pd.DataFrame({"participant_id": ["P098"], "session_id": ["P098_S01"], "timestamp": [5], "sao2": [95]})))
    q = merge.build_research_dataset(paths)
    rep = merge.read_report(paths)
    assert q["unmatched"]["pigmentation_records"] == 1 and rep["unmatched_pigmentation"][0]["participant_id"] == "P099"
    assert q["unmatched"]["sao2_records"] == 1 and rep["unmatched_sao2"][0]["reason"] == "no PPG recording for this session"
    assert q["valid_records"] == 2


def test_mixed_measurement_locations_are_not_combined(paths):
    add(paths, "ppg", ppg(), participant_id="P001", session_id="P001_S01")
    add(paths, "reference", csv(pd.DataFrame({"participant_id": ["P001"], "session_id": ["P001_S01"], "timestamp": [15.0], "sao2": [97.5]})))
    add(paths, "pigmentation", csv(pd.DataFrame({"participant_id": ["P001"] * 2, "L": [62, 50], "a": [12, 10], "b": [18, 20], "location": ["Forehead", "Finger dorsal"]})))
    q = merge.build_research_dataset(paths)
    inv = pd.read_csv(paths.processed / "research_dataset_invalid.csv")
    assert q["valid_records"] == 0 and inv["invalid_reason"].str.contains("different locations").any()


def test_repeated_pigmentation_measurements_use_the_median(paths):
    stage_study(paths)
    add(paths, "pigmentation", csv(pd.DataFrame({"participant_id": ["P001"] * 2, "session_id": ["P001_S01"] * 2, "L": [70, 60], "a": [12, 12], "b": [20, 20]})))
    merge.build_research_dataset(paths)
    ds = pd.read_csv(paths.processed / "research_dataset.csv")
    expect = float(np.median([compute_ita(62, 18), compute_ita(70, 20), compute_ita(60, 20)]))
    assert ds["ita"].iloc[0] == pytest.approx(expect, abs=1e-3)


# =================================================================== validation of combined / already-merged data
def combined_df(n=12, bad=None):
    rng = np.random.default_rng(0)
    df = pd.DataFrame({"participant_id": [f"P{i:03d}" for i in range(n)], "session_id": [f"P{i:03d}_S01" for i in range(n)],
                       "timestamp": 60.0, "spo2": rng.uniform(90, 99, n).round(1), "sao2": rng.uniform(90, 99, n).round(1),
                       "pi": rng.uniform(0.5, 4, n).round(2), "ita": rng.uniform(-10, 55, n).round(1), "sqi": 80, "motion": 5, "device_id": "OximeterX"})
    for (row, col), v in (bad or {}).items():
        df.loc[row, col] = v
    return df


def test_combined_csv_is_validated_record_by_record(paths):
    df = combined_df(n=12, bad={(0, "spo2"): 105, (1, "spo2"): 0, (2, "sao2"): 101, (3, "sao2"): 0, (4, "pi"): 0, (5, "pi"): -2, (6, "ita"): np.nan})
    add(paths, "combined", csv(df))
    q = merge.build_research_dataset(paths)
    assert q["total_records"] == 12 and q["valid_records"] == 5 and q["invalid_records"] == 7
    assert q["invalid_reasons"]["SpO₂ out of range (must be > 0 and ≤ 100)"] == 2
    assert q["invalid_reasons"]["SaO₂ out of range (must be > 0 and ≤ 100)"] == 2
    assert q["invalid_reasons"]["PI must be greater than 0"] == 2 and q["missing_ita"] == 1
    assert q["missing_pi"] == 0 and q["missing_sqi"] == 0 and q["missing_motion"] == 0


def test_combined_csv_lab_columns_give_ita_and_missing_values_are_counted(paths):
    df = combined_df(n=4).drop(columns=["ita", "sqi"])
    df["L"], df["a"], df["b"] = 62, 12, 18
    add(paths, "combined", csv(df))
    q = merge.build_research_dataset(paths)
    ds = pd.read_csv(paths.processed / "research_dataset.csv")
    assert q["valid_records"] == 4 and q["missing_sqi"] == 4 and np.allclose(ds["ita"], compute_ita(62, 18), atol=1e-3)


def test_combined_csv_duplicates_and_missing_sao2_are_flagged(paths):
    df = combined_df(n=4)
    df = pd.concat([df, df.iloc[[1]]], ignore_index=True)
    df.loc[0, "sao2"] = np.nan
    add(paths, "combined", csv(df))
    q = merge.build_research_dataset(paths)
    assert q["valid_records"] == 3 and q["missing_sao2"] == 1 and q["invalid_reasons"]["duplicate record (same participant, session and time)"] == 1


def test_combined_csv_without_session_id_is_rejected_not_filled_in(paths):
    assert err(paths, "combined", csv(combined_df().drop(columns=["session_id"]))).code == "missing_id"
    ok = add(paths, "combined", csv(combined_df(n=3).drop(columns=["session_id"])), session_id="P000_S01")        # one explicit session for the whole file
    assert ok["status"] == "staged"


# =================================================================== research dataset, quality file, status
def test_quality_report_has_every_required_field(paths):
    stage_study(paths)
    q = merge.build_research_dataset(paths)
    saved = json.loads((paths.processed / "research_data_quality.json").read_text())
    for k in ("total_records", "valid_records", "invalid_records", "participants", "sessions", "missing_spo2", "missing_sao2", "missing_ita",
              "missing_pi", "missing_sqi", "missing_motion", "unmatched"):
        assert k in saved
    assert saved["label"] == "RESEARCH DATA" and saved["participants"] == 1 and saved["sessions"] == 1 and saved["unmatched"]["ppg_records"] == 4
    assert saved["total_records"] == 6 and saved["valid_records"] == 2 and saved["invalid_records"] == 4 and saved["missing_sao2"] == 4
    assert "consent/ethics approval" in saved["consent_notice"] and saved == {k: v for k, v in q.items() if k not in ("status", "report")}


def test_building_publishes_valid_records_for_the_processing_step_and_clears_old_splits(paths):
    (paths.processed).mkdir(parents=True)
    (paths.processed / "train.csv").write_text("stale")
    stage_study(paths)
    merge.build_research_dataset(paths)
    assert not (paths.processed / "train.csv").exists()
    raw = pd.read_csv(paths.raw / "dataset.csv")
    assert len(raw) == 2 and {"participant_id", "session_id", "spo2", "sao2", "pi", "ita", "sqi", "motion", "device_id"} <= set(raw.columns)
    assert json.loads((paths.raw / "dataset_meta.json").read_text())["rows"] == 2


def test_nothing_staged_cannot_be_built(paths):
    with pytest.raises(CollectionError) as e:
        merge.build_research_dataset(paths)
    assert e.value.code == "nothing_staged"


def test_model_training_is_blocked_until_there_are_enough_valid_participants(paths):
    stage_study(paths)
    q = merge.build_research_dataset(paths)
    assert q["model_training"]["blocked"] and "Only 1 participant(s)" in q["model_training"]["reasons"][0]
    store.clear_all(paths)
    add(paths, "combined", csv(combined_df(n=12)))
    q = merge.build_research_dataset(paths)
    assert q["valid_records"] == 12 and q["model_training"]["blocked"] is False
    assert "never started automatically" in q["model_training"]["reasons"][-1]


# =================================================================== API end to end
@pytest.fixture
def client(tmp_path):
    set_paths(make_paths(tmp_path))
    yield TestClient(app)
    set_paths(None)


H = {"Content-Type": "text/csv"}


def test_api_status_before_any_upload_is_zero_real_records(client):
    s = client.get("/api/collection/status").json()
    assert s["real_data"] == {"records": 0, "participants": 0, "sessions": 0, "label": "REAL DATA: 0 records"}
    assert s["built"] is False and s["uploads"] == [] and s["model_training"]["blocked"] is True
    assert "consent/ethics approval" in s["consent_notice"]
    assert client.get("/api/collection/quality").json()["available"] is False
    assert client.post("/api/collection/build").json()["errors"][0]["code"] == "nothing_staged"
    assert client.get("/api/dataset/status").json()["loaded"] is False


def test_api_full_workflow(client):
    up = client.post("/api/collection/upload/ppg", content=ppg(), headers=H,
                     params={"filename": "session1.csv", "participant_id": "P001", "session_id": "P001_S01", "attested_real": "true", "source": "esp32"})
    assert up.status_code == 200 and up.json()["upload"]["summary"]["windows"] == 6
    s = client.get("/api/collection/status").json()
    assert s["staged"]["ppg_windows"] == 6 and s["real_data"]["records"] == 0          # staged is NOT research data
    r = client.post("/api/collection/upload/reference", content=csv(pd.DataFrame({"participant_id": ["P001"], "session_id": ["P001_S01"], "timestamp": [15.0], "sao2": [97.5]})),
                    headers=H, params={"attested_real": "true"})
    assert r.status_code == 200
    p = client.post("/api/collection/upload/pigmentation", content=csv(pd.DataFrame({"participant_id": ["P001"], "L": [62], "a": [12], "b": [18]})),
                    headers=H, params={"attested_real": "true"})
    assert p.status_code == 200
    b = client.post("/api/collection/build").json()
    assert b["status"] == "built" and b["valid_records"] == 1 and b["report"]["unmatched_ppg"][0]["reason"].startswith("no reference SaO₂")
    s = client.get("/api/collection/status").json()
    assert s["real_data"] == {"records": 1, "participants": 1, "sessions": 1, "label": "1 valid records"} and s["stale"] is False
    assert client.get("/api/dataset/status").json()["loaded"] is True
    assert client.get("/api/collection/quality").json()["valid_records"] == 1
    assert len(client.get("/api/collection/report").json()["unmatched_ppg"]) == 5


def test_api_errors_are_actionable(client):
    r = client.post("/api/collection/upload/ppg", content=ppg(), headers=H, params={"participant_id": "P001", "session_id": "S1"})
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "not_attested"
    renamed = reflective_recording(seconds=30).rename(columns={"ir": "counts"})
    r = client.post("/api/collection/upload/ppg", content=csv(renamed), headers=H, params={"participant_id": "P001", "session_id": "S1", "attested_real": "true"})
    b = r.json()
    assert r.status_code == 422 and b["missing_fields"] == ["ir"] and "counts" in b["detected_columns"]
    ok = client.post("/api/collection/upload/ppg", content=csv(renamed), headers=H,
                     params={"participant_id": "P001", "session_id": "S1", "attested_real": "true", "mapping": json.dumps({"ir": "counts"})})
    assert ok.status_code == 200
    assert client.post("/api/collection/upload/ppg", content=b"x", params={"mapping": "not json"}).status_code == 422
    assert client.post("/api/collection/upload/nonsense", content=b"x", params={"attested_real": "true"}).json()["errors"][0]["code"] == "bad_kind"
    assert client.get("/api/collection/fields/nonsense").status_code == 404


def test_api_remove_upload_marks_the_build_stale_and_removing_the_last_one_clears_it(client):
    client.post("/api/collection/upload/combined", content=csv(combined_df(n=12)), headers=H, params={"attested_real": "true"})
    client.post("/api/collection/build")
    up = client.get("/api/collection/status").json()["uploads"]
    assert client.get("/api/collection/status").json()["real_data"]["records"] == 12
    client.post("/api/collection/upload/reference", content=csv(pd.DataFrame({"participant_id": ["P000"], "session_id": ["P000_S01"], "sao2": [97]})),
                headers=H, params={"attested_real": "true"})
    assert client.get("/api/collection/status").json()["stale"] is True
    for u in client.get("/api/collection/status").json()["uploads"]:
        assert client.delete(f"/api/collection/uploads/{u['id']}").status_code == 200
    s = client.get("/api/collection/status").json()
    assert s["real_data"]["label"] == "REAL DATA: 0 records" and s["built"] is False
    assert client.get("/api/dataset/status").json()["loaded"] is False and client.delete("/api/collection/uploads/U999").status_code == 404
    assert up


def test_api_templates_are_header_only_and_fields_listed(client):
    for kind in ("ppg", "reference", "pigmentation", "combined"):
        t = client.get(f"/api/collection/template/{kind}")
        assert t.status_code == 200 and t.text.count("\n") == 1                 # a header row, no example values
    assert "participant_id,session_id,timestamp,sao2" in client.get("/api/collection/template/reference").text
    ids = {f["id"] for f in client.get("/api/collection/fields/ppg").json()["fields"]}
    assert {"ir", "red", "timestamp", "ax", "ay", "az"} <= ids


def test_training_stays_blocked_and_nothing_is_trained(client, tmp_path):
    client.post("/api/collection/upload/combined", content=csv(combined_df(n=3)), headers=H, params={"attested_real": "true"})
    client.post("/api/collection/build")
    r = client.post("/api/model/train")
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "training_blocked" and "Only 3 participant" in r.json()["errors"][0]["message"]
    assert not (tmp_path / "models").exists() and not (tmp_path / "results").exists()
    assert client.get("/api/model/status").json()["trained"] is False


# =================================================================== collected data -> processing -> training (test-only data, temp folder)
def test_collected_data_flows_through_processing_into_training(paths):
    """The chain a real study would follow. The numbers here are test-only; they make no research claim."""
    from app.ml import service, train
    from app.ml.data import FEATURES, GROUP_COL, dataset_provenance
    from app.pipeline import pipeline as pl

    rng = np.random.default_rng(5)
    n = 45
    ita = rng.uniform(-20, 60, n)
    df = pd.DataFrame({"participant_id": [f"P{i:03d}" for i in range(n)], "session_id": [f"P{i:03d}_S01" for i in range(n)], "timestamp": 60.0})
    df["spo2"] = rng.uniform(88, 99, n).round(1)
    df["pi"] = np.exp(rng.uniform(np.log(0.3), np.log(5), n)).round(3)
    df["ita"] = ita.round(1)
    df["sqi"], df["motion"] = rng.uniform(60, 100, n).round(1), rng.uniform(0, 30, n).round(1)
    df["sao2"] = (df["spo2"] - 0.05 * (30 - df["ita"]).clip(lower=0) * (1 / df["pi"]) + rng.normal(0, 0.5, n)).clip(50, 100).round(1)
    df["device_id"] = "OximeterX"
    # several sessions-worth of rows per participant so the splits have something to stratify
    df = pd.concat([df.assign(timestamp=60.0 * k, session_id=df["session_id"].str.replace("_S01", f"_S0{k}")) for k in (1, 2, 3)], ignore_index=True)
    df["spo2"] = (df["spo2"] + rng.normal(0, 0.3, len(df))).clip(70, 100).round(2)
    add(paths, "combined", csv(df))
    q = merge.build_research_dataset(paths)
    assert q["valid_records"] == 135 and q["participants"] == 45 and q["model_training"]["blocked"] is False
    assert dataset_provenance(paths)["kind"] == "LOADED"

    proc = pl.process_dataset(paths)
    assert proc["rows_kept"] == 135 and {"sqi", "motion"} <= set(proc["predictors"])
    res = train.train_models(paths)
    assert res["features"] == FEATURES and res["data_provenance"]["kind"] == "LOADED"
    assert sum(1 for _ in res["models"]) == 2 and res["dataset"]["calibration_use"].startswith("Validated")
    tr, ca, te = (set(pd.read_csv(paths.processed / f"{k}.csv")[GROUP_COL]) for k in ("train", "calibration", "test"))
    assert not (tr & ca) and not (tr & te) and not (ca & te)                       # participants never straddle splits
    for name in ("ridge_model.joblib", "lightgbm_model.joblib"):
        assert (paths.models / name).exists()
    assert (paths.results / "model_metrics.json").exists() and (paths.results / "test_predictions.csv").exists()
    st = service.status(paths)
    assert st["trained"] and st["research_data"] == {"records": 135, "participants": 45, "sessions": 135, "blocked": False, "reasons": ["Model training is never started automatically."]}
    assert {c["group"] for c in res["subgroups"]["ita"]} == {"Light", "Medium", "Dark"} and len(res["subgroups"]["ita_x_pi"]) == 6


def test_live_monitor_session_csv_uploads_as_is(paths):
    """The CSV saved by the Live Monitor (participant_id, session_id, timestamp, red, ir, accelerometer_x/y/z) needs no editing.
    Test-only signal; no SaO2 / ITA are present or invented."""
    df = reflective_recording(seconds=30)
    rng = np.random.default_rng(0)
    out = pd.DataFrame({"participant_id": "P001", "session_id": "P001_S01", "timestamp": df["t_s"].round(3), "red": df["red"].round(0), "ir": df["ir"].round(0),
                        "accelerometer_x": rng.normal(0, 0.01, len(df)).round(3), "accelerometer_y": rng.normal(0, 0.01, len(df)).round(3), "accelerometer_z": (1 + rng.normal(0, 0.01, len(df))).round(3)})
    r = add(paths, "ppg", csv(out))
    s = r["upload"]["summary"]
    assert s["sessions"] and s["sessions"][0]["participant_id"] == "P001" and s["sessions"][0]["session_id"] == "P001_S01"
    sess = store.table(paths, "ppg")
    assert {"sao2", "ita"}.isdisjoint(out.columns) and len(sess) > 0


def test_build_with_nothing_uploaded_is_refused_and_ppg_without_reference_is_not_ready(paths):
    with pytest.raises(CollectionError):
        merge.build_research_dataset(paths)
    add(paths, "ppg", ppg(), participant_id="P001", session_id="P001_S01")          # PPG only: no SaO2, no ITA
    q = merge.build_research_dataset(paths)
    assert q["readiness"]["status"] == "NOT READY" and q["readiness"]["reasons"] and q["valid_records"] == 0
    assert q["devices"] == [] and len(q["subgroups"]["cells"]) == 6
    assert all(c["records"] == 0 and c["status"] == "INSUFFICIENT DATA" for c in q["subgroups"]["cells"])
    assert q["missing_sao2"] > 0 and q["missing_ita"] > 0


def test_ready_status_and_insufficient_subgroups_on_test_only_data(tmp_path):
    from tests.test_conformal import build_env
    paths = build_env(tmp_path)                              # test-only synthetic folder; no Dark participants
    q = merge.read_quality(paths) if hasattr(merge, "read_quality") else __import__("json").loads((paths.processed / "research_data_quality.json").read_text())
    assert q["readiness"]["status"] == "READY FOR TRAINING" and q["devices"] == ["OximeterX"]
    dark = [c for c in q["subgroups"]["cells"] if c["label"].startswith("Dark")]
    assert dark and all(c["status"] == "INSUFFICIENT DATA" and c["records"] == 0 for c in dark)
    assert any("Dark" in w for w in q["readiness"]["warnings"])


def test_build_rejects_missing_pi_instead_of_counting_it_valid(paths):
    """A combined row without PI is rejected at the build with a reason, not counted valid and dropped later."""
    df = pd.DataFrame({"participant_id": ["P1"] * 2, "session_id": ["S1"] * 2, "timestamp": [1.0, 2.0], "spo2": [95, 95], "sao2": [96, 96],
                       "pi": [2.0, None], "ita": [30, 30], "sqi": [90, 90], "motion": [5, 5], "device_id": ["d"] * 2})
    add(paths, "combined", csv(df))
    q = merge.build_research_dataset(paths)
    assert q["valid_records"] == 1 and q["invalid_records"] == 1
    assert "missing PI" in pd.read_csv(paths.processed / "research_dataset_invalid.csv")["invalid_reason"].iloc[0]


def test_marked_test_data_is_never_counted_as_real_data(paths):
    """Records that the research gate classes as software-test data are reported separately; REAL DATA stays at 0."""
    df = pd.DataFrame({"participant_id": ["P1"] * 2, "session_id": ["S1"] * 2, "timestamp": [1.0, 2.0], "spo2": [95, 94], "sao2": [96, 95],
                       "pi": [2.0, 2.1], "ita": [30, 30], "sqi": [90, 90], "motion": [5, 5], "device_id": ["SYNTHETIC_DEVICE"] * 2})
    add(paths, "combined", csv(df), filename="synthetic_pipeline_test_dataset.csv")
    merge.build_research_dataset(paths)
    set_paths(paths)
    s = TestClient(app).get("/api/collection/status").json()
    assert s["real_data"] == {"records": 0, "participants": 0, "sessions": 0, "label": "REAL DATA: 0 records"}
    assert s["test_data"]["records"] == 2 and "not real data" in s["test_data"]["label"]


VIRTUAL_MARKER = b"# dataset_type=virtual_hardware_simulation; research_validity=not_for_research_validation; generated_for=hardware_pipeline_integration_testing\n"


def test_virtual_hardware_simulation_files_cannot_be_uploaded_as_research_data(paths):
    body = VIRTUAL_MARKER + b"participant_id,session_id,timestamp,red,ir,accelerometer_x,accelerometer_y,accelerometer_z\nP001,P001_S01,0.000,60000,90000,,,\n"
    for kind in ("ppg", "combined", "reference", "pigmentation"):
        e = err(paths, kind, body, filename="P001_P001_S01_VIRTUAL_SIMULATION.csv")
        assert e.code == "virtual_simulation" and "not real data" in e.message
    assert store.manifest(paths) == []


def test_research_gate_stays_locked_for_virtual_simulation_named_data(paths):
    """Even if the marker line were stripped, the simulation file name is a gate marker: never verified, never REAL DATA."""
    from app.governance import research_gate as gate
    assert gate.evaluate(paths)["state"] == "NO_DATA"
    df = pd.DataFrame({"participant_id": ["P1"] * 2, "session_id": ["S1"] * 2, "timestamp": [1.0, 2.0], "spo2": [95, 94], "sao2": [96, 95],
                       "pi": [2.0, 2.1], "ita": [30, 30], "sqi": [90, 90], "motion": [5, 5], "device_id": ["ESP32"] * 2})
    add(paths, "combined", csv(df), filename="P1_S1_VIRTUAL_SIMULATION.csv")
    merge.build_research_dataset(paths)
    g = gate.evaluate(paths)
    assert g["state"] == "UNVERIFIED_DATA" and g["results_allowed"] is False and g["verified_data"] is False      # a name is not provenance
    assert "no_synthetic_or_test_data" in g["failed_checks"]
    set_paths(paths)
    s = TestClient(app).get("/api/collection/status").json()
    assert s["real_data"]["label"] == "REAL DATA: 0 records" and s["test_data"]["records"] == 2


def test_pairing_is_one_to_one_and_never_guesses_between_ambiguous_references():
    """±match_tolerance_s is a LIMITATION: a reference is paired only with a PPG window ending within it; ties/duplicates stay unmatched."""
    win = [{"i": 0, "t": 100.0, "basis": "relative"}]
    ref = lambda i, t: {"i": i, "t": t, "basis": "relative", "sao2": 96.0}      # noqa: E731
    paired, w_reason, r_reason = merge._match_session(win, [ref(0, 95.0), ref(1, 105.0)], 30.0)
    assert len(paired) == 1 and len(r_reason) == 1 and "no PPG window ends within" in next(iter(r_reason.values()))   # one window cannot take two references
    paired, _, r_reason = merge._match_session(win, [ref(0, 100.0), ref(1, 100.0)], 30.0)
    assert len(paired) == 1 and len(r_reason) == 1                                  # duplicate references: only one is used, the other is listed
    paired, w_reason, _ = merge._match_session(win, [ref(0, 131.0)], 30.0)
    assert paired == {} and "no reference SaO₂ within ±30 s" in w_reason[0]         # just outside the tolerance: unmatched, never stretched
    paired, w_reason, r_reason = merge._match_session(win, [{"i": 0, "t": None, "basis": None, "sao2": 96.0}, {"i": 1, "t": None, "basis": None, "sao2": 95.0}], 30.0)
    assert paired == {} and "ambiguous" in w_reason[0] and len(r_reason) == 2         # several untimed references: no guess


# ---- upload hardening: size / rows / extension / file name / CSV injection / malformed input -> 4xx, never 5xx
def test_upload_extension_filename_and_row_cap(paths):
    from app.config import COLLECTION_CONFIG
    from dataclasses import replace
    body = csv(pd.DataFrame({"participant_id": ["P1"], "session_id": ["S1"], "timestamp": [1.0], "spo2": [95], "sao2": [96], "pi": [2.0], "ita": [30]}))
    assert err(paths, "combined", body, filename="records.exe").code == "bad_extension"
    assert err(paths, "combined", body, filename="records").code == "bad_extension"
    ingest.add_upload("combined", body, {**ATT, "filename": "../../etc/passwd.csv"}, paths)             # path traversal: only the base name survives
    ingest.add_upload("combined", body.replace(b"P1", b"P2").replace(b"S1", b"S2"), {**ATT, "filename": "=HYPERLINK(1).csv"}, paths)   # formula-looking name is defused
    names = [u["filename"] for u in store.manifest(paths)]
    assert names == ["passwd.csv", "_=HYPERLINK(1).csv"]
    cfg = replace(COLLECTION_CONFIG, max_upload_rows=3)
    big = b"participant_id,session_id,timestamp,spo2,sao2,pi,ita\n" + b"P3,S3,1,95,96,2,30\n" * 10
    with pytest.raises(CollectionError) as x:
        ingest.add_upload("combined", big, {**ATT, "filename": "big.csv"}, paths, cfg)
    assert x.value.code == "too_many_rows"
    cfg = replace(COLLECTION_CONFIG, max_upload_mb=0)
    with pytest.raises(CollectionError) as x:
        ingest.add_upload("combined", body, {**ATT, "filename": "x.csv"}, paths, cfg)
    assert x.value.code == "file_too_large"
    assert not (paths.raw.parent / "etc").exists()                                                         # nothing was written outside the data folder


def test_rejected_records_file_is_csv_injection_safe(paths):
    df = pd.DataFrame({"participant_id": ["=cmd|' /C calc'!A0", "@SUM(1)"], "session_id": ["S1", "S1"], "timestamp": [1.0, 2.0], "spo2": [95, 95],
                       "sao2": [96, 96], "pi": [2.0, 2.0], "ita": [30, 30], "sqi": [90, 90], "motion": [5, 5], "device_id": ["d"] * 2})
    add(paths, "combined", csv(df))
    q = merge.build_research_dataset(paths)
    assert q["valid_records"] == 0 and q["invalid_records"] == 2
    cells = pd.read_csv(paths.processed / "research_dataset_invalid.csv", dtype=str)["participant_id"]
    assert all(c.startswith("'") for c in cells)                                # shown as text in a spreadsheet, never executed


def test_malformed_uploads_return_4xx_json_never_5xx(paths):
    set_paths(paths)
    c = TestClient(app, raise_server_exceptions=False)
    for body in (b"", b"\x00\x01\x02" * 100, b'a,b\n"unterminated', b"\xff\xfe\x00\x00", b"a,b,c\n1,2\n3,4,5,6\n"):
        r = c.post("/api/collection/upload/combined?filename=x.csv&attested_real=true", content=body)
        assert 400 <= r.status_code < 500 and r.headers["content-type"].startswith("application/json"), (body[:20], r.status_code)
    r = c.post("/api/collection/upload/combined?filename=x.exe&attested_real=true", content=b"a,b\n1,2\n")
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "bad_extension"
