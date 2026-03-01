# New Patient Audit Matrix v1

| Field   | Value                                  |
|---------|----------------------------------------|
| Date    | 2026-02-24                             |
| Owner   | Sarah                                  |
| Status  | Living document — update after adds    |
| Branch  | tier0/new-patient-audit-matrix-doc     |

---

## 1. Purpose

This matrix classifies `data_raw/` patient files as validation
canaries for extractor development, Daily Notes v5 planning,
protocol-engine validation cohorts, and NTDS readiness reviews.

**Use this document to:**

- Identify which raw files are rich in specific clinical domains
  (SBIRT, procedures, neuro, respiratory, meds, ADT, etc.).
- Pick the best validation patients for a new extractor PR without
  trial-and-error file hunting.
- Track which new-format patients have been successfully ingested
  through the full pipeline (`./run_patient.sh`).
- Prioritize which extractor to build next based on data availability.

> **Seed rows may be ESTIMATED** — richness ratings are based on raw
> file keyword inspection until the patient has been run through the
> pipeline and output verified. Always check the `Row Status` and
> `Ingest OK?` columns before relying on a patient for validation.

---

## 2. New Patient Intake Check (Quick Reference)

When a new `.txt` file is added to `data_raw/`:

1. **Run the pipeline:**
   ```bash
   ./run_patient.sh <Patient_Name>
   ```
2. **Run the QA reporter:**
   ```bash
   PYTHONPATH=. python3 cerebralos/validation/report_features_qa.py --pat <Patient_Slug>
   ```
3. **Confirm non-empty outputs** — evidence, timeline, and features
   JSON files should exist and be non-trivially populated.
4. **Update this matrix** — flip `Ingest OK?` to `yes`, upgrade
   `Row Status` to `partially_verified` or `verified`, and refine
   richness ratings from `possible` to `strong` or `verified` as
   appropriate.

---

## 3. Column Definitions

| Column                        | Description |
|-------------------------------|-------------|
| **Patient**                   | Display name (matches raw file stem). |
| **Raw file name**             | Exact filename in `data_raw/`. |
| **Format family**             | Header style: `name-age-dob` (demographics-first, ADT table follows) or `legacy-keyed` (PATIENT_ID / ARRIVAL_TIME key–value header). Append `(verified)` if pipeline-confirmed. |
| **Row status**                | `estimated` = richness from keyword scan only; `partially_verified` = pipeline ran but not all domains checked; `verified` = pipeline ran and all domain ratings confirmed. |
| **Ingest OK?**                | `not_run` = `./run_patient.sh` has not been executed; `yes` = pipeline completed without fatal errors; `no` = pipeline errored. |
| **ADT-rich**                  | ADT Events table present with transfers. |
| **Note-sections-rich**        | Volume/variety of physician notes, progress notes, consults, PT/OT, case management. |
| **SBIRT-rich**                | SBIRT / AUDIT-C / DAST-10 / CAGE screening instruments present. |
| **Procedure/Anesthesia-rich** | Operative notes, anesthesia records, surgical procedure documentation. |
| **Neuro/TBI-rich**            | GCS tracking, neuro checks, TBI/ICH/subdural findings, craniotomy notes. |
| **Rib/Respiratory-rich**      | Rib fractures, pneumothorax, hemothorax, chest tubes, incentive spirometry flowsheets. |
| **Med/Allergy/Social-rich**   | PMH, allergies, social history, outpatient medications, anticoagulant context. |
| **Labs/MAR-rich**             | Lab panels, MAR administration records, ADS/OMNICELL dispensing data. |
| **NTDS-relevant event potential** | Estimated relevance for NTDS event extraction (activation category, disposition, complications). |
| **Best next use**             | Recommended extractor PRs or validation scenarios where this patient adds the most value. |
| **Notes / quirks**            | Format anomalies, known parser issues, filename space handling, etc. |

---

## 4. Rating Scale

### Richness ratings

| Rating       | Meaning |
|--------------|---------|
| `none`       | Domain content absent or negligible in the raw file. |
| `possible`   | Keyword scan suggests content exists but not manually confirmed. |
| `strong`     | Significant volume of domain content visible in raw file; not yet pipeline-validated. |
| `verified`   | Pipeline extraction confirmed correct output for this domain. |

### Row status

| Status               | Meaning |
|----------------------|---------|
| `estimated`          | Richness columns populated from raw-file keyword scan only. Pipeline has not been run. |
| `partially_verified` | Pipeline ran successfully; some domains confirmed, others still estimated. |
| `verified`           | Pipeline ran; all domain ratings manually confirmed against feature output. |

### Ingest OK?

| Value     | Meaning |
|-----------|---------|
| `not_run` | `./run_patient.sh` has not been executed for this patient. |
| `yes`     | Pipeline completed without fatal errors; outputs exist. |
| `no`      | Pipeline errored; see Notes column for details. |

---

## 5. Audit Matrix

<!-- NOTE: Scroll right to see all columns. -->
<!-- Keep entries concise: none / possible / strong / verified -->

| Patient | Raw file name | Format family | Row status | Ingest OK? | ADT | Notes-rich | SBIRT | Proc/Anesth | Neuro/TBI | Rib/Resp | Med/Allergy/Social | Labs/MAR | NTDS potential | Best next use | Notes / quirks |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Michael Dougan | `Michael_Dougan.txt` | name-age-dob (verified) | partially_verified | yes | strong | strong | none | strong | possible | possible | strong | strong | strong | ADT timeline validation (header); anticoag context (Eliquis+aspirin); long LOS (10d) | New-format with ADT in header; 527KB, 19.6K lines; Parkinson's + afib on anticoag |
| Charlotte Howlett | `Charlotte Howlett.txt` | name-age-dob (verified) | partially_verified | yes | strong | strong | none | strong | possible | none | strong | strong | possible | Elderly fall cohort (92yo); procedure-rich validation; PMH/social extraction | Space in filename; short stay; 266KB |
| Ronald Bittner | `Ronald Bittner.txt` | name-age-dob (verified) | partially_verified | yes | strong | strong | none | strong | possible | strong | strong | strong | strong | Respiratory/rib extractor (639 hits); long ICU stay (27d); DVT prophylaxis depth | Space in filename; 2.1MB, 74K lines — largest file; ADT rows inline (no "ADT Events" header); ICU course |
| Roscella Weatherly | `Roscella Weatherly.txt` | name-age-dob (verified) | partially_verified | yes | strong | strong | none | possible | possible | none | strong | strong | strong | ETOH/UDS validation; NTDS category validation; FAST exam | Space in filename; ADT in header; Cat 1 + Cat 2 refs; 263KB. Ingested 2026-03-01: arrival=2026-01-01T02:01, discharge=2026-01-02T18:03, 3 days, 35 features. |
| Mary King | `Mary King.txt` | name-age-dob (verified) | partially_verified | yes | strong | strong | none | possible | possible | strong | possible | strong | possible | Respiratory/rib extraction (41 hits); MAR-rich (366 hits); anticoag context | Space in filename; ADT in header; blank line 1; nickname "Lou"; 320KB. Ingested 2026-03-01: arrival=2026-01-01T17:41, discharge=2026-01-07T14:13, 7 days, 35 features. |
| Robert Altmeyer | `Robert Altmeyer.txt` | name-age-dob (verified) | partially_verified | yes | strong | strong | none | possible | possible | none | strong | possible | possible | FAST exam validation (9 hits); ADT with non-Trauma service (General Medical) | Space in filename; ADT in header; unique service = "General Medical"; 206KB. Ingested 2026-03-01: arrival=2026-01-01T17:50, discharge=2026-01-03T10:18, 3 days, 35 features. |
| Margaret Rudd | `Margaret Rudd.txt` | name-age-dob (verified) | partially_verified | yes | strong | strong | none | possible | possible | none | strong | strong | possible | Elderly fall cohort (88yo); labs-rich; neuro/GCS; DVT prophylaxis | Space in filename; ADT in header; nickname "Pat"; 283KB. Ingested 2026-03-01: arrival=2026-01-01T15:19, discharge=2026-01-04T16:42, 4 days, 35 features. |
| Betty Roll | `Betty Roll.txt` | name-age-dob (verified) | partially_verified | yes | strong | strong | strong | possible | strong | none | strong | strong | possible | SBIRT validation canary (4 hits + ETOH 20 hits); neuro/GCS depth; anticoag | Space in filename; ADT in header; 289KB. Ingested 2026-03-01: arrival=2026-01-01T10:05, discharge=2026-01-02T17:41, 2 days, 35 features. |
| Lee Woodard | `Lee Woodard.txt` | name-age-dob (verified) | partially_verified | yes | possible | strong | possible | possible | strong | possible | strong | none | strong | Neuro/TBI canary (28 hits); NTDS category depth (6 refs); SBIRT possible | Space in filename; ADT in header; shorter ADT (5 rows); 221KB; no MAR data. Ingested 2026-03-01: arrival=2026-01-01T00:08, discharge=2026-01-05T18:14, 6 days, 35 features. |
| Ronald Marshall | `Ronald_Marshall.txt` | name-age-dob (verified) | partially_verified | yes | strong | strong | none | strong | strong | strong | strong | strong | strong | Long-stay ICU validation (14d); neuro/TBI depth; respiratory/rib; procedure-rich | Underscore in filename; 48K lines; large file. Ingested 2026-03-01: arrival=2025-12-25T14:14, discharge=2026-01-07T16:55, 14 days, 35 features. |

---

## 6. Best Next Use — Summary

| Extractor / Validation Goal | Top candidates |
|------------------------------|----------------|
| ADT transfer timeline depth | Michael_Dougan (header, 15 events), Ronald Bittner (inline, 9 events, 27d ICU) |
| SBIRT screening coverage | Betty Roll (strong), Lee Woodard (possible) |
| ETOH / UDS panel | Roscella Weatherly, Betty Roll |
| Respiratory / rib / IS | Ronald Bittner (strong, 639 hits), Mary King (strong, 41 hits) |
| Neuro / TBI / GCS depth | Lee Woodard, Betty Roll, Ronald Bittner |
| Procedure / anesthesia | Michael_Dougan, Charlotte Howlett, Ronald Bittner |
| Anticoag context | Michael_Dougan (Eliquis+aspirin), Mary King, Betty Roll |
| PMH / social / allergies | Roscella Weatherly, Margaret Rudd, Betty Roll, Lee Woodard |
| Elderly fall cohort (age >80) | Charlotte Howlett (92), Margaret Rudd (88), Lee Woodard (84) |
| Long-stay / ICU validation | Ronald Bittner (27d ICU), Michael_Dougan (10d) |
| FAST exam | Robert Altmeyer (9), Betty Roll (9), Mary King (7) |
| NTDS event fidelity | Roscella Weatherly, Lee Woodard, Ronald Bittner |
| Non-Trauma service (General Medical) | Robert Altmeyer |

---

## 7. Known Format Quirks / Ingest Notes

### Filename spaces

All new-format patients except `Michael_Dougan` use spaces in their
filenames (e.g. `Charlotte Howlett.txt`). The pipeline slug function
converts spaces to underscores (`Charlotte_Howlett`), and
`./run_patient.sh` accepts either form. Feature output directories
use the underscore slug.

### ADT table placement

| Variant | Patients | Description |
|---------|----------|-------------|
| **Header with "ADT Events" label** | Michael_Dougan, Roscella Weatherly, Mary King, Robert Altmeyer, Margaret Rudd, Betty Roll, Lee Woodard | Standard: `ADT Events` header line → column header → tab-delimited rows. Parsed by `adt_transfer_timeline_v1`. |
| **Header with inline ADT rows (no label)** | Ronald Bittner | ADT data rows appear directly after DOB line with no "ADT Events" section header. Current `adt_transfer_timeline_v1` may not detect these — requires manual verification. |
| **ADT inside note body** | Charlotte Howlett | ADT table embedded deep in a physician note payload, not in file header. Detected via timeline-item fallback in `adt_transfer_timeline_v1`. |

### Format family: `name-age-dob`

All seed patients use the `name-age-dob` header format:
```
Full Name
NN year old male/female
M/D/YYYY
```
This is distinct from the older `legacy-keyed` format used by some
`data_raw/` files (e.g. `Gary_Linder.txt`):
```
PATIENT_ID: 136258
ARRIVAL_TIME: 2025-12-24 00:00:00
PATIENT_NAME: Gary L Linder
```

### Mary King leading blank line

`Mary King.txt` has a blank line 1 before the patient name on line 2.
The parser should handle this but verify after first ingest.

### Nicknames in header

Charlotte Howlett (`"Marlene"`), Mary King (`"Lou"`), Margaret Rudd
(`"Pat"`) include nicknames in quotes on the name line. Verify that
patient name extraction handles or ignores the nickname gracefully.

### Ronald Bittner — extreme file size

At 2.1 MB / 74K lines, this is the largest `data_raw/` file by far.
Represents a 27-day ICU course. Pipeline performance and timeout
handling should be tested with this patient. Very rich in respiratory
content (639 keyword hits), DVT prophylaxis data, and note volume.

---

## Appendix: Adding a New Row

When a new `.txt` is added to `data_raw/`:

1. Copy a row from the matrix above.
2. Fill in patient name, raw file name, and format family.
3. Set `Row status` = `estimated` and `Ingest OK?` = `not_run`.
4. Scan the raw file for keyword indicators and populate richness columns
   with `none` / `possible` / `strong`.
5. Run `./run_patient.sh` and update `Ingest OK?` → `yes` or `no`.
6. Run `report_features_qa.py` and upgrade richness ratings + row status.
7. Add any quirks to Section 7.
