# trauma_daily_plan_by_day_v1 — Feature Contract

| Field   | Value                              |
|---------|------------------------------------|
| Version | v1                                 |
| Date    | 2026-02-25                         |
| Status  | Active                             |
| Feature | `features["trauma_daily_plan_by_day_v1"]` |

## Purpose

Extract per-day plan text from physician progress notes (trauma and
medical/surgical specialties) and organise it by calendar day.  Provides
structured daily plan data so v5 per-day blocks can show the evolving
plan over the hospital stay.

## Qualifying Note Types (Allowlist)

Only these note headers qualify for extraction:

| Note Header                        | Item type        | Section Format       | Gate            |
|-----------------------------------|------------------|----------------------|-----------------|
| `Trauma Progress Note`            | `PHYSICIAN_NOTE` | Impression + Plan    | —               |
| `Trauma Tertiary Survey Note`     | `PHYSICIAN_NOTE` | Impression + Plan    | —               |
| `Trauma Tertiary Note`            | `PHYSICIAN_NOTE` | Impression + Plan    | —               |
| `Trauma Tertiary Progress Note`   | `PHYSICIAN_NOTE` | Impression + Plan    | —               |
| `Trauma Overnight Progress Note`  | `PHYSICIAN_NOTE` | Narrative (no Plan)  | — (warn+skip)   |
| `Daily Progress Note`             | `PHYSICIAN_NOTE` | Assessment + Plan    | ESA body text   |
| `ESA Brief Progress Note`         | `PHYSICIAN_NOTE` | Brief (no Plan)      | — (warn+skip)   |
| `ESA Brief Update`                | `PHYSICIAN_NOTE` | Brief (no Plan)      | — (warn+skip)   |
| `ESA Quick Update Note`           | `PHYSICIAN_NOTE` | Brief (no Plan)      | — (warn+skip)   |
| `ESA TRAUMA BRIEF NOTE`           | `PHYSICIAN_NOTE` | Brief (no Plan)      | — (warn+skip)   |

### General Physician / Specialty Note Patterns

Non-trauma `PHYSICIAN_NOTE` items are classified by header text
(first 500 chars). Each pattern maps to a descriptive `note_type` label:

| Pattern (header text)              | `note_type` label                   |
|-----------------------------------|-------------------------------------|
| Hospital Progress Note / Deaconess Care Group | Hospital Progress Note    |
| Pulmonary/Critical Care / PCCM    | Critical Care Progress Note         |
| Neurology (Inpatient) Consult/Progress | Neurology Progress Note        |
| Heart Group Daily Progress         | Cardiology Progress Note            |
| Electrophysiology (Daily) Progress / Brief EP | Electrophysiology Progress Note |
| Cardiology                         | Cardiology Progress Note            |
| Palliative Care                    | Palliative Care Progress Note       |
| Speech Language Pathology          | Speech Language Pathology           |
| Infectious Disease                 | Infectious Disease Progress Note    |
| Neurosurgery - {dx} ({surgeon})    | Neurosurgery Progress Note          |
| DEACONESS CLINIC NEPHROLOGY / Renal brief note | Nephrology Progress Note |
| HEMATOLOGY/ONCOLOGY                | Hematology/Oncology Progress Note   |
| Plastics consult                   | Plastics Progress Note              |

Notes:
- `Daily Progress Note` is only matched when the note body contains
  "Evansville Surgical Associates" (ESA gate) to avoid false-matching
  hospitalist notes.
- Brief/narrative notes without a Plan: section emit a warning and are
  skipped (fail-closed).  They are counted for audit visibility.
- `Assessment:` is accepted as an alternate section label for
  `Impression:` (used by ESA Daily Progress Note format).
- `A/P:` is accepted as an alternate section label for `Assessment/Plan:`
  (used by Neurosurgery SOAP format).
- Non-trauma notes without a Plan/Assessment-Plan/A-P section are
  silently skipped (fail-closed).

Excluded:
- `CONSULT_NOTE` items (initial consults — separate feature)
- Radiology reads typed as `PHYSICIAN_NOTE` → filtered by heuristic
- Unclassifiable `PHYSICIAN_NOTE` items (medication orders, etc.)
- ED notes, nursing notes, discharge summaries
- Orthopedics, CT Surgery, Wound Care, Anesthesia (not `PHYSICIAN_NOTE`)

## Extraction Strategy

1. Iterate `patient_days_v1.json` days chronologically.
2. For each `PHYSICIAN_NOTE` item, check for qualifying header.
3. For `Daily Progress Note`, verify ESA affiliation in body text.
4. Skip radiology reads (heuristic: `Narrative & Impression` or
   `INDICATION` + `FINDINGS` without qualifying header).
5. Extract `Impression:` or `Assessment:` section (bounded by `Plan:` start).
6. Extract `Plan:` section (bounded by attestation/footer terminators).
   Plan may have inline content on the header line.
7. Parse plan lines as bulleted items (dash-prefixed).
8. Record author, timestamp, and raw_line_id for traceability.

## Output Schema

```json
{
    "days": {
        "<ISO-date>": {
            "notes": [
                {
                    "note_type": "Trauma Progress Note",
                    "author": "Allison Kimmel, PA-C",
                    "dt": "2026-01-03T06:56:00",
                    "source_id": "61",
                    "impression_lines": ["72 y.o. male s/p fall...", ...],
                    "plan_lines": ["-  ICU", "- NSGY consult...", ...],
                    "impression_line_count": 6,
                    "plan_line_count": 14,
                    "raw_line_id": "a1b2c3d4e5f6g7h8"
                }
            ]
        }
    },
    "total_notes": 9,
    "total_days": 7,
    "qualifying_note_types_found": ["Trauma Progress Note", "Trauma Tertiary Survey Note"],
    "source_rule_id": "trauma_daily_plan_from_progress_notes",
    "warnings": [],
    "notes": []
}
```

## Key Fields

| Field                       | Description                                      |
|----------------------------|--------------------------------------------------|
| `days`                     | Per-day dict keyed by ISO date                   |
| `days[d].notes`            | List of extracted notes for that day              |
| `notes[].note_type`        | Qualifying note header text                       |
| `notes[].author`           | Clinician name + credential from note header      |
| `notes[].dt`               | ISO datetime of the note                          |
| `notes[].source_id`        | Timeline item source_id for traceability          |
| `notes[].impression_lines` | Extracted impression text lines                   |
| `notes[].plan_lines`       | Extracted plan text lines (bulleted)              |
| `notes[].raw_line_id`      | SHA-256 hash for evidence tracing                 |
| `total_notes`              | Total qualifying notes extracted                  |
| `total_days`               | Number of days with qualifying notes              |
| `source_rule_id`           | Extraction path identifier                        |

## Dedup / Caps / Warnings

- **Dedup**: Notes within a day are sorted by `dt` for deterministic ordering.
  No cross-day dedup (each day's plan is independent).
- **Caps**: Max 60 plan lines per note, max 30 impression lines per note.
- **Warnings**: Emitted when a qualifying note has no extractable Plan section.
- **Fail-closed**: If no qualifying notes exist → `source_rule_id = "no_qualifying_notes"`,
  `days = {}`, `total_notes = 0`.

## Evidence Tracing

Every extracted note includes `raw_line_id = sha256(source_id|dt|preview)[:16]`.

## v5 Rendering

Rendered in the per-day block as "Trauma Daily Plan:" section, after
Device Day Counts and before B7 Clinical Narrative.

Format:
```
Trauma Daily Plan:
  [Trauma Progress Note] 06:56:00 — Allison Kimmel, PA-C
  Impression (6 lines):
    72 y.o. male s/p fall ...
  Plan (14 lines):
    -  ICU
    - NSGY consult...
```

Rendering caps: 15 impression lines, 40 plan lines per note.

## Boundaries

- Does NOT extract consultant day-plans (separate feature)
- Does NOT modify `note_sections_v1` semantics
- Does NOT change v3 or v4 renderers
- Overlap with `non_trauma_team_day_plans_v1` is intentional: that
  feature captures brief updates; this captures full A/P sections
