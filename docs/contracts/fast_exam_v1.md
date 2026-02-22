# FAST Exam Extraction v1 — Contract

| Field   | Value               |
|---------|---------------------|
| Module  | `cerebralos/features/fast_exam_v1.py` |
| Version | v1                  |
| Date    | 2026-02-22          |
| Status  | Active              |

---

## Purpose

Extract FAST (Focused Assessment with Sonography for Trauma) exam
status from the TRAUMA_HP Primary Survey section.  Produces a
deterministic, fail-closed patient-level feature.

## Source Precedence

| Priority | Source                              | Rule ID                                  |
|----------|-------------------------------------|------------------------------------------|
| 1        | TRAUMA_HP → Primary Survey → FAST line | `trauma_hp_primary_survey`              |
| —        | No FAST line in Primary Survey       | `trauma_hp_primary_survey_no_fast_line` |
| —        | No Primary Survey in TRAUMA_HP       | `no_trauma_hp_primary_survey`           |
| —        | No TRAUMA_HP item at all             | `no_trauma_hp`                          |

Narrative mentions like "Fast exam is negative" in ED notes are **not**
extracted.  They are not structured enough for deterministic extraction
without clinical inference.

## Recognised Patterns

All patterns appear within the Primary Survey section of TRAUMA_HP,
as a line matching `FAST: <value>`:

| Raw Text                               | `fast_performed` | `fast_result`   |
|----------------------------------------|------------------|-----------------|
| `FAST: No`                             | `no`             | `null`          |
| `FAST: Not indicated`                  | `no`             | `null`          |
| `FAST: No not indicated`               | `no`             | `null`          |
| `FAST: Yes`                            | `yes`            | `indeterminate` |
| `FAST: Yes - negative`                 | `yes`            | `negative`      |
| `FAST: Yes - positive`                 | `yes`            | `positive`      |
| `FAST: Yes (per <name>) - negative`    | `yes`            | `negative`      |
| `FAST: Yes (per <name>) - positive`    | `yes`            | `positive`      |

## Output Schema

Lives under `features.fast_exam_v1` in `patient_features_v1.json`.

```json
{
  "fast_performed": "yes | no | DATA NOT AVAILABLE",
  "fast_result": "positive | negative | indeterminate | null",
  "fast_ts": "ISO datetime string | null",
  "fast_source": "TRAUMA_HP:Primary_Survey:FAST | null",
  "fast_source_rule_id": "trauma_hp_primary_survey | trauma_hp_primary_survey_no_fast_line | no_trauma_hp_primary_survey | no_trauma_hp | null",
  "fast_raw_text": "exact text after 'FAST:' | null",
  "raw_line_id": "sha256 hex string | null",
  "evidence": [
    {
      "raw_line_id": "sha256 hex",
      "source": "TRAUMA_HP:Primary_Survey:FAST",
      "ts": "ISO datetime | null",
      "snippet": "FAST: <raw text>"
    }
  ],
  "notes": ["string"],
  "warnings": ["string"]
}
```

## Fail-Closed Behaviour

- If no TRAUMA_HP exists → `fast_performed = "DATA NOT AVAILABLE"`
- If TRAUMA_HP exists but no Primary Survey section → same
- If Primary Survey exists but no FAST line → same, plus warning
  `fast_missing_in_primary_survey`
- Unrecognised FAST value text → `fast_performed = "yes"`,
  `fast_result = "indeterminate"`

## Evidence Traceability

`raw_line_id` is computed as `sha256("TRAUMA_HP|<source_id>|<line_text>")`.
Present on both the top-level result and each evidence entry.

## Design Constraints

- Deterministic, fail-closed
- No LLM, no ML, no clinical inference
- No narrative fallback (ED notes, flowsheets, etc.)
- Single source: TRAUMA_HP Primary Survey only
