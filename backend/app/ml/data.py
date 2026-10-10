"""Loading and guarding the processed dataset splits.

Scientific rules enforced here:
  * the target (SaO2) is never a predictor, and participant_id is never a predictor;
  * participants never appear in more than one of train / calibration / test;
  * missing or non-finite values are reported, never silently imputed or dropped;
  * nothing is trained unless a research dataset has actually been loaded.
"""

import contextlib
import hashlib
import pickle
from pathlib import Path
import json

import numpy as np
import pandas as pd

from .paths import Paths

# Predictors that every dataset provides (SpO2, PI and objective pigmentation and their interactions).
CORE_FEATURES = ["spo2", "d", "pi", "log_pi", "ita", "ita_x_d", "log_pi_x_d", "ita_x_log_pi"]
# Used only when the dataset has them AND they actually vary (a constant column carries no information).
OPTIONAL_FEATURES = ["sqi", "motion"]
FEATURES = CORE_FEATURES + OPTIONAL_FEATURES          # every predictor the pipeline can ever produce
RAW_FOR = {"sqi": "sqi", "motion": "motion"}          # optional predictors are raw inputs themselves
# Processed data stores SaO2 under this column name; "sao2" in the specification refers to it.
TARGET_COL = "sao2_target"
GROUP_COL = "participant_id"
SPLITS = ("train", "calibration", "test")

LOADED_LABEL = "Empirical evaluation on the loaded dataset — not clinical evidence."
NONE_LABEL = "NO RESEARCH DATASET LOADED"
UNVERIFIED_LABEL = "UNVERIFIED DATA — NOT A RESEARCH RESULT"


ARTIFACT_READ_ERRORS = (OSError, ValueError, EOFError, KeyError, IndexError, AttributeError, ImportError, pickle.UnpicklingError)


class ModelError(Exception):
    """A user-fixable problem, reported with a stable code and a human-readable message."""

    def __init__(self, code: str, message: str, field: str = "model"):
        super().__init__(message)
        self.code, self.message, self.field = code, message, field

    def as_error(self) -> dict:
        return {"field": self.field, "code": self.code, "message": self.message}


def assert_no_target_leakage(features: list[str]) -> None:
    """Fail loudly if the target, or anything that looks like it or a participant id, is a predictor."""
    bad = [f for f in features if f == TARGET_COL or f == GROUP_COL or "sao2" in f.lower() or "participant" in f.lower() or "session" in f.lower()]
    if bad:
        raise ModelError("target_leakage", f"Target leakage: {bad} must never be used as predictors.", "features")


@contextlib.contextmanager
def readable(what: str, fix: str = "Train the models again."):
    """Unreadable or inconsistent saved files become a clear, actionable ModelError instead of an HTTP 500."""
    try:
        yield
    except ModelError:
        raise
    except ARTIFACT_READ_ERRORS as exc:
        raise ModelError("artifacts_unreadable", f"The saved {what} could not be read ({type(exc).__name__}). {fix}") from exc


def _sidecar(path: Path) -> Path:
    return path.with_name(path.name + ".sha256")


def save_artifact(obj, path: Path) -> None:
    """Save a model artifact (joblib = pickle) together with its SHA-256, so a changed or foreign file is never loaded later."""
    import joblib
    joblib.dump(obj, path)
    _sidecar(path).write_text(file_sha256(path), encoding="utf-8")


def load_artifact(path: Path):
    """Load a model artifact ONLY if its SHA-256 sidecar exists and matches. joblib/pickle can execute code when loading, so a file
    that was not written by save_artifact() in this app's own models folder is refused. No API accepts model uploads."""
    import joblib
    side = _sidecar(path)
    if not side.exists():
        raise ModelError("artifact_untrusted", f"{path.name} has no integrity hash (it was not saved by this version of the app). Train again; it was not loaded.")
    if side.read_text(encoding="utf-8").strip() != file_sha256(path):
        raise ModelError("artifact_untrusted", f"{path.name} does not match its recorded SHA-256: it was changed after it was saved. It was not loaded. Train again.")
    return joblib.load(path)


def file_sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _validate_frame(name: str, df: pd.DataFrame) -> None:
    need = CORE_FEATURES + [TARGET_COL, GROUP_COL]
    missing = [c for c in need if c not in df.columns]
    if missing:
        raise ModelError("missing_columns", f"The {name} split is missing required column(s): {', '.join(missing)}. "
                         "Re-run the dataset processing step.", name)
    if len(df) == 0:
        raise ModelError("empty_split", f"The {name} split has no rows.", name)
    num = CORE_FEATURES + [TARGET_COL] + [c for c in OPTIONAL_FEATURES if c in df.columns]
    for c in num:
        if not pd.api.types.is_numeric_dtype(df[c]):
            raise ModelError("non_numeric", f"Column '{c}' in the {name} split is not numeric.", name)
    values = df[num].to_numpy(dtype=float)
    bad = ~np.isfinite(values)
    if bad.any():
        cols = {c: int(bad[:, i].sum()) for i, c in enumerate(num) if bad[:, i].any()}
        raise ModelError("missing_values", f"The {name} split has missing or non-finite values {cols}. "
                         "They are not imputed or dropped silently — fix them in the dataset pipeline.", name)
    if df[GROUP_COL].isna().any():
        raise ModelError("missing_values", f"The {name} split has rows without a participant_id.", name)


def load_splits(paths: Paths) -> dict[str, pd.DataFrame]:
    """Load train / calibration / test, validate them, and verify there is no participant leakage."""
    frames = {}
    for name in SPLITS:
        f = paths.processed / f"{name}.csv"
        if not f.exists():
            raise ModelError("no_processed_data",
                             "Processed data not found. Load a dataset and run the processing step first.", name)
        df = pd.read_csv(f)
        _validate_frame(name, df)
        df[GROUP_COL] = df[GROUP_COL].astype(str)
        frames[name] = df
    sets = {n: set(d[GROUP_COL]) for n, d in frames.items()}
    for a, b in (("train", "calibration"), ("train", "test"), ("calibration", "test")):
        both = sets[a] & sets[b]
        if both:
            raise ModelError("participant_leakage",
                             f"LEAKAGE: {len(both)} participant(s) appear in both the {a} and {b} splits "
                             f"(e.g. {sorted(both)[:3]}). Splits must be participant-disjoint.", "splits")
    return frames


def select_features(frames: dict[str, pd.DataFrame]) -> tuple[list[str], dict[str, str]]:
    """Core predictors plus any optional predictor that exists in every split and varies in the training split."""
    feats, excluded = list(CORE_FEATURES), {}
    for c in OPTIONAL_FEATURES:
        if not all(c in d.columns for d in frames.values()):
            excluded[c] = "not present in the dataset"
        elif float(frames["train"][c].std(ddof=0)) < 1e-12:
            excluded[c] = "constant in the training split (carries no information)"
        else:
            feats.append(c)
    assert_no_target_leakage(feats)
    return feats, excluded


def split_summary(paths: Paths, frames: dict[str, pd.DataFrame]) -> dict:
    out = {}
    for n, d in frames.items():
        out[n] = {"rows": int(len(d)), "participants": int(d[GROUP_COL].nunique()),
                  "sha256": file_sha256(paths.processed / f"{n}.csv")}
    return out


def current_hashes(paths: Paths) -> dict[str, str] | None:
    try:
        return {n: file_sha256(paths.processed / f"{n}.csv") for n in SPLITS}
    except FileNotFoundError:
        return None


def manifest_seed(paths: Paths):
    try:
        return json.loads((paths.processed / "split_manifest.json").read_text()).get("random_seed")
    except (OSError, ValueError):
        return None


def research_quality(paths: Paths) -> dict | None:
    """The record written when the research dataset was built from attested uploads (research_data_quality.json)."""
    try:
        return json.loads((paths.processed / "research_data_quality.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def dataset_provenance(paths: Paths) -> dict:
    """Is a research dataset loaded, and do the processed splits come from it?

    kind = LOADED   a dataset built from attested real uploads is loaded and the processed splits only contain its participants;
           UNVERIFIED a dataset file exists but was not built from attested uploads (e.g. dropped in by hand) — never research;
           NONE     no dataset is loaded (nothing is generated or assumed);
           MISMATCH processed splits exist that the loaded dataset cannot account for (re-run processing)."""
    raw = paths.raw / "dataset.csv"
    if not raw.exists():
        return {"kind": "NONE", "label": NONE_LABEL,
                "reason": "No research dataset is loaded. Upload one on the Dataset page; nothing is generated or simulated."}
    meta = {}
    try:
        meta = json.loads((paths.raw / "dataset_meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    info = {"file": meta.get("source_filename", "dataset.csv"), "sha256": meta.get("sha256")}
    q = research_quality(paths)
    if not (q and q.get("valid_records", 0) > 0 and q.get("sources")):
        return {"kind": "UNVERIFIED", "label": UNVERIFIED_LABEL,
                "reason": "This dataset was not built on the Data Collection page from uploads confirmed as real collected data, so it cannot be treated as research data.", **info}
    processed_files = [paths.processed / f"{n}.csv" for n in SPLITS]
    if not all(f.exists() for f in processed_files):
        return {"kind": "LOADED", "label": LOADED_LABEL, "reason": "Dataset loaded; processing has not been run yet.", **info}
    try:
        ids = set(pd.read_csv(raw, usecols=[GROUP_COL])[GROUP_COL].astype(str))
        processed = set()
        for f in processed_files:
            processed |= set(pd.read_csv(f, usecols=[GROUP_COL])[GROUP_COL].astype(str))
    except (OSError, ValueError, KeyError):
        return {"kind": "MISMATCH", "label": "PROCESSED DATA COULD NOT BE VERIFIED", "reason": "Re-run the processing step.", **info}
    if processed and processed <= ids:
        return {"kind": "LOADED", "label": LOADED_LABEL, "reason": "Processed splits were derived from the loaded dataset.", **info}
    return {"kind": "MISMATCH", "label": "PROCESSED DATA DOES NOT MATCH THE LOADED DATASET",
            "reason": "The processed splits contain participants that are not in the loaded dataset. Re-run the processing step.", **info}
