# ADT Transfer Timeline v1 — Contract

## Purpose

Deterministic extraction of ADT (Admission–Discharge–Transfer) events
from the raw export header and/or embedded note sections. Produces a
structured timeline of unit transfers, admissions, and discharges to
support Daily Notes v5 chronology and disposition context.

## Input

| Parameter     | Source                                        |
|---------------|-----------------------------------------------|
| pat_features  | `{"days": feature_days}` (standard pattern)   |
| days_data     | full `patient_days_v1.json` with injected `meta.raw_header_lines` |

The extractor searches two sources in priority order:

1. `meta.raw_header_lines` — first 50 lines of the raw export (injected
   by the build orchestrator from `patient_evidence_v1.json → raw.first_50_lines`).
2. Timeline item payload text — scans all items for an "ADT Events"
   section header.

First source that yields rows wins (no merging).

## Table Format Matched

Tab-delimited table beginning with header line `ADT Events`:

```
ADT Events

	Unit	Room	Bed	Service	Event
MM/DD/YY HHMM	UNIT_NAME	ROOM	BED	SERVICE	EVENT_TYPE
```

### Headerless Variant (v2)

Some raw files (e.g. Ronald Bittner) embed ADT data rows directly after
demographics (name / age / DOB) with **no** "ADT Events" header and no
column header row. The extractor detects these via a headerless fallback
that scans for `RE_ADT_ROW` matches when the standard header-based
extraction yields no events.

Event types (whitelist): `Admission`, `Transfer In`, `Transfer Out`,
`Patient Update`, `Discharge`.

## Output Shape

```jsonc
{
  "events": [
    {
      "timestamp_raw": "12/29/25 0722",
      "timestamp_iso": "2025-12-29 07:22:00",   // or "DATA NOT AVAILABLE"
      "unit": "EMERGENCY DEPT MC",
      "room": "1857",
      "bed": "16",
      "service": "Emergency",
      "event_type": "Admission",
      "raw_line_id": "header:8"
    }
    // ... one entry per table row
  ],
  "summary": {
    "adt_event_count": 15,          // total parsed events
    "first_admission_ts": "2025-12-29 07:22:00",  // or null
    "transfer_count": 7,            // max(transfer-in, transfer-out counts)
    "discharge_ts": "2026-01-07 17:54:00",  // or null
    "units_visited": ["EMERGENCY DEPT MC", "ORTHO NEURO TR CRE CTR", "SURGERY MC"],
    "los_hours": 226.5,             // or null
    "los_days": 9.4,                // or null (v2)
    "event_type_counts": {          // v2
      "Admission": 1,
      "Transfer Out": 7,
      "Transfer In": 7,
      "Patient Update": 0,
      "Discharge": 1
    },
    "services_seen": ["Emergency", "Trauma"],  // sorted unique (v2)
    "rooms_visited": ["1857", "4512", "4507"],  // ordered unique, excludes MCTRANSITION/NONE (v2)
    "patient_update_count": 0,      // v2
    "last_unit": "SURGERY MC",      // v2
    "last_room": "4507",            // v2
    "last_bed": "4507-01"           // v2
  },
  "evidence": [
    {
      "role": "adt_event",
      "snippet": "12/29/25 0722 Admission EMERGENCY DEPT MC 1857",
      "raw_line_id": "header:8"
    }
  ],
  "warnings": [],
  "notes": ["source=raw_header_lines, rows=15"]
}
```

When no ADT table is found, `events` is `[]`, summary fields are
`0` / `null` / `[]`, and `notes` contains `"no_adt_table_found"`.

## Determinism Guarantees

- **Fail-closed**: only structured tab-delimited table rows with
  whitelisted event types are captured.
- **No inference**: no clinical reasoning, no LLM, no ML.
- **raw_line_id**: every event and evidence entry carries a raw_line_id
  (`header:<idx>`, `header_headerless:<idx>`, or `item:<day>:<item_idx>:<idx>`).
- **First-source-wins**: header lines checked first (standard header →
  headerless fallback), then timeline items; no merging across sources.
- **Timestamp normalisation**: `MM/DD/YY HHMM` → `YYYY-MM-DD HH:MM:SS`
  with 2-digit year pivot at 80.
- **Defensive dedup** (v2): exact-match dedup on
  `(timestamp_raw, unit, room, bed, event_type)`. First occurrence wins;
  duplicates dropped with warning.
- **Chronology validation** (v2): warns if events deviate from
  chronological order. Does NOT reorder — purely advisory.

## Validation

The contract validator checks:

- `adt_transfer_timeline_v1` present in `KNOWN_FEATURE_KEYS`.
- Every entry in `evidence[]` has `raw_line_id`.
- Every entry in `events[]` has `raw_line_id`.

## QA Visibility

The `report_features_qa.py` renders:

- `ADT TRANSFER TIMELINE v1 QA:` section with summary fields,
  event list (up to 20), evidence count, warnings, and notes.

## Gate Patients

Standard gate: Anna_Dennis, William_Simmons, Timothy_Cowan, Timothy_Nachtwey.
ADT-positive validation: Michael_Dougan (header), Gary_Linder (embedded note),
Ronald Bittner (headerless variant).

## Changelog

| Date       | Change                        |
|------------|-------------------------------|
| 2026-02-25 | v2 — headerless ADT fallback, defensive dedup, chronology validation, enriched summary (event_type_counts, services_seen, rooms_visited, patient_update_count, last_unit/room/bed, los_days) |
| 2026-02-24 | v1 — initial implementation   |
