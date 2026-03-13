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
    "<YYYY-MM-DD>": {
      "cbc":      { "<panel_block>" },
      "bmp":      { "<panel_block>" },
      "coag":     { "<panel_block>" },
      "abg":      { "<panel_block>" },
      "pf_ratio": { "<pf_ratio_block>" }
    }
  },
  "summary": {
    "days_with_labs":        "<int>",
    "panels_complete_count": "<int>",
    "pf_available_count":    "<int>"
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
    "<canonical_name>": {
      "status": "available | DATA NOT AVAILABLE",
      "first":     "<float>",
      "last":      "<float>",
      "delta":     "<float>",
      "n_values":  "<int>",
      "abnormal":  "<bool>",
      "series": [
        {
          "observed_dt": "<ISO datetime or null>",
          "value":       "<float>",
          "flags":       ["<string>"],
          "raw_line_id": "<hex16>"
        }
      ]
    }
  },
  "complete":        "<bool>",
  "available_count": "<int>",
  "total_count":     "<int>"
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
  "status": "available | DATA NOT AVAILABLE",
  "pf_ratio":    "<float>",
  "pao2":        "<float>",
  "fio2":        "<float, 0-1 fraction>",
  "fio2_source": "<string>",
  "raw_line_id": "<hex16>"
}
```

When unavailable:
```json
{
  "status": "DATA NOT AVAILABLE",
  "reason": "pO2_not_available | fio2_not_available | pO2_series_empty"
}
```

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
   component, status is `"DATA NOT AVAILABLE"`.
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

The `raw_line_id` is computed deterministically from
`(component, observed_dt, value, source_line)` via SHA-256[:16].

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
