# Review Architecture v1

**Status:** Authoritative planning direction  
**Decision Date:** March 23, 2026  
**Depends On:** [TRAUMA_SUMMARY_V1_SPEC_2026-03-23.md](./TRAUMA_SUMMARY_V1_SPEC_2026-03-23.md)

## Purpose

This document defines the full review architecture so the product does
not drift into isolated feature work after the Trauma Summary anchor is
built.

The goal is to keep the system organized around the real trauma-review
workflow rather than around whichever extraction modules happen to
exist.

## Why This Doc Exists

During planning on March 23, 2026, it became clear that several review
lanes are related but must remain distinct:

1. the opening trauma story
2. the multidisciplinary clinical course
3. Deaconess/ImageTrend protocol and PI accountability
4. NTDS complication logic

If these are blended together, the output becomes confusing and the
build direction starts drifting again.

## The Four Review Layers

### Layer 1: Trauma Summary

Purpose:

- establish the opening trauma story
- anchor the case in the Trauma H&P / initial trauma evaluation

This layer answers:

- what happened
- what trauma thought initially
- what the primary survey showed
- what the initial trauma plan was

Examples:

- activation category
- MOI
- trauma H&P primary survey
- initial injuries
- initial trauma impression
- initial trauma plan

Current build status:

- active implementation slice (`summary.trauma_summary`)

### Layer 2: Specialty Course

Purpose:

- show what the important specialties thought and how their plan changed
  over time

This layer should follow an **anchor + delta** model:

- specialty consult note = specialty anchor
- specialty progress notes = specialty delta notes

Important rule:

- repeated copied-forward note content should be suppressed
- changing/current sections should be prioritized

Examples:

- PCCM `Currently` + current impression/plan
- neurosurgery non-op vs intervention vs sign-off
- ortho surgery / weight-bearing / brace / follow-up
- vascular decision-making when relevant
- hospitalist geriatric screening and medication/consult changes

### Layer 3: Protocol / Accountability

Purpose:

- support ImageTrend / Deaconess trauma PI review
- answer whether the expected care pathway and documentation occurred

This layer is **not** the same as NTDS complications.

Examples from ImageTrend critique workflow:

- neurosurgery emergency response timing
- orthopedic emergency response timing
- vascular emergency response timing
- Parkland / TBI DVT accountability
- delay to chemical DVT prophylaxis
- DVT none
- FAST performed / not performed / image availability / interpretation issues
- geriatric consult and hospitalist screening/documentation

Important rule:

- this layer tracks whether the right things happened and were
  documented, not just what diagnoses existed

### Layer 4: NTDS Complications

Purpose:

- support complication/event review under NTDS logic

This layer is separate because NTDS complications have their own rules,
including:

- POA exclusions
- event-specific criteria
- hospital-acquired timing requirements

Examples:

- delirium
- unplanned ICU admission
- unplanned intubation
- pressure ulcer
- AKI

Important rule:

- a valid ImageTrend / protocol PI may exist without an NTDS
  complication
- a clinical issue may matter to the reviewer even if NTDS excludes it
  as POA

## Ownership Split: PI RN vs Registrar

Not all review/accountability work belongs to the PI RN.

This ownership split must remain explicit in the product.

## Registrar-owned / registrar-primary items

Examples explicitly identified by Sarah:

- CAT I ETOH
- CAT I Trauma Flowsheet
- CAT I UDS
- delay in activation
- delay in decision to transfer from Deaconess
- delay in IV antibiotics > 60 min after arrival
- trauma surgeon response time
- ED Cat I GCS
- ED Cat I intake/output
- ED Cat I temperature delay
- ED Cat I vitals
- EMS scene or referring report missing
- inappropriate activation / overactivation / underactivation
- OR emergent case operational timing items
- some OSH transfer-delay reminder work
- medicine-admit reviewed by TMD (not PI RN-owned)

These may still be visible in the system, but they should not be
mistaken for the core PI RN review layer.

## PI RN-owned / PI RN-primary items

Examples explicitly identified by Sarah:

- neurosurgery emergency timing
- ortho emergency timing
- vascular emergency timing
- Parkland / TBI DVT accountability
- delay to chemical DVT prophylaxis
- DVT none
- FAST accountability
- geriatric consult / geriatric hospitalist documentation
- specialty consultation appropriateness for injuries/criteria
- specialty sign-off when it changes protocol accountability
- ImageTrend PI entry and loop-closure workflow

## Specialty Accountability Principles

These were clarified during March 23 planning:

1. A specialty matters not only because of its clinical plan, but because
   trauma must consult the correct specialty for the correct injuries and
   protocol triggers.
2. If emergency criteria are met and ESA does not document that the
   consult was called, the PI may belong to ESA because the specialty
   cannot respond to an emergency it was never clearly told about.
3. Neurosurgery, orthopedics, and vascular do not share identical
   emergency-timing logic.
4. Specialty sign-off can change protocol accountability, especially for
   DVT/TBI workflows.

## Specialty Prioritization

Sarah's current practical importance order is approximately:

1. Trauma
2. Neurosurgery
3. Orthopedics
4. Vascular
5. Pulmonary / Critical Care
6. Hospitalist / DCG
7. Palliative
8. ENT
9. OMFS
10. Plastics
11. Nephrology
12. Neurology
13. Cardiology
14. EP
15. Infectious Disease
16. Heme/Onc
17. Wound Care

This order should guide later implementation sequence, not necessarily
final display order.

## Note-Class Strategy

The product should treat note classes differently.

## Anchor notes

Examples:

- Trauma H&P
- specialty consult note

Use:

- structured extraction of the core opening evaluation

## Delta notes

Examples:

- trauma progress note
- PCCM progress note
- hospitalist progress note
- specialty progress note

Use:

- current-state / changed-state extraction only
- prioritize `CC`, `Subjective`, `Currently`, current `Impression`,
  current `Plan`, new procedures/events, and sign-off language

Avoid:

- copied-forward HPI/history
- copied labs
- copied imaging
- copied old vitals
- stale imported data from other encounters

This is the deterministic equivalent of Sarah's Epic workflow of hiding
copied text.

## Protocol and NTDS Interpretation Sequence

We will **not** jump directly from Trauma Summary into isolated
micro-features.

Before later implementation slices in protocol/accountability or NTDS
logic, we will intentionally go through:

1. Deaconess / ImageTrend-facing protocols and policy requirements
2. relevant NTDS complication/event logic

The purpose is to interpret the source rules first, compare them to
Sarah's real workflow, and only then decide what the product must
surface.

## Planned Interpretation Order

### Targeted protocol interpretation

1. neurosurgery emergency
2. orthopedic emergency
3. vascular emergency
4. geriatric trauma screening
5. Parkland / TBI DVT

First locked interpretation doc:

- [NEUROSURGERY_EMERGENCY_INTERPRETATION_V1_2026-03-23.md](./NEUROSURGERY_EMERGENCY_INTERPRETATION_V1_2026-03-23.md)
- [ORTHOPEDIC_EMERGENCY_INTERPRETATION_V1_2026-03-23.md](./ORTHOPEDIC_EMERGENCY_INTERPRETATION_V1_2026-03-23.md)
- [VASCULAR_INTERVENTION_EMERGENCY_INTERPRETATION_V1_2026-03-24.md](./VASCULAR_INTERVENTION_EMERGENCY_INTERPRETATION_V1_2026-03-24.md)
- [PARKLAND_TBI_DVT_INTERPRETATION_V1_2026-03-24.md](./PARKLAND_TBI_DVT_INTERPRETATION_V1_2026-03-24.md)

### Targeted NTDS interpretation

High-value overlap topics include:

- delirium
- unplanned ICU admission
- unplanned intubation
- pressure ulcer / pressure injury
- POA exclusion behavior where relevant

## Next Planning Documents

After Trauma Summary merge, the next major planning work should be:

1. protocol interpretation notes
2. NTDS interpretation notes
3. `SPECIALTY_COURSE_AND_ACCOUNTABILITY_STRATEGY_V1`

Only after those are written should later implementation slices start.
