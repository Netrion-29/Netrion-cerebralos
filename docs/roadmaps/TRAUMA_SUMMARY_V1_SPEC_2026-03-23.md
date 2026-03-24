# Trauma Summary v1 Spec

**Status:** Authoritative product decision  
**Decision Date:** March 23, 2026

## Purpose

The product is a deterministic, clinically trustworthy **Trauma
Summary** that helps the PI RN audit the full trauma continuum of care.

This is not just "more casefile sections." This is the review worksheet
the PI RN actually needs.

## March 23 Decision

We are:

- **not** restarting the repo from zero
- **not** relying on endless small fixes to make the current output
  eventually become the right thing
- **yes** building a new versioned Trauma Summary direction on top of
  the current deterministic pipeline

## Product Truths

### 1. Every patient in scope is an activated trauma patient

Even when medicine admits, the patient remains part of the trauma
continuum of care for PI review.

### 2. The H&P is the anchor

In newer raw `.txt` files:

1. patient info
2. ADT timeline
3. first real note = anchor note

That anchor is often the Trauma H&P. If medicine admits, a medical H&P
may exist too, but it does not replace the trauma initial evaluation.

### 3. The green card is a workflow model

The green card matters because it reflects the real review workflow.
Old green-card code is **not** authoritative and should not be revived
just because it exists.

## Workflow Truths Captured On March 23, 2026

These workflow answers were explicitly provided by Sarah and are now
part of the product direction.

### 1. First 60-second review priorities

When first opening a trauma chart for review, the immediate priorities
are:

- age
- MOI
- blood thinner use
- injuries
- consultants

These should strongly influence what becomes visible early in the final
product.

### 2. Green-card completeness expectation

Operationally, the whole green card is considered mandatory. In
practice, meaningful review depends first on establishing:

- injuries
- clinical course

This means the product should not treat early injury/course fields as
optional decoration. They are the foundation for the rest of the review.

### 3. Medicine-admit trauma activations

In a medicine-admit trauma activation, the patient is still followed as
a trauma patient with no meaningful reduction in trauma-review scope.

This confirms:

- trauma activation context remains mandatory
- trauma initial evaluation remains mandatory
- medicine ownership is additive context, not a replacement frame

### 4. Most common PI categories

The most common real-world PI categories reported so far are:

- delirium
- unplanned ICU admission
- unplanned intubation
- DVT prophylaxis-related PI
- geriatric-related PI

These categories should influence downstream prioritization after the
Trauma Summary anchor is built.

### 5. Final output style

The desired final product style is:

- a **hybrid**
- narrative case review
- with structured panels
- and some dashboard-like patient tracking utility

This means the long-term design should not become either:

- a pure digital green card only
- or a pure narrative wall of text

It should combine:

- narrative flow for the clinical story
- structured panels for rapid auditing

## Trauma Summary v1 Must Answer

1. Who is this patient and where did they come from?
2. What was the trauma activation and why?
3. What did the trauma initial evaluation say?
4. What injuries and emergencies were present at the start?
5. What immediate plan did trauma establish?
6. Who admitted / assumed ownership of the patient?
7. Which consultants were involved and when?
8. What happened during the hospital course?
9. What protocol, prophylaxis, clearance, device, and disposition items mattered?
10. What complications / PI issues / review concerns need attention?

## Required Trauma Summary Anchor Fields

These fields were explicitly chosen on March 23, 2026:

- activation category and activation timing
- trauma team arrival/evaluation timing if present
- concise HPI / mechanism summary
- primary survey summary:
  - airway
  - breathing
  - circulation
  - disability / GCS
  - FAST
- immediate injury summary as trauma documented it
- immediate trauma impression
- initial trauma plan
- resuscitation flags present in the H&P itself:
  - MTP
  - blood products
  - chest tubes
  - intubation / ventilation difficulty
  - straight to OR
- whether trauma remained primary vs medicine assumed care, if explicitly documented

## Canonical Section Model

Trauma Summary v1 should organize around:

1. Patient / Activation Header
2. Trauma Summary
3. Emergency / Resuscitation Flags
4. Injury Inventory
5. Admitting Service / Ownership Transition
6. Consultant / Specialty Involvement
7. Procedures / Devices / Lines / Drains / Airway
8. Protocol / Care Milestones
9. Daily Course
10. Disposition / Follow-Up / Ongoing Needs
11. PI / Complications / Review Notes

## Above-The-Fold Priority

Because the first-review priorities are age, MOI, blood thinner use,
injuries, and consultants, the final product should evolve toward
showing those items early and clearly.

For the immediate Trauma Summary build sequence, this means:

- age and patient identity remain in the top header
- MOI belongs in the Trauma Summary opening
- anticoagulant context should remain prominent in patient-level summary
- injuries must be easy to scan
- consultant involvement must become more visible in later slices

## Path Forward

After current in-flight small work completes, the major build order is:

1. Trauma Summary / Initial Trauma Evaluation v1
2. Admitting Service + Consultant / Specialty Course Visibility v1
3. Respiratory / Ventilator Course Visibility v1
4. Protocol / Care Milestone Alignment v1
5. Pretty output / visual polish

## Raw-File Audit Policy

We do **not** need more raw-file audits to lock this direction.

We **do** need targeted raw-note audits before each major implementation
slice so the build stays source-aligned.

This direction was chosen on **March 23, 2026**.
