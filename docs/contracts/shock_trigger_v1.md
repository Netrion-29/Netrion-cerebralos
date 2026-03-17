# Shock Trigger v1 — Contract

| Field   | Value                  |
|---------|------------------------|
| Status  | DRAFT — implemented    |
| Phase   | Tier 2 (Step 7, shock only) |
| Owner   | CerebralOS Phase 1.1  |
| Module  | `cerebralos/features/shock_trigger_v1.py` |
| Output  | `features.shock_trigger_v1` in `patient_features_v1.json` |
| Date    | 2026-02-22             |

---

## 1. Purpose

Deterministic shock trigger detection based on existing structured
outputs from prior pipeline steps (vitals canonical + base deficit
monitoring). This is the shock portion of Roadmap Step 7.

The neuro trigger (GCS < 9) is a separate PR — not included here.

Design principles:

- Deterministic, fail-closed.
- No inference. No LLM. No ML.
- Consumes only already-computed feature outputs (does not re-parse).
- Every evidence entry maps to a `raw_line_id` for audit traceability.

---

## 2. Trigger Rules (Locked v1)

### 2.1 Primary: SBP < 90 on Arrival

| Parameter         | Value   |
|-------------------|---------|
| Metric            | `sbp`   |
| Source             | `features.vitals_canonical_v1.arrival_vitals.sbp` |
| Operator          | `<`     |
| Threshold         | 90 mmHg |
| Rule ID           | `shock_sbp_lt90` |

### 2.2 Supporting: Base Deficit > 6

| Parameter         | Value   |
|-------------------|---------|
| Metric            | `initial_bd_value` |
| Source             | `features.base_deficit_monitoring_v1.initial_bd_value` |
| Operator          | `>`     |
| Threshold         | 6.0     |
| Rule ID           | `shock_bd_gt6` |

Arterial specimen is preferred. Venous or unknown specimen triggers a
warning but does not prevent evaluation.

### 2.3 Combined Logic

| SBP < 90 | BD > 6 | Result              | Rule ID                  | Shock Type           |
|-----------|--------|---------------------|--------------------------|----------------------|
| Yes       | Yes    | `shock_triggered=yes` | `shock_sbp_lt90+bd_gt6` | `hemorrhagic_likely` |
| Yes       | No     | `shock_triggered=yes` | `shock_sbp_lt90`         | `indeterminate`      |
| Yes       | N/A    | `shock_triggered=yes` | `shock_sbp_lt90`         | `indeterminate`      |
| No        | Yes    | `shock_triggered=yes` | `shock_bd_gt6`           | `indeterminate`      |
| No        | No     | `shock_triggered=no`  | `null`                   | `null`               |
| N/A       | *      | `DATA NOT AVAILABLE`  | `null`                   | `null`               |

N/A = arrival vitals not available or SBP is null.

### 2.4 Shock Index (Supplementary Metric)

| Parameter         | Value   |
|-------------------|---------|
| Metric            | `shock_index = hr / sbp` |
| Inputs            | `features.vitals_canonical_v1.arrival_vitals.hr`, `sbp` |
| Elevated threshold | `SI_ELEVATED_THRESHOLD = 0.7` |
| Critical threshold | `SI_CRITICAL_THRESHOLD = 1.0` |
| Classification    | `normal` (<0.7), `elevated` (0.7–<1.0), `critical` (≥1.0) |
| Rounding          | Classification uses unrounded SI; stored/displayed `shock_index` is rounded to 2 decimals |
| Trigger impact    | None (supplementary-only; does not change `shock_triggered`) |

---

## 3. Fail-Closed Behavior

- If `arrival_vitals.status` != `"selected"` → `shock_triggered = "DATA NOT AVAILABLE"`
- If `arrival_vitals.sbp` is null → `shock_triggered = "DATA NOT AVAILABLE"`
- If `base_deficit_monitoring_v1.initial_bd_value` is null → evaluate on
  SBP only (BD is supporting, not required)
- If `arrival_vitals.hr` is null/missing → `shock_index` and
  `shock_index_classification` are null (no inference)

---

## 4. Output Schema

| Key               | Type                     | Notes                                    |
|-------------------|--------------------------|------------------------------------------|
| `shock_triggered` | `"yes"` \| `"no"` \| `"DATA NOT AVAILABLE"` | Primary output |
| `trigger_rule_id` | string \| null           | Rule that fired (see §2.3)               |
| `trigger_ts`      | string (ISO) \| null     | Timestamp of triggering observation       |
| `trigger_vitals`  | object \| null           | See §4.1                                 |
| `shock_type`      | `"hemorrhagic_likely"` \| `"indeterminate"` \| null | Classification |
| `evidence`        | list[object]             | See §4.2                                 |
| `notes`           | list[string]             | Contextual notes                         |
| `warnings`        | list[string]             | Validation warnings                      |

### 4.1 trigger_vitals

| Key           | Type           | Source                |
|---------------|----------------|-----------------------|
| `sbp`         | float \| null  | `arrival_vitals.sbp`  |
| `hr`          | float \| null  | `arrival_vitals.hr`   |
| `map`         | float \| null  | `arrival_vitals.map`  |
| `shock_index` | float \| null  | computed `hr / sbp` (2 decimals) |
| `shock_index_classification` | `"normal"` \| `"elevated"` \| `"critical"` \| null | computed from unrounded SI |
| `bd_value`    | float \| null  | `initial_bd_value`    |
| `bd_specimen` | string \| null | `initial_bd_source`   |

### 4.2 evidence[]

Each entry:

| Key           | Type   | Required |
|---------------|--------|----------|
| `raw_line_id` | string | Yes      |
| `source`      | string | Yes — `"arrival_vitals"` or `"base_deficit_monitoring"` |
| `ts`          | string \| null | Yes |
| `snippet`     | string | Yes      |
| `role`        | string | Yes — `"primary"` or `"supporting"` |

---

## 5. Integration

### 5.1 Builder

Called in `build_patient_features_v1.py` **after** the features dict
is assembled (because it consumes arrival_vitals and
base_deficit_monitoring outputs that are already in the dict).

### 5.2 Validator

`shock_trigger_v1` is in `KNOWN_FEATURE_KEYS` in
`cerebralos/validation/validate_patient_features_contract_v1.py`.
Evidence `raw_line_id` is checked by the general evidence walker.

### 5.3 QA Report

Section in `cerebralos/validation/report_features_qa.py` displays:
- `shock_triggered`, `trigger_rule_id`, `trigger_ts`, `shock_type`
- `trigger_vitals` summary
- Evidence list
- Warnings and notes

---

## 6. Versioning and Change Control

- This is **v1** of the shock trigger contract.
- Any changes to thresholds, trigger logic, or output schema require:
  1. A version bump to this contract document.
  2. Corresponding code changes in the implementation module.
  3. Updates to validators and QA reporter.
  4. All in the same PR (AGENTS.md §4).
- The contract file path is:
  `docs/contracts/shock_trigger_v1.md`

---

End of contract.
