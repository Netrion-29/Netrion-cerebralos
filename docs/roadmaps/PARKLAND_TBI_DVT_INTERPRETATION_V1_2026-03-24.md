# Parkland / TBI DVT Interpretation v1

**Status:** Authoritative protocol/accountability interpretation  
**Decision Date:** March 24, 2026  
**Depends On:** [REVIEW_ARCHITECTURE_V1_2026-03-23.md](./REVIEW_ARCHITECTURE_V1_2026-03-23.md)

## Purpose

This document locks the current operational interpretation of the
**Parkland / TBI DVT prophylaxis** workflow for PI RN / ImageTrend
review.

It defines how this program should later reason about:

- whether a TBI patient entered the Parkland pathway
- whether chemoprophylaxis was expected
- whether delay/absence was justified
- who owned the delay when it was not justified

This is not a generic DVT prophylaxis summary. It is a trauma PI /
accountability interpretation for TBI patients.

## Why This Doc Exists

The formal protocol contains a clear Parkland decision flow, but real
charts often do **not** explicitly label patients as:

- low risk
- moderate risk
- high risk

Instead, the chart more often documents the operational pieces:

- Lovenox on hold
- repeat head CT stable/worse
- neurosurgery recommendation
- drain present
- procedure/surgery hold
- later sign-off

This document locks the practical review rule so later implementation
does not depend on an unrealistically explicit chart label.

## Scope

This document applies only to:

- **TBI / intracranial-hemorrhage DVT prophylaxis accountability**

It does **not** define:

- non-TBI DVT delay logic
- DVT/PE treatment decisions
- NTDS complication logic
- detailed anti-platelet restart logic

Those will be handled separately.

## Canonical Operational Question

For a TBI patient, the reviewer is asking:

1. do they have a TBI / intracranial hemorrhage?
2. should chemoprophylaxis have been started within the expected
   Parkland window?
3. if not, is there a valid documented reason?
4. if not, who owned the delay?

This is the core operational review rule.

## Parkland Governs TBI Timing

Current locked rule:

- if the patient has intracranial hemorrhage / TBI in scope for
  Parkland, **Parkland governs**
- the ordinary 24-hour trauma DVT rule does not govern by itself

Important note:

- explicit chart wording of `low risk`, `moderate risk`, or `high risk`
  is helpful but not required for operational review
- the reviewer can follow the flow based on the documented pathway even
  when those labels are absent

## What Matters in Real Review

The reviewer needs these facts together:

- TBI / intracranial hemorrhage present or not
- first chemoprophylaxis time
- repeat head CT timing
- repeat head CT stability or worsening
- craniotomy present or not
- ICP monitor present or not
- drain present or not
- surgery/procedure hold
- platelet count concerns
- BMAT / ambulatory status
- length of admission / whether the patient was even present long enough
  to judge the window
- neurosurgery still active vs signed off

## Key Operational Branches

### 1. Tiny isolated SAH with GCS 15

Current operational rule:

- treat this as the 24-hour Parkland branch if otherwise appropriate

This is the low-risk practical pathway.

## 2. Moderate-risk pathway

Examples from the Parkland flow include:

- SDH > 8 mm
- EDH > 8 mm
- contusion or IVH > 2 cm
- multiple contusions per lobe

Operationally, the important review question is:

- was the repeat head CT done on the expected timeline?
- if stable, was chemoprophylaxis then started on the expected timeline?

## 3. High-risk pathway

High-risk operational factors include:

- craniotomy
- ICP monitor
- worsening imaging / escalation out of the moderate pathway

Operationally, this is the branch where:

- chemoprophylaxis is delayed until the relevant conditions are met

## Drains Rule

Current locked rule:

- if neurosurgery places a drain, ESA will not order chemoprophylaxis
  until that drain is removed

Operational interpretation:

- drain present = valid hold reason unless there is an explicit
  documented override

## Procedure / Surgery Hold Rule

Procedure-related hold reasons may be valid.

Examples explicitly identified in workflow discussion:

- OR / surgery
- ESP block placement
- kyphoplasty

Operational interpretation:

- if a documented surgery/procedure explains why chemoprophylaxis was
  not started in the expected window, that can be a valid delay reason

## Platelet Rule

Platelet count matters in review.

Operational interpretation:

- thrombocytopenia / platelet-related concerns may be part of the
  documented reason for holding prophylaxis
- this must be treated as a reason-to-review, not blindly inferred

## BMAT / Ambulatory Exclusion Rule

Current locked rule:

- ambulatory status alone can be enough for exclusion

Product implication:

- later implementation should not require additional trauma-attending
  prose if the patient is clearly ambulatory / BMAT 4 under the
  operational rule used by review

## Length-of-Stay Rule

Another core review question is:

- was the patient even present long enough for the window to mature?

Operational interpretation:

- short admission can be a valid reason that the expected chemoprophylaxis
  window was never actually reached

## Neurosurgery Sign-Off Rule

This is a major operational accountability pivot.

Current locked rule:

- once neurosurgery signs off, ESA cannot keep documenting neurosurgery
  as the reason for continued delay

Operational implication:

- sign-off changes ownership
- after sign-off, ESA owns the next decision path unless some other
  documented reason exists

## If NSGY Says Hold but Never Re-addresses It

Current locked rule:

- if neurosurgery initially says hold and the delay continues without
  appropriate re-addressing, blame shifts to **ESA**

Reason:

- ESA is responsible for ongoing trauma-management ownership
- they cannot continue deferring indefinitely to a service that is no
  longer actively directing the case

## Real Chart Pattern

The current repo shows practical wording such as:

- `Lovenox on hold per NSGY`
- `Lovenox on hold given SDH`
- `DVT prophylaxis on hold`
- `mechanical yes, pharmacologic no`
- `repeat head CT stable`
- later neurosurgery sign-off language

Operational note:

- these practical phrases are often more important in review than
  explicit `low/moderate/high risk` labels

## Separate Accountability Lanes

Current locked rule:

- TBI/neuro DVT accountability must remain separate from non-TBI DVT
  accountability

Later product/accountability lanes should remain distinct, e.g.:

- `delay_tbi_dvt`
- `delay_non_tbi_dvt`
- `dvt_none_tbi`
- `dvt_none_non_tbi`

This matches real PI review workflow better than a single generic DVT
delay bucket.

## Future Product Fields

Not for implementation yet, but this doc supports later structured
fields such as:

- `has_tbi_dvt_pathway`
- `parkland_branch`
- `first_chem_dvt_time`
- `repeat_head_ct_time`
- `repeat_head_ct_stability`
- `has_neurosurgical_drain`
- `has_hold_reason`
- `hold_reason_detail`
- `nsgy_signed_off`
- `tbi_dvt_delay_status`
- `tbi_dvt_delay_attribution`

## Out of Scope

This doc does not yet define:

- exact structured mapping from every Parkland node to every chart form
- final source precedence for conflicting order/note/imaging timing
- anti-platelet restart accountability
- renderer placement
- how this interacts with NTDS

Those will be handled later.
