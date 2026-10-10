# PigmentCal-UQ: Can you trust this number?

*An independent project, designed and built by Pragatheesvar.*

An uncertainty-aware **reliability layer for pulse oximetry**. It does not replace the oximeter reading; it reports how much that reading can be trusted, given signal quality, motion, perfusion and *objective* skin pigmentation (ITA from colorimetry, never race). When the evidence is not sufficient it **abstains**.

> **Not a diagnostic device. Not clinically validated.** The app never presents generated data as measurements: simulated or synthetic data (the Virtual MAX30102, `data/synthetic/`) is always labelled, is never counted as real data, and simulation files are refused by Data Collection. Real values come from a connected sensor, a camera, a file you load, or your own entries. Where there is no real data (no dataset, no calibration) the app shows an empty state, never placeholder numbers.

## Features
| Area | What it does |
|---|---|
| **Live Monitor** | Live PPG (analysis about once per second) from an ESP32 + MAX30102 (USB, Web Serial), a phone/webcam camera, or a recording replayed in real time; signal quality, perfusion index, motion, pulse rate; session recording with CSV export |
| **Reliability Check** | GREEN / AMBER / RED / **ABSTAIN** with reasons; recorded-PPG analysis, objective ITA and perfusion inputs live in its "Measurement inputs" section |
| **Measurement inputs** | ITA = arctan((L* − 50) / b*) × 180/π (standard form, range −90° to 90°; b* = 0 → ±90°; L* = 50 with b* = 0 is undefined and rejected) from L*a*b*; PI classification; analysis of recorded PPG files (inside Reliability Check) |
| **Data Collection / Dataset** | Upload PPG, reference SaO₂ and colour data, match by participant and session, validate every record, build the research dataset, split by participant |
| **Models** | Ridge baseline and LightGBM comparator, trained only on a verified, ready dataset; subgroup error with INSUFFICIENT DATA where groups are small |
| **Conformal reliability** | CQR with ITA × PI Mondrian calibration, calibrated interval, lower bound and abstention (needs trained models) |
| **Results / Explainability** | Test metrics with participant-level bootstrap CIs, subgroup performance, conformal coverage; Ridge coefficients and TreeSHAP (model behaviour, not causality) |

The header badge always shows the backend gate's state: **NO RESEARCH DATA**, **SOFTWARE TEST DATA** (synthetic / test-fixture data, e.g. `data/synthetic/`; labelled *not a research result*), **SIMULATED HARDWARE DATA**, **UNVERIFIED EXTERNAL DATA**, **UNVERIFIED DATA** (data that fails at least one gate check), **VERIFIED RESEARCH DATA** or **REAL RESEARCH RESULTS** (verified data that has been trained *and* calibrated). Models fitted on anything but verified data are labelled *trained / calibrated on … — not research validated*.

**Virtual hardware simulation (no hardware needed).** Live Monitor → *Virtual MAX30102* runs a software ESP32 + MAX30102 (I²C 0x57, PART ID 0x15, FIFO, 100 Hz; `frontend/src/lib/virtualSensor.ts`) that emits only raw RED/IR JSON lines through the same serial parser, buffer, analysis and recorder as a real board. Scenarios: Normal, Low perfusion, High motion, High noise, Fast/Slow pulse, Combined; seeded and reproducible. It is a software integration test only: not real measurements, not hardware validation, not research data. Saved files carry a `dataset_type=virtual_hardware_simulation` marker line and `_VIRTUAL_SIMULATION` in the name, and Data Collection refuses them.

**Not tested / not evaluated (current status, see `hardware/STATUS.md`):** physical ESP32 and MAX30102 (not tested) · Wokwi runtime (not executed; the files in `hardware/wokwi/` are statically prepared) · browser Web Serial (not tested) · phone/webcam camera PPG (not tested) · virtual→real transfer (not evaluated) · cross-device generalization (not evaluated; the app only accepts a device identifier). `data/synthetic/` holds a deterministic synthetic dataset for software testing only (not human data).

**Two reliability paths (intentional, two different layers).** *Live Monitor* runs the **rule engine** on the live signal: signal quality, motion and perfusion add up points (RED from 3 points; poor signal or high motion → ABSTAIN) and no calibrated interval is shown. *Reliability Check* runs the **calibrated CQR + ITA × PI Mondrian** layer on typed or measured values: it adds a prediction interval, subgroup-calibration sufficiency and an abstention when the inputs lie outside the fitted range. Details, RED triggers and the motion = 0 case: `docs/RELIABILITY_PATHS.md`. On the live *virtual* path all four states can be demonstrated: GREEN and AMBER and ABSTAIN with the standard scenarios, and **RED is reproducible with the "Low perfusion + intermediate noise" scenario** (or Low perfusion with Noise = Intermediate): very-low PI (2 points) + moderate signal quality (1 point) reach the unchanged RED threshold of 3 points, decided by the real rule engine from the computed SQI and PI (the result varies with the analysis window: RED, AMBER or ABSTAIN). It shows that the implemented rules can produce RED under a valid simulated condition; it says nothing about real devices, safety or accuracy. VIRTUAL HARDWARE SIMULATION — NOT REAL MEASUREMENTS. On the calibrated path RED is reproduced with manually entered values.

**Simulation assumption.** The Virtual MAX30102 uses a simple reflectance model (blood-volume pulse → intensity falls as volume rises, plus drift, noise and motion artefacts; the RED/IR pulse-amplitude ratio is an internal constant). It is not a full Beer-Lambert / tissue model. SIMULATION ASSUMPTION: it supports software-integration and sanity tests only; it makes no clinical, calibration or accuracy claim.

**ITA bands.** ITA = arctan((L\* − 50) / b\*) × 180/π is computed in exactly one place (`backend/app/services/pigmentation.py`); the frontend only displays it. The project's *Light / Medium / Dark* labels are configured bands of that angle (`config.py`: Light = ITA > 41°, Dark = ITA ≤ 10°, Medium in between). They are **not** the standard Chardon skin-tone categories (very light > 55°, light 41–55°, intermediate 28–41°, tan 10–28°, brown −30–10°, dark < −30°); "Dark" here means ITA ≤ 10° (which spans standard tan, brown and dark) and does not mean the darkest skin. Never read the bands as race or ethnicity.

**SaO₂ pairing.** A reference SaO₂ is paired one-to-one with the nearest PPG window ending within ±30 s (`CollectionConfig.match_tolerance_s`, configurable). 30 s is a deliberately generous default that keeps few readings unmatched; it is a **limitation** (the true SaO₂ can change within that time). Ambiguous or duplicate references stay unmatched and are listed, never guessed.

**Provenance.** The research gate trusts only a *hash-bound provenance record* (`/api/research/provenance`): it stores the dataset's SHA-256, origin, dataset type, research validity, creation time, software version and (for synthetic data) the generator version. If the dataset changes by one value the record no longer applies. File names, comment lines, device labels and participant IDs are never provenance: they can only *block* (name markers), never classify. Synthetic test data is registered with `python scripts/register_synthetic_provenance.py`; without it the same data is reported as UNVERIFIED DATA.

**Model files.** `.joblib` files are pickles (loading an untrusted one can run code). They are written only to the app's own `models/` folder together with a SHA-256 sidecar, loaded only if that hash matches, and no API accepts a model upload. Anyone who can write to the models folder can still replace both files: protect that folder.

**Environment.** Python 3.13 (pinned versions in `backend/requirements.lock`), Node ≥ 22.12 (`frontend/.nvmrc`). One-command reproduction: `scripts/reproduce.ps1` or `scripts/reproduce.sh` (writes `docs/repro_log.txt`). Claims and their evidence: `docs/CLAIMS.md`.

## Run locally (two terminals)
```powershell
# Backend (http://127.0.0.1:8000, API docs at /docs)
cd backend
.\.venv\Scripts\python -m uvicorn app.main:app --reload
# (run it from the backend folder; `uvicorn main:app --reload` is accepted too)

# Frontend (http://localhost:5173)
cd frontend
npm run dev
```
First-time setup: `cd backend; python -m venv .venv; .\.venv\Scripts\pip install -r requirements.txt -r requirements-dev.txt`, then `cd frontend; npm install`.
If every page says "API offline", the backend is not running: open http://127.0.0.1:8000/api/health, which must answer with `"app": "PigmentCal-UQ"`. If another program already uses port 8000, start this backend on a free port and point the frontend at it (below).
Another backend port: `API_PORT=8001 npm run dev`. Keep data, models and results outside the project with `PIGMENTCAL_HOME=<folder>`. Production build: `cd frontend; npm run build` (served by any static host with `/api` proxied to the backend).

## Using it
1. **Live Monitor**: choose *ESP32 + MAX30102*, *Phone camera* or *Replay recording*. Sensor wiring and firmware: `hardware/README.md` (Chrome or Edge needed for Web Serial).
2. **Pigmentation**: enter colorimeter L\*, a\*, b\* to get ITA.
3. **Data Collection**: tick the real-data confirmation, then upload the session CSV, reference SaO₂ (`participant_id, session_id, timestamp, sao2`), and pigmentation (`participant_id, [session_id], ITA` or `L, a, b`), or one combined CSV. Use anonymous IDs only (P001, P001_S01): IDs that look like e-mail addresses or phone numbers, or contain spaces, are rejected, but the app cannot recognise every real name, so never type one. Real human data needs consent and ethics approval.
4. **Dataset**: validate and split by participant.
5. **Models**: shows the readiness status; training is allowed only for a ready, verified dataset and is never started automatically.

## Research data files
`backend/data/processed/research_dataset.csv` (participant_id, session_id, timestamp, spo2, sao2, pi, ita, L, a, b, sqi, motion, device_id), `research_dataset_invalid.csv` (flagged records with reasons), `research_data_quality.json`, `merge_report.json`. A reference SaO₂ is paired one-to-one with the nearest PPG window (end within ±30 s, configurable); ambiguous references stay unmatched. Name, phone, e-mail and address columns are ignored and never stored. These folders are created on first use and are git-ignored.

## Data policy
Only your project's own verified data is used for results. An external dataset (OpenOximetry v1.1.1) was audited under `external/openoximetry/` and is **not used**: key definitions were unresolved (see `external/openoximetry/STATUS.md`). Test signals with a known ground truth live in `backend/tests/` only.

## Tests
```powershell
cd backend;  .\.venv\Scripts\python -m pytest -q      # API, signal, pipeline, models, conformal (temp folders only)
cd frontend; npm test; npx tsc --noEmit; npm run build
```

## Scientific rules enforced in code
Race is never an input · ITA must be an objective measurement · splits are by participant (leakage is an error) · SaO₂ is never a predictor · invalid or missing values are reported, never imputed or silently dropped · poor signal or high motion → ABSTAIN · no uncertainty range without a real calibration dataset · coverage describes the procedure under its assumptions, not a probability for an individual · thresholds are configurable (`backend/app/config.py`) and not clinically validated.
