# Slice A Plan: Sex/Gender + Discharge Disposition Extraction

**Date:** 2026-03-12
**Author:** Claude (VS Code agent)
**Scope:** ANALYSIS-ONLY — no code/rule/engine/test changes in this PR
**Goal:** Raw-evidence plan for deterministic Sex and Discharge Disposition extraction

---

## 1. Raw-Data Availability Summary

| Item | Value |
|------|-------|
| Clone with data | `~/NetrionSystems/netrion-cerebralos/data_raw/` |
| Total patient files | 39 `.txt` files |
| Files found for 12 target patients | **12/12** — all present |
| VS Code clone (`~/Documents/GitHub/…`) | `data_raw/` empty (`.gitkeep` only) — expected, data is `.gitignore`d |

### Target Patients — All Found

| # | File | Present |
|---|------|---------|
| 1 | `Ronald Bittner.txt` | YES |
| 2 | `Margaret Rudd.txt` | YES |
| 3 | `Betty Roll.txt` | YES |
| 4 | `Lee Woodard.txt` | YES |
| 5 | `Jamie Hunter.txt` | YES |
| 6 | `James Eaton.txt` | YES |
| 7 | `Linda Hufford.txt` | YES |
| 8 | `Robert Altmeyer.txt` | YES |
| 9 | `Johnny Stokes.txt` | YES |
| 10 | `Arnetta Henry.txt` | YES |
| 11 | `Roscella Weatherly.txt` | YES |
| 12 | `Mary King.txt` | YES |

---

## 2. Citation Tables

### 2A. Sex/Gender — Positive Citations (≥10)

Every raw file has at least one deterministic sex/gender marker.

| # | Patient_File:line | Exact Phrase Snippet |
|---|-------------------|----------------------|
| 1 | `Ronald Bittner.txt:2` | `72 year old male` |
| 2 | `Margaret Rudd.txt:2` | `88 year old female` |
| 3 | `Betty Roll.txt:2` | `71 year old female` |
| 4 | `Lee Woodard.txt:2` | `84 year old male` |
| 5 | `Jamie Hunter.txt:2` | `62 year old female` |
| 6 | `James Eaton.txt:2` | `69 year old male` |
| 7 | `Linda Hufford.txt:2` | `75 year old female` |
| 8 | `Robert Altmeyer.txt:2` | `49 year old male` |
| 9 | `Johnny Stokes.txt:2` | `73 year old male` |
| 10 | `Arnetta Henry.txt:3` | `55 year old female` |
| 11 | `Roscella Weatherly.txt:2` | `55 year old female` |
| 12 | `Mary King.txt:3` | `60 year old female` |
| 13 | `Anna_Dennis.txt:23` | `Anna Dennis is a 65 y.o. female` |
| 14 | `Anna_Dennis.txt:4169` | `Dennis, Anna       Legal Sex` (next line: `Female`) |
| 15 | `William Simmons.txt:43` | `William H Simmons is a 86 y.o. male with PMH of Afib ...` |
| 16 | `Timothy_Cowan.txt:16` | `60 yo male with unknown PMH` |
| 17 | `Timothy_Nachtwey.txt:20` | `56-year-old male with PMH hemorrhagic stroke` |
| 18 | `Ronald Bittner.txt:36` | `Ronald Bittner is a 72 yo male with a PMH` |
| 19 | `Margaret Rudd.txt:40` | `88 yo female s/p multiple falls` |
| 20 | `Lee Woodard.txt:238` | `84 yo elderly male who appears to be in no acute distress` |

### 2B. Sex/Gender — Negative / Near-Miss Citations (≥10)

Lines that contain "sex" or related keywords but do **NOT** represent patient sex.

| # | Patient_File:line | Exact Phrase Snippet | Why Negative |
|---|-------------------|----------------------|--------------|
| 1 | `Anna_Dennis.txt:2062` | `Substance and Sexual Activity` | Section header — social history |
| 2 | `Anna_Dennis.txt:2088` | `Sexually Abused: No` | Social history screening |
| 3 | `Anna_Dennis.txt:2784` | `Sexual activity:        Not on file` | Social history field |
| 4 | `Arnetta Henry.txt:138` | `Substance and Sexual Activity` | Section header |
| 5 | `Arnetta Henry.txt:141` | `Sexual activity:        Never` | Social history field |
| 6 | `Arnetta Henry.txt:168` | `Sexually Abused: No` | Abuse screening |
| 7 | `Betty Roll.txt:150` | `Substance and Sexual Activity` | Section header |
| 8 | `Betty Roll.txt:154` | `Sexual activity:        Defer` | Social history field |
| 9 | `Ronald Bittner.txt:108` | `Partners:       Female` | Partner gender, not patient sex |
| 10 | `Robert Altmeyer.txt:117` | `Partners:       Female` | Partner gender, not patient sex |
| 11 | `Johnny Stokes.txt:180` | `Comment: Partners: Female.` | Partner gender, not patient sex |
| 12 | `Mary King.txt:136` | `Partners:       Male` | Partner gender, not patient sex |
| 13 | `Roscella Weatherly.txt:198` | `Gender:       Female` | EKG header block — technically valid but unusual source |
| 14 | `Anna_Dennis.txt:1677` | `have you been raped or forced to have any kind of sexual activity` | DV screening question |

### 2C. Discharge Disposition — Positive Citations (≥10)

| # | Patient_File:line | Exact Phrase Snippet | Value |
|---|-------------------|----------------------|-------|
| 1 | `Anna_Dennis.txt:1729` | `Discharge Disposition: Skilled Nursing Facility` | SNF |
| 2 | `Anna_Dennis.txt:1731` | `Discharge Plan: SNF` | SNF |
| 3 | `Anna_Dennis.txt:315` | `Disposition: SNF` | SNF |
| 4 | `Arnetta Henry.txt:1256` | `9. Disposition: Discharged to home.` | Home |
| 5 | `Betty Roll.txt:735` | `9. Disposition: Discharged to home.` | Home |
| 6 | `James Eaton.txt:2706` | `Discharge Disposition: Home` | Home |
| 7 | `James Eaton.txt:2707` | `Discharge Plan: Home` | Home |
| 8 | `Jamie Hunter.txt:3999` | `Discharge Disposition: Swing Bed` | Swing Bed |
| 9 | `Linda Hufford.txt:3064` | `Discharge Disposition: Home Health` | Home Health |
| 10 | `Linda Hufford.txt:3065` | `Discharge Plan: Home Health Care` | Home Health Care |
| 11 | `Robert Altmeyer.txt:1530` | `9. Disposition: Discharged to home.` | Home |
| 12 | `Ronald Bittner.txt:3677` | `Discharge Disposition: Long Term Hospital` | LTAC |
| 13 | `Ronald Bittner.txt:3680` | `Discharge Plan: LTAC` | LTAC |
| 14 | `Margaret Rudd.txt:1082` | `Discharge Disposition: Skilled Nursing Facility` | SNF |
| 15 | `Margaret Rudd.txt:1083` | `Discharge Plan: SNF` | SNF |
| 16 | `Mary King.txt:442` | `Discharge Disposition: Home` | Home |
| 17 | `Mary King.txt:443` | `Discharge Plan: Home` | Home |
| 18 | `Roscella Weatherly.txt:1772` | `9. Disposition: Discharged to home.` | Home |
| 19 | `Lee Woodard.txt:5040` | `Discharge Disposition: Home` | Home |
| 20 | `Lee Woodard.txt:5041` | `Discharge Plan: Home` | Home |
| 21 | `William Simmons.txt:16538` | `Discharge Disposition: Rehab-Inpt` | Rehab |
| 22 | `William Simmons.txt:16539` | `Discharge Plan: Acute Rehab` | Acute Rehab |
| 23 | `Carlton_Van_Ness.txt:8689` | `Discharge Disposition: Rehab-Inpt` | Rehab |
| 24 | `Wilma_Yates.txt:5794` | `Discharge Disposition: Skilled Nursing Facility` | SNF |

### 2D. Discharge Disposition — Negative / Near-Miss Citations (≥10)

Lines containing "discharge" or "disposition" that do NOT represent the final discharge destination.

| # | Patient_File:line | Exact Phrase Snippet | Why Negative |
|---|-------------------|----------------------|--------------|
| 1 | `Anna_Dennis.txt:3310` | `EYES:  Denies photophobia or discharge` | Ophthalmologic "discharge" (eye drainage) |
| 2 | `Anna_Dennis.txt:3458` | `Eyes: PERRLA, EOMI, Conjunctiva normal, No discharge.` | Eye exam — clinical "discharge" |
| 3 | `Betty Roll.txt:2686` | `Eyes: PERRLA. EOMI. Conjunctiva normal. No discharge.` | Eye exam finding |
| 4 | `Barbara_Burgdorf.txt:1722` | `EYES:  No complaints of discharge` | Eye exam finding |
| 5 | `Barbara_Burgdorf.txt:1993` | `Eyes: PERRLA. EOMI. Conjunctiva normal. No discharge.` | Eye exam finding |
| 6 | `Arnetta Henry.txt:356` | `- SW/CM for disposition needs.` | Planning note, not final disposition |
| 7 | `Jamie Hunter.txt:199` | `- SW/CM for disposition needs.` | Planning note |
| 8 | `Johnny Stokes.txt:468` | `- SW/CM for disposition needs.` | Planning note |
| 9 | `Mary King.txt:334` | `- SW/CM for disposition needs.` | Planning note |
| 10 | `Lee Woodard.txt:371` | `Barriers to discharge: Unable to complete basic hygiene` | OT/PT assessment — not destination |
| 11 | `Jamie Hunter.txt:259` | `Barriers to discharge: Does not have assist needed` | OT/PT assessment |
| 12 | `Timothy_Nachtwey.txt:3552` | `Disposition pending patient's progress.` | Intermediate note, no final value |
| 13 | `Carlton_Van_Ness.txt:4918` | `Disposition:  Defer to primary team` | Progress note disposition — not final |
| 14 | `Anna_Dennis.txt:947` | `Disposition:  SNF likely tomorrow.` | Interim plan — "likely" qualifier |
| 15 | `Betty Roll.txt:1449` | `Disposition: Per trauma` | Service routing, not destination |

### 2E. Missing Structured Disposition Data — Coverage Gaps

5 patients have **no** `Discharge Disposition:` or `Discharge Plan:` lines:

| # | File | Notes |
|---|------|-------|
| 1 | `Charlotte Howlett.txt` | No structured disposition field found |
| 2 | `David_Gross.txt` | No structured disposition field found |
| 3 | `Johnny Stokes.txt` | Only therapy recommendation lines; no formal disposition |
| 4 | `Timothy_Cowan.txt` | No structured disposition field found |
| 5 | `Timothy_Nachtwey.txt` | Patient expired (brain death `line:615`); no discharge disposition |

For these 5 patients, the `9. Disposition:` format and `Discharge Disposition:` structured field are both absent. The fallback for Timothy_Nachtwey is "Expired/Deceased" (extractable from `Date of Death: 1/3/2026` at line 534). The others would need broader pattern search (e.g., "Discharged in stable condition" narratives, `d/c home`, etc.).

---

## 3. Existing Code Audit

### 3A. Sex/Gender — Already Partially Extracted

File: `cerebralos/ingest/parse_patient_txt.py` (line 748–753)

```python
# Line 2: age/sex  ("67 year old male")
if len(lines) >= 2:
    m = re.match(r"(\d+)\s+year\s+old\s+(\w+)", lines[1].strip(), re.IGNORECASE)
    if m:
        header["AGE"] = m.group(1)
        header["SEX"] = m.group(2).capitalize()
```

**Current state:** Only matches line 2 of the file. Works for ~24/39 patients whose line 2 is `"NN year old male/female"`. Fails for ~15 patients whose line 2 is `ARRIVAL_TIME:`, patient name, or ADT data — these patients have sex data in HPI or structured `Legal Sex` blocks but it is not extracted.

### 3B. Discharge Disposition — Already Partially Extracted

File: `cerebralos/features/patient_movement_v1.py`

The `patient_movement_v1` module already extracts `Discharge Disposition` from structured ADT-style blocks (field key `"Discharge Disposition"`). It populates `discharge_disposition_final` in the movement summary.

**Current state:** Works for patients with explicit `Discharge Disposition:` structured headers. Does NOT capture:
- `9. Disposition: Discharged to home.` (discharge summary numbered-list format)
- `Disposition: SNF` (progress note format)
- `Discharge Plan: SNF` (paired field)
- Expired/deceased patients (no discharge disposition at all)

---

## 4. Proposed Deterministic Regex/Pattern Candidates

### 4A. Sex/Gender Extraction

**Priority 1 — Line 2 header (already implemented)**
```
r"(\d+)\s+year\s+old\s+(\w+)"
```
Captures: `72 year old male`, `88 year old female`

**Priority 2 — HPI age-sex pattern**
```
r"(\d+)[\s-]*(?:y\.?o\.?|year[\s-]*old)\s+(male|female)"
```
Captures: `65 y.o. female`, `72 yo male`, `55-year-old female`, `60 yo male`

**Priority 3 — Structured "Legal Sex" header**
```
r"Legal\s+Sex\s*$"  →  next non-blank line = "Male" | "Female"
```
Captures: `Dennis, Anna       Legal Sex` / `Female`

**Priority 4 — MRN Description line**
```
r"MRN:\s*\d+\s+Description:\s*(\d+)\s+year\s+old\s+(male|female)"
```
Captures: `MRN: 2849731       Description: 65 year old female`

**Priority 5 — EKG/report Gender field**
```
r"Gender:\s*(Male|Female)"
```
Captures: `Gender:       Female` (EKG header)

### 4B. Discharge Disposition Extraction

**Priority 1 — Structured "Discharge Disposition:" field (already captured by patient_movement_v1)**
```
r"Discharge\s+Disposition:\s*(.+)"
```
Captures: `Discharge Disposition: Home`, `Discharge Disposition: Skilled Nursing Facility`, `Discharge Disposition: Rehab-Inpt`, `Discharge Disposition: Long Term Hospital`, `Discharge Disposition: Swing Bed`, `Discharge Disposition: Home Health`

**Priority 2 — "Discharge Plan:" paired field**
```
r"Discharge\s+Plan:\s*(.+)"
```
Captures: `Discharge Plan: SNF`, `Discharge Plan: Home`, `Discharge Plan: Acute Rehab`, `Discharge Plan: LTAC`, `Discharge Plan: Home Health Care`

**Priority 3 — Numbered-list "9. Disposition: Discharged to X."**
```
r"9\.\s*Disposition:\s*Discharged\s+to\s+(.+?)\.?\s*$"
```
Captures: `9. Disposition: Discharged to home.`, `9. Disposition: Discharged to SNF.`, `9. Disposition: Discharged to rehab.`

**Priority 4 — Standalone "Disposition:" with value**
```
r"^\s*Disposition:\s*(SNF|Home|Rehab|LTAC|Floor|home)\s*$"
```
Captures: `Disposition: SNF`, `Disposition: home` — but requires guardrails against interim values like "Defer to primary team" or "Per trauma".

**Priority 5 — Expired/Deceased**
```
r"Date\s+of\s+Death:\s*(\d{1,2}/\d{1,2}/\d{4})"
r"Time\s+of\s+brain\s+death:\s*"
r"comfort\s+measures?\s+care"
```
Captures terminal outcomes.

---

## 5. False-Positive Guardrails

### 5A. Sex/Gender

| Risk | Guardrail |
|------|-----------|
| `Partners: Female` captured as patient sex | Exclude lines matching `Partners:\s*(Male\|Female)` |
| `Sexual activity`, `Sexually Abused` | Require `\b(male\|female)\b` preceded by age indicator (`\d+\s*y`, `year old`) OR anchored at `Legal Sex` header |
| `Gender: Female` in EKG metadata | Accept only as fallback — prefer HPI/header sources |
| Pronouns (he/she/him/her) | Do NOT use pronouns for sex extraction — ambiguous referent |

### 5B. Discharge Disposition

| Risk | Guardrail |
|------|-----------|
| `Eyes: … No discharge` (ophthalmologic) | Require `Discharge` preceded by `Disposition` or followed by `Plan\|to\|Date` |
| `SW/CM for disposition needs` (planning) | Exclude lines containing `needs\|planning\|arrange\|pending` |
| `Disposition: Defer to primary team` | Exclude values matching `defer\|pending\|per trauma\|per\s+\w+\s+team\|to be determined\|Floor` |
| `Disposition: SNF likely tomorrow` | Exclude values containing `likely\|possible\|probably\|if\|when\|consider` |
| `Barriers to discharge` | Exclude lines containing `Barriers\|barrier` |
| `discharge.*summary\|discharge.*diagnosis` | Already handled by anchoring on `Disposition:` or `Discharge Plan:` fields only |

---

## 6. KEEP NOW / TIGHTEN NEXT / DEFER Triage

### KEEP NOW (implement in next PR)

| Item | Rationale |
|------|-----------|
| Sex: enhance `parse_patient_txt.py` header parsing to also try HPI line for `N y.o. male/female` | Adds coverage for ~15 patients with non-standard line 2; low false-positive risk |
| Disposition: add `Discharge Plan:` and `9. Disposition: Discharged to` as secondary sources in `patient_movement_v1.py` | Clear structured formats; covers 5+ additional patients per format |
| Disposition: normalize values to canonical set (`Home`, `SNF`, `Rehab`, `LTAC`, `Swing Bed`, `Home Health`, `Expired`) | Enables downstream analytics; low ambiguity |
| Sex: expose `header["SEX"]` in `patient_features_v1.json` under `features.demographics.sex` | Currently extracted but not surfaced in the feature contract |

### TIGHTEN NEXT (follow-on PR after validation)

| Item | Rationale |
|------|-----------|
| Sex: add `Legal Sex` structured header extraction | Multi-line pattern; needs careful anchoring to avoid false matches |
| Sex: add `MRN: … Description: N year old male/female` fallback | Reliable but redundant with HPI pattern for most patients |
| Disposition: extract from standalone `Disposition:` in progress notes | High false-positive risk without guardrails ("Defer", "Per trauma", interim values) |
| Disposition: detect Expired/Deceased from death summary | Edge case (1/39 patients); needs separate clinical validation path |
| Disposition: cross-validate `Discharge Disposition:` vs `Discharge Plan:` for inconsistencies | Some patients (e.g., George_Kraus) have conflicting disposition records across encounters |

### DEFER (not in scope for Slice A)

| Item | Rationale |
|------|-----------|
| Gender identity vs. legal sex distinction | No "Gender Identity" field observed distinct from "Legal Sex"; not clinically required for TQIP |
| Pronoun-based sex inference | Unreliable; referent ambiguity |
| Discharge disposition intent vs. actual (therapy "recommendation" vs. final disposition) | Requires temporal reasoning beyond regex |
| Multi-encounter disposition reconciliation | Would need encounter-level tracking, not patient-level |
| Automated classification of Charlotte_Howlett, David_Gross, Timothy_Cowan missing disposition | Requires manual chart review or narrative NLP |

---

## 7. Exact Next Implementation PR Scope

### Files to Edit

| File | Change |
|------|--------|
| `cerebralos/ingest/parse_patient_txt.py` | Add HPI-based sex fallback: scan first 60 lines for `(\d+)[\s-]*(?:y\.?o\.?\|year[\s-]*old)\s+(male\|female)` if `header["SEX"]` is not set from line 2 |
| `cerebralos/features/patient_movement_v1.py` | Add `Discharge Plan:` and `9. Disposition: Discharged to` as additional source patterns for `discharge_disposition` |
| `cerebralos/features/patient_movement_v1.py` | Add disposition value normalization map (e.g., `"Skilled Nursing Facility"` → `"SNF"`, `"Rehab-Inpt"` → `"Rehab"`, `"Long Term Hospital"` → `"LTAC"`) |
| `cerebralos/features/build_patient_features_v1.py` | Surface `demographics.sex` in `patient_features_v1.json` under `features` dict |

### Tests to Add

| Test File | Coverage |
|-----------|----------|
| `tests/test_sex_extraction.py` | Parametrized across ≥12 patients; verify Male/Female for each; negative cases (Partners, Sexual Activity) must NOT pollute |
| `tests/test_discharge_disposition_extraction.py` | Parametrized: 10+ patients with known disposition; verify normalized values; negative cases (eye discharge, planning notes) must NOT match |
| Extend `tests/test_cohort_invariant.py` | Assert every patient in cohort has non-null sex; assert ≥34/39 patients have non-null disposition (5 known gaps) |

### Validation Checklist

- [ ] `pytest tests/test_sex_extraction.py -v` passes
- [ ] `pytest tests/test_discharge_disposition_extraction.py -v` passes
- [ ] `pytest tests/ -x` (full suite) passes
- [ ] `./scripts/gate_pr.sh` passes (baseline drift check)
- [ ] `patient_features_v1.json` contract validator passes
- [ ] Manual spot-check: 4 gate patients (Anna_Dennis, William_Simmons, Timothy_Cowan, Timothy_Nachtwey) have correct sex and disposition values
- [ ] No changes to protected engines (`ntds_logic/engine.py`, `protocol_engine/engine.py`)
- [ ] No changes to v3/v4 renderer outputs

---

## 8. Summary Statistics

| Metric | Sex/Gender | Discharge Disposition |
|--------|-----------|----------------------|
| Patients with data (any format) | **39/39** (100%) | **34/39** (87%) |
| Patients with structured header (line 2) | 24/39 (62%) | N/A |
| Patients with HPI-embedded | 39/39 (100%) | N/A |
| Patients with `Discharge Disposition:` field | N/A | 27/39 (69%) |
| Patients with `9. Disposition:` field | N/A | 18/39 (46%) |
| Patients with NO disposition data | N/A | 5/39 (13%) |
| Positive citation lines collected | 20 | 24 |
| Negative/near-miss citation lines collected | 14 | 15 |
| Proposed regex patterns | 5 | 5 |

---

*End of Slice A plan.*
