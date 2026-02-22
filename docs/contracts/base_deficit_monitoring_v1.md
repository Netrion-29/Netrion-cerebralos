# Base Deficit Monitoring v1 — Contract

**Module:** `cerebralos/features/base_deficit_monitoring_v1.py`
**Output key:** `base_deficit_monitoring_v1`
**Tier:** 1 Metric #3
**Reference policy:** Deaconess "Monitoring Base Deficit" (Revised June 2023)

---

## Output Contract

```json
{
  "base_deficit_monitoring_v1": {
    "initial_bd_ts": "ISO" | null,
    "initial_bd_value": number | null,
    "initial_bd_source": "arterial|venous|unknown",
    "initial_bd_raw_line_id": "..." | null,

    "trigger_bd_gt4": boolean | null,
    "first_trigger_ts": "ISO" | null,

    "bd_series": [
      {
        "ts": "ISO",
        "value": number,
        "specimen": "arterial|venous|unknown",
        "raw_line_id": "...",
        "snippet": "..."
      }
    ],

    "monitoring_windows": [
      {
        "phase": "q2h_until_improving|q4h_until_lt4",
        "start_ts": "ISO",
        "end_ts": "ISO" | null,
        "expected_interval_hours": 2 | 4,
        "observations": int,
        "max_gap_hours": number | null,
        "compliant": boolean | null,
        "violations": [
          {
            "gap_hours": number,
            "from_ts": "ISO",
            "to_ts": "ISO",
            "note": "..."
          }
        ]
      }
    ],

    "overall_compliant": boolean | null,
    "noncompliance_reasons": [string],
    "notes": [string]
  }
}
```

---

## Definitions

### Base Deficit Value
- Accept "Base Deficit" and "Base Excess" lab components.
- If only Base Excess reported: `BD = -BE` (only when explicitly labeled as base excess).
- Reject out-of-range values outside `[-30, +30]`.

### Specimen Source
- **arterial**: explicit ABG / "arterial" / "Art POC" context on the same line or component name.
- **venous**: explicit VBG / "venous" context on the same line.
- **unknown**: no explicit specimen context.
- Do NOT infer arterial from timing alone.

### Trigger
- Activates if **any** BD value > 4 (per Deaconess protocol).
- `trigger_bd_gt4 = true` once any BD in the series exceeds 4.
- `first_trigger_ts` records the timestamp of the first BD > 4.

### Improving (Deterministic Rule)
- **Improving** is defined as: two consecutive BD values that are strictly decreasing.
- Formally: `series[i].value > series[i+1].value > series[i+2].value`
- The transition to q4h phase occurs at index `i+2` (after the second consecutive decrease).

### Cadence Thresholds
| Phase | Expected Interval | Max Allowed Gap (with charting slack) |
|-------|------------------|---------------------------------------|
| q2h_until_improving | ≤ 2 hours | 2.5 hours |
| q4h_until_lt4 | ≤ 4 hours | 4.5 hours |

Violations are flagged when the gap between consecutive BD draws exceeds the max allowed gap for the current phase.

### Stop Conditions
- **q2h phase** ends when "improving" is detected (two consecutive decreases).
- **q4h phase** ends when BD < 4 (first occurrence) OR no further labs (`end_ts = null`).

---

## Data Sources

1. **Primary:** Structured labs from `patient_features_v1.json` → `days[date].labs.series` and `days[date].labs.daily`.
2. **Supplementary:** Raw timeline items (type=LAB) scanned for BD mentions not captured by the structured extractor (e.g., POC variant names like "Base Deficit, Art POC").

---

## Traceability

Every entry in `bd_series` includes a `raw_line_id` (SHA-256[:16] of evidence coordinates) for full traceability back to the source text.

---

## Failure Modes

| Condition | Output |
|-----------|--------|
| No BD values found at all | `initial_bd_value = null`, `trigger_bd_gt4 = null`, notes: "DATA NOT AVAILABLE: no BD values found" |
| BD values found but none > 4 | `trigger_bd_gt4 = false`, `overall_compliant = null`, notes: "BD never exceeded 4; no monitoring protocol triggered" |
| Only 1 BD value after trigger | `overall_compliant = null`, notes: "Only one BD value after trigger; cannot assess cadence compliance" |
| No timestamps on BD values | `max_gap_hours = null`, `compliant = null` |

---

## Wiring

- **build_patient_features_v1.py**: Added as additive cross-day feature, keyed `base_deficit_monitoring_v1`.
- **report_features_qa.py**: QA block prints initial_bd_ts/value/source, trigger, compliance, window details.
- **_regression_phase1_v2.py**: Informational summary: initial_bd_value, trigger_bd_gt4, overall_compliant, max_gap_hours, violations_count.

---

## Design Constraints

- Deterministic only; fail-closed; no inference.
- Does NOT change v3/v4 renderer outputs.
- Does NOT touch NTDS/protocol engines.
- Uses structured labs already extracted when possible; does not invent timestamps.
