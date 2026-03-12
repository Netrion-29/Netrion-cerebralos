# Source Alignment & Geriatric Delirium Nursing Shift Design — v1

| Field       | Value                                                    |
|-------------|----------------------------------------------------------|
| Date        | 2026-03-11                                               |
| Baseline    | `80d61da` (main, after PR #185)                          |
| Author      | Sarah (operator) + Claude (agent)                        |
| Status      | Design — no rule or engine changes in this PR            |
| Scope       | Recommendations only; implementation deferred            |

---

## 1. Source Alignment: allowed_sources vs Raw DATA SOURCE Hierarchy

### 1.1 Current State

The parser recognises 13 SourceType values:

| SourceType | Pattern anchor | Events using it |
|------------|----------------|-----------------|
| PHYSICIAN_NOTE | `^\[?\s*PHYSICIAN[\s_]+NOTE` | **21/21** (universal) |
| DISCHARGE | `^\[?\s*DISCHARGE` | 14/21 |
| ED_NOTE | `^\[?\s*ED[\s_]+NOTE` + EMERGENCY variant | 13/21 |
| IMAGING | `^\[?\s*IMAGING` / `RADIOLOGY` | 8/21 |
| PROCEDURE | `^\[?\s*PROCEDURE` | 8/21 |
| OPERATIVE_NOTE | compound-prefix anchor | 6/21 |
| NURSING_NOTE | `^\[?\s*NURSING[\s_]+NOTE` | **8/21** |
| LAB | `^\[?\s*LABS?\b` | 5/21 |
| CONSULT_NOTE | prose-before block | **3/21** |
| ANESTHESIA_NOTE | `^\[?\s*ANESTHESIA[\s_]` | 3/21 |
| MAR | `^\[?\s*MAR\b` / `MEDICATION[\s_]+ADMIN` | 1/21 |
| PROGRESS_NOTE | compound-prefix with 20 specialty prefixes | **1/21** |
| UNKNOWN | fallback default | n/a |

### 1.2 Coverage Gap Analysis

**PROGRESS_NOTE** is only allowed in **E21 VAP** (`vent_evidence` gate). This is
the most severe gap. PROGRESS_NOTE headers appear across virtually all patients
(specialty consults, hospital daily notes, trauma follow-ups). Many contain
clinically relevant evidence for diagnosis gates that currently cannot see it.

**NURSING_NOTE** is allowed in 8/21 events. The 13 events that exclude it:

| # | Event | Risk of nursing evidence loss |
|---|-------|-------------------------------|
| 01 | AKI | **Low** — AKI is a physician/lab diagnosis |
| 02 | ARDS | **Low** — ARDS requires physician/imaging confirmation |
| 05 | CAUTI | **Medium** — catheter-related observations happen in nursing notes |
| 06 | CLABSI | **Medium** — central line care is documented by nurses |
| 07 | Deep SSI | **Low** — surgical site assessment is operative/physician-driven |
| 10 | MI | **Low** — MI is a physician/lab/ECG diagnosis |
| 11 | Organ Space SSI | **Low** — same as Deep SSI |
| 12 | Osteomyelitis | **Low** — imaging/surgical diagnosis |
| 15 | Severe Sepsis | **Medium** — sepsis screening (qSOFA) may appear in nursing notes |
| 16 | Stroke/CVA | **Low** — stroke is diagnosed by physician/imaging |
| 17 | Superficial SSI | **Low** — wound assessments are also in physician notes |
| 19 | Unplanned Intubation | **Low** — intubation is a procedure event |
| 20 | OR Return | **Low** — surgical event |

**CONSULT_NOTE** is only allowed in 3 events (E08 DVT, E09 Delirium, E14 PE).
This is a moderate gap — specialty consult notes (cardiology, nephrology,
infectious disease) contain diagnostic assessments relevant to MI, Sepsis,
ARDS, Stroke.

### 1.3 Recommendations

#### Tier 1 — High-confidence additions (low FP risk)

| Event | Gate | Source to add | Rationale |
|-------|------|---------------|-----------|
| E05 CAUTI | `cauti_dx` | NURSING_NOTE | Catheter insertion/removal and UTI symptoms documented in nursing |
| E06 CLABSI | `clabsi_dx` | NURSING_NOTE | Central line care documented in nursing |
| E15 Severe Sepsis | `sepsis_dx` | NURSING_NOTE | qSOFA scoring, sepsis screening done by nurses |
| E01 AKI | `aki_dx` | CONSULT_NOTE | Nephrology consults contain AKI diagnosis |
| E10 MI | `mi_dx` | CONSULT_NOTE | Cardiology consults contain MI diagnosis |
| E15 Severe Sepsis | `sepsis_dx` | CONSULT_NOTE | ID consults contain sepsis diagnosis |
| E16 Stroke/CVA | `stroke_dx` | CONSULT_NOTE | Neurology consults contain stroke diagnosis |

#### Tier 2 — PROGRESS_NOTE expansion (requires impact analysis)

PROGRESS_NOTE should be considered for events where daily physician
assessments are the primary evidence source. However, PROGRESS_NOTE
sections often contain cross-referenced information from multiple
events, increasing false-positive risk.

**Recommended approach:**
1. Run a scoping pass: for each event, count how many patients have
   evidence-matching lines in PROGRESS_NOTE sections that are currently
   invisible to the engine.
2. For events with >0 invisible matches, assess FP risk per patient.
3. Add PROGRESS_NOTE to gates with confirmed true-positive recall gain
   and acceptable FP rate.

**Candidate events for PROGRESS_NOTE:**
- E01 AKI — "AKI" frequently appears in daily progress notes
- E08 DVT — DVT management tracked in daily progress
- E09 Delirium — delirium assessments in daily progress
- E10 MI — MI workup tracked in daily progress
- E15 Severe Sepsis — sepsis management in daily progress
- E16 Stroke/CVA — stroke evolution in daily progress

#### Tier 3 — No change recommended

| Event | Source | Reason to exclude |
|-------|--------|-------------------|
| E05–E07 CAUTI/CLABSI/Deep SSI | PROGRESS_NOTE | Hospital-acquired infections have specific procedural documentation; progress notes add noise |
| E11 Osteomyelitis | NURSING_NOTE | Osteomyelitis is an imaging/surgical diagnosis |
| E12 OR Return | NURSING_NOTE | Surgical event, not nursing-assessed |
| E17 Superficial SSI | PROGRESS_NOTE | Wound notes in progress sections are often cross-references |
| E19 Unplanned Intubation | NURSING_NOTE | Intubation is a procedural event |
| E20 OR Return | NURSING_NOTE | Surgical event |

### 1.4 Justification for Prior ED_NOTE and ANESTHESIA_NOTE Additions

- **ED_NOTE** (12 events, PR #173): ED physician notes contain identical
  diagnostic content to PHYSICIAN_NOTE but were classified separately after
  D6-P5 EMERGENCY source-detection hardening. Clinical content is identical
  to physician documentation. 0 NTDS outcome deltas confirmed the addition
  was safe.

- **ANESTHESIA_NOTE** (E19, E20, PR #174): Anesthesia notes document
  intubation procedures and OR details directly relevant to Unplanned
  Intubation and OR Return events. 0 NTDS outcome deltas on addition.

### 1.5 Implementation Plan

Each tier should be implemented as a separate single-goal PR:
1. **Tier 1 PR**: Add CONSULT_NOTE and NURSING_NOTE to 7 gates (listed above).
   Run full 39-patient validation. Expected: small recall improvements, 0–3
   outcome deltas.
2. **Tier 2 PR**: After Tier 1 merge, run PROGRESS_NOTE scoping pass. One PR
   per batch of events with confirmed gain.
3. No Tier 3 changes are planned.

---

## 2. Geriatric Delirium Nursing Shift Assessment Design

### 2.1 Clinical Background

Geriatric trauma patients (age ≥ 65) are at elevated risk for hospital-acquired
delirium. Standard of care requires structured delirium screening at regular
intervals, typically aligned with nursing shift changes:

| Shift | Times | Assessment |
|-------|-------|------------|
| Day | 06:30 – 19:00 | bCAM or CAM-ICU screening |
| Night | 18:30 – 07:00 | bCAM or CAM-ICU screening |

The NTDS E09 Delirium event currently detects delirium via the `delirium_dx`
mapper bucket (7 patterns) with `delirium_negation_noise` exclusion (10 patterns).
It does NOT specifically track whether structured nursing shift assessments
were performed or documented.

### 2.2 Current E09 State

| Component | Current |
|-----------|---------|
| Gate | `delirium_dx` (evidence_any) — 7 patterns |
| Noise | `delirium_negation_noise` — 10 patterns |
| Exclusion | `delirium_excl_poa` (history_noise + sentence_window proximity) |
| Allowed sources | PHYSICIAN_NOTE, NURSING_NOTE, CONSULT_NOTE, ED_NOTE |
| E09 distribution | YES=2 (Dallas_Clark, George_Kraus), EXCLUDED=1 (Carlton_Van_Ness), NO=36 |

### 2.3 CAM/bCAM Prevalence in Cohort

Structured delirium screening tools are present across 24/39 patients:

| Tool | Patients with ≥1 mention | Total mentions |
|------|--------------------------|----------------|
| bCAM | 20 | 375+ |
| CAM-ICU | 17 | 345+ |
| Delirium screen | 11 | 19+ |
| Confusion Assessment Method | 10 | 45+ |

**Key observations:**
- bCAM is the primary non-ICU screening tool (used in NURSING_NOTE sections)
- CAM-ICU is the ICU variant (also in NURSING_NOTE sections)
- Most screening results are **negative** ("Overall bCAM: Negative",
  "Overall CAM-ICU: Negative")
- Positive results appear as "CAM positive", "bCAM: Positive",
  "Feature 1: Acute Onset or Fluctuating Course: Yes"

### 2.4 Current Detection Gaps

1. **CAM-ICU positive results** are not in the `delirium_dx` mapper. Only
   `CAM positive` and `CAM-positive` are matched. "CAM-ICU: Positive"
   uses a different format and could be missed.

2. **bCAM positive results** are not in the `delirium_dx` mapper. Format:
   "Overall bCAM: Positive" or "bCAM Screening: Positive".

3. **Feature-level positive indicators** (from CAM/bCAM subscales) are not
   matched: "Feature 1: Acute Onset or Fluctuating Course: Yes" — these
   are currently only captured when they co-occur with a text line also
   containing "delirium" or "acute confusional state".

4. **No shift-level tracking.** The engine has no concept of "was a
   delirium screening performed on each nursing shift?" This is a
   compliance/quality metric rather than an outcome detection issue.

### 2.5 Proposed Mapper Additions

New patterns for `delirium_dx` (candidates for future implementation PR):

```
\bCAM[-\s]?ICU\s*:\s*positive\b
\bbCAM\s*:\s*positive\b
\boverall\s+(bCAM|CAM[-\s]?ICU)\s*:\s*positive\b
\bbCAM\s+screening\s*:\s*positive\b
```

New patterns for `delirium_negation_noise` (candidates):

```
\bCAM[-\s]?ICU\s*:\s*negative\b
\bbCAM\s*:\s*negative\b
\boverall\s+(bCAM|CAM[-\s]?ICU)\s*:\s*negative\b
\bbCAM\s+screening\s*:\s*negative\b
```

### 2.6 Shift Assessment Compliance Design

**Goal:** Track whether delirium screening was documented on each nursing
shift for geriatric trauma patients (age ≥ 65).

**Approach:** This is a NEW NTDS supplemental metric, not a change to E09
outcome logic. It would require:

1. **Age extraction** from patient file header (look for `AGE:` or
   `DATE_OF_BIRTH:` field). Not currently extracted by the runner.
2. **Shift window definition:** Day (06:30–19:00), Night (18:30–07:00).
3. **Assessment evidence scan:** For each shift window, check if a bCAM
   or CAM-ICU result line exists in NURSING_NOTE sections with a
   timestamp falling within the window.
4. **Gap reporting:** List shifts where no assessment was found. This is
   a quality metric, not an outcome gate.

**Engine impact:** This would require a new gate type
(`compliance_per_shift` or similar) that is NOT currently supported by the
NTDS engine. Adding it would require engine modification (PROTECTED).

**Recommended phased approach:**
1. **Phase 1 (no engine change):** Add a standalone script
   (`scripts/audit_delirium_shifts.py`) that scans patient data and
   produces a shift-compliance report. This validates the patterns and
   data availability before committing to engine changes.
2. **Phase 2 (engine change, requires approval):** If Phase 1 confirms
   viable data, propose a `compliance_per_shift` gate type to the engine
   to formalise the shift-coverage metric.

### 2.7 Implementation Plan

| # | Item | Scope | Effort | Prereqs |
|---|------|-------|--------|---------|
| 1 | Add CAM-ICU/bCAM positive patterns to `delirium_dx` | Mapper | Small | None |
| 2 | Add CAM-ICU/bCAM negative patterns to `delirium_negation_noise` | Mapper | Small | None |
| 3 | Run impact analysis of new patterns across 39 patients | Script | Small | #1, #2 |
| 4 | If deltas are acceptable, merge mapper changes | PR | Small | #3 |
| 5 | Build `scripts/audit_delirium_shifts.py` standalone | Script | Medium | None |
| 6 | Propose `compliance_per_shift` engine gate type | Design doc | Medium | #5 |

---

## 3. Ronald_Bittner Follow-Up

### 3.1 Current Outcomes

| Event | Outcome | Evidence sources |
|-------|---------|-----------------|
| E01 AKI | **UNABLE_TO_DETERMINE** | LAB (2 lines: "Acute kidney injury") |
| E13 Pressure Ulcer | **YES** | DISCHARGE (1 line) |
| E15 Severe Sepsis | **YES** | LAB (2 lines) |
| E19 Unplanned Intubation | **YES** | PROCEDURE (6 lines) |
| E21 VAP | **YES** | PROCEDURE (8 lines) + IMAGING (2 lines) |

### 3.2 Notable Characteristics

- **All evidence is from structured sections** (LAB, DISCHARGE, PROCEDURE,
  IMAGING). Zero evidence from PHYSICIAN_NOTE, NURSING_NOTE, CONSULT_NOTE,
  PROGRESS_NOTE, or ED_NOTE.
- This is unusual — most patients have mixed evidence sources.

### 3.3 E01 AKI UTD Root Cause

Ronald_Bittner's AKI passes `aki_dx` (2 LAB evidence lines with text
"Acute kidney injury") but fails `aki_after_arrival` because the onset
evidence — "Mild AKI, improving" — is in a section with SourceType
"Held" (not in `allowed_sources` for `aki_after_arrival`). This is a
parser source-detection issue: the "Held" section is a physician note
sub-section that the parser doesn't recognise as PHYSICIAN_NOTE.

**Fix requires:** Either (a) parser enhancement to handle "Held" section
headers, or (b) engine modification to inherit parent section SourceType
for unrecognised sub-sections. Both are engine-adjacent changes.

### 3.4 E13 Pressure Ulcer Validation

E13 was confirmed as a true positive in the D4 DISCHARGE precision audit
(PR #182). The single DISCHARGE evidence line correctly identifies a
documented hospital-acquired pressure ulcer. **No action needed.**

### 3.5 E21 VAP Validation

E21 was validated during the FLAG 002 VAP vent gate work. The
`vent_evidence` gate (8 PROCEDURE lines) and `vap_evidence` gate (2
IMAGING lines) both pass with legitimate evidence. **No action needed.**

### 3.6 Actionable Items

| # | Item | Priority | Effort |
|---|------|----------|--------|
| 1 | Investigate "Held" SourceType for Ronald_Bittner — parser traces needed | Medium | Small |
| 2 | If "Held" is a parser gap, design fix (may be engine-adjacent) | Medium | Medium |
| 3 | Spot-check E15 Severe Sepsis evidence for TP confirmation | Low | Small |
| 4 | Spot-check E19 Unplanned Intubation evidence for TP confirmation | Low | Small |

---

## 4. Summary of Deferred Implementation Items

| # | Item | Source | Priority | Blocked by |
|---|------|--------|----------|------------|
| 1 | Tier 1 source alignment (CONSULT_NOTE + NURSING_NOTE to 7 gates) | §1.3 | High | Nothing — ready to implement |
| 2 | Tier 2 PROGRESS_NOTE scoping pass | §1.3 | Medium | Tier 1 merge |
| 3 | CAM-ICU/bCAM mapper expansion | §2.5 | High | Nothing — ready to implement |
| 4 | Delirium shift compliance standalone script | §2.6 | Medium | Nothing — standalone |
| 5 | `compliance_per_shift` engine gate type | §2.6 | Low | Phase 1 validation + engine approval |
| 6 | Ronald_Bittner "Held" SourceType investigation | §3.6 | Medium | Nothing — standalone |
| 7 | PMH-aware gate handling | Roadmap #11 | Medium | Engine approval |

---

_End of document._
