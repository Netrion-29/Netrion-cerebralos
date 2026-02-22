# Vitals Canonical Schema v1 — Contract

| Field   | Value                  |
|---------|------------------------|
| Status  | DRAFT — implemented    |
| Phase   | Tier 0 Foundation      |
| Owner   | CerebralOS Phase 1.1  |
| Module  | `cerebralos/features/vitals_canonical_v1.py` |
| Output  | `features.vitals_canonical_v1` in `patient_features_v1.json` |
| Date    | 2026-02-21             |

---

## 1. Purpose

Define a deterministic, audit-traceable canonical vital record structure.
All downstream metrics (arrival selection, shock detection, NTDS logic)
must consume this schema — never raw extraction output directly.

Design principles:

- Deterministic, fail-closed.
- No inference. No LLM. No ML.
- Every record maps to exactly one `raw_line_id` for audit traceability.

---

## 2. Canonical Vital Record Schema

Each extracted vital measurement normalizes into a single record object.

### 2.1 Required Fields

| Field            | Type             | Description                                      |
|------------------|------------------|--------------------------------------------------|
| `ts`             | string (ISO-8601) or null | Timestamp from evidence; null only when genuinely absent |
| `day`            | string (YYYY-MM-DD)      | Calendar day bucket from timeline                |
| `source`         | string           | One of: `TRAUMA_HP`, `ED_NOTE`, `FLOWSHEET`, `NURSING_NOTE`, `MONITOR_TEXT` |
| `confidence`     | integer (0–100)  | Deterministic score (see §5)                      |
| `raw_line_id`    | string (non-empty) | Audit trace key (see §6); **must never be empty** |
| `abnormal_flags` | list of string   | Sorted list of triggered flag names (see §3)      |
| `abnormal_count` | integer          | Length of `abnormal_flags`                        |

### 2.2 Metric Fields (Required — null When Not Available)

| Field      | Type           | Unit     |
|------------|----------------|----------|
| `sbp`      | number or null | mmHg     |
| `dbp`      | number or null | mmHg     |
| `map`      | number or null | mmHg     |
| `hr`       | number or null | bpm      |
| `rr`       | number or null | rpm      |
| `spo2`     | number or null | %        |
| `temp_c`   | number or null | °C       |
| `temp_f`   | number or null | °F       |

`temp_c` is deterministically derived from `temp_f` via
`round((temp_f - 32) * 5 / 9, 1)` when `temp_f` is present.

### 2.3 Optional Fields (Reserved — null Until Extraction Supports Them)

| Field         | Type           | Description                            |
|---------------|----------------|----------------------------------------|
| `o2_device`   | string or null | Oxygen delivery device type            |
| `o2_flow_lpm` | number or null | O₂ flow rate in L/min                  |
| `fio2`        | number or null | Fraction of inspired oxygen            |
| `position`    | string or null | Patient position at time of recording  |

These fields are present in the schema for forward compatibility.
They are always `null` in the current implementation (v1).

---

## 3. Abnormal Thresholds (Locked v1)

| Flag           | Metric   | Operator | Threshold |
|----------------|----------|----------|-----------|
| Hypotension    | `sbp`    | `<`      | 90        |
| Severe_HTN     | `sbp`    | `>=`     | 180       |
| Tachycardia    | `hr`     | `>`      | 120       |
| Bradycardia    | `hr`     | `<`      | 50        |
| Fever          | `temp_c` | `>=`     | 38.0      |
| Hypothermia    | `temp_c` | `<`      | 36.0      |
| Hypoxia        | `spo2`   | `<`      | 90        |
| Tachypnea      | `rr`     | `>`      | 24        |

Thresholds are version-locked. Any change requires a schema version
bump and update to this contract, the implementation module, validators,
and all consumers in the same PR.

Enforced by: `CANONICAL_ABNORMAL_THRESHOLDS` dict in
`cerebralos/features/vitals_canonical_v1.py`.

---

## 4. Arrival Selector Rules (Draft — Not Yet Implemented)

Arrival vital selection hierarchy (planned):

1. TRAUMA_HP Primary Survey vitals within 30 min of arrival
2. ED triage vitals
3. First FLOWSHEET within 15 minutes
4. Otherwise: DATA NOT AVAILABLE

This selector must be deterministic and unit-tested before activation.
See Tier 0.3 in `docs/roadmaps/TRAUMA_BUILD_FORWARD_PLAN_v1.md`.

---

## 5. Confidence Scoring (Deterministic)

Implemented in `_compute_confidence()`:

| Component                     | Points |
|-------------------------------|--------|
| Complete timestamp (date+time, not defaulted) | +40    |
| Structured source (`TRAUMA_HP` or `FLOWSHEET`) | +20    |
| Parsed numeric integrity validated | +10    |
| Time defaulted to 0000        | −20    |

Score is clamped to 0–100.

No inference, no probabilistic weighting. Score is fully reproducible
from the record's `ts`, `source`, and metric values.

---

## 6. Audit / raw_line_id Rule

Every canonical vital record **must** map to exactly one non-empty
`raw_line_id`. No inferred vitals without traceability.

In the current implementation, canonical vitals use a **sha256-based**
`raw_line_id`:

```
sha256(f"{source_id}|{dt}|{preview}")[:16]
```

This is a 16-hex-character deterministic hash derived from the
evidence coordinates (source ID, timestamp, line preview). It differs
from the Layer-0 evidence format (`L{line_start}-L{line_end}`) but is
equally deterministic and traceable.

See `docs/CODEX_RULEBOOK.md` §6 for the full `raw_line_id` format
policy across layers.

---

## 7. Per-Day Rollup Structure

Each day's canonical vitals are stored under:

```
features.vitals_canonical_v1.days.<YYYY-MM-DD>
```

With structure:

```json
{
  "records": [ /* array of canonical vital record objects */ ],
  "count": 5,
  "abnormal_total": 2
}
```

---

## 8. Sort Order (Deterministic)

Records within a day are sorted by:

```
(ts or "", source or "", raw_line_id)
```

This ensures stable, reproducible ordering across runs.

---

## 9. Versioning and Change Control

- This is **v1** of the vitals canonical contract.
- Any changes to the schema, thresholds, confidence formula, or
  `raw_line_id` derivation require:
  1. A version bump to this contract document.
  2. Corresponding code changes in the implementation module.
  3. Updates to all validators and consumers.
  4. All in the same PR (AGENTS.md §4).
- The contract file path is:
  `docs/contracts/vitals_canonical_v1.md`

---

End of contract.