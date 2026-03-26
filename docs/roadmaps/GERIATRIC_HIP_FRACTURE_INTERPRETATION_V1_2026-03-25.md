# Geriatric Hip Fracture Interpretation v1

**Status:** Authoritative protocol/accountability interpretation  
**Decision Date:** March 25, 2026  
**Depends On:** [REVIEW_ARCHITECTURE_V1_2026-03-23.md](./REVIEW_ARCHITECTURE_V1_2026-03-23.md)

## Purpose

This document locks the current operational interpretation of the
**Geriatric Hip Fracture Guideline** for PI RN / ImageTrend review.

It defines how this program should later reason about:

- which fractures qualify
- what starts the timing clock
- when surgical timing becomes a PI problem
- what delay reasons may be appropriate versus inappropriate
- which service owns the delay

## Qualifying Fractures

This lane follows the protocol text exactly.

Qualifying fracture types are:

- proximal femur fracture
- trochanteric fracture
- intertrochanteric fracture

The patient must also meet the protocol age criterion:

- age **65 years or older**

## Clock Start

Current locked operational rule:

- the surgical-timing clock starts at **ED arrival time**

This interpretation does not use imaging time, consult time, or
admission-order time as the primary clock start.

For this lane, **ED arrival time** means:

- the Deaconess ED arrival timestamp tied to the encounter that leads to
  the qualifying admission / operation

Transfer note:

- for transfer-in patients, this clock starts at **arrival to
  Deaconess**, not at outside-hospital arrival time

## What Counts as the Real Timing Problem

The protocol contains both:

- surgery recommended within **24 hours** of arrival
- surgery should not be delayed beyond **48 hours** of arrival if the
  patient is an acceptable surgical candidate

Current locked operational rule:

- surgery occurring after **48 hours** is the PI problem in this lane

If surgery occurs after 24 hours but before 48 hours:

- that is treated as a normal surgery timing outcome for this lane
- it is not the primary PI failure threshold

## Appropriate vs Inappropriate Delay

A delay beyond 48 hours still needs to be noted.

Current locked operational rule:

- a delay can still be documented as **appropriate** or
  **inappropriate** in ImageTrend-style review
- if the delay is clinically justified, the case story should explain
  why it was appropriate
- it is still a delay and should still be acknowledged as such

## Acceptable Delay Reasons

Current accepted reasons that may make a >48-hour delay
**appropriate** include:

- medical instability
- anticoagulation reversal
- cardiac clearance / optimization
- patient or family decision-making delay
- transfer-related issues

Current locked operational rule:

- **OR availability is not an acceptable delay reason**
- the patient should be able to reach the OR within 48 hours

## Ownership Rule

Current locked rule:

- the delay belongs to **orthopedics**

This is the specialty-accountability lane for this protocol.

Operational note:

- even when orthopedics owns the delay, the trauma providers present
  when the PI occurred should still be noted in the case story

## Additional Orthopedic Protocol Requirements

Current locked operational requirements also include:

- **TXA:** `1 g` pre-operatively when the patient is treated with
  arthroplasty, unless contraindicated
- **Vitamin D:** `50,000 IU` daily for 3 days, followed by `5,000 IU`
  daily for 3 months

Operational note:

- the vitamin D course needs to continue at discharge
- these requirements remain orthopedic-accountability items in this lane

## Non-Operative Cases

Current operational rule:

- if the case is managed non-operatively, it is treated as non-operative
- the surgical-delay metric does not drive the review in the same way

## Trusted Sources

Current trusted source classes for this lane are:

- consult notes
- procedure / operative notes
- imaging
- progress notes

These sources are used to establish:

- qualifying fracture type
- operative timing
- delay reason
- whether the delay appears appropriate or inappropriate

Current operative-timing anchor for this lane:

- use the timestamp of the qualifying hip-fracture operation from the
  procedure / operative documentation
- when a specific procedure start time is explicitly documented, that is
  the preferred operative time
- otherwise, use the operative note timestamp as the practical fallback

## Future Product Fields

Not for implementation yet, but this doc supports later structured
fields such as:

- `geriatric_hip_fracture_triggered`
- `geriatric_hip_fracture_type`
- `geriatric_hip_fracture_arrival_time`
- `geriatric_hip_fracture_or_time`
- `geriatric_hip_fracture_delay_gt_48h`
- `geriatric_hip_fracture_delay_reason`
- `geriatric_hip_fracture_delay_appropriateness`
- `geriatric_hip_fracture_attribution`
- `geriatric_hip_fracture_txa_required`
- `geriatric_hip_fracture_txa_given_preop`
- `geriatric_hip_fracture_vitamin_d_started`
- `geriatric_hip_fracture_vitamin_d_discharge_continuation`

## Out of Scope

This doc does not yet define:

- exact source precedence between all note classes when timestamps
  conflict
- renderer placement
- how non-operative hip-fracture cases should later summarize in the UI
- interaction with registrar-owned timing or NTDS event logic
