# consultant_events_v1 — Contract

## Feature key
`consultant_events_v1`

## Source
- **Primary path:** `note_index_events_v1` feature output (no raw-file reread).
- **Fallback path:** Timeline `CONSULT_NOTE` items from `patient_days_v1.json`
  when `note_index_events_v1` returns `source_rule_id="no_notes_section"`
  (bracket-format files without a Notes event-log section).

## Purpose
Deterministic extraction of consultant-service involvement from the
Notes event-log index. Captures which specialist consultant services
were involved, with timing, note counts, and author details.

Does NOT extract consultant recommendations or note body content —
that is `consultant_plan_items_v1` (separate PR).

## Consultant detection rules

### Included (consultant evidence)
1. **note_type == "Consults"** with explicit service NOT in exclusion set
2. **note_type == "Progress Notes"** with explicit service NOT in exclusion set

### Excluded (non-consultant)
**Service exclusion set:**
- General Surgeon — primary trauma service
- Hospitalist — co-management role
- Physician to Physician — handoff note
- Nurse to Nurse — nursing handoff
- Case Manager — case management
- Emergency — ED staff
- Surgery — alias for primary surgical service

**Note type exclusion (never consultant regardless of service):**
- ED Notes, ED Provider Notes, Triage Assessment, H&P, Discharge Summary, Plan of Care

**Empty/null service:** excluded (no inference from credentials)

## Timeline CONSULT_NOTE fallback path

When `note_index_events_v1` has `source_rule_id="no_notes_section"` (the
raw file has no Notes event-log section — typical of bracket-format files),
the extractor falls back to scanning timeline items.

### Fallback detection rules
1. Scan all days in `patient_days_v1.json` for items with `type == "CONSULT_NOTE"`.
2. Extract consultant service name from the note text using:
   - **"consult to \<SERVICE\>"** pattern (e.g., `Consult to Pulmonology [order 12345]`)
   - **"\<SERVICE\> Consult Note"** heading pattern as a secondary match
3. Apply the same service exclusion set as the primary path.
4. Skip primary-service notes mislabeled as CONSULT_NOTE (Trauma H&P).
5. Pick the longest candidate when multiple "consult to" matches exist.
6. Normalize service names via alias map (e.g., "Orthopedics" → "Orthopedic Surgery").

### Service name aliases (fallback normalization)
| Raw pattern | Canonical form |
|---|---|
| orthopedic surgery, ortho, orthopedics | Orthopedic Surgery |
| vascular surgery, vascular | Vascular Surgery |
| neurosurgery | Neurosurgery |
| pulmonology | Pulmonology |
| ent | ENT |
| infection control | Infection Control |
| infectious disease | Infectious Disease |
| palliative care | Palliative Care |
| case management/social work, case management | Case Management |

### Primary-note exclusion
CONSULT_NOTE items whose first 500 chars contain "Trauma H & P",
"Trauma H&P", or "Trauma HP" are treated as primary-service notes
and excluded from consultant results.

## Schema

```json
{
  "consultant_present": "yes | no | DATA NOT AVAILABLE",
  "consultant_services_count": "<int>",
  "consultant_services": [
    {
      "service": "<string>",
      "first_ts": "MM/DD HHMM",
      "last_ts": "MM/DD HHMM",
      "note_count": "<int>",
      "authors": ["<author_name>", ...],
      "note_types": ["Consults", "Progress Notes"],
      "evidence": [
        {
          "role": "consultant_event",
          "snippet": "<first 120 chars>",
          "raw_line_id": "<sha256>"
        }
      ]
    }
  ],
  "source_rule_id": "consultant_events_from_note_index | consultant_events_from_timeline_items | no_note_index_available | no_consultant_entries",
  "warnings": [],
  "notes": []
}
```

## Fail-closed rules
| Condition | Result |
|---|---|
| No `note_index_events_v1` in features | consultant_present="DATA NOT AVAILABLE", source_rule_id=`no_note_index_available` |
| Note index present, no Notes section found, **no CONSULT_NOTE timeline items** | consultant_present="DATA NOT AVAILABLE", source_rule_id=`no_note_index_available` |
| Note index present, no Notes section found, **CONSULT_NOTE items found** | consultant_present="yes", source_rule_id=`consultant_events_from_timeline_items` |
| Note index present, 0 consultant entries | consultant_present="no", source_rule_id=`no_consultant_entries` |
| Consultant entries found (note_index path) | consultant_present="yes", source_rule_id=`consultant_events_from_note_index` |

## Validation patients
- **Roscella_Weatherly**: 3 consultant services (Otolaryngology, Internal Medicine, Physical Therapy) — note_index primary path
- **Lee_Woodard**: 4 consultant services (Wound/Ostomy, Orthopedics, Physical Therapy, Occupational Therapy) — note_index primary path
- **Margaret_Rudd**: 3 consults (Internal Medicine, Neurosurgery, Orthopedics) + additional services — note_index primary path
- **Timothy_Nachtwey**: 5 consultant services via timeline fallback (bracket-format, no Notes section)
- **Anna_Dennis**: CONSULT_NOTE is "Trauma consult" (primary service, correctly excluded) → DATA NOT AVAILABLE
- **Timothy_Cowan**: No CONSULT_NOTE items in file → DATA NOT AVAILABLE
