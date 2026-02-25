# lda_events_v1 — Contract

## Feature key
`lda_events_v1`

## Source
Raw data file (`meta.source_file`), **LDAs** (Lines / Drains / Airways) section.

Two source formats are handled:

- **Format A — Summary LDA** (newer event-log exports): `LDAs` header → device category → device label with assessment count → Placed/Removed/Duration fields → timestamped assessment rows.
- **Format B — Event-log Active LDA** (daily-note–embedded): `Patient Lines/Drains/Airways Status` → `Active LDAs` → tabular Name/Placement date/Placement time/Site/Days rows.  Two sub-formats exist:
  - **Newline-format B**: each field on its own line (5-line blocks per device)
  - **Tab-format B**: single tab-delimited row per device: `\tName\tDate\tTime\tSite\tDays`

## Relationship to existing features
- **Additive** — does NOT replace device-day-count logic (per-day `devices` in `days[]`).
- Provides explicit device lifecycle (placement/removal timestamps, duration, assessment rows) vs. the existing inferred device-tri-state per day.
- Urine-output-specific analysis is intentionally deferred to a separate `urine_output_events_v1` feature.

## Schema

```json
{
  "devices": [
    {
      "device_type": "<string>",
      "device_label": "<string>",
      "category": "PIV | PICC | Arterial Line | Central Line | Urethral Catheter | External Urinary Catheter | Chest Tube | Surgical Airway/Trach | Feeding Tube | Wound | Drain | Peripheral Nerve Catheter | Other",
      "placed_ts": "MM/DD/YY HHMM | null",
      "removed_ts": "MM/DD/YY HHMM | null",
      "duration_text": "<string> | null",
      "site": "<string> | null",
      "source_format": "summary | event_log",
      "assessment_count": "<int>",
      "event_rows": [
        {
          "ts_raw": "MM/DD HHMM",
          "fields": {"<key>": "<value>"}
        }
      ],
      "evidence": [
        {
          "role": "lda_device_entry",
          "snippet": "<first 120 chars>",
          "raw_line_id": "<sha256>"
        }
      ]
    }
  ],
  "lda_device_count": "<int>",
  "active_devices_count": "<int>",
  "categories_present": ["PIV", "Urethral Catheter", "..."],
  "devices_with_placement": ["<device_label>", "..."],
  "devices_with_removal": ["<device_label>", "..."],
  "source_file": "<path> | null",
  "source_rule_id": "lda_events_raw_file | no_lda_section",
  "warnings": [],
  "notes": []
}
```

## Fail-closed rules
| Condition | Result |
|---|---|
| No `meta.source_file` | devices=[], source_rule_id=`no_lda_section` |
| Raw file exists, no LDAs section | devices=[], source_rule_id=`no_lda_section` |
| Section found, 0 devices parsed | lda_device_count=0, source_rule_id=`lda_events_raw_file` |

## Category mapping

| Device prefix | Category |
|---|---|
| Peripheral IV | PIV |
| PICC | PICC |
| Arterial Line | Arterial Line |
| Central Line, CVC | Central Line |
| Urethral Catheter | Urethral Catheter |
| External Urinary Catheter | External Urinary Catheter |
| Chest Tube | Chest Tube |
| Surgical Airway, Trach | Surgical Airway/Trach |
| Non-Surgical Airway | Non-Surgical Airway |
| G-tube, J-tube, Feeding Tube, PEG | Feeding Tube |
| NG/OG Tube | NG/OG Tube |
| Wound | Wound |
| JP Drain, Surgical Drain, Drain | Drain |
| Continuous Nerve Block | Peripheral Nerve Catheter |

## Deduplication
Event-log format may repeat the same device across multiple daily snapshots. Devices are deduplicated by `device_label`, merging placement/removal/assessment data from the richest entry.  Evidence entries from all snapshot occurrences are preserved.  A `snapshot_duplicates_merged: N` note is added to `notes[]` when merges occur.

Em-dash characters (U+2014, U+2013) in the `Site` column are normalized to `null`.

## Evidence traceability
- Each device entry has `evidence[]` with `raw_line_id` (SHA-256 hash of the raw text line containing the device label).
- Since this feature parses the raw `.txt` file directly (like `patient_movement_v1` and `note_index_events_v1`), the `raw_line_id` is a hash of the source text rather than a timeline item reference.

## Deferred scope
- Urine-output-specific extraction (aggregation, trending, normalization) → `urine_output_events_v1` (separate PR)
- Assessment row normalization (e.g., structured urine color/appearance/output parsing) → deferred
- Device lifecycle timeline rendering → `render_trauma_daily_notes_v5.py` update (separate PR)

## Determinism
- Deterministic, fail-closed.
- No LLM, no ML, no clinical inference.
- Assessment rows capped at 50 per device.
