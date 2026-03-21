# NTDS Extraction Support Ledger — v1

| Field       | Value |
|-------------|-------|
| Date        | 2026-03-21 |
| Baseline    | main (post PR #278) |
| Source       | Codebase audit of all 21 NTDS rule files, mapper JSON, engine.py, LDA infrastructure, precision tests |
| Reference   | `rules/ntds/logic/2026/` (21 event rule files), `rules/mappers/epic_deaconess_mapper_v1.json` |

> **Purpose:** Event-by-event NTDS extraction support ledger for E01–E21.
> Documents current extraction support, rule support, blocker types, and
> remaining work. Distinguishes between true missing extraction, extracted
> but unusable, partial rule support, stale docs, and protected-engine
> blockers.

---

## Status Definitions

| Status | Meaning |
|--------|---------|
| **fully operational** | All gates functional, precision-tested, no known false negatives or blockers |
| **operational with gaps** | Functional and producing outcomes, but known precision/recall issues or missing precision tests |
| **partial rule support** | Rules exist but missing gates, weak mapper patterns, or untested conditions |

## Blocker Type Definitions

| Blocker Type | Meaning |
|-------------|---------|
| **none** | No blocker; event is fully operational |
| **mapper gap** | Needs additional or refined mapper patterns |
| **rule gap** | Needs gate additions or rule structure changes |
| **precision test gap** | No dedicated precision test suite; functional but untested edge cases |
| **LDA validation** | LDA gate enabled but needs broader cohort validation |
| **protected-engine blocker** | Requires changes to `cerebralos/ntds_logic/engine.py` (PROTECTED); future-fix track |
| **source alignment** | `allowed_sources` may be too narrow for some evidence types |

---

## Event-by-Event Ledger (E01–E21)

### Tier 1 — Fully Operational, Precision-Tested (10 events)

| Event | Name | Gates | Mapper Keys (patterns) | Allowed Sources | LDA? | Precision Tests | Status | Blocker | Remaining Work |
|-------|------|-------|----------------------|-----------------|------|-----------------|--------|---------|----------------|
| E01 | Acute Kidney Injury | evidence_any (3), timing_after_arrival, 2 exclusions | 7 keys (~45 patterns): aki_dx, aki_stage3_lab, aki_new_dialysis, aki_chronic_rrt, aki_onset, aki_negation_noise, history_noise | PHYSICIAN, LAB, DISCHARGE, ED, CONSULT, NURSING, PROGRESS | No | test_e01_aki_precision.py, test_e01_aki_stage3_precision.py | fully operational | none | 3 residual UTDs (Carlton_Van_Ness, David_Gross, Ronald_Bittner) — genuine clinical ambiguity |
| E05 | CAUTI (CDC SUTI 1a) | evidence_any (5), lda_duration, timing_after_arrival, 2 exclusions | 7 keys (~82 patterns): cauti_dx, cauti_negation_noise, cauti_catheter_duration, cauti_symptoms, cauti_culture_positive, cauti_chronic_catheter, cauti_onset | PHYSICIAN, CONSULT, NURSING, LAB, PROGRESS, DISCHARGE, ED, LDA | **Yes** (URINARY_CATHETER ≥2d) | test_e05_cauti_precision.py | fully operational | none | LDA catheter timeline synchronization with culture onset |
| E06 | CLABSI (NHSN) | evidence_any (5), lda_duration, timing_after_arrival, 2 exclusions | 7 keys (~68 patterns): clabsi_dx, clabsi_symptoms, clabsi_blood_culture_positive, clabsi_central_line_duration, clabsi_chronic_line, clabsi_onset, clabsi_negation_noise | PHYSICIAN, CONSULT, NURSING, LAB, PROGRESS, DISCHARGE, ED, LDA | **Yes** (CENTRAL_LINE ≥2d) | test_e06_clabsi_precision.py | fully operational | none | PICC vs CVC line-type distinction in LDA |
| E09 | Delirium | evidence_any (1), 1 exclusion | 2 keys (~28 patterns): delirium_dx, delirium_negation_noise | PHYSICIAN, NURSING, CONSULT, ED | No | test_e09_delirium_precision.py | operational with gaps | mapper gap | **Known false negatives** (AUD-002): Johnny_Stokes, Linda_Hufford, Ronald_Bittner have raw-file delirium evidence not captured. E09 has single `evidence_any` gate — single-gate fragility risk (AUD-008). CAM-ICU/bCAM instrument scores not structured. |
| E10 | Myocardial Infarction | evidence_any (1), 1 exclusion | 2 keys (~11 patterns): mi_dx, mi_negation_noise | PHYSICIAN, LAB, DISCHARGE, ED, CONSULT | No | test_e10_mi_precision.py | fully operational | none | Troponin threshold cutoff validation |
| E15 | Severe Sepsis | evidence_any (1), 1 exclusion | 2 keys (~17 patterns): sepsis_dx, sepsis_negation_noise | PHYSICIAN, LAB, DISCHARGE, ED, NURSING, CONSULT | No | test_e15_severe_sepsis_precision.py (46 tests) | fully operational | none | Expand organ dysfunction detection (lactate, vasopressor) |
| E16 | Stroke/CVA | evidence_any (1), 1 exclusion | 2 keys (~16 patterns): stroke_dx, stroke_negation_noise | PHYSICIAN, IMAGING, DISCHARGE, ED, CONSULT | No | test_e16_stroke_precision.py | fully operational | none | NIHSS score integration; ischemic vs hemorrhagic distinction |
| E18 | Unplanned ICU Admission | evidence_any (1), 1 exclusion | 2 keys (~16 patterns): unplanned_icu, icu_negation_noise | PHYSICIAN, NURSING, DISCHARGE, ED | No | test_e18_unplanned_icu_precision.py | fully operational | none | Planned vs emergency admission distinction |
| E19 | Unplanned Intubation | evidence_any (1), 1 exclusion | 2 keys (~24 patterns): unplanned_intubation, intubation_negation_noise | PROCEDURE, PHYSICIAN, ED, ANESTHESIA | No | test_e19_unplanned_intubation_precision.py | fully operational | none | Prophylactic vs emergent exclusion validation |
| E21 | VAP | evidence_any (3), lda_duration, 1 exclusion | 6 keys (~42 patterns): vent_dx, vap_dx, vap_cxr, prophylaxis_noise, vap_negation_noise, history_noise | PHYSICIAN, NURSING, PROGRESS, OPERATIVE, ANESTHESIA, PROCEDURE, ED, LDA | **Yes** (MECHANICAL_VENTILATOR ≥2d) | test_e21_vap_precision.py (34 tests) | fully operational | none | CXR infiltrate temporal correlation; reintubation consolidation |

### Tier 2 — Operational With Gaps, No Precision Tests (6 events)

| Event | Name | Gates | Mapper Keys (patterns) | Allowed Sources | LDA? | Precision Tests | Status | Blocker | Remaining Work |
|-------|------|-------|----------------------|-----------------|------|-----------------|--------|---------|----------------|
| E02 | ARDS (Berlin criteria) | evidence_any (2), timing_after_arrival, 1 exclusion | 2 keys (~8 patterns): ards_dx, ards_onset | PHYSICIAN, IMAGING, DISCHARGE, ED | No | **None** | operational with gaps | precision test gap, mapper gap | Add Berlin severity criteria (P/F ≤ 300 threshold using already-extracted ABG data); add bilateral opacity confirmation patterns; build precision test suite |
| E03 | Alcohol Withdrawal | evidence_any (1), 1 exclusion | 1 key (~7 patterns): alcohol_withdrawal_dx | PHYSICIAN, NURSING, ED | No | **None** | operational with gaps | precision test gap | Add CIWA score patterns; build precision test suite |
| E04 | Cardiac Arrest With CPR | evidence_any (2), 1 exclusion | 2 keys (~11 patterns): cardiac_arrest_dx, cpr_documented | PHYSICIAN, NURSING, ED | No | **None** | operational with gaps | precision test gap | Add ROSC timing patterns; build precision test suite |
| E08 | DVT | evidence_any (2), timing_after_arrival, requires_treatment_any (2), 1 exclusion | 7 keys (~40 patterns): dvt_dx, dvt_dx_negative, dvt_dx_noise_prophylaxis, dvt_onset, dvt_treatment_anticoag, dvt_treatment_filter, dvt_poa_phrase | PHYSICIAN, CONSULT, IMAGING, DISCHARGE, ED, NURSING, MAR, PROCEDURE | No | **None** | operational with gaps | precision test gap | Build precision test suite; PE/DVT concordance validation |
| E14 | Pulmonary Embolism | evidence_any (2), timing_after_arrival, 1 exclusion | 8 keys (~71 patterns): pe_dx_positive, pe_dx_negative, pe_prophylaxis_noise, pe_history_noise, pe_ruleout_noise, pe_poa_strict, pe_onset, pe_subsegmental_only | IMAGING, PHYSICIAN, CONSULT, DISCHARGE, ED, NURSING | No | **None** | operational with gaps | precision test gap | Build precision test suite; subsegmental PE inclusion threshold |
| E20 | Unplanned Return to OR | evidence_any (3), 3 exclusions | 7 keys (~69 patterns): or_initial_procedure, or_return_unplanned, or_planned_staged, or_same_site, or_ir, osh_or, or_procedure_context | OPERATIVE, PHYSICIAN, PROCEDURE, DISCHARGE, ANESTHESIA | No | **None** | operational with gaps | precision test gap | Build precision test suite; improve staged-washout vs unplanned differentiation |

### Tier 3 — Partial Rule Support (4 events)

| Event | Name | Gates | Mapper Keys (patterns) | Allowed Sources | LDA? | Precision Tests | Status | Blocker | Remaining Work |
|-------|------|-------|----------------------|-----------------|------|-----------------|--------|---------|----------------|
| E07 | Deep Surgical Site Infection | evidence_any (1), 1 exclusion | 1 key (~7 patterns): deep_ssi_dx | OPERATIVE, PHYSICIAN, DISCHARGE, PROCEDURE, IMAGING | No | **None** | partial rule support | mapper gap, rule gap, precision test gap | Add fascial-plane depth criteria; distinguish from superficial findings; add culture positivity gate; build precision test suite |
| E11 | Organ/Space SSI | evidence_any (1), 1 exclusion | 1 key (~7 patterns): organ_space_ssi_dx | OPERATIVE, PHYSICIAN, DISCHARGE, PROCEDURE, IMAGING | No | **None** | partial rule support | mapper gap, rule gap, precision test gap | Add intra-abdominal abscess location; fluid culture criteria; build precision test suite |
| E13 | Pressure Ulcer | evidence_any (1), 1 exclusion | 1 key (~5 patterns): pressure_ulcer_dx | NURSING, PHYSICIAN, DISCHARGE | No | **None** | partial rule support | mapper gap, precision test gap | Add staging (I–IV), anatomic location, hospital-acquired vs community distinction; build precision test suite |
| E17 | Superficial Incisional SSI | evidence_any (1), 1 exclusion | 1 key (~6 patterns): superficial_ssi_dx | PHYSICIAN, OPERATIVE, DISCHARGE, PROCEDURE | No | **None** | partial rule support | mapper gap, rule gap, precision test gap | Add wound erythema + drainage + culture criteria; build precision test suite |

---

## LDA Gate Status Detail

LDA (Lines, Drains, Airways) device-duration gates are a critical infrastructure for device-acquired infection events.

### Architecture

- **Engine support:** `cerebralos/ntds_logic/engine.py` supports 4 LDA gate types: `lda_duration`, `lda_present_at`, `lda_overlap`, `lda_device_day_count`
- **Feature flag:** `ENABLE_LDA_GATES` defaults to `False` in engine.py; per-event enablement via runner toggle in `run_all_events.py`
- **Device types:** URINARY_CATHETER, CENTRAL_LINE, MECHANICAL_VENTILATOR, ENDOTRACHEAL_TUBE, CHEST_TUBE, DRAIN_SURGICAL, NON_SURGICAL_AIRWAY (defined in `lda_events_v1.py`)

### Per-Event LDA Status

| Event | Device Type | Gate | Days Threshold | Enabled? | Confidence Level | Notes |
|-------|------------|------|----------------|----------|-----------------|-------|
| E05 CAUTI | URINARY_CATHETER | lda_duration | ≥ 2 days | **Yes** (eid=5 in runner) | TEXT_DERIVED | Rule `required: true`; catheter day-counter extraction from flowsheet |
| E06 CLABSI | CENTRAL_LINE | lda_duration | ≥ 2 days | **Yes** (eid=6 in runner) | TEXT_DERIVED | Rule `required: true`; central line day-counter extraction |
| E21 VAP | MECHANICAL_VENTILATOR | lda_duration | ≥ 2 days | **Yes** (eid=21 in runner) | TEXT_DERIVED | Rule `required: true`; multi-episode vent start/stop extraction (PR #250) |
| Other events | Various | — | — | **No** | — | LDA infrastructure defined but not enabled for other events |

### LDA Remaining Gaps

| Gap | Scope | Effort |
|-----|-------|--------|
| PICC vs CVC distinction | `lda_events_v1.py` device label parsing | Small — pattern match on insertion note |
| Catheter insertion timestamp | `lda_events_v1.py` date extraction | Medium — parse placement datetime |
| Reintubation within 24h consolidation | `lda_events_v1.py` episode merge | Medium — multi-episode logic exists, needs threshold |
| LDA enablement for non-E05/E06/E21 events | `run_all_events.py` toggle | Small — but requires cohort validation per event |

---

## Cross-Event Infrastructure

### Precision Test Coverage

| Coverage Level | Events | Count |
|----------------|--------|-------|
| **Has precision tests** | E01, E05, E06, E09, E10, E15, E16, E18, E19, E21 | 10 |
| **No precision tests** | E02, E03, E04, E07, E08, E11, E13, E14, E17, E20 | 11 |

### Mapper Coverage Summary

| Pattern Count Range | Events |
|--------------------|--------|
| **60+ patterns** | E05 (~82), E06 (~68), E14 (~71), E20 (~69) |
| **30–59 patterns** | E01 (~45), E08 (~40), E21 (~42) |
| **10–29 patterns** | E09 (~28), E19 (~24), E15 (~17), E16 (~16), E18 (~16) |
| **< 10 patterns** | E02 (~8), E03 (~7), E04 (~11), E07 (~7), E10 (~11), E11 (~7), E12 (~6), E13 (~5), E17 (~6) |

### Source Alignment

All 21 events have explicit `allowed_sources` lists. ED_NOTE was added to 12 events post-D6-P2 (E01, E02, E03, E04, E08, E09, E10, E14, E15, E16, E18, E19). ANESTHESIA_NOTE was added to E19 and E20.

Nine events exclude ED_NOTE by design (E05, E06, E07, E11, E12, E13, E17, E20, E21) — hospital-acquired/surgical events where ED evidence is not clinically relevant.

---

## Protected-Engine Future-Fix Track

These items require modifications to `cerebralos/ntds_logic/engine.py` (PROTECTED per AGENTS.md) and are **not active in-scope implementation work**. They are documented here for completeness and future planning.

| Item | Description | Impact | Blocked By |
|------|-------------|--------|------------|
| LDA gate default enablement | `ENABLE_LDA_GATES` defaults to `False`; currently overridden per-event in runner for E05/E06/E21 only. Enabling by default would require engine.py change. | Would simplify per-event LDA rule wiring | Protected engine — requires explicit authorization |
| Protocol-engine consumer disconnect | `cerebralos/protocol_engine/engine.py` does not consume `patient_features_v1.json` features. Protocol compliance assessment happens through separate rule evaluation, not through extracted features. | Protocol compliance and extracted features are parallel but disconnected pipelines | Protected engine — requires design doc + authorization |
| PMH-aware gate handling | Pre-existing medical history context (e.g., chronic conditions, prior surgeries) is not systematically available to NTDS gates for POA exclusion differentiation | Would improve POA exclusion precision across all events | Protected engine — requires design doc + architecture review |

---

## High-Confidence Next Actions (Ranked)

Based on: (1) evidence of known gaps in current cohort, (2) NTDS compliance impact, (3) mapper/rule-only scope (no engine changes).

| Rank | Action | Events | Type | Impact |
|------|--------|--------|------|--------|
| 1 | **E09 delirium false-negative hardening** (AUD-002) — add mapper patterns for confirmed misses (Johnny_Stokes, Linda_Hufford, Ronald_Bittner) | E09 | Mapper + rule | High — known false negatives |
| 2 | **Build precision test suites for Tier 2 events** (E02, E03, E04, E08, E14, E20) — 6 events with no precision tests | E02, E03, E04, E08, E14, E20 | Tests only | High — coverage gap |
| 3 | **E02 ARDS: wire P/F ratio threshold** — ABG pO2 and FiO2 already extracted in structured_labs_v1; Berlin criteria P/F ≤ 300 not applied as rule gate | E02 | Rule + mapper | Medium — improves ARDS adjudication |
| 4 | **SSI precision hardening (E07, E11, E17)** — add depth/culture/drainage criteria to distinguish superficial from deep from organ/space | E07, E11, E17 | Mapper + rule | Medium — reduces SSI misclassification |
| 5 | **Build precision test suites for Tier 3 events** (E07, E11, E13, E17) — 4 events with minimal mapper coverage and no tests | E07, E11, E13, E17 | Tests only | Medium — coverage gap |

**Explicit note:** LDA gate default enablement and protocol-engine consumer disconnect are future-fix-track items requiring engine-change authorization. They are not included in the ranked next actions.

---

_End of document._
