# OpenOximetry v1.1.1: join documentation and import audit

**STATUS: EXTERNAL DATA IMPORT BLOCKED** (two ambiguities the official documentation does not resolve; nothing was guessed).
EXTERNAL data only. Never merged with `backend/data/` or the project's own research dataset. No model was trained and no result was produced.

Source: PhysioNet `openox-repo` 1.1.1 (credentialed access, PhysioNet Restricted Health Data License 1.5.0).
Raw copies: `raw/*.csv` (byte-identical to the downloaded files, read-only; SHA-256 in `metadata/raw_sha256.txt`).
Machine-readable audit numbers: `reports/import_audit.json` (script: `audit_import.py`).

## 1. What the official documentation says (quoted from the PhysioNet page)
- `patient_id` identifies a person across encounters; `encounter_id` links all data of one session; `sample_number` identifies a blood gas draw within an encounter.
- "Each row contains one saturation reading from one pulse oximeter, corresponding to a specific controlled desaturation encounter (identified by `encounter_id`), and a specific blood gas (identified by `sample_number`)."
- Pulse oximeter and blood gas tables both use `encounter_id` + `sample_number` to link paired SpO₂ and SaO₂ at the same time point.
- "Spectrophotometer measurements are typically taken three times at each anatomic site, and repeated at each encounter", linked by `encounter_id` and `patient_id`.
- Device IDs in v1.1.1 "are now in float form. The integer represents the device ID ... The decimal represents probe ID" (36.01 = device 36, probe 1).
- The laboratory desaturation data are "provided unprocessed as collected"; a standardized cleaning process is planned for later releases.
- The page does **not** state: the units of pulsatility index (PI); the meaning of the `bloodgas.type` column; how repeated blood gas rows for one sample should be handled; what to do when an encounter has more than one patient id.

## 2. Join keys used in this audit (all documented)
| Link | Keys |
|---|---|
| pulse oximeter ↔ blood gas | `encounter_id` + `sample_number` (pulseoximeter) = `sample` (bloodgas) |
| spectrophotometer ↔ encounter | `encounter_id` (site filter: `group == "Palmar (C)"`) |
| encounter → patient | `encounter.csv` (`patient_id`), other tables carry `patient_id` too |
| device | `device` string parsed as `<device>.<probe>`; the integer part is the device ID |

## 3. Ambiguities that BLOCK the import
### 3a. Several blood gas rows per (encounter, sample): not resolved by the documentation
The documentation says `sample_number` identifies *a* blood gas draw, but the data have more than one row per (encounter, sample):
- bloodgas.csv: 18,685 (encounter, sample) groups (257 rows with no encounter_id are excluded from the grouping); 5,568 have 1 row, 12,558 have 2, and 559 have 3 or more. 526 rows are exact duplicates of another row.
- Rows in one group are a median of 60 s apart (a few groups span far longer, which points to date anomalies); SaO₂ ("so2") differs inside a group by a median of 0.2 and up to 1.0 percentage points. In the encounter inspected by hand, different samples share clock times, so time alone does not identify the draw.
- For the target pulse-oximeter rows (devices 55, 60, 73, 76, clean): 21,383 rows → 4,584 match exactly 1 blood gas row, 14,646 match 2, 617 match 3 or more, 1,536 match none.
- Possible handlings (average, first, nearest in time, keep all pairs) give different datasets and different effective sample sizes. The documentation gives no rule, and the pulse oximeter table has no timestamp to choose the nearest row. **No rule was applied.**
- A 1:1-only subset exists (3,669 rows, 217 encounters, 104 patients, almost all device 60) but selecting it is itself a choice that would bias the sample toward certain encounters, so it was not built.

### 3b. Encounters linked to more than one patient: not resolved by the documentation
- bloodgas.csv: 7 encounters carry 2 different `patient_id` values; spectrophotometer.csv: 11 encounters carry 2–3. These disagree with `encounter.csv`.
- A patient-level split is the leakage guard of this project, so the patient identity of every row must be certain. The documentation does not say which table is authoritative. **No patient id was chosen.**

## 4. Facts that are not ambiguous
- **PI (target devices):** device 60 (16,162 rows, PI 0.06–18, median 1.8), device 73 (4,020 rows, 0.06–15, median 2.7), device 76 (575 rows, 2.0–37, median 8.0); no missing PI. Device 55 has PI only on the 631 rows whose device string is the integer form "55" (min 0.25, median 2.8, max 17.0); its 3,041 probe-form rows (55.0, 55.01, 55.02, 55.03) have no PI (82.8% missing) and are excluded. Units are **not documented**; no conversion was made. Device 76's range (up to 37) is wider than the others'.
- **Exclusions so far (target pulse-oximeter rows):** 24,429 source rows → 5 SpO₂ outside 50–100; 3,041 PI missing; 0 non-numeric SpO₂ (the 11 text notes in the file belong to other devices); 0 unparsable device strings; 0 with PI ≤ 0 → 21,383 remain.
- **Palmar skin colour:** 2,382 palmar rows, 60 with a missing Lab value; 705 encounters have a valid palmar reading (657 with 3 readings, 46 with 6, 2 with 9). ITA per reading ranges −59.8° to 52.8°. Repeats within an encounter agree to a median of 1.1° (90th percentile 5.3°, maximum 72.3°, so some repeats are inconsistent). How to combine repeats (mean, median) is a modelling choice that is not defined by the documentation and was not applied.
- 18,348 clean target pulse-oximeter rows belong to an encounter with palmar skin colour (before any blood gas pairing).

## 5. What is needed to unblock
1. Ask the dataset authors (or find in the paper's supplementary material / data dictionary) the intended meaning of repeated blood gas rows per sample, and the authoritative `patient_id` for the 18 conflicting encounters; or
2. You explicitly choose and accept a documented handling rule for each (for example: exclude all encounters with a patient-id conflict; pair each pulse-oximeter row with the mean of the blood gas rows of its sample, or the maximum-agreement subset), knowing it is an analyst's assumption, not the dataset's definition.
