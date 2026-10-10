# Audit fix report

Baseline before any change: `docs/AUDIT_BASELINE.md` (backend 457 passed · frontend 106 passed · tsc clean · build OK).
No commits: the project folder is not a git repository (nothing was committed or initialised).

## Final verification (real output, `scripts/reproduce.ps1 -SkipInstall`, log in `docs/repro_log.txt`)
```
regenerated sha256 dfe784d85bbdb4609e2d6c717e11f78568cb8ce7e91f36e8773997ca4448eb52
recorded    sha256 dfe784d85bbdb4609e2d6c717e11f78568cb8ce7e91f36e8773997ca4448eb52   -> IDENTICAL
backend tests            496 passed in 37.71s            exit 0
frontend tests           Test Files 6 passed · Tests 106 passed      exit 0
frontend typecheck       (no output)                     exit 0
frontend production build  built in 654ms                exit 0
```
The install steps (venv creation, `pip install -r requirements.lock`, `npm ci`) were **NOT RUN** (the script was run with `-SkipInstall`, so the pinned lock file has not been installed from scratch).

## Issue table
| # | Confirmed? | Changed (file / function) | Test added | Result | Remaining risk |
|---|---|---|---|---|---|
| 1 ITA definition | YES: atan2 differs from the standard form when b*<0 (e.g. L*−50=10, b*=−5 gave 116° instead of −63.4°) | `services/pigmentation.compute_ita` is the single definition (arctan((L*−50)/b*), b*=0 → ±90°, L*=50&b*=0 and non-finite → error); `_lab` rejects L*=50&b*=0; research gate tolerates the undefined case; README, API docstring, Pigmentation page text | `test_pigmentation.py` (b>0, b=0, b<0, L=50, NaN/inf, range, API 422) | PASS | This supersedes the earlier standing instruction "do not change the ITA formula"; for b*>0 (all realistic skin values) results are identical. Group cut-points (41° / 10°) are configured constants, not tuned on the old formula: unaffected. The frontend has no ITA computation (it only displays the backend's); the OpenOximetry evidence report still quotes the old atan2 formula (historical, left unedited). |
| 2 ITA group naming | YES | documented in `config.py`, README, Pigmentation page, synthetic meta; labels NOT renamed (would touch the whole app and tests) | synthetic meta test | PASS (documentation) | "Light/Medium/Dark" remain in the UI; they are explained as configured bands, not standard categories |
| 3 PI definition | CONFIRMED correct (`100·AC_IR/DC_IR`, DC≤0, negative, NaN/inf rejected: existing tests) | none | `test_live.py::test_pi_is_computed_from_the_infrared_channel_only` | PASS | PI is a rough PPG-derived estimate |
| 4 SaO₂ pairing window | YES (±30 s, configurable) | default kept; documented as a LIMITATION in `config.py` and README | `test_collection.py::test_pairing_is_one_to_one_and_never_guesses…` | PASS | A tighter default needs a protocol-specific justification that I cannot make from the repo |
| 5 conformal/Mondrian audit by test | all five properties already had tests; no failures | none | existing: `test_pipeline.py::test_split_is_participant_disjoint…`, `test_models.py::test_participant_overlap_between_splits_is_blocked`, `test_conformal.py::test_a_cell_with_no_data_is_insufficient…`, `…::test_conformal_quantile_uses_the_finite_sample_rank`, `…::test_cqr_score_is_the_larger_signed_distance…`, `test_models.py::test_features_exclude_target_and_participant` / `test_leakage_guard_rejects` | PASS | |
| 6 reliability truth table | rule engine matches the design on every row | none | `test_truth_table.py` (normal, low PI, very low PI, high motion, poor SQI, high noise, combined, unsupported ITA, missing inputs, insufficient calibration, no model) | PASS | My first draft expected the conformal state to equal the rule-engine state; that was a wrong expectation (the conformal state also uses the interval width/gap), not a code defect. Rule: conformal is equal or more cautious, never less. |
| 7 synthetic data honesty | YES | generator writes `csv_sha256`, numpy/pandas/python versions, circularity + SpO₂-range + device_id limitations, LF line endings; `write()` function | `test_synthetic_data.py` (hash, regenerate, labels, device has no effect) | PASS | Optional low-SpO₂ variant NOT built. Line endings changed CRLF→LF: values are identical to the earlier file (checked), only the file hash changed. |
| 8 metric labels | GAPS: `/api/model/metrics`, `/predictions`, `/api/conformal/metrics`, `/coverage` had no origin label | those four now include `research_status` (new `research_gate.brief()`) | `test_api_resilience.py::test_every_metric_bearing_endpoint_carries…` | PASS | The label wording is the existing "SOFTWARE TEST DATA — NOT A RESEARCH RESULT", not the longer text suggested |
| 9–10 README contradictions / not-tested list | YES | README | – | PASS | |
| 11 Beer–Lambert simulator | DOES NOT EXIST (only a simple reflectance model) | README states exactly that, as a SIMULATION ASSUMPTION; no doc claims Beer–Lambert | – | PASS | |
| 12–13 claims sweep / device-agnostic | YES | see `docs/CLAIMS.md` (list of changes) | – | PASS | |
| 14 .gitignore `external/` | YES | ignores raw, processed, `official_docs/`, `reports/*.csv`, `import_audit.json`; STATUS.md, `*.md` reports, `metadata/raw_sha256.txt`, `audit_import.py` become trackable | – | PASS (not run through git: no repo) | **Review `external/openoximetry/reports/*.md` before publishing:** they derive from a credentialed PhysioNet dataset and may quote record-level examples |
| 15 pins / engines | YES | `backend/requirements.lock`, `frontend/package.json` engines, `.nvmrc`, README | upload test (below) | PASS | `python-multipart` NOT added: no route uses UploadFile/Form (uploads read the raw body) |
| 16 machine paths | YES | `audit_import.py` (CLI arg / own folder, exploratory header); bogus `.vscode/settings.json` deleted | – | PASS | |
| 17 Google Fonts | YES | `index.html` no third-party requests; system font stack (Inter only if installed locally) | – | PASS (build) | slightly different look on machines without Inter |
| 18 repro script | YES | `scripts/reproduce.ps1`, `reproduce.sh` | – | `.ps1` run with `-SkipInstall` PASS; `.sh` NOT RUN; install steps NOT RUN | |
| 19 joblib | YES | `ml/data.save_artifact/load_artifact` (SHA-256 sidecar verified before unpickling) used by train, conformal fit/predict, service, validation report | tampered/unhashed file refused; every artifact has its sidecar; no model-upload route | PASS | Anyone with write access to `models/` can replace file and hash. Existing artifacts without sidecars are refused ("train again"): the main-home models were retrained; `data/synthetic/sandbox/` models were NOT (they are now refused until retrained) |
| 20 uploads | PARTLY existed (size cap, 4xx) | extension check, safe file name, row cap, CSV-injection guard on the rejected-records file | extension / traversal / formula name / row cap / size / injection / malformed → 4xx | PASS | Staged tables still carry `source_file` (sanitised) |
| 21 input validation | existed | – | NaN / Infinity / −Infinity / negative PI / out-of-range → 422 | PASS | |
| 22 CORS / secrets | CORS already restricted to localhost, no credentials; pattern search found no secrets | – | – | PASS | pattern search is not a full secret scan |
| 23 participant IDs | existed (e-mail, phone, spaces, charset) | README clarifies that names cannot be detected reliably | existing tests | PASS | |
| 24 header / footer | badge + footer exist | none | – | PARTLY | "Research prototype" was NOT added: the project owner earlier banned that phrase everywhere. The footer says "Not a diagnostic device. Not clinically validated." |
| 25 interval wording | existing backend wording shown in the UI | none | `test_prediction_wording_never_claims_individual_probability…` | PASS | |
| 26 empty/error/loading states | not re-verified in a browser in this pass | – | – | NOT RE-RUN | verified in earlier passes |
| 27 explainability wording | existing "model behavior, not causality" | none | – | PASS | |
| 28 hardware status | YES | `hardware/STATUS.md` (everything NOT TESTED) + bring-up checklist | – | PASS | |
| 29 virtual → … → refusal chain | existed only in halves | – | `test_virtual_integration.py` (marker/header read from the TS sources, refusal for all four upload kinds, validator accepts); frontend `virtualSensor.test.ts` covers parser → buffer → recorder → CSV | PASS | labelled software integration only |

## Truth table
| Component | Status | Evidence | Can I claim it? |
|---|---|---|---|
| Software pipeline | runs end to end | 496 backend + 106 frontend tests, reproduce log | YES (software) |
| Models / CQR / Mondrian | trained / calibrated on synthetic test data | synthetic run | ONLY as "pipeline test" |
| Real research data | 0 records | `/api/collection/status`: "REAL DATA: 0 records" | NO data |
| Research validation | not available | gate = SOFTWARE_TEST_DATA | NO |
| Fairness / bias / clinical validity | not evaluated | – | NO |
| Physical ESP32 / MAX30102 | not tested | `hardware/STATUS.md` | NO |
| Wokwi runtime | not executed | – | NO |
| Web Serial with a board | not tested | – | NO |
| Phone camera PPG | not tested | – | NO |
| Virtual MAX30102 | tested as software integration | virtual tests | YES, as simulation only |
| OpenOximetry | blocked, not imported; `processed/` empty | `external/openoximetry/STATUS.md` | NO |

## Found that was NOT in the prompt
1. `external/openoximetry/reports/patient_conflicts.csv` and `import_audit.json` (examples) derive from credentialed data: they are now ignored rather than tracked.
2. With integrity hashes, previously saved model files are refused until retrained (sandbox models under `data/synthetic/sandbox/`).
3. The earlier synthetic CSV had CRLF line endings; it is now LF (hash changed, values identical).
4. The Live Monitor reliability card says calibrated uncertainty "requires a real dataset … which has not been loaded" even while synthetic calibration exists (accurate about real data, but easy to misread).
5. The conformal layer abstains on the virtual sensor's motion score 0 because the synthetic training data never contained 0 (existing behaviour).

## Re-run everything
```powershell
powershell -ExecutionPolicy Bypass -File scripts/reproduce.ps1            # full, with installs
powershell -ExecutionPolicy Bypass -File scripts/reproduce.ps1 -SkipInstall
bash scripts/reproduce.sh --skip-install                                   # Git Bash / Linux / macOS
cd backend  ; .\.venv\Scripts\python -m pytest -q
cd frontend ; npm test ; npx tsc --noEmit ; npm run build
```
