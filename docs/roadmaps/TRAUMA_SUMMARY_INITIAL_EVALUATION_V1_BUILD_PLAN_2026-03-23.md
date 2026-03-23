# Trauma Summary / Initial Trauma Evaluation v1 Build Plan

**Status:** Active build plan  
**Decision Date:** March 23, 2026  
**Depends On:** [TRAUMA_SUMMARY_V1_SPEC_2026-03-23.md](./TRAUMA_SUMMARY_V1_SPEC_2026-03-23.md)  
**Applies To:** Next major trauma-summary implementation slice after in-flight small PRs complete

## Purpose

This document translates the March 23, 2026 Trauma Summary v1 product decision into an implementation plan that Claude and Codex can execute without drifting back into small disconnected changes.

This plan is specifically for the first major build slice:

- **Trauma Summary / Initial Trauma Evaluation v1**

This is the first major section because it establishes the opening frame of the case. If this section is wrong or missing, the rest of the casefile remains clinically flatter than the real chart.

## Current Decision

We will **not**:

- restart the repository from zero
- create a separate repo
- keep doing random casefile patching with no organizing model

We **will**:

- keep the current deterministic pipeline
- keep `patient_bundle_v1`
- keep the current PI RN casefile renderer as the active product surface
- add a new, explicit, self-contained trauma-summary assembly object inside the current bundle
- render a top-of-document Trauma Summary section from that object

This is the concrete implementation choice made on **March 23, 2026**.

## Scope Of This Build Slice

This build slice is only about the **initial trauma evaluation / trauma summary anchor**.

It is **not** the full green-card implementation.

### In Scope

- a new patient-level bundle object for the Trauma Summary anchor
- deterministic assembly from Trauma H&P / initial trauma evaluation sources
- explicit handling of trauma-activated patients even when medicine admits
- top-of-casefile rendering of the Trauma Summary section
- tests, docs, validator, and bundle contract updates

### Out Of Scope

- consultant longitudinal overhaul
- respiratory / ventilator overhaul
- protocol milestone overhaul
- PI/complications structured workspace overhaul
- pretty-output redesign
- NTDS/protocol engine changes
- inference / summarization by model
- replacing the existing full casefile architecture

## Product Goal For This Slice

After this build, the PI RN should be able to open the casefile and immediately understand:

- what trauma activation occurred
- what trauma thought was happening at the start
- what the primary survey showed
- what the immediate injuries and emergencies were
- what the initial trauma plan was
- whether trauma remained primary or another service admitted the patient

without having to reconstruct that opening story from scattered sections.

## Architectural Choice

### Chosen path

Implement the initial trauma evaluation as a new field under the existing bundle:

- `summary.trauma_summary`

and render it as a dedicated patient-level section near the top of the PI RN casefile.

### Why this path

- lowest disruption to the current working product
- does not require a new top-level bundle version immediately
- still creates a clean, explicit object instead of scattering fields
- can later be promoted into a broader `Trauma Summary v1` assembly without redoing the work

### Rejected paths

#### 1. Start from scratch

Rejected because it would discard useful deterministic extraction and assembly work already present in the repo.

#### 2. Keep injecting H&P fragments into existing sections

Rejected because this is what caused product drift and underuse of the H&P anchor.

#### 3. Build a separate renderer first without a bundle object

Rejected because the model needs a stable assembly contract, not direct note parsing in the renderer.

## Source Model

This slice is centered on the **initial trauma evaluation**.

### Primary source precedence

1. Trauma H&P / Trauma H & P
2. trauma tertiary note if needed for missing anchor fields
3. early trauma progress note on day 0/1 when needed
4. activation feature / ADT / demographics for header context
5. admitting medical H&P only for ownership/admission context

### Important rule

The medical/hospitalist H&P does **not** replace the trauma summary.

It may contribute to:

- admitting service
- ownership transition
- confirmation that medicine assumed care

but the trauma summary remains anchored in the trauma activation / trauma evaluation context.

## Required Target Data

The `summary.trauma_summary` object must support the following patient-level review data.

## 1. Source Metadata

Purpose: make it clear what note produced the summary and when.

Required fields:

- `present`: boolean
- `source_note_type`: string or null
- `source_note_datetime`: string or null
- `source_doc_title`: string or null
- `trauma_authored`: boolean or null

## 2. Activation Context

Required fields:

- `trauma_category`: string or null
- `activation_datetime`: string or null
- `trauma_eval_datetime`: string or null
- `arrival_datetime`: string or null
- `from_location`: string or null

## 3. Opening Narrative

Required fields:

- `mechanism_summary`: string or null
- `hpi_summary`: string or null
- `transfer_summary`: string or null

Important rule:

- These are deterministic extracted summaries from the note, not model-written prose.

## 4. Primary Survey

Required fields:

- `airway`: string or null
- `breathing`: string or null
- `circulation`: string or null
- `disability`: string or null
- `gcs`: string or null
- `fast_performed`: string or null
- `fast_result`: string or null

Allowed status patterns:

- explicit factual values only
- `null` when absent

No inferred normalization beyond deterministic parsing.

## 5. Immediate Injury Summary

Required fields:

- `injury_items`: list[str]

Notes:

- this should reflect trauma-documented working injuries
- this is not a replacement for full imaging/injury sections

## 6. Initial Trauma Impression

Required fields:

- `impression_items`: list[str]

Notes:

- direct note-derived items only
- no deduced diagnoses

## 7. Initial Trauma Plan

Required fields:

- `plan_items`: list[str]

Notes:

- this is one of the most important outputs in the object
- maintain note order where possible

## 8. Resuscitation / Emergency Flags

Required fields:

- `mtp_activated`: string or null
- `blood_products`: list[str]
- `intubated`: string or null
- `ventilation_difficulty`: string or null
- `chest_tubes`: list[str]
- `straight_to_or`: string or null
- `emergent_procedure_path`: list[str]

Important rule:

- use explicit factual evidence only
- do not infer severity scores or "major trauma" labels

## 9. Trauma-Initiated Consults

Required fields:

- `consults_initiated`: list[dict]

Each consult item should support:

- `service`: string
- `contacted_datetime`: string or null
- `source_text`: string or null

Important rule:

- only include a contact time if explicitly documented

## 10. Ownership / Admission Context

Required fields:

- `admitting_service`: string or null
- `trauma_primary_initially`: string or null
- `ownership_transition_note`: string or null

Important rule:

- this field family exists so medicine-admit cases still make clinical sense
- it should remain factual, not interpretive

## Bundle Shape

This build slice adds one new key under `summary` in `patient_bundle_v1.json`:

```json
"summary": {
  "...existing_keys": null,
  "trauma_summary": {
    "present": true,
    "source_note_type": "Trauma H&P",
    "source_note_datetime": "2026-03-13T23:00:00",
    "source_doc_title": "Trauma H & P",
    "trauma_authored": true,
    "activation_context": {
      "trauma_category": "Category 1",
      "activation_datetime": "2026-03-13T22:12:00",
      "trauma_eval_datetime": "2026-03-13T22:12:00",
      "arrival_datetime": "2026-03-13T22:12:00",
      "from_location": "outlying facility"
    },
    "opening_narrative": {
      "mechanism_summary": "...",
      "hpi_summary": "...",
      "transfer_summary": "..."
    },
    "primary_survey": {
      "airway": "...",
      "breathing": "...",
      "circulation": "...",
      "disability": "...",
      "gcs": "3T",
      "fast_performed": "YES",
      "fast_result": "inconclusive"
    },
    "injury_items": ["..."],
    "impression_items": ["..."],
    "plan_items": ["..."],
    "resuscitation_flags": {
      "mtp_activated": "YES",
      "blood_products": ["3 units PRBCs prior to arrival"],
      "intubated": "YES",
      "ventilation_difficulty": "YES",
      "chest_tubes": ["bilateral pigtails replaced with large-bore tubes"],
      "straight_to_or": "YES",
      "emergent_procedure_path": ["emergent chest exploration"]
    },
    "consults_initiated": [
      {
        "service": "PCCM",
        "contacted_datetime": null,
        "source_text": "Consult PCCM - vent management."
      }
    ],
    "ownership_context": {
      "admitting_service": "Trauma",
      "trauma_primary_initially": "YES",
      "ownership_transition_note": null
    }
  }
}
```

This JSON is illustrative. Exact values remain fail-closed and evidence-bound.

## Fail-Closed Rules

1. If no valid trauma-summary anchor source is found, set:
   - `summary.trauma_summary = null`
2. Never invent:
   - consult contact times
   - FAST results
   - GCS
   - ownership transitions
3. Do not overwrite explicit trauma-source data with later medical summaries.
4. When fields are absent, prefer:
   - `null`
   - empty list
   depending on the field shape
5. If the source note is not clearly trauma-related, do not label it as a trauma-authored H&P.

## Renderer Placement

The new rendered section should appear high in the patient-level casefile.

### Recommended order

1. current patient header / snapshot
2. **Trauma Summary**
3. injuries / imaging / procedures / devices / prophylaxis
4. SBIRT
5. consultants / daily course / other downstream sections

### Why this order

This keeps the opening clinical story visible before the rest of the downstream detail.

## Rendering Requirements

The Trauma Summary section should render as a high-signal patient-level section, not a wall of text.

### Recommended subsection layout

- activation line
- mechanism / HPI block
- primary survey grid/list
- immediate injuries
- trauma impression
- initial trauma plan
- emergency / resuscitation flags
- trauma-initiated consults
- admitting / ownership context

### Rendering rules

- compact and factual
- preserve clinical labels where helpful
- no model-written prose
- no paragraph stuffing
- omit empty subsections cleanly
- do not surface raw dict/debug output

## Exact Files Expected To Change

This build slice should touch these files:

### Required

- `docs/contracts/patient_bundle_v1.md`
- `cerebralos/reporting/build_patient_bundle_v1.py`
- `cerebralos/validation/validate_patient_bundle_contract_v1.py`
- `cerebralos/reporting/render_pi_rn_casefile_v1.py`
- `tests/test_patient_bundle_v1.py`
- `tests/test_pi_rn_casefile_v1.py`

### Likely new helper / contract doc

One of:

- a new contract doc for the trauma-summary assembly object
- or a dedicated roadmap/build note if kept bundle-local

### Possible implementation helper

One of:

- a helper in `cerebralos/reporting/`
- or a small deterministic assembler helper module

Preferred approach:

- small helper module if it keeps `build_patient_bundle_v1.py` readable

## Data Source Mapping Plan

The build should prefer existing pipeline artifacts and only add new parsing where necessary.

### Already likely available from current artifacts

- demographics
- arrival/discharge timing
- trauma category
- mechanism
- PMH context
- trauma daily plan content
- injury/imaging/procedure/device/prophylaxis summaries

### Needs dedicated trauma-summary assembly logic

- primary survey extraction into stable fields
- trauma H&P anchor selection
- opening HPI / transfer summary extraction
- resuscitation flag extraction from trauma H&P
- trauma-initiated consult extraction
- ownership/admission-context assembly

## Required Pre-Implementation Audit

We do **not** need more audits to approve the direction.

We **do** need one focused raw-note audit before implementing this slice.

### Audit target

Review 6 to 8 real Trauma H&Ps / initial trauma evaluations, including:

- straightforward trauma-admit cases
- medicine-admit but trauma-activated cases
- ICU / high-acuity trauma cases
- penetrating trauma if available

### Audit output

The audit must answer:

1. which H&P headers are stable across current raw files
2. how Primary Survey is represented in real notes
3. how FAST is documented in real notes
4. how trauma-initiated consults and contact times are documented
5. how ownership / medicine-admit transitions are documented
6. which fields are common enough for v1 vs better deferred

This is a narrow implementation audit, not another product-direction debate.

## Test Plan

Tests must prove:

1. bundle contract includes `summary.trauma_summary`
2. validator rejects missing required schema shape where applicable
3. assembler maps present trauma-summary data correctly
4. assembler fail-closes when no valid trauma-summary source exists
5. renderer shows the section when populated
6. renderer omits it cleanly when null
7. renderer handles medicine-admit context correctly
8. no v3/v4 drift

### Required test scenarios

- clear trauma H&P with full Primary Survey and Plan
- trauma H&P with partial fields
- penetrating trauma / high-acuity example
- medicine-admit case with valid trauma summary + ownership context
- no valid trauma-summary anchor
- malformed / partial source data

## PR Shape

This should be one focused PR:

- **Goal:** add Trauma Summary / Initial Trauma Evaluation v1

No additional consultant overhaul, vent overhaul, or protocol overhaul in the same PR.

## Suggested Build Sequence

### Step 1

Run the focused H&P audit and write down the stable field patterns.

### Step 2

Add the new bundle contract shape:

- `summary.trauma_summary`

### Step 3

Implement deterministic assembly logic from the selected source fields.

### Step 4

Render the new Trauma Summary section near the top of the casefile.

### Step 5

Add tests and run:

- targeted tests
- `./scripts/gate_pr.sh`

### Step 6

Review rendered output on a small representative patient set before any wider visual work.

## Success Criteria For This Build Slice

This build slice is successful when:

- the top of the casefile clearly opens with the trauma story
- the PI RN can see activation, primary survey, initial trauma impression, and initial trauma plan quickly
- medicine-admit trauma activations still make sense
- the section feels like the opening of the green-card workflow
- the implementation is deterministic and stable

## What Comes Immediately After

Once this slice is done, the next planned major slices are:

1. `Admitting Service + Consultant / Specialty Course Visibility v1`
2. `Respiratory / Ventilator Course Visibility v1`
3. `Protocol / Care Milestone Alignment v1`
4. `Visual polish`

That sequence is intentional and should not be reordered lightly.

## Guardrail For Future Work

If future discussion starts drifting toward:

- "maybe we should just add one more card"
- "maybe the daily notes are enough"
- "maybe the H&P fragments already cover this"

stop and return to this document.

The standard is:

- build the review workflow on purpose

not:

- hope the workflow emerges from patches.

This is the implementation path chosen on **March 23, 2026**.
