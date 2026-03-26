# Spinal Clearance and Spinal Injury Management Interpretation v1

**Status:** Authoritative protocol/accountability interpretation  
**Decision Date:** March 25, 2026  
**Depends On:** [REVIEW_ARCHITECTURE_V1_2026-03-23.md](./REVIEW_ARCHITECTURE_V1_2026-03-23.md)

## Purpose

This document locks the current operational interpretation of
**Spinal Clearance and Spinal Injury Management** for PI RN / ImageTrend
review.

It defines how this program should later reason about:

- spine-surgery timing when operative treatment is indicated
- the required spine-clearance order workflow
- regional clearance state for cervical versus thoracolumbar spine
- when neurosurgery must own regional clearance decisions
- when missing neurosurgery consultation becomes an accountability issue

## Highest-Value Accountability Items

Current highest-value issues in this lane are:

- **delay to spine surgery** when surgery is indicated
- missing or incorrect **spine-clearance order**
- missing or delayed **neurosurgery consult** when required

## Surgery Timing Rule

Current locked operational rule:

- spine surgery should occur within **36 hours of injury** when surgery
  is indicated

This lane uses **time of injury**, not ED arrival time, as the timing
anchor.

Operational note:

- transfer cases may already consume part of that 36-hour window before
  arrival to Deaconess
- if the Trauma H&P clearly documents injury occurring days earlier,
  that can establish obvious non-compliance even when transfer timing is
  incomplete in the local chart

## Spine Clearance Order Requirement

Current locked operational rule:

- **every trauma patient should have a spine-clearance order**

This is the core order-based accountability workflow in this lane.

The order is managed as separate yes/no states for two independent
regions:

- **cervical spine (`C-spine`)**
- **thoracolumbar spine (`TLS`)**

For this document, the only allowed order states per region are:

- `clear` = order value `Yes`
- `not clear` = order value `No`

Operational note:

- narrative phrases such as `TLS pending` do not create a third order
  state
- they should be interpreted as `not clear` while additional evaluation
  is still expected

If the order is missing:

- that is a PI issue

If the order is present but not updated to match the patient's actual
status during the admission:

- that is also a PI issue

Operational note:

- this is commonly blamed on the ESA APP / trauma physician team for the
  day when the order remains wrong

## Cervical and TLS Are Separate States

Current locked rule:

- cervical spine and thoracolumbar spine must be treated as separate
  clearance states

Examples:

- C-spine cleared, TLS pending
- C-spine not clear, TLS clear

The product should not collapse these into a single spine-clearance
status.

## Who Is Authoritative for Clearance

Current locked operational rule:

- trauma documentation can be accepted as authoritative for clearance
  unless there is a fracture / known injury in that spinal region and
  neurosurgery is on the case

If there is a known fracture or regional spine injury and neurosurgery is
consulted for that region:

- neurosurgery should control the clearance decision for that region

Operational ownership split:

- **neurosurgery** can be authoritative for the regional decision
- **ESA** remains responsible for making sure the spine-clearance order
  is actually placed and updated correctly

## Collar / Brace vs Clearance Status

Current locked operational rule:

- collar or brace presence by itself does not determine whether the
  spine is cleared

If neurosurgery says the spine is cleared and the order is updated to
clear:

- the spine is treated as cleared
- even if the patient continues wearing a collar for comfort or because
  of persistent pain complaints

However, if the patient must remain in a continuous brace or use a brace
when out of bed because of a fresh fracture, such as:

- cervical collar
- Jewett brace
- TLSO

then operationally the spine is not treated as fully cleared in the same
way.

## Order / Activity Conflict

Current locked operational rule:

- if the spine-clearance order remains `not clear` but the patient has
  activity orders, PT/OT, HOB elevation, or similar progression that
  assumes clearance, that is wrong and is a PI issue

This is one of the main order-maintenance failures in this lane.

## Neurosurgery Consultation Trigger in This Lane

Current locked operational rule:

- missing or delayed neurosurgery consult is an accountability issue
  when required spinal findings are present

For the neurologic-deficit pathway in this lane:

- **weakness must be present**
- weakness in at least **1 of 4 extremities** is the threshold signal
- other symptoms may still be clinically important, but weakness is the
  operational trigger for this consult-accountability pathway

## Trusted Sources

Current trusted source classes for this lane are:

- Trauma H&P
- neurosurgery consult
- progress notes
- imaging
- discharge summary

These sources are used to establish:

- injury presence and region
- time of injury
- surgery timing
- regional clearance state
- consult timing and ownership
- whether the order matched the actual care pathway

## Future Product Fields

Not for implementation yet, but this doc supports later structured
fields such as:

- `spine_surgery_indicated`
- `spine_injury_time`
- `spine_surgery_time`
- `spine_surgery_delay_gt_36h`
- `c_spine_clear_order_state`
- `tls_spine_clear_order_state`
- `spine_clear_order_present`
- `spine_clear_order_conflict_with_activity`
- `spine_region_nsgy_authoritative`
- `spine_nsgy_consult_required`
- `spine_nsgy_consult_delay`
- `spine_motor_weakness_present`

## Out of Scope

This doc does not yet define:

- exact transfer-timeline reconstruction rules across outside hospitals
- renderer placement
- brace-specific nursing workflows
- interaction with registrar-owned or NTDS event logic
