# consultant_day_plans_by_day_v1 — Feature Contract

## Feature Key
`consultant_day_plans_by_day_v1`

## Purpose
Reorganises `consultant_plan_items_v1` items into a per-day, per-service
structure.  This is the consultant analogue of `trauma_daily_plan_by_day_v1`:
it shows what each consultant service recommended on each calendar day.

## Architecture
- **Feature-first consumer**: reads only from the assembled features dict.
- Consumes `consultant_events_v1` (to gate on `consultant_present`) and
  `consultant_plan_items_v1` (for the actual plan items).
- No raw-text extraction; no timeline re-scanning.
- Deterministic, fail-closed.  No LLM, no ML, no clinical inference.

## Source Features
| Feature                          | Usage                                      |
|----------------------------------|---------------------------------------------|
| `consultant_events_v1`           | Gate: `consultant_present == "yes"`          |
| `consultant_plan_items_v1`       | Source items (ts, service, item_text, etc.)  |

## Output Schema
```json
{
    "days": {
        "<ISO-date>": {
            "services": {
                "<service-name>": {
                    "items": [
                        {
                            "ts": "<ISO datetime>",
                            "author_name": "<name>",
                            "item_text": "<plan text>",
                            "item_type": "<type tag>",
                            "evidence": [...]
                        }
                    ],
                    "item_count": 2,
                    "authors": ["Smith, John"]
                }
            },
            "service_count": 1,
            "item_count": 2
        }
    },
    "total_days": 1,
    "total_items": 2,
    "total_services": 1,
    "services_seen": ["Orthopedics"],
    "source_rule_id": "consultant_day_plans_from_plan_items",
    "warnings": [],
    "notes": []
}
```

## source_rule_id Values
| Rule ID                              | Meaning                                    |
|--------------------------------------|--------------------------------------------|
| `consultant_day_plans_from_plan_items` | Items grouped successfully                 |
| `no_consultant_events`               | No consultant events in upstream features   |
| `no_plan_items`                      | Consultant events exist but 0 plan items    |

## Fail-Closed Behaviour
- No `consultant_events_v1` or `consultant_present != "yes"`
  → empty days, `source_rule_id = "no_consultant_events"`
- Consultant events present but `consultant_plan_items_v1.item_count == 0`
  → empty days, `source_rule_id = "no_plan_items"`
- Items grouped → `source_rule_id = "consultant_day_plans_from_plan_items"`

## v5 Rendering
Rendered in per-day blocks as "Consultant Day Plans:" section, grouped by
service, showing time, author, and each plan item with its type tag.
Appears after the "Trauma Daily Plan:" block and before "Clinical Narrative".

Deterministic cap: 25 items per service per day in rendered output.

## Relationship to Existing Features
| Feature                            | Scope        | This PR Touches? |
|------------------------------------|-------------|-------------------|
| `consultant_events_v1`             | Patient-level | No (read-only)   |
| `consultant_plan_items_v1`         | Patient-level | No (read-only)   |
| `consultant_plan_actionables_v1`   | Patient-level | No                |
| `consultant_day_plans_by_day_v1`   | Per-day       | **New (this PR)** |
| `trauma_daily_plan_by_day_v1`      | Per-day       | No                |

## Test Coverage
- `tests/test_consultant_day_plans_by_day.py` — 25 tests
  - Extractor: single/multi day, multi-service, sorting, authors, evidence, item_type
  - Fail-closed: missing features, consultant_present=no/DNA, empty items, bad ts
  - Determinism: idempotent output, sorted keys
  - v5 rendering: single/multi service render, empty states, item count display

## Files Modified
- `cerebralos/features/consultant_day_plans_by_day_v1.py` (NEW)
- `cerebralos/features/build_patient_features_v1.py` (wire-in)
- `cerebralos/reporting/render_trauma_daily_notes_v5.py` (v5 per-day block)
- `tests/test_consultant_day_plans_by_day.py` (NEW)
- `docs/contracts/consultant_day_plans_by_day_v1.md` (NEW — this file)
