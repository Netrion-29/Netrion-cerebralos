# LDA Engine Design — Device Duration-Aware Gates (Lines, Drains, Airways)

| Field | Value |
|---|---|
| Date | 2026-03-12 |
| Author | Design doc (Sarah / CerebralOS team) |
| Status | IMPLEMENTED (v1+text) — PRs `tier2/lda-engine-impl-v1` (merged), `tier2/lda-text-episodes-v1`; feature flag `ENABLE_LDA_GATES` default False |
| Baseline | `d0b7f5c` (main, post PR #200) |
| Predecessor | `docs/audits/CAUTI_ENGINE_DESIGN_v1.md` (CAUTI-specific; this doc generalizes to all LDA device types) |
| Depends on | Engine authorization; no active PR dependency |

---

## 1. Problem Statement

### 1a. Duration Verification Is Not Possible from Text Patterns Alone

Multiple NTDS events require that a specific device be present for a minimum number of consecutive calendar days before the event can be counted. Current gates use `gate_type: evidence_any` with text patterns. This approach has three systematic limitations:

1. **Duration cannot be computed.** A note stating "Foley catheter in place" on Day 1 satisfies the pattern match — but says nothing about whether the catheter was present on Day 2, Day 3, or beyond. The only way to verify >2 consecutive calendar days is to trace a device episode with a `start_ts` and `stop_ts`.

2. **Multiple independent devices are indistinguishable.** A patient may have two urinary catheters placed and removed during the same admission. Text patterns cannot distinguish overlapping episodes or confirm which specific episode met the duration threshold.

3. **Removal/replacement events are invisible.** Text patterns that detect "Foley in place" cannot see that the catheter was removed on Day 1 and a new one placed on Day 3. Each device episode must be tracked independently to determine whether any single episode meets the threshold.

### 1b. Affected NTDS Events

| NTDS Event | Device | Duration Threshold | Current Gate | Gap |
|---|---|---|---|---|
| E05 CAUTI | Urinary catheter (Foley) | >2 consecutive calendar days | `cauti_catheter_gt2d` (text patterns) | Cannot verify calendar-day continuity |
| E06 CLABSI | Central line (PICC/CVL/CVC) | >2 consecutive calendar days | `clabsi_central_line_gt2d` (text patterns) | Cannot verify calendar-day continuity |
| E21 VAP | Mechanical ventilator (ETT/trach) | >2 consecutive calendar days | `vent_evidence` (text patterns, presence only) | No duration gate at all currently |
| E08 DVT (peds) | Central venous catheter | Risk factor — not threshold | `dvt_dx` (text patterns) | Device risk factor not structured |

### 1c. Affected Protocol Elements

| Protocol | Device | Duration / Threshold | Gap |
|---|---|---|---|
| CAUTI (CDC SUTI 1a) | Urinary catheter | >2 consecutive calendar days | Same as E05 |
| CLABSI (NHSN) | Central line | >2 consecutive calendar days | Same as E06 |
| DVT Prophylaxis — Peds | Central venous catheter | Risk factor (present/absent) | Not structured |
| Spinal / SCI | Foley catheter | Neurogenic bladder indication; q6h CIC transition | Not tracked as episode |
| Burns | Foley catheter | Required for TBSA >90% | Not tracked |
| Hypothermia | All IV lines / warming devices | Fluid warmers in use | Not tracked |

### 1d. Why This Is a New Engine Feature (Not a Pattern Fix)

Text-pattern improvements cannot solve this problem. The gap is structural:

- **What we have:** evidence items with a `source_type` and a `raw_line_id`. No start/stop timestamps for devices.
- **What we need:** structured device episodes with `start_ts`, `stop_ts`, `device_type`, `location`, and a mechanism to evaluate whether any episode meets a duration threshold (e.g., `days >= 2`) at the time of a clinical event.

This requires (a) a new SourceType `LDA` with a defined schema, (b) a PatientFacts builder that assembles LDA episodes from structured feeds or text-derived approximations, and (c) new gate types that operate on episode duration rather than pattern presence.

---

## 2. Proposed Engine Changes

> **Authorization required before any of the following are implemented.**
> All modifications to `cerebralos/ntds_logic/engine.py`,
> `cerebralos/features/build_patientfacts_from_txt.py`,
> and the SourceType enum are **engine-protected**. See §8.

### 2a. New SourceType: `LDA`

Add `LDA` to the `SourceType` enum in `cerebralos/ntds_logic/build_patientfacts_from_txt.py`.

**LDA evidence item schema:**

```json
{
  "source_type": "LDA",
  "raw_line_id": "L4521-L4521",
  "device_type": "URINARY_CATHETER",
  "start_ts": "2026-01-03T14:30:00",
  "stop_ts": "2026-01-07T09:00:00",
  "location": "urethral",
  "inserted_by": "RN",
  "notes": "Foley 16Fr placed for strict I&O",
  "episode_days": 3,
  "source_confidence": "STRUCTURED"
}
```

**`device_type` canonical values:**

| Value | Covers |
|---|---|
| `URINARY_CATHETER` | Foley, indwelling urinary catheter, U-cath |
| `CENTRAL_LINE` | PICC, CVL, CVC, triple lumen, port, PA catheter, Hickman |
| `ENDOTRACHEAL_TUBE` | ETT, oral ET tube, nasotracheal |
| `TRACHEOSTOMY` | Trach tube (surgical or percutaneous) |
| `MECHANICAL_VENTILATOR` | Any mechanical ventilation episode (may span ETT → trach transitions) |
| `CHEST_TUBE` | Thoracostomy tube, pleural drain |
| `NASOGASTRIC_TUBE` | NG tube, OG tube |
| `ARTERIAL_LINE` | A-line, radial/femoral arterial catheter |
| `DRAIN_SURGICAL` | JP drain, Blake drain, wound drain |
| `PERIPHERAL_IV` | PIV (used for device-day counting) |

**`source_confidence` values:**

| Value | Meaning |
|---|---|
| `STRUCTURED` | Start/stop from structured feed (EHR LDA table) |
| `TEXT_DERIVED` | Start estimated from insertion note; stop from removal note or end of admission |
| `TEXT_APPROXIMATE` | Presence inferred from multiple mentions; no reliable start/stop |

### 2b. PatientFacts Builder: LDA Ingest

Add `build_lda_episodes()` to `cerebralos/features/build_patientfacts_from_txt.py`.

**Ingest priority (highest to lowest):**

1. **Structured feed** (`data_raw/$PAT_lda.json` if present) — parse directly; assign `source_confidence: STRUCTURED`.
2. **Insertion note detection** — scan evidence items for insertion language (`placed Foley`, `PICC inserted`, `intubated`) and a timestamp or date; assign `start_ts` from note date; `source_confidence: TEXT_DERIVED`.
3. **Removal note detection** — scan for removal language (`Foley removed`, `PICC pulled`, `extubated`) and assign `stop_ts`.
4. **Presence-only fallback** — if neither insertion nor removal found but device mentioned on multiple days, generate an approximate episode spanning first-mention to last-mention day; `source_confidence: TEXT_APPROXIMATE`.

**Output — added to `patient_features_v1.json` under `"features"` key:**

```json
"lda_episodes_v1": {
  "episodes": [
    {
      "device_type": "URINARY_CATHETER",
      "start_ts": "2026-01-03T14:30:00",
      "stop_ts": "2026-01-07T09:00:00",
      "episode_days": 3,
      "source_confidence": "STRUCTURED",
      "raw_line_ids": ["L4521-L4521", "L6234-L6234"]
    }
  ],
  "device_day_counts": {
    "URINARY_CATHETER": 3,
    "CENTRAL_LINE": 0,
    "MECHANICAL_VENTILATOR": 0
  }
}
```

### 2c. New Gate Types

Add the following gate types to `cerebralos/ntds_logic/engine.py`:

#### `lda_duration`

Evaluates whether any LDA episode of the specified `device_type` meets a duration threshold at the time of the event under evaluation.

```json
{
  "gate_id": "cauti_lda_catheter_gt2d",
  "gate_type": "lda_duration",
  "device_type": "URINARY_CATHETER",
  "days_gte": 2,
  "require_active_on_event_date": true,
  "min_confidence": "TEXT_DERIVED",
  "outcome_if_missing": "EXCLUDED"
}
```

| Parameter | Type | Description |
|---|---|---|
| `device_type` | string | Canonical device type (see §2a) |
| `days_gte` | int | Minimum episode length in days (≥ N) |
| `require_active_on_event_date` | bool | Episode must span the event date if true |
| `min_confidence` | enum | Minimum `source_confidence` to accept; `TEXT_APPROXIMATE` = loose; `TEXT_DERIVED` = medium; `STRUCTURED` = strict |
| `outcome_if_missing` | enum | Outcome when no LDA data at all: `EXCLUDED`, `NO`, or `UNKNOWN` |

#### `lda_present_at`

Evaluates whether a device was present (active episode) on a specific timestamp.

```json
{
  "gate_id": "vent_active_on_event_date",
  "gate_type": "lda_present_at",
  "device_type": "MECHANICAL_VENTILATOR",
  "reference": "event_date",
  "min_confidence": "TEXT_APPROXIMATE"
}
```

#### `lda_overlap`

Evaluates whether two device episodes overlapped within a specified window (e.g., central line and blood culture positive within 2 days).

```json
{
  "gate_id": "clabsi_line_culture_overlap",
  "gate_type": "lda_overlap",
  "device_type": "CENTRAL_LINE",
  "overlap_gate": "clabsi_lab_positive",
  "window_days": 2
}
```

#### `lda_device_day_count`

Returns the total number of device-days for ICU benchmarking and protocol compliance.

```json
{
  "gate_id": "cauti_device_days",
  "gate_type": "lda_device_day_count",
  "device_type": "URINARY_CATHETER",
  "count_gte": 1
}
```

### 2d. Modified Existing Gates

For backward compatibility during migration, existing `evidence_any` duration gates continue to function. A feature flag controls which gate type is active:

```json
"lda_feature_flag": "lda_engine_v1",
"fallback_gate": "cauti_catheter_gt2d_text"
```

When `lda_engine_v1` flag is enabled:
- `lda_duration` gate is evaluated first.
- If no LDA data and `outcome_if_missing: EXCLUDED`, the event is excluded with reason `LDA_DATA_MISSING`.
- If no LDA data and `outcome_if_missing: NO`, text-pattern fallback gate is evaluated.

### 2e. `exclude_if_only_source` (from CAUTI design doc)

Retain the CAUTI-specific mechanism from `docs/audits/CAUTI_ENGINE_DESIGN_v1.md`:

```json
"exclude_if_only_source": ["LAB", "IMAGING"]
```

This excludes events where the only supporting evidence comes from sources that cannot independently confirm clinical diagnosis (lab-only or imaging-only). Generalizes to CLABSI (lab-only) and VAP (imaging-only).

---

## 3. Use Cases

### 3a. CAUTI (E05) — >2 Consecutive Calendar Days

**Current behavior:** `cauti_catheter_gt2d` fires on text patterns that mention a catheter and a duration phrase. Cannot verify calendar-day continuity.

**Proposed behavior with LDA engine:**
1. LDA builder produces `URINARY_CATHETER` episodes with `start_ts` / `stop_ts`.
2. `lda_duration` gate evaluates: any episode with `episode_days >= 2` active on or before the event date?
3. If structured feed unavailable: text-derived episode from insertion/removal notes (medium confidence).
4. If only presence-inferred: `source_confidence: TEXT_APPROXIMATE`; gate passes at reduced confidence; event flagged with confidence label.

**Gate chain (proposed):**
```
cauti_dx AND cauti_lda_catheter_gt2d AND cauti_symptoms AND cauti_culture AND cauti_after_arrival
EXCLUDED: cauti_poa, cauti_chronic_catheter
```

### 3b. CLABSI (E06) — >2 Consecutive Calendar Days

Same pattern as CAUTI. Central line episodes must span >2 calendar days before a positive blood culture that is not present on admission.

**Device types covered:** `CENTRAL_LINE` (PICC, CVL, CVC, triple-lumen, tunneled, port).

**Special case:** Port-a-cath accessed for infusion only — episode starts at first access during current admission, not at original placement. Requires `access_ts` field in structured feed.

### 3c. VAP (E21) — Mechanical Ventilation >2 Days

**Current behavior:** `vent_evidence` gate verifies mechanical ventilation is mentioned but does NOT gate on duration. Duration is the CDC definition requirement.

**Proposed behavior:**
1. `MECHANICAL_VENTILATOR` episode spans ETT placement → extubation (or trach transition).
2. `lda_duration` gate: `device_type: MECHANICAL_VENTILATOR`, `days_gte: 2`.
3. If patient has multiple intubation episodes, any single episode ≥2 days satisfies the gate.

### 3d. DVT Prophylaxis — Pediatric (E08)

Central venous catheter is a documented risk factor in the pediatric DVT Prophylaxis guideline. Current peds DVT risk factor documentation does not capture CVC type, location, or duration.

**Proposed:** `lda_present_at` gate: `device_type: CENTRAL_LINE` present on the day DVT prophylaxis decision is evaluated. Feeds into protocol compliance feature rather than NTDS gate.

### 3e. ICU Device-Day Counting (Protocol Compliance)

NHSN device utilization ratios require:
- Urinary catheter-days per patient-day
- Central line-days per patient-day
- Ventilator-days per patient-day

`lda_device_day_count` gate supports all three. Output stored in `lda_episodes_v1.device_day_counts` in `patient_features_v1.json`.

---

## 4. Backfill Strategy

### Phase 1 — Text-Derived Episodes (No Structured Feed Required)

**Flowsheet day-counter extraction** (IMPLEMENTED in `tier2/lda-text-episodes-v1`):
Scans raw `.txt` lines for flowsheet day-counter patterns such as `Catheter day 3`,
`Line Day: 5`, `CVC day: 2`, `Vent day: 4`. The *highest* day count per device
type is kept. Source confidence = `TEXT_DERIVED`. Covers 13 of 39 cohort patients
(169 matching lines). Helper: `_extract_lda_episodes_from_lines()` in builder.

**Insertion/removal scanning** (DEFERRED — future phase):

Deploy LDA builder in text-derivation mode. For each patient `.txt` file:

1. Scan evidence items for insertion patterns → assign `start_ts`.
2. Scan for removal patterns → assign `stop_ts`.
3. If `stop_ts` missing: default to end of admission.
4. Assign `source_confidence: TEXT_DERIVED` for start+stop; `TEXT_APPROXIMATE` for presence-only.
5. Validate against known ground-truth patients (Ronald_Bittner, Cheryl_Burton, Robert_Sauer).

Insertion patterns (draft):
```
(placed|inserted|insertion of|started|initiated) (foley|urinary cath|u-cath|picc|central line|cvl|cvc|et tube|ett|trach|endotracheal)
```

Removal patterns (draft):
```
(removed|discontinued|dc'?d|pulled|extubated|decannulated) (foley|urinary cath|picc|central line|cvl|et tube|trach)
```

### Phase 2 — Structured Feed Integration

When EHR exports an LDA table (`data_raw/$PAT_lda.json` or similar), the builder prefers structured data over text derivation. Structured feed format (proposed):

```json
{
  "patient_id": "Ronald_Bittner",
  "lda_records": [
    {
      "device_type": "URINARY_CATHETER",
      "label": "Indwelling Urinary Catheter",
      "start_ts": "2026-01-03T14:30:00",
      "stop_ts": "2026-01-07T09:15:00",
      "location": "urethral",
      "size": "16Fr",
      "inserted_by": "RN",
      "removed_by": "RN"
    }
  ]
}
```

### Phase 3 — Gate Migration

Per event, once LDA episodes are validated for the 39-patient cohort:
1. Enable `lda_engine_v1` feature flag for that event.
2. Run full cohort comparison: text-gate outcomes vs LDA-gate outcomes.
3. Investigate any delta patient — confirm LDA result is more accurate.
4. Update baseline hashes and distribution.
5. Disable text-duration gate fallback for that event.

---

## 5. Risks and Mitigations

| Risk | Description | Mitigation |
|---|---|---|
| **Data completeness** | Text-derived episodes will miss insertions not documented in notes | `source_confidence` field; `TEXT_APPROXIMATE` episodes flagged; audit trail in `raw_line_ids` |
| **Time zone / clock skew** | Notes may not have timestamps; date-only resolution may give ±1 day error | Default to day-level granularity; `episode_days` rounded conservatively |
| **Multiple simultaneous devices** | Patient may have 2 Foley catheters (e.g., bladder irrigation) | Each insertion note generates a separate episode; `episode_id` field distinguishes them |
| **ETT → trach transitions** | Intubation removed, trach placed same day — is this continuous ventilation? | Configurable `merge_window_hours` parameter: if gap between ETT-out and trach-in ≤N hours, merge episodes |
| **Partial episodes at admission boundaries** | Device placed before admission; `start_ts` unknown | If admission date known and device mentioned on Day 1 note without insertion language, allow `start_ts = admission_date - 1` for `TEXT_APPROXIMATE` confidence |
| **Discharge summary vs daily note conflict** | Discharge summary may state different durations than daily notes | Prefer earliest insertion note over discharge summary for `start_ts`; log conflict in `warnings` |
| **Feature flag rollout** | Enabling LDA gate may flip outcomes for some patients | Require pre-merge cohort comparison table in PR description |
| **`patient_features_v1.json` contract** | New `lda_episodes_v1` key must be added to contract | Update `validate_patient_features_contract_v1.py` allowed keys before deploying builder |

---

## 6. Testing Strategy

### Unit Tests

| Test | Description |
|---|---|
| `test_lda_builder_structured_feed` | Given a structured `_lda.json` file, verify correct episode parsing |
| `test_lda_builder_text_insertion` | Given evidence items with insertion patterns, verify `start_ts` extracted |
| `test_lda_builder_text_removal` | Given evidence items with removal patterns, verify `stop_ts` extracted |
| `test_lda_builder_presence_only` | Given presence-only mentions across multiple days, verify `TEXT_APPROXIMATE` episode |
| `test_lda_builder_multiple_devices` | Given two Foley insertions, verify two separate episodes |
| `test_lda_duration_gate_pass` | Episode with `episode_days >= 2` on event date → gate passes |
| `test_lda_duration_gate_fail_short` | Episode with `episode_days < 2` → gate fails |
| `test_lda_duration_gate_missing_excluded` | No LDA data and `outcome_if_missing: EXCLUDED` → event excluded |
| `test_lda_duration_gate_missing_fallback` | No LDA data and `outcome_if_missing: NO` → text fallback evaluated |
| `test_lda_present_at_active` | Episode spans event date → gate passes |
| `test_lda_present_at_inactive` | Episode ended before event date → gate fails |
| `test_lda_merge_window` | ETT removed and trach placed within 4 hours → merged into single vent episode |
| `test_lda_device_day_count` | 3-day Foley episode → device_day_counts.URINARY_CATHETER = 3 |
| `test_lda_contract_validation` | `lda_episodes_v1` key present and schema-valid after builder runs |

### Fixture Examples

New fixtures required per event:

**E05 CAUTI:**
- `05_cauti_lda_structured_yes.txt` — structured feed with 3-day Foley, positive culture, symptoms → YES
- `05_cauti_lda_text_derived_yes.txt` — insertion note Day 1, removal note Day 5 → YES
- `05_cauti_lda_short_episode_no.txt` — insertion note Day 1, removal note Day 2 (1 day) → gate fails → NO
- `05_cauti_lda_missing_excluded.txt` — no LDA data, `outcome_if_missing: EXCLUDED` → EXCLUDED

**E06 CLABSI:**
- `06_clabsi_lda_picc_yes.txt` — PICC placed Day 1, positive blood culture Day 4 → YES
- `06_clabsi_lda_short_no.txt` — PICC placed Day 0, removed Day 1 (1 day) → NO

**E21 VAP:**
- `21_vap_lda_vent_gt2d_yes.txt` — intubated Day 1, ventilator-associated pneumonia Day 4 → YES
- `21_vap_lda_vent_lt2d_no.txt` — intubated Day 1, extubated Day 2 (<2 days) → NO

### Backward Compatibility

- All existing text-pattern duration gates remain in place behind the feature flag.
- When `lda_engine_v1` is disabled (default), behavior is identical to current.
- Enabling `lda_engine_v1` for a given event requires a cohort comparison PR that documents all outcome changes and confirms each is clinically correct.
- Baseline hash and distribution updates are mandatory when any outcome changes.

---

## 7. Authorization Requirements

The following are **engine-protected** and require explicit authorization before implementation:

| Change | File(s) | Authorization Required |
|---|---|---|
| Add `LDA` to `SourceType` enum | `cerebralos/ntds_logic/build_patientfacts_from_txt.py` | YES — engine core |
| Add `build_lda_episodes()` builder | `cerebralos/features/build_patientfacts_from_txt.py` | YES — engine core |
| Add `lda_duration` gate type | `cerebralos/ntds_logic/engine.py` | YES — engine core |
| Add `lda_present_at` gate type | `cerebralos/ntds_logic/engine.py` | YES — engine core |
| Add `lda_overlap` gate type | `cerebralos/ntds_logic/engine.py` | YES — engine core |
| Add `lda_device_day_count` gate type | `cerebralos/ntds_logic/engine.py` | YES — engine core |
| Add feature flag evaluation logic | `cerebralos/ntds_logic/engine.py` | YES — engine core |
| Update `patient_features_v1.json` contract | `cerebralos/validation/validate_patient_features_contract_v1.py` | YES — contract |
| Modify NTDS event rule files to use LDA gates | `rules/ntds/logic/2026/05_cauti.json`, `06_clabsi.json`, `21_vap.json` | YES — after engine implementation only |

**Does NOT require separate authorization (docs-only):**
- This design document
- Roadmap / boot header / startup doc updates
- Fixture file additions (no rule or engine changes)
- `test_lda_*.py` unit test stubs (no engine changes)

---

## 8. Relationship to Existing CAUTI Design Doc

`docs/audits/CAUTI_ENGINE_DESIGN_v1.md` (2026-03-11) contains:
- CAUTI-specific LDA gate design (§1a, §2)
- Alternative-source exclusion (`exclude_if_only_source`) design (§1b, §3)
- CAUTI-specific fixture and backward-compat plan

This document (`LDA_ENGINE_DESIGN_v1.md`) **supersedes the CAUTI doc's LDA sections** for the purpose of engine specification, and generalizes to all device types. The CAUTI doc remains authoritative for CAUTI-specific clinical requirements and the `exclude_if_only_source` mechanism.

When engine authorization is granted:
1. Implement the shared LDA infrastructure specified here.
2. Apply it to E05 CAUTI first (as the most clinically validated case).
3. Extend to E06 CLABSI and E21 VAP in subsequent PRs.

---

## 9. Deferred Items (Out of Scope for This Doc)

| Item | Notes |
|---|---|
| Port-a-cath access episode tracking | Requires `access_ts` field; structured feed only; deferred to Phase 2 |
| Ventilator mode tracking (SIMV vs PSV vs CPAP) | Clinical detail for VAP subspecification; not required for NTDS duration gate |
| Drain output volume tracking | Useful for chest tube management; not required for NTDS events |
| LDA-to-protocol compliance mapping | Device presence feeding protocol rules (e.g., Spinal CIC protocol); separate design track |
| EHR LDA feed format negotiation | Depends on Deaconess IT; placeholder schema in §4 Phase 2 |
| Real-time streaming LDA updates | Out of scope for batch pipeline |
