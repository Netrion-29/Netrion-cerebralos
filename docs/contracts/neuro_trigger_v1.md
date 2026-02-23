# Neuro Emergency Trigger v1 — Contract

| Field   | Value                  |
|---------|------------------------|
| Status  | DRAFT — implemented    |
| Phase   | Tier 2 (Step 7, neuro only) |
| Owner   | CerebralOS Phase 1.1  |
| Module  | `cerebralos/features/neuro_trigger_v1.py` |
| Output  | `features.neuro_trigger_v1` in `patient_features_v1.json` |
| Date    | 2026-02-22             |

---

## 1. Purpose

Deterministic neuro emergency trigger detection based on existing
structured GCS outputs from the per-day `gcs_daily` extraction
(arrival GCS priority logic). This is the neuro portion of Roadmap
Step 7.

The shock trigger (SBP < 90 + BD > 6) is a separate, already-merged PR.

Design principles:

- Deterministic, fail-closed.
- No inference. No LLM. No ML.
- Consumes only already-computed per-day `gcs_daily` feature outputs.
- Every evidence entry maps to a `raw_line_id` for audit traceability.

---

## 2. Trigger Rules (Locked v1)

### 2.1 Primary: Arrival GCS < 9

| Parameter         | Value   |
|-------------------|---------|
| Metric            | `arrival_gcs_value` |
| Source             | `days[arrival_day].gcs_daily.arrival_gcs_value` |
| Operator          | `<`     |
| Threshold         | 9       |
| Rule ID           | `neuro_gcs_lt9` |

The arrival GCS is selected by `gcs_daily`'s existing priority logic:

1. **Trauma H&P Primary Survey — "D" (Disability) in ABCDE** (hard priority)
2. ED NOTE fallback GCS within 0–120 min of arrival (if Trauma H&P GCS missing)
3. DATA NOT AVAILABLE

### 2.2 Decision Table

| Arrival GCS | Result                | Rule ID          |
|-------------|------------------------|------------------|
| < 9         | `neuro_triggered=yes`  | `neuro_gcs_lt9`  |
| >= 9        | `neuro_triggered=no`   | `null`           |
| null / N/A  | `DATA NOT AVAILABLE`   | `null`           |

---

## 3. Fail-Closed Behavior

- If `gcs_daily.arrival_gcs_value` is null → `neuro_triggered = "DATA NOT AVAILABLE"`
- If arrival day cannot be determined → `neuro_triggered = "DATA NOT AVAILABLE"`
- If no feature days present → `neuro_triggered = "DATA NOT AVAILABLE"`
- If arrival GCS is not numeric → `neuro_triggered = "DATA NOT AVAILABLE"`

---

## 4. Output Schema

| Key               | Type                     | Notes                                    |
|-------------------|--------------------------|------------------------------------------|
| `neuro_triggered` | `"yes"` \| `"no"` \| `"DATA NOT AVAILABLE"` | Primary output |
| `trigger_rule_id` | string \| null           | `"neuro_gcs_lt9"` or null               |
| `trigger_ts`      | string (ISO) \| null     | Timestamp of triggering GCS observation  |
| `trigger_inputs`  | object \| null           | See §4.1                                 |
| `evidence`        | list[object]             | See §4.2                                 |
| `notes`           | list[string]             | Contextual notes                         |
| `warnings`        | list[string]             | Validation warnings                      |

### 4.1 trigger_inputs

| Key                        | Type           | Source                       |
|----------------------------|----------------|------------------------------|
| `arrival_gcs_value`        | int \| null    | `gcs_daily.arrival_gcs_value` |
| `arrival_gcs_source`       | string \| null | `gcs_daily.arrival_gcs_source` |
| `arrival_gcs_source_rule_id` | string \| null | `gcs_daily.arrival_gcs_source_rule_id` |
| `arrival_gcs_intubated`    | bool \| null   | From arrival reading's intubated flag |

### 4.2 evidence[]

Each entry:

| Key           | Type   | Required |
|---------------|--------|----------|
| `raw_line_id` | string | Yes — SHA-256[:16] derived from source + ts + line_preview |
| `source`      | string | Yes — `"gcs_daily"` |
| `ts`          | string \| null | Yes |
| `snippet`     | string | Yes      |
| `role`        | string | Yes — `"primary"` |

---

## 5. Integration

### 5.1 Builder

Called in `build_patient_features_v1.py` after the features dict is
assembled. Receives `feature_days` (per-day blocks) and `arrival_ts`.

### 5.2 Validator

`neuro_trigger_v1` is in `KNOWN_FEATURE_KEYS` in
`cerebralos/validation/validate_patient_features_contract_v1.py`.
Evidence `raw_line_id` is checked by a dedicated section in the
evidence walker.

### 5.3 QA Report

Section in `cerebralos/validation/report_features_qa.py` displays:
- `neuro_triggered`, `trigger_rule_id`, `trigger_ts`
- `trigger_inputs` summary (GCS value, source, intubated status)
- Evidence list
- Warnings and notes

---

## 6. Versioning and Change Control

- This is **v1** of the neuro trigger contract.
- Any changes to the threshold, trigger logic, or output schema require:
  1. A version bump to this contract document.
  2. Corresponding code changes in the implementation module.
  3. Updates to validators and QA reporter.
  4. All in the same PR (AGENTS.md §4).
- The contract file path is:
  `docs/contracts/neuro_trigger_v1.md`

---

End of contract.
