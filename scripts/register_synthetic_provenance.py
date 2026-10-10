"""Register a hash-bound provenance record for the SYNTHETIC pipeline-test dataset that was built in Data Collection.

Without this record the gate calls the data UNVERIFIED (file names never count as provenance); with it, the dataset is classified SOFTWARE TEST DATA
and bound to its SHA-256: change one value and the record stops applying. It never verifies anything as research data.

Usage (backend running):  python scripts/register_synthetic_provenance.py [http://127.0.0.1:8000]
"""
import json
import sys
import urllib.request
from pathlib import Path

base = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
meta = json.loads((Path(__file__).resolve().parents[1] / "data" / "synthetic" / "synthetic_pipeline_test_dataset.meta.json").read_text(encoding="utf-8"))
payload = {
    "data_origin": "synthetic",
    "dataset_name": "synthetic pipeline test dataset",
    "source_description": f"{meta['generator']} seed {meta['seed']}; source CSV sha256 {meta['csv_sha256']}; {meta['label']}",
    "registered_by": "software test",
    "generator_version": f"{meta['generator']}@seed={meta['seed']}@numpy={meta['versions']['numpy']}@pandas={meta['versions']['pandas']}",
    "declaration": True,
}
req = urllib.request.Request(f"{base}/api/research/provenance", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
with urllib.request.urlopen(req) as r:
    out = json.load(r)
print("state:", out["status"]["state"], "| bound to dataset hash:", out["status"]["provenance_bound"], "| results_allowed:", out["status"]["results_allowed"])
