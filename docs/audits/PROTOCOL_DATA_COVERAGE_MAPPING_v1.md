# Protocol Data Coverage Mapping — v1

| Field       | Value |
|-------------|-------|
| Source       | Analysis of CerebralOS extraction pipeline vs. Protocol Data Element Master v1 |
| Generated   | 2026-03-16 (refreshed; original 2026-03-12) |
| Baseline     | `16d2bfa` (main, after PR #260) |
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

| Status | Count | Pct | Δ from v1 (2026-03-12) |
|--------|------:|----:|:----------------------:|
| EXTRACTED | 82 | 35.7% | +22 |
| PARTIAL | 46 | 20.0% | −11 |
| MISSING | 86 | 37.4% | −11 |
| N/A | 16 | 7.0% | 0 |
| **Total** | **230** | 100% | — |

**Actionable elements** (excluding N/A): 214
**Actionable coverage** (EXTRACTED + PARTIAL): 128 / 214 = **59.8%** (was 54.7%)
**Fully extracted**: 82 / 214 = **38.3%** (was 28.0%)

### Change Log (v1 → v2 refresh)

| Category | Change | PRs | Elements moved |
|----------|--------|-----|----------------|
| Resuscitation | 6 MISSING → EXTRACTED | #229–#231 | MTP, pRBC, FFP, Platelets, TXA, Cryo |
| Laboratory | 7 PARTIAL → EXTRACTED | #226–#228, #232 | CBC, BMP, Coag, ABG, Lactate, Creatinine, Troponin |
| Vital Signs | 2 PARTIAL → EXTRACTED | #238–#239, #243, #254 | GCS (E/V/M components), Shock Index |
| Airway | 2 MISSING → EXTRACTED | #233–#237, #226–#228 | Vent mode/settings, PaO2/FiO2 ratio |
| Demographics | 1 MISSING → EXTRACTED | #222–#225 | Sex |
| Disposition | 1 MISSING → EXTRACTED | #222–#225 | Discharge disposition |
| Pharmacologic | 1 MISSING → EXTRACTED | (this PR) | Seizure prophylaxis |

---

## Coverage Matrix by Category

| # | Category | EXTRACTED | PARTIAL | MISSING | N/A | Total | Coverage |
|---|----------|----------:|--------:|--------:|----:|------:|---------:|
| 1 | Demographics / Patient Identification | 5 | 1 | 1 | 1 | 8 | 86% |
| 2 | Prehospital / EMS | 1 | 0 | 6 | 1 | 8 | 14% |
| 3 | Injury Mechanism / Classification | 2 | 0 | 8 | 2 | 12 | 20% |
| 4 | Emergency Department Assessment | 4 | 0 | 5 | 0 | 9 | 44% |
| 5 | Vital Signs / Hemodynamic Monitoring | 7 | 1 | 2 | 0 | 10 | 80% |
| 6 | Neurologic Assessment | 1 | 7 | 1 | 0 | 9 | 89% |
| 7 | Laboratory / Diagnostics | 11 | 0 | 5 | 0 | 16 | 69% |
| 8 | Imaging / Radiology | 1 | 8 | 3 | 0 | 12 | 75% |
| 9 | Airway / Respiratory | 2 | 3 | 4 | 0 | 9 | 56% |
| 10 | Resuscitation / Blood Products | 6 | 0 | 6 | 0 | 12 | 50% |
| 11 | Operative / Procedural | 2 | 5 | 5 | 0 | 12 | 58% |
| 12 | Pharmacologic Interventions | 3 | 2 | 4 | 0 | 9 | 56% |
| 13 | Device / Line Management | 0 | 6 | 6 | 0 | 12 | 50% |
| 14 | Infection Prevention / HAI Monitoring | 7 | 2 | 2 | 0 | 11 | 82% |
| 15 | Prophylaxis (DVT / GI / Hypothermia) | 2 | 2 | 3 | 0 | 7 | 57% |
| 16 | Screening / Behavioral Health | 4 | 3 | 4 | 0 | 11 | 64% |
| 17a | Special Populations — Geriatric | 0 | 2 | 5 | 0 | 7 | 29% |
| 17b | Special Populations — Pediatric | 0 | 0 | 7 | 0 | 7 | 0% |
| 17c | Special Populations — Obstetric | 0 | 0 | 6 | 0 | 6 | 0% |
| 18 | Disposition / Discharge Planning | 3 | 3 | 3 | 2 | 11 | 67% |
| 19 | Complications / NTDS Events | 20 | 1 | 0 | 0 | 21 | 100% |
| 20 | Operational / Call Panel | 1 | 0 | 0 | 10 | 11 | 100% |

> **Coverage** = (EXTRACTED + PARTIAL) / (Total − N/A). Categories with 0%
> have no extraction infrastructure at all today.

---

## Detailed Evidence: EXTRACTED Elements (81)

| Category | Element | Repo Evidence |
|----------|---------|---------------|
| Demographics | Patient name / MRN | `patient_id` parsed from PATIENT_ID header line in ingestion pipeline |
| Demographics | Date of birth / Age | `cerebralos/features/age_extraction_v1.py` |
| Demographics | Admission date/time | ARRIVAL_TIME header parsing; `cerebralos/features/adt_transfer_timeline_v1.py` |
| Demographics | Trauma activation category | `cerebralos/features/category_activation_v1.py`; `rules/features/category_activation_v1.json` |
| Demographics | Sex | `cerebralos/features/build_patient_features_v1.py` → `demographics_v1.sex`; primary from evidence header SEX, fallback `_extract_sex_hpi_fallback()` in `parse_patient_txt.py` (PRs #222–#225) |
| Prehospital | Mechanism of injury narrative | `cerebralos/features/mechanism_region_v1.py` |
| Injury Mech. | Blunt vs. penetrating classification | `cerebralos/features/mechanism_region_v1.py` — classifies blunt/penetrating |
| Injury Mech. | Body region(s) involved | `cerebralos/features/mechanism_region_v1.py` — extracts body regions |
| ED Assessment | ED arrival date/time | ARRIVAL_TIME header; `cerebralos/features/adt_transfer_timeline_v1.py` |
| ED Assessment | Triage category (Cat I / Cat II / Consult) | `cerebralos/features/category_activation_v1.py` |
| ED Assessment | FAST exam (positive/negative/indeterminate) | `cerebralos/features/fast_exam_v1.py` |
| ED Assessment | ED disposition time | `cerebralos/features/adt_transfer_timeline_v1.py` summary `ed_departure_ts`, `ed_los_hours`, `ed_los_minutes` |
| Vital Signs | Blood pressure (systolic/diastolic/MAP) | `cerebralos/features/vitals_canonical_v1.py`; `rules/features/vitals_patterns_v1.json` |
| Vital Signs | Heart rate | `cerebralos/features/vitals_canonical_v1.py` |
| Vital Signs | Respiratory rate | `cerebralos/features/vitals_canonical_v1.py` |
| Vital Signs | SpO2 (pulse oximetry) | `cerebralos/features/vitals_canonical_v1.py` |
| Vital Signs | Temperature (core) | `cerebralos/features/vitals_canonical_v1.py` |
| Vital Signs | GCS (total + components E/V/M) | `cerebralos/features/gcs_daily.py` — structured E/V/M component extraction from inline + flowsheet + tabular sources; emits per-day `arrival_gcs`, `best_gcs`, `worst_gcs`, and `all_readings`; sum-mismatch guard; compact-intubated fix (PRs #238–#239, #243) |
| Vital Signs | Shock index (HR/SBP) | `cerebralos/features/shock_trigger_v1.py` — deterministic SI = HR/SBP; classification: normal/elevated/critical; fail-closed null (PR #254) |
| Neurologic | Spinal clearance status | `cerebralos/features/spine_clearance_v1.py` |
| Laboratory | Base deficit (serial) | `cerebralos/features/base_deficit_monitoring_v1.py` |
| Laboratory | Blood culture results | `clabsi_blood_culture_positive` mapper key in `rules/mappers/epic_deaconess_mapper_v1.json` |
| Laboratory | Urine culture results | `cauti_culture_positive` mapper key |
| Laboratory | Urine drug screen / BAL | `cerebralos/features/etoh_uds_v1.py` |
| Laboratory | CBC (H/H, WBC, platelets) | `cerebralos/features/structured_labs_v1.py` — cbc panel with Hgb/Hct/WBC/Plt; per-day series with delta tracking (PRs #226–#228) |
| Laboratory | BMP (Na, K, Cl, CO2, BUN, Cr, glucose) | `cerebralos/features/structured_labs_v1.py` — bmp panel with 7 components; per-day series (PRs #226–#228) |
| Laboratory | Coagulation panel (PT/INR, PTT, fibrinogen) | `cerebralos/features/structured_labs_v1.py` — coag panel; 4 components (PRs #226–#228) |
| Laboratory | ABG (pH, pCO2, pO2, base deficit, lactate) | `cerebralos/features/structured_labs_v1.py` — abg panel; 5 components (PRs #226–#228) |
| Laboratory | Lactate (serial) | `cerebralos/features/structured_labs_v1.py` — abg.Lactate component with serial tracking (PRs #226–#228) |
| Laboratory | Serum creatinine (baseline + serial) | `cerebralos/features/structured_labs_v1.py` — bmp.Cr component with serial tracking (PRs #226–#228) |
| Laboratory | Troponin | `cerebralos/features/structured_labs_v1.py` — cardiac.Troponin_T panel component (PR #232) |
| Imaging | FAST/eFAST | `cerebralos/features/fast_exam_v1.py` |
| Airway | Ventilator mode / settings | `cerebralos/features/ventilator_settings_v1.py` — vent_mode, FiO2, PEEP, Vt, RR from flowsheet rows; ventilated_flag; NIV (IPAP/EPAP) support (PRs #233–#237) |
| Airway | PaO2/FiO2 ratio | `cerebralos/features/structured_labs_v1.py` — PF ratio computed from ABG pO2 + flowsheet FiO2; per-day series (PRs #226–#228) |
| Operative | Surgical complications | `deep_ssi_dx` + `organ_space_ssi_dx` + `superficial_ssi_dx` mapper keys |
| Operative | Unplanned return to OR | `or_return_unplanned` + `or_initial_procedure` + `or_same_site` mapper keys; `rules/ntds/logic/2026/20_or_return.json` |
| Pharmacologic | GI prophylaxis agent (PPI/H2 blocker) | `cerebralos/features/gi_prophylaxis_v1.py` |
| Pharmacologic | VTE chemoprophylaxis (LMWH/UFH, timing) | `cerebralos/features/dvt_prophylaxis_v1.py`; `dvt_treatment_anticoag` mapper key |
| Pharmacologic | Seizure prophylaxis (agent, start, duration) | `cerebralos/features/seizure_prophylaxis_v1.py` — levetiracetam/phenytoin/valproate/lacosamide detection; dose/route/frequency; home med vs inpatient; admin confirmation; discontinuation tracking |
| Resuscitation | MTP activation (yes/no, time) | `cerebralos/features/transfusion_blood_products_v1.py` — MTP pattern detection with timestamp (PRs #229–#231) |
| Resuscitation | pRBC units transfused | `cerebralos/features/transfusion_blood_products_v1.py` — MAR section blood product row parsing; unit count (PRs #229–#231) |
| Resuscitation | FFP units transfused | `cerebralos/features/transfusion_blood_products_v1.py` — MAR section FFP row parsing; unit count (PRs #229–#231) |
| Resuscitation | Platelet units transfused | `cerebralos/features/transfusion_blood_products_v1.py` — MAR section platelet row parsing; unit count (PRs #229–#231) |
| Resuscitation | TXA administration | `cerebralos/features/transfusion_blood_products_v1.py` — tranexamic acid detection from MAR/note text (PRs #229–#231) |
| Resuscitation | Cryoprecipitate | `cerebralos/features/transfusion_blood_products_v1.py` — cryoprecipitate detection from MAR section (PRs #229–#231) |
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
| Disposition | ICU LOS (days) | `cerebralos/features/patient_movement_v1.py` — `icu_los_hours`, `icu_los_days`, `icu_admission_count` in summary; computed from movement entry `Level of Care: ICU` intervals |
| Disposition | Discharge disposition | `cerebralos/features/build_patient_features_v1.py` → `demographics_v1.discharge_disposition`; primary from `patient_movement_v1.summary.discharge_disposition_final`, fallback keyword extraction (PRs #222–#225) |
| NTDS E01 | Acute Kidney Injury (KDIGO Stage 3) | `rules/ntds/logic/2026/01_aki.json` — 3+ gate logic |
| NTDS E03 | Alcohol Withdrawal | `rules/ntds/logic/2026/03_alcohol_withdrawal_syndrome.json` |
| NTDS E04 | Cardiac Arrest | `rules/ntds/logic/2026/04_cardiac_arrest_with_cpr.json` — dual gate |
| NTDS E05 | CAUTI (CDC SUTI 1a) | `rules/ntds/logic/2026/05_cauti.json` — 6 gates + LDA (built; disabled by default in `engine.py`, enabled for E05 in NTDS runner/tests pending broader validation) |
| NTDS E06 | CLABSI (NHSN) | `rules/ntds/logic/2026/06_clabsi.json` — 5 gates + LDA (built; disabled by default in `engine.py`, enabled for E06 in NTDS runner/tests pending broader validation) |
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
| NTDS E21 | Ventilator-Associated Pneumonia | `rules/ntds/logic/2026/21_vap.json` — multi-gate + LDA vent duration (built; disabled by default in `engine.py`, enabled for E21 in NTDS runner/tests pending broader validation) |
| Operational | Trauma team activation level (Cat I / Cat II / Consult) | `cerebralos/features/category_activation_v1.py` |

---

## Detailed Evidence: PARTIAL Elements (46)

| Category | Element | What Exists | What's Missing |
|----------|---------|-------------|----------------|
| Demographics | Transferring facility | `adt_transfer_timeline_v1.py` captures transfers | Facility name not structured |
| Vital Signs | Serial vital sign monitoring | `vitals_canonical_v1.py` captures values | Serial compliance not assessed |
| Neurologic | GCS post-resuscitation | `neuro_trigger_v1.py` captures GCS mentions | Post-resuscitation timing not determined |
| Neurologic | Pupil reactivity (bilateral) | `neuro_trigger_v1.py` captures pupil mentions | Bilateral/reactive status not structured |
| Neurologic | Motor exam (lateralizing signs) | `neuro_trigger_v1.py` captures motor findings | Lateralizing signs not classified |
| Neurologic | Sensory exam (dermatome level) | `spine_clearance_v1.py` captures some sensory findings | Dermatome level not structured |
| Neurologic | NEXUS / Canadian C-Spine criteria | `spine_clearance_v1.py` may capture mentions | Criteria not scored |
| Neurologic | Delirium screening (CAM-ICU / bCAM) | `delirium_dx` mapper key for diagnosis | CAM-ICU/bCAM instrument scores not structured |
| Neurologic | Mental status changes | `neuro_trigger_v1.py` captures AMS patterns | Not classified by type |
| Imaging | CT head | `radiology_findings_v1.py` captures imaging mentions | Not CT-head-specific |
| Imaging | CT cervical spine | `radiology_findings_v1.py` + `spine_clearance_v1.py` | Not specifically classified |
| Imaging | CT chest/abdomen/pelvis | `radiology_findings_v1.py` captures imaging mentions | Not body-region-specific |
| Imaging | CTA neck/chest | `radiology_findings_v1.py` captures CTA mentions | Not classified by target |
| Imaging | Plain films (chest, pelvis, extremity) | `radiology_findings_v1.py` captures x-ray mentions | Not modality-structured |
| Imaging | Angiography (diagnostic/interventional) | `radiology_findings_v1.py` may capture angiography | Not procedural-specific |
| Imaging | MRI spine | `radiology_findings_v1.py` captures MRI mentions | Not spine-specific |
| Imaging | Chest X-ray (serial) | `vap_cxr` mapper key captures CXR in VAP context | Generic CXR not structured |
| Airway | Intubation (date/time/indication) | `unplanned_intubation` mapper key; `note_index_events_v1.py` | Date/time not fully structured |
| Airway | Ventilator days | `vent_dx` mapper key; flowsheet day rows present; LDA vent-duration gate exists in NTDS logic | Duration logic built and feature-flagged; currently exercised for VAP/E21 in the NTDS runner/tests |
| Airway | Oxygen supplementation type/FiO2 | `cerebralos/features/incentive_spirometry_v1.py` captures IS | FiO2 not parsed |
| Operative | Procedure type / CPT | `procedure_operatives_v1.py` captures mentions | CPT not extracted |
| Operative | Procedure date/time | `procedure_operatives_v1.py` captures some timing | Not fully structured |
| Operative | Anesthesia type / duration | `cerebralos/features/anesthesia_case_metrics_v1.py` | Partial metrics |
| Operative | Operative findings | `procedure_operatives_v1.py` captures operative note text | Not classified |
| Operative | Spinal stabilization surgery (time from injury) | `spine_clearance_v1.py` captures surgery mention | Time-from-injury not computed |
| Pharmacologic | Anticoagulant reversal agent (4F-PCC, vitamin K, protamine, idarucizumab) | `anticoag_context_v1.py` captures anticoag mentions | Reversal agents not structured |
| Pharmacologic | Pre-injury anticoagulant/antiplatelet list | `pmh_social_allergies_v1.py` + `anticoag_context_v1.py` | Medication list not structured |
| Device | Central venous catheter (type, site, date placed) | `clabsi_central_line_in_place` mapper key; LDA CENTRAL_LINE defined in `lda_events_v1.py` | Type/site not structured |
| Device | Central line duration (days) | Flowsheet 'Catheter day' data present; LDA duration gate exists in NTDS logic | Duration logic built and feature-flagged; currently exercised for CLABSI/E06 in the NTDS runner/tests |
| Device | Urinary catheter (Foley) placement date | `cauti_catheter_in_place` mapper key; LDA URETHRAL_CATHETER defined | Placement date not structured |
| Device | Urinary catheter duration (days) | Flowsheet data present for ≥12 patients; LDA duration gate exists in NTDS logic | Duration logic built and feature-flagged; currently exercised for CAUTI/E05 in the NTDS runner/tests |
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
| Disposition | Discharge date/time | DISCHARGE section parsed | Date/time not always structured |
| Disposition | Transfer destination (facility, level) | `adt_transfer_timeline_v1.py` captures transfers | Destination facility not structured |
| NTDS E02 | ARDS (Berlin criteria) | E02 rule: `ards_dx` + `ards_onset` | P/F ratio components not structured |

---

## Top 10 High-Confidence Gaps (updated 2026-03-16)

These are MISSING elements where (a) the data is likely present in the raw
Epic `.txt` export, (b) extraction would directly support protocol compliance
or NTDS event adjudication, and (c) the implementation path is clear.

Six of the original ten gaps have been closed since the initial audit.

| Rank | Element | Category | Status | Closed By |
|------|---------|----------|--------|-----------|
| 1 | ~~MTP activation (yes/no, time)~~ | Resuscitation | ✅ EXTRACTED | `transfusion_blood_products_v1.py` (PRs #229–#231) |
| 2 | ~~pRBC / FFP / Platelet units transfused~~ | Resuscitation | ✅ EXTRACTED | `transfusion_blood_products_v1.py` (PRs #229–#231) |
| 3 | ~~Ventilator mode / settings~~ | Airway | ✅ EXTRACTED | `ventilator_settings_v1.py` (PRs #233–#237) |
| 4 | ~~PaO2/FiO2 ratio~~ | Airway | ✅ EXTRACTED | `structured_labs_v1.py` PF computation (PRs #226–#228) |
| 5 | **Chest tube placement (date/time/output)** | Airway | MISSING | LDA CHEST_TUBE defined; text extraction needed |
| 6 | ~~Sex~~ | Demographics | ✅ EXTRACTED | `demographics_v1.sex` (PRs #222–#225) |
| 7 | **ICP (intracranial pressure)** | Vital Signs | MISSING | Flowsheet row or note section pattern matching |
| 8 | ~~Discharge disposition~~ | Disposition | ✅ EXTRACTED | `demographics_v1.discharge_disposition` (PRs #222–#225) |
| 9 | **Mental health screening** | Screening | MISSING | Pattern matching in nursing assessment / social work notes |
| 10 | **Antibiotic administration (type, time)** | Pharmacologic | MISSING | MAR section antibiotic pattern matching |

---

## Completed PR Slices

### Slice A — ✅ COMPLETE: Sex + Discharge Disposition Extraction (PRs #222–#225)

| Element | Source | Status |
|---------|--------|--------|
| Sex | Header SEX field + HPI fallback (`_extract_sex_hpi_fallback()`) | ✅ Merged |
| Discharge disposition | `patient_movement_v1.summary.discharge_disposition_final` | ✅ Merged |

### Slice B — ✅ COMPLETE: Blood Product Transfusion Extraction (PRs #229–#231)

| Element | Source | Status |
|---------|--------|--------|
| MTP activation | Operative / ED note pattern detection | ✅ Merged |
| pRBC units transfused | MAR section blood product row parsing | ✅ Merged |
| FFP units transfused | MAR section FFP row parsing | ✅ Merged |
| Platelet units transfused | MAR section platelet row parsing | ✅ Merged |
| TXA administration | MAR / note `tranexamic acid` / `TXA` pattern | ✅ Merged |
| Cryoprecipitate | MAR section cryoprecipitate row parsing | ✅ Merged |

### Slice C — ✅ COMPLETE: Structured Lab Value Parsing (PRs #226–#228, #232)

| Element | Source | Status |
|---------|--------|--------|
| CBC components (H/H, WBC, platelets) | LAB section flowsheet parsing | ✅ Merged |
| BMP components (Na, K, Cr, glucose, etc.) | LAB section flowsheet parsing | ✅ Merged |
| Full coag panel (PT/INR, PTT, fibrinogen) | LAB section flowsheet parsing | ✅ Merged |
| ABG components (pH, pCO2, pO2, BD, lactate) | LAB section flowsheet parsing | ✅ Merged |
| PaO2/FiO2 ratio computation | ABG pO2 + flowsheet FiO2 | ✅ Merged |
| Troponin value parsing | LAB section cardiac panel | ✅ Merged |

---

## Appendix: Category Coverage Heat Map

```
Category                                     Coverage  Bar
──────────────────────────────────────────── ─────── ──────────────────────
19 · Complications / NTDS Events               100%   ████████████████████
20 · Operational / Call Panel (excl N/A)        100%   ████████████████████
 6 · Neurologic Assessment                      89%   █████████████████▊
 1 · Demographics / Patient Identification      86%   █████████████████▏
14 · Infection Prevention / HAI Monitoring      82%   ████████████████▍
 5 · Vital Signs / Hemodynamic Monitoring       80%   ████████████████
 8 · Imaging / Radiology                        75%   ███████████████
 7 · Laboratory / Diagnostics                   69%   █████████████▊
18 · Disposition / Discharge Planning           67%   █████████████▍
16 · Screening / Behavioral Health              64%   ████████████▊
11 · Operative / Procedural                     58%   ███████████▌
15 · Prophylaxis (DVT / GI / Hypothermia)       57%   ███████████▍
 9 · Airway / Respiratory                       56%   ███████████
12 · Pharmacologic Interventions                56%   ███████████
10 · Resuscitation / Blood Products             50%   ██████████
13 · Device / Line Management                   50%   ██████████
 4 · Emergency Department Assessment            44%   ████████▊
17a· Special Populations — Geriatric            29%   █████▊
 3 · Injury Mechanism / Classification          20%   ████
 2 · Prehospital / EMS                          14%   ██▊
17b· Special Populations — Pediatric             0%   ▏
17c· Special Populations — Obstetric             0%   ▏
```

> **Strongest areas:** NTDS event adjudication (21/21 events), demographics
> (6/7 actionable), neurologic assessment, and infection prevention.
>
> **Most improved:** Resuscitation (0% → 50%), Airway (33% → 56%),
> Demographics (71% → 86%), Disposition (56% → 67%).
>
> **Weakest areas:** Special populations (0 of 20 across 17b pediatric /
> 17c obstetric), prehospital (1 of 7 actionable), and injury mechanism
> classification (2 of 10 actionable).

---

_End of document._
