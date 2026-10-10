"""Filesystem locations, anchored to the backend directory (not the working directory).

Tests override them with `set_paths()` so they never touch real data or real model artifacts.
"""

import os
from dataclasses import dataclass
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
# Where data/, models/ and results/ live. Defaults to the backend folder; set PIGMENTCAL_HOME to relocate them
# (for a deployment, or to keep test data out of the project).
HOME = Path(os.environ.get("PIGMENTCAL_HOME") or BACKEND_DIR).resolve()


@dataclass(frozen=True)
class Paths:
    processed: Path   # train.csv / calibration.csv / test.csv / split_manifest.json (dataset-processing output)
    raw: Path         # raw/dataset.csv exists only when a REAL research dataset has been loaded
    models: Path      # ridge_model.joblib, lightgbm_model.joblib
    results: Path     # model_metrics.json, test_predictions.csv
    collection: Path | None = None   # staged uploads (PPG windows, reference SaO2, pigmentation); defaults next to raw/

    @property
    def collection_dir(self) -> Path:
        return self.collection or (self.raw.parent / "collection")


DEFAULT_PATHS = Paths(
    processed=HOME / "data" / "processed",
    raw=HOME / "data" / "raw",
    models=HOME / "models",
    results=HOME / "results",
    collection=HOME / "data" / "collection",
)

_current = DEFAULT_PATHS


def get_paths() -> Paths:
    return _current


def set_paths(paths: Paths | None) -> None:
    """Override the locations (None restores the defaults)."""
    global _current
    _current = paths or DEFAULT_PATHS
