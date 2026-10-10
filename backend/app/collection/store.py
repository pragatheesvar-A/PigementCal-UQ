"""Staging area for uploads. Each upload is stored whole (nothing is merged or dropped here); the research
dataset is built from the staged tables only when the person asks for it."""

import json
from datetime import datetime, timezone

import pandas as pd

from ..ml.paths import Paths

TABLES = {"ppg": "ppg_windows.csv", "reference": "reference_sao2.csv", "pigmentation": "pigmentation.csv", "combined": "combined_records.csv"}
MANIFEST = "uploads.json"


def _dir(paths: Paths):
    d = paths.collection_dir
    d.mkdir(parents=True, exist_ok=True)
    return d


def manifest(paths: Paths) -> list[dict]:
    try:
        return json.loads((paths.collection_dir / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _save_manifest(paths: Paths, items: list[dict]) -> None:
    f = _dir(paths) / MANIFEST
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, indent=2), encoding="utf-8")
    tmp.replace(f)


def table(paths: Paths, kind: str) -> pd.DataFrame:
    f = paths.collection_dir / TABLES[kind]
    if not f.exists():
        return pd.DataFrame()
    return pd.read_csv(f, dtype=str, keep_default_na=False)


def _save_table(paths: Paths, kind: str, df: pd.DataFrame) -> None:
    f = _dir(paths) / TABLES[kind]
    if df.empty:
        f.unlink(missing_ok=True)
        return
    tmp = f.with_suffix(".tmp")
    df.to_csv(tmp, index=False)
    tmp.replace(f)


def add_upload(paths: Paths, kind: str, rows: pd.DataFrame, meta: dict) -> dict:
    """Append staged rows and record the upload (with the person's 'this is real data' attestation)."""
    items = manifest(paths)
    upload_id = f"U{max([int(i['id'][1:]) for i in items] + [0]) + 1:03d}"
    entry = {"id": upload_id, "kind": kind, "added_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "staged_rows": int(len(rows)), **meta}
    rows = rows.copy()
    rows["upload_id"] = upload_id
    existing = table(paths, kind)
    _save_table(paths, kind, pd.concat([existing, rows.astype(str)], ignore_index=True) if not existing.empty else rows.astype(str))
    items.append(entry)
    _save_manifest(paths, items)
    return entry


def remove_upload(paths: Paths, upload_id: str) -> dict | None:
    items = manifest(paths)
    entry = next((i for i in items if i["id"] == upload_id), None)
    if entry is None:
        return None
    t = table(paths, entry["kind"])
    if not t.empty:
        _save_table(paths, entry["kind"], t[t["upload_id"] != upload_id])
    _save_manifest(paths, [i for i in items if i["id"] != upload_id])
    return entry


def clear_all(paths: Paths) -> None:
    for kind in TABLES:
        _save_table(paths, kind, pd.DataFrame())
    _save_manifest(paths, [])
