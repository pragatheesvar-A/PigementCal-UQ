"""Merge the staged sources into the research dataset.

Matching rules (all reported, nothing silently discarded):
  * PPG windows <-> reference SaO2: same participant_id AND session_id; then by time. Each reference is paired with the
    nearest PPG window whose end lies within `match_tolerance_s` (one-to-one). A session with exactly ONE reference and
    no timestamps is paired with all of its windows (match_mode = "session"). Ambiguous references stay unmatched.
  * Pigmentation: by (participant_id, session_id) when the file has sessions, otherwise by participant_id. Several rows
    -> the median ITA; rows from different measurement locations are NOT combined (the group is flagged).
  * Records that cannot be completed are kept in research_dataset_invalid.csv with the reasons.
"""

import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib

import numpy as np
import pandas as pd

from ..config import COLLECTION_CONFIG, CONSENT_NOTICE, CollectionConfig, LIVE_CONFIG
from ..ml.paths import Paths, get_paths
from . import store
from .rules import CollectionError, csv_safe_frame, fmt_time, id_problem

DATASET_COLUMNS = ["participant_id", "session_id", "timestamp", "spo2", "sao2", "pi", "ita", "L", "a", "b", "sqi", "motion", "device_id"]
DATASET_FILE = "research_dataset.csv"
INVALID_FILE = "research_dataset_invalid.csv"
QUALITY_FILE = "research_data_quality.json"
REPORT_FILE = "merge_report.json"


def _f(x):
    try:
        v = float(x)
        return v if np.isfinite(v) else None
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ matching
def _match_session(windows: list[dict], refs: list[dict], tol: float):
    """Returns (window_idx -> (ref_idx, mode), window_idx -> reason, ref_idx -> reason)."""
    paired: dict[int, tuple[int, str]] = {}
    w_reason: dict[int, str] = {}
    r_reason: dict[int, str] = {}
    timed = [r for r in refs if r["t"] is not None]
    untimed = [r for r in refs if r["t"] is None]
    if not refs:
        return paired, {w["i"]: "no reference SaO₂ for this session" for w in windows}, r_reason
    if timed:
        for r in untimed:
            r_reason[r["i"]] = "no timestamp, while this session has timestamped references"
        bases = {r["basis"] for r in timed} | {w["basis"] for w in windows}
        if len(bases) > 1:
            msg = "time bases differ (PPG is relative seconds vs reference absolute date-times, or the reverse): give the PPG recording start time"
            return paired, {w["i"]: msg for w in windows}, {**r_reason, **{r["i"]: msg for r in timed}}
        cand = sorted((abs(w["t"] - r["t"]), r["i"], w["i"]) for r in timed for w in windows if abs(w["t"] - r["t"]) <= tol)
        used_r: set[int] = set()
        for d, ri, wi in cand:
            if ri in used_r or wi in paired:
                continue
            paired[wi] = (ri, "time")
            used_r.add(ri)
        for r in timed:
            if r["i"] not in used_r:
                r_reason[r["i"]] = f"no PPG window ends within ±{tol:g} s of this reference"
        for w in windows:
            if w["i"] not in paired:
                w_reason[w["i"]] = f"no reference SaO₂ within ±{tol:g} s"
    elif len(untimed) == 1:
        for w in windows:
            paired[w["i"]] = (untimed[0]["i"], "session")
    else:
        for r in untimed:
            r_reason[r["i"]] = f"ambiguous: {len(untimed)} references in this session have no timestamp"
        for w in windows:
            w_reason[w["i"]] = "ambiguous reference SaO₂ (several without timestamps)"
    return paired, w_reason, r_reason


# ------------------------------------------------------------------ pigmentation
def _pigment_groups(pig: pd.DataFrame):
    """-> (groups, flagged_rows). groups[(pid, sid)] = dict(ita, L, a, b, n, invalid)."""
    groups: dict[tuple[str, str], dict] = {}
    flagged = []
    if pig.empty:
        return groups, flagged
    ok = pig[pig["invalid_reason"] == ""]
    for _, r in pig[pig["invalid_reason"] != ""].iterrows():
        flagged.append({"participant_id": r["participant_id"], "session_id": r["session_id"], "reason": r["invalid_reason"], "source_file": r["source_file"]})
    for key, g in ok.groupby(["participant_id", "session_id"], sort=False):
        locs = sorted({str(x).strip() for x in g["location"] if str(x).strip()})
        itas = [float(x) for x in g["ita"]]
        d = {"n": len(g), "invalid": ""}
        if len(locs) > 1:
            d["invalid"] = f"measurements from different locations ({', '.join(locs)}) are not combined — keep one location per participant"
        else:
            d["ita"] = statistics.median(itas)
            for f in ("L", "a", "b"):
                vals = [float(x) for x in g[f] if str(x).strip() != ""]
                d[f] = statistics.median(vals) if len(vals) == len(g) else None
        groups[key] = d
    return groups, flagged


# ------------------------------------------------------------------ build
def build_research_dataset(paths: Paths | None = None, cfg: CollectionConfig = COLLECTION_CONFIG) -> dict:
    paths = paths or get_paths()
    uploads = store.manifest(paths)
    if not uploads:
        raise CollectionError("nothing_staged", "Nothing has been uploaded yet. Upload PPG, reference SaO₂ and pigmentation data first.")
    if not all(u.get("attested_real") for u in uploads):
        raise CollectionError("not_attested", "Every upload must be confirmed as real collected data before the research dataset is built.")
    ppg, ref, pig, comb = (store.table(paths, k) for k in ("ppg", "reference", "pigmentation", "combined"))
    tol = cfg.match_tolerance_s

    # ---- references
    refs_by_session: dict[tuple[str, str], list[dict]] = defaultdict(list)
    ref_value: dict[int, float] = {}
    unmatched_sao2: list[dict] = []
    if not ref.empty:
        for i, r in ref.iterrows():
            if r["invalid_reason"]:
                unmatched_sao2.append({"participant_id": r["participant_id"], "session_id": r["session_id"], "sao2": r["sao2"], "timestamp": r["timestamp_s"], "reason": "flagged: " + r["invalid_reason"]})
                continue
            refs_by_session[(r["participant_id"], r["session_id"])].append({"i": i, "t": _f(r["timestamp_s"]), "basis": r["time_basis"], "sao2": float(r["sao2"])})
            ref_value[i] = float(r["sao2"])

    # ---- pigmentation
    pgroups, unmatched_pig = _pigment_groups(pig)
    used_pig: set[tuple[str, str]] = set()

    def pigment_for(pid: str, sid: str):
        for key in ((pid, sid), (pid, "")):
            if key in pgroups:
                used_pig.add(key)
                return pgroups[key]
        return None

    records: list[dict] = []
    used_refs: set[int] = set()
    unmatched_ppg: list[dict] = []

    # ---- PPG windows
    if not ppg.empty:
        ppg = ppg.reset_index(drop=True)
        for (pid, sid), g in ppg.groupby(["participant_id", "session_id"], sort=False):
            wins = [{"i": i, "t": float(r["timestamp_s"]), "basis": r["time_basis"]} for i, r in g.iterrows()]
            paired, w_reason, r_reason = _match_session(wins, refs_by_session.get((pid, sid), []), tol)
            for i, why in r_reason.items():
                rr = ref.loc[i]
                unmatched_sao2.append({"participant_id": pid, "session_id": sid, "sao2": rr["sao2"], "timestamp": rr["timestamp_s"], "reason": why})
            for i, r in g.iterrows():
                p = pigment_for(pid, sid)
                rec = {"participant_id": pid, "session_id": sid, "timestamp": fmt_time(float(r["timestamp_s"]), r["time_basis"]),
                       "spo2": _f(r["spo2"]), "sao2": None, "pi": _f(r["pi"]), "ita": None, "L": None, "a": None, "b": None,
                       "sqi": _f(r["sqi"]), "motion": _f(r["motion"]), "device_id": r["device_id"], "source": "ppg_window",
                       "match_mode": "", "spo2_source": r["spo2_source"], "signal_quality": r["signal_quality"], "staged_reason": "", "_why": []}
                if r["analysis_note"] and rec["spo2"] is None:
                    rec["_why"].append(f"missing SpO₂ ({r['analysis_note']})")
                if i in paired:
                    ri, mode = paired[i]
                    rec["sao2"], rec["match_mode"] = ref_value[ri], mode
                    used_refs.add(ri)
                else:
                    unmatched_ppg.append({"participant_id": pid, "session_id": sid, "timestamp": rec["timestamp"], "reason": w_reason.get(i, "no reference SaO₂")})
                if p is None:
                    rec["_why"].append("missing ITA (no pigmentation data for this participant/session)")
                elif p["invalid"]:
                    rec["_why"].append("ITA unusable: " + p["invalid"])
                else:
                    rec.update(ita=p["ita"], L=p["L"], a=p["a"], b=p["b"])
                records.append(rec)

    # ---- combined records
    for _, r in (comb.iterrows() if not comb.empty else []):
        t = _f(r["timestamp_s"])
        rec = {"participant_id": r["participant_id"], "session_id": r["session_id"], "timestamp": fmt_time(t, r["time_basis"]) if t is not None else "",
               "spo2": _f(r["spo2"]), "sao2": _f(r["sao2"]), "pi": _f(r["pi"]), "ita": _f(r["ita"]), "L": _f(r["L"]), "a": _f(r["a"]), "b": _f(r["b"]),
               "sqi": _f(r["sqi"]), "motion": _f(r["motion"]), "device_id": r["device_id"], "source": "combined_file", "match_mode": "", "spo2_source": "file",
               "signal_quality": "", "staged_reason": r["invalid_reason"], "_why": []}
        if rec["ita"] is None and not r["invalid_reason"]:
            rec["_why"].append("missing ITA (no ITA and no complete L*, a*, b*)")
        records.append(rec)

    # ---- validation of every record
    seen: set[tuple] = set()
    for rec in records:
        why = list(rec.pop("_why"))
        if rec["staged_reason"]:
            why.append(rec["staged_reason"])
        for field in ("participant_id", "session_id"):
            p = id_problem(rec[field])
            if p:
                why.append(f"{field}: {p}")
        if rec["spo2"] is None and not any(w.startswith("missing SpO₂") for w in why):
            why.append("missing SpO₂")
        elif rec["spo2"] is not None and not (0 < rec["spo2"] <= 100):
            why.append("SpO₂ out of range (must be > 0 and ≤ 100)")
        if rec["sao2"] is None:
            why.append("missing SaO₂ (no matching reference)" if rec["source"] == "ppg_window" else "missing SaO₂")
        elif not (0 < rec["sao2"] <= 100):
            why.append("SaO₂ out of range (must be > 0 and ≤ 100)")
        if rec["pi"] is None:
            why.append("missing PI")
        elif not rec["pi"] > 0:
            why.append("PI must be greater than 0")
        key = (rec["participant_id"], rec["session_id"], rec["timestamp"], rec["source"])
        if key in seen:
            why.append("duplicate record (same participant, session and time)")
        seen.add(key)
        rec["invalid_reason"] = "; ".join(dict.fromkeys(why))

    df = pd.DataFrame(records, columns=DATASET_COLUMNS + ["source", "match_mode", "spo2_source", "signal_quality", "invalid_reason"]) if records else \
        pd.DataFrame(columns=DATASET_COLUMNS + ["source", "match_mode", "spo2_source", "signal_quality", "invalid_reason"])
    valid = df[df["invalid_reason"] == ""]
    invalid = df[df["invalid_reason"] != ""]

    # ---- pigmentation never used
    for key, d in pgroups.items():
        if key not in used_pig:
            unmatched_pig.append({"participant_id": key[0], "session_id": key[1], "reason": "no PPG window or combined record for this participant/session"})

    # ---- unmatched reference rows that belong to sessions without any PPG data
    ppg_sessions = {(p, s) for p, s in ppg[["participant_id", "session_id"]].drop_duplicates().itertuples(index=False)} if not ppg.empty else set()
    for key, lst in refs_by_session.items():
        if key not in ppg_sessions:
            for r in lst:
                rr = ref.loc[r["i"]]
                unmatched_sao2.append({"participant_id": key[0], "session_id": key[1], "sao2": rr["sao2"], "timestamp": rr["timestamp_s"], "reason": "no PPG recording for this session"})

    # ---- write outputs
    paths.processed.mkdir(parents=True, exist_ok=True)
    out_cols = DATASET_COLUMNS
    for fname, part in ((DATASET_FILE, valid[out_cols]), (INVALID_FILE, csv_safe_frame(invalid[out_cols + ["source", "invalid_reason"]]))):
        f = paths.processed / fname
        if part.empty:
            f.unlink(missing_ok=True)
        else:
            tmp = f.with_suffix(".tmp")
            part.to_csv(tmp, index=False)
            tmp.replace(f)

    reasons = Counter()
    for s in invalid["invalid_reason"]:
        for r in s.split("; "):
            reasons[r.split(" (")[0] if r.startswith("missing") else r] += 1
    n_total, n_valid = len(df), len(valid)
    val_part = int(valid["participant_id"].nunique()) if n_valid else 0
    blockers = []
    if n_valid == 0:
        blockers.append("There are no valid real records.")
    elif val_part < cfg.min_training_participants:
        blockers.append(f"Only {val_part} participant(s) have valid records; at least {cfg.min_training_participants} are required.")
    subgroups = _subgroup_counts(valid)
    if blockers:
        readiness = {"status": "NOT READY", "reasons": blockers}
    else:
        readiness = {"status": "READY FOR TRAINING", "reasons": [],
                     "warnings": [f"{c['label']}: INSUFFICIENT DATA" for c in subgroups["cells"] if c["status"] == "INSUFFICIENT DATA"]}
    quality = {
        "readiness": readiness, "subgroups": subgroups,
        "devices": sorted(valid["device_id"].dropna().astype(str).unique().tolist()) if n_valid else [],
        "label": "RESEARCH DATA" if n_valid else "NO RESEARCH DATA",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "total_records": n_total, "valid_records": n_valid, "invalid_records": n_total - n_valid,
        "participants": val_part, "sessions": int(valid[["participant_id", "session_id"]].drop_duplicates().shape[0]) if n_valid else 0,
        "participants_all_records": int(df["participant_id"].nunique()) if n_total else 0,
        "missing_spo2": int(df["spo2"].isna().sum()), "missing_sao2": int(df["sao2"].isna().sum()), "missing_ita": int(df["ita"].isna().sum()),
        "missing_pi": int(df["pi"].isna().sum()), "missing_sqi": int(df["sqi"].isna().sum()), "missing_motion": int(df["motion"].isna().sum()),
        "unmatched": {"ppg_records": len(unmatched_ppg), "sao2_records": len(unmatched_sao2), "pigmentation_records": len(unmatched_pig)},
        "invalid_reasons": dict(reasons.most_common()),
        "matching": {"tolerance_s": tol, "window_s": LIVE_CONFIG.window_seconds, "hop_s": cfg.hop_seconds,
                     "matched_records": int(sum(1 for r in records if r["sao2"] is not None and r["source"] == "ppg_window"))},
        "sources": [{"id": u["id"], "kind": u["kind"], "filename": u["filename"], "staged_rows": u["staged_rows"]} for u in uploads],
        "model_training": {"blocked": bool(blockers), "reasons": blockers + ["Model training is never started automatically."]},
        "consent_notice": CONSENT_NOTICE,
    }
    report = {"unmatched_ppg": unmatched_ppg[: cfg.max_listed], "unmatched_sao2": unmatched_sao2[: cfg.max_listed],
              "unmatched_pigmentation": unmatched_pig[: cfg.max_listed],
              "truncated": {"ppg": max(0, len(unmatched_ppg) - cfg.max_listed), "sao2": max(0, len(unmatched_sao2) - cfg.max_listed),
                            "pigmentation": max(0, len(unmatched_pig) - cfg.max_listed)}}
    (paths.processed / QUALITY_FILE).write_text(json.dumps(quality, indent=2), encoding="utf-8")
    (paths.processed / REPORT_FILE).write_text(json.dumps(report, indent=2), encoding="utf-8")
    _publish_for_processing(paths, valid, uploads)
    return {"status": "built", **quality, "report": report}


def _subgroup_counts(valid: pd.DataFrame) -> dict:
    """Record and participant counts per ITA group, PI group and ITA x PI cell, from the SAME thresholds as everywhere else.
    A group below the conformal sufficiency minimum is labelled INSUFFICIENT DATA; nothing is balanced or filled in."""
    from ..config import CONFORMAL_CONFIG
    from ..conformal import core
    out = {"ita": [], "pi": [], "cells": [], "min_participants": CONFORMAL_CONFIG.min_cell_participants, "min_records": CONFORMAL_CONFIG.min_cell_rows}
    if valid.empty:
        ig = pg = pd.Series(dtype=object)
    else:
        i, p = core.assign_groups(valid["ita"].astype(float), valid["pi"].astype(float))
        ig, pg = pd.Series(i, index=valid.index), pd.Series(p, index=valid.index)

    def row(label, mask):
        sub = valid[mask] if len(valid) else valid
        n, k = int(len(sub)), int(sub["participant_id"].nunique()) if len(sub) else 0
        ok = k >= CONFORMAL_CONFIG.min_cell_participants and n >= CONFORMAL_CONFIG.min_cell_rows
        return {"label": label, "records": n, "participants": k, "status": "OK" if ok else "INSUFFICIENT DATA"}

    for g in core.ITA_GROUPS:
        out["ita"].append(row(g, ig == g))
    for g in core.PI_GROUPS:
        out["pi"].append(row(g, pg == g))
    for a, b in core.CELLS:
        out["cells"].append(row(f"{a} × {b}", (ig == a) & (pg == b)))
    return out


def _publish_for_processing(paths: Paths, valid: pd.DataFrame, uploads: list[dict]) -> None:
    """Make the valid research records the dataset that validation/splitting (Dataset page) works on.
    The previous splits are removed because they no longer describe the data."""
    for n in ("train", "calibration", "test"):
        (paths.processed / f"{n}.csv").unlink(missing_ok=True)
    for n in ("split_manifest.json", "data_quality.json"):
        (paths.processed / n).unlink(missing_ok=True)
    paths.raw.mkdir(parents=True, exist_ok=True)
    raw, meta = paths.raw / "dataset.csv", paths.raw / "dataset_meta.json"
    if valid.empty:
        raw.unlink(missing_ok=True)
        meta.unlink(missing_ok=True)
        return
    canon = valid[DATASET_COLUMNS].rename(columns={"timestamp": "timestamp"})
    canon.to_csv(raw, index=False)
    sha = hashlib.sha256((paths.processed / DATASET_FILE).read_bytes()).hexdigest()
    meta.write_text(json.dumps({"source_filename": f"{DATASET_FILE} (merged from {len(uploads)} upload(s))", "sha256": sha,
                                "uploaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "rows": int(len(valid))}, indent=2), encoding="utf-8")


def clear_outputs(paths: Paths | None = None) -> None:
    """Remove everything derived from the staged data (used when the last upload is removed)."""
    paths = paths or get_paths()
    for n in (DATASET_FILE, INVALID_FILE, QUALITY_FILE, REPORT_FILE):
        (paths.processed / n).unlink(missing_ok=True)
    _publish_for_processing(paths, pd.DataFrame(columns=DATASET_COLUMNS), [])


def read_quality(paths: Paths | None = None) -> dict | None:
    paths = paths or get_paths()
    try:
        return json.loads((paths.processed / QUALITY_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def read_report(paths: Paths | None = None) -> dict | None:
    paths = paths or get_paths()
    try:
        return json.loads((paths.processed / REPORT_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
