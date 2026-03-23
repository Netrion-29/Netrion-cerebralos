# Trauma Summary / Initial Trauma Evaluation v1 Build Plan

**Status:** Active build plan  
**Decision Date:** March 23, 2026  
**Depends On:** [TRAUMA_SUMMARY_V1_SPEC_2026-03-23.md](./TRAUMA_SUMMARY_V1_SPEC_2026-03-23.md)

## Purpose

This is the first major implementation slice for Trauma Summary v1.

The goal is to make the casefile open with the trauma story instead of
forcing the reviewer to reconstruct it from scattered sections.

This slice also supports Sarah's first-review workflow by improving the
top-of-document understanding of:

- age / patient context
- MOI
- injuries
- early trauma plan

Consultant visibility and blood-thinner prominence remain important, but
full consultant visibility is a later slice and anticoagulant context is
already partly available from existing summary data.

## Scope

### In scope

- a dedicated patient-level trauma summary assembly object
- deterministic assembly from Trauma H&P / initial trauma evaluation
- explicit handling of trauma-activated patients even when medicine admits
- top-of-casefile Trauma Summary rendering

### Out of scope

- consultant longitudinal overhaul
- ventilator / respiratory overhaul
- protocol milestone overhaul
- broad visual redesign

## Implementation Choice

For this slice, we will keep the current casefile infrastructure and add
a new bundle object under:

- `summary.trauma_summary`

This avoids:

- repo restart
- renderer-only hacks
- more fragment scattering

## `summary.trauma_summary` should contain

- source metadata
- activation context
- opening narrative
- primary survey
- injury items
- impression items
- plan items
- resuscitation flags
- trauma-initiated consults
- ownership / admission context

## Required source precedence

1. Trauma H&P / Trauma H & P
2. trauma tertiary note if needed
3. early trauma progress notes if needed
4. activation / ADT / demographics for context
5. medical/hospitalist H&P only for ownership context

Important rule:

- medical admission context supplements the trauma summary
- it does not replace it

## Required files to change

- `docs/contracts/patient_bundle_v1.md`
- `cerebralos/reporting/build_patient_bundle_v1.py`
- `cerebralos/validation/validate_patient_bundle_contract_v1.py`
- `cerebralos/reporting/render_pi_rn_casefile_v1.py`
- `tests/test_patient_bundle_v1.py`
- `tests/test_pi_rn_casefile_v1.py`

## Required focused audit before implementation

Review 6 to 8 real H&Ps / initial trauma evaluations and answer:

1. which H&P headers are stable
2. how Primary Survey is represented
3. how FAST is documented
4. how trauma-initiated consults and contact times are documented
5. how medicine-admit ownership transition is documented
6. which fields are common enough for v1 vs better deferred

This is a narrow implementation audit, not another direction debate.

## Success Criteria

This slice is successful when:

- the top of the casefile clearly opens with the trauma story
- activation, primary survey, trauma impression, and initial plan are easy to see
- medicine-admit trauma activations still make sense
- the section feels like the opening of the PI RN workflow
- the section makes it easier to establish injuries and clinical course
  before protocol/PI review

## Rendering Direction For Later Polish

The long-term output target remains:

- narrative case review
- with structured panels
- plus dashboard-like utility for patient tracking

This first slice should therefore avoid locking the renderer into either
extreme:

- pure form-only green-card mimicry
- pure prose-only narrative

## What comes next

After this slice:

1. Admitting Service + Consultant / Specialty Course Visibility v1
2. Respiratory / Ventilator Course Visibility v1
3. Protocol / Care Milestone Alignment v1
4. Pretty output

This plan was chosen on **March 23, 2026**.
