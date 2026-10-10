# Submission pack: presentation, demo script, judge Q&A, release checklist

Everything here describes the frozen software as it is. Data = synthetic software-test data; sensor = virtual hardware simulation; typed values = manual input. Nothing is real participant data, a physical measurement, or clinical evidence.

Recorded baseline re-run for this pack: backend 520 passed · frontend 108 passed (6 files) · `tsc --noEmit` clean · production build OK.

---
## A. Seven-slide plan (target 6 min 30 s)

### Slide 1: "CAN YOU TRUST THIS NUMBER?" (30 s)
* **Slide:** project name, one line: "A reliability layer for pulse-oximeter readings", your name, "Independent project".
* **Visual:** the Overview page (header badge visible).
* **Notes:** "A pulse oximeter gives one number. It never tells you when that number should not be trusted. My project adds that missing warning."
* **Transition:** "Let me show why that matters."

### Slide 2: Problem Statement (50 s)
* **Slide:** 3 bullets: one number, no warning · signal quality, motion and perfusion change reliability · studies report pulse oximeters can overestimate oxygen in people with darker skin (reliability is not equal for everyone).
* **Visual:** simple diagram: finger → red/infrared light → "98 %".
* **Notes:** "The reading depends on light passing through tissue. Weak blood flow, movement, noise and skin pigmentation can change how reliable it is. A single number hides that. I am not claiming to fix the number; I want to measure how far it can be trusted." (Do not quote figures or citations you have not checked.)
* **Transition:** "So what does my system do about it?"

### Slide 3: Proposed Solution and Innovation (60 s)
* **Slide:** pipeline in one line: PPG → signal quality, perfusion → objective pigmentation (ITA) → conformal interval → GREEN / AMBER / RED / ABSTAIN. Innovation: reliability bounds calibrated per pigmentation × perfusion group, and the system abstains when evidence is too thin.
* **Visual:** the Models/conformal cell table (six cells, two marked INSUFFICIENT).
* **Notes:** "ITA is a colour angle calculated from lab-style colour values (L*, a*, b*). It is an objective measurement, not race. I split data into groups by ITA and by perfusion index, and calibrate an uncertainty interval for each group (conformal prediction, Mondrian style). If a group has too little calibration data the system says 'I don't know'."
* **Transition:** "Here is how it is built."

### Slide 4: System Architecture and Technology (60 s)
* **Slide:** boxes: ESP32 + MAX30102 (or virtual simulation) → Web Serial → React/Vite app → FastAPI backend → rule engine / Ridge + LightGBM + CQR → research gate. Tech: Python, FastAPI, scikit-learn, LightGBM, React, TypeScript.
* **Visual:** architecture diagram; mark "Live path = rule engine" and "Reliability Check = calibrated CQR/Mondrian".
* **Notes:** "There are two layers. The Live Monitor uses a transparent rule engine. The Reliability Check adds the calibrated interval. A research gate keeps synthetic or simulated data from ever being shown as research results."
* **Transition:** "Now the prototype."

### Slide 5: Prototype Demonstration (150 s, live; see section B)
* **Slide:** title "Live demo" + banner text "VIRTUAL HARDWARE SIMULATION — NOT REAL MEASUREMENTS".
* **Visual:** switch to the app. Backup: 3 screenshots (GREEN, RED, ABSTAIN).
* **Transition:** "That was a simulation. Here is what is and is not validated."

### Slide 6: Results, Validation Status and Limitations (60 s)
* **Slide (table, short):** Real data: 0 · Real validation: not available · Physical hardware: not tested · CQR/Mondrian: implemented, validation pending · Software: 520 backend + 108 frontend tests pass · Synthetic pipeline: tested.
* **Visual:** Research Summary status block.
* **Notes:** "I want to be clear about what this is. The models are trained on a synthetic dataset I generated with an invented rule, so its metrics only show that the pipeline works. I have not tested the physical sensor, and I have no real participant data yet."
* **Transition:** "So the next steps are clear."

### Slide 7: Conclusion and Future Scope (40 s)
* **Slide:** done: complete tested pipeline with honest abstention · next: ethics approval and permissions, paired reference SaO₂ + colorimeter data, participant-level validation, physical hardware test.
* **Notes:** "The contribution is a framework that says when not to trust a reading, built and tested end to end. The real validation is the next phase."
* **Closing line:** "Can you trust this number? Now the system can tell you when you should not."

**Timing:** 30 + 50 + 60 + 60 + 150 + 60 + 40 = 450 s (7 min 30 s with the full demo). To land on about 6 min 30 s, run the demo at 90 s (scenarios A, D, E only) or trim slides 2 and 4 by 15 s each.

---
## B. Demo script (banner "VIRTUAL HARDWARE SIMULATION — NOT REAL MEASUREMENTS" stays visible)

Setup: backend and frontend running, header says "API v1.0.0" and "SOFTWARE TEST DATA", Live Monitor → **Virtual MAX30102**. Start the simulation 15 s before speaking about it (the analysis needs about 10 s of signal).

| Scenario | Page / control | Expected | Say | Evidence | Disclose |
|---|---|---|---|---|---|
| A. Normal → GREEN | Live Monitor · Scenario "Normal" · type ITA 55 | SQI ≈ 90+, PI ≈ 1.9 %, GREEN, "no reliability flags" | "Good signal, normal perfusion: no flags." | `test_truth_table.py`, browser run | Simulation; SpO₂ shown is an uncalibrated estimate. |
| B. Low perfusion → AMBER | Scenario "Low perfusion" | PI ≈ 0.28 % (very low), AMBER, 2 points | "Weak blood flow: the app asks for caution, it does not guess." | `test_reliability.py` | PI is a signal-derived estimate. |
| C. Poor signal → ABSTAIN | Scenario "High motion" or "Combined challenge" | SQI very low, PI/SpO₂ withheld, ABSTAIN "reacquire signal" | "When the signal is bad it refuses to give a verdict." | `test_truth_table.py` | Motion is estimated from the signal (no accelerometer). |
| D. RED | Scenario "Low perfusion + intermediate noise" (or Low perfusion with Noise = Intermediate); wait a few seconds | RED (3 points: very low PI + moderate quality). It may flip to AMBER/ABSTAIN between windows | "Two weaknesses at once reach the RED threshold. The simulator never sets a state; the rule engine decides." | `test_live_red_integration.py` (browser: RED 6 of 9 readings) | RED shows the rules working in a simulated condition. It does not show a real oximeter is inaccurate or unsafe. The variation is real. |
| E. Insufficient calibration → ABSTAIN | Reliability Check · SpO₂ 94, PI 2, ITA −10, SQI 85, motion 3, device Other | "INSUFFICIENT CALIBRATION DATA. Dark × Normal PI has 8 participants and 44 rows; needs ≥10 and ≥30. No data were invented." | "It would rather say 'I don't know' than invent confidence." | calibrated case D in `RELIABILITY_PATHS.md` | MANUAL INPUT on a synthetic-trained layer; the Dark group is deliberately small in the synthetic set. |

Optional: Reliability Check with 94 / 2 / ITA 55 / SQI 85 / motion 3 → GREEN with an interval (92.74–94.99) to show the calibrated path.
Say once: "The live rule engine and the calibrated CQR/Mondrian layer are two separate implementations."
Do not demo: phone camera, Web Serial with a board (both NOT TESTED).

---
## C. Judge Q&A (short answers)
* **What problem?** A pulse-oximeter number carries no warning about its own reliability; signal quality, motion, perfusion and pigmentation affect it.
* **Innovation?** Reliability bounds calibrated per pigmentation × perfusion group, plus abstention when a group has too little calibration data, and a gate that keeps synthetic or simulated data out of "research results".
* **What is ITA?** Individual Typology Angle, arctan((L*−50)/b*) × 180/π from colour values. An objective colour descriptor, not race, and not a melanin measurement.
* **Why perfusion?** Weak blood flow weakens the pulse signal, so readings are less reliable; PI = AC/DC of the infrared signal × 100 (a signal-derived estimate here).
* **What is CQR?** Conformalized quantile regression: predict a lower and upper quantile, then widen by a margin computed on held-out calibration data so the interval has the intended empirical coverage under exchangeability.
* **What is Mondrian calibration?** The margin is computed separately inside each group (here ITA group × PI group), so coverage is checked per group, not only on average.
* **What do the states mean?** GREEN: no flags. AMBER: caution (some weaknesses). RED: several weaknesses at once or a wide/low interval. ABSTAIN: not enough evidence. They describe the reliability of the reading, not a medical condition.
* **Why abstain?** Poor signal, high motion, input outside the fitted range, or too few calibration participants/rows.
* **Novelty gap?** The method is implemented and tested, but its coverage has not been checked on real paired data, which is the missing evidence for the novelty claim.
* **Dataset?** A synthetic pipeline-test dataset (180 virtual participants, 1,440 rows, invented rule, fixed seed). It tests the software only. An external dataset was audited and blocked pending author clarification.
* **Why is real validation unavailable?** It needs consented participants, a colorimeter and reference SaO₂ (blood gas); I have none yet.
* **Hardware tested?** No. The firmware compiles and a software simulation of the sensor is tested; the physical sensor and Web Serial are not tested.
* **Does GREEN guarantee accuracy?** No. It means no reliability flags were raised under the implemented rules.
* **Replace a medical device?** No. It is not a diagnostic device and is not clinically validated.
* **Next step?** Ethics approval, real paired data, participant-level validation of subgroup coverage and interval width, then a physical hardware test.

---
## D. Privacy and public-release review (external/openoximetry)
Inspected: `STATUS.md`, `reports/*.md`, `reports/*.json`, `reports/patient_conflicts.csv`, `metadata/official_docs/`.
* **Keep local / restricted (do not publish):**
  * `reports/patient_conflicts.csv`: full 64-character identifier hashes per encounter and patient (record-level).
  * `reports/import_audit.json`: contains short ID fragments in its `A_examples`.
  * `metadata/official_docs/`: the dataset's licence text and data dictionaries; redistribution rights unclear.
  * `raw/` (all dataset files).
  All four are already covered by `.gitignore`; there is no git repo, so also exclude them manually from any zip or upload.
* **Review before publishing:** `reports/final_data_resolution.md` contains a table with six-character ID fragments and a record number (about line 62). Redact those rows if you publish it.
* **Probably fine to publish (aggregate counts and questions):** `STATUS.md`, `decision_matrix_and_import_gate.md`, `author_clarification_package.md`, `author_email_draft.md`, `join_documentation.md`, `join_resolution.md`, `openoximetry_unblocking_report.md`, `metadata/raw_sha256.txt`. Re-read them for any ID or row detail first.
* Nothing was uploaded or transmitted during this audit.

---
## E. Checklists
**Before the presentation:** backend and frontend running · header "API v1.0.0" + "SOFTWARE TEST DATA" · Data Collection shows "REAL DATA: 0 records" · simulation banner visible in Live Monitor · rehearse A–E twice with a timer · backup screenshots (GREEN, AMBER, ABSTAIN, RED, insufficient calibration) · slides and speaker notes open · counts: 520 backend, 108 frontend.
**Before public code release:** choose and add a licence · review dataset provenance statements · scan for credentials (pattern scan found none; not a full secret scan) · keep external raw data, `patient_conflicts.csv`, `import_audit.json` and `official_docs/` out · redact ID fragments in `final_data_resolution.md` · remove local `backend/data`, `models`, `results` · confirm only distributable files are included.
**Future research (not done):** obtain permissions and ethical approval · resolve dataset-definition questions with the authors · collect or obtain valid paired SaO₂ and colour measurements · participant-level validation · evaluate subgroup empirical coverage and interval width · physical hardware test · assess clinical relevance only after validation.

---
REAL RESEARCH DATA: 0 · REAL RESEARCH VALIDATION: NOT AVAILABLE · PHYSICAL HARDWARE: NOT TESTED · WOKWI: NOT EXECUTED · VIRTUAL HARDWARE: TESTED FOR SOFTWARE INTEGRATION · SYNTHETIC PIPELINE: TESTED · CQR/MONDRIAN: IMPLEMENTED — REAL EMPIRICAL VALIDATION PENDING · CLINICAL VALIDATION: NOT AVAILABLE
