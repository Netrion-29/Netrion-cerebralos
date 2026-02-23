# Radiology Findings v1 — Feature Contract

| Field   | Value                     |
|---------|---------------------------|
| Date    | 2026-02-22                |
| Version | v1                        |
| Owner   | Sarah                     |
| Status  | Active                    |

---

## Purpose

Deterministic extraction of structured, protocol-relevant radiology
findings from imaging reports (RADIOLOGY items) and clinical notes
(TRAUMA_HP, ED_NOTE, PHYSICIAN_NOTE).

This is an **extractor coverage** feature — it produces structured
labels from imaging text to enable downstream protocol compliance
checks.  It does **not** perform clinical inference, severity scoring,
or protocol logic.

## Output Key

`features.radiology_findings_v1`

## Output Schema

```json
{
  "findings_present": "yes" | "no" | "DATA NOT AVAILABLE",
  "findings_labels": ["pneumothorax", "rib_fracture", ...],

  "pneumothorax": {
    "present": true,
    "subtype": "tension" | "open" | "occult" | "simple" | "small" | "large" | "moderate" | null,
    "raw_line_id": "<sha256-16>"
  } | null,

  "hemothorax": {
    "present": true,
    "qualifier": "massive" | "retained" | "large" | "small" | "moderate" | null,
    "raw_line_id": "<sha256-16>"
  } | null,

  "rib_fracture": {
    "present": true,
    "count": <int> | null,
    "rib_numbers": ["1", "3", "4", ...] | null,
    "raw_line_id": "<sha256-16>"
  } | null,

  "flail_chest": {
    "present": true,
    "raw_line_id": "<sha256-16>"
  } | null,

  "solid_organ_injuries": [
    {
      "organ": "liver" | "spleen" | "kidney",
      "present": true,
      "grade": "1" | "2" | "3" | "4" | "5" | null,
      "raw_line_id": "<sha256-16>"
    }
  ],

  "intracranial_hemorrhage": [
    {
      "subtype": "edh" | "sdh" | "sah" | "ich" | "ivh" | "unspecified",
      "present": true,
      "raw_line_id": "<sha256-16>"
    }
  ],

  "pelvic_fracture": {
    "present": true,
    "raw_line_id": "<sha256-16>"
  } | null,

  "spinal_fracture": {
    "present": true,
    "level": "S4" | "L1" | "T5-T6" | null,
    "raw_line_id": "<sha256-16>"
  } | null,

  "source_rule_id": "radiology_impression" | "radiology_findings" | "trauma_hp_impression" | ... | "no_qualifying_source" | "no_findings_matched",
  "evidence": [
    {
      "raw_line_id": "<sha256-16>",
      "source": "RADIOLOGY" | "TRAUMA_HP" | ...,
      "ts": "<ISO datetime>" | null,
      "snippet": "<text excerpt>",
      "role": "finding",
      "label": "pneumothorax" | "rib_fracture" | ...
    }
  ],
  "notes": ["..."],
  "warnings": ["..."]
}
```

## Source Priority

1. **RADIOLOGY** items — IMPRESSION section preferred, FINDINGS fallback
2. **TRAUMA_HP** — impression/assessment text
3. **ED_NOTE** — impression/assessment text
4. **PHYSICIAN_NOTE** — impression/assessment text

All qualifying items are scanned.  Findings are merged across all items
(first occurrence of each category wins for scalar categories; list
categories like solid_organ_injuries and intracranial_hemorrhage
merge by organ/subtype dedup).

## Finding Categories

| Category | Subtypes / Fields | Fail-closed rule |
|---|---|---|
| Pneumothorax | subtype: tension/open/occult/simple/small/large/moderate | subtype=null if not explicitly stated |
| Hemothorax | qualifier: massive/retained/large/small/moderate | qualifier=null if not explicit |
| Rib fracture | count, rib_numbers | count/numbers=null if not deterministic |
| Flail chest | presence only | — |
| Solid organ (liver/spleen/kidney) | grade (1-5) | grade=null if not explicit |
| Intracranial hemorrhage | subtype: edh/sdh/sah/ich/ivh/unspecified | only subtype labels explicitly documented |
| Pelvic fracture | presence | includes hip fracture |
| Spinal fracture | level (C1-S5 range) | level=null if not explicit |

## Negation Handling

Findings preceded by negation phrases ("No pneumothorax", "without
evidence of hemothorax", "negative for intracranial hemorrhage") are
**excluded**.

## Chronic/Incidental Exclusion

Findings preceded by chronic qualifiers ("chronic", "stable", "old",
"remote", "healed", "prior", "previous", "known", "unchanged",
"resolved") are **excluded** to avoid overmatching non-acute findings.

## Evidence Traceability

Every evidence entry includes `raw_line_id` (16-char SHA-256 prefix)
computed from `source_type|source_id|line_text`.

## Validator

Registered in `KNOWN_FEATURE_KEYS` in
`cerebralos/validation/validate_patient_features_contract_v1.py`.

Evidence `raw_line_id` presence is enforced by the contract validator.

## QA Visibility

Displayed in `cerebralos/validation/report_features_qa.py` under
"RADIOLOGY FINDINGS v1 QA" section.

## Disallowed

- No clinical inference of severity/grade from weak phrasing
- No modification of NTDS/protocol engines
- No renderer changes
- No mechanism extraction (separate feature)
