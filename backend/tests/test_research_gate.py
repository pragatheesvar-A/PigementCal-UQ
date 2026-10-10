"""Deterministic research-status gate (app/governance/research_gate.py).

All data here is TEST-ONLY and synthetic. Where a test registers it as human-participant data, that is only to exercise the gate's logic;
nothing in this file creates, or implies, a research result."""

import json
from datetime import date, timedelta

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.collection import ingest, merge
from app.conformal import fit as cfit
from app.governance import research_gate as gate
from app.main import app
from app.ml import train
from app.ml.paths import set_paths
from app.pipeline import pipeline as pl

from .test_conformal import ATT, CFG, build_env, make_paths, study_csv

BLOCKED = "# OpenOximetry external dataset: status\n\n**OpenOximetry external validation dataset: BLOCKED — AUTHOR CLARIFICATION REQUIRED.**\n"
NO_EXTERNAL = None


def good(**over) -> dict:
    today = date.today()
    p = dict(data_origin="human_participants_collected", dataset_name="Own ESP32 cohort A", source_description="ESP32 + MAX30102 sessions with arterial reference",
             collecting_site="Study site 1", ethics_reference="IRB-001", collection_start=str(today - timedelta(days=60)), collection_end=str(today - timedelta(days=1)),
             reference_sao2_method="ABG co-oximetry", skin_colour_instrument="Colorimeter CM700d", perfusion_source="PPG AC/DC (red/IR)",
             registered_by="Researcher One", declaration=True)
    p.update(over)
    return p


def ev(paths, ext=None):
    return gate.evaluate(paths, external_dir=ext or paths.processed.parent / "no_external")


def tamper(paths, col):
    """Blank a column in a few rows of the built research dataset (the data are then invalid for the full PI-based study)."""
    f = paths.processed / "research_dataset.csv"
    d = pd.read_csv(f)
    d.loc[d.index[:3], col] = float("nan")
    d.to_csv(f, index=False)


# ------------------------------------------------------------------ states
def test_no_dataset_is_no_data(tmp_path):
    r = ev(make_paths(tmp_path))
    assert r["state"] == "NO_DATA" and r["label"] == "NO RESEARCH DATA" and not r["results_allowed"] and not r["verified_data"]


def test_A_attested_data_without_provenance_is_not_a_research_result(tmp_path):
    paths = build_env(tmp_path)
    r = ev(paths)
    assert r["attestation_present"] is True                      # the checkbox was ticked...
    assert r["state"] == "UNVERIFIED_DATA" and not r["results_allowed"] and "NOT A RESEARCH RESULT" in r["label"]
    assert {"verified_flag", "provenance_metadata", "no_synthetic_or_test_data"} <= set(r["failed_checks"])      # ...and was not enough


def test_A_synthetic_declared_is_software_test_data(tmp_path):
    paths = build_env(tmp_path)
    gate.register_provenance(good(data_origin="synthetic"), paths)
    r = ev(paths)
    assert r["state"] == "SOFTWARE_TEST_DATA" and not r["results_allowed"] and not r["verified_data"] and "NOT A RESEARCH RESULT" in r["label"]
    assert gate.read_provenance(paths)["verified_research_dataset"] is False


def test_A_test_markers_in_upload_names_block_even_a_human_declaration(tmp_path):
    paths = make_paths(tmp_path)
    ingest.add_upload("combined", study_csv(120, 5), {**ATT, "filename": "synthetic_cohort.csv"}, paths)
    merge.build_research_dataset(paths)
    pl.process_dataset(paths)
    gate.register_provenance(good(), paths)                       # claims human participants...
    r = ev(paths)
    assert r["state"] == "UNVERIFIED_DATA" and not r["results_allowed"]         # ...but the file name says synthetic: blocked, and a name alone classifies nothing
    assert "no_synthetic_or_test_data" in r["failed_checks"]


def test_simulated_hardware_is_its_own_state(tmp_path):
    paths = build_env(tmp_path)
    gate.register_provenance(good(data_origin="simulated_hardware"), paths)
    r = ev(paths)
    assert r["state"] == "SIMULATED_HARDWARE_DATA" and not r["results_allowed"] and "NOT A RESEARCH RESULT" in r["label"]


# ------------------------------------------------------------------ required fields in the data
@pytest.mark.parametrize("col,check", [("sao2", "reference_sao2_present"), ("ita", "skin_colour_present"), ("pi", "pi_present")])
def test_B_C_D_missing_required_values_are_not_a_research_result(tmp_path, col, check):
    paths = build_env(tmp_path)
    tamper(paths, col)
    gate.register_provenance(good(), paths)                       # provenance is fine and matches the (tampered) file
    r = ev(paths)
    assert check in r["failed_checks"] and not r["results_allowed"] and not r["verified_data"]
    assert r["state"] == "UNVERIFIED_DATA" and "NOT A RESEARCH RESULT" in r["label"]


def test_inconsistent_ita_is_caught_and_consistent_ita_passes(tmp_path):
    from app.services.pigmentation import compute_ita
    paths = build_env(tmp_path)
    f = paths.processed / "research_dataset.csv"
    d = pd.read_csv(f)
    d["L"], d["b"] = 60.0, 15.0
    d["ita"] = compute_ita(60.0, 15.0)                           # consistent with L*, b*
    d.to_csv(f, index=False)
    gate.register_provenance(good(), paths)
    assert "skin_colour_present" not in ev(paths)["failed_checks"]
    d.loc[d.index[:2], "ita"] = d.loc[d.index[:2], "ita"] + 20     # two records no longer match their L*, b*
    d.to_csv(f, index=False)
    gate.register_provenance(good(), paths)
    assert "skin_colour_present" in ev(paths)["failed_checks"]


def test_invalid_participant_ids_fail(tmp_path):
    paths = build_env(tmp_path)
    f = paths.processed / "research_dataset.csv"
    d = pd.read_csv(f)
    d.loc[d.index[:2], "participant_id"] = "jane.doe@example.com"
    d.to_csv(f, index=False)
    gate.register_provenance(good(), paths)
    assert "participant_ids_valid" in ev(paths)["failed_checks"]


# ------------------------------------------------------------------ OpenOximetry
def test_E_openoximetry_while_blocked_is_not_a_research_result(tmp_path):
    ext = tmp_path / "ext"
    (ext / "openoximetry").mkdir(parents=True)
    (ext / "openoximetry" / "STATUS.md").write_text(BLOCKED, encoding="utf-8")
    paths = build_env(tmp_path / "p")
    gate.register_provenance(good(data_origin="external_public", dataset_name="OpenOximetry v1.1.1"), paths)
    r = ev(paths, ext)
    assert r["state"] == "UNVERIFIED_EXTERNAL_DATA" and not r["results_allowed"] and "external_source_not_blocked" in r["failed_checks"]
    # a human-origin record that merely names the blocked source is blocked too
    gate.register_provenance(good(dataset_name="OpenOximetry subset"), paths)
    r2 = ev(paths, ext)
    assert not r2["results_allowed"] and "external_source_not_blocked" in r2["failed_checks"]


def test_external_data_without_any_audit_record_is_blocked(tmp_path):
    paths = build_env(tmp_path)
    gate.register_provenance(good(data_origin="external_public", dataset_name="Some Public Set"), paths)
    r = ev(paths, tmp_path / "empty_ext")
    assert r["state"] == "UNVERIFIED_EXTERNAL_DATA" and not r["results_allowed"]


def test_the_projects_real_openoximetry_status_is_blocked():
    status = gate.EXTERNAL_DIR / "openoximetry" / "STATUS.md"
    if not status.exists():
        pytest.skip("external/openoximetry is not present in this checkout")
    assert "BLOCKED" in status.read_text(encoding="utf-8").upper()


# ------------------------------------------------------------------ the passing path
@pytest.fixture(scope="module")
def fully_trained(tmp_path_factory):
    paths = build_env(tmp_path_factory.mktemp("gate_ok"))
    train.train_models(paths)
    cfit.fit_conformal(paths, CFG)
    gate.register_provenance(good(), paths)
    return paths


def test_F_valid_verified_dataset_with_trained_and_calibrated_models_is_a_research_result(fully_trained):
    r = ev(fully_trained)
    assert r["failed_checks"] == [] and r["state"] == "RESEARCH_RESULTS" and r["results_allowed"] is True and r["label"] == "REAL RESEARCH RESULTS"
    ids = {c["id"] for c in r["checks"] if c["passed"]}
    assert {"verified_flag", "source_recorded", "real_records", "participant_ids_valid", "reference_sao2_present", "skin_colour_present", "pi_present",
            "quality_checks_pass", "participant_split_exists", "no_synthetic_or_test_data", "provenance_metadata", "readiness_gate_passed",
            "external_source_not_blocked", "models_trained_on_this_data", "conformal_calibrated_on_this_data"} <= ids


def test_verified_data_without_trained_models_is_not_yet_a_result(tmp_path):
    paths = build_env(tmp_path)
    gate.register_provenance(good(), paths)
    r = ev(paths)
    assert r["state"] == "VERIFIED_RESEARCH_DATA" and r["verified_data"] and not r["results_allowed"]


def test_rebuilding_the_dataset_invalidates_the_provenance(tmp_path):
    paths = build_env(tmp_path)
    gate.register_provenance(good(), paths)
    assert ev(paths)["verified_data"]
    f = paths.processed / "research_dataset.csv"
    f.write_text(f.read_text() + "\n", encoding="utf-8")          # any change to the file
    r = ev(paths)
    assert not r["verified_data"] and "provenance_metadata" in r["failed_checks"]


def test_stale_models_are_not_a_result(tmp_path):
    paths = build_env(tmp_path)
    train.train_models(paths)
    cfit.fit_conformal(paths, CFG)
    gate.register_provenance(good(), paths)
    assert ev(paths)["results_allowed"]
    (paths.processed / "test.csv").write_text((paths.processed / "test.csv").read_text() + "\n", encoding="utf-8")
    r = ev(paths)
    assert not r["results_allowed"]


# ------------------------------------------------------------------ attestation can never override
def test_G_attestation_checked_but_data_invalid_is_not_a_research_result(tmp_path):
    paths = build_env(tmp_path)
    tamper(paths, "pi")
    gate.register_provenance(good(), paths)
    r = ev(paths)
    assert r["attestation_present"] is True and not r["results_allowed"] and not r["verified_data"]


def test_registration_requires_every_field_and_the_declaration(tmp_path):
    paths = build_env(tmp_path)
    with pytest.raises(gate.ProvenanceError) as e:
        gate.register_provenance(good(ethics_reference="", declaration=False), paths)
    fields = {x["field"] for x in e.value.errors}
    assert {"ethics_reference", "declaration"} <= fields
    assert gate.read_provenance(paths) is None
    with pytest.raises(gate.ProvenanceError):
        gate.register_provenance(good(data_origin="real"), paths)
    with pytest.raises(gate.ProvenanceError):
        gate.register_provenance(good(collection_end=str(date.today() + timedelta(days=3))), paths)


def test_registration_needs_a_built_dataset(tmp_path):
    with pytest.raises(gate.ProvenanceError):
        gate.register_provenance(good(), make_paths(tmp_path))


# ------------------------------------------------------------------ backend enforcement over the API
def test_api_the_client_cannot_set_or_override_the_status(tmp_path):
    paths = build_env(tmp_path)
    tamper(paths, "sao2")
    set_paths(paths)
    c = TestClient(app)
    body = {k: v for k, v in good().items()}
    # unknown fields (like a client-side status) are rejected
    assert c.post("/api/research/provenance", json={**body, "state": "RESEARCH_RESULTS"}).status_code == 422
    assert c.post("/api/research/provenance", json={**body, "verified_research_dataset": True}).status_code == 422
    # the declaration is required
    assert c.post("/api/research/provenance", json={**body, "declaration": False}).status_code == 422
    # a complete record on invalid data is accepted as a record, but the decision stays negative
    r = c.post("/api/research/provenance", json=body)
    assert r.status_code == 200 and r.json()["status"]["results_allowed"] is False and "reference_sao2_present" in r.json()["status"]["failed_checks"]
    h = c.get("/api/health").json()
    assert h["research_status"]["results_allowed"] is False and h["dataset"]["verified"] is False
    assert h["research_status"]["state"] == "UNVERIFIED_DATA"
    assert c.get("/api/model/status").json()["research_results"] is False
    assert c.put("/api/research/status", json={"state": "RESEARCH_RESULTS"}).status_code == 405


def test_api_health_model_status_and_reports_follow_the_gate(fully_trained):
    set_paths(fully_trained)
    c = TestClient(app)
    h = c.get("/api/health").json()
    assert h["research_status"]["state"] == "RESEARCH_RESULTS" and h["dataset"]["verified"] is True
    assert c.get("/api/model/status").json()["research_results"] is True
    assert c.get("/api/validation/report").json()["research_status"]["results_allowed"] is True
    assert c.get("/api/xai/report").json()["research_status"]["state"] == "RESEARCH_RESULTS"
    s = c.get("/api/research/status").json()
    assert s["results_allowed"] and not s["failed_checks"]


def test_reports_say_not_a_result_when_the_gate_is_closed(tmp_path):
    paths = build_env(tmp_path)
    train.train_models(paths)
    cfit.fit_conformal(paths, CFG)                                # trained and calibrated, but no provenance
    set_paths(paths)
    c = TestClient(app)
    v = c.get("/api/validation/report").json()
    assert v["research_status"]["results_allowed"] is False and "NOT A RESEARCH RESULT" in v["research_status"]["label"]
    assert c.get("/api/model/status").json()["research_results"] is False
