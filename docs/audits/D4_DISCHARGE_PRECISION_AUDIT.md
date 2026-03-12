# D4 — DISCHARGE Precision Audit

| Field | Value |
|-------|-------|
| Date | 2026-03-11 |
| Scope | 14 NTDS events using DISCHARGE as `allowed_sources` |
| Cohort | 39 patients |
| Baseline | `64f5478` (main, after PR #181) |
| Outcome | **No false positives found. No rule changes needed.** |

---

## Events Audited

The following 14 NTDS events include `DISCHARGE` in their `allowed_sources`:

| # | Event | Rule File |
|---|-------|-----------|
| E01 | Acute Kidney Injury (AKI) | `01_aki.json` |
| E02 | ARDS | `02_ards.json` |
| E06 | CLABSI | `06_clabsi.json` |
| E07 | Deep SSI | `07_deep_ssi.json` |
| E08 | DVT | `08_dvt.json` |
| E10 | Myocardial Infarction | `10_mi.json` |
| E11 | Organ-Space SSI | `11_organ_space_ssi.json` |
| E13 | Pressure Ulcer | `13_pressure_ulcer.json` |
| E14 | Pulmonary Embolism | `14_pe.json` |
| E15 | Severe Sepsis | `15_severe_sepsis.json` |
| E16 | Stroke/CVA | `16_stroke_cva.json` |
| E17 | Superficial SSI | `17_superficial_ssi.json` |
| E18 | Unplanned ICU Admission | `18_unplanned_icu_admission.json` |
| E20 | Unplanned Return to OR | `20_or_return.json` |

---

## Findings

### YES Outcomes with DISCHARGE Gate Evidence

| Patient | Event | Gate | Source | Classification | Evidence Text |
|---------|-------|------|--------|----------------|---------------|
| Ronald_Bittner | E13 | `pressure_ulcer_dx` | DISCHARGE | **TP** | "Wound 01/12/26 Flank Right;Upper Medical device related deep tissue pressure injury" |

**Analysis:** This is a genuine pressure ulcer documented in the discharge wound log. DISCHARGE is the correct source for wound care documentation. No false positive.

### DISCHARGE-Only Passed Gates

Only 1 gate passed solely on DISCHARGE evidence (Ronald_Bittner E13, classified as TP above). All other YES outcomes across these 14 events rely on non-DISCHARGE evidence (IMAGING, OPERATIVE_NOTE, PROCEDURE, etc.).

### Near-Miss DISCHARGE Evidence (NO Outcomes)

14 near-miss items were found — all correctly in NO outcomes:

| Patient | Event | Text | Classification |
|---------|-------|------|----------------|
| Anna_Dennis | E01 | "Suspected CKD stage 2" | **Correct NO** — CKD is chronic, not acute injury |
| Gary_Linder | E01 | "PMH of AKI, COPD, GERD..." | **Correct NO** — PMH mention, not active AKI |
| Linda_Hufford | E10, E15 | "Subarachnoid hemorrhage (HCC)" | **Correct NO** — HCC code, hemorrhage not MI/sepsis |
| Margaret_Rudd | E10, E15 | "Alzheimer dementia (HCC)" | **Correct NO** — HCC code, not cardiovascular/sepsis |
| Mary_King | E16 | "history of stroke" / "PMH... CVA" | **Correct NO** — prior stroke history, not new event |
| Timothy_Nachtwey | E10, E15 | "Intraparenchymal hemorrhage (HCC)" | **Correct NO** — brain hemorrhage, not MI/sepsis |
| Wilma_Yates | E10, E15 | "T12 burst fracture (HCC)" | **Correct NO** — spinal fracture, not MI/sepsis |

All near-miss items represent correct system behavior: PMH mentions and HCC diagnostic codes in DISCHARGE summaries are correctly matched as near-miss evidence but do not pass the diagnostic gates.

### Evidence Source Distribution

Across all 14 DISCHARGE-eligible events and 39 patients:

| Source Type | Evidence Count |
|-------------|---------------|
| IMAGING | 44 |
| PROCEDURE | 29 |
| OPERATIVE_NOTE | 18 |
| LAB | 13 |
| PHYSICIAN_NOTE | 11 |
| DISCHARGE | 1 |

DISCHARGE contributes only 1 of 116 total evidence items (0.9%), reflecting the parser hardening work in N5–N7 (PRs #145, #147, #149) which eliminated false DISCHARGE source triggers.

---

## Conclusion

The DISCHARGE source type is working correctly across all 14 events:

1. **0 false positives** — the only YES outcome using DISCHARGE evidence is a true positive
2. **14 near-miss items** are all correctly classified as NO outcomes
3. **Parser hardening** (N5–N7) has effectively reduced DISCHARGE noise
4. **No rule changes needed** — no new exclusion patterns or gate modifications required

---

## Deferred Observations

- Gary_Linder E01 AKI remains a known residual (PMH contamination). Tracked in backlog item #6 (5 AKI UTD residuals).
- Mary_King E16 Stroke near-miss is a regression-safe observation — PMH "history of stroke" correctly excluded by existing gate logic.
