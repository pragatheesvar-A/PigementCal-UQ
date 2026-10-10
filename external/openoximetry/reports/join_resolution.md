# OpenOximetry v1.1.1: resolution of the join ambiguities

EXTERNAL data only. Nothing was imported, averaged, deduplicated, dropped, converted or trained in this step; `processed/` is still empty.

## Official sources consulted
| Tag | Source | Reachable |
|---|---|---|
| [PN] | PhysioNet page, OpenOximetry Repository v1.1.1: https://physionet.org/content/openox-repo/1.1.1/ | yes |
| [SD] | Fong, Lipnick, Behnke et al., "Open Access Dataset and Common Data Model for Pulse Oximeter Performance Data", *Scientific Data* 12:570 (2025), doi 10.1038/s41597-025-04870-8 (read as the UCSF eScholarship PDF, 9 pages) | yes |
| [SD-pre] | medRxiv preprint 10.1101/2024.08.30.24312744 | no (HTTP 403) |
| [CODE] | https://github.com/OpenOximetry/PublicDatabaseCode (named in [SD] "Code availability") | **no (HTTP 404)** |
| [DICT] | A data dictionary: both [PN] and [SD] say one exists, but [SD] states the paper has no explicit column table and no dictionary file was reachable | **not available to me** |

Because [CODE] and [DICT] could not be read, anything those would define is marked NOT RESOLVED. The credentialed PhysioNet file listing may contain a README / data dictionary that I cannot see.

"Local observation" notes below come from the downloaded CSVs. They are **not official evidence** and are not used to reach any conclusion.

---

## ISSUE 1: repeated blood gas rows per (encounter_id, sample): **NOT RESOLVED BY OFFICIAL SOURCE**

| Q | Official evidence | Conclusion |
|---|---|---|
| **A. Why can several rows exist for one encounter + sample?** | [SD] and [PN]: "Each row represents the results from a single blood gas sample and clinical data from that time"; Table 1 of [SD]: "Each row represents the results from a single blood gas sample linked to a specific desaturation plateau and pulse oximeter reading (identified by sample_number)". [SD] Methods: "The saturation reading of each test device at the time the sample is taken was simultaneously recorded and was denoted incrementally as the 'sample number' within an encounter." | The documented model is **one row per sample number**. The delivered file has more than one row for most (encounter, sample) pairs. **OFFICIAL SOURCE DOES NOT DEFINE THIS** (why, or what the extra rows are). |
| **B. Which column is the reference SaO₂?** | [SD]: the blood gas table "contains blood gas data, including arterial functional saturation (SaO2)", measured with a Radiometer ABL90 Flex Plus co-oximeter. [SD]/[PN] describe `ScalcO2` as "the instantaneously estimated SaO2 based on ETO2" (a calculated value, not the reference). | The official text names the quantity (SaO₂ from the ABL90 co-oximeter) but **does not name the CSV column** in any source I could read. **OFFICIAL SOURCE DOES NOT DEFINE THIS** by column name. |
| **C. What are the repeated rows?** (duplicates / repeats / vital-sign convenience rows / different devices / other) | [PN] release notes v1.1.1: "`bloodgas`: ... includes vital signs from the `_2hz` waveforms file" as a convenience. This describes extra **columns** (e.g. `dev60_HR`, `ETCO2`), not extra rows. [PN]: "laboratory desaturation data is provided unprocessed as collected. In upcoming releases ... we will implement a standardized data cleaning process to filter out potential artifacts or inaccuracies." | **OFFICIAL SOURCE DOES NOT DEFINE THIS.** The only related official statements are (i) rows = single blood gas samples, (ii) data are unprocessed, cleaning is planned. |
| **D. Is there an official selection/aggregation rule?** | [SD] Usage Notes: join `pulseoximeter` to the blood gas table "on 'encounter_id' and 'sample' (to obtain the ABG results for each sample during the encounter)". [SD] technical validation: "Data changes ... were minimized as much as possible." | The join keys are official. **No rule for choosing among, or aggregating, several rows is given.** **OFFICIAL SOURCE DOES NOT DEFINE THIS.** |
| **E. Does the paper/dictionary specify averaging, first row or another method?** | None found in [PN] or [SD]. | **OFFICIAL SOURCE DOES NOT DEFINE THIS.** |

**Local observation (not official).** In bloodgas.csv, 18,685 (encounter, sample) groups (257 rows without an encounter_id are not in a group): 5,568 have 1 row, 12,558 have 2 and 559 have 3+; 526 rows are exact duplicates of another row; 552 of 759 encounters have at least one repeated sample number. In one mid-sized encounter inspected row by row, rows in clock order were not in sample order, and several sample numbers appear twice 1–2 minutes apart with slightly different SaO₂ (e.g. 96.4 and 96.3; 86.5 and 86.5 with different PO₂). That pattern is *compatible with* replicate analyses, but it equally fits other explanations, so it was not used.

**Remaining ambiguity.** What the extra rows are; which row (if any) is "the" reference for a pulse oximeter reading; whether replicate rows are independent measurements; which column is SaO₂ (`so2` is the only measured saturation column in the table, but that is my inference, not an official statement). The pulse oximeter table has **no timestamp**, so a time-nearest pairing is not possible and `sample_number` is the only official link.

**Recommended action.** (1) Ask the PhysioNet data contact / paper authors (Hypoxia Lab, UCSF) exactly these questions: what do repeated rows per `sample` represent; which column is the reference SaO₂; is there a recommended selection rule. (2) Check the credentialed "Files" tab on PhysioNet for a README or data dictionary. (3) Do not import until answered, or until you explicitly accept an analyst rule (to be labelled as an assumption in every result).

---

## ISSUE 2: encounter → patient conflicts: **NOT RESOLVED BY OFFICIAL SOURCE**

| Q | Official evidence | Conclusion |
|---|---|---|
| Which table is authoritative for encounter_id → patient_id? | [SD] and [PN]: "Each encounter corresponds to one participant (i.e., each row has one participant ID)", said of the **encounter** table, which "includes information from a single encounter ... examining a single encounter requires looking at only one row of the encounter table; this is not the case for other files". "Most tables have the primary key, encounter_id." Spectrophotometer rows are "linked to the encounter via encounter_id and to the patient via patient_id." Patients: "each participant having one row in the participants file." | The official data model **implies** one participant per encounter and treats the encounter table as the one-row-per-encounter table. **No official statement ranks the tables when they disagree**, and the spectrophotometer is documented as linking to the patient by its own `patient_id`. **OFFICIAL SOURCE DOES NOT DEFINE THIS.** |
| What should happen to rows whose patient_id disagrees? | Not addressed. | **OFFICIAL SOURCE DOES NOT DEFINE THIS.** |

**Local observation (not official).** encounter.csv has 907 rows, no duplicate encounter_id, no missing patient_id. 18 distinct encounters have conflicts: 7 in bloodgas.csv (323 of 332 rows agree with encounter.csv, 9 disagree) and 11 in spectrophotometer.csv (297 of 558 rows agree, 261 disagree). The conflicting ids are real participants elsewhere in the data. patients.csv was not downloaded, so I could not check it.

**Remaining ambiguity.** Whether encounter.csv or the other table is correct in the 18 encounters, and whether the conflicting rows were attached to the wrong encounter or the wrong participant. Because the project's leakage guard is a participant-level split, a wrong participant for any row could put one person in two splits.

**Recommended action.** Ask the authors which table prevails and whether these 18 encounter_ids are known errors. Download `patients.csv` as an additional (non-decisive) cross-check. Until then, do not guess and do not drop; keep the 18 encounters flagged. If you want to proceed anyway, the least arbitrary option is a documented, explicit rule such as "use encounter.csv's patient_id for the whole encounter", stated as an assumption.

---

## ISSUE 3: device / probe interpretation: **PARTLY STATED, NOT RESOLVED FOR USE**

| Q | Official evidence | Conclusion |
|---|---|---|
| How are device and probe IDs represented? | [PN] release notes v1.1.1: "device IDs are now in float form. The integer represents the device ID as per previous versions. The decimal represents probe ID". [SD]: the device table has "a unique device ID number, as well as the make, model, and light transmission mode of the oximeter (and probe)." | **RESOLVED BY OFFICIAL SOURCE (the rule):** `<device>.<probe>`, so `36.01` is device 36, probe 1. |
| Where does this apply? | The release note attaches the sentence to the **bloodgas** table. | **NOT RESOLVED.** bloodgas.csv has no device column (only `devNN_HR` column names). Float-form IDs actually occur in **encounter.csv** and **pulseoximeter.device**. The note does not say it applies to those. |
| Are `55`, `55.0`, `55.01` ... the same device? Is `55` (no decimal) the old format with an unknown probe? | Only "The integer represents the device ID as per previous versions". | **NOT RESOLVED.** No statement on the integer-only form, or on `N.0`. |
| What is the pulseoximeter `probe_location` column (values 1–10, or empty)? | Not described in [PN] or [SD]. | **OFFICIAL SOURCE DOES NOT DEFINE THIS.** |
| What to do with `56 .01` (25 rows) and 190 empty device values? | Not addressed. | **OFFICIAL SOURCE DOES NOT DEFINE THIS.** Not normalized. |
| The paper's join instruction | [SD]: join on `encounter_id` and `device_id`. | The delivered column is called `device`, not `device_id`. The data dictionary that would explain this was not available. |

**Local observation (not official).** pulseoximeter.device: 47,142 integer-form rows, 20,152 `N.0`, 21,920 `N.0x`, 25 containing a space, 190 empty. encounter.csv device columns use `N.0x` forms (e.g. 59.02, 60.01). The PI-bearing devices (55, 59, 60, 64, 73, 76) match the `devNN_HR` convenience columns in bloodgas.csv (55, 60, 59, 64, 71, 73, 76).

**Consequence for your device selection.** Device 55 has PI only on its 631 integer-form rows; its probe-form rows (55.0 to 55.03) have no PI. Whether those rows are the "same device" is not defined, so device 55's PI rows were not extended to its other rows.

**Remaining ambiguity / action.** Confirm with the authors how integer-only, `N.0` and `N.0x` device strings relate and what `probe_location` means. No device string was normalized.

---

## ISSUE 4: perfusion index (PI): **NOT RESOLVED BY OFFICIAL SOURCE**

| Q | Official evidence | Conclusion |
|---|---|---|
| Is `pi` in pulseoximeter.csv the same PI as in the 2 Hz reference waveform files? | [SD] Table 1 and [PN]: the `_2hz` reference-oximeter files "contain SpO2, HR, and pulsatility index (PI) recorded at 2 Hz". The body of [SD] says the same files contain "SpO2, HR, and a signal quality indicator". The **pulseoximeter table's `pi` column is not described anywhere** in [PN] or [SD]. | **NOT RESOLVED.** PI is documented only for the 2 Hz files, and even there the two official texts disagree (pulsatility index vs signal quality indicator). Nothing links the `pi` column to those files. |
| Does the official documentation define PI units? | None found. | **OFFICIAL SOURCE DOES NOT DEFINE THIS.** |
| Do different devices' PI ranges share one unit? | Not stated. | **NOT RESOLVED.** No conversion is supported. |

**Local observation (not official).** pi (non-empty) exists for devices 55, 59, 60, 64, 73, 76 only. Ranges by device: 55: 0.25 to 17.0 (median 2.8); 59: 1 to 255 (25); 60: 0.06 to 18 (1.8); 64: 4 to 1717 (177); 73: 0.06 to 15 (2.7); 76: 2 to 37 (8). Those wide differences between devices, and the absence of any PI definition, mean the numbers cannot be treated as one scale. The `_2hz.csv` waveform files were not downloaded, so the two PI sources could not be compared.

**Recommended action.** (1) Ask the authors what `pulseoximeter.pi` is, its unit, and which device's PI it reports per row. (2) Download a few `_2hz.csv` files for the same encounters if PhysioNet access allows, to compare values. (3) Until answered, PI from this source cannot be assumed compatible with the project's PI thresholds (Low < 1.0). That is true even for devices 55, 60, 73 and 76, whose ranges only *look* percent-like.

---

## Summary
| Issue | Classification | Import unblocked? |
|---|---|---|
| 1. Repeated blood gas rows / SaO₂ column / aggregation | **NOT RESOLVED BY OFFICIAL SOURCE** | no |
| 2. encounter → patient authority | **NOT RESOLVED BY OFFICIAL SOURCE** | no |
| 3. Device / probe | rule **RESOLVED**; applicability and integer-only forms **NOT RESOLVED** | no |
| 4. PI definition and units | **NOT RESOLVED BY OFFICIAL SOURCE** | no |

**EXTERNAL DATA IMPORT: STILL BLOCKED.** What is missing is not code but answers only the dataset authors (or the credentialed data dictionary) can give.

---
---

# PHASE 17C UPDATE: cross-check against the files you downloaded

Labels used below: **CONFIRMED BY OFFICIAL FILE** (an official dataset file states it or directly encodes it) or **STILL UNRESOLVED**. Evidence that is only consistent with a hypothesis is reported as evidence and still labelled STILL UNRESOLVED. No analyst assumption was applied, nothing was imported, deduplicated or trained.

## What I could and could not inspect
- **I cannot open the credentialed PhysioNet Files tab.** It needs your login, and I have none. I worked only with files already on your machine.
- **New official file found and registered:** `patient.csv` (237 rows; columns `patient_id, site_id, assigned_sex, race, ethnicity`; one site, `ucsf-hypoxialab`). Copied to `raw/patient.csv`, read-only, SHA-256 added to `metadata/raw_sha256.txt`. All six raw files verify against their recorded hashes (`sha256sum -c`).
- **Not available locally:** any `*_2hz.csv`, README, data dictionary, `SHA256SUMS.txt`, `LICENSE`, `RECORDS` or other supplementary file. So A (repeated blood gas rows) and D (PI) cannot be cross-checked yet.

## B. Authoritative participant identity
| Finding | Evidence from official files | Status |
|---|---|---|
| `encounter.csv` participant IDs are valid participants | All 237 distinct `patient_id` values in `encounter.csv` exist in `patient.csv`, and every one of the 237 participants in `patient.csv` has at least one encounter. | **CONFIRMED BY OFFICIAL FILE** |
| Some alternate IDs in the conflicts are not valid participants | 20 (encounter, alternate id) conflict pairs over the 18 conflicting encounters. In 3 of the 20 pairs the alternate id is absent from `patient.csv` (all three from `bloodgas.csv`, one row each). `bloodgas.csv` and `spectrophotometer.csv` each contain 4 patient ids that are not in `patient.csv`. | **CONFIRMED BY OFFICIAL FILE** (those ids are not participants in the participant table) |
| Which table is authoritative when the other tables disagree | No file or document states it. Supporting evidence only: the official documentation says dates are offset by a random amount set per participant, preserving each participant's own chronology. Of the 20 pairs, 18 have the encounter dated within the year range of the *other* encounters of the participant named in `encounter.csv` (2 pairs cannot be assessed because that participant has no other encounter), and **0 of 20** fall within the year range of the alternate participant. | **STILL UNRESOLVED** (strong supporting evidence for `encounter.csv`, but not an official statement) |
| What to do with the conflicting rows | Not defined by any file. In the spectrophotometer file the conflicts are whole 21-reading sessions labelled with another participant's id. | **STILL UNRESOLVED** |

## C. Device / probe mapping
| Finding | Evidence | Status |
|---|---|---|
| `encounter.csv` and `pulseoximeter.csv` use the same float device strings | For the `N.0` and `N.0x` forms, 91.7% and 92.7% of (encounter, device string) pairs in `pulseoximeter.csv` appear exactly among that encounter's device assignments in `encounter.csv`. | **CONFIRMED BY OFFICIAL FILE** that the float string is a shared key (about 8% of pairs do not match, reason **STILL UNRESOLVED**) |
| Integer-only device strings (e.g. `55`, `60`, `73`, `76`) | Only 4.8% match an encounter assignment as an exact string; 79.4% match on the integer part alone. 44,652 of their 47,142 rows have an empty `probe_location`. Nothing says which probe an integer-only row used. | **STILL UNRESOLVED** |
| Meaning of `probe_location` (1–10) | Not defined. Evidence only: it equals the position of the encounter slot holding that device (left fingers 1–5 → 1–5, right fingers 1–5 → 6–10) in 88.2% of 1,685 triples. | **STILL UNRESOLVED** (consistent, not defined) |
| `devices.csv` content | 63 rows with only `device_number` and `device_type` (codes 1: 16, 2: 40, 3: 7); no make or model, although the paper says the table has them. Device numbers 50 and 74 are assigned in `encounter.csv` but absent from `devices.csv`. The meaning of the `device_type` codes is not defined. | **STILL UNRESOLVED** |
| Official decimal = probe rule | Quoted from the PhysioNet release notes in the previous section. | confirmed in the earlier section |

## A. Repeated blood gas rows: **STILL UNRESOLVED**
No new official file addresses this (no README, dictionary or `_2hz` file available). Nothing from `patient.csv` bears on it.

## D. Meaning and units of PI: **STILL UNRESOLVED**
No `_2hz.csv` file or dictionary is available, so I cannot compare `pulseoximeter.pi` with the waveform PI or find any unit definition.

## Updated status
| Issue | Status after 17C |
|---|---|
| A. Repeated blood gas rows / SaO₂ column / aggregation | STILL UNRESOLVED |
| B. Participant identity | **partly confirmed** (see table); table authority and handling of conflicting rows STILL UNRESOLVED |
| C. Device / probe | float key CONFIRMED; integer-only forms, `probe_location`, `devices.csv` STILL UNRESOLVED |
| D. PI definition and units | STILL UNRESOLVED |

**EXTERNAL DATA IMPORT: STILL BLOCKED.**

## What would resolve the rest (files you can fetch legitimately with your own login)
1. `SHA256SUMS.txt` (small): it lists every file in the release, so I can name the README, dictionary and `_2hz` files. In your own terminal: `wget --user pragatheeshh --ask-password -P D:\PigmentCal-UQ\external\openoximetry\raw https://physionet.org/files/openox-repo/1.1.1/SHA256SUMS.txt`
2. Any README, data dictionary or `LICENSE.txt` in the release.
3. The `_2hz.csv` files for 2 or 3 encounters that have device 60 or 73 rows (the waveform folders are named by the first character of the encounter id).
4. Written answers from the dataset authors on A and the conflicting rows.
