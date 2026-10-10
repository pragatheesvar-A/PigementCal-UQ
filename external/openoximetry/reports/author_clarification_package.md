# Author clarification package v2: OpenOximetry v1.1.1 (DRAFT, NOT SENT)

Supersedes v1 and `author_email_draft.md`. Nothing has been sent. Fill the bracketed fields before sending.

## C. Recipient / contact
- **Primary:** the OpenOximetry contact form, https://openoximetry.org/contact/ (fields: email, name, country, question). This is the only question channel listed on the official site.
- **Not for this purpose:** comms@opencriticalcare.org (the data-sharing terms list it only for reporting possible identification of individuals) and PHI-report@physionet.org (same purpose).
- **Optional second channel:** the PhysioNet project page for `openox-repo` may list a dataset contact (not verified; check it while logged in). No corresponding-author email was found in the official documents, so none is guessed.
- If the form has a character limit, send the short version (end of the email) and offer the rest by reply.

## B. Suggested subject line
`Clarification on OpenOximetry v1.1.1: blood-gas SaO2, PI and participant-ID fields`

## A. Final email

Dear OpenOximetry team,

Thank you for making the OpenOximetry repository available. I have credentialed access to v1.1.1 and am preparing a subgroup analysis of how pulse-oximeter reliability varies with objective skin colour (CIELAB-derived ITA) and perfusion (PI). I have read the data dictionary, the Scientific Data paper and the Hypoxia Lab protocols, but six points are not specified there, and I would like to avoid making assumptions. Short answers, or a pointer to a v1.1.1 README or dictionary, would be very helpful.

1. **Reference SaO₂.** Is `bloodgas.csv::so2` the intended arterial functional SaO₂ reference (not fractional O₂Hb)? The dictionary lists it as "Oxygen saturation, percent".

2. **Repeated blood-gas rows.** What is the authoritative rule for multiple `bloodgas.csv` rows with the same encounter_id and sample_number? In my copy, 5,568 groups have one row, 12,558 have two, 559 have three or more, and 526 rows are exact duplicates of another row. Protocol step 8 describes two ABL90 analyses per sample (a third if they differ by more than 0.5 points) and averaging the two that agree. Does that rule apply to these rows, and how should the single-row, two-row, 4+ row and exact-duplicate cases be handled?

3. **Participant IDs.** Which table is authoritative when `patient_id` conflicts across `encounter.csv`, `bloodgas.csv` and `spectrophotometer.csv`? I found 18 encounters with a conflict; I can send the encounter IDs if helpful.

4. **PI.** What does `pulseoximeter.csv::pi` represent: meaning, units, scaling, calculation, and is it comparable across devices? Is it the same quantity as the PI in the `_2hz` reference-oximeter files?

5. **Device and probe IDs.** How should decimal device/probe identifiers (e.g. `36.01`) be interpreted across the relevant tables (`pulseoximeter.device`, `encounter.*_device`), including integer-only strings (`55`), `N.0` strings (`55.0`) and rows with an empty `probe_location`?

6. **Repeated CIELAB.** Is there an official rule for repeated CIELAB measurements at the same body site and encounter, or should researchers use a documented analytical aggregation?

**Why this matters.** Our analysis compares reliability across pigmentation × perfusion subgroups. The reference value, the pairing of rows, the participant identity (for participant-level data splits) and the PI scale each directly determine the subgroup results, so we prefer to follow the maintainers' definitions rather than guess.

**Status on our side.** The raw files are unmodified (checksums recorded). The data have not been imported into any processed dataset, and no model has been trained or evaluated on them. We will not proceed until these points are clarified. I will cite the Scientific Data paper, will not redistribute the data, and will share the analysis code openly as the data license requires.

Thank you for your time.

Kind regards,
[Name]
[Affiliation]
[Email]

**Short version (if the form is length-limited):**
"I have credentialed access to OpenOximetry v1.1.1 and need six clarifications before analysing it: (1) is bloodgas.csv::so2 the arterial functional SaO2 reference; (2) the rule for multiple blood-gas rows per encounter/sample_number (1, 2, 4+ rows and exact duplicates); (3) which table is authoritative for participant IDs when they conflict (18 encounters); (4) the meaning, units, scaling and cross-device comparability of pulseoximeter.csv::pi; (5) interpretation of decimal device/probe IDs across tables; (6) any official rule for repeated CIELAB readings. Nothing has been imported or modelled. A README/dictionary pointer would suffice. Thank you."

## D. Attachment list
- **Attach nothing that contains OpenOximetry data** (the terms bar sharing the data or modified versions).
- Optional, text only: this email as a plain `.txt`/`.pdf`; the list of question wording.
- **On request only:** the 18 conflicting encounter IDs (`reports/patient_conflicts.csv`, IDs only, no data columns) and counts supporting question 2. Do not send the CSV files.
- Do not attach `official_docs` copies; link to the public pages instead (data dictionary and protocols are at openoximetry.org/data-repository and /study-protocols).

## E. Evidence to save after sending
Create `external/openoximetry/metadata/author_contact/` and store:
1. The exact text sent (save as `2026-MM-DD_sent_email.txt`) and its SHA-256.
2. A screenshot or saved copy of the form confirmation page with date and time (and any ticket or reference number).
3. Which channel was used and any fields you entered.
4. Each reply as received (full headers if email), with date; never edit it.
5. A line in a log (`contact_log.md`): date sent, date of reminder(s), date of each reply, who replied.
6. If the answer is verbal or in a call, a written summary you ask them to confirm.
7. After a reply: update `reports/decision_matrix_and_import_gate.md`. Mark an item RESOLVED only for what is confirmed in writing, and quote the sentence.

Do not edit the raw files or `processed/` while waiting.

## F. Follow-up reminder email template (send after about 3 weeks without a reply)

Subject: Reminder: clarification on OpenOximetry v1.1.1 blood-gas, PI and participant-ID fields

Dear OpenOximetry team,

I am following up on my message of [date] (reference: [ticket number if any]) about six points in OpenOximetry v1.1.1: the reference SaO₂ column (`so2`), the handling of multiple blood-gas rows per sample, the authoritative participant ID when tables disagree, the meaning and units of `pulseoximeter.csv::pi`, device/probe identifiers, and repeated CIELAB readings. I appreciate how busy you must be. Even a one-line answer to any single question, or a link to the relevant documentation, would help. In the meantime I have not imported or analysed the data.

If there is a better person or channel for data questions, please let me know and I will redirect.

Thank you,
[Name] · [Affiliation] · [Email]

A second reminder after another 2–3 weeks is reasonable; after that, follow Path B in `decision_matrix_and_import_gate.md`.

---
## Checks before sending
- [ ] Name, affiliation, email filled in; no participant-level data in the message.
- [ ] Counts in question 2 still match `reports/final_data_resolution_numbers.json` (18,685 groups: 5,568 / 12,558 / 559; 526 exact duplicate rows).
- [ ] You have read the wording and agree with the commitments (citation, no redistribution, open code).
