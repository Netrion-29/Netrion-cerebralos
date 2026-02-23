# Hemodynamic Instability Pattern v1 — Contract

**Feature key**: `hemodynamic_instability_pattern_v1`  
**Location**: `features.hemodynamic_instability_pattern_v1`  
**Source module**: `cerebralos/features/hemodynamic_instability_pattern_v1.py`  
**Version**: v1  
**Status**: Active  

---

## §1 Purpose

Deterministic detection of hemodynamic instability patterns across all
hospital days, using canonical vitals records from `vitals_canonical_v1`.

This is a **protocol-enablement prerequisite** — downstream protocol
engines consume `pattern_present` and sub-pattern counts to evaluate
resuscitation adequacy and escalation criteria.

---

## §2 Input

| Source | Key | Required |
|--------|-----|----------|
| `features.vitals_canonical_v1.days` | Per-day canonical vitals records | Yes |

Fail-closed: if `vitals_canonical_v1.days` is empty/missing or has
zero records → `pattern_present = "DATA NOT AVAILABLE"`.

---

## §3 Thresholds (Locked)

| Pattern | Metric | Operator | Threshold | Rule ID |
|---------|--------|----------|-----------|---------|
| Hypotension | SBP | `<` | 90 mmHg | `hemo_sbp_lt90` |
| MAP low | MAP | `<` | 65 mmHg | `hemo_map_lt65` |
| Tachycardia | HR | `>` | 120 bpm | `hemo_hr_gt120` |

Any change to these thresholds requires a schema version bump.

---

## §4 Detection Rules

1. Each canonical vitals record is checked against all three thresholds.
2. A pattern is `detected = true` if **≥ 1** qualifying reading exists.
3. `pattern_present = "yes"` if **any** sub-pattern is detected.
4. `reading_count` and `days_affected` are provided for downstream
   severity thresholds (this module does not apply minimum-count gates).
5. Each qualifying reading becomes an evidence entry with `raw_line_id`.

---

## §5 Output Schema

```json
{
  "pattern_present": "yes" | "no" | "DATA NOT AVAILABLE",
  "hypotension_pattern": {
    "detected": true | false,
    "reading_count": 0,
    "days_affected": 0,
    "threshold": "SBP < 90",
    "source_rule_id": "hemo_sbp_lt90"
  },
  "map_low_pattern": {
    "detected": true | false,
    "reading_count": 0,
    "days_affected": 0,
    "threshold": "MAP < 65",
    "source_rule_id": "hemo_map_lt65"
  },
  "tachycardia_pattern": {
    "detected": true | false,
    "reading_count": 0,
    "days_affected": 0,
    "threshold": "HR > 120",
    "source_rule_id": "hemo_hr_gt120"
  },
  "patterns_detected": ["hypotension", "map_low", "tachycardia"],
  "total_abnormal_readings": 0,
  "total_vitals_readings": 0,
  "source_rule_id": "hemodynamic_instability_pattern_canonical_vitals",
  "evidence": [
    {
      "raw_line_id": "...",
      "ts": "..." | null,
      "day": "..." | null,
      "pattern": "hypotension" | "map_low" | "tachycardia",
      "value": 85.0,
      "threshold": "SBP < 90",
      "snippet": "SBP=85 (Hypotension: SBP < 90)"
    }
  ],
  "notes": [],
  "warnings": []
}
```

---

## §6 Evidence Traceability

Every evidence entry **must** have a `raw_line_id` sourced from the
canonical vitals record. Records without `raw_line_id` are skipped with
a warning.

---

## §7 Fail-Closed Behavior

| Condition | Result |
|-----------|--------|
| `vitals_canonical_v1.days` empty/missing | `pattern_present = "DATA NOT AVAILABLE"` |
| Days present but zero records | `pattern_present = "DATA NOT AVAILABLE"` |
| No thresholds triggered | `pattern_present = "no"` |

---

## §8 Constraints

- **Deterministic**: No LLM, no ML, no clinical inference.
- **Additive**: Does not modify `vitals_canonical_v1`, `shock_trigger_v1`,
  or any other feature module.
- **No renderer changes**: Output lives under `features` dict only.
- **Locked thresholds**: Threshold changes require version bump.
