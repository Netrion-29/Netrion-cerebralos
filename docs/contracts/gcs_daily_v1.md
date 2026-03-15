# gcs_daily — Schema Contract (v1)

**Module:** `cerebralos/features/gcs_daily.py`
**Feature key:** `gcs_daily` (under per-day feature output)
**Version:** v1
**Status:** Active

---

## Purpose

Per-day GCS (Glasgow Coma Scale) extraction from timeline items with
deterministic component parsing. Extracts arrival GCS, best/worst GCS, and
all readings per calendar day. When GCS components (Eye/Verbal/Motor) are
explicitly present in the source text, optional `eye`, `verbal`, `motor`
fields are included in the reading.

---

## Output Schema

**Example (data present):**

```json
{
  "arrival_gcs": { "value": 15, "intubated": false, "source": "TRAUMA_HP:Primary_Survey:Disability", "dt": "2025-12-18T14:30:00", "timestamp_quality": "full" },
  "arrival_gcs_value": 15,
  "arrival_gcs_ts": "2025-12-18T14:30:00",
  "arrival_gcs_source": "TRAUMA_HP:Primary_Survey:Disability",
  "arrival_gcs_missing_in_trauma_hp": false,
  "arrival_gcs_source_rule_id": "trauma_hp_primary_survey",
  "best_gcs":  { "value": 15, "intubated": false, "source": "ED_NOTE:structured_block", "dt": "2025-12-18T16:00:00", "timestamp_quality": "full", "eye": 4, "verbal": 5, "motor": 6 },
  "worst_gcs": { "value": 8,  "intubated": true,  "source": "ED_NOTE:compact", "dt": "2025-12-18T18:00:00", "timestamp_quality": "full" },
  "all_readings": [],
  "warnings": []
}
```

**Example (data not available):**

```json
{
  "arrival_gcs": "DATA NOT AVAILABLE",
  "arrival_gcs_value": null,
  "arrival_gcs_ts": null,
  "arrival_gcs_source": null,
  "arrival_gcs_missing_in_trauma_hp": false,
  "arrival_gcs_source_rule_id": null,
  "best_gcs": "DATA NOT AVAILABLE",
  "worst_gcs": "DATA NOT AVAILABLE",
  "all_readings": [],
  "warnings": []
}
```

---

## Reading Fields

| Field | Type | Presence | Description |
|---|---|---|---|
| `value` | int (3–15) | always | GCS total score |
| `intubated` | bool | always | True if T suffix present |
| `source` | string | always | Origin tag (see Source Tags below) |
| `dt` | string \| null | always | ISO datetime or date string |
| `timestamp_quality` | string | always | `"full"`, `"date_only"`, or `"missing"` |
| `eye` | int (1–4) | optional | Eye Opening sub-score, only when explicitly extracted |
| `verbal` | int (1–5) | optional | Best Verbal Response sub-score, only when explicitly extracted |
| `motor` | int (1–6) | optional | Best Motor Response sub-score, only when explicitly extracted |

### Component Rules

- Components are **only** emitted when explicitly present in source text.
- For simple total-only lines (`GCS: 15`), no components are inferred.
- For structured flowsheet blocks, component text is mapped to numbers deterministically.
- For structured blocks, `eye + verbal + motor` must equal `value` (fail-closed).

---

## Source Tags

| Tag | Description |
|---|---|
| `TRAUMA_HP:Primary_Survey:Disability` | Arrival GCS from primary survey |
| `<type>:simple` | Simple total (`GCS: 15`) |
| `<type>:component_paren` | Parenthesized form (`GCS (E:4 V:5 M:6) 15`) |
| `<type>:inline_components` | Inline form (`GCS E:4 V:5 M:6 15`) |
| `<type>:desc_components` | Descriptive form (`GCS: 4 (spontaneously),5 (oriented),6 (follows commands) = 15`) |
| `<type>:compact` | Compact form (`E4V5M6 GCS 15`) |
| `<type>:structured_block` | 4-line flowsheet block |

---

## Component Text→Number Mappings

### Eye Opening

| Text | Score |
|---|---|
| Spontaneous / Spontaneously | 4 |
| To speech / To voice | 3 |
| To pain / To pressure | 2 |
| None / No response | 1 |

### Best Verbal Response

| Text | Score |
|---|---|
| Oriented | 5 |
| Confused | 4 |
| Inappropriate words / Inappropriate | 3 |
| Incomprehensible sounds / Incomprehensible | 2 |
| None / No response | 1 |

### Best Motor Response

| Text | Score |
|---|---|
| Obeys commands / Obeys | 6 |
| Localizes pain / Localizes / Localizing | 5 |
| Withdrawal / Flexion withdrawal / Normal flexion | 4 |
| Abnormal flexion / Flexion | 3 |
| Extension | 2 |
| None / No response | 1 |

---

## Structured 4-Line Flowsheet Block Format

Recognized when four consecutive lines match:

```
Eye Opening: <text>
Best Verbal Response: <text>
Best Motor Response: <text>
Glasgow Coma Scale Score: <total>
```

Validation (all must pass or block is skipped):
1. All four lines present consecutively
2. All component texts map to known values
3. Sum of mapped values equals stated total
4. Total is in range 3–15

---

## Arrival GCS Priority

1. **TRAUMA_HP Primary Survey Disability line** (highest priority)
2. **ED_NOTE fallback** — if TRAUMA_HP exists but no Primary Survey GCS, earliest ED_NOTE GCS within 0–120 min of arrival_datetime
3. **DATA NOT AVAILABLE** — if neither source provides arrival GCS

---

## Fail-Closed Behavior

- Unknown component text → block skipped entirely
- Component sum ≠ stated total → block skipped entirely
- GCS value outside 3–15 → excluded
- Questionnaire ranges (`GCS 3-4?`) → excluded
- Narrative-only references (`GCS changes`) → excluded
- No clinical inference from text descriptions to GCS scores that aren't explicitly stated

---

## Design Invariants

- Deterministic, fail-closed
- No LLM, no ML, no clinical inference
- Existing arrival/best/worst logic preserved
- Simple total-only lines never produce component fields
