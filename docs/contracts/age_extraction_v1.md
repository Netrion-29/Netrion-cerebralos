# Age Extraction v1 — Contract

| Field   | Value                  |
|---------|------------------------|
| Status  | DRAFT — implemented    |
| Phase   | Extractor coverage (protocol-enablement prerequisite) |
| Owner   | CerebralOS Phase 1.1  |
| Module  | `cerebralos/features/age_extraction_v1.py` |
| Output  | `features.age_extraction_v1` in `patient_features_v1.json` |
| Date    | 2026-02-22             |

---

## 1. Purpose

Deterministic patient age extraction (integer years) from existing
parsed patient data in the timeline layer.  This is a protocol-enablement
prerequisite — geriatric (≥65) and pediatric (≤17) protocol gates
require a structured age field in the features pipeline.

Design principles:

- Deterministic, fail-closed.
- No inference. No LLM. No ML.
- Consumes only timeline data (`patient_days_v1.json`).
- Evidence-traced where feasible; metadata-source exception documented.

---

## 2. Extraction Hierarchy (Locked v1)

### 2.1 Primary: DOB from Note Text

| Parameter     | Value                                        |
|---------------|----------------------------------------------|
| Pattern       | `DOB:\s*M/D/YYYY` or `Date of Birth:\s*M/D/YYYY` |
| Source        | Timeline item payload text (note headers)    |
| Computation   | `age_years = floor((arrival_date − DOB) / year)` |
| Rule ID       | `dob_note_header`                            |

Item type search priority: TRAUMA_HP → CONSULT_NOTE → ED_NOTE →
PHYSICIAN_NOTE → NURSING_NOTE → DISCHARGE.

### 2.2 Fallback: HPI Narrative Age

| Parameter     | Value                                        |
|---------------|----------------------------------------------|
| Pattern       | `\b(\d{1,3})\s*[-\s]?(?:y\.?o\.?\|year[-\s]?old\|yr)\b` |
| Source        | Arrival-day items: TRAUMA_HP → CONSULT_NOTE → ED_NOTE |
| Rule ID       | `hpi_narrative_age`                          |

Note: narrative age is approximate (no birth date).  A note is appended
when this fallback is used.

### 2.3 Decision Table

| DOB Found | HPI Age Found | Result              | Rule ID              |
|-----------|---------------|----------------------|----------------------|
| yes       | —             | age from DOB         | `dob_note_header`    |
| no        | yes           | age from HPI         | `hpi_narrative_age`  |
| no        | no            | DATA NOT AVAILABLE   | null                 |

---

## 3. Fail-Closed Behavior

- If `arrival_datetime` is missing → `DATA NOT AVAILABLE`
- If no timeline items available → `DATA NOT AVAILABLE`
- If DOB computes to age outside [0, 120] → skip DOB, try fallback
- If HPI age is outside (0, 120] → skip that match
- If neither source yields valid age → `DATA NOT AVAILABLE`

---

## 4. Output Schema

| Key                | Type                     | Notes                                  |
|--------------------|--------------------------|----------------------------------------|
| `age_years`        | int \| null              | Integer age at arrival                 |
| `age_available`    | `"yes"` \| `"DATA NOT AVAILABLE"` | Primary output flag        |
| `age_source_rule_id` | string \| null          | `"dob_note_header"` or `"hpi_narrative_age"` |
| `age_source_text`  | string \| null           | Matched text (e.g., `"DOB: 3/20/1960"`) |
| `dob_iso`          | string (ISO date) \| null | `"YYYY-MM-DD"` when DOB available      |
| `evidence`         | list[object]             | See §4.1                               |
| `notes`            | list[string]             | Contextual notes                       |
| `warnings`         | list[string]             | Validation warnings                    |

### 4.1 evidence[]

Each entry:

| Key           | Type   | Required |
|---------------|--------|----------|
| `raw_line_id` | string | Yes — SHA-256[:16] from item_type + ts + text line |
| `source`      | string | Yes — item type (e.g., `"TRAUMA_HP"`)  |
| `ts`          | string \| null | Yes                              |
| `snippet`     | string | Yes                                    |
| `role`        | string | Yes — `"primary"`                      |

### 4.2 Metadata-Source Exception

DOB originates from note header metadata lines (e.g., `DOB: 3/20/1960`),
not from clinical evidence rows.  These lines are formulaic chart headers
repeated across physician notes and do not have native `raw_line_id`
provenance from the ingestion layer.  The `raw_line_id` is therefore
**synthesised** via SHA-256[:16] of the evidence coordinates
(`item_type|ts|matched_line`).  This is a known metadata-source pattern
and is documented here per the contract requirement.

---

## 5. Integration

### 5.1 Builder

Called in `build_patient_features_v1.py` after neuro trigger.
Receives `days_data` (full timeline JSON).

### 5.2 Validator

`age_extraction_v1` is in `KNOWN_FEATURE_KEYS` in
`validate_patient_features_contract_v1.py`.
Evidence `raw_line_id` is checked by a dedicated evidence walker section.

### 5.3 QA Report

Section in `report_features_qa.py` displays:
- `age_available`, `age_years`, `age_source_rule_id`
- `age_source_text`, `dob_iso`
- Evidence list
- Warnings and notes

---

## 6. Versioning and Change Control

- This is **v1** of the age extraction contract.
- Any changes to extraction logic, hierarchy, or output schema require:
  1. A version bump to this contract document.
  2. Corresponding code changes in the implementation module.
  3. Updates to validators and QA reporter.
  4. All in the same PR (AGENTS.md §4).
- The contract file path is:
  `docs/contracts/age_extraction_v1.md`

---

End of contract.
