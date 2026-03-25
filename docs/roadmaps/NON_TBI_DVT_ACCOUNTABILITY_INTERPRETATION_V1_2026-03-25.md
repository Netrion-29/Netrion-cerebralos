# Non-TBI DVT Accountability Interpretation v1

**Status:** Authoritative protocol/accountability interpretation  
**Decision Date:** March 25, 2026  
**Depends On:** [REVIEW_ARCHITECTURE_V1_2026-03-23.md](./REVIEW_ARCHITECTURE_V1_2026-03-23.md)

## Purpose

This document locks the current operational interpretation of
**non-TBI DVT prophylaxis accountability** for PI RN / ImageTrend
review.

It defines how this program should later reason about:

- when chemoprophylaxis is expected
- what valid hold reasons exist
- when delay is acceptable
- what `DVT NONE` means
- who owns the delay when it is not justified

This lane is intentionally separate from:

- [PARKLAND_TBI_DVT_INTERPRETATION_V1_2026-03-24.md](./PARKLAND_TBI_DVT_INTERPRETATION_V1_2026-03-24.md)

## Canonical Operational Rule

For non-TBI trauma patients, the default rule is:

- **chemical DVT prophylaxis is expected within 24 hours of arrival**
- unless there is a valid documented reason not to start it

Mechanical prophylaxis alone does **not** satisfy this metric.

## Core Review Questions

For non-TBI DVT accountability, the reviewer is asking:

1. was chemical prophylaxis started within 24 hours of arrival?
2. if not, was there a valid documented reason?
3. if not, who owned the ongoing delay?

## Valid Hold / Delay Reasons

Current accepted operational hold reasons include:

- OR / surgery
- procedure hold
- active bleeding
- significant hemoglobin drop without explicit active bleeding, such as
  approximately 3-4 gram drop in 24 hours
- thrombocytopenia / platelet issue
- consultant-directed hold
- epidural / ESP block or similar procedure-related hold

Operational note:

- a documented hold reason is part of the accountability review
- it is not an automatic permanent exclusion

## Restart Expectation After Surgery / Procedure

Current locked rule:

- if DVT prophylaxis is held for surgery or procedure, it should be
  restarted within **24 hours post-op** when otherwise appropriate

This is the default operational expectation for review.

## Ambulatory / BMAT Exclusion

Current locked rule:

- ambulatory status alone is enough for exclusion in this lane

This means the reviewer does not need an additional special trauma
attending note if the patient is clearly ambulatory under the workflow
being used.

## Length-of-Stay Rule

Current locked rule:

- if the patient was in the hospital for **less than 24 hours**, they
  are excluded from delay review

Important operational note:

- the reviewer needs to be able to specifically tell that the patient
  was present for less than 24 hours

## DVT NONE Definition

Current locked operational meaning:

- `DVT NONE` means no chemical prophylaxis was ever given during an
  admission where it should have been considered

This is distinct from:

- temporary appropriate hold
- short admission
- ambulatory exclusion

## Ownership Rule

Current locked rule:

- if a consultant says hold but never re-addresses it, the ongoing delay
  belongs to **ESA**

Reason:

- ESA remains the captain of the ship
- they own the ongoing trauma-management pathway
- they cannot indefinitely attribute delay to a consultant once the case
  continues moving without reassessment

## Chemical vs Mechanical

Operational rule:

- only chemical prophylaxis counts toward the 24-hour metric
- mechanical prophylaxis can be documented, but it does not satisfy the
  chemical timing expectation by itself

Common examples in chart language may include:

- `Mechanical yes, pharmacologic no`
- `SCDs only`
- `hold for OR`
- `hold for procedure`

## Future Product Fields

Not for implementation yet, but this doc supports later structured
fields such as:

- `non_tbi_dvt_expected`
- `first_chem_dvt_time`
- `non_tbi_dvt_delay_24h`
- `non_tbi_dvt_hold_reason`
- `non_tbi_dvt_hold_reason_detail`
- `non_tbi_dvt_excluded_short_stay`
- `non_tbi_dvt_excluded_ambulatory`
- `dvt_none_non_tbi`
- `non_tbi_dvt_attribution`

## Out of Scope

This doc does not yet define:

- exact source precedence across all order, MAR, and note artifacts
- renderer placement
- detailed consultant-specific restart rules beyond the locked defaults
- interaction with NTDS logic

Those will be handled later.
