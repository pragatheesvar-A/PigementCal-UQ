"""The synthetic pipeline-test dataset: reproducible, honestly labelled, and never usable as research data."""
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

DIR = Path(__file__).resolve().parents[2] / "data" / "synthetic"
META = json.loads((DIR / "synthetic_pipeline_test_dataset.meta.json").read_text(encoding="utf-8"))


def _generator():
    spec = importlib.util.spec_from_file_location("gen_synth", DIR / "generate_synthetic_pipeline_data.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_committed_csv_matches_its_recorded_hash_and_labels():
    csv = DIR / META["file"]
    assert hashlib.sha256(csv.read_bytes()).hexdigest() == META["csv_sha256"]
    assert META["dataset_type"] == "synthetic" and META["research_validity"] == "not_for_research_validation"
    assert META["generated_for"] == "pipeline_integration_testing" and "NOT RESEARCH RESULTS" in META["label"]
    text = " ".join(META["limitations"])
    assert "CIRCULAR" in text and "device_id" in text and "NO effect" in text and "hypoxemic" in text


def test_regenerating_gives_the_identical_file(tmp_path):
    g = _generator()
    meta = g.write(tmp_path)
    got = META["versions"]
    if (got["numpy"], got["pandas"]) != (np.__version__, pd.__version__):
        pytest.skip(f"byte-identity is only guaranteed with the recorded versions (numpy {got['numpy']}, pandas {got['pandas']}); "
                    f"installed: numpy {np.__version__}, pandas {pd.__version__}")
    assert meta["csv_sha256"] == META["csv_sha256"]


def test_regenerated_values_are_identical_even_if_the_library_versions_differ(tmp_path):
    g = _generator()
    g.write(tmp_path)
    a, b = pd.read_csv(tmp_path / META["file"]), pd.read_csv(DIR / META["file"])
    pd.testing.assert_frame_equal(a, b)


def test_sao2_is_the_target_only_and_device_has_no_effect_in_the_rule():
    df = pd.read_csv(DIR / META["file"])
    assert list(df.columns) == ["participant_id", "session_id", "timestamp", "spo2", "sao2", "pi", "ita", "sqi", "motion", "device_id"]
    r = (df.sao2 - df.spo2).groupby(df.device_id).mean()
    assert abs(r.iloc[0] - r.iloc[1]) < 0.2                      # device_id carries no generative signal
    assert df.spo2.min() > 80                                    # the hypoxemic range is NOT represented (documented limitation)
