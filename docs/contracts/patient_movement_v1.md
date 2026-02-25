# patient_movement_v1 — Contract

## Feature key
`patient_movement_v1`

## Source
Raw data file (`meta.source_file`), **Patient Movement** event-log subsection.

## Relationship to adt_transfer_timeline_v1
Complementary — **NOT** a replacement.
- `adt_transfer_timeline_v1` extracts the tab-delimited **ADT Events** header table (admission date, discharge date, arrival mode, etc.).
- `patient_movement_v1` extracts the structured **Patient Movement** event-log subsection with richer per-event fields (room, bed, level of care, providers, discharge disposition).

Both features may coexist in the same patient output.

## Schema

```json
{
  "entries": [
    {
      "unit": "<string>",
      "date_raw": "MM/DD",
      "time_raw": "HHMM",
      "event_type": "Admission | Transfer In | Discharge | Checked In | Checked Out",
      "room": "<string> | null",
      "bed": "<string> | null",
      "patient_class": "<string> | null",
      "level_of_care": "<string> | null",
      "service": "<string> | null",
      "providers": {"admitting": "...", "attending": "...", "discharge": "..."},
      "discharge_disposition": "<string> | null",
      "raw_line_id": "<sha256>"
    }
  ],
  "summary": {
    "movement_event_count": "<int>",
    "first_movement_ts": "MM/DD HHMM | null",
    "admission_ts": "MM/DD HHMM | null",
    "discharge_ts": "MM/DD HHMM | null",
    "discharge_disposition_final": "<string> | null",
    "transfer_count": "<int>",
    "units_visited": ["..."],
    "levels_of_care": ["..."],
    "services_seen": ["..."],
    "rooms_visited": ["..."],
    "event_type_counts": {"Admission": 1, "Transfer In": 2, "Discharge": 1}
  },
  "evidence": [
    {
      "role": "patient_movement_entry",
      "snippet": "<first 120 chars>",
      "raw_line_id": "<sha256>"
    }
  ],
  "source_file": "<path> | null",
  "source_rule_id": "patient_movement_raw_file | no_patient_movement_section",
  "warnings": [],
  "notes": []
}
```

## Fail-closed rules
| Condition | Result |
|---|---|
| No `meta.source_file` | entries=[], source_rule_id=`no_patient_movement_section` |
| Raw file exists, no Patient Movement section | entries=[], source_rule_id=`no_patient_movement_section` |
| Section found, 0 entries parsed | movement_event_count=0, source_rule_id=`patient_movement_raw_file` |

## Dedup rules (v2)
- Deterministic dedup on `(unit, date_raw, time_raw, event_type)`.
- First occurrence wins; duplicates are discarded.
- Warning `dedup_removed=N` emitted when duplicates are removed.

## Event types
| Event type | Body fields | Notes |
|---|---|---|
| Admission | Full | Standard inpatient/ED admission |
| Transfer In | Full | Unit-to-unit transfer |
| Discharge | Full | Includes discharge disposition |
| Checked In | **Bare** (all null) | Clinic/urgent-care check-in |
| Checked Out | **Bare** (all null) | Clinic/urgent-care check-out |

## Entry format (raw data)
```
<UnitName>\t<MM/DD>\t<HHMM>\t<EventType>

Room
<room_value>

Bed
<bed_value>

Patient Class
<class_value>

Level of Care          (optional)
<loc_value>

Service
<service_value>

[Admitting|Attending|Discharge] Provider  (optional, multiple)
<provider_name>

Discharge Disposition  (optional, Discharge events only)
<disposition_value>
```

## v2 summary enrichments
| Field | Description |
|---|---|
| `admission_ts` | Timestamp of the earliest Admission event (reverse-chron → last Admission entry) |
| `discharge_disposition_final` | Disposition from the most recent Discharge event |
| `event_type_counts` | Dict of `{event_type: count}` for all event types |
| `rooms_visited` | Ordered list of unique rooms (null rooms excluded) |

## Section boundaries
Detection stops at: Notes, LDAs, Flowsheets, Meds, Labs, Imaging,
Imaging EKG and Radiology, Scheduled, Procedures, Orders, Vitals,
Allergies, Consults, Results, Micro, I&O, ADT Events,
or lab-data lines (`MM/DD/YY HH:MM`).

## Medication-line guard
Entry-header regex rejects lines containing medication dosage terms
(tablet, capsule, mg, mL, etc.) to prevent false matches against
medication lines that share the tab-delimited format.

## Gate / validation patients
- **Roscella_Weatherly**: 7 movement events, inter-facility transfers, discharge
- **Ronald_Bittner**: 3 movement events, no discharge
- **Lee_Woodard**: 7 movement events, inter-facility, multiple dispositions
- **Betty_Roll**: 6 movement events incl. Checked In / Checked Out (bare entries)
- **Michael_Dougan**: No Patient Movement section (negative control)
- **Anna_Dennis**: Gate patient (expected no section)
