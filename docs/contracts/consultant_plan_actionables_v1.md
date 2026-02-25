# consultant_plan_actionables_v1 — Contract

## Feature key
`consultant_plan_actionables_v1`

## Purpose
Transform consultant plan items from `consultant_plan_items_v1` into
structured, protocol-friendly actionables with explicit category
labels.  This is the feature that Daily Notes v5 and protocol
plan-of-care checks consume for consultant recommendations.

## Source data
- `consultant_plan_items_v1` (the only input — feature-first design)

## Detection strategy

### Category mapping (deterministic)
Each `consultant_plan_items_v1` item is mapped to an actionable
category using two-phase deterministic logic:

**Phase 1: Direct `item_type` mapping**

| item_type (from plan items) | actionable category |
|---|---|
| `imaging` | `imaging` |
| `procedure` | `procedure` |
| `medication` | `medication` |
| `follow-up` | `follow_up` |
| `activity` | `activity` |
| `discharge` | `discharge` |

**Phase 2: Keyword promotion for `recommendation` items**

Items typed as `recommendation` are scanned for keywords to promote
into a specific category:

| Actionable category | Trigger keywords |
|---|---|
| `brace_immobilization` | brace, bracing, sling, collar, splint, Jewett, immobiliz |
| `monitoring_labs` | labs ordered, telemetry monitoring, serial troponins, TSH, free T4, cortisol, proBNP, procalcitonin |
| `follow_up` | follow-up, f/u, return to clinic, outpatient follow, neurosurgical follow |
| `medication` | start, continue, resume, discontinue, hold, titrate, specific drug names |
| `imaging` | CT, MRI, X-ray, XR, CTA, ultrasound, ECHO, TTE |
| `procedure` | surgery, operative, ORIF, debridement, repair |
| `activity` | weight-bearing, NWB, WBAT, mobilize, ambulate, PT/OT |
| `discharge` | discharge, d/c, disposition, SNF, rehab facility |
| `recommendation` | Fallback when no keyword matches |

Keywords are matched case-insensitively.  Order matters: first match
wins.  `brace_immobilization` is checked before `activity` to ensure
explicit brace/sling/collar orders are categorized specifically.

### Normalization
- `action_text` is trimmed, whitespace-collapsed, capped at 200 chars.
- Trailing ellipsis added when truncated.

### Deduplication
Identical (service, category, action_text_lowercase) tuples are
deduplicated.  Duplicates are logged as warnings.

### Evidence traceability
Each actionable carries evidence with:
- `role`: `"consultant_plan_actionable"`
- `raw_line_id`: passed through from the source `consultant_plan_items_v1`
  item evidence

## Output schema
```json
{
  "actionables": [
    {
      "service": "Orthopedics",
      "ts": "2026-01-01T09:30:00",
      "author_name": "Smith, John",
      "category": "activity",
      "action_text": "May use R arm for writing/feeding, otherwise NWB on RUE",
      "source_item_type": "activity",
      "evidence": [
        {
          "role": "consultant_plan_actionable",
          "snippet": "[Orthopedics] activity:: May use R arm...",
          "raw_line_id": "<sha256>"
        }
      ]
    }
  ],
  "actionable_count": 5,
  "services_with_actionables": ["Internal Medicine", "Orthopedics"],
  "category_counts": {
    "activity": 2,
    "imaging": 1,
    "medication": 2
  },
  "source_rule_id": "consultant_actionables_from_plan_items"
                   | "no_plan_items"
                   | "no_actionables_extracted",
  "warnings": [],
  "notes": []
}
```

## Fail-closed rules
| Condition | Output |
|---|---|
| No `consultant_plan_items_v1` or item_count == 0 | actionables=[], source_rule_id=`"no_plan_items"` |
| Plan items present but no actionables extracted | actionables=[], source_rule_id=`"no_actionables_extracted"` |
| Actionables extracted | source_rule_id=`"consultant_actionables_from_plan_items"` |

## Relationship to other features
- `consultant_events_v1` → *who* consulted and *when*
- `consultant_plan_items_v1` → *what* consultants wrote in plan sections (raw items)
- `consultant_plan_actionables_v1` → *structured actionables* derived from plan items (this feature)
- This feature is a pure consumer of `consultant_plan_items_v1`.  It does
  not re-parse raw note text or access the timeline.

## Validation patients
| Patient | Expected |
|---|---|
| Roscella_Weatherly | Actionables from Internal Medicine, Otolaryngology, Physical Therapy |
| Lee_Woodard | Actionables from Orthopedics, Wound/Ostomy, OT, PT |
| Margaret_Rudd | Actionables from Internal Medicine, Neurosurgery, Orthopedics |
| Betty_Roll | Actionables from Neurosurgery |
| Anna_Dennis | DNA (no consultant plan items, older format) |

## Intentional exclusions
- Does not filter out "recommendation" items — all plan items from
  `consultant_plan_items_v1` become actionables (noise filtering is
  the responsibility of the upstream extractor).
- Does not invent clinical meaning beyond explicit text.
- Does not access raw note text or timeline data.
