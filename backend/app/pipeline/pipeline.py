"""Dataset ingestion, cleaning, feature engineering and participant-level splitting.

  Data Collection page -> raw/dataset.csv (valid research records) -> process -> processed/{train,calibration,test}.csv

Principles: every dropped row is counted by reason (never silent); splits are by PARTICIPANT, stratified by
ITA tertile, so a participant never appears in two splits; all locations come from ml.paths (absolute,
overridable in tests); no shell commands.
"""

import json
import random

import numpy as np
import pandas as pd

from ..config import PIPELINE_CONFIG, RELIABILITY_CONFIG, PipelineConfig
from ..ml.paths import Paths, get_paths
from .features import engineer_features
from .schema import PipelineError

RAW_NAME = "dataset.csv"
META_NAME = "dataset_meta.json"
QUALITY_NAME = "data_quality.json"
MANIFEST_NAME = "split_manifest.json"
OPTIONAL_FEATURES = ("sqi", "motion")


def _atomic_write(path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def dataset_info(paths: Paths | None = None) -> dict:
    """What is loaded right now (no dataset is ever assumed)."""
    paths = paths or get_paths()
    raw = paths.raw / RAW_NAME
    if not raw.exists():
        return {"loaded": False, "rows": 0, "participants": 0, "devices": 0, "processed": False}
    meta = {}
    try:
        meta = json.loads((paths.raw / META_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    try:
        df = pd.read_csv(raw, usecols=lambda c: c in ("participant_id", "device_id"))
        if "participant_id" not in df:
            raise ValueError("no participant_id column")
    except (OSError, ValueError) as exc:                           # unreadable file: say so, never report it as usable
        return {"loaded": True, "readable": False, "verified": False, "error": f"The dataset file could not be read ({type(exc).__name__}). Build the research dataset again.",
                "file": meta.get("source_filename", RAW_NAME), "rows": 0, "participants": 0, "devices": 0, "sha256": meta.get("sha256"), "uploaded_at": meta.get("uploaded_at"), "processed": False}
    from ..governance import research_gate
    return {"loaded": True, "verified": research_gate.evaluate(paths)["verified_data"], "file": meta.get("source_filename", RAW_NAME), "rows": int(len(df)),
            "participants": int(df["participant_id"].nunique()),
            "devices": int(df["device_id"].nunique()) if "device_id" in df else 0,
            "sha256": meta.get("sha256"), "uploaded_at": meta.get("uploaded_at"),
            "processed": all((paths.processed / f"{n}.csv").exists() for n in ("train", "calibration", "test"))}


def _stratified_split(frame: pd.DataFrame, cfg: PipelineConfig) -> dict[str, list[str]]:
    """Participant-level 60/20/20 split, stratified by tertile of each participant's median ITA."""
    med = frame.groupby("participant_id")["ita"].median().sort_values(kind="stable")
    ids = list(med.index)
    n = len(ids)
    bins = [ids[: n // 3], ids[n // 3: 2 * n // 3], ids[2 * n // 3:]]
    rng = random.Random(cfg.seed)
    out = {"train": [], "calibration": [], "test": []}
    for b in bins:
        b = sorted(b)
        rng.shuffle(b)
        k_cal = round(cfg.calibration_fraction * len(b))
        k_test = round((1 - cfg.train_fraction - cfg.calibration_fraction) * len(b))
        k_cal, k_test = max(k_cal, 1 if len(b) >= 3 else 0), max(k_test, 1 if len(b) >= 3 else 0)
        out["calibration"] += b[:k_cal]
        out["test"] += b[k_cal:k_cal + k_test]
        out["train"] += b[k_cal + k_test:]
    return out


def process_dataset(paths: Paths | None = None, cfg: PipelineConfig = PIPELINE_CONFIG) -> dict:
    paths = paths or get_paths()
    raw = paths.raw / RAW_NAME
    if not raw.exists():
        raise PipelineError("no_dataset", "No research dataset is loaded. Upload your data and build the research dataset on the Data Collection page first.")
    df = pd.read_csv(raw, low_memory=False)
    n0 = len(df)
    rc = RELIABILITY_CONFIG

    for c in ("spo2", "sao2", "pi", "ita", "sqi", "motion"):
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["participant_id"] = df["participant_id"].astype("string").str.strip()

    # Row validity, evaluated in this order; each row is counted under the FIRST rule it breaks.
    rules = [
        ("missing_participant_id", df["participant_id"].isna() | (df["participant_id"] == "")),
        ("missing_or_invalid_spo2", ~np.isfinite(df["spo2"].astype(float))),
        ("missing_or_invalid_sao2", ~np.isfinite(df["sao2"].astype(float))),
        ("missing_or_invalid_pi", ~np.isfinite(df["pi"].astype(float))),
        ("missing_or_invalid_ita", ~np.isfinite(df["ita"].astype(float))),
        ("spo2_or_sao2_out_of_range", (df["spo2"] < cfg.sat_min) | (df["spo2"] > cfg.sat_max) | (df["sao2"] < cfg.sat_min) | (df["sao2"] > cfg.sat_max)),
        ("pi_not_positive_or_above_max", (df["pi"] <= 0) | (df["pi"] > rc.pi_max)),
        ("ita_out_of_range", (df["ita"] < rc.ita_min) | (df["ita"] > rc.ita_max)),
    ]
    dropped: dict[str, int] = {}
    keep = pd.Series(True, index=df.index)
    for name, bad in rules:
        hit = bad.fillna(True) & keep
        dropped[name] = int(hit.sum())
        keep &= ~hit
    dup = df.duplicated(keep="first") & keep
    dropped["exact_duplicate_row"] = int(dup.sum())
    keep &= ~dup
    df = df[keep].copy()

    excluded_optional = {}
    for c in OPTIONAL_FEATURES:
        if c in df and df[c].isna().any():
            excluded_optional[c] = f"{int(df[c].isna().sum())} of {len(df)} rows missing — column not used as a predictor"
            df = df.drop(columns=[c])

    n_part = int(df["participant_id"].nunique()) if len(df) else 0
    if n_part < cfg.min_participants:
        raise PipelineError("too_few_participants",
                            f"Only {n_part} participant(s) have valid rows; at least {cfg.min_participants} are needed to split into "
                            "train / calibration / test.", "dataset", {"dropped_rows": dropped})

    # Centralized feature pipeline (one function, used for training and for live prediction)
    recs = []
    for row in df.to_dict("records"):
        f = engineer_features({k: row.get(k) for k in ("spo2", "pi", "ita", "sqi", "motion")})
        f["participant_id"] = str(row["participant_id"])
        f["session_id"] = "" if pd.isna(row.get("session_id")) else str(row.get("session_id"))      # identifier only, never a predictor
        f["sao2_target"] = float(row["sao2"])
        if "device_id" in row and pd.notna(row["device_id"]):
            f["device_id"] = row["device_id"]
        recs.append(f)
    feat = pd.DataFrame(recs)
    feat["participant_id"] = feat["participant_id"].astype(str)

    split = _stratified_split(feat, cfg)
    paths.processed.mkdir(parents=True, exist_ok=True)
    counts = {}
    for name, ids in split.items():
        part = feat[feat["participant_id"].isin(set(ids))]
        part.to_csv(paths.processed / f"{name}.csv", index=False)
        counts[name] = {"participants": len(ids), "rows": int(len(part))}
    manifest = {"train_participants": split["train"], "calibration_participants": split["calibration"],
                "test_participants": split["test"], "random_seed": cfg.seed,
                "stratified_by": "tertile of each participant's median ITA",
                "fractions": {"train": cfg.train_fraction, "calibration": cfg.calibration_fraction,
                              "test": round(1 - cfg.train_fraction - cfg.calibration_fraction, 6)}}
    _atomic_write(paths.processed / MANIFEST_NAME, json.dumps(manifest))
    quality = {"rows_in": int(n0), "rows_kept": int(len(df)), "rows_dropped": int(n0 - len(df)), "dropped_by_reason": dropped,
               "excluded_optional_predictors": excluded_optional, "participants": n_part, "splits": counts,
               "predictors": [c for c in feat.columns if c not in ("participant_id", "sao2_target", "device_id")]}
    _atomic_write(paths.processed / QUALITY_NAME, json.dumps(quality, indent=2))
    return {"status": "success", **quality}


def read_quality(paths: Paths | None = None) -> dict | None:
    paths = paths or get_paths()
    try:
        return json.loads((paths.processed / QUALITY_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
