# OpenOximetry: decision matrix, import gate and paths

**OpenOximetry external validation dataset: BLOCKED — AUTHOR CLARIFICATION REQUIRED.**

| Status line | Value |
|---|---|
| SOFTWARE PIPELINE STATUS | operational (tested on test-fixture data only; the app itself shows NO RESEARCH DATA) |
| REAL-DATA VALIDATION STATUS | not yet established |
| OPENOXIMETRY IMPORT STATUS | blocked |
| CLINICAL VALIDATION STATUS | not performed |

`external/openoximetry/processed/` is empty. Raw files are unmodified (6 hashes re-verified on 2026-10-07).

## 1. Final audit verdict
OpenOximetry v1.1.1 contains paired SpO₂, arterial blood gas SaO₂, CIELAB skin colour and a device-reported perfusion value, so it is a **candidate** dataset. The audit could not establish four things the method needs for a defensible, reproducible import: the reference SaO₂ definition and row selection, the authoritative participant identity for 18 encounters, the definition and comparability of PI, and the handling of repeated CIELAB readings. A smaller clean dataset is preferable to a large dataset with uncertain labels, so nothing was imported. The data do not validate (or invalidate) the proposed method; no performance or coverage number exists.

## 2. Decision matrix
Status uses only: RESOLVED / PARTIALLY RESOLVED / UNRESOLVED / AUTHOR CLARIFICATION REQUIRED. Nothing is marked resolved unless official documentation supports it.

| QUESTION | CURRENT EVIDENCE | STATUS | WHAT AUTHOR MUST CONFIRM | EFFECT IF UNRESOLVED |
|---|---|---|---|---|
| What is a bloodgas row? | Dictionary and paper: "results from a single blood gas sample"; `type` 1 = ABG (all 32,877 rows). | **RESOLVED** | nothing | none |
| Is `so2` the arterial functional SaO₂ reference? | Dictionary: "Oxygen saturation, percent". Paper: the blood gas table contains arterial functional SaO₂. Protocol: ABL90 co-oximetry gives functional SaO₂ (and warns some labs use fractional). No document maps `so2` to that by name. | **PARTIALLY RESOLVED** → **AUTHOR CLARIFICATION REQUIRED** | `so2` = arterial functional SaO₂ | The regression target is undefined; no model may be trained. |
| Which blood-gas row(s) pair with a pulse-ox reading? | Protocol step 8: two analysers per sample, third if >0.5 apart, average of two agreeing results is the sample's SaO₂, excluded if none agree. Data: 12,051 two-valid-row groups, 99.99% within 0.5; 293 three-row groups all contain a pair within 0.5 (only 40% show a >0.5 gap between the first two); 5,255 single-row groups, 243 groups with 4+ rows, 526 exact duplicates are unexplained. Dictionary says `sample` is the index of an ABG draw (implies one row). | **PARTIALLY RESOLVED** → **AUTHOR CLARIFICATION REQUIRED** | rule for 1-row, 2-row, 3-row, 4+ row and exact-duplicate groups | Label noise or selection bias; averaging or picking a row would be an undocumented assumption. |
| Authoritative participant ID? | 237 `encounter.csv` ids all in `patient.csv`. 18 encounters conflict (blood gas 7 / 9 rows, spectrophotometer 11 / 261 rows). Date-offset check (official property: offset consistent per patient) favours `encounter.csv` in 16 of 18, and the alternate in 0 of 15. No official statement of authority. | **UNRESOLVED** → **AUTHOR CLARIFICATION REQUIRED** | which table prevails; whether those 18 encounters are known errors | Participant leakage risk in the participant-level split, and mislabelled skin colour. Until answered, the 18 encounters are excluded (an analyst exclusion, labelled as such). |
| What is `pulseoximeter.pi`? | Dictionary: "The perfusion measurement as reported by the device, typically 'perfusion index'." No unit, scaling or calculation anywhere. Protocol names heterogeneous perfusion sources (a Nellcor pulsatility amplitude, a Masimo perfusion index, a custom PPG device). Observed per-device medians from 1.8 to 177; devices 59, 64, 76 are whole numbers only. | **PARTIALLY RESOLVED** (definition only) → **AUTHOR CLARIFICATION REQUIRED** | definition, unit, scaling, per-device comparability, relation to the `_2hz` PI | PI is **not usable**: the PI < 1 = Low rule and the ITA × PI cells cannot be applied; the core model cannot be built from this data. |
| Device and probe notation | Release notes: integer = device ID, decimal = probe ID (attached to the blood gas table). Dictionary: `probe_location` 1–5 = L1–L5, 6–10 = R1–R5; `device_type` 1 handheld, 2 fingertip, 3 tabletop. `N.0x` strings are shared keys between `encounter.csv` and `pulseoximeter.csv` (about 92% of pairs). | **PARTIALLY RESOLVED** (integer part, `probe_location`, `device_type` are RESOLVED) | meaning of integer-only and `N.0` strings, empty `probe_location`, `56 .01`, applicability of the decimal rule to the pulse-ox and encounter tables, missing `devices.csv` columns | Device grouping by integer part is safe; probe-level analysis and device-specific PI handling are not. |
| Repeated palmar CIELAB readings | Dictionary: `lab_l/a/b` = L\*, a\*, b\*. Protocol: three readings per site without lifting the probe; data review for zero reflectance or ΔE\*ab > 15 between repeats (6 of 705 palmar encounters exceed 15; 12 palmar rows have Lab but zero/missing reflectance). No aggregation rule. | **UNRESOLVED** → **AUTHOR CLARIFICATION REQUIRED** | official rule, or confirmation that a documented analytical aggregation is acceptable | Any mean/median is an analyst choice and must be disclosed; ITA per encounter is otherwise undefined. |
| ITA group boundaries | OpenOximetry's skin protocol uses its own bins (dark below −30°). The project's thresholds are a **project-defined analytical choice** and are not replaced. | **Project decision, not a data ambiguity** | nothing | Subgroup counts differ by definition; always report which thresholds were used. |
| Files behind the PhysioNet login (`_2hz`, any README) | Not inspected; LOGIN REQUIRED. | **UNRESOLVED** | n/a | The PI relationship cannot be checked. |

## 3. Safe import gate
OpenOximetry may enter `external/openoximetry/processed/` **only when every box is ticked**. The gate is checked by a person, not by the code.

- [x] Raw files preserved: SHA-256 recorded (`metadata/raw_sha256.txt`) and re-verified; no raw file modified.
- [x] `processed/` is empty at this time.
- [ ] Reference SaO₂ definition confirmed in writing by the authors or in an official document (`so2` = arterial functional SaO₂).
- [ ] Blood-gas row-selection rule confirmed for 1-row, 2-row, 3-row, 4+ row and exact-duplicate groups.
- [ ] Participant-ID conflict rule confirmed for the 18 encounters (or a documented exclusion approved by the investigator and labelled as an analyst exclusion).
- [ ] PI definition, unit and cross-device comparability confirmed, or PI formally excluded and the import re-scoped (an external set without PI cannot feed the ITA × PI pipeline).
- [ ] Repeated-CIELAB handling rule documented (official, or an analytical rule written down before looking at results).
- [ ] Every preprocessing step written down (`reports/preprocessing_rules.md`), each tagged A (officially specified), B (data structure) or C (analyst assumption), with the source of the answer quoted.
- [ ] Every excluded row has a reason in an exclusion report; nothing silently dropped.
- [ ] Participant-level split planned before looking at outcomes; patient is the unit; no patient in more than one of train/calibration/test.
- [ ] The processed file carries `data_source = EXTERNAL_OPENOXIMETRY` and is never merged with own project data.
- [ ] Data-use terms respected: no redistribution of the data or modified versions, no identification attempts, `external/` kept out of any shared or public repository.

## 4. Two paths
### PATH A: authors respond
1. Save the reply under `metadata/author_reply/` with date and sender; update `join_resolution.md` and the matrix above (mark RESOLVED only for what they confirm in writing).
2. Write `reports/preprocessing_rules.md` with every rule, its source and its A/B/C tag.
3. Implement the preprocessing as a deterministic script with fixed ordering, logged exclusions and recorded hashes of inputs and outputs; check it with tests on fixtures only.
4. Create the processed dataset (`data_source = EXTERNAL_OPENOXIMETRY`) and an audit trail of counts per step.
5. Split by participant before any modelling; check no leakage.
6. Only then train; evaluate on the held-out test split; label results as external-dataset results, with their limitations (lab desaturation study, different devices, not the ESP32 + MAX30102).

### PATH B: authors do not respond (after a reasonable period, e.g. 4–6 weeks and one reminder)
- **Do not force OpenOximetry into the research dataset.** Keep it as an audited external candidate with the reports above.
- Software validation continues with the test fixtures that are already in the automated tests (synthetic, labelled, in temporary folders); no synthetic result is reported as a finding, and the app itself stays free of demo data.
- Look for another public dataset that has reference SaO₂, objective pigmentation (L\*a\*b\* or ITA) and a defined PI, and audit it the same way before any use.
- Or collect primary data with ethics approval and consent: ESP32 + MAX30102 sessions, reference SaO₂ with timestamps, colorimeter L\*a\*b\*, participant/session matching, as the project already supports.
- The paper can state that the external data were audited and not used (note below).

## 5. Data-quality rules that stay in force
Never invent SaO₂; never infer PI units or assume PI comparability; never resolve participant conflicts silently; never average repeated measurements without a documented rule; never fabricate ITA or calibration cells; never report synthetic results as real-world findings. Cells with too few calibration participants use the pre-documented merge rule or show INSUFFICIENT CALIBRATION DATA.

## 6. Researcher note (for Methods / Data Availability)
> The OpenOximetry v1.1.1 repository (PhysioNet; credentialed access) was identified as a candidate external dataset containing paired pulse-oximeter readings, arterial blood-gas SaO₂, spectrophotometric CIELAB skin colour and a device-reported perfusion value. We audited the released tables against the public data dictionary, the Scientific Data descriptor and the Hypoxia Lab protocols, preserving the raw files unchanged and documenting every join. As a methodological and data-governance decision, these data were not used for model training or validation: several definitions required for a reproducible analysis were not specified in the official documentation, namely the selection or aggregation rule for repeated blood-gas rows sharing a sample number, the authoritative participant identifier for 18 encounters with conflicting identifiers, the unit and cross-device comparability of the perfusion variable, and the handling of repeated colourimetric readings. We have requested clarification from the dataset maintainers and will incorporate the dataset only if written, citable answers resolve these points. No performance or calibration results were derived from the unresolved data, and no assumption was introduced to fill these gaps.

## 7. Exact next action
1. **You:** fill in your name and affiliation in `reports/author_clarification_package.md` and send it through https://openoximetry.org/contact/. Note the date.
2. **You (optional, with your login):** download `SHA256SUMS.txt` and one `_2hz.csv` file (e.g. for encounter `01a542fe…1969`) so I can compare `pi` with the waveform PI as additional evidence.
3. **Me, on request:** when the reply arrives, update the matrix and gate. Until then nothing is imported and nothing is trained.
