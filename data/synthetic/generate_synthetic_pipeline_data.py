"""Deterministic SYNTHETIC dataset for software / pipeline integration testing ONLY.

NOT real participants, NOT measured data, NOT clinical data, NOT research validation. The SpO2 -> SaO2 relationship below is an
invented rule used to exercise the training, CQR and Mondrian code paths; it says nothing about real pulse-oximeter bias.

Usage:  python generate_synthetic_pipeline_data.py     (writes next to this file; same seed -> byte-identical output)
Schema = the project's combined-record schema: participant_id, session_id, timestamp, spo2, sao2, pi, ita, sqi, motion, device_id.
SaO2 is the TARGET; no SaO2-derived value (e.g. SaO2 - SpO2) is written as a column.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 20260101
HERE = Path(__file__).resolve().parent
FILENAME = "synthetic_pipeline_test_dataset.csv"
# Light 70 / Medium 70 / Dark 40 participants: the Dark group is deliberately small so that its calibration cells fall below the
# project's minimum-data rule and the existing "insufficient data" behaviour is exercised (not inflated).
GROUPS = {"Light": (70, (45.0, 70.0)), "Medium": (70, (12.0, 38.0)), "Dark": (40, (-25.0, 8.0))}
READINGS = 8                                    # per participant: 2 sessions x 4 readings
DEVICES = ("SYNTHETIC_DEVICE_A", "SYNTHETIC_DEVICE_B")


def build() -> pd.DataFrame:
    rng = np.random.default_rng(SEED)
    rows, k = [], 0
    for name, (n, (lo, hi)) in GROUPS.items():
        for _ in range(n):
            k += 1
            pid = f"SYN{k:04d}"
            ita = float(rng.uniform(lo, hi))
            pi_base = float(np.exp(rng.normal(np.log(1.3), 0.7)))      # participant-level perfusion tendency
            dev = DEVICES[k % 2]
            for r in range(READINGS):
                sess = f"{pid}_S{r // 4 + 1:02d}"
                spo2 = float(np.clip(rng.normal(94.0, 3.2), 82.0, 100.0))
                pi = float(np.clip(pi_base * np.exp(rng.normal(0, 0.45)), 0.1, 12.0))
                sqi = float(np.clip(rng.normal(80, 14), 20, 100))
                motion = float(np.clip(rng.gamma(2.0, 6.0), 0, 60))
                low = pi < 1.0
                # invented rule: reference sits below the displayed value by an amount that grows with darker ITA and low PI
                bias = 0.5 + 1.6 * np.clip((30.0 - ita) / 60.0, -0.5, 1.0) + 0.9 * low
                sd = 0.6 + 0.8 * low + 0.4 * (sqi < 50) + 0.01 * motion
                sao2 = float(np.clip(spo2 - bias + rng.normal(0, sd), 50.0, 100.0))
                rows.append({"participant_id": pid, "session_id": sess, "timestamp": float(15 * (r % 4 + 1)), "spo2": round(spo2, 1),
                             "sao2": round(sao2, 1), "pi": round(pi, 3), "ita": round(ita, 1), "sqi": round(sqi, 1),
                             "motion": round(motion, 1), "device_id": dev})
    return pd.DataFrame(rows)


def write(out_dir: Path = HERE) -> dict:
    """Write the CSV and its metadata next to `out_dir`. Same seed + same numpy/pandas versions -> byte-identical CSV."""
    import hashlib, platform
    df = build()
    csv_path = Path(out_dir) / FILENAME
    df.to_csv(csv_path, index=False, lineterminator=chr(10))
    meta = {"dataset_type": "synthetic", "research_validity": "not_for_research_validation", "generated_for": "pipeline_integration_testing",
            "label": "SOFTWARE / PIPELINE TEST DATA — NOT RESEARCH RESULTS",
            "seed": SEED, "generator": Path(__file__).name, "file": FILENAME, "participants": int(df.participant_id.nunique()), "rows": int(len(df)),
            "csv_sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
            "versions": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__},
            "itagroups_participants": {k: v[0] for k, v in GROUPS.items()},
            "ita_group_note": "Group names are only labels for the project's configured ITA bands (Light: ITA > 41, Dark: ITA <= 10, Medium otherwise). They are NOT the standard ITA skin-tone categories and 'Dark' does not mean the darkest skin.",
            "limitations": [
                "CIRCULAR: the SaO2 bias is invented to grow with lower ITA and lower PI, so any model that 'finds' it only recovers the rule written in this file.",
                "SpO2 is drawn from about 82-100 %: the hypoxemic range (below ~80 %) is not represented.",
                "device_id (SYNTHETIC_DEVICE_A/B) has NO effect on the generative rule: device generalisation cannot be tested with this data.",
                "Not human data. Does not demonstrate real pulse-oximeter bias. Never use as research evidence."],
            }
    (Path(out_dir) / "synthetic_pipeline_test_dataset.meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return meta


if __name__ == "__main__":
    m = write()
    print(m["participants"], "participants,", m["rows"], "rows, sha256", m["csv_sha256"])
