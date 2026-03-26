# Protocol Extraction Completion Ledger — v1

| Field       | Value |
|-------------|-------|
| Date        | 2026-03-21 |
| Baseline    | main (post PR #278) |
| Source       | Codebase audit + raw-file scan of 6 gate patients |
| Reference   | `docs/audits/PROTOCOL_DATA_COVERAGE_MAPPING_v1.md` (230 elements, 20 categories) |

> **Purpose:** Factual completion ledger for protocol data extraction.
> Maps each element to its current extraction status, downstream usability,
> docs accuracy, and remaining work. Complements the coverage mapping with
> operational detail.

---

## Status Definitions

| Status | Meaning |
|--------|---------|
| **extracted and usable** | Extractor exists, output wired to at least one downstream consumer (renderer, NTDS, protocol engine) |
| **extracted but under-documented** | Extractor exists and is usable, but docs are stale or incomplete |
| **extracted but not rendered/usable** | Extractor exists and outputs to patient_features_v1.json, but no renderer or downstream system consumes the output |
| **partially extracted** | Extraction infrastructure exists (module, mapper key) but output is incomplete — missing subfields, timing, classification, or structured values |
| **missing extraction** | No extraction logic exists; raw cohort evidence is available |
| **no current cohort evidence** | No extraction logic exists AND raw data for this element is absent or insufficient in current 39-patient cohort |

---

## Ledger: Extracted and Usable (65 elements)

These elements are extracted AND consumed by at least one downstream system (v5 renderer, NTDS engine, or v4 renderer).

| Element | Extractor / Module | Downstream Consumer | Docs Accurate? | Notes |
|---------|-------------------|---------------------|----------------|-------|
| Patient name / MRN | Ingestion pipeline | v5 header | Yes | — |
| Date of birth / Age | `age_extraction_v1.py` | v5 demographics | Yes | — |
| Admission date/time | `adt_transfer_timeline_v1.py` | v5 timeline | Yes | — |
| Trauma activation category | `category_activation_v1.py` | v5 activation | Yes | — |
| Sex | `build_patient_features_v1.py` → `demographics_v1.sex` | v5 partial | Yes | Sex stored but not always rendered in output text |
| Mechanism of injury narrative | `mechanism_region_v1.py` | v5 mechanism | Yes | — |
| Blunt vs. penetrating classification | `mechanism_region_v1.py` | v5 mechanism | Yes | — |
| Body region(s) involved | `mechanism_region_v1.py` | v5 mechanism | Yes | — |
| ED arrival date/time | `adt_transfer_timeline_v1.py` | v5 timeline | Yes | — |
| Triage category | `category_activation_v1.py` | v5 activation | Yes | — |
| FAST exam (positive/negative) | `fast_exam_v1.py` | v5 FAST | Yes | — |
| ED disposition time | `adt_transfer_timeline_v1.py` | v5 timeline | Yes | — |
| Blood pressure (systolic/diastolic/MAP) | `vitals_canonical_v1.py` | v5 vitals | Yes | — |
| Heart rate | `vitals_canonical_v1.py` | v5 vitals | Yes | — |
| Respiratory rate | `vitals_canonical_v1.py` | v5 vitals | Yes | — |
| SpO2 (pulse oximetry) | `vitals_canonical_v1.py` | v5 vitals | Yes | — |
| Temperature (core) | `vitals_canonical_v1.py` | v5 vitals | Yes | — |
| GCS (total + E/V/M components) | `gcs_daily.py` | v4 + v5 neuro | Yes | v5 uses neuro_trigger primary, gcs_daily fallback |
| Shock index (HR/SBP) | `shock_trigger_v1.py` | v5 shock trigger | Yes | SI classification in trigger_vitals |
| Spinal clearance status | `spine_clearance_v1.py` | v5 spine | Yes | — |
| Base deficit (serial) | `base_deficit_monitoring_v1.py` | v5 shock trigger | Yes | Consumed by shock trigger logic |
| Blood culture results | `clabsi_blood_culture_positive` mapper | E06 NTDS | Yes | — |
| Urine culture results | `cauti_culture_positive` mapper | E05 NTDS | Yes | — |
| Urine drug screen / BAL | `etoh_uds_v1.py` | v5 screening | Yes | — |
| CBC (H/H, WBC, platelets) | `structured_labs_v1.py` | v4 labs_panel_daily | Yes | v4 simplified; full panel in features JSON |
| BMP (Na, K, Cl, CO2, BUN, Cr, glucose) | `structured_labs_v1.py` | v4 labs_panel_daily | Yes | — |
| Coagulation panel (PT/INR, PTT, fibrinogen) | `structured_labs_v1.py` | v4 labs_panel_daily | Yes | — |
| ABG (pH, pCO2, pO2, base deficit, lactate) | `structured_labs_v1.py` | v4 labs_panel_daily | Yes | — |
| Lactate (serial) | `structured_labs_v1.py` | v4 labs_panel_daily | Yes | — |
| Serum creatinine (baseline + serial) | `structured_labs_v1.py` | v4 labs_panel_daily | Yes | — |
| Troponin | `structured_labs_v1.py` | v4 labs_panel_daily | Yes | — |
| FAST/eFAST (imaging) | `fast_exam_v1.py` | v5 FAST | Yes | — |
| PaO2/FiO2 ratio | `structured_labs_v1.py` | v4 labs_panel_daily | Yes | Computed from ABG pO2 + flowsheet FiO2 |
| Surgical complications | SSI mapper keys | E07/E11/E17 NTDS | Yes | — |
| Unplanned return to OR | `or_return_unplanned` mapper | E20 NTDS | Yes | — |
| GI prophylaxis agent | `gi_prophylaxis_v1.py` | v5 + NTDS | Yes | — |
| VTE chemoprophylaxis | `dvt_prophylaxis_v1.py` | v5 + NTDS | Yes | — |
| CAUTI diagnosis (CDC criteria) | E05 rule (6 gates + LDA) | NTDS engine | Yes | — |
| CLABSI diagnosis (NHSN criteria) | E06 rule (5 gates + LDA) | NTDS engine | Yes | — |
| SSI — superficial | E17 rule | NTDS engine | Yes | — |
| SSI — deep | E07 rule | NTDS engine | Yes | — |
| SSI — organ/space | E11 rule | NTDS engine | Yes | — |
| VAP diagnosis | E21 rule (3 gates + LDA) | NTDS engine | Yes | — |
| Sepsis / severe sepsis | E15 rule | NTDS engine | Yes | — |
| DVT prophylaxis — chemical | `dvt_prophylaxis_v1.py` | v5 prophylaxis | Yes | — |
| GI prophylaxis (PPI/H2 blocker) | `gi_prophylaxis_v1.py` | v5 prophylaxis | Yes | — |
| SBIRT screening completed | `sbirt_screening_v1.py` | v5 screening | Yes | — |
| SBIRT screening result | `sbirt_screening_v1.py` | v5 screening | Yes | — |
| Blood alcohol level (BAL) | `etoh_uds_v1.py` | v5 screening | Yes | — |
| Urine drug screen result | `etoh_uds_v1.py` | v5 screening | Yes | — |
| ICU admission (planned vs. unplanned) | `unplanned_icu` mapper | E18 NTDS | Yes | — |
| ICU LOS (days) | `patient_movement_v1.py` | v5 movement | Yes | icu_los_hours, icu_los_days in summary |
| Discharge disposition | `demographics_v1.discharge_disposition` | v5 disposition | Yes | — |
| E01 AKI (KDIGO Stage 3) | E01 rule (3+ gates) | NTDS engine | Yes | — |
| E03 Alcohol Withdrawal | E03 rule | NTDS engine | Yes | — |
| E04 Cardiac Arrest | E04 rule | NTDS engine | Yes | — |
| E08 DVT | E08 rule | NTDS engine | Yes | — |
| E09 Delirium | E09 rule | NTDS engine | Yes | Known false negatives (AUD-002) |
| E10 MI | E10 rule | NTDS engine | Yes | — |
| E12 Osteomyelitis | E12 rule | NTDS engine | Yes | — |
| E13 Pressure Ulcer | E13 rule | NTDS engine | Yes | — |
| E14 PE | E14 rule | NTDS engine | Yes | — |
| E16 Stroke/CVA | E16 rule | NTDS engine | Yes | — |
| E18 Unplanned ICU | E18 rule | NTDS engine | Yes | — |
| E19 Unplanned Intubation | E19 rule | NTDS engine | Yes | — |
| E20 Unplanned Return to OR | E20 rule | NTDS engine | Yes | — |

---

## Ledger: Extracted but Under-Documented (0 elements)

No elements currently carry this status. The tier is retained in the taxonomy
for future use — any element whose extractor is usable but whose docs are
stale or incomplete should be classified here.

---

## Ledger: Extracted but Not Rendered/Usable (5 elements)

These features are extracted into patient_features_v1.json but have **no downstream renderer or consumer**. They represent visibility gaps — the extraction work is done but the data is not surfaced.

| Element | Extractor / Module | Where It Stops | Usable? | Docs Accurate? | Remaining Work | Likely Files |
|---------|-------------------|----------------|---------|----------------|----------------|--------------|
| Seizure prophylaxis (agent, start, duration) | `seizure_prophylaxis_v1.py` | stored in features JSON | No — not rendered | Yes (extraction) | Wire into v5 renderer | `cerebralos/reporting/render_trauma_daily_notes_v5.py` |
| Antibiotic administration (type, time) | `antibiotic_admin_v1.py` | stored in features JSON | No — not rendered | Yes (extraction) | Wire into v5 renderer | `cerebralos/reporting/render_trauma_daily_notes_v5.py` |
| Transfusion / blood products (MTP, pRBC, FFP, TXA, Cryo) | `transfusion_blood_products_v1.py` | stored in features JSON | No — not rendered | Yes (extraction) | Wire into v5 renderer | `cerebralos/reporting/render_trauma_daily_notes_v5.py` |
| Ventilator mode / settings (FiO2, PEEP, Vt, RR, mode) | `ventilator_settings_v1.py` | stored in features JSON | No — not rendered | Yes (extraction) | Wire into v5 renderer | `cerebralos/reporting/render_trauma_daily_notes_v5.py` |
| Structured labs full panels (CBC, BMP, Coag, ABG) | `structured_labs_v1.py` | stored in features JSON; v4 uses simplified `labs_panel_daily` | Partial — simplified version in v4 | Yes | Wire full panel view into v5 renderer | `cerebralos/reporting/render_trauma_daily_notes_v5.py` |

---

## Ledger: Partially Extracted (46 elements)

Extraction infrastructure exists but output is incomplete — missing subfields, type/site classification, timing, or structured values.

| Element | What Exists | What's Missing | Status | Docs Accurate? | Remaining Work | Likely Files |
|---------|-------------|----------------|--------|----------------|----------------|--------------|
| Transferring facility | `adt_transfer_timeline_v1.py` detects transfers | Facility name not structured | partially extracted | Yes | Parse facility name from ADT section | `cerebralos/features/adt_transfer_timeline_v1.py` |
| Serial vital sign compliance | `vitals_canonical_v1.py` captures readings | Compliance gap detection not implemented | partially extracted | Yes | Add frequency-based compliance gate | `cerebralos/features/vitals_canonical_v1.py` |
| GCS post-resuscitation | `gcs_daily.py` captures GCS | Post-resuscitation timing not determined | partially extracted | Yes | Link GCS to post-CPR/intubation events | `cerebralos/features/gcs_daily.py` |
| Pupil reactivity (bilateral) | `neuro_trigger_v1.py` captures mentions | Bilateral/reactive status not classified | partially extracted | Yes | Classify reactive vs fixed vs sluggish | `cerebralos/features/neuro_trigger_v1.py`, PR #259 pending |
| Motor exam (lateralizing signs) | `neuro_trigger_v1.py` captures motor | Lateralizing LEFT vs RIGHT not classified | partially extracted | Yes | Extract laterality + grade | `cerebralos/features/neuro_trigger_v1.py` |
| Sensory exam (dermatome level) | `spine_clearance_v1.py` captures mentions | Dermatome level not structured | partially extracted | Yes | Parse C5/L4 patterns | `cerebralos/features/spine_clearance_v1.py` |
| NEXUS / C-Spine criteria | `spine_clearance_v1.py` may capture | Criteria not scored | partially extracted | Yes | Implement NEXUS 5-gate scorer | `cerebralos/features/spine_clearance_v1.py` |
| Delirium screening (CAM-ICU score) | `delirium_dx` mapper | CAM-ICU/bCAM scores not structured | partially extracted | Yes | Extract RASS/CAM-ICU from flowsheet | `rules/mappers/epic_deaconess_mapper_v1.json` |
| Mental status changes | `neuro_trigger_v1.py` captures AMS | Not classified by type | partially extracted | Yes | Add confusion/agitation/lethargy classifier | `cerebralos/features/neuro_trigger_v1.py` |
| CT head | `radiology_findings_v1.py` captures imaging | Not CT-head-specific | partially extracted | Yes | Add CT type classifier on report headers | `cerebralos/features/radiology_findings_v1.py` |
| CT cervical spine | `radiology_findings_v1.py` + `spine_clearance_v1.py` | Not specifically classified | partially extracted | Yes | Multi-modality classifier | `cerebralos/features/radiology_findings_v1.py` |
| CT chest/abdomen/pelvis | `radiology_findings_v1.py` captures imaging | Region not parsed separately | partially extracted | Yes | Region-aware parsing | `cerebralos/features/radiology_findings_v1.py` |
| CTA neck/chest | `radiology_findings_v1.py` captures CTA | Not classified by target | partially extracted | Yes | Modality + target classifier | `cerebralos/features/radiology_findings_v1.py` |
| Plain films (chest, pelvis, extremity) | `radiology_findings_v1.py` captures x-ray | Not modality-structured | partially extracted | Yes | Modality detection (XR vs CT vs MRI) | `cerebralos/features/radiology_findings_v1.py` |
| Angiography (diagnostic vs interventional) | `radiology_findings_v1.py` may capture | Not procedural-specific | partially extracted | Yes | Diagnostic vs interventional classifier | `cerebralos/features/radiology_findings_v1.py` |
| MRI spine | `radiology_findings_v1.py` captures MRI | Not spine-specific | partially extracted | Yes | Body-part classification | `cerebralos/features/radiology_findings_v1.py` |
| Chest X-ray (serial) | `vap_cxr` mapper (VAP context only) | Generic CXR not structured | partially extracted | Yes | Separate VAP CXR from protocol CXR | `cerebralos/features/radiology_findings_v1.py` |
| Intubation (date/time/indication) | `unplanned_intubation` mapper; `note_index_events_v1` | Date/time not fully structured | partially extracted | Yes | Structured timestamp extraction | `cerebralos/features/note_index_events_v1.py` |
| Ventilator days | LDA vent-duration gate (feature-flagged) | Duration in NTDS engine; not exposed in features | partially extracted | Yes | Expose vent-day count to features JSON | `cerebralos/features/lda_events_v1.py` |
| Oxygen supplementation type/FiO2 | `incentive_spirometry_v1.py` captures IS | Generic O2 delivery mode not parsed | partially extracted | Yes | Flowsheet O2 delivery mode parser | `cerebralos/features/incentive_spirometry_v1.py` |
| Procedure type / CPT | `procedure_operatives_v1.py` captures mentions | CPT not extracted | partially extracted | Yes | Procedure name → CPT mapping | `cerebralos/features/procedure_operatives_v1.py` |
| Procedure date/time | `procedure_operatives_v1.py` captures timing | OR start/end time not fully structured | partially extracted | Yes | Operative note timestamp parser | `cerebralos/features/procedure_operatives_v1.py` |
| Anesthesia type / duration | `anesthesia_case_metrics_v1.py` partial | Regional vs general not classified | partially extracted | Yes | Anesthesia type classification | `cerebralos/features/anesthesia_case_metrics_v1.py` |
| Operative findings | `procedure_operatives_v1.py` captures text | Findings not classified | partially extracted | Yes | Injury/repair classification | `cerebralos/features/procedure_operatives_v1.py` |
| Spinal stabilization surgery timing | `spine_clearance_v1.py` captures mention | Time-from-injury not computed | partially extracted | Yes | Link to trauma mechanism datetime | `cerebralos/features/spine_clearance_v1.py` |
| Anticoagulant reversal agents | `anticoag_context_v1.py` captures mentions | Reversal agents not structured | partially extracted | Yes | Pattern + dose extraction for 4F-PCC, vitamin K, etc. | `cerebralos/features/anticoag_context_v1.py` |
| Pre-injury anticoagulant/antiplatelet list | `pmh_social_allergies_v1.py` + `anticoag_context_v1.py` | Medication list not fully structured | partially extracted | Yes | Harmonize medication parsing | `cerebralos/features/pmh_social_allergies_v1.py` |
| Central venous catheter (type, site, date) | `lda_events_v1.py`; `clabsi_central_line_in_place` mapper | Type/site not structured | partially extracted | Yes | CVC type + site classifier | `cerebralos/features/lda_events_v1.py` |
| Central line duration (days) | LDA duration gate (feature-flagged) | Feature-flagged; exercised for E06 only | partially extracted | Yes | Expose duration to features | `cerebralos/features/lda_events_v1.py` |
| Urinary catheter placement date | `lda_events_v1.py`; `cauti_catheter_in_place` mapper | Placement date not structured | partially extracted | Yes | Foley timestamp extraction | `cerebralos/features/lda_events_v1.py` |
| Urinary catheter duration (days) | LDA duration gate (feature-flagged) | Feature-flagged; exercised for E05 only | partially extracted | Yes | Expose duration to features | `cerebralos/features/lda_events_v1.py` |
| Mechanical ventilation (start/end date) | `ventilator_settings_v1.py` + LDA logic | Start/end timestamps not structured | partially extracted | Yes | Parse ETT placement/extubation timestamps | `cerebralos/features/lda_events_v1.py` |
| Sequential compression devices (SCDs) | `dvt_prophylaxis_v1.py` may capture | SCD start date + compliance not structured | partially extracted | Yes | SCD-specific pattern + timestamp | `cerebralos/features/dvt_prophylaxis_v1.py` |
| Pressure ulcer (stage, location, date) | `pressure_ulcer_dx` mapper | Stage/location/date not structured | partially extracted | Yes | Staging + anatomic location classifier | `rules/mappers/epic_deaconess_mapper_v1.json` |
| Infection source identification | E05/E06 culture results per-event | Generic source not classified | partially extracted | Yes | Source classification gate | `rules/mappers/epic_deaconess_mapper_v1.json` |
| DVT prophylaxis contraindication | `dvt_prophylaxis_v1.py` may capture | Not explicitly structured | partially extracted | Yes | Verify excluded_reason field | `cerebralos/features/dvt_prophylaxis_v1.py` |
| SBIRT brief intervention provided | `sbirt_screening_v1.py` captures screening | Intervention not parsed | partially extracted | Yes | Intervention action extraction | `cerebralos/features/sbirt_screening_v1.py` |
| SBIRT referral to treatment | `sbirt_screening_v1.py` captures screening | Referral not extracted | partially extracted | Yes | Referral documentation matcher | `cerebralos/features/sbirt_screening_v1.py` |
| Social work consult ordered | `consultant_events_v1.py` may capture | Not SBIRT-specific | partially extracted | Yes | Tag social work → SBIRT link | `cerebralos/features/consultant_events_v1.py` |
| Pre-injury anticoagulant use (geriatric) | `pmh_social_allergies_v1.py` + `anticoag_context_v1.py` | Medication specifics not structured | partially extracted | Yes | Dose + frequency extraction | `cerebralos/features/pmh_social_allergies_v1.py` |
| Geriatric consult | `consultant_events_v1.py` may capture | Not geriatric-protocol-linked | partially extracted | Yes | Tag geriatric → age + protocol trigger | `cerebralos/features/consultant_events_v1.py` |
| Hospital LOS (days) | `adt_transfer_timeline_v1.py` captures admit/discharge | LOS not computed as explicit field | partially extracted | Yes | Compute discharge_ts − admission_ts | `cerebralos/features/adt_transfer_timeline_v1.py` |
| Discharge date/time | DISCHARGE section parsed | Date/time not always structured | partially extracted | Yes | Parse discharged timestamp | `cerebralos/features/adt_transfer_timeline_v1.py` |
| Transfer destination (facility, level) | `adt_transfer_timeline_v1.py` captures transfers | Destination facility not classified | partially extracted | Yes | Facility type classifier (SNF, rehab, home) | `cerebralos/features/adt_transfer_timeline_v1.py` |
| ARDS (Berlin criteria — P/F components) | E02 rule: `ards_dx` + `ards_onset` | P/F ratio threshold not applied as ARDS gate | partially extracted | Yes | Wire P/F ratio from structured_labs into E02 gate | `rules/ntds/logic/2026/02_ards.json` |

---

## Ledger: Missing Extraction (22 elements with cohort evidence)

Raw cohort evidence exists but no extraction logic is implemented.

| Element | Cohort Evidence? | Evidence Quality | Remaining Work | Likely Files |
|---------|-----------------|------------------|----------------|--------------|
| Radiology study classification (CT type: head, c-spine, chest/abd/pelvis) | Yes — 100% of patients | Excellent — standardized headers | Build CT type classifier from report headers | `cerebralos/features/radiology_findings_v1.py` |
| Prehospital narrative | Yes — sparse (~2/6 with detail) | Inconsistent — narrative-embedded in H&P | Pattern match EMS/transport details | `cerebralos/features/` (new module) |
| Intubation indication (airway vs respiratory vs AMS) | Yes — documented in ED/airway notes | Moderate — free-text pattern matching | Pattern matching in ED/TRAUMA_HP/ANESTHESIA | `cerebralos/features/` (new module) |
| Extubation date/time/reason | Yes — documented in daily notes | Moderate — event extraction | Flowsheet vent status or note narrative | `cerebralos/features/lda_events_v1.py` |
| Mental health screening (depression, PTSD risk) | Yes — social work / behavioral health notes | Moderate — consult note pattern matching | Pattern match in CONSULT_NOTE | `cerebralos/features/` (new module) |
| Functional status at discharge | Yes — PT/OT discharge summaries | Moderate — PT/OT note parsing | PT/OT progress note extraction | `cerebralos/features/` (new module) |
| Shock type classification (hemorrhagic vs cardiogenic) | Yes — physician assessment | Moderate — classification logic | Pattern match in assessment | `cerebralos/features/shock_trigger_v1.py` |
| Rhabdomyolysis (CK levels) | Yes — lab results when suspected | Moderate — CK lab parsing | LAB section chemistry | `cerebralos/features/structured_labs_v1.py` |
| Hyperglycemia (glucose > 180) | Yes — BMP glucose available | Easy — threshold gate | BMP glucose component already extracted | `cerebralos/features/structured_labs_v1.py` |
| Anemia (Hgb < 7) | Yes — CBC Hgb available | Easy — threshold gate | CBC Hemoglobin already extracted | `cerebralos/features/structured_labs_v1.py` |
| Hypothermia (core temp < 32°C) | Yes — temperature recorded | Easy — threshold gate | Vitals temperature already extracted | `cerebralos/features/vitals_canonical_v1.py` |
| Hyperthermia (temp > 39°C) | Yes — temperature recorded | Easy — threshold gate | Vitals temperature already extracted | `cerebralos/features/vitals_canonical_v1.py` |
| Coagulopathy (INR/PTT abnormal) | Yes — coag panel available | Easy — threshold gate | Coag panel already extracted | `cerebralos/features/structured_labs_v1.py` |
| DNR / code status | Yes — admission documentation | Easy — pattern match | PMH/admissions section | `cerebralos/features/` (new or existing) |
| Geriatric fall risk screening | Yes — present in age > 65 + fall mechanism | Moderate — geriatric consult pattern | Geriatric consult notes | `cerebralos/features/` (new module) |
| Geriatric pre-morbid functional status | Yes — documented in H&P for elderly | Hard — narrative "lives alone", "uses walker" | TRAUMA_HP social history | `cerebralos/features/pmh_social_allergies_v1.py` |
| Aspiration pneumonia diagnosis | Yes — documented in assessment | Moderate — pattern matching | PHYSICIAN_NOTE assessment | `cerebralos/features/` (new module) |
| Electrolyte abnormality classification | Yes — BMP results available | Moderate — multi-threshold logic | BMP components already extracted | `cerebralos/features/structured_labs_v1.py` |
| Mechanism scoring (ISS) | Maybe — ISS sometimes in H&P | Hard — requires ICD coding | TRAUMA_HP impression | `cerebralos/features/` (new module) |
| Sepsis bundle compliance | Yes — component data exists (labs, cultures, MAR) | Hard — multi-gate timestamp logic | LAB + CULTURE + MAR sections | Cross-module integration |
| Oliguric vs non-oliguric classification | Yes — urine output documented | Moderate — threshold gate (UOP < 0.5 mL/kg/hr) | Urine output already extracted | `cerebralos/features/urine_output_events_v1.py` |
| Stress ulcer bleeding (GI bleed event) | Yes — documented as complication | Moderate — GI bleed diagnosis pattern | PHYSICIAN_NOTE assessment | `cerebralos/features/` (new module) |

---

## Ledger: No Current Cohort Evidence (48 elements)

These elements are either absent from the Epic `.txt` export, not relevant to the current 39-patient adult trauma cohort, or not documented in the raw files. Extraction should NOT be prioritized.

| Element | Category | Reason |
|---------|----------|--------|
| **ICP (intracranial pressure)** | Vital Signs | **No current cohort evidence.** Verified across 6 patients including cases with large frontal ICH and acute/chronic SDH. Only historical EVD references found ("history of previous... EVD and prolonged hospitalization"). No active ICP monitoring values present. Institutional policy may not export ICP flowsheet data to Epic `.txt`. **Do not prioritize.** |
| Chest tube placement (date/time/output) | Airway | **No current cohort evidence.** Verified via cohort-wide search: zero mentions of "chest tube", "thoracostomy", or "chest drain" across all 39 patient files. LDA CHEST_TUBE type is defined in `lda_events_v1.py` infrastructure but no patients trigger it. Even the patient with T8 + rib fractures (5–7, 9–10) has no chest tube documented. |
| Prehospital vital signs (field vitals) | EMS | Rarely in Epic `.txt` export — prehospital vitals not integrated |
| Prehospital interventions (IV, medications, airway) | EMS | EMS documentation sparse in Epic `.txt` — narrative format only |
| Prehospital GCS | EMS | Not documented as structured field in current cohort |
| EMS transport time | EMS | Not present in Epic `.txt` export |
| Timing compliance metrics (door-to-X) | Operational | Not documented in raw files — no "within 30 min" or "door-to-CT" language found |
| Frailty assessment (formal) | Geriatric | Rarely explicit in current trauma cohort |
| Immunization status (tetanus) | Infection Prevention | Not standard in Epic `.txt` acute trauma export |
| WHO Surgical Safety Checklist | Operative | Quality reporting only — not in narrative export |
| Organ donation consent | Disposition | Separate workflow — not in narrative export |
| Antimicrobial stewardship (de-escalation timing) | Infection Prevention | Not standard outcome in Epic `.txt` |
| Pediatric trauma score (PTS) | Special Pop — Pediatric | No pediatric patients in current 39-patient cohort |
| Pediatric weight-based dosing | Special Pop — Pediatric | No pediatric patients |
| Pediatric GCS (modified) | Special Pop — Pediatric | No pediatric patients |
| Pediatric vital sign norms | Special Pop — Pediatric | No pediatric patients |
| Pediatric C-spine assessment | Special Pop — Pediatric | No pediatric patients |
| Pediatric non-accidental trauma screening | Special Pop — Pediatric | No pediatric patients |
| Pediatric family-centered care | Special Pop — Pediatric | No pediatric patients |
| Maternal trauma (mechanism-specific) | Special Pop — Obstetric | No obstetric patients in current cohort |
| Fetal heart tones / monitoring | Special Pop — Obstetric | No obstetric patients |
| Rh factor / Kleihauer-Betke | Special Pop — Obstetric | No obstetric patients |
| Gestational age assessment | Special Pop — Obstetric | No obstetric patients |
| OB consult / NICU activation | Special Pop — Obstetric | No obstetric patients |
| Perimortem C-section criteria | Special Pop — Obstetric | No obstetric patients |
| Geriatric medication reconciliation (polypharmacy) | Geriatric | Partially captured in PMH; no formal polypharmacy scoring |
| Geriatric advanced directives | Geriatric | Partially captured; formal directive not structured |
| Geriatric nutritional status | Geriatric | Not consistently documented in current cohort |
| Geriatric delirium prevention protocol | Geriatric | Protocol adherence not documented as structured field |
| Reintubation (episodes, reason, timing) | Airway | May exist in complex cases; not verified as prevalent |
| Ventilator day compliance | Airway | Implicit in vent days; protocol timing gate not documented |
| Chest tube removal date | Airway | No chest tubes in current cohort |
| Chest tube output (daily trends) | Airway | No chest tubes in current cohort |
| Hypokalemia with cardiac dysrhythmia | Laboratory | Correlation gate (K < 3.0 + EKG) — complex, low prevalence |
| Acute coronary syndrome (ECG + troponin) | Laboratory | Multi-gate; EKG section parsing not built |
| Perforated viscus | Operative | Surgical finding — rare |
| Necrotizing soft tissue infection | Operative | Surgical finding — rare |
| Immune suppression (transplant, asplenia) | Infection Prevention | PMH keyword matching possible but low prevalence |
| Pandemic-related protocols | Operational | Not present in 2025–2026 cohort |
| Goals-of-care discussion | Disposition | Maybe present in complex cases; inconsistent |
| Trauma activation decline reason | ED Assessment | Rarely documented |
| E-field data (paramedic PCR import) | EMS | Not in Epic `.txt` |
| Skin assessment (admission baseline) | Nursing | Not consistently structured |
| Pain assessment (protocol-based) | Nursing | Scores present but protocol compliance not structured |
| Nutritional screening (MUST/NRS-2002) | Nursing | Not consistently documented |
| Mobility assessment (AM-PAC) | Nursing | Not consistently documented |
| Fall risk assessment (Morse scale) | Nursing | Not consistently documented |
| Sleep quality / ICU delirium bundle | Nursing | Not consistently documented |

---

## High-Confidence Next Actions (Ranked)

Based on: (1) raw evidence availability, (2) protocol compliance impact, (3) implementation simplicity.

| Rank | Action | Type | Impact | Complexity |
|------|--------|------|--------|------------|
| 1 | **Renderer visibility: wire seizure prophylaxis, antibiotic admin, transfusion, vent settings, structured labs into v5 renderer** | Renderer wiring | High — 5 features extracted but invisible | Small per feature (template additions) |
| 2 | **Radiology study classification** — build CT type classifier from standardized report headers (100% cohort coverage, excellent evidence quality) | New extractor | High — 8 PARTIAL imaging elements unblocked | Small — regex on report headers |
| 3 | **Central line type/site/date** — parse PICC vs CVL, insertion site from LDA section and procedure notes | Extractor enhancement | Medium — CLABSI adjudication improvement | Medium — sparse but structured when present |
| 4 | **Lab threshold alerting** — hyperglycemia, anemia, coagulopathy, hypothermia/hyperthermia gates using already-extracted lab/vital values | Threshold gates | Medium — 5 missing elements closed with minimal code | Small — values already extracted |
| 5 | **E02 ARDS P/F ratio gate** — wire existing PaO2/FiO2 computation into E02 rule as Berlin criteria threshold | Rule enhancement | Medium — ARDS event adjudication improvement | Small — data exists, wire to rule |

**Explicit deferral:** ICP extraction has no current cohort evidence and should not be prioritized. Chest tube extraction has defined LDA infrastructure but zero cohort evidence. Both should wait until cohort expansion provides raw data.

**Protected-engine note:** LDA gate default enablement for broader events beyond E05/E06/E21, and protocol-engine consumer disconnect from patient_features_v1.json, are future-fix-track items requiring engine-change authorization. They are documented here for completeness but are not active in-scope implementation work.

---

_End of document._
