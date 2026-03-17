# Protocol Data Coverage Mapping — v1

| Field       | Value |
|-------------|-------|
| Source       | First-pass analysis of CerebralOS extraction pipeline vs. Protocol Data Element Master v1 |
| Generated   | 2026-03-12 |
| Roadmap item | #15 — Protocol Data Coverage Mapping |
| Baseline doc | `docs/audits/PROTOCOL_DATA_ELEMENT_MASTER_v1.md` (20 categories, 230 elements, 51 protocols) |
| Coverage CSV | `docs/audits/PROTOCOL_DATA_ELEMENT_MASTER_v1_with_coverage.csv` |

> **Purpose:** Map every protocol data element from the master list to its
> current CerebralOS extraction status. Identifies gaps, documents repo
> evidence for each claim, and proposes scoped next-PR slices.

---

## Method

Coverage was assessed by:

1. **Master list baseline.** Used the 230 data elements defined in
   `PROTOCOL_DATA_ELEMENT_MASTER_v1.md` across 20 clinical categories
   (derived from 51 Deaconess Trauma Center protocol PDFs).

2. **Codebase verification.** For each element, identified the responsible
   extraction source: feature module (`cerebralos/features/*.py`), mapper key
   (`rules/mappers/epic_deaconess_mapper_v1.json`), NTDS rule file
   (`rules/ntds/logic/2026/*.json`), LDA engine
   (`cerebralos/features/lda_events_v1.py`), or feature rule config
   (`rules/features/*.json`).

3. **Status assignment.** Each element received one of four statuses:
   - **EXTRACTED** — a dedicated feature module, mapper key, or rule fully
     captures the element with structured output.
   - **PARTIAL** — extraction infrastructure exists (feature module, mapper
     pattern) but output is incomplete (e.g., detects presence without
     structured values, missing subfields, or lacks timing/dosing granularity).
   - **MISSING** — no extraction logic exists for this element.
   - **N/A** — element is registrar-owned, operational, or not present in the
     Epic `.txt` export and therefore out of scope for text extraction.

4. **Verification.** Every claimed feature module file was confirmed to exist
   in `cerebralos/features/`. Every mapper key was confirmed in the mapper
   JSON. All 21 NTDS event rule files were confirmed in `rules/ntds/logic/2026/`.

---

## Summary

| Status | Count | Pct |
|--------|------:|----:|
| EXTRACTED | 60 | 26.1% |
| PARTIAL | 57 | 24.8% |
| MISSING | 97 | 42.2% |
| N/A | 16 | 7.0% |
| **Total** | **230** | 100% |

**Actionable elements** (excluding N/A): 214
**Actionable coverage** (EXTRACTED + PARTIAL): 117 / 214 = **54.7%**
**Fully extracted**: 60 / 214 = **28.0%**

---

## Coverage Matrix by Category

| # | Category | EXTRACTED | PARTIAL | MISSING | N/A | Total | Coverage |
|---|----------|----------:|--------:|--------:|----:|------:|---------:|
| 1 | Demographics / Patient Identification | 4 | 1 | 2 | 1 | 8 | 71% |
| 2 | Prehospital / EMS | 1 | 0 | 6 | 1 | 8 | 14% |
| 3 | Injury Mechanism / Classification | 2 | 0 | 8 | 2 | 12 | 20% |
| 4 | Emergency Department Assessment | 3 | 1 | 5 | 0 | 9 | 44% |
| 5 | Vital Signs / Hemodynamic Monitoring | 5 | 3 | 2 | 0 | 10 | 80% |
| 6 | Neurologic Assessment | 1 | 7 | 1 | 0 | 9 | 89% |
| 7 | Laboratory / Diagnostics | 4 | 7 | 5 | 0 | 16 | 69% |
| 8 | Imaging / Radiology | 1 | 8 | 3 | 0 | 12 | 75% |
| 9 | Airway / Respiratory | 0 | 3 | 6 | 0 | 9 | 33% |
| 10 | Resuscitation / Blood Products | 0 | 0 | 12 | 0 | 12 | 0% |
| 11 | Operative / Procedural | 2 | 5 | 5 | 0 | 12 | 58% |
| 12 | Pharmacologic Interventions | 2 | 2 | 5 | 0 | 9 | 44% |
| 13 | Device / Line Management | 0 | 6 | 6 | 0 | 12 | 50% |
| 14 | Infection Prevention / HAI Monitoring | 7 | 2 | 2 | 0 | 11 | 82% |
| 15 | Prophylaxis (DVT / GI / Hypothermia) | 2 | 2 | 3 | 0 | 7 | 57% |
| 16 | Screening / Behavioral Health | 4 | 3 | 4 | 0 | 11 | 64% |
| 17a | Special Populations — Geriatric | 0 | 2 | 5 | 0 | 7 | 29% |
| 17b | Special Populations — Pediatric | 0 | 0 | 7 | 0 | 7 | 0% |
| 17c | Special Populations — Obstetric | 0 | 0 | 6 | 0 | 6 | 0% |
| 18 | Disposition / Discharge Planning | 1 | 4 | 4 | 2 | 11 | 56% |
| 19 | Complications / NTDS Events | 20 | 1 | 0 | 0 | 21 | 100% |
| 20 | Operational / Call Panel | 1 | 0 | 0 | 10 | 11 | 100% |

> **Coverage** = (EXTRACTED + PARTIAL) / (Total − N/A). Categories with 0%
> have no extraction infrastructure at all today.

---

## Detailed Evidence: EXTRACTED Elements (60)

| Category | Element | Repo Evidence |
|----------|---------|---------------|
| Demographics | Patient name / MRN | `patient_id` parsed from PATIENT_ID header line in ingestion pipeline |
| Demographics | Date of birth / Age | `cerebralos/features/age_extraction_v1.py` |
| Demographics | Admission date/time | ARRIVAL_TIME header parsing; `cerebralos/features/adt_transfer_timeline_v1.py` |
| Demographics | Trauma activation category | `cerebralos/features/category_activation_v1.py`; `rules/features/category_activation_v1.json` |
| Prehospital | Mechanism of injury narrative | `cerebralos/features/mechanism_region_v1.py` |
| Injury Mech. | Blunt vs. penetrating classification | `cerebralos/features/mechanism_region_v1.py` — classifies blunt/penetrating |
| Injury Mech. | Body region(s) involved | `cerebralos/features/mechanism_region_v1.py` — extracts body regions |
| ED Assessment | ED arrival date/time | ARRIVAL_TIME header; `cerebralos/features/adt_transfer_timeline_v1.py` |
| ED Assessment | Triage category (Cat I / Cat II / Consult) | `cerebralos/features/category_activation_v1.py` |
| ED Assessment | FAST exam (positive/negative/indeterminate) | `cerebralos/features/fast_exam_v1.py` |
| Vital Signs | Blood pressure (systolic/diastolic/MAP) | `cerebralos/features/vitals_canonical_v1.py`; `rules/features/vitals_patterns_v1.json` |
| Vital Signs | Heart rate | `cerebralos/features/vitals_canonical_v1.py` |
| Vital Signs | Respiratory rate | `cerebralos/features/vitals_canonical_v1.py` |
| Vital Signs | SpO2 (pulse oximetry) | `cerebralos/features/vitals_canonical_v1.py` |
| Vital Signs | Temperature (core) | `cerebralos/features/vitals_canonical_v1.py` |
| Neurologic | Spinal clearance status | `cerebralos/features/spine_clearance_v1.py` |
| Laboratory | Base deficit (serial) | `cerebralos/features/base_deficit_monitoring_v1.py` |
| Laboratory | Blood culture results | `clabsi_blood_culture_positive` mapper key in `rules/mappers/epic_deaconess_mapper_v1.json` |
| Laboratory | Urine culture results | `cauti_culture_positive` mapper key |
| Laboratory | Urine drug screen / BAL | `cerebralos/features/etoh_uds_v1.py` |
| Imaging | FAST/eFAST | `cerebralos/features/fast_exam_v1.py` |
| Operative | Surgical complications | `deep_ssi_dx` + `organ_space_ssi_dx` + `superficial_ssi_dx` mapper keys |
| Operative | Unplanned return to OR | `or_return_unplanned` + `or_initial_procedure` + `or_same_site` mapper keys; `rules/ntds/logic/2026/20_or_return.json` |
| Pharmacologic | GI prophylaxis agent (PPI/H2 blocker) | `cerebralos/features/gi_prophylaxis_v1.py` |
| Pharmacologic | VTE chemoprophylaxis (LMWH/UFH, timing) | `cerebralos/features/dvt_prophylaxis_v1.py`; `dvt_treatment_anticoag` mapper key |
| Infection | CAUTI diagnosis (CDC criteria) | E05 multi-gate rule: `rules/ntds/logic/2026/05_cauti.json` |
| Infection | CLABSI diagnosis (NHSN criteria) | E06 multi-gate rule: `rules/ntds/logic/2026/06_clabsi.json` |
| Infection | SSI — superficial | E17 rule: `rules/ntds/logic/2026/17_superficial_ssi.json` |
| Infection | SSI — deep | E07 rule: `rules/ntds/logic/2026/07_deep_ssi.json` |
| Infection | SSI — organ/space | E11 rule: `rules/ntds/logic/2026/11_organ_space_ssi.json` |
| Infection | VAP diagnosis | E21 multi-gate rule: `rules/ntds/logic/2026/21_vap.json` |
| Infection | Sepsis / severe sepsis (qSOFA, SIRS criteria) | `sepsis_dx` mapper key; E15 rule: `rules/ntds/logic/2026/15_severe_sepsis.json` |
| Prophylaxis | DVT prophylaxis — chemical (agent, dose, start date) | `cerebralos/features/dvt_prophylaxis_v1.py`; `dvt_treatment_anticoag` mapper key |
| Prophylaxis | GI prophylaxis (PPI/H2 blocker, start date) | `cerebralos/features/gi_prophylaxis_v1.py` |
| Screening | SBIRT screening completed (yes/no) | `cerebralos/features/sbirt_screening_v1.py` |
| Screening | SBIRT screening result (negative/positive) | `cerebralos/features/sbirt_screening_v1.py` |
| Screening | Blood alcohol level (BAL) | `cerebralos/features/etoh_uds_v1.py` |
| Screening | Urine drug screen result | `cerebralos/features/etoh_uds_v1.py` |
| Disposition | ICU admission (planned vs. unplanned) | `unplanned_icu` mapper key; E18 rule: `rules/ntds/logic/2026/18_unplanned_icu_admission.json` |
| NTDS E01 | Acute Kidney Injury (KDIGO Stage 3) | `rules/ntds/logic/2026/01_aki.json` — 3+ gate logic |
| NTDS E03 | Alcohol Withdrawal | `rules/ntds/logic/2026/03_alcohol_withdrawal_syndrome.json` |
| NTDS E04 | Cardiac Arrest | `rules/ntds/logic/2026/04_cardiac_arrest_with_cpr.json` — dual gate |
| NTDS E05 | CAUTI (CDC SUTI 1a) | `rules/ntds/logic/2026/05_cauti.json` — 6 gates + LDA |
| NTDS E06 | CLABSI (NHSN) | `rules/ntds/logic/2026/06_clabsi.json` — 5 gates + LDA |
| NTDS E07 | Deep SSI | `rules/ntds/logic/2026/07_deep_ssi.json` |
| NTDS E08 | DVT | `rules/ntds/logic/2026/08_dvt.json` — multi-gate with imaging early-exit |
| NTDS E09 | Delirium | `rules/ntds/logic/2026/09_delirium.json` |
| NTDS E10 | Myocardial Infarction | `rules/ntds/logic/2026/10_mi.json` |
| NTDS E11 | Organ/Space SSI | `rules/ntds/logic/2026/11_organ_space_ssi.json` |
| NTDS E12 | Osteomyelitis | `rules/ntds/logic/2026/12_osteomyelitis.json` |
| NTDS E13 | Pressure Ulcer | `rules/ntds/logic/2026/13_pressure_ulcer.json` |
| NTDS E14 | Pulmonary Embolism | `rules/ntds/logic/2026/14_pe.json` — multi-gate with imaging early-exit |
| NTDS E15 | Severe Sepsis | `rules/ntds/logic/2026/15_severe_sepsis.json` |
| NTDS E16 | Stroke/CVA | `rules/ntds/logic/2026/16_stroke_cva.json` |
| NTDS E17 | Superficial SSI | `rules/ntds/logic/2026/17_superficial_ssi.json` |
| NTDS E18 | Unplanned ICU Admission | `rules/ntds/logic/2026/18_unplanned_icu_admission.json` |
| NTDS E19 | Unplanned Intubation | `rules/ntds/logic/2026/19_unplanned_intubation.json` |
| NTDS E20 | Unplanned Return to OR | `rules/ntds/logic/2026/20_or_return.json` |
| NTDS E21 | Ventilator-Associated Pneumonia | `rules/ntds/logic/2026/21_vap.json` — multi-gate + LDA vent duration |
| Operational | Trauma team activation level (Cat I / Cat II / Consult) | `cerebralos/features/category_activation_v1.py` |

---

## Detailed Evidence: PARTIAL Elements (57)

| Category | Element | What Exists | What's Missing |
|----------|---------|-------------|----------------|
| Demographics | Transferring facility | `adt_transfer_timeline_v1.py` captures transfers | Facility name not structured |
| ED Assessment | ED disposition time | `adt_transfer_timeline_v1.py` captures transfers | No explicit ED dispo timestamp |
| Vital Signs | GCS (total + components E/V/M) | `neuro_trigger_v1.py` detects GCS trigger patterns | No structured E/V/M component parsing |
| Vital Signs | Serial vital sign monitoring | `vitals_canonical_v1.py` captures values | Serial compliance not assessed |
| Vital Signs | Shock index (HR/SBP) | `hemodynamic_instability_pattern_v1.py` + `shock_trigger_v1.py` | Ratio value not computed |
| Neurologic | GCS post-resuscitation | `neuro_trigger_v1.py` captures GCS mentions | Post-resuscitation timing not determined |
| Neurologic | Pupil reactivity (bilateral) | `neuro_trigger_v1.py` captures pupil mentions | Bilateral/reactive status not structured |
| Neurologic | Motor exam (lateralizing signs) | `neuro_trigger_v1.py` captures motor findings | Lateralizing signs not classified |
| Neurologic | Sensory exam (dermatome level) | `spine_clearance_v1.py` captures some sensory findings | Dermatome level not structured |
| Neurologic | NEXUS / Canadian C-Spine criteria | `spine_clearance_v1.py` may capture mentions | Criteria not scored |
| Neurologic | Delirium screening (CAM-ICU / bCAM) | `delirium_dx` mapper key for diagnosis | CAM-ICU/bCAM instrument scores not structured |
| Neurologic | Mental status changes | `neuro_trigger_v1.py` captures AMS patterns | Not classified by type |
| Laboratory | CBC (H/H, WBC, platelets) | LAB section parsed | Individual lab values not structured |
| Laboratory | BMP (Na, K, Cl, CO2, BUN, Cr, glucose) | `aki_stage3_lab` patterns match creatinine | Full BMP not structured |
| Laboratory | Coagulation panel (PT/INR, PTT, fibrinogen) | `cerebralos/features/inr_normalization_v1.py` | Full coag panel not structured |
| Laboratory | ABG (pH, pCO2, pO2, base deficit, lactate) | `base_deficit_monitoring_v1.py` captures BD patterns | Full ABG not structured |
| Laboratory | Lactate (serial) | `base_deficit_monitoring_v1.py` captures some lactate | Not fully structured |
| Laboratory | Serum creatinine (baseline + serial) | `aki_stage3_lab` patterns match creatinine mentions | Values not parsed |
| Laboratory | Troponin | `mi_dx` mapper patterns may match troponin mentions | Values not parsed |
| Imaging | CT head | `radiology_findings_v1.py` captures imaging mentions | Not CT-head-specific |
| Imaging | CT cervical spine | `radiology_findings_v1.py` + `spine_clearance_v1.py` | Not specifically classified |
| Imaging | CT chest/abdomen/pelvis | `radiology_findings_v1.py` captures imaging mentions | Not body-region-specific |
| Imaging | CTA neck/chest | `radiology_findings_v1.py` captures CTA mentions | Not classified by target |
| Imaging | Plain films (chest, pelvis, extremity) | `radiology_findings_v1.py` captures x-ray mentions | Not modality-structured |
| Imaging | Angiography (diagnostic/interventional) | `radiology_findings_v1.py` may capture angiography | Not procedural-specific |
| Imaging | MRI spine | `radiology_findings_v1.py` captures MRI mentions | Not spine-specific |
| Imaging | Chest X-ray (serial) | `vap_cxr` mapper key captures CXR in VAP context | Generic CXR not structured |
| Airway | Intubation (date/time/indication) | `unplanned_intubation` mapper key; `note_index_events_v1.py` | Date/time not fully structured |
| Airway | Ventilator days | `vent_dx` mapper key; flowsheet day rows present | LDA vent day extraction pending |
| Airway | Oxygen supplementation type/FiO2 | `cerebralos/features/incentive_spirometry_v1.py` captures IS | FiO2 not parsed |
| Operative | Procedure type / CPT | `procedure_operatives_v1.py` captures mentions | CPT not extracted |
| Operative | Procedure date/time | `procedure_operatives_v1.py` captures some timing | Not fully structured |
| Operative | Anesthesia type / duration | `cerebralos/features/anesthesia_case_metrics_v1.py` | Partial metrics |
| Operative | Operative findings | `procedure_operatives_v1.py` captures operative note text | Not classified |
| Operative | Spinal stabilization surgery (time from injury) | `spine_clearance_v1.py` captures surgery mention | Time-from-injury not computed |
| Pharmacologic | Anticoagulant reversal agent (4F-PCC, vitamin K, protamine, idarucizumab) | `anticoag_context_v1.py` captures anticoag mentions | Reversal agents not structured |
| Pharmacologic | Pre-injury anticoagulant/antiplatelet list | `pmh_social_allergies_v1.py` + `anticoag_context_v1.py` | Medication list not structured |
| Device | Central venous catheter (type, site, date placed) | `clabsi_central_line_in_place` mapper key; LDA CENTRAL_LINE defined in `lda_events_v1.py` | Type/site not structured |
| Device | Central line duration (days) | Flowsheet 'Catheter day' data present | LDA duration gate pending full activation |
| Device | Urinary catheter (Foley) placement date | `cauti_catheter_in_place` mapper key; LDA URETHRAL_CATHETER defined | Placement date not structured |
| Device | Urinary catheter duration (days) | Flowsheet data present for ≥12 patients | LDA duration gate pending full activation |
| Device | Mechanical ventilation (start/end date) | `vent_dx` mapper key; LDA infrastructure defined | Start/end timestamps not structured |
| Device | Sequential compression devices (SCDs) | `dvt_prophylaxis_v1.py` may capture SCD mentions | Not specifically structured |
| Infection | Pressure ulcer (stage, location, date identified) | `pressure_ulcer_dx` mapper key detects diagnosis | Stage/location/date not structured |
| Infection | Infection source identification | Culture results per-event (E05 urine, E06 blood) | Generic source not structured |
| Prophylaxis | DVT prophylaxis — mechanical (SCDs, date started) | `dvt_prophylaxis_v1.py` captures mentions | SCD start date not structured |
| Prophylaxis | DVT prophylaxis — contraindication documented | `dvt_prophylaxis_v1.py` may capture contraindication text | Not explicitly structured |
| Screening | SBIRT brief intervention provided | `sbirt_screening_v1.py` captures screening | Intervention documentation not structured |
| Screening | SBIRT referral to treatment | `sbirt_screening_v1.py` captures screening | Referral not structured |
| Screening | Social work consult ordered | `consultant_events_v1.py` may capture social work | Not SBIRT-specific |
| Geriatric | Pre-injury anticoagulant use | `pmh_social_allergies_v1.py` + `anticoag_context_v1.py` | Medication specifics not structured |
| Geriatric | Geriatric consult | `consultant_events_v1.py` may capture geriatric consult | Not geriatric-protocol-specific |
| Disposition | Hospital LOS (days) | `adt_transfer_timeline_v1.py` captures admit/discharge | LOS not computed |
| Disposition | ICU LOS (days) | `patient_movement_v1.py` captures ICU transfers | ICU LOS not computed |
| Disposition | Discharge date/time | DISCHARGE section parsed | Date/time not always structured |
| Disposition | Transfer destination (facility, level) | `adt_transfer_timeline_v1.py` captures transfers | Destination facility not structured |
| NTDS E02 | ARDS (Berlin criteria) | E02 rule: `ards_dx` + `ards_onset` | P/F ratio components not structured |

---

## Top 10 High-Confidence Gaps

These are MISSING elements where (a) the data is likely present in the raw
Epic `.txt` export, (b) extraction would directly support protocol compliance
or NTDS event adjudication, and (c) the implementation path is clear.

| Rank | Element | Category | Why It Matters | Likely Implementation |
|------|---------|----------|----------------|----------------------|
| 1 | **MTP activation (yes/no, time)** | Resuscitation | Critical for transfusion protocol compliance; MTP text likely present in operative/ED notes | New mapper key + feature module; pattern: `massive transfusion protocol` / `MTP activated` |
| 2 | **pRBC / FFP / Platelet units transfused** | Resuscitation | 1:1:1 ratio monitoring for blood transfusion protocol compliance | MAR section parsing for blood product administration |
| 3 | **Ventilator mode / settings** | Airway | Required for ARDS Berlin criteria (NTDS E02) and TBI PaCO2 targeting | Flowsheet row parsing for vent mode/FiO2/PEEP |
| 4 | **PaO2/FiO2 ratio** | Airway | Core Berlin criteria component for E02 ARDS; currently partial | LAB section ABG value parsing + computation |
| 5 | **Chest tube placement (date/time/output)** | Airway | LDA CHEST_TUBE type already defined in `lda_events_v1.py`; text extraction needed | Wire existing LDA category to flowsheet row parsing |
| 6 | ~~**Sex**~~ | Demographics | ✅ EXTRACTED (PR #223) — `demographics_v1.sex` | Header/HPI parsing in `parse_patient_txt.py` + `build_patient_features_v1.py` |
| 7 | **ICP (intracranial pressure)** | Vital Signs | TBI Management protocol requires ICP monitoring; text likely present | Flowsheet row or note section pattern matching |
| 8 | ~~**Discharge disposition**~~ | Disposition | ✅ EXTRACTED (PR #259) — `demographics_v1.discharge_disposition` | Sourced from `patient_movement_v1.summary.discharge_disposition_final` |
| 9 | **Mental health screening** | Screening | Required by protocol for all trauma patients; likely documented | Pattern matching in nursing assessment / social work notes |
| 10 | **Antibiotic administration (type, time)** | Pharmacologic | Open fracture protocol requires antibiotics within 1 hour | MAR section antibiotic pattern matching |

---

## Next PR Slices

### Slice A — ✅ COMPLETE: Sex + Discharge Disposition Extraction

**Status:** Completed across PRs #222–#225 (sex) and PR #259 (discharge disposition wiring).

| Element | Status | Module |
|---------|--------|--------|
| Sex | ✅ EXTRACTED | `demographics_v1.sex` via evidence header + HPI fallback |
| Discharge disposition | ✅ EXTRACTED | `demographics_v1.discharge_disposition` via `patient_movement_v1.summary.discharge_disposition_final` |

**Files touched:**
- `cerebralos/features/build_patient_features_v1.py` — demographics_v1 assembly
- `docs/contracts/demographics_v1.md` — schema contract
- `tests/test_demographics_v1.py` — behaviour lock tests

### Slice B — Medium: Blood Product Transfusion Extraction

**Scope:** 4–5 elements from Resuscitation / Blood Products category.

| Element | Source | Pattern |
|---------|--------|---------|
| MTP activation | Operative / ED notes | `massive transfusion protocol`, `MTP activated` |
| pRBC units transfused | MAR section | Blood product administration rows |
| FFP units transfused | MAR section | Blood product administration rows |
| Platelet units transfused | MAR section | Blood product administration rows |
| TXA administration | MAR section | `tranexamic acid` / `TXA` rows |

**Files touched:**
- `cerebralos/features/` — new `blood_products_v1.py` feature module
- `rules/mappers/epic_deaconess_mapper_v1.json` — new mapper keys if needed
- `tests/` — test files with real MAR section extracts

**Estimated effort:** Medium (1–2 days). Requires MAR section parsing for
blood product rows, unit counting, and ratio computation.

### Slice C — Large: Structured Lab Value Parsing

**Scope:** 8–10 elements across Laboratory / Diagnostics.

| Element | Source | Pattern |
|---------|--------|---------|
| CBC components (H/H, WBC, platelets) | LAB section flowsheet | Structured lab value rows |
| BMP components (Na, K, Cr, glucose) | LAB section flowsheet | Structured lab value rows |
| Full coag panel (PT/INR, PTT, fibrinogen) | LAB section flowsheet | Structured lab value rows |
| ABG components (pH, pCO2, pO2, BD, lactate) | LAB section flowsheet | Structured lab value rows |
| PaO2/FiO2 ratio computation | LAB + flowsheet | Derived computation |
| Troponin value parsing | LAB section | Troponin rows |
| Procalcitonin value parsing | LAB section | Procalcitonin rows |

**Files touched:**
- `cerebralos/features/labs_extract.py`, `labs_daily.py`, `labs_panel_daily.py`
  — extend existing lab extraction infrastructure
- `rules/features/labs_thresholds_v1.json` — add threshold configs
- `tests/` — extensive test coverage for lab value parsing

**Estimated effort:** Large (3–5 days). Requires robust numeric value parsing
from LAB section flowsheet rows, handling of units, reference ranges, and serial
trending. Foundation work that would unlock multiple downstream protocol elements.

---

## Appendix: Category Coverage Heat Map

```
Category                                     Coverage  Bar
──────────────────────────────────────────── ─────── ──────────────────────
19 · Complications / NTDS Events               100%   ████████████████████
20 · Operational / Call Panel (excl N/A)        100%   ████████████████████
 6 · Neurologic Assessment                      89%   █████████████████▊
14 · Infection Prevention / HAI Monitoring      82%   ████████████████▍
 5 · Vital Signs / Hemodynamic Monitoring       80%   ████████████████
 8 · Imaging / Radiology                        75%   ███████████████
 1 · Demographics / Patient Identification      71%   ██████████████▎
 7 · Laboratory / Diagnostics                   69%   █████████████▊
16 · Screening / Behavioral Health              64%   ████████████▊
11 · Operative / Procedural                     58%   ███████████▌
15 · Prophylaxis (DVT / GI / Hypothermia)       57%   ███████████▍
18 · Disposition / Discharge Planning           56%   ███████████
13 · Device / Line Management                   50%   ██████████
 4 · Emergency Department Assessment            44%   ████████▊
12 · Pharmacologic Interventions                44%   ████████▊
 9 · Airway / Respiratory                       33%   ██████▋
17a· Special Populations — Geriatric            29%   █████▊
 3 · Injury Mechanism / Classification          20%   ████
 2 · Prehospital / EMS                          14%   ██▊
10 · Resuscitation / Blood Products              0%   ▏
17b· Special Populations — Pediatric             0%   ▏
17c· Special Populations — Obstetric             0%   ▏
```

> **Strongest areas:** NTDS event adjudication (21/21 events), vital signs,
> infection prevention, and neurologic assessment.
>
> **Weakest areas:** Resuscitation / blood products (0 of 12), special
> populations (0 of 20 across 17a geriatric / 17b pediatric / 17c obstetric),
> and prehospital (1 of 7 actionable).

---

_End of document._
