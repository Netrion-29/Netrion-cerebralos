# INR Normalization v1 — Contract

**Module:** `cerebralos/features/inr_normalization_v1.py`
**Output key:** `inr_normalization_v1`
**Tier:** 1 Metric #4
**Reference:** Trauma Build-Forward Plan v1 §1.4

---

## Output Contract

```json
{
  "inr_normalization_v1": {
    "initial_inr_ts": "ISO" | null,
    "initial_inr_value": number | null,
    "initial_inr_source_lab": "INR" | null,

    "inr_series": [
      {
        "ts": "ISO",
        "inr_value": number,
        "source_lab": "INR",
        "raw_line_id": "...",
        "parse_warning": string | null,
        "ts_granularity": "datetime" | "day"
      }
    ],

    "inr_count": int,
    "parse_warnings": [string],
    "notes": [string]
  }
}
```

---

## Definitions

### INR Value
- Accept only components explicitly named "INR" (case-insensitive).
- Sanity range: 0.5 ≤ INR ≤ 20.0. Values outside this range are rejected with a parse_warning.
- Values are rounded to 2 decimal places.

### PT vs INR Disambiguation
- Components named "PROTIME", "PT", "Pro Time", "Prothrombin Time" are classified as PT seconds.
- PT seconds are NEVER treated as INR values, regardless of numeric range.
- Component name is the sole disambiguator (deterministic, fail-closed).
- Unrecognized component names are rejected (not guessed).

### Numeric Parsing
- Strip flags: `(H)`, `(L)`, `High`, `Low`, `Critical`, `Final`, `Abnormal`, `*`.
- Strip `<` and `>` qualifiers (e.g. `<0.5` → `0.5`, `>20` → `20`).
- If parsing fails, record a `parse_warning` and skip the value.

---

## Data Sources

1. **Primary:** Structured labs from `patient_features_v1.json` → `days[date].labs.series` (component "INR"). Entries have `ts_granularity = "datetime"`.
2. **Fallback:** `days[date].labs.daily` (component "INR") when no series data exists for that day. Fallback entries have:
   - `ts` = date only (e.g. `"2025-12-18"`), no invented time component. `ts_granularity = "day"`.
   - `raw_line_id` = synthetic hash of `"daily_fallback|<date>|<component>"` (not tied to a specific evidence line).

---

## Traceability

Every entry in `inr_series` includes a `raw_line_id` (SHA-256[:16]). For series-sourced entries this is derived from evidence coordinates; for daily-fallback entries the hash is synthetic (reduced traceability).

---

## Failure Modes

| Condition | Output |
|-----------|--------|
| No INR values found | `initial_inr_value = null`, notes: "DATA NOT AVAILABLE: no INR values found" |
| All INR values out of range | `initial_inr_value = null`, parse_warnings populated |
| Unparseable value_raw | Skipped with parse_warning |

---

## Wiring

- **build_patient_features_v1.py**: Added as additive cross-day feature, keyed `inr_normalization_v1`.
- **validate_patient_features_contract_v1.py**: `inr_normalization_v1` in KNOWN_FEATURE_KEYS; inr_series checked for raw_line_id.
- **report_features_qa.py**: QA block prints initial INR, count, and parse warnings.

---

## Design Constraints

- Deterministic only; fail-closed; no inference.
- Does NOT change v3/v4 renderer outputs.
- Does NOT touch NTDS/protocol engines.
- Uses structured labs already extracted; does not invent sub-day timestamp precision.
