# OpenOximetry v1.1.1: unblocking report

**IMPORT DECISION: C. BLOCKED — AUTHOR CLARIFICATION REQUIRED**

EXTERNAL data only. Nothing was imported, averaged, deduplicated, normalized, converted or trained. Raw files are unchanged (hashes verified). No processed data exists.

## Step 1: sources checked
| Source | Result |
|---|---|
| PhysioNet page v1.1.1 | read |
| Scientific Data paper (Fong et al. 2025) | read in full |
| **Official data dictionary** (public Google Sheet linked from openoximetry.org/data-repository; tabs Fields, Tables, Waveform) | **found and read** (new in this step) |
| **Official study protocols** (public Google Docs linked from openoximetry.org/study-protocols): laboratory hypoxemia protocol, skin colour protocol, CM700d SOP | **found and read** (new) |
| Repository data-sharing terms | read (new) |
| PhysioNet Files tab (`SHA256SUMS`, any README, `_2hz.csv` waveform files) | **LOGIN REQUIRED**. Not accessed; I did not try to bypass it. |
| Authors' build code (`OpenOximetry/PublicDatabaseCode`) | HTTP 404, not available |

Copies and hashes: `metadata/official_docs/`, `metadata/official_docs_sha256.txt`, `metadata/official_docs_SOURCES.md`. **Caveats:** the dictionary is a live, unversioned Google Sheet and predates v1.1.1 in at least one respect (it types device ids as integers; the v1.1.1 files hold float ids). The study protocol describes laboratory practice, not how the CSV rows were built.

Terms of use that bind any use of these files: no redistribution of the data or any modified version, no sale, no sharing of access, no attempt to identify anyone; keep `external/` out of any shared or public repository.

## Step 8: decision matrix

Status values: RESOLVED / PARTIALLY RESOLVED / UNRESOLVED / LOGIN REQUIRED / AUTHOR CLARIFICATION REQUIRED. "A/B/C" = officially specified / supported by data structure / analyst assumption.

### Question A: blood gas rows
| Question | Official answer | Evidence | Status |
|---|---|---|---|
| What does one bloodgas row represent? | "The results from a single blood gas sample and clinical data from that time" (dictionary, paper). `type` 1 = ABG, 2 = VBG. | All 32,877 rows have type 1 (ABG). | **RESOLVED** |
| Why can one (encounter, sample) have several rows? | Not stated in the dataset documentation, and the dictionary says `sample` is "this sample's index in the sequence of ABG draws in a single encounter" (which implies one row per index). **The lab protocol (step 8) gives a likely explanation:** each blood sample is analysed on two ABL90 analysers; if the two SaO₂ results differ by more than 0.5 points a third analyser is used. | Data consistent with that: 12,051 groups with 2 valid SaO₂ rows, 99.99% within 0.5 (max 1.0, so one or a few groups outside); all 293 groups with 3 rows contain at least one pair within 0.5; but only 40% of 3-row groups show a >0.5 gap between the first two rows (time order), 5,255 groups have a single row, and 243 groups have 4 or more rows (6 valid rows in one), none of which the protocol explains. 526 rows are exact duplicates. | **PARTIALLY RESOLVED** → **AUTHOR CLARIFICATION REQUIRED** |
| Separate measurement, or duplicate? | Not stated for the files. Protocol implies repeated analyses of the same blood sample. | Rows in a group differ in pH, pCO₂, pO₂, COHb, MetHb, tHb in 73–93% of groups, so they are not copies; 526 rows are exact duplicates. | **PARTIALLY RESOLVED** |
| Why do pH/pCO₂/pO₂ differ between rows? | Not stated. Consistent with different analysers/runs of one sample (B). | Same as above. | **PARTIALLY RESOLVED** |
| Which SaO₂ pairs with the pulse-ox reading? | **Protocol (A for lab practice):** "If two SaO2 values are within 0.5% then the average of those two results are recorded as the sample's SaO2"; if no two of three agree the data point is excluded during cleaning. The released file holds the individual rows, not the recorded sample value. | The mapping "rows = the analyser results this rule is applied to" is B, not stated in the dataset documentation. | **PARTIALLY RESOLVED** → **AUTHOR CLARIFICATION REQUIRED** |
| Is averaging officially recommended? | Averaging two agreeing analyser results is the **laboratory protocol's own rule** for the sample's SaO₂. Not stated in the dataset documentation for the CSV rows. | Protocol step 8. | **PARTIALLY RESOLVED** |
| Is first-row selection officially recommended? | No. Not mentioned anywhere. | | **UNRESOLVED** (not supported) |
| Should all rows be retained? | Not stated. | | **UNRESOLVED** |
| **Is `bloodgas.so2` officially the arterial reference SaO₂?** | The dictionary defines `so2` only as "Oxygen saturation, percent". The paper says the blood gas table "contains blood gas data, including arterial functional saturation (SaO2)"; the protocol says the ABL90 co-oximeter gives the "true functional saturation (SaO2)" and warns that some labs use fractional O₂Hb instead. **No document states "so2 = functional SaO₂" by name**, or whether `so2` is functional or fractional. `ScalcO2` is explicitly the imputed (calculated) value, so it is not the reference. | The inference by elimination (the only measured saturation field in an all-ABG table) is **ANALYST INFERENCE**; it was not made from the value range. | **AUTHOR CLARIFICATION REQUIRED** |

### Question B: participant identity
| Question | Official answer | Evidence | Status |
|---|---|---|---|
| Which ID is authoritative for encounter → participant? | Not stated. The dictionary defines `patient_id` identically in the patient, encounter, bloodgas and spectrophotometer tables, and says "Each encounter corresponds to one participant (i.e. each row has one participant ID)" about the encounter table. | 18 encounters conflict (blood gas 7 encounters / 9 rows; spectrophotometer 11 / 261 rows; none in both). All 237 `encounter.csv` ids are in `patient.csv`; in 3 conflicts the alternate id is not in `patient.csv` at all. The dictionary states the date offset is "consistent for a given patient between encounters": 16 of 18 encounters fall inside the year range of the `encounter.csv` participant's other encounters, **0 of 15** assessable inside the alternate's. | **UNRESOLVED**. `encounter.csv` is only an **ANALYST INFERENCE** (strongly supported). **AUTHOR CLARIFICATION REQUIRED** |
| For splitting | Use none of the 18 conflicting encounters until answered (your rule; an analyst exclusion). | `reports/patient_conflicts.csv` | — |

### Question C: perfusion index
| Question | Official answer | Evidence | Status |
|---|---|---|---|
| Definition of `pulseoximeter.pi` | Dictionary: "The perfusion measurement as reported by the device, typically 'perfusion index'." | | **PARTIALLY RESOLVED** (definition: device-reported) |
| Unit | Not stated anywhere. | Observed ranges are very different between devices (median 1.8 to 177). | **UNRESOLVED** |
| Calculation | Not stated; it is whatever each device reports (manufacturer-defined). | | **UNRESOLVED** |
| Source / device dependence | Device-reported, so device-dependent by definition. The lab protocol says perfusion is measured with reference devices: Nellcor PM1000N "pulsatility amplitude signal output", Masimo Radical-97 "perfusion index", and a custom raw PPG device; for test devices that do not measure perfusion a reference device on an adjacent finger "approximates" it. It is not stated which source supplies `pi` in any given row. | Devices 60, 73, 76, 59, 64 are tabletop (type 3) and 55 handheld (type 1); `devices.csv` lacks make and model. | **UNRESOLVED** → **AUTHOR CLARIFICATION REQUIRED** |
| Comparable between devices? | Not stated; the description ("as reported by the device") and the different measures named in the protocol (amplitude vs index) argue against it. | | **UNRESOLVED** |
| Same as the 2-Hz waveform PI? | Not stated. The 2-Hz files are described as holding "pulsatility index (PI)" of reference oximeters (the paper's body text calls the field a "signal quality indicator"). They require the PhysioNet login. | | **LOGIN REQUIRED** / **AUTHOR CLARIFICATION REQUIRED** |

**PI = NOT USABLE FOR PRIMARY ANALYSIS.** No conversion, no threshold (PI < 1 = Low is not applied), no combining of devices.

### Question D: device and probe
| Question | Official answer | Evidence | Status |
|---|---|---|---|
| device_id | Integer part. Release notes: "The integer represents the device ID as per previous versions." Dictionary: `device` = "OpenOximetery unique device identifier". | | **RESOLVED** |
| probe_id (decimal) | Release notes: "The decimal represents probe ID" (e.g. 36.01 = device 36, probe 1). The note is attached to the bloodgas table, which has no device column; it is not stated for `pulseoximeter.device` / `encounter` columns. | `N.0x` strings are shared between `encounter.csv` and `pulseoximeter.csv` in about 92% of encounter-device pairs. | **PARTIALLY RESOLVED** |
| Integer-only strings (`55`, `36`) and `N.0` (`55.0`, `36.0`) | The integer part is the device. Nothing says which probe, or whether `.0` means "none". | Never assigned as such in `encounter.csv`. 44,652 of the 47,142 integer-form rows have an empty `probe_location`. | **UNRESOLVED** for probe |
| `probe_location` | **Official mapping:** 1–5 = L1–L5, 6–10 = R1–R5 (finger position, not a probe model). | Matches the encounter slots in 88% of triples (consistent with the dictionary). Meaning of an empty value is not stated. | **RESOLVED** (mapping); empty values **UNRESOLVED** |
| `device_type` | 1 = handheld, 2 = fingertip, 3 = tabletop. | | **RESOLVED** |
| `devices.csv` content | The dictionary lists make, model, light type and probe columns; the delivered file has only `device_number` and `device_type`; ids 50 and 74 are assigned in `encounter.csv` but absent. | | **UNRESOLVED** (cannot map device ids to models) |
| `56 .01` | No official statement. | 25 rows, 1 encounter; the same encounter family uses `56.01`. | **UNRESOLVED**. Not repaired. |

**Device normalization proposal (only what the official representation supports; nothing applied):** `device_id` = integer part of the string (A). `probe_id` = the decimal digits when the string has the form `N.0x` (A rule, applicability B); `NULL` (unknown, not 0) for integer-only and `N.0` strings. `56 .01` (25 rows) and the 190 empty device strings go to a quarantine list (no repair). The proposal was not applied to any file.

### Question E: palmar skin colour
| Question | Official answer | Evidence | Status |
|---|---|---|---|
| Meaning of `lab_l`, `lab_a`, `lab_b` | CIELAB "L* value / a* value / b* value" (dictionary); instrument Konica Minolta CM700d (skin protocol). | 2,382 palmar rows; no L* = 0; none outside plausible Lab ranges. | **RESOLVED** |
| Flags | 60 rows (20 encounters) have all Lab values missing. The protocol's own data review looks for "zero reflectance or color difference > 15 ΔE\*ab between repeat measures": 12 palmar rows have Lab values but all-zero or missing reflectance spectra; 6 of 705 assessable palmar encounters exceed ΔE\*ab 15 between repeats (maximum 20.4). | `reports/protocol_consistency_checks.json` | flagged only, **not repaired** |
| Aggregation of repeated palmar readings | **No official rule.** Facts: three measurements at one site taken by pressing capture without removing the probe; "consider measuring up to five times"; encounters have 3, 6 or 9 palmar rows (11 span more than one date). | | **UNRESOLVED**: aggregation is **ANALYST-DEFINED**. **AUTHOR CLARIFICATION REQUIRED** |
| ITA group boundaries | OpenOximetry skin protocol: light ITA > 41°, medium 41° to −30°, dark < −30° (Del Bino-based). The project's current thresholds (Dark ≤ 10°) differ. | Palmar ITA ranges from −59.8° to 52.8°. | **Project decision (C)**, not a data ambiguity |

## Step 9: import decision
**C. BLOCKED — AUTHOR CLARIFICATION REQUIRED.**

**Exact blockers**
1. The reference SaO₂ column (`so2`) is not officially confirmed to be the functional arterial SaO₂, and the repeated rows are only partly explained (protocol-based, not dataset documentation). Without these, the target label is uncertain.
2. The authoritative participant id for 18 encounters is not defined.
3. `pi` has no unit or comparability, so PI cannot be used. The project's model and its ITA × PI subgroups need PI, so an external dataset without PI cannot serve the stated purpose, which is why a "limited import" is not offered.
4. Repeated palmar readings have no official aggregation rule.

The credential access is not the blocker: the official dictionary and protocols were public. The PhysioNet Files tab (`_2hz` files, any in-release README) would only help question C, and still needs your login.

**What would change the decision to B (limited import):** author confirmation of blockers 1, 2 and 4, plus a decision to use the external data **without PI** (SpO₂ vs SaO₂ and ITA only, e.g. for a bias analysis, not for the full conformal pipeline). It would still carry the labelled analyst choices: the palmar aggregation, and the protocol's averaging if confirmed.

A smaller clean dataset is preferable to a large one with uncertain labels, so no import was started.
