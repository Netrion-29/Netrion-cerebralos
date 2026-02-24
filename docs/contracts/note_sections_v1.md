# Note Sections v1 — Contract

| Field   | Value                                              |
|---------|----------------------------------------------------|
| Module  | `cerebralos/features/note_sections_v1.py`           |
| Version | v1                                                 |
| Date    | 2026-02-23                                         |
| Roadmap | Daily Notes v5 Phase A1 — structured section extraction |

---

## Purpose

Deterministic extraction of the five canonical note sections from trauma
documentation:

1. **HPI** — History of Present Illness
2. **Primary Survey** — with sub-fields: Airway, Breathing, Circulation,
   Disability, Exposure, FAST
3. **Secondary Survey**
4. **Impression** — clinical impression only (NOT radiological IMPRESSION)
5. **Plan**

This feature provides structured section text and boundaries that
downstream renderers and protocol engines can consume without re-parsing
raw notes.

---

## Output Key

`features.note_sections_v1` in `patient_features_v1.json`.

---

## Output Schema

```json
{
  "sections_present": true | false | "DATA NOT AVAILABLE",
  "source_type": "TRAUMA_HP | ED_NOTE | PHYSICIAN_NOTE | CONSULT_NOTE | null",
  "source_ts": "<ISO datetime> | null",
  "source_rule_id": "trauma_hp_sections | ed_note_sections | physician_note_sections | consult_note_sections | no_qualifying_source",
  "hpi": {
    "present": true | false,
    "text": "<full extracted text> | null",
    "line_count": 0
  },
  "primary_survey": {
    "present": true | false,
    "text": "<full extracted text> | null",
    "line_count": 0,
    "fields": {
      "airway": "<text> | null",
      "breathing": "<text> | null",
      "circulation": "<text> | null",
      "disability": "<text> | null",
      "exposure": "<text> | null",
      "fast": "<text> | null"
    }
  },
  "secondary_survey": {
    "present": true | false,
    "text": "<full extracted text> | null",
    "line_count": 0
  },
  "impression": {
    "present": true | false,
    "text": "<full extracted text> | null",
    "line_count": 0
  },
  "plan": {
    "present": true | false,
    "text": "<full extracted text> | null",
    "line_count": 0
  },
  "evidence": [
    {
      "raw_line_id": "<sha256[:16]>",
      "source_type": "TRAUMA_HP | ED_NOTE | ...",
      "ts": "<ISO datetime | null>",
      "section": "hpi | primary_survey | secondary_survey | impression | plan",
      "snippet": "<first 120 chars>"
    }
  ],
  "notes": ["..."],
  "warnings": ["..."]
}
```

---

## Source Precedence

1. `TRAUMA_HP` — preferred; standard structured format
2. `ED_NOTE` — fallback
3. `PHYSICIAN_NOTE` — fallback
4. `CONSULT_NOTE` — lowest priority

Within the same source type, earlier (by timestamp) is preferred.

---

## Section Boundaries

| Section          | Start Pattern                     | End Pattern                              |
|------------------|-----------------------------------|------------------------------------------|
| HPI              | `^HPI:` or `^History of Present Illness:` | Primary Survey, Secondary Survey, PMH, etc. |
| Primary Survey   | `^Primary Survey:`                | Secondary Survey, PMH, Allergies, etc.   |
| Secondary Survey | `^Secondary Survey:`              | Radiographs, Labs, Impression, Plan, etc.|
| Impression       | `^Impression:` (title case only)  | Plan, Disposition, etc.                  |
| Plan             | `^Plan:` or `^Assessment/Plan:`   | Disposition, Electronically signed, etc. |

---

## Primary Survey Sub-fields

Extracted from indented lines within the Primary Survey block:

- `Airway:` → `fields.airway`
- `Breathing:` → `fields.breathing`
- `Circulation:` → `fields.circulation`
- `Disability:` → `fields.disability`
- `Exposure:` → `fields.exposure`
- `FAST:` → `fields.fast`

---

## Fail-closed Behavior

| Condition                              | Result                                |
|----------------------------------------|---------------------------------------|
| No qualifying source item              | `sections_present = "DATA NOT AVAILABLE"` |
| Source exists, section absent           | `section.present = false`             |
| Radiological `IMPRESSION:` (ALL CAPS)  | Excluded from clinical Impression     |
| Anna_Dennis outlier format             | `History of Present Illness:` → HPI   |

---

## Evidence Contract

Every entry in `evidence[]` carries:

- `raw_line_id` — SHA-256[:16] of `"source_type|source_id|first_line_stripped"`
- `source_type` — the timeline item type
- `ts` — ISO timestamp from the item (may be null)
- `section` — which section this evidence belongs to
- `snippet` — first 120 chars of the section

---

## Warnings

| Code                      | Trigger                                       |
|---------------------------|-----------------------------------------------|
| `no_qualifying_source`    | No TRAUMA_HP/ED_NOTE/PHYSICIAN_NOTE/CONSULT_NOTE found |
| `non_trauma_hp_source`    | Fallback source used (not TRAUMA_HP)           |
| `most_sections_missing`   | 4+ of 5 sections absent in the selected note   |

---

## Gate Patients

- `Timothy_Cowan` — TRAUMA_HP present, all sections expected
- `William_Simmons` — TRAUMA_HP present, all sections expected
- `Anna_Dennis` — outlier format, "History of Present Illness" alias
- `Timothy_Nachtwey` — no TRAUMA_HP, ED/CONSULT fallback

---

## Validation Canary

`Michael_Dougan` — new paste format canary, standard TRAUMA_HP structure.
