"""Deterministic research-status gate.

The application may call something a research result ONLY when this module says so. The decision is made on the backend from
files on disk; the frontend only displays it and has no way to override it. A checkbox (the upload attestation) is necessary
but never sufficient.

States (exactly one):
  NO_DATA                  no research dataset exists
  SOFTWARE_TEST_DATA       synthetic / test-fixture data (declared, or the files carry test/synthetic markers)
  SIMULATED_HARDWARE_DATA  output of a simulated sensor
  UNVERIFIED_EXTERNAL_DATA data from an external source that has not been cleared (for example OpenOximetry while BLOCKED)
  UNVERIFIED_DATA          data exists but at least one gate check fails (or no provenance record exists)
  VERIFIED_RESEARCH_DATA   every gate check passes, but no trained and calibrated results exist yet
  RESEARCH_RESULTS         verified data AND models trained AND conformal layer calibrated on exactly this data

What the gate can and cannot know: it cannot prove from the numbers alone that participants are real. It therefore requires
a deliberate, field-by-field provenance record (see `register_provenance`) bound to the SHA-256 of the dataset, AND it
re-checks the data itself (reference SaO2, ITA, PI, ids, quality, participant-level split). Any failing check keeps the
dataset out of "research" status. Marker words (test, synthetic, demo, fixture, simulated, mock, fake) found in upload file
names, ids or device ids can only BLOCK, never grant.
"""

import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from ..collection import store as cstore
from ..collection.rules import id_problem
from ..config import COLLECTION_CONFIG, RELIABILITY_CONFIG
from ..ml.data import SPLITS, current_hashes, file_sha256
from ..ml.paths import BACKEND_DIR, Paths, get_paths
from ..config import APP_VERSION
from ..services.pigmentation import compute_ita

DATASET_FILE = "research_dataset.csv"
PROVENANCE_FILE = "research_provenance.json"
EXTERNAL_DIR = BACKEND_DIR.parent / "external"           # audited external candidates, each with a STATUS.md
ORIGINS = ("human_participants_collected", "software_test", "synthetic", "simulated_hardware", "external_public")
REQUIRED_FIELDS = ("data_origin", "dataset_name", "source_description", "collecting_site", "ethics_reference", "collection_start",
                   "collection_end", "reference_sao2_method", "skin_colour_instrument", "perfusion_source", "registered_by")
NON_HUMAN_ORIGINS = ("software_test", "synthetic", "simulated_hardware")
NON_HUMAN_REQUIRED = ("data_origin", "dataset_name", "source_description", "registered_by")      # ethics / site / instrument fields do not apply
DATASET_TYPE = {"human_participants_collected": "human_participants", "software_test": "software_test", "synthetic": "synthetic",
                "simulated_hardware": "virtual_hardware_simulation", "external_public": "external_public"}
MARKER_RE = re.compile(r"(synthetic|simulat|demo|fixture|mock|fake|dummy|(^|[^a-z])test([^a-z]|$))", re.I)
ITA_RECOMPUTE_TOLERANCE_DEG = 0.5

STATES = ("NO_DATA", "SOFTWARE_TEST_DATA", "SIMULATED_HARDWARE_DATA", "UNVERIFIED_EXTERNAL_DATA", "UNVERIFIED_DATA",
          "VERIFIED_RESEARCH_DATA", "RESEARCH_RESULTS")
LABELS = {
    "NO_DATA": "NO RESEARCH DATA",
    "SOFTWARE_TEST_DATA": "SOFTWARE TEST DATA — NOT A RESEARCH RESULT",
    "SIMULATED_HARDWARE_DATA": "SIMULATED HARDWARE DATA — NOT A RESEARCH RESULT",
    "UNVERIFIED_EXTERNAL_DATA": "UNVERIFIED EXTERNAL DATA — NOT A RESEARCH RESULT",
    "UNVERIFIED_DATA": "UNVERIFIED DATA — NOT A RESEARCH RESULT",
    "VERIFIED_RESEARCH_DATA": "VERIFIED RESEARCH DATA — NO TRAINED AND CALIBRATED RESULTS YET",
    "RESEARCH_RESULTS": "REAL RESEARCH RESULTS",
}
GENERIC_FAIL_LABEL = LABELS["UNVERIFIED_DATA"]


class ProvenanceError(Exception):
    def __init__(self, errors: list[dict]):
        super().__init__("; ".join(e["message"] for e in errors))
        self.errors = errors


# ------------------------------------------------------------------ provenance record
def provenance_path(paths: Paths) -> Path:
    return paths.processed.parent / "provenance" / PROVENANCE_FILE          # outside processed/, so a rebuild never deletes it


def read_provenance(paths: Paths) -> dict | None:
    try:
        return json.loads(provenance_path(paths).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _parse_date(v):
    try:
        return date.fromisoformat(str(v))
    except ValueError:
        return None


def register_provenance(payload: dict, paths: Paths | None = None) -> dict:
    """Record who/what/where the research dataset came from. A deliberate act with required fields, bound to the dataset's SHA-256.
    The caller can never set the verification result: `verified_research_dataset` is computed here, and the gate still re-checks the data."""
    paths = paths or get_paths()
    errors: list[dict] = []
    ds = paths.processed / DATASET_FILE
    if not ds.exists():
        raise ProvenanceError([{"field": "dataset", "code": "no_dataset", "message": "Build the research dataset on the Data Collection page first; provenance is bound to that file."}])
    origin = payload.get("data_origin")
    non_human = origin in NON_HUMAN_ORIGINS
    for f in (NON_HUMAN_REQUIRED if non_human else REQUIRED_FIELDS):
        v = payload.get(f)
        if v is None or str(v).strip() == "":
            errors.append({"field": f, "code": "required", "message": f"{f} is required."})
    if payload.get("data_origin") not in ORIGINS and not any(e["field"] == "data_origin" for e in errors):
        errors.append({"field": "data_origin", "code": "invalid", "message": f"data_origin must be one of: {', '.join(ORIGINS)}."})
    start, end = _parse_date(payload.get("collection_start")), _parse_date(payload.get("collection_end"))
    for f, d in (("collection_start", start), ("collection_end", end)):
        if payload.get(f) and d is None:
            errors.append({"field": f, "code": "invalid", "message": f"{f} must be a date (YYYY-MM-DD)."})
    if start and end and (end < start or end > date.today()):
        errors.append({"field": "collection_end", "code": "invalid", "message": "collection_end must be on or after collection_start and not in the future."})
    if payload.get("declaration") is not True:
        errors.append({"field": "declaration", "code": "required", "message": (
            "The declaration must be confirmed: this dataset is NOT from real participants and the origin stated above is accurate." if non_human else
            "The declaration must be confirmed: the records are from real human participants and were collected with approved ethics/consent.")})
    if errors:
        raise ProvenanceError(errors)
    rec = {k: (str(payload.get(k) or "").strip() or "not applicable") for k in REQUIRED_FIELDS}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rec.update({"declaration_confirmed": True, "registered_at": now, "created_at": now,
                "dataset_file": DATASET_FILE, "dataset_sha256": file_sha256(ds),
                "dataset_type": DATASET_TYPE.get(origin, str(origin)),
                "research_validity": "not_for_research_validation" if (non_human or origin == "external_public") else "pending_gate_checks",
                "software_version": APP_VERSION, "generator_version": str(payload.get("generator_version") or "").strip() or None,
                "source_device": str(payload.get("source_device") or "").strip() or None,
                # computed, never accepted from the client:
                "verified_research_dataset": rec_origin_is_human(payload)})
    old = read_provenance(paths)
    rec["history"] = (old.get("history", []) + [{k: old.get(k) for k in ("registered_at", "registered_by", "data_origin", "dataset_sha256")}]) if old else []
    f = provenance_path(paths)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec, indent=2), encoding="utf-8")
    tmp.replace(f)
    return rec


def _ita_or_nan(L: float, b: float) -> float:
    try:
        return compute_ita(L, b)
    except ValueError:
        return float("nan")


def brief(paths: Paths | None = None) -> dict:
    """The gate's verdict in the short form every metric-bearing API response carries, so no number leaves the API without its data-origin label."""
    g = evaluate(paths)
    return {k: g[k] for k in ("state", "label", "results_allowed", "failed_checks")}


def rec_origin_is_human(payload: dict) -> bool:
    return payload.get("data_origin") == "human_participants_collected"


# ------------------------------------------------------------------ helpers
def _chk(cid: str, title: str, passed: bool, detail: str) -> dict:
    return {"id": cid, "title": title, "passed": bool(passed), "detail": detail}


def _read_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _marker_hits(paths: Paths, df: pd.DataFrame | None, prov: dict | None) -> list[str]:
    hits: list[str] = []
    for u in cstore.manifest(paths):
        for k in ("filename", "device_id"):
            if u.get(k) and MARKER_RE.search(str(u[k])):
                hits.append(f"upload {u.get('id', '?')} {k} '{u[k]}'")
    if df is not None:
        for c in ("participant_id", "session_id", "device_id"):
            if c in df:
                for v in df[c].dropna().astype(str).unique()[:5000]:
                    if MARKER_RE.search(v):
                        hits.append(f"{c} '{v}'"); break
    if prov:
        for k in ("dataset_name", "source_description"):
            if prov.get(k) and MARKER_RE.search(str(prov[k])):
                hits.append(f"provenance {k} '{prov[k]}'")
    return hits


def _external_blocked(prov: dict | None, external_dir: Path) -> tuple[bool, str]:
    """Is this dataset (by name) an external candidate whose STATUS.md says BLOCKED?"""
    name = " ".join(str(prov.get(k, "")) for k in ("dataset_name", "source_description")).lower() if prov else ""
    if prov and prov.get("data_origin") == "external_public":
        key = next((d.name for d in external_dir.glob("*") if d.is_dir() and d.name.lower() in name), None)
        status = external_dir / key / "STATUS.md" if key else None
        if status is None or not status.exists():
            return True, "External public data has no cleared audit record (no STATUS.md for this source)."
        txt = status.read_text(encoding="utf-8", errors="replace")
        if "BLOCKED" in txt.upper() or "CLEARED" not in txt.upper():
            return True, f"External source '{key}' is BLOCKED or not marked CLEARED in its STATUS.md."
        return False, f"External source '{key}' is marked CLEARED."
    # a human-origin record that names a blocked external source is still blocked
    for d in external_dir.glob("*") if external_dir.exists() else []:
        st = d / "STATUS.md"
        if d.is_dir() and d.name.lower() in name and st.exists() and "BLOCKED" in st.read_text(encoding="utf-8", errors="replace").upper():
            return True, f"The provenance names '{d.name}', which is BLOCKED."
    return False, "Not an external source, or the external source is cleared."


def _results_checks(paths: Paths) -> list[dict]:
    from ..conformal import fit as cfit
    from ..ml import service as mservice
    hashes = current_hashes(paths)
    out = []
    try:
        m = mservice.read_metrics(paths)
        ok = mservice._is_valid_run(m)
        fresh = bool(hashes) and hashes == {k: v["sha256"] for k, v in m["dataset"]["splits"].items()}
        out.append(_chk("models_trained_on_this_data", "Ridge and LightGBM trained on this exact split", ok and fresh,
                        "Trained and current." if ok and fresh else "Models are missing, from another dataset, or stale; retrain."))
    except Exception as e:                                               # noqa: BLE001 - any failure means no result
        out.append(_chk("models_trained_on_this_data", "Ridge and LightGBM trained on this exact split", False, f"No valid trained models ({type(e).__name__})."))
    try:
        c = cfit.read_metrics(paths)
        fresh = bool(hashes) and hashes == {k: v["sha256"] for k, v in c["dataset"]["splits"].items()}
        out.append(_chk("conformal_calibrated_on_this_data", "Conformal layer calibrated on this exact split", fresh,
                        "Calibrated and current." if fresh else "Conformal layer is stale; recalibrate."))
    except Exception as e:                                               # noqa: BLE001
        out.append(_chk("conformal_calibrated_on_this_data", "Conformal layer calibrated on this exact split", False, f"No valid conformal layer ({type(e).__name__})."))
    return out


_CACHE: dict = {}


def _cache_key(paths: Paths, external_dir: Path):
    files = [paths.processed / DATASET_FILE, paths.processed / "research_data_quality.json", provenance_path(paths), paths.raw / "dataset_meta.json",
             paths.processed / "split_manifest.json", paths.collection_dir / cstore.MANIFEST, paths.results / "model_metrics.json",
             paths.results / "conformal_metrics.json", *[paths.processed / f"{n}.csv" for n in SPLITS]]
    files += list(external_dir.glob("*/STATUS.md")) if external_dir.exists() else []
    key = [str(paths.processed), str(external_dir)]
    for f in files:
        try:
            st = f.stat(); key.append((str(f), st.st_mtime_ns, st.st_size))
        except OSError:
            key.append((str(f), None, None))
    return tuple(key)


# ------------------------------------------------------------------ the gate
def evaluate(paths: Paths | None = None, external_dir: Path | None = None) -> dict:
    paths = paths or get_paths()
    external_dir = external_dir or EXTERNAL_DIR
    key = _cache_key(paths, external_dir)
    if _CACHE.get("key") == key:
        return _CACHE["value"]
    value = _evaluate(paths, external_dir)
    _CACHE.update(key=key, value=value)
    return value


def _evaluate(paths: Paths, external_dir: Path) -> dict:
    ds_file = paths.processed / DATASET_FILE
    prov = read_provenance(paths)
    attested = any(u.get("attested_real") for u in cstore.manifest(paths))
    if not ds_file.exists():
        return _result("NO_DATA", [], prov, attested, "No research dataset has been built.")
    try:
        df = pd.read_csv(ds_file, low_memory=False)
    except (OSError, ValueError):
        df = pd.DataFrame()
    q = _read_json(paths.processed / "research_data_quality.json") or {}
    bound = bool(prov and prov.get("dataset_sha256") == file_sha256(ds_file))
    origin = prov.get("data_origin") if bound else None            # a record for a different / changed file establishes nothing
    checks: list[dict] = []

    # 1 explicitly marked as a verified research dataset
    checks.append(_chk("verified_flag", "Dataset is explicitly marked as a verified research dataset",
                       bool(prov and prov.get("verified_research_dataset") is True and prov.get("declaration_confirmed") is True and origin == "human_participants_collected"),
                       "Provenance record present and declares human-participant data." if prov else "No provenance record is registered for this dataset."))
    # 2 source recorded
    src_missing = [f for f in ("dataset_name", "source_description", "collecting_site") if not (prov and str(prov.get(f, "")).strip())]
    checks.append(_chk("source_recorded", "Dataset source is recorded", not src_missing, "Source recorded." if not src_missing else f"Missing: {', '.join(src_missing)}."))
    # 3 real participant/session records
    n, parts = len(df), (df["participant_id"].nunique() if "participant_id" in df else 0)
    sess = df[["participant_id", "session_id"]].drop_duplicates().shape[0] if {"participant_id", "session_id"} <= set(df.columns) else 0
    minp = COLLECTION_CONFIG.min_training_participants
    checks.append(_chk("real_records", "Dataset contains real participant/session records", n > 0 and parts >= minp and sess > 0 and origin == "human_participants_collected",
                       f"{n} records, {parts} participants (minimum {minp}), {sess} sessions, origin: {origin or 'not recorded'}."))
    # 4 participant ids valid
    bad_ids = []
    for c in ("participant_id", "session_id"):
        if c in df:
            bad_ids += [f"{c} '{v}': {id_problem(v)}" for v in df[c].dropna().astype(str).unique() if id_problem(v)]
    checks.append(_chk("participant_ids_valid", "Participant and session IDs are valid and anonymous", n > 0 and not bad_ids and "participant_id" in df and not df["participant_id"].isna().any(),
                       "All IDs valid." if n and not bad_ids else (bad_ids[0] if bad_ids else "No records.")))
    # 5 reference SaO2
    sao2 = pd.to_numeric(df["sao2"], errors="coerce") if "sao2" in df else pd.Series(dtype=float)
    ok5 = n > 0 and len(sao2) == n and sao2.notna().all() and sao2.between(0, 100, inclusive="right").all() and bool(prov and str(prov.get("reference_sao2_method", "")).strip())
    checks.append(_chk("reference_sao2_present", "Reference SaO2 is present for every record (and its method recorded)", ok5,
                       "Present." if ok5 else f"{int(sao2.isna().sum()) if len(sao2) else n} of {n} records lack a valid SaO2, or the reference method is not recorded."))
    # 6 ITA / L*a*b*
    ita = pd.to_numeric(df["ita"], errors="coerce") if "ita" in df else pd.Series(dtype=float)
    ita_ok = n > 0 and len(ita) == n and ita.notna().all() and ita.between(RELIABILITY_CONFIG.ita_min, RELIABILITY_CONFIG.ita_max).all()
    mism = 0
    if ita_ok and {"L", "b"} <= set(df.columns):
        L, b = pd.to_numeric(df["L"], errors="coerce"), pd.to_numeric(df["b"], errors="coerce")
        have = L.notna() & b.notna()
        if have.any():
            calc = np.array([_ita_or_nan(float(l), float(bb)) for l, bb in zip(L[have], b[have])])
            mism = int((np.abs(calc - ita[have].to_numpy()) > ITA_RECOMPUTE_TOLERANCE_DEG).sum())
    ok6 = ita_ok and mism == 0 and bool(prov and str(prov.get("skin_colour_instrument", "")).strip())
    checks.append(_chk("skin_colour_present", "Objective ITA (from L*a*b*) is present for every record and consistent", ok6,
                       "Present and consistent." if ok6 else (f"{int(ita.isna().sum()) if len(ita) else n} of {n} records lack ITA" if not ita_ok else f"{mism} record(s) have an ITA that does not match L*, b*") + ", or the instrument is not recorded."))
    # 7 PI
    pi = pd.to_numeric(df["pi"], errors="coerce") if "pi" in df else pd.Series(dtype=float)
    ok7 = n > 0 and len(pi) == n and pi.notna().all() and (pi > 0).all() and bool(prov and str(prov.get("perfusion_source", "")).strip())
    checks.append(_chk("pi_present", "PI is present for every record (required for the full PI-based study)", ok7,
                       "Present." if ok7 else f"{int(pi.isna().sum()) if len(pi) else n} of {n} records lack a valid PI, or the PI source is not recorded."))
    # 8 data-quality checks
    ready = (q.get("readiness") or {}).get("status") == "READY FOR TRAINING"
    ok8 = ready and int(q.get("valid_records", -1)) == n and n > 0
    checks.append(_chk("quality_checks_pass", "Data-quality checks pass", ok8, "Quality report says READY FOR TRAINING." if ok8 else "Quality report is missing, not READY FOR TRAINING, or does not match the dataset."))
    # 9 participant-level split
    split_ok, split_detail = _split_check(paths, df)
    checks.append(_chk("participant_split_exists", "Participant-level train/calibration/test split exists and is leak-free", split_ok, split_detail))
    # 10 no synthetic / demo / test fixture
    hits = _marker_hits(paths, df, prov)
    ok10 = origin == "human_participants_collected" and not hits
    checks.append(_chk("no_synthetic_or_test_data", "No synthetic, simulated, demo or test-fixture data", ok10,
                       "No markers found and origin is human participants." if ok10 else (f"Marker found: {hits[0]}." if hits else f"Declared origin is '{origin or 'not recorded'}'.")))
    # 11 provenance metadata complete and bound to this dataset
    miss = [f for f in REQUIRED_FIELDS if not (prov and str(prov.get(f, "")).strip())]
    bound = bool(prov and prov.get("dataset_sha256") == file_sha256(ds_file))
    checks.append(_chk("provenance_metadata", "Provenance metadata is complete and bound to this exact dataset", not miss and bound and bool(prov),
                       "Complete and matches the dataset hash." if not miss and bound and prov else ("No provenance record." if not prov else (f"Missing fields: {', '.join(miss)}." if miss else "The dataset changed after the provenance was registered; register it again."))))
    # 13 blocked external sources
    blocked, why = _external_blocked(prov, external_dir)
    checks.append(_chk("external_source_not_blocked", "Not an uncleared or BLOCKED external dataset (e.g. OpenOximetry)", not blocked, why))
    # 12 overall data-readiness gate
    checks.append(_chk("readiness_gate_passed", "Project data-readiness gate passed", all(c["passed"] for c in checks), "All checks above pass." if all(c["passed"] for c in checks) else "At least one check above fails."))

    failed = [c for c in checks if not c["passed"]]
    if failed:
        if origin in ("software_test", "synthetic"):                # only a hash-bound provenance record can classify data as test data
            state = "SOFTWARE_TEST_DATA"
        elif origin == "simulated_hardware":
            state = "SIMULATED_HARDWARE_DATA"
        elif origin == "external_public" or blocked:
            state = "UNVERIFIED_EXTERNAL_DATA"
        else:
            state = "UNVERIFIED_DATA"
        note = "One or more gate checks failed."
        if prov and not bound:
            note += " The registered provenance does not match this dataset's SHA-256 (the dataset changed or the record is for another file), so it is ignored."
        elif hits and not origin:
            note += " Test/simulation name markers were found, but names are not provenance: register a hash-bound provenance record to classify this data."
        return _result(state, checks, prov, attested, note, bound, bool(hits))
    res = _results_checks(paths)
    state = "RESEARCH_RESULTS" if all(c["passed"] for c in res) else "VERIFIED_RESEARCH_DATA"
    return _result(state, checks + res, prov, attested, "All gate checks pass." if state == "RESEARCH_RESULTS" else "Data verified; models and/or conformal calibration are not current.", bound)


def _split_check(paths: Paths, df: pd.DataFrame) -> tuple[bool, str]:
    files = {n: paths.processed / f"{n}.csv" for n in SPLITS}
    if not all(f.exists() for f in files.values()) or not (paths.processed / "split_manifest.json").exists():
        return False, "Train/calibration/test files or the split manifest are missing; run Validate & split."
    try:
        sets = {n: set(pd.read_csv(f, usecols=["participant_id"])["participant_id"].astype(str)) for n, f in files.items()}
    except (OSError, ValueError, KeyError):
        return False, "Split files could not be read."
    if any(not s for s in sets.values()):
        return False, "A split is empty."
    for a, b in (("train", "calibration"), ("train", "test"), ("calibration", "test")):
        if sets[a] & sets[b]:
            return False, f"Participant leakage between {a} and {b}."
    meta = _read_json(paths.raw / "dataset_meta.json") or {}
    ds_sha = file_sha256(paths.processed / DATASET_FILE)
    if meta.get("sha256") != ds_sha:
        return False, "The splits were made from a different version of the dataset; re-run Validate & split."
    if not set().union(*sets.values()) <= set(df["participant_id"].astype(str)):
        return False, "The splits contain participants that are not in the dataset."
    return True, "Participant-disjoint splits exist and derive from the current dataset."


def _result(state: str, checks: list[dict], prov: dict | None, attested: bool, note: str, bound: bool | None = None, markers: bool = False) -> dict:
    failed = [c["id"] for c in checks if not c["passed"]]
    summary = ({k: prov.get(k) for k in ("data_origin", "dataset_name", "collecting_site", "registered_at", "registered_by", "verified_research_dataset")} if prov else None)
    return {"state": state, "label": LABELS[state], "generic_label": GENERIC_FAIL_LABEL if state not in ("NO_DATA", "VERIFIED_RESEARCH_DATA", "RESEARCH_RESULTS") else LABELS[state],
            "results_allowed": state == "RESEARCH_RESULTS", "verified_data": state in ("VERIFIED_RESEARCH_DATA", "RESEARCH_RESULTS"),
            "failed_checks": failed, "checks": checks, "attestation_present": attested, "provenance": summary, "provenance_bound": bound, "name_markers_found": markers, "note": note,
            "rule": "A research result is shown only when every check passes on the backend. The upload attestation alone never grants it."}
