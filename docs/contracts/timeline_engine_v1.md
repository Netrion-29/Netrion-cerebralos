# Timeline Engine Contract v1 (Layer 1 — Calendar-Day Normalization)

## Purpose
Convert structured patient evidence into a deterministic, calendar-day indexed artifact (`patient_days.json`) that downstream engines (signals, NTDS rules, protocol rules, reporting) can evaluate without temporal ambiguity.

This layer DOES NOT:
- infer clinical facts
- decide NTDS/protocol outcomes
- re-parse raw note text

This layer DOES:
- choose the best-available timestamp for each structured item
- assign items to local calendar days (America/Chicago)
- produce stable ordering within each day
- preserve provenance pointers for audit

---

## Inputs (minimum required)
Input is a structured evidence JSON (already produced by Layer 0). The Timeline Engine only depends on:

### Required meta
- `meta.patient_id` (string)
- `meta.timezone` (string) — expected `America/Chicago`
- `meta.arrival_datetime` (string, ISO 8601) — canonical “Day 0” anchor

### Required items array
- `items[]` (array) where each item includes:
  - `source_id` (string, unique per item; stable across runs)
  - `type` (string: note|imaging|procedure|lab|diagnosis|med|other)
  - timestamp candidates (any/all may exist):
    - `dt` (explicit datetime, ISO 8601) — best
    - `document_dt` (document datetime, ISO 8601)
    - `date` (date-only, YYYY-MM-DD)
  - `payload` (object)
  - `provenance` (object; may include line offsets/snippet ids/doc ids)

Missing timestamps are allowed; items must never be dropped.

---

## Output Artifact
File: `patient_days.json` with shape:

- `meta` includes:
  - `patient_id`
  - `timezone`
  - `arrival_datetime`
  - `day0_date` (YYYY-MM-DD derived from arrival in local tz)
- `days` is a dict keyed by:
  - `YYYY-MM-DD` calendar days in local tz
  - plus `UNDATED` bucket (always present if any item lacks a date)

Each day contains:
- `anchors.start` / `anchors.end` (local day boundaries)
- `items[]` — normalized items with:
  - `dt` (ISO 8601) if known
  - `dt_quality` enum: `EXPLICIT|DOCUMENT|DATE_ONLY|MISSING`
  - `source_id`, `type`, `payload`, `provenance`
- `rollups` — optional placeholders; must not assume continuity without evidence

---

## Deterministic Rules

### Timezone / day boundaries
- All day assignment is done in `meta.timezone` (America/Chicago).
- Day boundaries are local calendar days.

### Timestamp precedence
For each item, choose the first available:
1. `item.dt` → `dt_quality=EXPLICIT`
2. `item.document_dt` → `dt_quality=DOCUMENT`
3. `item.date` → assign `T12:00:00` local → `dt_quality=DATE_ONLY`
4. none → no `dt` field → `dt_quality=MISSING` and bucket under `UNDATED`

### Stable ordering within a day
Sort by:
1. `dt` ascending (missing dt last)
2. `source_priority` ascending (if exists; default 999)
3. `source_id` ascending
4. `provenance.line_offset` ascending (if exists; default large)

Same input → identical output ordering every run.

### Fail-closed behavior
If a required temporal relationship cannot be proven downstream (due to missing timestamps), Layer 3 must output `UNKNOWN`.
Layer 1 must preserve missingness; never “guess” times.

---

## Notes for downstream layers
- Downstream logic must treat `patient_days.json` as temporal truth.
- Signals layer should read items by day and emit candidate facts.
- Rule engines should evaluate with explicit evidence pointers and day context.
