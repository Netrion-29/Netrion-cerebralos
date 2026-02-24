# Incentive Spirometry v1 — Contract

**Feature key:** `incentive_spirometry_v1`
**Source rule id:** `incentive_spirometry_v1`
**Module:** `cerebralos/features/incentive_spirometry_v1.py`
**PR branch:** `tier1/incentive-spirometry-v1`

## Purpose

Deterministic extraction of incentive spirometry (IS) documentation from
patient timeline items.  Covers plan/assessment mentions, IS orders, and
flowsheet numeric data (when present in timeline items).

## Output Schema

```jsonc
{
  "is_mentioned": "yes" | "no" | "DATA NOT AVAILABLE",
  "is_value_present": "yes" | "no",
  "mention_count": <int>,
  "mention_type_counts": {
    "explicit_is": <int>,
    "plan_is": <int>,
    "is_use": <int>,
    "is_order": <int>,
    "pulm_hygiene_only": <int>
  },
  "mentions": [
    {
      "type": "<mention_type>",
      "text": "<snippet>",
      "ts": "<ISO timestamp>",
      "raw_line_id": "<sha256[:16]>",
      "source_type": "<item type>"
    }
  ],
  "order_count": <int>,
  "orders": [
    {
      "type": "is_order",
      "frequency": "Q2H" | "Q1H" | ...,
      "context": "While awake",
      "designator": "RT16",
      "order_number": "<string>",
      "status": "<string or null>",
      "ts": "<ISO timestamp>",
      "raw_line_id": "<sha256[:16]>",
      "source_type": "<item type>"
    }
  ],
  "measurement_count": <int>,
  "measurements": [
    {
      "ts": "MM/DD HHMM",
      "goal_cc": <int>,
      "num_breaths": <int>,
      "avg_volume_cc": <int>,
      "largest_volume_cc": <int>,
      "patient_effort": "Good" | "Poor" | ...,
      "assessment_recommendation": "Continue present therapy",
      "cough_effort": "<string>",
      "cough_production": "<string>",
      "comments": "<string>",
      "raw_line_id": "<sha256[:16]>",
      "source_type": "<item type>"
    }
  ],
  "goals": [
    {"value": <int>, "unit": "cc", "source_ts": "<string>"}
  ],
  "source_rule_id": "incentive_spirometry_v1",
  "evidence": [ /* standard evidence entries with raw_line_id */ ],
  "notes": ["<string>"],
  "warnings": ["<string>"]
}
```

## Field Semantics

| Field | Values | Meaning |
|-------|--------|---------|
| `is_mentioned` | `"yes"` | At least one strong IS reference (explicit mention, plan IS, IS use, order, flowsheet) |
| `is_mentioned` | `"no"` | Only weak mentions (pulmonary hygiene without explicit IS) |
| `is_mentioned` | `"DATA NOT AVAILABLE"` | No IS-related text found in any timeline items |
| `is_value_present` | `"yes"` | Numeric volume measurements found in flowsheet data |
| `is_value_present` | `"no"` | No numeric volumes (mentions/orders only, or no data) |

## Mention Type Classification

| Type | Signal Strength | Pattern |
|------|----------------|---------|
| `explicit_is` | Strong | "incentive spirometry/spirometer" in text |
| `plan_is` | Strong | "Pulm Hygiene, incentive spirometry" in plan |
| `is_use` | Strong | "Frequent IS use", "Continue incentive spirometer" |
| `is_order` | Strong | "INCENTIVE SPIROMETER Q2H..." order format |
| `pulm_hygiene_only` | Weak | "Pulmonary hygiene encouraged" without explicit IS |

## False Positive Guards

- **PFT spirometry excluded:** "Spirometry suggests…", "FEV1", "FVC", "DLCO"
  patterns are NOT captured as IS references.
- **Pulmonary hygiene without IS:** Treated as weak mention (`is_mentioned="no"`).
- **Negation context:** PFT spirometry in 80-char window around an IS match
  causes the match to be skipped.

## Fail-Closed Behaviour

- Numeric values extracted ONLY from explicit flowsheet data rows.
- No inference of compliance from mentions alone.
- No LLM, no ML, no heuristic scoring.

## Source Types Scanned

`TRAUMA_HP`, `PHYSICIAN_NOTE`, `ED_NOTE`, `NURSING_NOTE`, `CONSULT_NOTE`,
`RADIOLOGY`, `CASE_MGMT`, `REMOVED`

## Evidence Traceability

Every evidence entry and measurement includes `raw_line_id` (sha256[:16]
of `"source_type|source_id|line_text"`).

## Validated Against

| Patient | is_mentioned | mention_count | order_count | measurement_count |
|---------|-------------|---------------|-------------|-------------------|
| Michael_Dougan | yes | 5 | 0 | 0 |
| Ronald_Bittner | yes | 9 | 0 | 0 |
| Charlotte_Howlett | yes | 4 | 0 | 0 |
| Anna_Dennis | DATA NOT AVAILABLE | 0 | 0 | 0 |
