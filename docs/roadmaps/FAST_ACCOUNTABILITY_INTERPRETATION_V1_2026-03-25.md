# FAST Accountability Interpretation v1

**Status:** Authoritative protocol/accountability interpretation  
**Decision Date:** March 25, 2026  
**Depends On:** [REVIEW_ARCHITECTURE_V1_2026-03-23.md](./REVIEW_ARCHITECTURE_V1_2026-03-23.md)

## Purpose

This document locks the current operational interpretation of
**FAST accountability** for PI RN / ImageTrend review.

It defines how this program should later reason about:

- whether FAST was performed
- whether FAST was not performed
- whether FAST was not indicated
- what result was documented when FAST was performed

This interpretation is intentionally scoped to what is visible in the
raw `.txt` pipeline. It does not try to automate Epic image-archive
review.

## Why This Doc Exists

Raw trauma notes use several common FAST forms:

- `FAST: No`
- `FAST: Not indicated`
- `FAST: No - taken to CT imaging`
- `FAST: Yes ... negative`
- `FAST: Yes ... positive`

These are not the same operationally, and they should not all be
flattened into one status.

## Scope

This document applies only to:

- **FAST performed/documented accountability**

It does **not** define:

- Epic image-availability verification
- FAST image archive review
- FAST interpretation quality / misread adjudication beyond what the
  Trauma H&P explicitly documents
- broader abdominal trauma logic

Those are handled manually or in later workflow.

## Canonical Operational Questions

For FAST review, the practical questions are:

1. was FAST done?
2. if yes, did the Trauma H&P document positive vs negative?
3. if not done, was it not indicated / appropriately bypassed?

That is the useful operational layer for the product.

## FAST Status Categories

Current locked operational categories:

- `performed`
- `not_performed`
- `not_indicated`
- `unclear`

## What Counts as Performed

FAST counts as **performed** when the Trauma H&P / Primary Survey
documents a FAST exam with a result.

Examples:

- `FAST: Yes ... negative`
- `FAST: Yes ... positive`

When FAST is performed, the product should later try to carry:

- FAST performed = yes
- documented result = positive / negative / unclear

## What Counts as Not Performed

FAST counts as **not performed** when the Trauma H&P states:

- `FAST: No`

Current locked interpretation:

- `FAST: No` means FAST was **not done**

## What Counts as Not Indicated

FAST counts as **not indicated** when the Trauma H&P states:

- `FAST: Not indicated`

Current locked interpretation:

- this is acceptable/compliant when the case did not require FAST

## CT-Path Variant

Current locked interpretation:

- `FAST: No - taken to CT imaging` is acceptable as a **not-performed /
  CT-path** case

Operationally:

- it is not treated as automatic FAST failure
- it should be interpreted as FAST not performed because the patient was
  taken down a CT-based pathway instead

## What the Product Should Track

The product should stay simple in this lane.

Useful later structured fields would be:

- `fast_status`
  - performed
  - not_performed
  - not_indicated
  - unclear
- `fast_result`
  - positive
  - negative
  - unclear
  - null

## What Stays Out of Scope

FAST image availability is **not** available in the raw `.txt` corpus
and should not be forced into this extraction lane.

Current locked rule:

- image availability / archive verification remains a manual Epic-side
  review task

Reason:

- the user can verify that quickly in Epic
- requiring it in the raw-text workflow would create more friction than
  value

## Important Distinction

FAST performed/documented review and FAST image-availability review are
related, but they are not the same thing.

Current decision:

- keep FAST performed/result in the extracted protocol/accountability
  lane
- keep image availability outside the raw-text automation boundary

## Future Product Fields

Not for implementation yet, but this doc supports later structured
fields such as:

- `fast_status`
- `fast_result`
- `fast_raw_text`

## Out of Scope

This doc does not yet define:

- exact handling of every rare textual FAST variant
- image-availability verification
- FAST misread adjudication
- renderer placement
- interaction with NTDS

Those will be handled later.
