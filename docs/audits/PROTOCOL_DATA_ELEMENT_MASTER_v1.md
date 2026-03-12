# Protocol Data Element Master List — v1

| Field       | Value |
|-------------|-------|
| Source       | Claude analysis of all 51 Deaconess Trauma Center protocol PDFs |
| Generated   | 2026-03-12 |
| Protocol count | 51 total (43 structured/evaluable + 8 administrative/call panel) |
| Missing PDFs | None — SBIRT and Orthopedic/Neurologic Splint PDFs fixed and ingested |
| Structured file | `rules/deaconess/protocols_deaconess_structured_v1.json` (v1.1.0, 43 protocols) |

> **Purpose:** Comprehensive inventory of every data element referenced or
> required across the Deaconess trauma protocol set. Organized by clinical
> category. Each element lists the protocol(s) that reference it and any
> extraction notes relevant to CerebralOS coverage mapping.
>
> **Coverage status:** This document captures *what* data elements exist.
> Mapping each element to current CerebralOS extraction coverage is a
> separate backlog item ("Protocol Data Coverage Mapping" — NOT STARTED).

---

## 1. Demographics / Patient Identification

| Element | Notes / Protocols |
|---------|-------------------|
| Patient name / MRN | All protocols — patient identification |
| Date of birth / Age | Geriatric Trauma (≥65), Geriatric Hip Fracture (≥65), DVT Prophylaxis Pediatric (≤17), Pediatric Special Consideration (≤14), NAT (≤14), Obstetrical (gestation) |
| Sex | All protocols — demographic baseline |
| Race / Ethnicity | Registry requirement — not protocol-specific |
| Admission date/time | All protocols — timeline anchor |
| Trauma activation category | Activation Process; Definition of Trauma Patient; Base Deficit Monitoring (Cat I only) |
| Attending trauma surgeon | Trauma Team Attending Requirements; Trauma Surgeon Call Panel |
| Transferring facility | Transfer TO/FROM Deaconess Midtown |

---

## 2. Prehospital / EMS

| Element | Notes / Protocols |
|---------|-------------------|
| EMS run number / agency | Activation Process; all injury protocols (mechanism source) |
| Transport mode (ground/air) | Activation Process; Transfer TO/FROM Deaconess |
| Scene vital signs (BP, HR, RR, SpO2) | Activation Process; Traumatic Arrest; Drowning |
| Prehospital GCS | TBI Management; Traumatic Arrest |
| Prehospital interventions (intubation, IV, tourniquet) | TBI Management; Penetrating protocols; Traumatic Arrest |
| Mechanism of injury narrative | All injury protocols — trigger gate |
| Estimated time of injury | Spinal Clearance (36 h timing); TBI Management |
| Prehospital fluids / blood products | Blood and Blood Product Transfusion; Hypothermia Prevention |

---

## 3. Injury Mechanism / Classification

| Element | Notes / Protocols |
|---------|-------------------|
| Blunt vs. penetrating classification | Blunt Abdominal; Blunt Chest; Penetrating Abdominal; Penetrating Chest; Penetrating Neck; Transmediastinal GSW |
| Body region(s) involved | All injury-specific protocols |
| ICD-10 injury diagnosis codes | Registry requirement — derived from all protocols |
| ISS / AIS scores | Registry requirement — composite from all injuries |
| Injury severity (isolated vs. polytrauma) | Activation Process; Resuscitation Role Assignments |
| Burn mechanism (thermal/chemical/electrical) | Burned Patient Management |
| TBSA (total body surface area burned) | Burned Patient Management |
| Burn depth (superficial/partial/full thickness) | Burned Patient Management |
| Drowning/submersion mechanism | Drowning |
| Hanging/strangulation mechanism | Suspected Hanging Guideline |
| Gunshot wound trajectory | Transmediastinal GSW; Penetrating protocols |
| Fall height / MVC speed | Activation Process; Geriatric Trauma |

---

## 4. Emergency Department Assessment

| Element | Notes / Protocols |
|---------|-------------------|
| ED arrival date/time | All protocols — timeline anchor |
| Triage category (Cat I / Cat II / Consult) | Activation Process; Definition of Trauma Patient; Trauma Surgeon Consult |
| Primary survey (ABCDE) findings | All injury protocols; Resuscitation Role Assignments |
| Secondary survey findings | All injury protocols |
| FAST exam (positive/negative/indeterminate) | Blunt Abdominal Trauma; Penetrating Abdominal Trauma; Obstetrical Trauma |
| Digital rectal exam | Penetrating Abdominal; Pelvic Fractures |
| Wound exploration findings | Penetrating Neck; Penetrating Abdominal |
| Tetanus immunization status | Burned Patient Management; Musculoskeletal Injuries |
| ED disposition time | All protocols — time-to-OR, time-to-ICU |

---

## 5. Vital Signs / Hemodynamic Monitoring

| Element | Notes / Protocols |
|---------|-------------------|
| Blood pressure (systolic/diastolic/MAP) | All injury protocols; Hypothermia Prevention (target MAP) |
| Heart rate | All injury protocols; Traumatic Arrest; Blood Transfusion |
| Respiratory rate | All injury protocols; Drowning; TBI Management |
| SpO2 (pulse oximetry) | All injury protocols; Drowning; Hypothermia |
| Temperature (core) | Hypothermia Prevention (target ≥36°C); Burned Patient Management; all NTDS infection events |
| GCS (total + components E/V/M) | TBI Management (post-resuscitation); Neurosurgical Emergencies; Spinal Clearance |
| Serial vital sign monitoring | Solid Organ Injuries (non-operative); Rib Fracture; Blunt Chest/Abdominal |
| ICP (intracranial pressure) | TBI Management; Neurosurgical Emergencies |
| CPP (cerebral perfusion pressure) | TBI Management (CPP ≥60 mmHg) |
| Shock index (HR/SBP) | Blood and Blood Product Transfusion; Vascular Intervention |

---

## 6. Neurologic Assessment

| Element | Notes / Protocols |
|---------|-------------------|
| GCS post-resuscitation | TBI Management (REQ_TIMING_CRITICAL) |
| Pupil reactivity (bilateral) | TBI Management; Neurosurgical Emergencies |
| Motor exam (lateralizing signs) | TBI Management; Spinal Clearance; Neurosurgical Emergencies |
| Sensory exam (dermatome level) | Spinal Clearance; Musculoskeletal Injuries |
| Spinal clearance status (cleared/not cleared) | Spinal Clearance and Spinal Injury Management |
| NEXUS / Canadian C-Spine criteria | Spinal Clearance |
| Delirium screening (CAM-ICU / bCAM) | Geriatric Trauma; NTDS E09 Delirium |
| Mental status changes | TBI Management; Suspected Hanging; Drowning |
| Seizure activity | TBI Management; Neurosurgical Emergencies |

---

## 7. Laboratory / Diagnostics

| Element | Notes / Protocols |
|---------|-------------------|
| CBC (H/H, WBC, platelets) | Laboratory Studies; Blood Transfusion; all injury protocols |
| BMP (Na, K, Cl, CO2, BUN, Cr, glucose) | Laboratory Studies; AKI monitoring (NTDS E01) |
| Coagulation panel (PT/INR, PTT, fibrinogen) | Laboratory Studies; Anticoagulation Reversal; Blood Transfusion |
| Type and screen / crossmatch | Laboratory Studies; Blood Transfusion |
| ABG (pH, pCO2, pO2, base deficit, lactate) | Base Deficit Monitoring; ROTEM; Blood Transfusion |
| Base deficit (serial) | Base Deficit Monitoring (Cat I, q4-6h until normalized) |
| Lactate (serial) | Base Deficit Monitoring; Blood Transfusion; Sepsis (NTDS E15) |
| ROTEM parameters (EXTEM, FIBTEM, INTEM) | ROTEM Guideline (MTP activation) |
| Serum creatinine (baseline + serial) | AKI monitoring (NTDS E01 — KDIGO Stage 3) |
| Blood culture results | CLABSI (NTDS E06); Sepsis (NTDS E15) |
| Urine culture results | CAUTI (NTDS E05 — ≥10^5 CFU) |
| Urine drug screen / BAL | SBIRT Screening; Laboratory Studies |
| Pregnancy test (urine/serum β-hCG) | Obstetrical Trauma; Laboratory Studies (all females of childbearing age) |
| Troponin | MI monitoring (NTDS E10); Blunt Chest Trauma |
| Procalcitonin | Sepsis (NTDS E15); infection monitoring |
| Thromboelastography (TEG) | Blood Transfusion (adjunct to ROTEM) |

---

## 8. Imaging / Radiology

| Element | Notes / Protocols |
|---------|-------------------|
| CT head | TBI Management; Neurosurgical Emergencies; BCVI screening |
| CT cervical spine | Spinal Clearance; BCVI screening (Denver criteria) |
| CT chest/abdomen/pelvis | Blunt Abdominal; Blunt Chest; Pelvic Fractures; Solid Organ Injuries |
| CTA neck/chest | BCVI (Biffl grading); Penetrating Neck Injury; Transmediastinal GSW; Vascular Intervention |
| Plain films (chest, pelvis, extremity) | Rib Fracture; Pelvic Fractures; Musculoskeletal Injuries |
| FAST/eFAST | Blunt Abdominal; Penetrating Abdominal; Blunt Chest (hemothorax) |
| Angiography (diagnostic/interventional) | Vascular Intervention Guideline; Peripheral Vascular Trauma; Pelvic Fractures (embolization) |
| MRI spine | Spinal Clearance (obtunded patients); Musculoskeletal Injuries |
| Echocardiography (TTE/TEE) | Blunt Chest Trauma (cardiac contusion); Transmediastinal GSW |
| Chest X-ray (serial) | Rib Fracture; Penetrating Chest; Drowning (pulmonary edema) |
| Solid organ injury grade (AAST) | Solid Organ Injuries (I–V grading for non-operative management) |
| Fracture classification | Pelvic Fractures (Young-Burgess); Musculoskeletal (Gustilo-Anderson for open fractures) |

---

## 9. Airway / Respiratory

| Element | Notes / Protocols |
|---------|-------------------|
| Intubation (date/time/indication) | TBI Management (GCS ≤8); Drowning; Suspected Hanging; Traumatic Arrest; NTDS E19 Unplanned Intubation |
| Ventilator mode / settings | ARDS monitoring (NTDS E02); TBI Management (PaCO2 target) |
| Ventilator days | VAP screening (NTDS E21 — ≥48h); ARDS |
| Chest tube placement (date/time/output) | Blunt Chest; Penetrating Chest; Rib Fracture |
| Chest tube output (serial) | Penetrating Chest (>1500 mL = OR trigger); Blunt Chest |
| Needle decompression | Blunt Chest; Penetrating Chest; Traumatic Arrest |
| Tracheostomy (date/time) | TBI Management; prolonged intubation |
| Oxygen supplementation type/FiO2 | Drowning; Rib Fracture (incentive spirometry) |
| PaO2/FiO2 ratio | ARDS monitoring (NTDS E02 — Berlin criteria) |

---

## 10. Resuscitation / Blood Products

| Element | Notes / Protocols |
|---------|-------------------|
| MTP activation (yes/no, time) | Blood and Blood Product Transfusion; ROTEM Guideline |
| ED Blood Box use | ROTEM Guideline; Blood Transfusion |
| pRBC units transfused | Blood Transfusion (ratio targets 1:1:1); ROTEM |
| FFP units transfused | Blood Transfusion (ratio targets) |
| Platelet units transfused | Blood Transfusion (ratio targets) |
| Cryoprecipitate administered | Blood Transfusion; ROTEM (fibrinogen <150) |
| TXA (tranexamic acid) administration (time) | Blood Transfusion (within 3h of injury) |
| Calcium supplementation | Blood Transfusion (ionized Ca monitoring) |
| Crystalloid volume (total) | All resuscitation protocols; Hypothermia (warmed fluids) |
| Vasopressor use (agent, dose, duration) | Traumatic Arrest; Sepsis (NTDS E15) |
| Resuscitative thoracotomy performed | Emergency Resuscitative Thoracotomy |
| REBOA (if applicable) | Vascular Intervention; Pelvic Fractures |

---

## 11. Operative / Procedural

| Element | Notes / Protocols |
|---------|-------------------|
| Procedure type / CPT | All surgical protocols; NTDS E20 OR Return |
| Procedure date/time | Spinal Clearance (surgery within 36h); all surgical protocols |
| Time from arrival to OR | Neurosurgical Emergencies; Penetrating protocols; Pelvic Fractures |
| Anesthesia type / duration | Rib Fracture (epidural/nerve block); Anesthesia Trauma Panel |
| Operative findings | Solid Organ Injuries; Penetrating protocols; Musculoskeletal |
| Damage control surgery (DCS) | Penetrating Abdominal; Solid Organ Injuries; Pelvic Fractures |
| Fasciotomy | Musculoskeletal Injuries (compartment syndrome); Peripheral Vascular |
| Spinal stabilization surgery (time from injury) | Spinal Clearance (within 36h — REQ_TIMING_CRITICAL) |
| Surgical complications | All surgical protocols; NTDS E07 Deep SSI; E11 Organ Space SSI; E17 Superficial SSI |
| Unplanned return to OR | NTDS E20 OR Return |
| ICP monitor placement | TBI Management; Neurosurgical Emergencies |
| Angioembolization | Vascular Intervention; Pelvic Fractures; Solid Organ Injuries |

---

## 12. Pharmacologic Interventions

| Element | Notes / Protocols |
|---------|-------------------|
| Anticoagulant reversal agent (4F-PCC, vitamin K, protamine, idarucizumab) | Anticoagulation and Antiplatelet Medication Reversal |
| Pre-injury anticoagulant/antiplatelet list | Anticoagulation Reversal; Geriatric Trauma; TBI Management |
| Antibiotic administration (type, time) | Open fractures (Musculoskeletal, within 1h); Penetrating Abdominal |
| Tetanus prophylaxis | Burned Patient; Musculoskeletal; Penetrating protocols |
| Pain management (opioid/non-opioid) | Rib Fracture (multimodal); Orthopedic/Neurologic Splint |
| Sedation agents (for intubated patients) | TBI Management (avoid hypotension); Drowning |
| Anti-seizure prophylaxis | TBI Management (levetiracetam/phenytoin) |
| GI prophylaxis agent (PPI/H2 blocker) | Geriatric Trauma; TBI Management |
| VTE chemoprophylaxis (LMWH/UFH, timing) | DVT Prophylaxis Adult; DVT Prophylaxis Pediatric; Geriatric Trauma |

---

## 13. Device / Line Management

| Element | Notes / Protocols |
|---------|-------------------|
| Central venous catheter (type, site, date placed) | CLABSI monitoring (NTDS E06 — in place >2 calendar days) |
| Central line duration (days) | CLABSI (NTDS E06 — central_line_gt2d gate) |
| Urinary catheter (Foley) placement date | CAUTI monitoring (NTDS E05 — in place >2 calendar days) |
| Urinary catheter duration (days) | CAUTI (NTDS E05 — catheter_gt2d gate) |
| Arterial line | Hemodynamic monitoring; Base Deficit (ABG draws) |
| ICP monitor (type, date placed) | TBI Management; Neurosurgical Emergencies |
| Chest tube (date placed, date removed) | Blunt/Penetrating Chest; Rib Fracture |
| External fixator | Pelvic Fractures; Musculoskeletal Injuries |
| Pelvic binder | Pelvic Fractures (hemodynamic instability) |
| Splint / brace (type, application) | Orthopedic/Neurologic Splint and/or Brace |
| Mechanical ventilation (start/end date) | VAP screening (NTDS E21); ARDS (NTDS E02) |
| Sequential compression devices (SCDs) | DVT Prophylaxis Adult; DVT Prophylaxis Pediatric |

---

## 14. Infection Prevention / HAI Monitoring

| Element | Notes / Protocols |
|---------|-------------------|
| CAUTI diagnosis (CDC criteria) | NTDS E05 — SUTI 1a: catheter >2d + symptoms + culture ≥10^5 CFU |
| CLABSI diagnosis (NHSN criteria) | NTDS E06 — central line >2d + positive blood culture + no other source |
| SSI — superficial | NTDS E17 — incisional infection within 30 days |
| SSI — deep | NTDS E07 — deep incisional infection within 30/90 days |
| SSI — organ/space | NTDS E11 — organ/space infection within 30/90 days |
| VAP diagnosis | NTDS E21 — mechanical ventilation ≥48h + clinical/radiographic/microbiologic criteria |
| Pressure ulcer (stage, location, date identified) | NTDS E13 — hospital-acquired, not POA |
| Sepsis / severe sepsis (qSOFA, SIRS criteria) | NTDS E15 — Severe Sepsis |
| Infection source identification | All HAI events — blood culture, urine culture, wound culture |
| Central line bundle compliance | CLABSI prevention — daily assessment documented |
| Catheter necessity review | CAUTI prevention — daily necessity documented |

---

## 15. Prophylaxis (DVT / GI / Hypothermia)

| Element | Notes / Protocols |
|---------|-------------------|
| DVT prophylaxis — mechanical (SCDs, date started) | DVT Prophylaxis Adult/Pediatric |
| DVT prophylaxis — chemical (agent, dose, start date) | DVT Prophylaxis Adult/Pediatric; Geriatric Trauma |
| DVT prophylaxis — contraindication documented | DVT Prophylaxis Adult/Pediatric (active bleeding, craniotomy, spinal surgery) |
| GI prophylaxis (PPI/H2 blocker, start date) | Geriatric Trauma; TBI Management |
| Hypothermia prevention (warming method, target temp) | Hypothermia Prevention and Treatment (target ≥36°C) |
| Hypothermia — rewarming modality | Hypothermia Prevention (passive external → active external → active internal) |
| Temperature monitoring frequency | Hypothermia Prevention (continuous in OR/ICU; q1h in ED) |

---

## 16. Screening / Behavioral Health

| Element | Notes / Protocols |
|---------|-------------------|
| SBIRT screening completed (yes/no) | SBIRT (all trauma patients) |
| SBIRT screening result (negative/positive) | SBIRT |
| SBIRT brief intervention provided | SBIRT (if positive screen) |
| SBIRT referral to treatment | SBIRT (if positive screen) |
| Blood alcohol level (BAL) | SBIRT; Laboratory Studies |
| Urine drug screen result | SBIRT; Laboratory Studies |
| Mental health screening completed | Mental Health Screening for the Trauma Patient |
| PHQ-2 / PHQ-9 score | Mental Health Screening |
| PC-PTSD screen | Mental Health Screening |
| Social work consult ordered | Mental Health Screening; NAT; SBIRT |
| NAT screening (skeletal survey, fundoscopic exam) | Non-Accidental Trauma (Pediatric ≤14) |

---

## 17. Special Populations

### 17a. Geriatric (age ≥ 65)

| Element | Notes / Protocols |
|---------|-------------------|
| Falls risk assessment | Geriatric Trauma Guideline |
| Pre-injury functional status | Geriatric Trauma; Geriatric Hip Fracture |
| Pre-injury anticoagulant use | Geriatric Trauma; Anticoagulation Reversal |
| Frailty screening | Geriatric Trauma Guideline |
| Hip fracture type / classification | Geriatric Hip Fracture Guideline |
| Time to hip fracture surgery | Geriatric Hip Fracture (target <24–48h) |
| Geriatric consult | Geriatric Trauma Guideline |

### 17b. Pediatric (age ≤ 14–17)

| Element | Notes / Protocols |
|---------|-------------------|
| Weight (kg) — for dosing | Pediatric Special Consideration; DVT Prophylaxis Pediatric |
| Broselow color / length-based tape | Pediatric Special Consideration |
| Pediatric GCS | TBI Management (pediatric variant) |
| NAT concern documented | Non-Accidental Trauma |
| Skeletal survey ordered/completed | Non-Accidental Trauma |
| Child protective services notified | Non-Accidental Trauma |
| Pediatric intensivist consult | Pediatric Intensive Trauma Panel |

### 17c. Obstetric (gestation ≥ 18 weeks)

| Element | Notes / Protocols |
|---------|-------------------|
| Gestational age (weeks) | Obstetrical Trauma (≥18 weeks) |
| Fetal heart monitoring (continuous) | Obstetrical Trauma |
| OB consult date/time | Obstetrical Trauma |
| Kleihauer-Betke test | Obstetrical Trauma (Rh-negative patients) |
| RhoGAM administered | Obstetrical Trauma (if indicated) |
| Tocodynamometry / contraction monitoring | Obstetrical Trauma |

---

## 18. Disposition / Discharge Planning

| Element | Notes / Protocols |
|---------|-------------------|
| Hospital LOS (days) | All protocols — registry requirement |
| ICU LOS (days) | TBI Management; Neurosurgical Emergencies; ARDS |
| ICU admission (planned vs. unplanned) | NTDS E18 — Unplanned ICU Admission |
| Discharge date/time | All protocols |
| Discharge disposition (home/rehab/SNF/LTAC/death) | Rehabilitative Services and Discharge Planning |
| Discharge GCS | TBI Management |
| 30-day mortality | Autopsy in the Trauma Patient; registry requirement |
| Autopsy performed (yes/no, findings) | Autopsy in the Trauma Patient |
| Rehab services ordered (PT/OT/SLP) | Rehabilitative Services and Discharge Planning |
| Follow-up plan documented | All protocols; Geriatric Trauma; Orthopedic Splint |
| Transfer destination (facility, level) | Transfer TO/FROM Deaconess Midtown |
| Transfer reason | Transfer TO/FROM Deaconess Midtown |

---

## 19. Complications / NTDS Events

| Element | Notes / Protocols |
|---------|-------------------|
| E01 — Acute Kidney Injury (KDIGO Stage 3) | AKI dx + stage 3 labs + after arrival − POA − chronic RRT |
| E02 — ARDS (Berlin criteria) | Bilateral opacities + PaO2/FiO2 ≤300 + not cardiogenic |
| E03 — Alcohol Withdrawal | Documented withdrawal requiring treatment |
| E04 — Cardiac Arrest | In-hospital cardiac arrest requiring CPR |
| E05 — CAUTI (CDC SUTI 1a) | Catheter >2d + symptoms + culture ≥10^5 + after arrival |
| E06 — CLABSI (NHSN) | Central line >2d + positive blood culture + after arrival |
| E07 — Deep SSI | Deep incisional infection within 30/90 days of procedure |
| E08 — DVT | New DVT diagnosis after arrival |
| E09 — Delirium | New delirium diagnosis (CAM-ICU/bCAM positive) |
| E10 — Myocardial Infarction | New MI diagnosis after arrival |
| E11 — Organ/Space SSI | Organ/space infection within 30/90 days of procedure |
| E12 — Osteomyelitis | New osteomyelitis diagnosis after arrival |
| E13 — Pressure Ulcer | Hospital-acquired pressure injury (not POA) |
| E14 — Pulmonary Embolism | New PE diagnosis after arrival |
| E15 — Severe Sepsis | Sepsis with organ dysfunction after arrival |
| E16 — Stroke/CVA | New stroke/CVA after arrival |
| E17 — Superficial SSI | Superficial incisional infection within 30 days |
| E18 — Unplanned ICU Admission | Unplanned transfer to ICU |
| E19 — Unplanned Intubation | Unplanned intubation/reintubation |
| E20 — Unplanned Return to OR | Unplanned return to operating room |
| E21 — Ventilator-Associated Pneumonia | Mechanical vent ≥48h + clinical/micro/radiographic criteria |

---

## 20. Operational / Call Panel

| Element | Notes / Protocols |
|---------|-------------------|
| Trauma team activation level (Cat I / Cat II / Consult) | Activation Process for Trauma Patients |
| Attending surgeon arrival time | Trauma Team Attending Requirements (Cat I: ≤15 min) |
| Attending surgeon notification time | Trauma Team Attending Requirements |
| Trauma surgeon on-call roster | Trauma Surgeon Call Panel Process |
| Neurosurgeon on-call roster | Neurosurgeon Trauma Panel |
| Orthopedic surgeon on-call roster | Orthopedic Surgeon Trauma Call Panel Process |
| Anesthesia on-call roster | Anesthesia Trauma Panel |
| Pediatric intensivist on-call roster | Pediatric Intensive Trauma Panel |
| Advanced practice provider (APP) role | Advanced Practice Trauma Provider Requirements |
| Resuscitation role assignments | Resuscitation Role Assignments (team leader, airway, circulation, etc.) |
| Performance improvement review flags | Performance Improvement and Patient Safety Plan; Quality Plan |
| Educational competency documentation | Educational Requirements for Staff |
| Public education activities | Role in Public Education |

---

## Appendix A — Protocol Index (51 PDFs)

### Class I — Evaluable (35 protocols)

1. Traumatic Brain Injury Management
2. Rib Fracture Management
3. Blunt Abdominal Trauma
4. Blunt Chest Trauma
5. Penetrating Abdominal Trauma
6. Penetrating Neck Injury
7. Peripheral Vascular Trauma
8. Blunt Cerebrovascular Injury (BCVI)
9. DVT Prophylaxis — Adult Trauma Patient
10. DVT Prophylaxis — Pediatric Trauma Patient
11. Geriatric Trauma Guideline
12. Geriatric Hip Fracture Guideline
13. Screening of the Trauma Patient for Alcohol and/or Drug Use (SBIRT)
14. Mental Health Screening for the Trauma Patient
15. Emergency Resuscitative Thoracotomy
16. Traumatic Arrest
17. Drowning
18. Management and Triage of Burned Patients
19. Management of Solid Organ Injuries
20. Management of Severe Musculoskeletal Injuries
21. Management of Neurosurgical Emergencies
22. Spinal Clearance and Spinal Injury Management
23. Management and Stabilization of Pelvic Fractures
24. Rib Fracture Management (Extended)
25. Monitoring Base Deficit
26. Penetrating Chest Injury
27. ROTEM Guideline
28. Vascular Intervention Guideline
29. Suspected Hanging Guideline
30. Blood and Blood Product Transfusion
31. Hypothermia — Prevention and Treatment
32. Laboratory Studies Needed in Trauma Resuscitation
33. Management and Triage of the Obstetrical Trauma Patient
34. Autopsy in the Trauma Patient
35. Non-Accidental Trauma (NAT) in the Pediatric Patient
36. Management of Transmediastinal Gunshot Wounds
37. Anticoagulation and Antiplatelet Medication Reversal

### Class II — Context Only (6 protocols)

38. Management of the Orthopedic/Neurologic Splint and/or Brace
39. Transfer of the Trauma Patient TO Deaconess Midtown
40. Transfer of the Trauma Patient FROM Deaconess Midtown
41. Rehabilitative Services and Discharge Planning for the Trauma Patient
42. Trauma Surgeon Consult
43. Resuscitation Role Assignments
44. Special Consideration for the Management of the Pediatric Trauma Patient

### Administrative / Call Panel (8 documents)

45. Activation Process for Trauma Patients
46. Definition of Trauma Patient
47. Trauma Team Attending Requirements
48. Trauma Surgeon Call Panel Process
49. Neurosurgeon Trauma Panel
50. Orthopedic Surgeon Trauma Call Panel Process
51. Anesthesia Trauma Panel
52. Pediatric Intensive Trauma Panel
53. Advanced Practice Trauma Provider Requirements
54. Educational Requirements for Staff
55. Performance Improvement and Patient Safety Plan
56. Quality Plan
57. Role in Public Education

> **Note:** 57 total PDFs ingested. The "51 protocols" count excludes the 6
> purely administrative documents (Definition of Trauma Patient, Educational
> Requirements, Performance Improvement, Quality Plan, Role in Public
> Education, Advanced Practice Provider Requirements) which contain no
> patient-level data elements. All 57 PDFs were successfully parsed with no
> missing files.

---

_End of document._
