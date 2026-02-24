# pmh_social_allergies_v1 — Contract

**Feature key:** `pmh_social_allergies_v1`
**Source rule id:** `pmh_social_allergies_v1`
**Version:** 1
**Status:** Active

## Purpose

Deterministic structured extraction of **Past Medical History (PMH)**, **Allergies**,
and **Social History** from trauma-relevant chart note sections.  Supports the
Daily Notes v5 patient-summary context header.

## Input

| Parameter       | Type   | Description                          |
|-----------------|--------|--------------------------------------|
| `pat_features`  | dict   | Must contain `pat_features["days"]`  |
| `days_data`     | dict   | Full `days_json` with timeline items |

## Scanned note types

`TRAUMA_HP`, `PHYSICIAN_NOTE`, `ED_NOTE`, `CONSULT_NOTE`, `NURSING_NOTE`

## Section headers matched

| Section   | Regex anchors                                            |
|-----------|----------------------------------------------------------|
| PMH       | `PMH:`, `PAST MEDICAL HISTORY:`, `Past Medical History:` |
| Allergies | `Allergies:`, `ALLERGIES`                                |
| Social Hx | `Social Hx:`, `SOCIAL HISTORY:`, `Social History`       |

## Output shape

```jsonc
{
  "pmh_items": [
    {
      "label": "Hypertension",
      "date": "3/16/2018",          // "" if absent
      "sub_comment": "on lisinopril",  // "" if absent
      "raw_line_id": "...:42"
    }
  ],
  "pmh_count": 1,
  "allergies": [
    {
      "allergen": "Ciprofloxacin",
      "reaction": "YEAST INFECTION",  // "" if none captured
      "raw_line_id": "...:55"
    }
  ],
  "allergy_count": 1,
  "allergy_status": "NKA" | "PRESENT" | "DATA NOT AVAILABLE",
  "social_history": {
    "smoking_status": "Never",
    "smokeless_tobacco": "Never",
    "vaping_status": "Never Used",
    "alcohol_use": "No",
    "drug_use": {
      "status": "Yes",
      "types": "Marijuana",
      "comment": "5x monthly 06/2022"
    },
    "marital_status": "Married"
  },
  "source_rule_id": "pmh_social_allergies_v1",
  "evidence": [
    {
      "role": "pmh_section" | "allergies_section" | "social_section",
      "snippet": "<first 120 chars of section text>",
      "raw_line_id": "...:10",
      "source_type": "TRAUMA_HP",
      "day": "2024-09-02"
    }
  ],
  "notes": [],
  "warnings": []
}
```

## Determinism guarantees

* **Fail-closed:** Empty output dict with `warnings` if no sections found.
* **No clinical inference:** Values are extracted verbatim; no mapping,
  normalisation, or lookup beyond de-duplication.
* **Deduplication:** PMH by normalised label (lowercase, strip `(HCC)`,
  trailing dates); allergies by allergen name (case-insensitive);
  evidence by `raw_line_id`.
* **First-seen-wins:** Social history fields take the first non-empty
  value across all scanned notes.
* **raw_line_id:** Every `pmh_items[]`, `allergies[]`, and `evidence[]`
  entry carries a `raw_line_id`.

## Validation

Checked by `validate_patient_features_contract_v1.py`:

* `pmh_social_allergies_v1` present in `KNOWN_FEATURE_KEYS`.
* `evidence[]`, `pmh_items[]`, and `allergies[]` entries must have
  `raw_line_id`.

## QA visibility

Rendered in `report_features_qa.py` under **PMH / SOCIAL / ALLERGIES v1 QA**.

## Gate patients

Standard gate: `Anna_Dennis`, `William_Simmons`, `Timothy_Cowan`,
`Timothy_Nachtwey`.

## Changelog

| Date       | Change                |
|------------|-----------------------|
| 2025-07-18 | v1 — initial release  |
