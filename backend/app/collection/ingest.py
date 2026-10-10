"""Stage an uploaded CSV: PPG recording, reference SaO2, pigmentation, or an already-combined file.

Nothing is invented here. PPG recordings are turned into analysis windows with the SAME analysis the Live Monitor
uses; reference and pigmentation rows are kept as given, with any problem recorded in `invalid_reason` (flagged,
never silently dropped). ITA comes from the pigmentation module.
"""

import hashlib
import io
import math

import numpy as np
import pandas as pd

from ..config import COLLECTION_CONFIG, LIVE_CONFIG, RELIABILITY_CONFIG, CollectionConfig
from ..ml.paths import Paths, get_paths
from ..services.live import DEVICE_FOR_SOURCE, SOURCES, analyze_live
from ..services.pigmentation import calculate_ita
from ..services.validation import InputValidationError
from . import mapping as mp
from . import store
from .rules import CollectionError, id_problem, safe_filename, is_missing, numeric, parse_start, parse_times, private_columns


# ------------------------------------------------------------------ small helpers
def _read(data: bytes, cfg: CollectionConfig) -> pd.DataFrame:
    if len(data) == 0:
        raise CollectionError("empty_file", "The uploaded file is empty.")
    if len(data) > cfg.max_upload_mb * 1024 * 1024:
        raise CollectionError("file_too_large", f"The file is larger than {cfg.max_upload_mb} MB.")
    if data.count(b"\n") > cfg.max_upload_rows + 1:
        raise CollectionError("too_many_rows", f"The file has more than {cfg.max_upload_rows:,} rows. Split it into smaller files.")
    if b"dataset_type=virtual_hardware_simulation" in data[:512]:       # Live Monitor output of the virtual sensor: never research data
        raise CollectionError("virtual_simulation", "This file was produced by the virtual MAX30102 simulation (dataset_type=virtual_hardware_simulation, "
                              "not_for_research_validation). It is not real data and cannot be uploaded as research data.", "file")
    try:
        df = pd.read_csv(io.BytesIO(data), dtype=str, keep_default_na=False, skipinitialspace=True)
    except (UnicodeDecodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise CollectionError("unreadable_csv", f"The file could not be read as CSV ({exc.__class__.__name__}).") from exc
    df.columns = [str(c).strip() for c in df.columns]
    if df.empty or len(df.columns) < 2:
        raise CollectionError("unreadable_csv", "The file has no data rows or too few columns.")
    return df


def _ids(df: pd.DataFrame, applied: dict, params: dict, field: str, required: bool) -> pd.Series:
    """participant_id / session_id from a mapped column, or one value given for the whole file."""
    if field in applied:
        s = df[applied[field]].astype(str).str.strip()
    elif not is_missing(params.get(field)):
        s = pd.Series([str(params[field]).strip()] * len(df), index=df.index)
    elif required:
        raise CollectionError("missing_id", f"{field} is required: enter it for this file, or map a column that contains it.", field)
    else:
        return pd.Series([""] * len(df), index=df.index)
    return s


def _check_ids(values: pd.Series, field: str, strict: bool = True) -> None:
    """Reject missing / personal-looking / badly formed identifiers (strict) so they are fixed at the source."""
    for v in pd.unique(values):
        problem = id_problem(v)
        if problem and (strict or problem != "missing"):
            raise CollectionError("bad_id", f"{field} '{v}': {problem}.", field)


def _no_private_mapping(applied: dict) -> None:
    from .rules import PRIVATE_RE
    for f in ("participant_id", "session_id"):
        if f in applied and PRIVATE_RE.search(applied[f]):
            raise CollectionError("personal_data", f"Column '{applied[f]}' looks like personal data. Only anonymous IDs (e.g. P001) may be used as {f}.", "mapping")


def _ita_from_lab(L, a, b) -> tuple[float | None, str]:
    """ITA via the pigmentation module. Returns (ita, problem)."""
    try:
        return float(calculate_ita({"L": L, "a": a, "b": b})["ita"]), ""
    except InputValidationError as exc:
        return None, "; ".join(e["message"] for e in exc.errors)


def _sessions_conflict(paths: Paths, new_pairs: set[tuple[str, str]]) -> None:
    """A session belongs to ONE participant, and a (participant, session) recording may be uploaded only once."""
    seen: dict[str, set[str]] = {}
    for kind in ("ppg", "combined", "reference"):
        t = store.table(paths, kind)
        if not t.empty:
            for p, s in t[["participant_id", "session_id"]].drop_duplicates().itertuples(index=False):
                if s:
                    seen.setdefault(s, set()).add(p)
    for p, s in new_pairs:
        if s and seen.get(s, set()) - {p}:
            raise CollectionError("duplicate_session", f"session_id '{s}' is already used by participant {sorted(seen[s] - {p})[0]}. A session belongs to one participant.", "session_id")


# ------------------------------------------------------------------ PPG
def _stage_ppg(df, applied, params, paths, cfg):
    ir = numeric(df[applied["ir"]])
    ok = ir.notna().to_numpy()
    end = len(ok)
    while end > 0 and not ok[end - 1]:
        end -= 1
    notes = [f"{len(ok) - end} incomplete trailing row(s) at the end were ignored."] if end < len(ok) else []
    df, ir = df.iloc[:end].reset_index(drop=True), ir.iloc[:end].reset_index(drop=True)
    if end < 20:
        raise CollectionError("too_short", "The recording has too few samples.")
    if ir.isna().any():
        k = int(np.flatnonzero(ir.isna().to_numpy())[0])
        raise CollectionError("invalid_samples", f"The infrared column has {int(ir.isna().sum())} non-numeric sample(s) (first at data row {k + 1}). Fix or remove them.", "ir")
    red = None
    if "red" in applied:
        red = numeric(df[applied["red"]])
        if red.isna().any():
            raise CollectionError("invalid_samples", f"The red column has {int(red.isna().sum())} non-numeric sample(s).", "red")
    acc = None
    if all(f in applied for f in ("ax", "ay", "az")):
        acc = np.column_stack([numeric(df[applied[f]]).to_numpy(float) for f in ("ax", "ay", "az")])
    elif "accel" in applied:
        acc = numeric(df[applied["accel"]]).to_numpy(float)
    if acc is not None and not np.isfinite(acc).all():
        raise CollectionError("invalid_samples", "The accelerometer columns contain non-numeric values.", "accel")
    dev_spo2 = numeric(df[applied["spo2"]]).to_numpy(float) if "spo2" in applied else None

    if "timestamp" in applied:
        t, basis = parse_times(df[applied["timestamp"]], applied["timestamp"])
    else:
        fs = params.get("fs")
        if fs is None or not (isinstance(fs, (int, float)) and math.isfinite(fs) and 20 <= fs <= 1000):
            raise CollectionError("no_time", "This file has no time column: enter its sampling rate (20–1000 Hz).", "fs")
        t, basis = np.arange(end) / float(fs), "relative"
    start = parse_start(params.get("recording_start"))
    if basis == "relative" and start is not None:
        t, basis = t + start, "absolute"

    pid = _ids(df, applied, params, "participant_id", True)
    sid = _ids(df, applied, params, "session_id", True)
    _check_ids(pid, "participant_id")
    _check_ids(sid, "session_id")
    pairs = {(p, s) for p, s in zip(pid, sid)}
    _sessions_conflict(paths, pairs)
    have = store.table(paths, "ppg")
    if not have.empty:
        dup = pairs & set(map(tuple, have[["participant_id", "session_id"]].drop_duplicates().itertuples(index=False)))
        if dup:
            p, s = sorted(dup)[0]
            raise CollectionError("duplicate_session", f"Session {s} of participant {p} was already uploaded. Remove that upload first if you want to replace it.", "session_id")

    source = params.get("source") or "esp32"
    if source not in SOURCES:
        raise CollectionError("bad_source", f"source must be one of: {', '.join(SOURCES)}.", "source")
    device = applied.get("device_id")
    rows, sessions = [], []
    W = LIVE_CONFIG.window_seconds
    for (p, s), idx in pd.DataFrame({"p": pid, "s": sid}).groupby(["p", "s"], sort=False).groups.items():
        idx = np.asarray(idx)
        tg = t[idx]
        if not np.all(np.diff(tg) > 0):
            raise CollectionError("not_increasing", f"Timestamps in session {s} are not strictly increasing.", "timestamp")
        irg, redg = ir.to_numpy(float)[idx], (red.to_numpy(float)[idx] if red is not None else None)
        accg = acc[idx] if acc is not None else None
        spg = dev_spo2[idx] if dev_spo2 is not None else None
        dev = str(df[device].iloc[idx[0]]).strip() if device else (params.get("device_id") or DEVICE_FOR_SOURCE[source])
        n_win = {"GOOD": 0, "MODERATE": 0, "POOR": 0, "FAILED": 0}
        w0 = tg[0]
        while w0 + W <= tg[-1] + 1e-9:
            i0, i1 = int(np.searchsorted(tg, w0, "left")), int(np.searchsorted(tg, w0 + W, "right"))
            w0 += cfg.hop_seconds
            if i1 - i0 < 20:
                continue
            seg_t = tg[i0:i1]
            req = {"ir": irg[i0:i1].tolist(), "t": (seg_t - seg_t[0]).tolist(), "source": source}
            if redg is not None:
                req["red"] = redg[i0:i1].tolist()
            if accg is not None:
                req["accel"] = accg[i0:i1].tolist()
            rec = {"participant_id": p, "session_id": s, "device_id": dev, "timestamp_s": f"{seg_t[-1]:.6f}", "time_basis": basis,
                   "spo2": "", "spo2_source": "", "pi": "", "sqi": "", "motion": "", "motion_state": "", "signal_quality": "", "analysis_note": "",
                   "source_file": params.get("filename", "")}
            try:
                r = analyze_live(req)
            except InputValidationError as exc:
                rec["analysis_note"] = "analysis failed: " + "; ".join(e["message"] for e in exc.errors)
                n_win["FAILED"] += 1
                rows.append(rec)
                continue
            if r.get("status") != "ok":
                rec["analysis_note"] = "window too short to analyze"
                n_win["FAILED"] += 1
                rows.append(rec)
                continue
            rec.update(sqi=f"{r['sqi']:.2f}", motion=f"{r['motion_score']:.2f}", motion_state=r["motion_state"], signal_quality=r["signal_quality"])
            if r["pi_estimate"] is not None:
                rec["pi"] = f"{r['pi_estimate']:.4f}"
            if spg is not None and np.isfinite(spg[i0:i1]).any():
                rec.update(spo2=f"{np.nanmedian(spg[i0:i1]):.2f}", spo2_source="device column")
            elif r["spo2"]["estimate"] is not None:
                rec.update(spo2=f"{r['spo2']['estimate']:.2f}", spo2_source="uncalibrated red/IR estimate")
            else:
                rec["analysis_note"] = r["spo2"]["note"]
            n_win[r["signal_quality"]] += 1
            rows.append(rec)
        sessions.append({"participant_id": p, "session_id": s, "samples": int(len(idx)), "duration_s": round(float(tg[-1] - tg[0]), 1),
                         "windows": int(sum(n_win.values())), **{k.lower(): v for k, v in n_win.items()}})
    if not rows:
        raise CollectionError("no_windows", f"No analysis windows could be made: each session needs at least {W:g} s of signal.", "ir")
    fs_est = float(1.0 / np.median(np.diff(t[: min(len(t), 2000)])))
    return pd.DataFrame(rows), {"samples": int(end), "windows": len(rows), "sessions": sessions, "estimated_fs_hz": round(fs_est, 1),
                                "time_basis": basis, "has_red": red is not None, "has_accelerometer": acc is not None,
                                "spo2_from": "device column" if dev_spo2 is not None else ("red/IR estimate" if red is not None else "none"), "notes": notes}


# ------------------------------------------------------------------ reference SaO2
def _stage_reference(df, applied, params, paths, cfg):
    pid = _ids(df, applied, params, "participant_id", True)
    sid = _ids(df, applied, params, "session_id", True)
    sao2 = numeric(df[applied["sao2"]])
    raw_sao2 = df[applied["sao2"]]
    reasons = [[] for _ in range(len(df))]
    for k in range(len(df)):
        for field, v in (("participant_id", pid.iloc[k]), ("session_id", sid.iloc[k])):
            p = id_problem(v)
            if p:
                reasons[k].append(f"{field}: {p}")
        if is_missing(raw_sao2.iloc[k]):
            reasons[k].append("missing SaO₂")
        elif pd.isna(sao2.iloc[k]):
            reasons[k].append("SaO₂ is not a number")
        elif not (0 < sao2.iloc[k] <= 100):
            reasons[k].append("SaO₂ out of range (must be > 0 and ≤ 100)")
    t = np.full(len(df), np.nan)
    basis = "none"
    if "timestamp" in applied:
        col = df[applied["timestamp"]]
        present = ~col.map(is_missing)
        if present.any():
            tv, basis = parse_times(col[present], applied["timestamp"])
            t[present.to_numpy()] = tv
    ok_pairs = {(p, s) for p, s, r in zip(pid, sid, reasons) if not r}
    _sessions_conflict(paths, ok_pairs)
    out = pd.DataFrame({"participant_id": pid.values, "session_id": sid.values, "timestamp_s": [("" if np.isnan(x) else f"{x:.6f}") for x in t],
                        "time_basis": basis, "sao2": ["" if pd.isna(x) else f"{x:.4f}" for x in sao2], "source_file": params.get("filename", "")})
    dup = out.duplicated(["participant_id", "session_id", "timestamp_s"], keep="first") & (out["timestamp_s"] != "")
    for k in np.flatnonzero(dup.to_numpy()):
        reasons[k].append("duplicate reference (same participant, session and time)")
    out["invalid_reason"] = ["; ".join(r) for r in reasons]
    return out, {"rows": len(out), "flagged_rows": int((out["invalid_reason"] != "").sum()), "time_basis": basis,
                 "has_timestamps": bool((out["timestamp_s"] != "").any())}


# ------------------------------------------------------------------ pigmentation
def _lab_rows(df, applied, params, with_session: bool):
    pid = _ids(df, applied, params, "participant_id", True)
    sid = _ids(df, applied, params, "session_id", with_session)
    Lc, ac, bc = (numeric(df[applied[f]]) if f in applied else pd.Series(np.nan, index=df.index) for f in ("L", "a", "b"))
    given = numeric(df[applied["ita"]]) if "ita" in applied else pd.Series(np.nan, index=df.index)
    rows = []
    for k in range(len(df)):
        reasons, warning = [], ""
        for field, v, req in (("participant_id", pid.iloc[k], True), ("session_id", sid.iloc[k], with_session)):
            p = id_problem(v) if (req or not is_missing(v)) else None
            if p:
                reasons.append(f"{field}: {p}")
        L, a, b, g = Lc.iloc[k], ac.iloc[k], bc.iloc[k], given.iloc[k]
        has_lab = not (pd.isna(L) and pd.isna(a) and pd.isna(b))
        ita = None
        if has_lab:
            ita_c, problem = _ita_from_lab(None if pd.isna(L) else float(L), None if pd.isna(a) else float(a), None if pd.isna(b) else float(b))
            if problem:
                reasons.append(problem)
            ita = ita_c
        if not pd.isna(g):
            if not (RELIABILITY_CONFIG.ita_min <= g <= RELIABILITY_CONFIG.ita_max):
                reasons.append(f"ITA {g:g}° outside the supported range ({RELIABILITY_CONFIG.ita_min:g}° to {RELIABILITY_CONFIG.ita_max:g}°)")
            else:
                if ita is not None and abs(ita - g) > COLLECTION_CONFIG.ita_consistency_tol_deg:
                    warning = f"supplied ITA {g:.1f}° differs from the {ita:.1f}° computed from L*, a*, b*"
                ita = float(g)                        # a supplied ITA is used as given
        elif not has_lab and "ita" in applied:
            reasons.append("missing ITA")
        if ita is None and not reasons:
            reasons.append("missing ITA (no ITA and no complete L*, a*, b*)")
        rows.append({"participant_id": pid.iloc[k], "session_id": sid.iloc[k],
                     "L": "" if pd.isna(L) else f"{L:.4f}", "a": "" if pd.isna(a) else f"{a:.4f}", "b": "" if pd.isna(b) else f"{b:.4f}",
                     "ita": "" if ita is None else f"{ita:.4f}", "warning": warning, "invalid_reason": "; ".join(dict.fromkeys(reasons))})
    return pd.DataFrame(rows)


def _stage_pigmentation(df, applied, params, paths, cfg):
    out = _lab_rows(df, applied, params, with_session=False)
    out["location"] = df[applied["location"]].astype(str).str.strip().values if "location" in applied else ""
    out["source_file"] = params.get("filename", "")
    _sessions_conflict(paths, {(p, s) for p, s, r in zip(out["participant_id"], out["session_id"], out["invalid_reason"]) if not r and s})
    return out, {"rows": len(out), "flagged_rows": int((out["invalid_reason"] != "").sum()), "participants": int(out["participant_id"].nunique()),
                 "computed_from_lab": int(((out["L"] != "") & (out["ita"] != "") & ("ita" not in applied)).sum()),
                 "warnings": int((out["warning"] != "").sum())}


# ------------------------------------------------------------------ combined
def _stage_combined(df, applied, params, paths, cfg):
    base = _lab_rows(df, applied, params, with_session=True) if any(f in applied for f in ("ita", "L", "a", "b")) else None
    pid = _ids(df, applied, params, "participant_id", True)
    sid = _ids(df, applied, params, "session_id", True)
    if base is None:
        base = pd.DataFrame({"participant_id": pid.values, "session_id": sid.values, "L": "", "a": "", "b": "", "ita": "", "warning": "", "invalid_reason": ""})
        base["invalid_reason"] = [("" if not id_problem(p) and not id_problem(s) else "invalid participant_id/session_id") for p, s in zip(pid, sid)]
    out = base.copy()
    out["pi"] = numeric(df[applied["pi"]]).map(lambda x: "" if pd.isna(x) else f"{x:.6f}").values if "pi" in applied else ""
    for f in ("spo2", "sao2", "sqi", "motion"):
        out[f] = numeric(df[applied[f]]).map(lambda x: "" if pd.isna(x) else f"{x:.6f}").values if f in applied else ""
    out["device_id"] = df[applied["device_id"]].astype(str).str.strip().values if "device_id" in applied else (params.get("device_id") or "")
    t, basis = (np.full(len(df), np.nan), "none")
    if "timestamp" in applied:
        present = ~df[applied["timestamp"]].map(is_missing)
        if present.any():
            tv, basis = parse_times(df[applied["timestamp"]][present], applied["timestamp"])
            t[present.to_numpy()] = tv
    out["timestamp_s"] = ["" if np.isnan(x) else f"{x:.6f}" for x in t]
    out["time_basis"] = basis
    out["source_file"] = params.get("filename", "")
    _sessions_conflict(paths, {(p, s) for p, s in zip(out["participant_id"], out["session_id"]) if not id_problem(p) and not id_problem(s)})
    return out, {"rows": len(out), "flagged_rows": int((out["invalid_reason"] != "").sum()), "participants": int(out["participant_id"].nunique()),
                 "sessions": int(out[["participant_id", "session_id"]].drop_duplicates().shape[0]),
                 "has_ita_columns": any(f in applied for f in ("ita", "L", "a", "b"))}


STAGERS = {"ppg": _stage_ppg, "reference": _stage_reference, "pigmentation": _stage_pigmentation, "combined": _stage_combined}


def add_upload(kind: str, data: bytes, params: dict, paths: Paths | None = None, cfg: CollectionConfig = COLLECTION_CONFIG) -> dict:
    """Validate and stage one upload. `params`: filename, mapping, attested_real, participant_id, session_id, device_id,
    source, fs, recording_start. Raises CollectionError (with mapping help when columns are missing)."""
    paths = paths or get_paths()
    params = {**params, "filename": safe_filename(params.get("filename"))}                 # never trust a path or a formula in a file name
    if not params["filename"].lower().endswith((".csv", ".txt")):
        raise CollectionError("bad_extension", "Upload a CSV file (.csv or .txt). Other file types are not accepted.", "file")
    if kind not in mp.KINDS:
        raise CollectionError("bad_kind", f"Upload kind must be one of: {', '.join(mp.KINDS)}.", "kind")
    if params.get("attested_real") is not True:
        raise CollectionError("not_attested", "Confirm that this is real collected data (not simulated) before uploading it.", "attested_real")
    df = _read(data, cfg)
    sha = hashlib.sha256(data).hexdigest()
    if any(i["sha256"] == sha and i["kind"] == kind for i in store.manifest(paths)):
        raise CollectionError("duplicate_file", "This exact file was already uploaded. Remove the earlier upload first if you want to replace it.", "file")
    applied = mp.resolve(list(df.columns), kind, params.get("mapping"))
    _no_private_mapping(applied)
    ignored_private = private_columns(list(df.columns), set(applied.values()))
    rows, summary = STAGERS[kind](df, applied, params, paths, cfg)
    meta = {"filename": params.get("filename") or "upload.csv", "sha256": sha, "attested_real": True, "mapping": applied,
            "ignored_personal_columns": ignored_private, "summary": summary,
            "participant_id": params.get("participant_id"), "session_id": params.get("session_id")}
    entry = store.add_upload(paths, kind, rows, meta)
    return {"status": "staged", "upload": entry, "ignored_personal_columns": ignored_private,
            "note": "Staged only. Build the research dataset to merge the sources."}
