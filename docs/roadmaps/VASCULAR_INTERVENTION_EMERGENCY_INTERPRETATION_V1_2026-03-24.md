# Vascular Intervention Emergency Interpretation v1

**Status:** Authoritative protocol/accountability interpretation  
**Decision Date:** March 24, 2026  
**Depends On:** [REVIEW_ARCHITECTURE_V1_2026-03-23.md](./REVIEW_ARCHITECTURE_V1_2026-03-23.md)

## Purpose

This document locks the current operational interpretation of the
**vascular intervention emergency** workflow for PI RN / ImageTrend
review.

This is the timed vascular-emergency lane that matters for current PI
tracking. It is distinct from peripheral/extremity vascular injury
review.

It defines how this program should later reason about:

- trigger status
- timing clock
- the timed emergency metric
- acceptable evidence
- PI attribution

## Why This Doc Exists

The local source material contains two different vascular-related
lanes:

1. extremity/peripheral vascular trauma
2. vascular intervention / angioembolization emergency

For current PI RN workflow, the true tracked **vascular emergency** is
the second one:

- hemorrhage-control / angioembolization
- timed from request to arterial puncture

If the product combines these into one concept, it will create
confusion.

## Scope

This document applies only to:

- **vascular intervention / angioembolization emergency**

It does **not** define:

- peripheral/pulseless-extremity vascular injury review
- ortho/vascular overlap adjudication outside the angioembolization lane
- broader hemorrhage-management logic
- NTDS complication logic

Those will be handled elsewhere.

## Canonical Operational Rule

A case counts as a **vascular intervention emergency** when all of the
following are true:

- blood transfusion initiated
- repeated hypotension, operationally interpreted as
  **SBP 90 or less on two readings**
- angioembolizable lesion present

This is the current timed vascular-emergency lane for PI review.

## What This Is Not

The following do **not** count as the timed vascular emergency by
themselves:

- pulseless extremity
- limb ischemia
- fracture/dislocation with vascular compromise
- peripheral vascular trauma alone

Those are important, but they belong to a different review lane.

## Timing Metric

The timed metric is:

- **request to arterial puncture within 60 minutes**

This is the formal timed vascular-emergency standard that matters for
current PI review.

## Evidence the Reviewer Cares About

In actual review workflow, the important time points are:

- request time
- arterial puncture time
- procedure start / whether the patient was taken promptly

All of these matter to the reviewer, even though the primary formal
metric is request-to-puncture.

## Clock Start

The vascular emergency clock starts from:

- documented request / call / activation time for vascular intervention

Operational rule:

- if trauma/ESA fails to document the request/call time, that is a major
  accountability problem

Source note:

- local protocol text does not fully resolve which single Epic artifact
  must define the request time
- operationally, trauma/ESA documentation remains central because they
  are responsible for activation and coordination

## Timely Response Standard

The vascular intervention emergency is timely when:

- arterial puncture occurs within 60 minutes of the documented request

Reviewer-facing practical questions also include:

- was vascular called promptly
- was the patient taken promptly
- was the intervention process timely overall

## PI Attribution Rule

If the patient meets vascular intervention emergency criteria:

### Case A: request/call time is documented

If the vascular intervention pathway is not completed in a timely way,
PI review may attribute delay to the vascular/intervention lane as
appropriate.

### Case B: request/call time is missing

If the patient clearly met vascular intervention emergency criteria but
trauma/ESA never documented the request/call time:

- responsibility falls to **ESA**

Reason:

- trauma is the captain of the ship
- a timed emergency standard cannot be enforced cleanly if the start of
  the emergency clock was never documented

## Rarity

This is a **rare** pathway in current PI RN workflow.

Operational note from Sarah:

- in approximately one year of work, only one case clearly met this true
  vascular-emergency standard

Product implication:

- later implementation must be careful and explicit
- raw-chart example coverage may remain thin

## Distinction from Peripheral Vascular Trauma

The local source text also supports a separate extremity/peripheral
vascular injury lane, including:

- absent pulses
- ischemic limb
- fracture with poor arterial perfusion

Current decision:

- do **not** merge that lane into this document
- do **not** call that the timed vascular emergency

That should later be documented separately as a distinct accountability
lane.

## Relation to Orthopedic Overlap

Some cases, such as fracture/dislocation with vascular compromise, may
implicate:

- orthopedic emergency review
- peripheral/extremity vascular review

That overlap does **not** automatically make them timed vascular
intervention emergencies.

The timed vascular intervention lane requires the angioembolization /
hemorrhage-control pattern described above.

## Future Product Fields

Not for implementation yet, but this doc supports later structured
fields such as:

- `meets_vascular_intervention_emergency`
- `vascular_intervention_request_time`
- `vascular_intervention_puncture_time`
- `vascular_intervention_start_time`
- `vascular_intervention_timed_status`
- `vascular_intervention_attribution`

## Out of Scope

This doc does not yet define:

- exact source precedence for request-time capture across all Epic
  artifacts
- peripheral vascular injury accountability
- overlap precedence between orthopedic, vascular-trauma, and vascular
  intervention lanes
- renderer placement
- integration with NTDS

Those will be handled later.
