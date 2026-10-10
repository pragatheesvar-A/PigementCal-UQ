"""SOFTWARE INTEGRATION TEST ONLY (not hardware validation, not research data).

Chain: virtual MAX30102 -> serial parser -> buffer -> SQI / PI (frontend vitest: virtualSensor.test.ts, tests the producer side up to the recorder
and CSV) -> recorded CSV -> Data Collection refusal -> CSV validator (this file, the consumer side). The two halves are tied together by reading
the marker values and the CSV header straight from the TypeScript sources, so a change on either side breaks this test.
"""
import importlib.util
import re
from pathlib import Path

import numpy as np
import pytest

from app.collection import ingest, store
from app.collection.rules import CollectionError
from app.ml.paths import Paths

ROOT = Path(__file__).resolve().parents[2]
VS = (ROOT / "frontend/src/lib/virtualSensor.ts").read_text(encoding="utf-8")
SESSION = (ROOT / "frontend/src/lib/session.ts").read_text(encoding="utf-8")


def _meta() -> dict:
    block = re.search(r"export const VIRTUAL_META = \{(.*?)\} as const;", VS, re.S).group(1)
    return dict(re.findall(r'(\w+):\s*"([^"]+)"', block))


def _header() -> str:
    return ",".join(re.findall(r'"(\w+)"', re.search(r"export const CSV_HEADER = \[(.*?)\]", SESSION, re.S).group(1)))


def _virtual_csv(n=600) -> str:
    meta = _meta()
    t = np.arange(n) / 100.0
    ir = (90000 * (1 - 0.01 * np.sin(2 * np.pi * 1.2 * t))).round().astype(int)
    red = (60000 * (1 - 0.005 * np.sin(2 * np.pi * 1.2 * t))).round().astype(int)
    lines = ["# " + "; ".join(f"{k}={v}" for k, v in {**meta, "scenario": "normal", "seed": "42"}.items()), _header()]
    lines += [f"P001,P001_S01,{x:.3f},{r},{i},,," for x, r, i in zip(t, red, ir)]
    return "\n".join(lines) + "\n"


def test_marker_values_match_the_frontend_and_the_backend_guard():
    m = _meta()
    assert m == {"dataset_type": "virtual_hardware_simulation", "research_validity": "not_for_research_validation",
                 "generated_for": "hardware_pipeline_integration_testing"}
    assert _header() == "participant_id,session_id,timestamp,red,ir,accelerometer_x,accelerometer_y,accelerometer_z"


@pytest.mark.parametrize("kind", ["ppg", "combined", "reference", "pigmentation"])
def test_recorded_virtual_csv_is_refused_by_data_collection(tmp_path, kind):
    paths = Paths(processed=tmp_path / "p", raw=tmp_path / "r", models=tmp_path / "m", results=tmp_path / "res")
    with pytest.raises(CollectionError) as e:
        ingest.add_upload(kind, _virtual_csv().encode(), {"attested_real": True, "filename": "P001_P001_S01_VIRTUAL_SIMULATION.csv"}, paths)
    assert e.value.code == "virtual_simulation"
    assert store.manifest(paths) == []


def test_the_csv_validator_accepts_the_recorded_virtual_csv(tmp_path):
    f = tmp_path / "P001_P001_S01_VIRTUAL_SIMULATION.csv"
    f.write_text(_virtual_csv(), encoding="utf-8")
    spec = importlib.util.spec_from_file_location("check_session_csv", ROOT / "hardware/check_session_csv.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main([str(f), "--fs", "100"]) == 0


def test_weakest_point_documented_a_renamed_marker_free_copy_is_accepted_but_never_verified(tmp_path):
    """CURRENT PROTECTION: the marker line (refused outright), the file/device/ID name markers (gate -> SOFTWARE_TEST_DATA), and, last, the provenance
    requirement (research status needs a registered human-participant declaration bound to the dataset hash).
    WEAKNESS: a person who strips the marker line AND renames the file gets a recording that Data Collection accepts: nothing inside the data proves it is
    simulated. The remaining barrier is that the research gate cannot reach VERIFIED / RESULTS without a deliberate (self-declared) provenance record."""
    from app.collection import merge
    from app.governance import research_gate as gate
    from tests.test_collection import add, csv, make_paths
    import pandas as pd
    paths = make_paths(tmp_path)
    df = pd.DataFrame({"participant_id": ["P1"] * 2, "session_id": ["S1"] * 2, "timestamp": [1.0, 2.0], "spo2": [95, 94], "sao2": [96, 95],
                       "pi": [2.0, 2.1], "ita": [30, 30], "sqi": [90, 90], "motion": [5, 5], "device_id": ["ESP32 + MAX30102"] * 2})
    add(paths, "combined", csv(df), filename="session_001.csv")                       # no marker line, neutral name, real-looking device
    merge.build_research_dataset(paths)
    g = gate.evaluate(paths)
    assert g["state"] == "UNVERIFIED_DATA" and g["verified_data"] is False and g["results_allowed"] is False
    assert any(c["id"] == "verified_flag" and not c["passed"] for c in g["checks"])    # no provenance record -> never verified
