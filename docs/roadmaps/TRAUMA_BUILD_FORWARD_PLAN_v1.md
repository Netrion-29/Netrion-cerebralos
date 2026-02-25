# Trauma Build-Forward Plan v1

| Field   | Value                          |
|---------|--------------------------------|
| Date    | 2026-02-21 (updated 2026-02-25)|
| Owner   | Sarah                          |
| Status  | Active                         |

---

## Execution Status (updated 2026-02-25)

### Completed & Merged

| #  | PR  | Branch / Item                         | Status    | Merged   |
|----|-----|---------------------------------------|-----------|----------|
| 1  | #40 | urine-output-events-v1                | MERGED    | ✅       |
| 2  | #41 | daily-notes-v5-refinement-v1          | MERGED    | ✅       |
| 3  | #42 | consultant-plan-items-v1              | MERGED    | ✅       |
| 4  | #44 | consultant-plan-actionables-v1        | MERGED    | ✅       |
| 5  | #45 | daily-notes-v5-refinement-v2          | MERGED    | ✅       |
| 6  | #46 | patient-movement-v2                   | MERGED    | ✅       |
| 7  | #47 | adt-transfer-timeline-v2              | MERGED    | ✅       |

### In Flight

| #  | PR  | Branch / Item                         | Status    | Notes                |
|----|-----|---------------------------------------|-----------|----------------------|
| 8  | #48 | tier1/lda-urine-v2                    | OPEN PR   | Tab-format B parser, cross-source dedup |

### Revised Priority Queue (next items)

| Priority | Branch / Item                         | Scope      | Rationale                  |
|----------|---------------------------------------|------------|----------------------------|
| **NEXT** | `arrival-vitals-selector-v2`          | 1 file + tests | Selector bug: NURSING_NOTE + TABULAR not in priority list; TRAUMA_HP window too tight. Fixes 4/5 patients immediately. Unblocks shock_trigger. |
| 2        | `vitals-upstream-bittner-fix`         | Investigation | Ronald Bittner arrival-day 0 records (date assignment gap). Targeted, 1 patient. |
| 3        | `sbirt_screening_v2`                  | Feature    | SBIRT extraction refinement |
| 4        | `consultant-coverage-refinement`      | Feature    | Consultant plan actionables quality |
| 5        | `daily-notes-v5-refinement-v3`        | Renderer   | Polish bundle (renderer cleanup) |
| 6        | Decision fork: protocol checks OR NTDS protected-engine fix track | | After refinements stable |

### Vitals Audit Findings (2026-02-25)

See: `docs/audits/vitals_coverage_audit_2026-02-25.md`

**TL;DR**: Vitals extraction pipeline works (per-day vitals + canonical records
populated). The arrival vitals selector fails because:
- `NURSING_NOTE` and `TABULAR` source types are not in `_ARRIVAL_SOURCE_PRIORITY`
- `TRAUMA_HP` window (30 min) is too tight for Visit Vitals timestamps
- Ronald Bittner has 0 arrival-day records (upstream date assignment issue)

**Fix track**: `arrival-vitals-selector-v2` (selector-only, ~50 LOC, 1 file)

### Definition of Project Completion (near-term)

Before declaring v5 feature layer + notes stable enough to pivot to
protocol/NTDS tracks, ALL of the following must be true:

1. **Arrival Vitals**: ≥ 4/5 audit patients produce a selected arrival vital
   (not DNA). Shock trigger evaluates for those patients.
2. **LDA + Urine**: PR #48 merged. Snapshot dedup + cross-source dedup active.
3. **Per-day vitals trending**: All patients with raw vitals data show populated
   vitals trending in v5 output (already true today).
4. **Gate passes**: All gate patients (Anna_Dennis, William_Simmons,
   Timothy_Cowan, Timothy_Nachtwey) pass determinism + zero-drift gate.
5. **No DNA cascades**: Arrival Vitals DNA should not cascade into downstream
   feature DNA (shock trigger, neuro trigger) for patients that have vitals data.
6. **Contract docs current**: All feature contracts reflect actual behavior.
7. **Test coverage**: ≥ 80 feature-layer tests passing.

Once these are met, the project can pivot to:
- SBIRT screening refinement
- Protocol checks / NTDS protected-engine work
- Consultant coverage scoring

---

## Tier 0: Vitals Refinement (Foundation for Everything Else)

Vitals extraction + draft rendering already exist. Next is making it
clinically trustworthy and metric-ready.

### 0.1 Normalize Vitals into a Canonical Schema

Goal: every extracted vital becomes a comparable record.
No new architecture — just stricter output.

Canonical fields (suggested):

- `ts` — ISO, from timeline
- `day` — calendar day bucket (already exists)
- `source` — TRAUMA_HP / ED VS / ICU flowsheet / nursing note / monitor strip text
- `sbp_dbp_map` — mmHg
- `hr` — bpm
- `rr` — rpm
- `spo2` — %
- `temp_c` + `temp_f` — store both if available
- `o2_device` + `o2_flow_lpm` + `fio2` — when present
- `position` — optional
- `confidence` — deterministic score based on source + formatting integrity
- `raw_line_id` — so you can audit back to evidence

### 0.2 Vitals Abnormal Flags (Deterministic, Tunable)

For each vital record, compute flags:

| Flag          | Condition          |
|---------------|--------------------|
| Hypotension   | sbp < 90           |
| Severe HTN    | sbp >= 180 (opt.)  |
| Tachycardia   | hr > 120           |
| Bradycardia   | hr < 50 (opt.)     |
| Fever         | temp_c >= 38.0     |
| Hypothermia   | temp_c < 36.0      |
| Hypoxia       | spo2 < 90          |
| Tachypnea     | rr > 24            |

Store per record:

- `abnormal_flags: [...]`
- `abnormal_count`

### 0.3 "Best Value" Selectors per Time Window (Arrival Metrics)

Deterministic selectors needed:

- **Arrival vitals** — first reliable within X minutes of arrival, or Trauma H&P hard-priority
- **Worst SBP in first hour**
- **Worst SpO2 in first hour**
- **Peak temp per day**
- **Worst shock profile** (SBP + BD later)

This stops "which vital do we use?" from becoming a chaos demon.

---

## Tier 1: Immediate Clinical Accuracy Metrics

These sit directly on top of the timeline + labs matrix + carry-forward.

### 1) Arrival-to-First DVT Prophylaxis Hours

**Definition:** time from `arrival_ts` → first documented prophylaxis action.

Inputs: MAR-like text, orders, "SCDs on", heparin/lovenox admin,
"chemical prophylaxis held".

Output:

- `first_dvt_proph_ts`
- `arrival_to_dvt_proph_hours`
- `delay_flag`: >24 h

### 2) Arrival-to-First GI Prophylaxis Hours

Similar pattern.

Evidence: PPI/H2 blocker orders/admin, "GI prophylaxis not indicated".

Output + `delay_flag`: >48 h.

### 3) Category I Base Deficit Validation (Arterial Source Check)

High PI value, easy to get wrong.

Requirements:

- BD value present
- Specimen type arterial (ABG) vs venous (VBG) via lab metadata / line text

Output:

- `base_deficit_value`
- `base_deficit_ts`
- `source_type`: arterial | venous | unknown
- `category1_bd_validated`: yes / no
- `validation_failure_reason` (deterministic string)

### 4) INR Extraction Normalization

Normalize:

- Numeric parsing (strip qualifiers)
- Ensure unitless
- Store `inr_value`, `ts`, `source_lab`

Sanity gates:

- Reject if looks like PT seconds unless explicitly INR
- Store `parse_warning` rather than guessing

### 5) FAST Exam Extraction (YES/NO + Timestamp)

Detect:

- FAST positive / negative / indeterminate
- Timestamp from closest header / procedure line / ED note time anchor

Output:

- `fast_performed`: yes / no
- `fast_result`: positive | negative | indeterminate
- `fast_ts`
- `evidence_line_id`

### 6) Primary Survey GCS Hard-Priority from TRAUMA_HP

TRAUMA_HP wins unless absent.

Output:

- `gcs_primary_survey`
- `gcs_source`: trauma_hp | ed_note | flowsheet | unknown
- `gcs_ts` (if present)
- `arrival_gcs_value` (selected by arrival selector rules)

### 7) ETOH + UDS Extraction with Timestamp Validation

Store:

- `etoh_value` (numeric if available, else qualitative)
- `etoh_ts`
- `uds_panel`: {amphetamines: pos/neg, …}
- `uds_ts`

Timestamp validation:

- Must fall after arrival and before discharge (catches chart ghosts)
- If missing ts, mark DATA NOT AVAILABLE rather than inferring

### 8) Admitting MD Fallback Logic Improvement

Deterministic hierarchy:

1. Admission order provider
2. H&P author
3. ED attending (if admit doc missing)
4. Trauma service attending on call (if schedule input exists later)

Output:

- `admitting_provider_name`
- `admitting_provider_role_guess` (optional)
- `provider_source_rule_id`

### 9) Impression/Plan Drift Diffing Across Days

Deterministic (no LLM):

- Extract Impression/Plan bullets per day
- Normalize: lowercase, strip dates, replace vitals/labs numbers with `<NUM>`, stable sentence hashing
- Compute: `added_items`, `removed_items`, `persisted_items`
- Drift score: `drift_ratio = (added + removed) / max(prev_items, 1)`

This becomes a "plan churn" QA signal.

---

## Tier 2: Trauma-Specific Intelligence Layer (Still Deterministic)

Rule engines sitting on normalized features.

### Neuro Emergency Trigger: GCS < 9 on Arrival

- Uses arrival GCS selector.
- Output: `neuro_emergency_triggered` (yes/no), `trigger_ts`, evidence.

### Shock Detection: SBP < 90 + BD > 6

- SBP from arrival or first-hour worst (define rule explicitly).
- BD must be validated arterial (or mark uncertain).
- Output: `shock_detected` (yes/no), `shock_type` (hemorrhagic_likely | indeterminate), `supporting_evidence_ids`.

### Massive Transfusion Detection

Deterministic patterns:

- MTP activation text
- PRBC units within time window (if blood product extraction exists)
- "cooler", "level 1", "massive transfusion protocol"

Output: `mtp_activated` (yes/no), `mtp_ts`, `units_prbc_6h` (if extractable).

### Spine Clearance Timing Metric

- `arrival_ts` → `spine_clear_ts`
- Flag if > X hours (threshold set later)

### Tourniquet Duration Calculation

- `tourniquet_on_ts`, `tourniquet_off_ts`
- `duration_minutes`
- `duration_flag` (e.g., >120 min)

### DVT Prophylaxis Delay Flag (>24 h)

Falls out of Tier 1 #1. Add rule + classification:

- Mechanical only vs chemical started vs contraindicated

### GI Prophylaxis Delay Flag (>48 h)

Same pattern.

---

## Tier 3: Structural Hardening

Keeps regressions from creeping in as extraction grows.

### Golden-File Regression Tests

For each regression patient, store a small "golden" JSON subset:

- Arrival vitals selection
- Key labs (BD, INR)
- FAST result
- GCS arrival
- DVT/GI timestamps + hours

Compare outputs exact-match (or stable-hash match) on every run.

### Automatic Diff Comparison on Pipeline Run

Emit:

- `run_id`, `git_commit`, `patient_id`, `artifact_hashes`

Produce a diff report file when anything changes.

### Missing Nursing Documentation Detector

Deterministic signals:

- Gap-day detection already exists.
- Add: "no nursing note / flowsheet vitals for >N hours" during ICU stay.

Output: `nursing_doc_gap_intervals[]`

### Discharge-vs-H&P Discrepancy QA

Compare:

- H&P injury list vs discharge diagnoses / problem list text (if available)

Output:

- `new_dx_on_discharge_not_in_hp[]`
- `hp_dx_not_on_discharge[]`

### Consultant Coverage Completeness Scoring

If consult orders/notes exist:

- Expected consult types based on injuries (future)
- For now: "consult mentioned" vs "consult note exists"

Output: `consult_coverage_score_0_to_1`

---

## Tier 4: Future Layer (Only After Extraction Is Rock-Solid)

- NTDS event engine
- Protocol compliance scoring
- Automated PI packet builder
- PDF export
- Dashboard

Timeline + features must be correct first, or NTDS/protocol scoring
becomes confidently wrong.

---

## Build-Forward Order (Minimizes Rework)

Each step unlocks the next without rewiring:

| Step | Item                                           |
|------|------------------------------------------------|
| 1    | Vitals canonicalization + abnormal flags + arrival selectors |
| 2    | DVT/GI timestamps + delay flags                |
| 3    | BD arterial validation + INR normalization      |
| 4    | FAST + Primary Survey GCS priority              |
| 5    | ETOH/UDS timestamp validation                   |
| 6    | Impression/Plan drift diff                      |
| 7    | Shock + Neuro triggers                          |
| 8    | Tourniquet duration + spine clearance timing    |
| 9    | Golden files + auto diff + missing nursing doc  |

This is the shortest path to "clinically defensible metrics" with the
least thrash.
