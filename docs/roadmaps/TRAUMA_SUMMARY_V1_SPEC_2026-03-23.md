# Trauma Summary v1 Spec

**Status:** Authoritative product decision  
**Decision Date:** March 23, 2026  
**Owners:** Sarah + Codex + Claude  
**Applies To:** All future PI RN casefile / trauma-summary build decisions unless explicitly superseded by a newer dated doc

## Why This Doc Exists

On March 23, 2026, we made an explicit product decision to stop drifting into small local fixes that do not converge on the real goal.

The real goal is not "more extracted sections" or "more cards in the current casefile."

The real goal is a deterministic, clinically trustworthy **Trauma Summary** that helps the PI RN audit the full trauma continuum of care and complete the same review workflow currently supported by the green card.

This doc is the current source of truth for that direction. It is intentionally dated so Sarah, Codex, and Claude can all distinguish it from older roadmap ideas and partial implementations.

This spec does **not** revive or depend on any abandoned legacy green-card implementation. Older green-card code may exist in the repository, but it is not the authority for this design.

## Product North Star

The product is a **single-patient trauma review document** built for:

- trauma PI review
- Deaconess trauma protocol review
- ACS NTDS-related review support
- green-card completion support
- rapid reconstruction of the trauma continuum of care

The product is **not** primarily:

- a generic dashboard
- a collection of extracted widgets
- a daily-note viewer
- a consultant viewer
- an analytics surface

Those are ingredients. The product is the **review worksheet / Trauma Summary**.

## Core Decision Made On March 23, 2026

We are **not** restarting the repository from zero.

We **are** changing the organizing model of the patient-facing product.

### Decision

Build a new, explicit, versioned **Trauma Summary v1** layer on top of the current deterministic pipeline.

That means:

- keep ingestion
- keep evidence
- keep timeline
- keep existing feature extraction where it is useful
- keep deterministic/fail-closed behavior
- stop relying on incremental section-patching as the main product strategy
- reorganize the final patient-facing output around the Trauma Summary / green-card review workflow

### Why

The current system has useful extraction foundations, but the output is still organized too much around whatever feature modules happen to exist. That has led to:

- local improvements without full workflow convergence
- underuse of the Trauma H&P
- weak reconstruction of the trauma continuum of care
- long-stay / ICU / specialty-heavy cases still feeling incomplete
- repeated "small fix" cycles instead of product completion

## Foundational Product Truths

These are now explicit assumptions for Trauma Summary v1.

### 1. Every patient in scope is an activated trauma patient

Even when trauma is not the admitting service, the PI RN still follows the patient as part of the trauma continuum of care.

Therefore:

- trauma activation remains clinically relevant
- trauma initial evaluation remains clinically relevant
- the trauma H&P or initial trauma evaluation is still part of the core story

### 2. The H&P is the anchor note

In the newer raw `.txt` files, the note flow is typically:

1. patient information
2. ADT timeline
3. first real note = anchor note

That anchor note is often:

- a Trauma H&P when trauma authors the initial evaluation

But it may also be:

- a medical / hospitalist H&P when medicine ultimately admits

For Trauma Summary v1, the system must treat the **initial trauma evaluation** as a first-class anchor even when medicine later owns the admission.

### 3. The green card is not a side artifact

The green card is a practical data model for how the PI RN reviews the trauma continuum of care.

Its ingredients feed:

- protocol review
- NTDS review support
- PI issue identification
- daily course understanding
- discharge/disposition review
- follow-up review

Trauma Summary v1 should be organized to support this workflow directly.

Important clarification:

- the **workflow** is authoritative
- the **old green-card code** is not

## What Trauma Summary v1 Must Answer

For every patient, the summary must make it easy to answer:

1. Who is this patient and where did they come from?
2. What was the trauma activation and why?
3. What did the Trauma H&P / initial trauma evaluation say?
4. What injuries and emergencies were present at the start?
5. What immediate plan did trauma establish?
6. Who admitted / assumed ownership of the patient?
7. Which consultants were involved and when?
8. What happened during the hospital course?
9. What protocol, prophylaxis, clearance, device, and disposition items mattered?
10. What complications / PI issues / review concerns need attention?

## Trauma Summary v1 Output Model

Trauma Summary v1 should be a patient-level review document with the following canonical sections.

## 1. Patient / Activation Header

Purpose: establish identity, timing, activation context, and immediate review frame.

Target fields:

- name
- MRN
- CSN
- age / DOB
- admitting date/time
- room / location when available
- from / transfer source
- trauma category / alert level
- trauma activation time
- trauma evaluation / arrival time if documented
- primary attending / MD if available
- code status

Primary sources:

- demographics
- ADT timeline
- Trauma H&P
- initial notes

## 2. Trauma Summary

Purpose: present the trauma initial evaluation as the anchor narrative for the case.

This section is the single most important new organizing section.

Target fields:

- concise HPI / MOI
- transfer narrative if present
- primary survey summary:
  - airway
  - breathing
  - circulation
  - disability / GCS
  - FAST
- immediate injury summary as trauma documented it
- initial trauma impression
- initial trauma plan
- whether trauma remained primary or medicine assumed care, if explicitly documented
- early consults initiated by trauma
- consultant contact times when explicitly documented

Primary sources:

- Trauma H&P
- trauma tertiary note
- initial trauma progress notes

Important rule:

- This section remains in scope even when trauma does not admit.

## 3. Emergency / Resuscitation Flags

Purpose: make the initial severity and emergency workflow obvious without reading the whole chart.

Target fields:

- MTP activated
- blood products / transfusion signals
- intubated
- ventilation difficulty / hypoxemia if documented
- chest tubes
- straight to OR / emergent procedure path
- shock / hemodynamic instability signals
- acute neuro emergency signals
- fast exam performed / result

Primary sources:

- Trauma H&P
- procedure notes
- early imaging / ED / trauma notes
- existing hemodynamic and procedure features

Important rule:

- These should be extracted and rendered as factual flags, not inferred severity scoring.

## 4. Injury Inventory

Purpose: give the reviewer a stable body-region injury list aligned with review workflow.

Target fields:

- head / brain
- facial / skull
- cervical spine
- thoracic / lumbar spine
- chest / ribs / sternum / lungs
- abdomen
- pelvis
- vascular
- extremity
- wound / soft tissue
- incidental findings

Primary sources:

- Trauma H&P
- imaging features
- trauma notes
- operative notes when relevant

Important rule:

- The injury inventory should reflect the reviewer's working injury model, not just a dump of every imaging phrase.

## 5. Admitting Service / Ownership Transition

Purpose: make it obvious who owned the stay and when.

Target fields:

- trauma primary vs medicine primary vs other primary service
- handoff / transfer of ownership if explicitly documented
- initial admitting plan from non-trauma H&P when relevant
- service-transition notes when relevant

Primary sources:

- Trauma H&P
- medical/hospitalist H&P
- hospital progress notes
- ADT / movement context

Important rule:

- Medicine admission does not replace the trauma summary. It supplements it.

## 6. Consultant / Specialty Involvement

Purpose: show the multidisciplinary course cleanly and longitudinally.

Target fields:

- consultant services involved
- first consult date/time when documented
- major consultant daily plan themes
- consultant-specific action items when extracted
- whether consultant involvement is ongoing vs one-time

Expected services include, when present:

- neurosurgery
- orthopedics
- vascular
- cardiology / electrophysiology
- pulmonary / critical care
- palliative care
- nephrology
- infectious disease
- ENT
- OMFS
- plastics
- hospital medicine / DCG
- others materially affecting trauma care

Primary sources:

- consultant plan features
- specialty physician notes
- trauma daily plans when trauma explicitly references consultant direction

Important rules:

- PT/OT/SLP must not leak into the consultant physician lane unless explicitly intended by design.
- Consultant visibility must be longitudinal, not just a one-time service list.

## 7. Procedures / Devices / Lines / Drains / Airway

Purpose: support rapid operational review of what was done and what the patient had in place.

Target fields:

- operative / bedside procedures
- airway events
- chest tubes
- drains
- lines / central access
- Foley / urinary devices
- PEG / feeding access
- ventilator support presence
- device start/stop when deterministically known

Primary sources:

- procedure/operative features
- LDA features
- respiratory/ventilator features
- trauma H&P and progress notes

## 8. Protocol / Care Milestones

Purpose: align directly with green-card review needs and Deaconess protocol review.

Target fields:

- anticoagulation / reversal context
- GI prophylaxis
- mechanical DVT prophylaxis
- chemical DVT prophylaxis
- spine clearance
- bowel regimen
- pulmonary toilet / IS / EZ Pap when applicable
- splenic vaccine status when applicable
- SBIRT / ETOH / UDS context
- initial imaging / labs / serial labs

Primary sources:

- existing deterministic protocol-support features
- Trauma H&P
- orders/admin features where already extracted

Important rule:

- These are protocol-review ingredients, not decorative side sections.

## 9. Daily Course

Purpose: summarize the evolving inpatient story after the initial trauma summary is established.

Target content:

- trauma daily plans
- major consultant daily plans
- important support-team plans where appropriate
- movement / transfer milestones
- disposition progress
- major clinical turning points

Important rule:

- The Daily Course is not the anchor. It sits on top of the Trauma Summary.

## 10. Disposition / Follow-Up / Ongoing Needs

Purpose: support end-of-stay review and unresolved issue tracking.

Target fields:

- PT / OT / SLP recommendations
- case management / social work disposition planning
- rehab / SNF / LTACH / hospice / home disposition
- follow-up needs
- incidental findings follow-up

Primary sources:

- disposition features
- therapy features
- case management features
- discharge summary where appropriate

## 11. PI / Complications / Review Notes

Purpose: provide the explicit review workspace for quality concerns.

Target content:

- identified complications
- PI concerns
- EMS issue checkbox / pathway if applicable
- unresolved review concerns
- notes relevant to green-card completion

Important rule:

- This section should support audit work, not replace the auditor's judgment.

## The Trauma Summary Section: Required Deterministic Fields

The following fields were explicitly chosen on March 23, 2026 as required components of the Trauma Summary anchor section:

- activation category and activation timing
- trauma team arrival/evaluation timing if present
- concise HPI / mechanism summary
- primary survey summary
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

This list is intentionally explicit because it reflects the PI RN's real workflow and must not drift back into generic casefile thinking.

## What Trauma Summary v1 Is Not

Trauma Summary v1 is not:

- a replacement for the evidence layer
- a replacement for daily notes
- a free-text narrative generator
- an inference engine
- a generic hospital chart summary

Trauma Summary v1 is a deterministic review assembly built from the evidence and feature layers.

## Implementation Strategy

We will not keep endlessly patching the current output shape section by section and hoping the green card emerges.

Instead, Trauma Summary v1 should be implemented in phased, explicit steps.

## Phase 0: Lock The Product Spec

Deliverable:

- this doc

Goal:

- stop product drift
- align Sarah, Codex, and Claude on the actual target

## Phase 1: Trauma Summary Anchor

Goal:

- build the patient-level Trauma Summary anchor section first

Expected implementation work:

- create a dedicated assembly path for the Trauma Summary section
- map the H&P and activation-related data into a stable bundle shape
- render the Trauma Summary near the top of the patient document

Definition of success:

- the reviewer can understand the opening trauma story without reading scattered sections

## Phase 2: Ownership + Consultant Course

Goal:

- clarify who owned the admission and how consultant/specialty involvement evolved

Expected implementation work:

- explicit ownership / admitting-service layer
- better longitudinal consultant visibility
- strict boundary cleanup between physician consultant lanes and therapy/support-team lanes

Definition of success:

- long-stay and specialty-heavy cases no longer feel clinically flattened

## Phase 3: Protocol / Milestone Alignment

Goal:

- make the review document line up cleanly with the green-card / protocol workflow

Expected implementation work:

- align protocol ingredients into stable review sections
- cleanly surface prophylaxis / clearance / milestone items
- ensure these are easy to audit, not buried

Definition of success:

- the PI RN can use the output directly for green-card and protocol review support

## Phase 4: Output Polish

Goal:

- make the output visually strong and pleasant to use after the core model is right

Expected implementation work:

- better section design
- cleaner summary layout
- better visual hierarchy
- removal of debug-like rendering patterns

Important rule:

- pretty output comes after the product model is correct, not instead of it

## Path Forward: Concrete Next Work

After current in-flight work completes, the next major build work should be:

1. **Trauma Summary / Initial Trauma Evaluation v1**
2. **Admitting Service + Consultant / Specialty Course Visibility v1**
3. **Respiratory / Ventilator Course Visibility v1**
4. **Protocol / green-card alignment pass**
5. **visual polish / pretty output**

This ordering was chosen deliberately on March 23, 2026 to stop small-fix drift.

## Raw-Chart Audit Policy Going Forward

We do **not** need more raw-file audits to lock this top-level product direction.

This direction is already sufficiently grounded in:

- the newer raw-file structure
- the Trauma H&P content model
- the green-card workflow
- multi-patient raw-vs-output review

However, we **do** need targeted raw-chart audits before implementing each major section so the build remains source-aligned.

Required targeted audits before implementation slices:

- Trauma Summary anchor section: yes
- consultant/ownership section: yes
- respiratory/ventilator section: yes
- protocol/milestone alignment section: yes

Those audits should be narrow and implementation-focused, not product-direction debates.

## Architectural Rules

1. Deterministic only; fail-closed.
2. No clinical inference.
3. No protected engine changes unless explicitly authorized.
4. No silent schema changes.
5. The Trauma H&P / initial trauma evaluation is the anchor for every activated trauma patient.
6. Medicine admission does not remove the trauma summary.
7. The green card is a workflow model, not a nostalgic artifact.
8. The final output must support the trauma continuum of care, not just isolated facts.

## Success Criteria

Trauma Summary v1 is successful when:

- the opening trauma story is obvious
- long-stay and ICU cases read coherently
- medicine-admit trauma activations still make clinical sense
- consultant involvement is visible without lane contamination
- protocol review is easier, not harder
- the output supports green-card completion and PI review directly

## Final Instruction To Future Builders

If future implementation work starts drifting back toward small disconnected patches, return to this document.

The standard is not:

- "can we surface one more field?"

The standard is:

- "does this move the product closer to a coherent Trauma Summary that helps the PI RN audit the full trauma continuum of care?"

That is the decision made on **March 23, 2026**.
