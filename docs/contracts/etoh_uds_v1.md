# ETOH + UDS Extraction v1 — Contract

| Field   | Value                          |
|---------|--------------------------------|
| Module  | `cerebralos/features/etoh_uds_v1.py` |
| Version | v1                             |
| Date    | 2026-02-22                     |
| Roadmap | Step 5 — ETOH/UDS timestamp validation |

---

## Purpose

Deterministic extraction of:

1. **ETOH (Alcohol Serum)** — numeric or qualitative value with timestamp.
2. **UDS (Urine Drug Screen)** — 7-analyte panel with per-analyte POSITIVE/NEGATIVE.

Both results are **timestamp-validated** against the admission window
(`arrival_datetime` ≤ ts ≤ `discharge_datetime`).

---

## Output Key

`features.etoh_uds_v1` in `patient_features_v1.json`.

---

## Output Schema

```json
{
  "etoh_value": "<float | str | null>",
  "etoh_value_raw": "<raw string | null>",
  "etoh_ts": "<ISO datetime | null>",
  "etoh_ts_validation": "VALID | MISSING_TS | OUT_OF_WINDOW | null",
  "etoh_unit": "MG/DL | null",
  "etoh_source_rule_id": "lab_series_alcohol_serum | raw_text_alcohol_serum | null",
  "etoh_raw_line_id": "<sha256[:16] | null>",

  "uds_performed": "yes | no | DATA NOT AVAILABLE",
  "uds_panel": {
    "thc": "POSITIVE | NEGATIVE | null",
    "cocaine": "POSITIVE | NEGATIVE | null",
    "opiates": "POSITIVE | NEGATIVE | null",
    "benzodiazepines": "POSITIVE | NEGATIVE | null",
    "barbiturates": "POSITIVE | NEGATIVE | null",
    "amphetamines": "POSITIVE | NEGATIVE | null",
    "phencyclidine": "POSITIVE | NEGATIVE | null"
  },
  "uds_ts": "<ISO datetime | null>",
  "uds_ts_validation": "VALID | MISSING_TS | OUT_OF_WINDOW | null",
  "uds_source_rule_id": "lab_series_uds_panel | raw_text_drug_screen | null",
  "uds_raw_line_id": "<sha256[:16] | null>",

  "evidence": [ { "raw_line_id": "...", "source": "...", "ts": "...", "snippet": "..." } ],
  "notes": [ "..." ],
  "warnings": [ "..." ]
}
```

---

## Source Precedence

### ETOH
1. **Structured lab series** — `Alcohol Serum` component in `labs.series`
   (extracted by `labs_extract`). Rule: `lab_series_alcohol_serum`.
2. **Raw text fallback** — regex scan of LAB/ED_NOTE/PHYSICIAN_NOTE
   text for `Alcohol Serum` tabular rows. Rule: `raw_text_alcohol_serum`.

### UDS
1. **Structured lab series** — UDS analyte components (THC, Cocaine Metabolites,
   etc.) in `labs.series`. Rule: `lab_series_uds_panel`.
2. **Raw text fallback** — regex scan for `DRUG SCREEN MEDICAL` header
   and individual analyte lines. Rule: `raw_text_drug_screen`.

---

## Timestamp Validation

| Status | Meaning |
|--------|---------|
| `VALID` | Timestamp within admission window |
| `MISSING_TS` | No timestamp available; value preserved but flagged |
| `OUT_OF_WINDOW` | Timestamp before arrival or after discharge |

**Fail-closed**: timestamps are never inferred or fabricated.

---

## UDS Panel Analytes

| Canonical Key | Common Source Names |
|---------------|--------------------|
| `thc` | THC, Cannabinoid, Marijuana |
| `cocaine` | Cocaine Metabolites Urine |
| `opiates` | Opiate Screen, Urine |
| `benzodiazepines` | Benzodiazepine Screen, Urine |
| `barbiturates` | Barbiturate Screen, Urine |
| `amphetamines` | Amphetamine/Methamph Screen, Urine |
| `phencyclidine` | Phencyclidine Screen Urine |

---

## Constraints

- Deterministic, fail-closed.
- No LLM, no ML, no clinical inference.
- No invented timestamps.
- `raw_line_id` required on all evidence entries.
- All data under `features.etoh_uds_v1` — never at top level.
