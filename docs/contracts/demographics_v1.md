# Demographics v1 — Contract

| Field   | Value                  |
|---------|------------------------|
| Status  | DRAFT — implemented    |
| Phase   | Extractor coverage (protocol-enablement prerequisite) |
| Owner   | CerebralOS Phase 1.1  |
| Module  | `cerebralos/features/build_patient_features_v1.py` (assembly) |
| Fallback | `cerebralos/ingest/parse_patient_txt.py` (`_extract_sex_hpi_fallback`) |
| Output  | `features.demographics_v1` in `patient_features_v1.json` |
| Date    | 2026-03-12             |

---

## 1. Purpose

Deterministic patient demographics extraction from existing parsed patient data.
Sex and discharge disposition are protocol-enablement prerequisites —
several NTDS fields and clinical rules require structured demographic values.

Design principles:

- Deterministic, fail-closed.
- No inference. No LLM. No ML.
- Consumes evidence header SEX field (primary) or HPI/note text (fallback).
- Returns `null` when sex cannot be determined (fail-closed).

---

## 2. Output Schema

```json
{
  "sex": "Male",
  "discharge_disposition": "SNF"
}
```

| Field | Type              | Description                         |
|-------|-------------------|-------------------------------------|
| `sex` | `str \| null`    | Patient sex: `"Male"`, `"Female"`, or `null` if undetermined. |
| `discharge_disposition` | `str \| null` | Final discharge disposition from `patient_movement_v1.summary.discharge_disposition_final`, or `null` if unavailable. |

---

## 3. Allowed Values

| Value    | Meaning        |
|----------|----------------|
| `"Male"` | Patient is male |
| `"Female"` | Patient is female |
| `null`   | Sex not determinable from available data (fail-closed) |

No other sex values are emitted. Any raw value not matching `"Male"` or
`"Female"` is collapsed to `null`.

### 3.2 `discharge_disposition` Allowed Values

The value is passed through from `patient_movement_v1.summary.discharge_disposition_final`
as-is when it is a string. Returns `null` when unavailable or non-string.
Common values: `"Home"`, `"SNF"`, `"Rehab"`, `"LTAC"`, `"Expired"`, etc.

---

## 4. Extraction Hierarchy

### 4.1 Primary: Evidence Header SEX Field

| Parameter | Value |
|-----------|-------|
| Source    | `patient_evidence_v1.json → header.SEX` |
| Path      | `build_patient_features_v1.py` injects `meta.sex` from evidence |
| Rule      | Accept only exact `"Male"` or `"Female"`; else `null` |

### 4.2 Fallback: HPI Sex Pattern (Ingest-Time)

| Parameter | Value |
|-----------|-------|
| Source    | First 60 lines of raw patient text |
| Function  | `_extract_sex_hpi_fallback()` in `parse_patient_txt.py` |
| Pattern   | HPI-style age/sex phrase (e.g., "54-year-old male") |
| Returns   | `(sex, line_number)` where `line_number` is a 0-based index |
| Guardrail | Lines matching `_RE_SEX_NOISE` are skipped to avoid false positives |

---

## 5. Fail-Closed Behavior

- If the evidence header has no SEX field, falls back to HPI scan.
- If HPI scan finds no match within 60 lines, sex is `null`.
- If the raw value is anything other than `"Male"` or `"Female"`, sex is `null`.
- No guessing, no imputation, no defaults.

---

## 6. Validator Reference

- Key `demographics_v1` is registered in `KNOWN_FEATURE_KEYS` in
  `cerebralos/validation/validate_patient_features_contract_v1.py`.
- Contract tests in `tests/test_validate_patient_features_contract.py`
  verify the key is present and that `validate_contract()` accepts
  a minimal payload containing `demographics_v1`.
