"""Hash-bound provenance: the ONLY thing that can classify a dataset as synthetic / simulated test data (or, with the full human declaration and every
other check, verify it). File names, comment lines, device labels and participant IDs never establish provenance; at most they BLOCK.
All data are test-only fixtures in temporary folders."""
import json

import pandas as pd
import pytest

from app.collection import merge
from app.governance import research_gate as gate
from app.governance.research_gate import ProvenanceError
from tests.test_collection import add, csv, make_paths
from tests.test_research_gate import build_env, ev, good

SYN = {"data_origin": "synthetic", "dataset_name": "pipeline test set", "source_description": "generate_synthetic_pipeline_data.py seed 20260101",
       "registered_by": "tester", "generator_version": "generate_synthetic_pipeline_data.py@seed=20260101", "declaration": True}


def _dataset(tmp_path, filename="session_001.csv", device="ESP32 + MAX30102", n=12):
    """A neutral-looking combined dataset (no markers anywhere unless the arguments add them)."""
    paths = make_paths(tmp_path)
    rows = [{"participant_id": f"P{i:03d}", "session_id": f"P{i:03d}_S01", "timestamp": float(t), "spo2": 95.0, "sao2": 96.0, "pi": 2.0, "ita": 30.0,
             "sqi": 90.0, "motion": 5.0, "device_id": device} for i in range(n) for t in (1, 2)]
    add(paths, "combined", csv(pd.DataFrame(rows)), filename=filename)
    merge.build_research_dataset(paths)
    return paths


def test_1_valid_synthetic_provenance_classifies_the_data_as_test_data_even_with_a_neutral_name(tmp_path):
    paths = _dataset(tmp_path)
    rec = gate.register_provenance(dict(SYN), paths)
    assert rec["dataset_sha256"] == gate.file_sha256(paths.processed / gate.DATASET_FILE)
    assert rec["dataset_type"] == "synthetic" and rec["research_validity"] == "not_for_research_validation"
    assert rec["generator_version"].startswith("generate_synthetic") and rec["software_version"] and rec["created_at"]
    assert rec["verified_research_dataset"] is False
    r = ev(paths)
    assert r["state"] == "SOFTWARE_TEST_DATA" and r["provenance_bound"] is True and not r["results_allowed"] and not r["verified_data"]


def test_2_modified_csv_with_the_old_provenance_is_rejected(tmp_path):
    paths = _dataset(tmp_path)
    gate.register_provenance(dict(SYN), paths)
    f = paths.processed / gate.DATASET_FILE
    f.write_text(f.read_text(encoding="utf-8").replace("96.0", "97.0", 1), encoding="utf-8")      # one value changed after registration
    r = ev(paths)
    assert r["provenance_bound"] is False and r["state"] == "UNVERIFIED_DATA" and not r["results_allowed"] and not r["verified_data"]
    assert "provenance_metadata" in r["failed_checks"] and "does not match this dataset" in r["note"]


def test_3_missing_provenance_is_unverified(tmp_path):
    r = ev(_dataset(tmp_path))
    assert r["state"] == "UNVERIFIED_DATA" and r["provenance_bound"] is False and "verified_flag" in r["failed_checks"]


def test_4_a_synthetic_looking_file_name_without_provenance_is_unverified_not_test_data(tmp_path):
    r = ev(_dataset(tmp_path, filename="synthetic.csv"))
    assert r["state"] == "UNVERIFIED_DATA" and not r["results_allowed"] and "no_synthetic_or_test_data" in r["failed_checks"]
    assert "names are not provenance" in r["note"]


def test_5_a_simulation_device_label_without_provenance_is_unverified_and_a_marker_comment_is_refused_by_data_collection(tmp_path):
    r = ev(_dataset(tmp_path, device="Virtual ESP32 + Virtual MAX30102 (simulation)"))
    assert r["state"] == "UNVERIFIED_DATA" and not r["results_allowed"]
    paths = make_paths(tmp_path / "c")
    body = b"# dataset_type=virtual_hardware_simulation; anything\n" + csv(pd.DataFrame({"a": [1], "b": [2]}))
    with pytest.raises(Exception) as e:
        add(paths, "combined", body)
    assert getattr(e.value, "code", "") == "virtual_simulation"


def test_6_a_provenance_for_a_different_dataset_hash_is_rejected(tmp_path):
    a, b = _dataset(tmp_path / "a", n=12), _dataset(tmp_path / "b", n=13)
    rec = gate.register_provenance(dict(SYN), a)
    gate.provenance_path(b).parent.mkdir(parents=True, exist_ok=True)
    gate.provenance_path(b).write_text(json.dumps(rec), encoding="utf-8")                  # A's record copied next to B's data
    r = ev(b)
    assert r["provenance_bound"] is False and r["state"] == "UNVERIFIED_DATA"
    forged = {**rec, "data_origin": "human_participants_collected", "verified_research_dataset": True, "declaration_confirmed": True}
    gate.provenance_path(b).write_text(json.dumps(forged), encoding="utf-8")               # a forged "verified" flag on the wrong hash
    r = ev(b)
    assert r["state"] == "UNVERIFIED_DATA" and not r["verified_data"] and not r["results_allowed"]


def test_7_incomplete_or_invalid_provenance_is_refused_and_the_data_stays_blocked(tmp_path):
    paths = _dataset(tmp_path)
    with pytest.raises(ProvenanceError):                                  # incomplete human declaration (no ethics reference, dates, instruments...)
        gate.register_provenance({"data_origin": "human_participants_collected", "dataset_name": "x", "declaration": True}, paths)
    with pytest.raises(ProvenanceError):                                  # non-human origin without the declaration
        gate.register_provenance({**SYN, "declaration": False}, paths)
    with pytest.raises(ProvenanceError):                                  # unknown origin
        gate.register_provenance({**SYN, "data_origin": "trust_me"}, paths)
    r = ev(paths)
    assert r["state"] == "UNVERIFIED_DATA" and not r["verified_data"]


def test_non_human_provenance_can_never_verify_even_with_every_other_check_passing(tmp_path):
    paths = build_env(tmp_path)
    gate.register_provenance(good(data_origin="simulated_hardware"), paths)
    r = ev(paths)
    assert r["state"] == "SIMULATED_HARDWARE_DATA" and not r["verified_data"] and not r["results_allowed"]
    assert gate.read_provenance(paths)["dataset_type"] == "virtual_hardware_simulation"
