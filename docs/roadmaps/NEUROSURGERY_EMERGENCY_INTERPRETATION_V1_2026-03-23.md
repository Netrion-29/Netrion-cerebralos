# Neurosurgery Emergency Interpretation v1

**Status:** Authoritative protocol/accountability interpretation  
**Decision Date:** March 23, 2026  
**Depends On:** [REVIEW_ARCHITECTURE_V1_2026-03-23.md](./REVIEW_ARCHITECTURE_V1_2026-03-23.md)

## Purpose

This document locks the March 23, 2026 operational interpretation of
the **neurosurgery emergency** workflow for PI RN / ImageTrend review.

It is not a generic clinical reference. It defines how this program
should later reason about:

- trigger status
- timing clock
- acceptable response evidence
- PI attribution

This interpretation is based on:

- local protocol source collection
- Sarah's real review workflow
- current Deaconess trauma PI/accountability practice

## Why This Doc Exists

The written protocol language, neurosurgical preferences, and
day-to-day PI review practice are not perfectly identical.

If the product tries to infer this logic later from notes alone, it
will drift. This document locks the operational review rule first.

## Scope

This document applies only to:

- **neurosurgery emergency accountability**

It does **not** define:

- broader TBI management
- Parkland / DVT timing
- neurosurgery sign-off logic
- NTDS complication logic

Those will be documented separately.

## Canonical Operational Rule

A case counts as a **neurosurgery emergency** when either the
intracranial pathway or the spinal-cord pathway is met.

### 1. Intracranial pathway

All of the following must be true:

- trauma-context case
- **GCS <= 12 at Deaconess**
- the GCS used is the **Trauma H&P GCS**
- qualifying traumatic intracranial pathology is present on imaging

Acceptable qualifying intracranial findings include:

- subdural hematoma (SDH)
- epidural hematoma (EDH)
- intraparenchymal hemorrhage (IPH)
- intraventricular hemorrhage (IVH)
- other traumatic intracranial findings treated operationally as a
  neurosurgical emergency

Important note:

- OSH imaging can establish the lesion
- but the emergency still depends on the **Deaconess Trauma H&P GCS**

### 2. Spinal-cord pathway

A case also counts as a **neurosurgery emergency** when there is:

- documented neurologic deficit suggesting potential spinal cord injury

Acceptable deficit examples:

- weakness
- paralysis
- cannot move extremities
- bowel/bladder dysfunction when documented in the context of possible
  spinal cord injury

Important rule:

- numbness alone does **not** count
- tingling alone does **not** count
- there must be weakness-based deficit evidence

Important exclusion:

- if paralysis/weakness is explained by paralytic medication, that does
  not count as valid trigger evidence by itself

Important resolution rule:

- if MRI later excludes cord injury, the emergency can be excluded

## Explicit Exclusions

The following do **not** count as neurosurgery emergency triggers in
current PI RN operational review:

- isolated subarachnoid hemorrhage (SAH)
- contusion
- numbness/tingling without weakness
- low GCS with clean head CT
- apparent weakness explained by paralytic

## Contusion Clarification

This was explicitly clarified in March 2026 with the neurosurgical
liaison and is now locked for operational review.

Current PI RN tracking rule:

- **contusions do not count as neurosurgery emergencies**

Reason captured from workflow discussion:

- contusions may evolve over 72 hours and are not treated as a
  30-minute neurosurgical emergency target for PI review

Product implication:

- later implementation must follow this locked operational rule, even if
  older broad protocol wording appears to include contusion-related
  language

## SAH Clarification

Current PI RN tracking rule:

- **isolated SAH does not count**

Operational note:

- user indicated neurosurgery does not treat isolated SAH as a true
  30-minute emergency target in this workflow

Edge-case note:

- diffuse/mixed SAH patterns may still need manual reviewer judgment,
  but the default operational rule is **no isolated SAH**

## Timing Clock

The neurosurgery emergency response clock starts from:

- **ESA / Trauma H&P documented contact time only**

This means the authoritative start time must be documented in the
Trauma H&P by ESA/trauma.

The following do **not** start the clock by themselves:

- consult order time
- nursing note time
- trauma progress note time
- later backfilled timing from non-H&P sources

## Acceptable Neurosurgery Response Evidence

Only **neurosurgery-authored documentation** counts as response
evidence.

Timely response may be credited in either of these two ways:

1. neurosurgery note timestamp is within 30 minutes of the ESA
   documented call time
2. neurosurgery note is later, but explicitly documents an earlier
   response/contact time that occurred within 30 minutes

Examples of acceptable explicit-response wording:

- "Spoke with Dr. X at 1900"
- "Was sent txt ... at 12:53"
- similar explicit documented communication time in the neurosurgery
  note

Important rule:

- trauma note text describing what neurosurgery said does **not** count
  as neurosurgery response evidence by itself

## What Does Not Count as Response Evidence

These do **not** count as neurosurgery response evidence by themselves:

- trauma note text summarizing the neurosurgery recommendation
- trauma plan text saying neurosurgery was aware
- consult order timestamp alone
- nursing note alone
- trauma team recollection without neurosurgery documentation

Neurosurgery must document its own response.

## PI Attribution Rule

If a patient meets neurosurgery emergency criteria:

### Case A: ESA call time is documented in Trauma H&P

If neurosurgery does not document timely response, enter:

- **Delay in Neurosurgery Response Time**

Attribution:

- **neurosurgery**

### Case B: ESA call time is missing in Trauma H&P

If the patient met neurosurgery emergency criteria but ESA never
documented when they called, enter the same PI label:

- **Delay in Neurosurgery Response Time**

Attribution:

- **ESA**

Reason:

- the specialty cannot be held to a timed emergency-response standard if
  ESA never documented the start of the emergency consult clock

## Evidence Prioritization for Later Product Work

When later implementation happens, evidence should be prioritized in
this order:

1. Trauma H&P GCS at Deaconess
2. Trauma H&P documented neurosurgery contact/call time
3. imaging establishing qualifying lesion
4. neurosurgery-authored note timestamp
5. explicit neurosurgery-documented contact/response time inside the
   neurosurgery note

## Future Product Fields

Not for implementation yet, but this doc supports later structured
fields such as:

- `meets_neurosurg_emergency`
- `neurosurg_emergency_basis`
- `esa_neurosurg_call_time`
- `neurosurg_response_note_time`
- `neurosurg_response_documented_time`
- `neurosurg_response_status`
- `neurosurg_response_attribution`

## Out of Scope

This doc does not yet define:

- exact source hierarchy for mixed/missing imaging evidence
- edge cases involving diffuse/mixed hemorrhage patterns beyond the
  default operational rule
- how to render this in casefile output
- how to integrate this with Parkland / DVT logic
- how to integrate this with NTDS complication logic

Those will be handled in later documents.
