# Geriatric Trauma Screening Interpretation v1

**Status:** Authoritative protocol/accountability interpretation  
**Decision Date:** March 25, 2026  
**Depends On:** [REVIEW_ARCHITECTURE_V1_2026-03-23.md](./REVIEW_ARCHITECTURE_V1_2026-03-23.md)

## Purpose

This document locks the current operational interpretation of the
**geriatric trauma screening** workflow for PI RN / ImageTrend review.

It defines how this program should later reason about:

- guideline trigger status
- whether the geriatric screen was actually done
- what counts as compliant vs incomplete vs missing
- what supporting evidence is acceptable

This is not a generic geriatric-medicine note summary. It is a trauma
PI / accountability interpretation.

## Why This Doc Exists

The formal geriatric trauma guideline and the actual hospitalist/DCG
screening workflow are related, but they are not the same thing.

The guideline defines **who should enter the workflow**.
The hospitalist/DCG note defines whether the **screening/accountability
work actually happened**.

If these are collapsed into one concept, the product will blur trigger
logic and compliance logic.

## Scope

This document applies only to:

- **geriatric trauma screening accountability**

It does **not** define:

- NTDS delirium logic
- general hospitalist note quality
- non-geriatric hospitalist consult logic
- downstream outpatient geriatrics follow-up tracking

Those will be handled elsewhere.

## Canonical Operational Split

The geriatric lane has two separate questions:

### 1. Was the guideline triggered?

The formal protocol is triggered when the patient meets:

- age `>= 65`
- qualifying injury
- qualifying medical vulnerability

This is the **guideline trigger** question.

### 2. Was the geriatric screen done adequately?

This is the **accountability / compliance** question.

For PI review, this is the main practical question once the guideline is
triggered.

## Where Compliance Usually Lives

In the current raw charts, compliance usually appears in:

- `DCG Medical Management Consult Note`
- hospitalist/DCG geriatric-trauma template language

Common recurring structure includes:

- delirium
- depression
- dementia / cognition
- advanced care planning
- code status

Operational note:

- in the current sample, these notes are usually either mostly done or
  mostly not done
- there is not much true gray area in routine review

## Core Compliance Domains

A geriatric trauma screen counts as compliant when the hospitalist/DCG
documentation addresses the core domains:

- **code status**
- **delirium**
- **dementia / cognition**
- **depression**

These are the key operational review domains.

## What Counts as Compliant

The screen counts as **compliant** if the core domains are addressed,
even if some supporting details come from other sources or the patient
could not fully complete the formal bedside tools.

### Delirium

Counts as addressed if the hospitalist/DCG note:

- states delirium is present
- states delirium is not present
- states the patient is at risk for delirium
- states delirium could not be fully assessed but still addresses the
  domain

### Dementia / Cognition

Counts as addressed if the hospitalist/DCG note:

- documents current dementia/cognitive findings
- documents history of dementia
- documents cognitive concern with follow-up recommendation
- uses or references 6CIT / SLP cognitive screening support
- states the domain was addressed even if limited by patient condition

Important operational rule:

- if the patient already came in with dementia, acknowledging that
  history still counts

### Depression

Counts as addressed if the hospitalist/DCG note:

- discusses depression directly
- references the depression-screen domain
- marks the domain as unable to assess

Important operational rule:

- the hospitalist does **not** have to explicitly mention `PHQ-9` by
  name if the depression domain is addressed

### Code Status

Counts as addressed if the note documents:

- code status directly
- or advanced care planning / code-status decision in a way that makes
  the current status clear

## Nursing and SLP Support

Supporting evidence from other services can still satisfy parts of the
screening workflow.

### Nursing

Operationally acceptable support includes:

- nursing PHQ-9
- nursing delirium assessments

Important rule:

- the hospitalist/DCG note still needs to address the relevant domain
- but it does not have to repeat every nursing detail

### SLP

Operationally acceptable support includes:

- SLP/SLUMS or other cognitive screening ordered through the geriatric
  workflow

Important rule:

- if hospitalist orders speech to do the cognitive screening because
  they do not want to perform 6CIT themselves, that still counts as long
  as the cognition/dementia domain is addressed

## Unable-to-Assess Rule

Current locked rule:

- `unable to assess` still counts if the note meaningfully addresses the
  domain

This applies to:

- delirium
- depression
- dementia/cognition

The key review question is whether the domain was addressed, not
whether every bedside tool produced a numeric result.

## What Counts as Non-Compliant

Operationally, this should be treated as:

- **geriatric screen missing/incomplete**

The screen is non-compliant when the hospitalist/DCG documentation fails
to address the core domains, especially:

- no code status
- no delirium mention
- no dementia/cognition mention
- no depression-domain mention

## Practical Label

The working failure label in this lane is:

- **geriatric screen missing/incomplete**

This matches current review workflow better than over-fragmenting the
problem into many tiny sub-failures.

## Important Distinction from NTDS

This lane must remain separate from NTDS event logic.

Examples:

- a note can be compliant because it addresses delirium, even if the
  patient does not meet NTDS delirium
- history of dementia can satisfy the cognition/dementia domain without
  meaning the patient acquired a hospital complication

Product implication:

- do not collapse geriatric-screen compliance into NTDS delirium or
  dementia logic

## Future Product Fields

Not for implementation yet, but this doc supports later structured
fields such as:

- `geriatric_guideline_triggered`
- `geriatric_screen_present`
- `geriatric_screen_status`
- `code_status_addressed`
- `delirium_addressed`
- `depression_addressed`
- `dementia_cognition_addressed`
- `phq9_support_present`
- `slp_cognitive_support_present`

## Out of Scope

This doc does not yet define:

- exact field-by-field scoring for every bedside screening tool
- exact source precedence between nursing/DCG/SLP when they conflict
- renderer placement
- how this intersects with NTDS event adjudication

Those will be handled later.
