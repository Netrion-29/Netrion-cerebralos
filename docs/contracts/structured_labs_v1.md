# structured_labs_v1 — Schema Contract

**Module:** `cerebralos/features/structured_labs_v1.py`
**Feature key:** `structured_labs_v1` (under top-level `features` dict)
**Version:** v1
**Status:** Active

---

## Output Schema

```json
{
  "panels_by_day": {
    "2025-12-18": {
      "cbc":      "<panel_block, see below>",
      "bmp":      "<panel_block, see below>",
      "coag":     "<panel_block, see below>",
      "abg":      "<panel_block, see below>",
      "pf_ratio": "<pf_ratio_block, see below>"
    }
  },
  "summary": {
    "days_with_labs": 1,
    "panels_complete_count": 0,
    "pf_available_count": 0
  },
  "parse_warnings": [],
  "notes": []
}
```

### Panel Block

Each panel (cbc, bmp, coag, abg) has this structure:

```json
{
  "components": {
    "Hgb": {
      "status": "available",
      "first": 12.7,
      "last": 10.8,
      "delta": -1.9,
      "n_values": 2,
      "abnormal": true,
      "series": [
        {
          "observed_dt": "2025-12-18T06:00:00",
          "value": 12.7,
          "flags": [],
          "raw_line_id": "a1b2c3d4e5f67890"
        }
      ]
    },
    "Hct": {
      "status": "DATA NOT AVAILABLE"
    }
  },
  "complete": false,
  "available_count": 1,
  "total_count": 4
}
```

When `status` is `"DATA NOT AVAILABLE"`, only `{"status": "DATA NOT AVAILABLE"}`
is emitted (no first/last/series keys).

### Panel Components

| Panel | Canonical Keys |
|-------|---------------|
| CBC   | Hgb, Hct, WBC, Plt |
| BMP   | Na, K, Cl, CO2, BUN, Cr, Glucose |
| Coag  | PT, INR, PTT, Fibrinogen |
| ABG   | pH, pCO2, pO2, Base_Deficit, Lactate |

### P/F Ratio Block

```json
{
  "status": "available",
  "pf_ratio": 1446.7,
  "pao2": 434.0,
  "fio2": 0.30,
  "fio2_source": "FIO2",
  "raw_line_id": "b2c3d4e5f6789012"
}
```

When unavailable:
```json
{
  "status": "DATA NOT AVAILABLE",
  "reason": "fio2_not_available"
}
```

Valid `reason` values: `pO2_not_available`, `fio2_not_available`, `pO2_series_empty`.

**P/F ratio behavior:**
- Computed only when BOTH PaO2 and FiO2 are present as numeric lab
  components in the same day's series data.
- FiO2 is sourced from numeric lab rows matching FiO2 candidate keys
  (`FIO2`, `FiO2`, `FiO2 (%)`, `FiO2 (%) **`).
- Non-numeric FiO2 sources (e.g. qualitative "ROOM AIR" text) are NOT
  supported because the upstream lab pipeline filters rows where
  `value_num` is `None`.
- FiO2 values > 1.0 are treated as percentages and normalized to
  fractions (e.g. 30 → 0.30).
- Acceptable FiO2 range: 0.21–1.0 (after normalization).
- Uses the LAST PaO2 value from the day's ABG series.

---

## Fail-Closed Rules

1. **Range gates:** Each component has a hard min/max sanity range.
   Values outside the range are silently dropped.
2. **Non-numeric values:** Rows with `value_num is None` are skipped.
3. **Unknown components:** If no series key matches any candidate for a
   component, status is `"DATA NOT AVAILABLE"`.  If a candidate key
   exists but all its entries have null `value_num`, that candidate is
   skipped and later candidates are tried.
4. **FiO2 missing/ambiguous:** If no valid numeric FiO2 is found,
   P/F ratio is `"DATA NOT AVAILABLE"`.
5. **`__UNDATED__` days:** Skipped entirely.

---

## raw_line_id Requirements

Every structured output entry that represents an observed lab value
MUST include a `raw_line_id` field (SHA-256[:16] hex string):

- **Panel component series entries:** Each entry in
  `panels_by_day.<day>.<panel>.components.<comp>.series[]` must have
  `raw_line_id`.
- **P/F ratio:** When `status` is `"available"`,
  `panels_by_day.<day>.pf_ratio` must have `raw_line_id`.

The `raw_line_id` is computed deterministically via SHA-256[:16]:

- **Panel component series entries:** hash of
  `(component, observed_dt, value, source_line)` — where `component`
  is the canonical name (e.g. `"Hgb"`), and `source_line` is the
  integer line number from the raw patient file.
- **P/F ratio:** hash of
  `("P/F", pao2_observed_dt, pf_ratio_value, pao2_raw_line_id)` —
  where `pao2_raw_line_id` is the raw_line_id of the last PaO2 series
  entry used in the computation (not a numeric source_line).

These requirements are enforced by:
`cerebralos/validation/validate_patient_features_contract_v1.py`

---

## Raw Evidence Citations

| Patient File | Lines | Content |
|---|---|---|
| Anna_Dennis.txt | 144–147 | CBC in Recent Labs matrix (WBC/HGB/HCT/PLT) |
| Anna_Dennis.txt | 151–153 | BMP in Recent Labs matrix (CO2/BUN/CREATININE) |
| Timothy_Cowan.txt | 194–200 | BMP via tab-delimited table (Glucose/Cr/Na/K/Cl/Co2) |
| Timothy_Cowan.txt | 215 | Coag via tab-delimited (APTT) |
| Timothy_Cowan.txt | 219–224 | ABG via tab-delimited (pH/pCO2/pO2/Base Deficit) |
| Timothy_Cowan.txt | 266–267 | Coag via tab-delimited (PROTIME/INR) |
| Timothy_Nachtwey.txt | 173–179 | BMP via tab-delimited (Glucose/Cr/Na/K/Cl/Co2) |
| Timothy_Nachtwey.txt | 194 | Coag via tab-delimited (APTT) |
| Timothy_Nachtwey.txt | 204–209 | ABG via tab-delimited (pH/pCO2/pO2/Base Deficit) |
| Timothy_Nachtwey.txt | 251–252 | Coag via tab-delimited (PROTIME/INR) |
| Timothy_Nachtwey.txt | 1140 | FiO2 from flowsheet (FIO2 : 30 %) |
| William_Simmons.txt | 343–349 | CBC in newline-delimited Recent Labs matrix |
