# ventilator_settings_v1 — Schema Contract

**Module:** `cerebralos/features/ventilator_settings_v1.py`
**Feature key:** `ventilator_settings_v1` (under top-level `features` dict)
**Version:** v1
**Status:** Active

---

## Purpose

Deterministic extraction of ventilator setting parameters from raw patient
text with full `raw_line_id` traceability. Covers structured Vent Settings
blocks (flowsheet), O2 Device / NIV headers, and inline FiO2+PEEP narrative
patterns.

---

## Output Schema

```json
{
  "events": [
    {
      "param": "fio2",
      "value": 60,
      "day": "2026-01-10",
      "line_index": 4,
      "snippet": "FIO2 : 60 %",
      "raw_line_id": "a1b2c3d4e5f67890",
      "source": "vent_settings_block"
    }
  ],
  "summary": {
    "total_events": 6,
    "days_with_vent_data": 2,
    "mechanical_vent_days": ["2026-01-10"],
    "niv_days": ["2026-01-12"],
    "params_found": ["fio2", "peep", "resp_rate_set", "tidal_volume", "vent_status"]
  }
}
```

---

## Event Fields

| Field | Type | Description |
|---|---|---|
| `param` | string | One of: `vent_status`, `fio2`, `peep`, `tidal_volume`, `resp_rate_set`, `ventilated_flag` |
| `value` | number / string / bool | Extracted value (see param-specific semantics below) |
| `day` | string | ISO date (`YYYY-MM-DD`) of the day the line belongs to |
| `line_index` | int | Zero-based index into `raw_lines` for the day |
| `snippet` | string | Truncated source line (max 200 chars) |
| `raw_line_id` | string | SHA-256[:16] of `"{param}|{day}|{line_index}|{snippet}"` |
| `source` | string | Origin tag (see Source Tags below) |

### Source Tags

| Tag | Description |
|---|---|
| `vent_settings_block` | From structured Vent Settings header block (RR, Vt, PEEP, FiO2) |
| `o2_device_flowsheet` | From `O2 Device: Ventilator` flowsheet line |
| `ventilated_patient_flowsheet` | From `Ventilated Patient?: Yes` flowsheet line |
| `niv_header` | From `Non-Invasive Mechanical Ventilation` header |
| `inline_narrative` | From inline FiO2/PEEP patterns in clinical narrative |
| `fio2_flowsheet` | Standalone FiO2 flowsheet line outside a block |

---

## Summary Fields

| Field | Type | Description |
|---|---|---|
| `total_events` | int | Count of all extracted events |
| `days_with_vent_data` | int | Distinct days with any vent-related data |
| `mechanical_vent_days` | list[str] | Sorted ISO dates where `vent_status == "mechanical"` |
| `niv_days` | list[str] | Sorted ISO dates where `vent_status == "niv"` |
| `params_found` | list[str] | Sorted unique param names across all events |

---

## Param-Specific Semantics

| Param | Value Type | Unit / Scale | Notes |
|---|---|---|---|
| `vent_status` | `"mechanical"` or `"niv"` | — | Ventilator mode classification |
| `fio2` | float | percent (0–100) | **Canonicalized**: if raw parsed value ≤ 1.0, converted via ×100 before storage |
| `peep` | float | cm H₂O | — |
| `tidal_volume` | float | mL | — |
| `resp_rate_set` | float | breaths/min | Set respiratory rate |
| `ventilated_flag` | `true` | boolean | From explicit `Ventilated Patient?: Yes` |

---

## FiO2 Canonicalization Rule

All emitted `fio2` values are stored on the **percent scale (0–100)**.

- If the raw parsed value is ≤ 1.0 (fraction notation, e.g., `0.6`), it is
  converted to percent via `value * 100` → `60`.
- If the raw parsed value is > 1.0 (already percent, e.g., `60`), it is
  stored as-is.
- Range gating is applied **after** canonicalization.

---

## Range Gates (Fail-Closed)

Values outside physiological ranges are **silently rejected** (fail-closed).
No event is emitted for out-of-range values.

| Param | Min | Max |
|---|---|---|
| `fio2` | 20 | 100 |
| `peep` | 0 | 30 |
| `tidal_volume` | 50 | 2000 |
| `resp_rate_set` | 1 | 60 |

---

## raw_line_id Requirement

Every event **must** include a `raw_line_id` field. This is a deterministic
SHA-256[:16] hash computed from the extraction coordinates:

```
SHA-256("{param}|{day}|{line_index}|{snippet}")[:16]
```

This ensures full traceability from any output event back to the exact
source line in the raw patient text.

---

## Design Constraints

- **Deterministic**: No LLM, no ML, no clinical inference.
- **Fail-closed**: Unknown patterns are ignored, not guessed.
- **Additive only**: Does not modify any other feature module output.
- **Block capture**: Vent Settings header captures exactly the next 4 lines.
