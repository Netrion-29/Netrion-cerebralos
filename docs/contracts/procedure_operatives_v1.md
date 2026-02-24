# Procedure / Operative Events v1 — Contract

## Purpose

Deterministic extraction of structured procedure, operative, and
anesthesia events from the patient timeline.  Captures explicit
procedural records — not inferred procedures from narrative text.

Produces a structured event timeline for Daily Notes v5 procedural
narrative and event chronology.

## Input

| Parameter     | Source                                             |
|---------------|----------------------------------------------------|
| pat_features  | `{"days": feature_days}` (standard pattern)        |
| days_data     | full `patient_days_v1.json`                        |

## Recognised Item Kinds

The extractor scans all timeline items and selects those with an
explicit procedural `type` (kind):

| Kind                       | Category              |
|----------------------------|-----------------------|
| `PROCEDURE`                | `operative`           |
| `OP_NOTE`                  | `operative`           |
| `PRE_PROCEDURE`            | `pre-op`              |
| `ANESTHESIA_PREPROCEDURE`  | `anesthesia`          |
| `ANESTHESIA_PROCEDURE`     | `anesthesia`          |
| `ANESTHESIA_POSTPROCEDURE` | `anesthesia`          |
| `ANESTHESIA_FOLLOWUP`      | `anesthesia`          |
| `ANESTHESIA_CONSULT`       | `anesthesia`          |
| `SIGNIFICANT_EVENT`        | `significant_event`   |

Items not in this map are ignored (fail-closed).

## Output Shape

```jsonc
{
  "events": [
    {
      "ts": "2025-12-31T13:56:00",
      "source_kind": "OP_NOTE",
      "category": "operative",
      "label": "ORTHOPEDIC OPERATIVE REPORT",
      "status": "completed",          // optional, explicit only
      "preop_dx": "Left 5th metatarsal fracture",  // optional
      "milestones": [                  // optional, anesthesia records only
        {"milestone": "anesthesia_start", "time_raw": "1136"}
      ],
      "anesthesia_type": "General",    // optional
      "asa_status": "3",               // optional
      "raw_line_id": "item:2025-12-31:22",
      "evidence": [
        {
          "role": "procedure_event",
          "snippet": "Signed   |||ORTHOPEDIC OPERATIVE REPORT...",
          "raw_line_id": "item:2025-12-31:22"
        }
      ]
    }
  ],
  "procedure_event_count": 12,       // items with kind=PROCEDURE
  "operative_event_count": 2,        // items with kind=OP_NOTE
  "anesthesia_event_count": 5,       // items with anesthesia category
  "categories_present": ["anesthesia", "operative", "pre-op"],
  "evidence": [
    {
      "role": "procedure_event",
      "snippet": "2025-12-31T13:56:00 OP_NOTE ORTHOPEDIC...",
      "raw_line_id": "item:2025-12-31:22"
    }
  ],
  "warnings": [],
  "notes": [],
  "source_rule_id": "procedure_operatives_v1"
}
```

When no qualifying items exist:
- `events` is `[]`
- All counts are `0`
- `categories_present` is `[]`
- `notes` contains `"no_procedure_operative_events_found"`

## Label Extraction

Labels are extracted from explicit structured headings only:

1. `Procedure:` / `Operation:` / `Block type:` colon-delimited lines
2. Heading text after `Signed` / `Attested` / `Addendum` markers
3. `null` if no explicit label can be determined (fail-closed)

No procedure labels are inferred from narrative, radiology, or
impression text.

## Anesthesia Milestones

For anesthesia-category items, explicit timestamped milestones are
captured when present:

| Milestone              | Pattern                           |
|------------------------|-----------------------------------|
| `anesthesia_start`     | `Anesthesia Start: <time>`        |
| `anesthesia_stop`      | `Anesthesia Stop/End: <time>`     |
| `induction`            | `Induction: <time>`               |
| `intubation`           | `Intubation: <time>`              |
| `extubation`           | `Extubation: <time>`              |
| `incision`             | `Incision: <time>`                |
| `tourniquet_inflated`  | `Tourniquet Inflated: <time>`     |
| `tourniquet_deflated`  | `Tourniquet Deflated: <time>`     |
| `emergence`            | `Emergence: <time>`               |

These milestones are a preparedness feature: the patterns will fire
when structured anesthesia records with these fields appear in
future data.  Current patient data primarily uses narrative-style
anesthesia documentation without timestamp-labelled milestones.

## Determinism Guarantees

- Item iteration is deterministic (sorted by day_iso, then item index).
- Only explicit item kinds and text patterns are consumed.
- No cross-item inference, no narrative text mining for procedures.
- Every event carries `raw_line_id` for audit traceability.
- Empty / missing data produces empty output, never an error.

## Green-Card Overlap Note

The green card layer (`extract_green_card_v1.py`) also extracts
procedure-related data, but in a fundamentally different shape:

| Aspect           | Green Card                            | This Feature                       |
|------------------|---------------------------------------|------------------------------------|
| Purpose          | H&P/discharge procedure list (PMH)    | Event-level chronology             |
| Data source      | H&P/progress/discharge note text      | Timeline items by kind             |
| Output shape     | `procedures` field = list of labels   | `events[]` with ts/category/label  |
| Spine data       | `spine_clearance` (order questions)    | Not extracted                      |
| Tourniquet       | Prehospital/ED tourniquet application  | Intra-op tourniquet milestones     |
| Granularity      | Label-level (what was done)           | Event-level (when, what, status)   |

This feature is additive and does not conflict with or modify
green-card outputs.

## Scope Exclusions

- No anesthesia physiologic metrics (temp, EBL, med doses) — deferred
  to `anesthesia-case-metrics-v1`.
- No inferred procedures from radiology/imaging text.
- No renderer changes.
- No NTDS/protocol engine changes.
