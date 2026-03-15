# Vitals Daily Extraction v1 — Contract

| Field   | Value                  |
|---------|------------------------|
| Status  | DRAFT — implemented    |
| Phase   | Tier 2 Hardening       |
| Owner   | CerebralOS Phase 1.1  |
| Module  | `cerebralos/features/vitals_daily.py` |
| Output  | `days.<YYYY-MM-DD>.vitals` in `patient_features_v1.json` |
| Date    | 2026-03-15             |

---

## 1. Purpose

Per-day vitals extraction from timeline items.  Produces per-metric
rollups (min, max, last, last_dt, sources[]) for each calendar day.

Additionally provides **arrival vitals extraction** with a deterministic
item-type-aware priority hierarchy.

Design principles:

- Deterministic, fail-closed.
- No inference. No LLM. No ML.
- Config-driven patterns (`rules/features/vitals_patterns_v1.json`).
- Flowsheet-table rows preferred when present.

---

## 2. Per-Day Vitals Schema (`extract_vitals_for_day`)

### 2.1 Output Keys

| Key              | Type       | Description                           |
|------------------|------------|---------------------------------------|
| `temp_f`         | metric obj | Temperature (°F)                      |
| `hr`             | metric obj | Heart rate (bpm)                      |
| `rr`             | metric obj | Respiratory rate (rpm)                |
| `spo2`           | metric obj | Oxygen saturation (%)                 |
| `sbp`            | metric obj | Systolic BP (mmHg)                    |
| `dbp`            | metric obj | Diastolic BP (mmHg)                   |
| `map`            | metric obj | Mean arterial pressure (mmHg)         |
| `abnormal_summary` | object   | Per-metric abnormal counts            |
| `warnings`       | list[str]  | Warning codes                         |
| `vitals_qa`      | object     | QA metrics for audit                  |

### 2.2 Metric Object

| Field           | Type             | Description                          |
|-----------------|------------------|--------------------------------------|
| `min`           | number or null   | Minimum value for the day            |
| `max`           | number or null   | Maximum value for the day            |
| `last`          | number or null   | Latest timestamped value             |
| `last_dt`       | string or null   | ISO timestamp of last value          |
| `count`         | integer          | Number of readings                   |
| `sources`       | list[source_obj] | All source evidence entries          |
| `abnormal_count`| integer          | Count of abnormal readings           |
| `first_abnormal`| object or null   | First abnormal reading detail        |

### 2.3 Source Types (Extraction Layer)

| Source Type    | Description                      | Parser              |
|----------------|----------------------------------|----------------------|
| `FLOWSHEET`    | Nursing flowsheet table rows     | `_parse_flowsheet_table` |
| `ED_TRIAGE`    | ED Triage Vitals block           | `_parse_ed_triage_block` |
| `VISIT_VITALS` | Visit Vitals label-value block   | `_parse_visit_vitals_block` |
| `INLINE`       | Narrative inline vitals          | `_parse_inline_vitals` |
| `TABULAR`      | Tabular note-internal vitals     | `_parse_tabular_note_vitals` |

### 2.4 Deduplication

When multiple parsers produce the same (metric, dt, value) tuple,
the highest-priority source type wins:

    FLOWSHEET > ED_TRIAGE > VISIT_VITALS > TABULAR > INLINE

---

## 3. Abnormal Thresholds (Locked)

| Metric   | Low        | High       |
|----------|------------|------------|
| `sbp`    | ≤ 90 mmHg  | —          |
| `map`    | ≤ 65 mmHg  | —          |
| `hr`     | < 50 bpm   | > 120 bpm  |
| `rr`     | < 10 rpm   | > 24 rpm   |
| `spo2`   | ≤ 92 %     | —          |
| `temp_f` | ≤ 96.0 °F  | ≥ 100.4 °F |

---

## 4. Arrival Vitals Extraction (`extract_arrival_vitals`)

Deterministic item-type-aware hierarchy for selecting arrival vitals.
Uses the timeline item `type` field to partition items by clinical
context.

### 4.1 Priority Hierarchy

| Priority | Item Type(s)            | Source Context    | Description               |
|----------|-------------------------|-------------------|---------------------------|
| 1        | `TRAUMA_HP`             | `PRIMARY_SURVEY`  | Trauma H&P (Primary / Secondary Survey vitals) |
| 2        | `ED_NOTE`, `ED_NURSING`, `TRIAGE` | `ED_FALLBACK` | ED provider / triage / nursing vitals |
| 3        | —                       | —                 | `DATA NOT AVAILABLE`       |

### 4.2 Selection Rules

1. Partition items by `type` into Primary Survey group and ED group.
2. For the highest-priority group that exists:
   a. Run all vitals parsers on those items.
   b. Deduplicate readings.
   c. If readings found → select earliest per metric → `status="selected"`.
3. If no group yields readings → `status="DATA NOT AVAILABLE"`.

### 4.3 Output Schema

| Field              | Type             | Description                            |
|--------------------|------------------|----------------------------------------|
| `status`           | string           | `"selected"` or `"DATA NOT AVAILABLE"` |
| `source_context`   | string or null   | `"PRIMARY_SURVEY"`, `"ED_FALLBACK"`, or null |
| `item_type`        | string or null   | Original item type (e.g. `"TRAUMA_HP"`) |
| `source_item_dt`   | string or null   | Timestamp of contributing item         |
| `source_item_id`   | string or null   | Source ID of contributing item         |
| `vitals`           | object           | Per-metric values (see §4.4)           |
| `readings_count`   | integer          | Total readings extracted               |
| `line_preview`     | string or null   | First evidence line preview            |
| `warnings`         | list[str]        | Warning codes                          |

### 4.4 Vitals Sub-Object

Keys: `temp_f`, `hr`, `rr`, `spo2`, `sbp`, `dbp`, `map`.
Each value is number or null (null = metric not found).

---

## 5. Guardrails

All extracted values are range-checked before acceptance:

| Metric   | Min  | Max  |
|----------|------|------|
| `temp_f` | 85   | 115  |
| `hr`     | 20   | 300  |
| `rr`     | 4    | 60   |
| `spo2`   | 50   | 100  |
| `sbp`    | 40   | 300  |
| `dbp`    | 20   | 200  |

Values outside these ranges are silently rejected (fail-closed).

---

## 6. Design Constraints

- No protected engine changes.
- No clinical inference.
- Config patterns live in `rules/features/vitals_patterns_v1.json`.
- MAP is always computed: `round(dbp + (sbp - dbp) / 3, 1)`.
