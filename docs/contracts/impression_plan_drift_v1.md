# Impression/Plan Drift v1 Contract

## Feature key

`impression_plan_drift_v1` (under top-level `features` dict)

## Purpose

Deterministic day-to-day comparison of Impression/Plan content from
PHYSICIAN_NOTE and TRAUMA_HP timeline items.  Surfaces "plan churn" as
a QA signal without clinical inference.

## Source selection

For each calendar day, all PHYSICIAN_NOTE and TRAUMA_HP items are
scanned for:

- **IMPRESSION:** / **IMPRESSION.** sections (including
  "Narrative & Impression" headers)
- **Assessment/Plan** / **A/P** sections

Bullets are extracted, normalised, and compared across consecutive days.

## Normalisation pipeline

1. Strip leading bullet markers (`•`, `-`, `*`, `1.`, `2.`, …)
2. Lowercase
3. Replace date tokens (`MM/DD/YYYY`, `MM/DD/YY`, `YYYY-MM-DD`) → `<DATE>`
4. Replace standalone numeric tokens → `<NUM>`
5. Collapse whitespace
6. Strip trailing punctuation

## Diff algorithm

- Stable SHA-256 (truncated 16 hex) of each normalised item.
- Set-based comparison on hashes between consecutive days with
  impression/plan content.
- `added_items`: in current day but not previous.
- `removed_items`: in previous day but not current.
- `persisted_count`: intersection size.
- `drift_ratio = (len(added) + len(removed)) / max(len(prev_items), 1)`

## Output schema

```json
{
  "drift_detected": true | false | "DATA NOT AVAILABLE",
  "days_compared_count": "<int>",
  "days_with_impression_count": "<int>",
  "drift_events": [
    {
      "date": "YYYY-MM-DD",
      "prev_date": "YYYY-MM-DD",
      "source_note_types": ["PHYSICIAN_NOTE", ...],
      "added_items": ["<normalised text>", ...],
      "removed_items": ["<normalised text>", ...],
      "persisted_count": "<int>",
      "drift_ratio": "<float>",
      "evidence": [
        {
          "raw_line_id": "<sha256 hex 16>",
          "day": "YYYY-MM-DD",
          "source_type": "<item type>",
          "snippet": "<first 120 chars>"
        }
      ]
    }
  ],
  "evidence": [
    {
      "raw_line_id": "<sha256 hex 16>",
      "day": "YYYY-MM-DD",
      "source_type": "<item type>",
      "snippet": "<first 120 chars>"
    }
  ],
  "notes": ["..."],
  "warnings": ["..."]
}
```

## Fail-closed behaviour

| Condition | `drift_detected` | Notes |
|-----------|-------------------|-------|
| No Impression/Plan sections in any note | `"DATA NOT AVAILABLE"` | `days_compared_count = 0` |
| Only 1 day has Impression/Plan | `"DATA NOT AVAILABLE"` | Drift requires ≥ 2 days |
| ≥ 2 days with content, no changes | `false` | All items persisted |
| ≥ 2 days with content, items differ | `true` | `drift_events` populated |

## Evidence traceability

Every extracted bullet line produces a `raw_line_id` (SHA-256 of
`source_type|dt|line_text`, truncated 16 hex).  Evidence entries appear
in both the top-level `evidence` list and per-drift-event evidence.

## Warnings

- `high_drift_ratio`: emitted when `drift_ratio > 0.5` for any
  day-pair comparison.

## Validators

- `validate_patient_features_contract_v1.py`: checks
  `impression_plan_drift_v1` evidence entries have `raw_line_id`.
- `report_features_qa.py`: prints drift QA summary.
