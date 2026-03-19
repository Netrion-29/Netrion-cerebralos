# note_index_events_v1 — Contract Doc

## Feature Key
`note_index_events_v1`

## Purpose
Deterministic extraction of the **Notes subsection** from the Epic-format
encounter event log.  Captures the structured index of all notes authored
during the encounter: timestamps, authors, credentials, and service tags.

Only the `Notes` subsection is parsed — NOT Meds / Labs / Imaging / LDAs /
Flowsheets / Patient Movement.

## Source
Raw data file (`data_raw/<patient>.txt`), path injected via
`meta.source_file` from the evidence JSON.

## Output Schema

```json
{
  "entries": [
    {
      "note_type": "Consults",
      "date_raw": "01/01",
      "time_raw": "1020",
      "author_raw": "Chacko, Chris E, MD",
      "author_name": "Chacko, Chris E",
      "author_credential": "MD",
      "service": "Otolaryngology",
      "raw_line_id": "<sha256>"
    }
  ],
  "summary": {
    "note_index_event_count": 25,
    "unique_authors_count": 15,
    "unique_note_types_count": 8,
    "services_detected": ["Otolaryngology", "Internal Medicine"],
    "consult_note_count": 2
  },
  "evidence": [
    {
      "role": "note_index_entry",
      "snippet": "Consults 01/01 1020 Chacko, Chris E, MD",
      "raw_line_id": "<sha256>"
    }
  ],
  "source_file": "/path/to/raw/file.txt",
  "source_rule_id": "note_index_raw_file",
  "warnings": [],
  "notes": ["source=raw_file, section_lines=86, entries_parsed=25"]
}
```

## Note Types Observed
- Consults
- Discharge Summary
- ED Notes
- ED Provider Notes
- H&P
- Plan of Care
- Progress Notes
- Triage Assessment
- Anesthesia Procedure Notes

## Fail-Closed Behaviour
| Condition | Result |
|---|---|
| No `meta.source_file` | `source_rule_id="no_notes_section"`, entries=[] |
| Raw file not found | Same + `source_file_not_found` warning |
| No Notes subsection | `source_rule_id="no_notes_section"`, entries=[] |
| Notes subsection empty | `note_index_event_count=0` |
| Older format patients | No Notes section → fail-closed |

## Gate Patients
- Roscella_Weatherly — rich Notes (25 entries)
- Lee_Woodard — rich Notes (40 entries)
- Michael_Dougan — no Notes section (negative control)
- Betty_Roll, David_Gross, Johnny_Stokes, Larry_Corne, Ronald_Bittner, Roscella_Weatherly — gate

## Dependencies
- `meta.source_file` injected by builder from evidence JSON
- No other feature dependencies

## Design
- Deterministic, fail-closed
- No LLM, no ML, no clinical inference
- `raw_line_id` on every evidence entry
