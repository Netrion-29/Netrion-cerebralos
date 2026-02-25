# consultant_events_v1 — Contract

## Feature key
`consultant_events_v1`

## Source
`note_index_events_v1` feature output (no raw-file reread).

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
  "source_rule_id": "consultant_events_from_note_index | no_note_index_available | no_consultant_entries",
  "warnings": [],
  "notes": []
}
```

## Fail-closed rules
| Condition | Result |
|---|---|
| No `note_index_events_v1` in features | consultant_present="DATA NOT AVAILABLE", source_rule_id=`no_note_index_available` |
| Note index present, no Notes section found | consultant_present="DATA NOT AVAILABLE", source_rule_id=`no_note_index_available` |
| Note index present, 0 consultant entries | consultant_present="no", source_rule_id=`no_consultant_entries` |
| Consultant entries found | consultant_present="yes", source_rule_id=`consultant_events_from_note_index` |

## Validation patients
- **Roscella_Weatherly**: 3 consultant services (Otolaryngology, Internal Medicine, Physical Therapy)
- **Lee_Woodard**: 4 consultant services (Wound/Ostomy, Orthopedics, Physical Therapy, Occupational Therapy)
- **Margaret_Rudd**: 3 consults (Internal Medicine, Neurosurgery, Orthopedics) + additional services
- **Anna_Dennis**: No note index → DATA NOT AVAILABLE
