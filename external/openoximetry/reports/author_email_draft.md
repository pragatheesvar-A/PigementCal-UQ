> **SUPERSEDED** by `author_clarification_package.md` (the version to send).

# DRAFT: not sent

To: OpenOximetry data team via the contact form at https://openoximetry.org/contact/
(the only email address in the official documents, comms@opencriticalcare.org, is listed in the data-sharing terms for reporting identification issues, so the contact form is the better route; I did not find a corresponding author's email in the documents I could read)

Subject: Clarification on OpenOximetry v1.1.1 blood-gas, PI and participant linkage fields

Dear OpenOximetry team,

I have credentialed access to OpenOximetry v1.1.1 and am preparing a paired SpO2/SaO2 analysis. The data dictionary and the laboratory protocol answer most of my questions, but I could not find answers to the following six, and I want to avoid guessing.

1. In bloodgas.csv, multiple rows sometimes share the same encounter_id + sample_number (for example, 12,558 groups have two rows and several hundred have three or more; some have one). The dictionary describes `sample` as the index of an ABG draw in an encounter. Does each row represent one analysis of the same blood sample on a different ABL90 analyser, as step 8 of the laboratory protocol suggests? If so, how should one reference SaO2 value be selected for pairing with pulseoximeter.csv: is the sample's SaO2 the average of the two agreeing results, and how should single-row and 4-or-more-row groups be treated?

2. Is bloodgas.csv::so2 the intended arterial functional SaO2 reference variable for comparison with pulseoximeter.csv::saturation (as opposed to fractional O2Hb)?

3. When patient_id conflicts occur between bloodgas.csv or spectrophotometer.csv and encounter.csv (I found 18 encounters), which patient_id should be treated as authoritative? I can send the list of encounter_ids if useful.

4. What exactly does pulseoximeter.csv::pi represent? What are its units and calculation method? The dictionary says "the perfusion measurement as reported by the device, typically 'perfusion index'".

5. Is pulseoximeter.csv::pi comparable across device/probe types, or should PI analysis be restricted to particular devices? Is it the same quantity as the pulsatility index in the *_2hz.csv reference-oximeter files?

6. For multiple spectrophotometer measurements at the same body site and encounter (typically three; sometimes six or nine), is there an official rule for selecting or aggregating the measurements?

If a data dictionary or release README for v1.1.1 that addresses these points exists, a pointer to it would be enough.

Thank you for making this dataset available. I will cite the Scientific Data paper (Fong et al., 2025) and will not redistribute the data.

Kind regards,
[Your name]
[Affiliation]
[Contact email]
