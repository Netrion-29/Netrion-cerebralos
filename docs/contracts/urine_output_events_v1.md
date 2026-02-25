# Urine Output Events v1 — Contract

| Field       | Value                                     |
|-------------|-------------------------------------------|
| Feature key | `urine_output_events_v1`                  |
| Module      | `cerebralos/features/urine_output_events_v1.py` |
| Added       | 2026-02-24                                |
| Status      | Active                                    |

---

## Purpose

Extract explicit urine output events from raw Epic encounter exports
to support I/O monitoring in Daily Notes v5 and downstream NTDS/protocol
context.  Extraction-only — no rendering changes.

---

## Source Data

### Source 1 — Flowsheet "Urine Documentation"

Located in the Flowsheets section of the raw file.  Tab-delimited
table with columns:

| Column                      | Description                    |
|-----------------------------|--------------------------------|
| `Urine ml`                  | Volume in mL (e.g. "200 mL")  |
| `Urine Unmeasured Occurrence` | Count of unmeasured voiding  |
| `Urine Color`               | e.g. "Yellow/Straw", "Amber"  |
| `Urine Appearance`          | e.g. "Clear", "Cloudy"        |
| `Urine Odor`                | e.g. "No odor", "Malodorous"  |
| `Urine Source`              | e.g. "Voided"                 |

Each data row starts with `MM/DD HHMM` timestamp.

### Source 2 — LDA Columnar Assessment Rows

Within `[REMOVED]` or `[ACTIVE]` Urethral Catheter / External Urinary
Catheter device sections, `Assessments` blocks contain:

- `Row Name` header with timestamps as tab-separated columns
  (format: `MM/DD/YY HHMM`)
- Field rows: `Output (ml)`, `Urine Color`, `Urine Appearance`,
  `Urine Odor` with tab-separated values per timestamp column

**Important**: `Output (ml)` is only extracted from urethral catheter
and external urinary catheter contexts.  Feeding tube / chest tube /
drain `Output (ml)` values are explicitly excluded.

### Source 3 — LDA Format A Vertical Assessment Rows

Within LDA summary sections, per-device assessment rows with
`\tMM/DD\tHHMM\t` timestamps followed by key-value pairs on
subsequent lines.  Only extracted when parent device is a urethral or
external urinary catheter.

---

## Output Schema

```json
{
  "events": [
    {
      "ts": "MM/DD HHMM",
      "output_ml": 200,
      "source_type": "flowsheet",
      "source_subtype": "Voided",
      "urine_color": "Yellow/Straw",
      "urine_appearance": "Clear",
      "urine_odor": "No odor",
      "evidence": [
        {
          "role": "urine_output_entry",
          "snippet": "<first 120 chars of source line>",
          "raw_line_id": "<sha256>"
        }
      ]
    }
  ],
  "urine_output_event_count": 9,
  "total_urine_output_ml": 2200,
  "first_urine_output_ts": "01/01 0515",
  "last_urine_output_ts": "01/02 0830",
  "source_types_present": ["flowsheet", "lda_assessment"],
  "source_rule_id": "urine_output_events_raw_file",
  "warnings": [],
  "notes": [
    "source_breakdown: flowsheet=9, lda_assessment=12",
    "subtypes: Urethral Catheter, Voided"
  ]
}
```

### Field descriptions

| Field                       | Type            | Description |
|-----------------------------|-----------------|-------------|
| `events[].ts`               | string          | Timestamp in `MM/DD HHMM` format |
| `events[].output_ml`        | int \| null     | Explicit mL volume (null if row has characteristics only) |
| `events[].source_type`      | string          | `"flowsheet"` or `"lda_assessment"` |
| `events[].source_subtype`   | string          | Device type or "Voided" |
| `events[].urine_color`      | string \| null  | e.g. "Yellow/Straw", "Amber", "Cherry" |
| `events[].urine_appearance` | string \| null  | e.g. "Clear", "Cloudy", "Sediment" |
| `events[].urine_odor`       | string \| null  | e.g. "No odor", "Malodorous" |
| `events[].evidence[]`       | array           | Evidence with `raw_line_id` |
| `urine_output_event_count`  | int             | Count of events |
| `total_urine_output_ml`     | int             | Sum of explicit mL values only |
| `first_urine_output_ts`     | string \| null  | Earliest event timestamp |
| `last_urine_output_ts`      | string \| null  | Latest event timestamp |
| `source_types_present`      | string[]        | Distinct source types found |
| `source_rule_id`            | string          | `"urine_output_events_raw_file"` or `"no_urine_output_data"` |

---

## Fail-Closed Behaviour

| Condition                              | Result                                    |
|----------------------------------------|-------------------------------------------|
| No raw file path                       | `events=[]`, `source_rule_id="no_urine_output_data"` |
| Raw file exists, no urine sections     | Same as above                             |
| Sections found, 0 explicit events      | `urine_output_event_count=0`              |

---

## Category / Device Filtering

Only `Output (ml)` values from these device contexts are extracted:

- `Urethral Catheter`
- `External Urinary Catheter`

Explicitly excluded:
- Feeding tube `Output (ml)` (gastric drainage)
- Chest tube `Output (ml)`
- Wound / JP Drain `Output (ml)`

---

## Deduplication

Events are deduplicated by `(ts, output_ml, source_type)` tuple.
First occurrence is kept.  This prevents double-counting when the same
urine data appears in both flowsheet and LDA assessment blocks.

---

## Evidence Traceability

Every event carries an `evidence[]` array with at least one entry
containing:
- `role`: `"urine_output_entry"`
- `snippet`: First 120 characters of the source line
- `raw_line_id`: SHA-256 of the stripped source line

---

## Deferred Scope

- Intra-operative urine (anesthesia case metrics) — separate feature
- Urine output trending / normalization / alerting — renderer concern
- Generalized I/O extraction (stool, blood loss, drain output) —
  separate feature(s)
- Inference from device presence without explicit output — not allowed

---

## Validator

`KNOWN_FEATURE_KEYS` in
`cerebralos/validation/validate_patient_features_contract_v1.py`
includes `"urine_output_events_v1"`.

Evidence `raw_line_id` check: per-event evidence entries are validated
for presence of `raw_line_id`.

---

## QA Report

`cerebralos/validation/report_features_qa.py` includes:
- `URINE OUTPUT EVENTS v1 QA` section with event count, total mL,
  first/last timestamps, source types, source subtypes breakdown,
  event samples, evidence count, warnings, notes.
