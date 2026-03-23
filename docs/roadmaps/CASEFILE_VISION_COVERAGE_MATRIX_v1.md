# PI RN Casefile — Vision Coverage Matrix v1

| Field       | Value                                                    |
|-------------|----------------------------------------------------------|
| Date        | 2026-03-22                                               |
| Baseline    | `b8ac647` (main, after PR #292)                          |
| Owner       | Sarah                                                    |
| Status      | Active — tracks vision-to-implementation alignment        |

---

## Purpose

Maps the product vision ([PI_RN_CASEFILE_V1.md](PI_RN_CASEFILE_V1.md)) to
current implementation reality. Each row shows what exists, what's missing,
where the gap lives (extraction / bundle / renderer / tests), and what the
likely next action is.

**Status definitions:**

| Status | Meaning |
|--------|---------|
| **Implemented** | Feature extracted + bundled + rendered in casefile |
| **Partial** | Some layers exist (e.g. extraction done) but not fully surfaced |
| **Missing** | No implementation or only at design phase |
| **Deferred** | Recognized gap, explicitly deferred with rationale |

---

## 1. Trauma Summary Header (Above the Fold)

All 11 header fields are **Implemented** — extracted, bundled, and rendered
in the above-the-fold clinical snapshot (PR #290) and patient card.

| # | Vision Item | Status | Gap Type | Notes | Next Action |
|---|-------------|--------|----------|-------|-------------|
| 1 | Patient name | **Implemented** | — | `patient_evidence_v1 → meta.patient_name` → bundle → header | — |
| 2 | Date of birth | **Implemented** | — | `patient_evidence_v1 → meta.dob` → bundle → header | — |
| 3 | Age | **Implemented** | — | Computed from DOB + admission date in `age_extraction_v1` | — |
| 4 | Admission date | **Implemented** | — | `patient_evidence_v1 → meta.arrival_datetime` → bundle → header | — |
| 5 | Discharge date | **Implemented** | — | `patient_evidence_v1 → meta.discharge_datetime` → bundle → header | — |
| 6 | Trauma activation category | **Implemented** | — | `category_activation_v1` multi-source detection → bundle `summary.activation` | — |
| 7 | Admitting physician | **Implemented** | — | `patient_movement_v1 → events[].providers.admitting` → bundle → header | — |
| 8 | Initial GCS | **Implemented** | — | `gcs_daily` arrival priority extraction → bundle daily → day-card renderer (PR #292) | — |
| 9 | Mechanism of injury (MOI) | **Implemented** | — | `mechanism_region_v1` → bundle `summary.mechanism` → casefile MOI card | — |
| 10 | PMH | **Implemented** | — | `pmh_social_allergies_v1` → bundle `summary.pmh` → casefile PMH section | — |
| 11 | Home anticoagulation | **Implemented** | — | `anticoag_context_v1` → bundle `summary.anticoagulants` → casefile anticoag badge | — |

**Summary: 11/11 Implemented.**

---

## 2. Daily Clinical Detail Areas

| # | Vision Item | Status | Gap Type | Notes | Next Action |
|---|-------------|--------|----------|-------|-------------|
| 12 | Injury list by region | **Implemented** | — | `radiology_findings_v1` → bundle `summary.injuries` → casefile "Primary Injuries" section. Grouped by finding type (singular/list), shows level, count, laterality, grade. Fail-closed when absent. | — |
| 13 | Procedures & operations | **Implemented** | — | `procedure_operatives_v1` → bundle `summary.procedures` → casefile "Procedures" section. Chronological event list with color-coded category badges, preop dx, CPT codes, summary counts. Fail-closed when absent. | — |
| 14 | Lines / drains / airways | **Implemented** | — | `lda_events_v1` → bundle `summary.devices` → casefile "Lines / Drains / Airways" section. Device table with category, type, placement/removal, duration, site, active/removed status. Fail-closed when absent. | — |
| 15 | Consultations | **Implemented** | — | `consultant_events_v1` → bundle → casefile consultants section in header | — |
| 16 | Consultant plans | **Implemented** | — | `consultant_day_plans_by_day_v1` → bundle daily → day-card renderer (PR #292). Renders per-service plan items. | Consider structured recommendation extraction (future refinement). |
| 17 | Imaging highlights | **Implemented** | — | `radiology_findings_v1` → bundle `summary.imaging` → casefile "Imaging Studies" section. Evidence trail table with timestamp, source, finding label, snippet. Fail-closed when absent. | — |
| 18 | Admission-day imaging inventory | **Partial** | Renderer | Extraction exists in `trauma_doc_extractor._extract_admission_imaging()` for v5 report. Not integrated into casefile renderer. | Add admission imaging inventory to first-day snapshot. |
| 19 | Admission labs | **Implemented** | — | `structured_labs_v1` (CBC, BMP, coag, ABG, cardiac, sepsis panels) → bundle daily → day-card lab renderer (PR #292). Renders flagged values with H/L highlighting. | — |
| 20 | Daily narrative / notes | **Partial** | Upstream feature gap | Feature module exists (`trauma_daily_plan_by_day_v1`). Bundle wiring and renderer exist (PR #291 + #292). However, the feature module returns null/empty for most gate patients — this is an **upstream extraction gap**, not a bundle or renderer bug. | Investigate why `trauma_daily_plan_by_day_v1` produces empty results for gate patients. Fix extraction or document limitation. |
| 21 | Respiratory support / ventilator | **Partial** | Renderer (deferred) | Extraction complete (`ventilator_settings_v1` — mode, FiO2, PEEP, Vt, RR, NIV). Bundle wiring exists. Renderer stub exists (`_render_ventilator`). Rendering intentionally deferred — ventilator display not yet enabled in casefile output. | Enable ventilator rendering when product decision is made. |
| 22 | PT / OT / disposition | **Implemented** | Bundle + renderer | `non_trauma_team_day_plans_v1` wired to bundle daily as `non_trauma_team_plans`. `patient_movement_v1` wired to bundle summary as `patient_movement`. Disposition Planning card + per-day Non-Trauma Team Plans section rendered in casefile (PR #297). | — |

**Summary: 6/11 Implemented, 5/11 Partial (extraction exists but rendering gap).**

---

## 3. Compliance / Governance

| # | Vision Item | Status | Gap Type | Notes | Next Action |
|---|-------------|--------|----------|-------|-------------|
| 23 | NTDS event outcomes | **Implemented** | — | 21/21 events mapped. `ntds_summary` + per-event detail → bundle `compliance.ntds_summary` → casefile NTDS summary table with outcome badges. | — |
| 24 | Protocol compliance | **Implemented** | — | ~40 Deaconess protocols evaluated. `protocol_results` → bundle `compliance.protocol_results` → casefile protocol summary table with compliance badges. | Consider adding "why non-compliant" context detail (future). |
| 25 | Future PI skeleton / potential_PI tagging | **Missing** | Not started | No feature module, no roadmap entry, no design doc. Requires PI classification criteria design — risk of clinical inference if not carefully scoped. | Design work required before implementation. Must stay within deterministic/fail-closed constraints. |

**Summary: 2/3 Implemented, 0/3 Partial, 1/3 Missing.**

---

## 4. Nice-to-Have / Future

| # | Vision Item | Status | Gap Type | Notes | Next Action |
|---|-------------|--------|----------|-------|-------------|
| 26 | Clipboard capture helper | **Deferred** | UX / frontend | No feature module, no design. Requires UI/UX work outside core pipeline. | Design phase when casefile content is complete. |
| 27 | LLM copilot packet ideas | **Deferred** | Blocked by constraints | Codebase constraint: "No LLM, no ML, no clinical inference." Deterministic-only architecture prevents LLM integration in feature layer. | Future product evolution; not compatible with current architecture. |
| 28 | Visual / emotional design | **Partial** | CSS refinement | Foundation in place: CSS design tokens, color palette, cards, badges, typography in casefile renderer. Professional HTML output. "Emotional design" concept not yet formally specified. | Polish pass after content completeness. |
| 29 | BMAT (blood management) | **Partial** | Extraction gap | Transfusion data extracted (`transfusion_blood_products_v1` — pRBC, FFP, platelets, TXA, MTP). Referenced in protocol rules. Transfusion summary now rendered in casefile (PR #296). Explicit BMAT scoring feature stub does not exist. | Define BMAT scoring criteria; build on existing transfusion extraction. |
| 30 | Time to OR | **Missing** | Derivation gap | Data exists (procedures via `procedure_operatives_v1`, admission time via evidence). No computed time-delta feature module yet. ~5-line derivation once procedures are bundled. | Implement after procedure timeline is wired (depends on #13 above). |
| 31 | SBIRT surfacing | **Partial** | Renderer | Extraction complete (`sbirt_screening_v1` — AUDIT-C, DAST-10, CAGE scores + question-level responses). Contract doc exists. Not yet rendered in casefile but fully extracted and available. | Wire into casefile when rendering scope expands. |

**Summary: 0/6 Implemented, 3/6 Partial, 1/6 Missing, 2/6 Deferred.**

---

## 5. Overall Coverage Summary

| Category | Implemented | Partial | Missing | Deferred | Total |
|----------|-------------|---------|---------|----------|-------|
| Trauma Summary Header (1–11) | 11 | 0 | 0 | 0 | 11 |
| Daily Clinical Detail (12–22) | 3 | 8 | 0 | 0 | 11 |
| Compliance / Governance (23–25) | 2 | 0 | 1 | 0 | 3 |
| Nice-to-Have / Future (26–31) | 0 | 3 | 1 | 2 | 6 |
| **TOTAL** | **16** | **11** | **2** | **2** | **31** |

**Key insight:** The extraction layer is substantially more complete than the
rendering layer. 10 of the 31 vision items have working feature modules but
don't fully surface in the casefile — the remaining value is in bundle wiring
and renderer work, not new extraction logic.

---

## 6. Stale Findings — Corrected

The following items from earlier audits have been resolved and should not be
treated as open gaps:

| Finding | Resolution |
|---------|------------|
| Bundle nested-days mapping bugs (vitals, plans, consultant_plans reading wrong key depth) | **Fixed in PR #291** — `build_patient_bundle_v1.py` now reads `module.days[date]` correctly for nested features. |
| Day-card renderer real-shape alignment (GCS, labs, vitals, consultant plans using wrong data shapes) | **Fixed in PR #292** — renderer methods aligned to canonical feature module output shapes; 98 tests passing. |
| Labs canonical guard (empty `latest` dict falling into legacy fallback) | **Fixed in PR #292** — `_CANONICAL_KEYS` detection returns empty panel when canonical shape detected but empty. |

---

## 7. Recommended Build Order (Next PR Themes)

Based on current coverage gaps, ranked by PI RN workflow value:

| Priority | Theme | Items Addressed | Rationale |
|----------|-------|-----------------|-----------|
| 1 | **Injury inventory + imaging results** | #12, #17 | Closes biggest content gap. PI RN's first question is "what was injured?" Data exists in `radiology_findings_v1` + `mechanism_region_v1`. |
| 2 | **Procedure/operative timeline** | #13, #30 | Unblocks return-to-OR, delay-to-definitive-care metrics. `procedure_operatives_v1` extraction is high-confidence. Time-to-OR is ~5-line derivation. |
| 3 | **Resuscitation / hemodynamic summary** | (new section) | **Wired in PR #296** — `base_deficit_monitoring_v1` + `transfusion_blood_products_v1` + `hemodynamic_instability_pattern_v1` bundled and rendered. BMAT composite scoring remains deferred. |
| 4 | **Device duration + prophylaxis grid** | #14, #22 | **Partially addressed** — PR #295 wired `lda_events_v1` device summary + `dvt_prophylaxis_v1` + `gi_prophylaxis_v1` + `seizure_prophylaxis_v1` into casefile. PR #297 wired PT/OT + disposition (#22). Per-day device grid remains. |
| 5 | **Daily narrative investigation** | #20 | Investigate `trauma_daily_plan_by_day_v1` upstream extraction gap for gate patients. |

See [STATUS_DASHBOARD_v1.md](../STATUS_DASHBOARD_v1.md) for the current
one-page overview of recommended next work.

---

## Update Log

| Date | Change |
|------|--------|
| 2026-03-22 | Initial version — baseline at PR #292 (`b8ac647`) on main. |
| 2026-03-22 | PR #295 — Device + prophylaxis visibility v1. Item #14 → Implemented. Prophylaxis summary (DVT, GI, seizure) added. |
