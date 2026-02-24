# Daily Notes v5 — Design & Delivery Plan

| Field   | Value                            |
|---------|----------------------------------|
| Date    | 2026-02-23                       |
| Owner   | Sarah                            |
| Status  | Draft                            |
| Branch  | tier0/daily-notes-v5-design-doc  |

---

## 1. Current State (What v4 Renders Today)

The v4 renderer (`render_trauma_daily_notes_v4.py`) produces a
standalone structured report per patient, organized by calendar day.

### Per-day sections rendered in v4

| Section             | Source                              | Content                                                    |
|---------------------|-------------------------------------|------------------------------------------------------------|
| Vitals Trending     | `days[date].vitals` (rollups)       | Temp hi/lo, HR hi/lo, SBP hi/lo, lowest MAP, lowest SpO2  |
| GCS                 | `days[date].gcs_daily`              | Arrival GCS, best/worst per day                            |
| Labs Panel Lite     | `days[date].labs_panel_daily`       | CBC, BMP, Coags, Lactate, Base Deficit (latest per day)    |
| Device Day Counts   | `days[date].device_day_counts`      | Foley, central line, ETT/vent, chest tube, drain (consec days + totals) |

### What v4 does NOT include

- No patient summary header (demographics, mechanism, injuries).
- No cross-day feature summaries (DVT timing, INR trends, shock status).
- No narrative text (physician notes, nursing notes, imaging results).
- No radiology findings, FAST, ETOH/UDS, SBIRT, or impression/plan content.
- No per-day or cross-day clinical flags (prophylaxis delays, hemodynamic instability).

### v3 renderer (narrative layer)

The v3 renderer (`render_trauma_daily_notes_v3.py`) produces a
deduplicated narrative report:

- H&P / physician note text (with prior-day suppression)
- Imaging items (type == RADIOLOGY only)
- Consult notes
- Nursing / flowsheet text
- Impression/Plan bullets (short lines only, narrative filtered)

v3 has no access to structured features — it works from raw
timeline text. It is currently the only way clinical narrative
reaches the daily notes.

---

## 2. Feature Coverage Now Available but Not Rendered

The following extracted features exist on `main` under
`patient_features_v1.json → features.*` but are **not rendered** in
either v3 or v4 daily notes.

| Feature Key                            | Contract                                    | Summary                                                          |
|----------------------------------------|---------------------------------------------|------------------------------------------------------------------|
| `age_extraction_v1`                    | `docs/contracts/age_extraction_v1.md`       | Patient age in years, DOB, source rule                           |
| `mechanism_region_v1`                  | `docs/contracts/mechanism_region_v1.md`     | Mechanism labels, primary mechanism, penetrating flag, body regions |
| `radiology_findings_v1`               | `docs/contracts/radiology_findings_v1.md`   | Pneumothorax, hemothorax, rib fractures, solid organ injury, ICH, pelvic/spinal fractures |
| `category_activation_v1`              | (internal)                                  | Category I trauma activation flag + evidence                     |
| `vitals_canonical_v1.arrival_vitals`   | `docs/contracts/vitals_canonical_v1.md`     | Deterministic arrival vitals (SBP, MAP, HR, SpO2, temp)          |
| `fast_exam_v1`                         | `docs/contracts/fast_exam_v1.md`            | FAST performed, result, timestamp                                |
| `etoh_uds_v1`                          | `docs/contracts/etoh_uds_v1.md`             | ETOH level, UDS panel, timestamps                                |
| `sbirt_screening_v1`                   | `docs/contracts/sbirt_screening_v1.md`      | SBIRT screening present, instruments, AUDIT-C/DAST-10/CAGE       |
| `dvt_prophylaxis_v1`                   | `docs/contracts/dvt_prophylaxis_v1.md`      | First DVT prophylaxis timestamp, delay hours, delay flag         |
| `gi_prophylaxis_v1`                    | `docs/contracts/dvt_prophylaxis_v1.md`      | First GI prophylaxis timestamp, delay hours, delay flag          |
| `base_deficit_monitoring_v1`           | `docs/contracts/base_deficit_monitoring_v1.md` | BD series, arterial source validation, trend                  |
| `inr_normalization_v1`                 | `docs/contracts/inr_normalization_v1.md`    | INR series, normalization timing, trend                          |
| `hemodynamic_instability_pattern_v1`   | `docs/contracts/hemodynamic_instability_pattern_v1.md` | SBP<90, MAP<65, HR>120 pattern counts across all days  |
| `shock_trigger_v1`                     | `docs/contracts/shock_trigger_v1.md`        | Shock triggered (SBP<90 + BD>6), type, evidence                 |
| `neuro_trigger_v1`                     | `docs/contracts/neuro_trigger_v1.md`        | Neuro trigger (GCS<9 on arrival), evidence                       |
| `impression_plan_drift_v1`            | `docs/contracts/impression_plan_drift_v1.md`| Impression/plan drift events, added/removed items, drift ratio   |

All 15+ feature modules have contracts, evidence traceability, and
deterministic outputs. None reach the daily notes today.

---

## 3. Daily Notes v5 Target Outcome

### 3.1 Goals

1. **Patient Summary header** — first-day demographics, mechanism,
   body regions, activation status, arrival metrics, FAST, ETOH/UDS,
   and SBIRT status in one glanceable block.
2. **Per-day clinical status sections** — extend v4's vitals/GCS/labs/
   devices with prophylaxis status, hemodynamic patterns, trigger
   flags, and impression/plan content.
3. **Structured feature integration** — render extracted features
   directly (deterministic, auditable) instead of relying on narrative
   text mining.
4. **Narrative + structured union** — merge v3 narrative content
   (physician notes, imaging, consults) with v4 structured sections
   into a single unified report, eliminating the need to read two
   separate outputs.

### 3.2 Design Principles

- **Deterministic** — all rendered values trace to a feature module
  with `raw_line_id` evidence. No inference, no LLM.
- **Fail-closed** — missing data renders as "DATA NOT AVAILABLE",
  never omitted silently.
- **Additive** — v5 is a new output file (`TRAUMA_DAILY_NOTES_v5.txt`).
  v3 and v4 continue to be produced unchanged.
- **Baseline-managed** — v5 output will get its own baseline hash
  file (`v5_hashes_v1.json`) once stabilized.

---

## 4. Proposed v5 Sections (Minimum Viable)

### 4.1 Patient Summary (once, top of report)

Rendered from patient-level features. Appears before the first day.

```
PATIENT SUMMARY
  Patient ID:       <patient_id>
  Age:              <age_years> years (source: <age_source_rule_id>)
  Category I:       <yes/no/DATA NOT AVAILABLE>
  Mechanism:        <mechanism_primary> (<mechanism_labels>)
  Penetrating:      <yes/no>
  Body Regions:     <body_region_labels>
  Arrival Vitals:   SBP=<sbp> MAP=<map> HR=<hr> SpO2=<spo2> Temp=<temp_c>°C
  Arrival GCS:      <gcs_value> (source: <gcs_source>)
  FAST:             <result> at <ts>
  ETOH:             <level> at <ts>
  UDS:              <panel_summary>
  SBIRT Screening:  <present> (instruments: <instruments>)
```

**Source features:**
`age_extraction_v1`, `category_activation_v1`, `mechanism_region_v1`,
`vitals_canonical_v1.arrival_vitals`, `neuro_trigger_v1` (arrival GCS),
`fast_exam_v1`, `etoh_uds_v1`, `sbirt_screening_v1`

### 4.2 Established Injury Catalog (once or carry-forward, TBD)

Rendered from `radiology_findings_v1`. Lists all radiologically
confirmed injuries with structured detail.

```
ESTABLISHED INJURY CATALOG
  Pneumothorax:          R, simple
  Rib Fractures:         L ribs 4-8 (5 ribs)
  Solid Organ Injury:    Spleen grade III
  Intracranial:          SDH
  Pelvic Fracture:       present
```

**Note:** This section may evolve to include non-radiology injury
sources (H&P documented injuries, operative findings) in a later
version. For v5 MVP, radiology-only is acceptable.

### 4.3 Vitals / GCS / Labs / Devices (per day — existing v4 sections)

Carried forward from v4 unchanged. These are already structured,
deterministic, and baseline-tested.

### 4.4 DVT / GI Prophylaxis Status (per day or summary)

```
PROPHYLAXIS STATUS
  DVT:  First action at <ts> (<hours> hrs post-arrival)
        Delay flag: <yes/no> (threshold: 24h)
        Type: <mechanical/chemical/both>
  GI:   First action at <ts> (<hours> hrs post-arrival)
        Delay flag: <yes/no> (threshold: 48h)
```

**Source features:** `dvt_prophylaxis_v1`, `gi_prophylaxis_v1`

### 4.5 INR / Base Deficit Trend Summary

```
BASE DEFICIT MONITORING
  Initial BD:    <value> (<specimen>) at <ts>
  Latest BD:     <value> at <ts>
  Trend:         <improving/worsening/stable/insufficient_data>
  Clearance:     <yes/no> (BD ≤ 2 sustained)

INR NORMALIZATION
  Initial INR:   <value> at <ts>
  Latest INR:    <value> at <ts>
  Normalized:    <yes/no> (INR ≤ 1.4)
  Time to norm:  <hours> hrs
```

**Source features:** `base_deficit_monitoring_v1`, `inr_normalization_v1`

### 4.6 Hemodynamic Instability Pattern

```
HEMODYNAMIC INSTABILITY
  Pattern present:   <yes/no/DATA NOT AVAILABLE>
  Hypotension:       <count> readings across <days> days (SBP < 90)
  MAP low:           <count> readings across <days> days (MAP < 65)
  Tachycardia:       <count> readings across <days> days (HR > 120)
```

**Source feature:** `hemodynamic_instability_pattern_v1`

### 4.7 Neuro / Shock Trigger Status

```
TRIGGER STATUS
  Shock triggered:   <yes/no/DATA NOT AVAILABLE>
    Rule:            <trigger_rule_id>
    Type:            <hemorrhagic_likely/indeterminate>
    Vitals:          SBP=<sbp>, BD=<bd>
  Neuro triggered:   <yes/no/DATA NOT AVAILABLE>
    Rule:            <trigger_rule_id>
    GCS:             <value> (source: <source>)
```

**Source features:** `shock_trigger_v1`, `neuro_trigger_v1`

### 4.8 Impression / Plan Drift Summary

```
IMPRESSION/PLAN DRIFT
  Drift detected:        <yes/no/DATA NOT AVAILABLE>
  Days with impression:  <count>
  Days compared:         <count>
  Drift events:          <count>
  Highest drift ratio:   <ratio>
```

**Source feature:** `impression_plan_drift_v1`

---

## 5. Optional / Advanced Sections (Defer Candidates)

These are architecturally ready but deferred from v5 MVP. Each can
be added as an incremental PR once the v5 renderer is stable.

### 5.1 Protocol Status Summary

Render NTDS protocol compliance scores per applicable protocol.
Requires the protocol engine output to be surfaced to the features
layer (currently lives in `outputs/protocols/`).

**Deferral reason:** Protocol engine outputs are not yet wired into
`patient_features_v1.json`. Adding them requires a schema discussion.

### 5.2 Evidence-Age Flags

Flag evidence items that are older than N days relative to the
current day being rendered. Useful for detecting stale carry-forward
data.

**Deferral reason:** Needs a clear policy on staleness thresholds and
which features are subject to aging.

### 5.3 NTDS Pre-Screening Risk Hints

Surface high-risk NTDS event indicators (e.g., predicted non-compliant
items) as QA hints in the daily notes.

**Deferral reason:** NTDS event engine is Tier 4 — must not be
exposed prematurely.

### 5.4 Commitment Gate / Missing-Required-Data Precheck

A "readiness" block at the top of the report listing which required
data elements are present vs. missing (e.g., "BD specimen unknown",
"FAST not documented").

**Deferral reason:** Requires a formal required-data schema definition
that does not yet exist. Can be added once feature coverage is
broader.

---

## 6. Delivery Plan (Phased PR Sequence)

### Phase A: Pre-requisite Extractions

New feature extractors needed before the v5 renderer can be built.
Each is a standalone PR (one goal per PR).

| PR | Feature | Description | Depends On |
|----|---------|-------------|------------|
| A1 | `note_sections_v1` | Extract structured physician note sections (HPI, ROS, Exam, Impression, Plan) from timeline text. Enables narrative integration in v5. | None |
| A2 | Radiology findings refinement | Improve `radiology_findings_v1` coverage (negation handling, laterality, additional injury types). | None |
| A3 | `incentive_spirometry_v1` | Extract incentive spirometry compliance from nursing notes / flowsheets. | None |
| A4 | `transfusion_v1` | Extract blood product administration (PRBC, FFP, platelets, cryo) with timestamps and unit counts. Enables MTP detection. | None |
| A5 | `burn_assessment_v1` | Extract burn TBSA, depth, and location from H&P / burn flow sheets. | None |

### Phase B: Renderer Build

| PR | Deliverable | Description | Depends On |
|----|-------------|-------------|------------|
| B1 | `render_trauma_daily_notes_v5.py` scaffold | Empty renderer with section stubs, baseline wiring, and CLI. Outputs `TRAUMA_DAILY_NOTES_v5.txt`. No v3/v4 changes. | None (uses existing features) |
| B2 | Patient Summary section | Render §4.1 from existing features. | B1 |
| B3 | Established Injury Catalog | Render §4.2 from `radiology_findings_v1`. | B1 |
| B4 | Prophylaxis + trend sections | Render §4.4 + §4.5 (DVT, GI, BD, INR). | B1 |
| B5 | Hemodynamic + trigger sections | Render §4.6 + §4.7 (hemodynamic instability, shock, neuro). | B1 |
| B6 | Impression/Plan drift section | Render §4.8. | B1 |
| B7 | Narrative integration | Merge v3 narrative content (physician notes, imaging, consults) into v5 per-day blocks. | B1, A1 |
| B8 | v5 baseline + gate integration | Add `v5_hashes_v1.json` to gate, enable baseline drift checking for v5. | B1-B7 |

### Phase C: Optional Sections

| PR | Deliverable | Description | Depends On |
|----|-------------|-------------|------------|
| C1 | Protocol status summary | §5.1 — requires protocol engine wiring. | B1, protocol schema decision |
| C2 | Evidence-age flags | §5.2 — staleness thresholds. | B1 |
| C3 | NTDS pre-screening hints | §5.3 — requires NTDS event engine maturity. | B1, Tier 4 |
| C4 | Commitment gate precheck | §5.4 — required-data schema. | B1 |

---

## 7. Acceptance Criteria for v5

### 7.1 Hard Requirements

1. **Deterministic output** — identical input must produce identical
   output, verified by dual-run hash comparison in the gate.
2. **Baseline-managed** — v5 output hashes tracked in
   `scripts/baselines/v5_hashes_v1.json`. Gate fails on unexpected
   drift.
3. **No v3 regression** — v3 output must remain byte-identical unless
   an explicit v3 change is part of the PR scope.
4. **No v4 regression** — v4 output must remain byte-identical.
5. **Evidence traceability** — every displayed claim (vitals value,
   lab result, injury finding, trigger status) must trace to a
   feature module with `raw_line_id` evidence. No free-text claims
   without audit trail.
6. **Fail-closed rendering** — missing features render as
   "DATA NOT AVAILABLE", never silently omitted.
7. **No renderer changes in feature PRs** — feature extraction PRs
   (Phase A) must not modify any renderer. Renderer work is Phase B
   only.

### 7.2 Quality Gates

- All existing tests pass (currently 680+).
- New tests for each v5 section (render correctness, DNA fallbacks).
- Gate passes on all 4 default patients (Anna_Dennis, William_Simmons,
  Timothy_Cowan, Timothy_Nachtwey).
- At least one full 23-patient rebuild before merging B8.

### 7.3 Documentation

- Each new feature (Phase A) gets a contract doc in `docs/contracts/`.
- The v5 renderer gets a contract doc: `docs/contracts/daily_notes_v5.md`.
- This plan (`DAILY_NOTES_V5_PLAN_v1.md`) is updated as sections are
  completed (status column added to tables).

---

## 8. Scope Exclusions

### 8.1 Deaconess Protocol Exclusion

The Deaconess protocol
**"ROLE_OF_TRAUMA_SERVICES_IN_THE_ADMISSION_OR_CONSULTATION_OF_TRAUMA_PATIENTS"**
is intentionally excluded from current protocol scope by operator
decision. Audits should not treat its absence as accidental. This
exclusion applies to both protocol engine evaluation and any future
protocol status summary section in v5.

### 8.2 Out of Scope for v5

- LLM-generated summaries or interpretations.
- PDF export (Tier 4).
- Dashboard / web UI (Tier 4).
- NTDS event scoring (Tier 4 — engine not ready).
- Any modification to v3 or v4 output format.
- Clinical inference or risk prediction.

---

## Appendix A: Feature Module Inventory (as of 2026-02-23)

All modules live under `patient_features_v1.json → features.*`.

| # | Feature Key                          | Contract Doc | Rendered in v4 | v5 Section |
|---|--------------------------------------|--------------|----------------|------------|
| 1 | `vitals_canonical_v1`                | Yes          | Indirectly (vitals trending uses rollups) | §4.1 arrival, §4.3 trending |
| 2 | `dvt_prophylaxis_v1`                 | Yes          | No             | §4.4       |
| 3 | `gi_prophylaxis_v1`                  | Yes          | No             | §4.4       |
| 4 | `base_deficit_monitoring_v1`         | Yes          | No             | §4.5       |
| 5 | `inr_normalization_v1`               | Yes          | No             | §4.5       |
| 6 | `fast_exam_v1`                       | Yes          | No             | §4.1       |
| 7 | `etoh_uds_v1`                        | Yes          | No             | §4.1       |
| 8 | `impression_plan_drift_v1`           | Yes          | No             | §4.8       |
| 9 | `category_activation_v1`             | Internal     | No             | §4.1       |
| 10| `shock_trigger_v1`                   | Yes          | No             | §4.7       |
| 11| `neuro_trigger_v1`                   | Yes          | No             | §4.7       |
| 12| `age_extraction_v1`                  | Yes          | No             | §4.1       |
| 13| `mechanism_region_v1`                | Yes          | No             | §4.1       |
| 14| `radiology_findings_v1`              | Yes          | No             | §4.2       |
| 15| `sbirt_screening_v1`                 | Yes          | No             | §4.1       |
| 16| `hemodynamic_instability_pattern_v1` | Yes          | No             | §4.6       |
| 17| `vitals_qa`                          | Internal     | No             | (QA only)  |

**Rendered in v4:** 4 per-day sections (vitals trending, GCS, labs panel lite, device day counts) — sourced from `days[date].*`, not from `features.*`.

**Available but unrendered:** 16 feature modules with full contracts and evidence traceability.

---

## Appendix B: Per-Day Section Keys (from `days[date].*`)

These are per-day extraction outputs used by v4 and available for v5.

| Key               | Description                           | Used in v4 |
|-------------------|---------------------------------------|------------|
| `labs`            | Legacy + v2 lab extraction per day    | Yes (via labs_panel_daily) |
| `labs_panel_daily`| CBC/BMP/Coags/Lactate/BD panels       | Yes        |
| `devices`         | Device presence + tri-state + carry-forward | Yes (via device_day_counts) |
| `device_day_counts` | Consecutive days + totals           | Yes        |
| `services`        | Service tags + notes_by_service       | No         |
| `vitals`          | Per-metric vitals rollups             | Yes (vitals trending) |
| `gcs_daily`       | GCS arrival/best/worst per day        | Yes        |
