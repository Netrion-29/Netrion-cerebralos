# Orthopedic Emergency Interpretation v1

**Status:** Authoritative protocol/accountability interpretation  
**Decision Date:** March 23, 2026  
**Depends On:** [REVIEW_ARCHITECTURE_V1_2026-03-23.md](./REVIEW_ARCHITECTURE_V1_2026-03-23.md)

## Purpose

This document locks the March 23, 2026 operational interpretation of
the **orthopedic emergency** workflow for PI RN / ImageTrend review.

It defines how this program should later reason about:

- trigger status
- timing clock
- acceptable response evidence
- reduction status
- PI attribution

This is not a generic orthopedic reference. It is an operational trauma
PI/accountability interpretation.

## Why This Doc Exists

Orthopedic emergency review differs from neurosurgery emergency review
in a key way:

- **bedside presence matters**

Documentation is also less reliable, and real raw-chart emergency
examples are thinner in the current repo than routine ortho consult
examples. This means the rule must be written explicitly rather than
inferred later from a few scattered notes.

## Scope

This document applies only to:

- **orthopedic emergency accountability**

It does **not** define:

- routine orthopedic consult timing
- fracture coding logic beyond what is needed for emergency review
- long-term orthopedic follow-up
- vascular emergency precedence
- NTDS complication logic

Those will be handled elsewhere.

## Canonical Operational Rule

A case counts as an **orthopedic emergency** when at least one
qualifying emergency pathway is present and the event has not already
been operationally excluded before trauma calls orthopedics.

### 1. Unstable pelvic fracture pathway

The case counts when all of the following are true:

- pelvic fracture with pelvic ring instability
- at least **two** of:
  - systolic blood pressure <= 90
  - heart rate > 100
  - respiratory rate > 30

Explicit exclusion:

- isolated pubic rami fracture does **not** count

### 2. Compartment syndrome pathway

The case counts when there is:

- suspected extremity compartment syndrome

### 3. Femoral head dislocation pathway

The case counts when there is:

- femoral head dislocation **prior to successful reduction**

Operational exclusion:

- once reduced, this pathway is excluded

### 4. Talus / subtalar pathway

The case counts when there is:

- talus fracture with subtalar dislocation **prior to successful
  reduction**

Operational note:

- this must be documented
- orthopedic documentation is treated as the most authoritative source
  for this diagnosis because the case cannot be submitted as an ortho
  emergency if the qualifying diagnosis is never actually documented

Operational exclusion:

- once reduced, this pathway is excluded

### 5. Vascular-compromise fracture/dislocation pathway

The case counts when there is:

- documented vascular compromise associated with fracture or dislocation

Examples of real-world evidence may include:

- pulseless extremity
- dusky/cold limb
- poor arterial perfusion
- similar documented vascular-compromise findings

### 6. Trauma-surgeon discretionary pathway

A case may also count when:

- the trauma surgeon/ESA explicitly treats the case as an orthopedic
  emergency in the Trauma H&P

Operational note:

- this has not been seen often in the current sample
- but if it is used, it should be documented in the Trauma H&P

## Clock Start

The orthopedic emergency response clock starts from:

- **ESA / Trauma H&P documented orthopedic call time only**

This is the authoritative start time.

The following do **not** start the clock by themselves:

- consult order time
- nursing note time
- later progress-note timing
- implied timing from subsequent specialty notes

## Response Standard

Orthopedics is expected to be:

- **at bedside within 30 minutes**

This is different from neurosurgery, where the key accountability
standard is timely neurosurgery documentation/response.

## Acceptable Orthopedic Response Evidence

The following count as acceptable orthopedic response evidence:

1. orthopedic note timestamp within 30 minutes
2. later orthopedic note that explicitly documents bedside time within
   30 minutes
3. reduction/procedure documentation with exact time
4. explicit orthopedic note statement that they were at bedside at an
   exact time within 30 minutes

Important rule:

- if there is **no exact documented time**, use the note time only

Operational note:

- exact time is preferred
- later documented exact time is currently accepted operationally even if
  the note itself is later
- this is allowed for now, even though the preferred state is for the
  actual note time itself to be within 30 minutes

## What Does Not Count as Timely Evidence

The following do **not** count as timely orthopedic bedside evidence by
themselves:

- trauma note saying ortho was aware
- consult order timestamp alone
- note text without an exact time
- vague statements such as "seen in ED" without a documented time

## Reduction Rule

Reduction is a key operational modifier in this workflow.

### If reduction happens before trauma calls orthopedics

If ED or another provider reduces the qualifying injury **before**
trauma makes the emergency call to orthopedics:

- it does **not** operationally trigger orthopedic emergency review

Reason:

- in this workflow, trauma is what triggers the emergency call and
  starts the accountability clock

### If trauma calls orthopedics before reduction

If trauma calls orthopedics while the qualifying injury is still
present:

- it is an orthopedic emergency
- it remains operationally active until reduced

Product implication for later work:

- later structured output should show a visible `reduced` flag and
  reduction time when documented
- the system should not try to over-adjudicate every reduction scenario
  automatically

## PI Attribution Rule

If the patient meets orthopedic emergency criteria:

### Case A: ESA call time documented in Trauma H&P

If orthopedics does not document timely bedside response, the PI is:

- orthopedic emergency response delay

Attribution:

- **orthopedics**

### Case B: ESA call time missing in Trauma H&P

If the patient met criteria but ESA never documented when orthopedics
was called, the same PI label may still be used operationally.

Attribution:

- **ESA**

Reason:

- orthopedics cannot be held to a 30-minute response clock if the start
  of that clock was never documented by trauma

## Documentation Authority

Two different documentation authorities matter here.

### 1. Clock authority

For emergency timing/accountability:

- Trauma H&P call time is authoritative

### 2. Diagnostic authority

For certain qualifying diagnoses, especially rare patterns such as
talus/subtalar injuries:

- orthopedic documentation may be the most authoritative source for
  whether the qualifying diagnosis was truly present

This split must remain explicit in later product design.

## Overlap with Vascular Emergency

Current provisional rule:

- a fracture/dislocation case with vascular compromise may trigger
  **both** the orthopedic emergency lane and the vascular emergency lane

Reason:

- local source text supports orthopedic trigger for documented vascular
  compromise with fracture/dislocation
- local vascular protocol text also supports vascular review in
  overlapping arterial-compromise scenarios

Current decision:

- do **not** force precedence yet
- allow both lanes provisionally
- final precedence, if needed, will be decided after the vascular
  emergency interpretation is written

## Real Example in Current Repo

The current repo contains a useful overlap example:

- [Timothy_Cowan.txt](../../data_raw/Timothy_Cowan.txt)

Useful features of this case:

- trauma-context grain-bin injury
- pulseless extremity
- vascular-compromise findings
- severe humerus fracture
- explicit Trauma H&P orthopedic call time
- explicit Trauma H&P vascular call time

This case supports:

- the ESA call-time rule
- fracture/dislocation with vascular-compromise overlap
- the need to treat ortho and vascular as potentially parallel review
  lanes

## Evidence Prioritization for Later Product Work

When later implementation happens, evidence should be prioritized in
this order:

1. Trauma H&P qualifying injury/emergency statement
2. Trauma H&P orthopedic call time
3. documentation that the qualifying lesion was or was not reduced
4. orthopedic-authored note timestamp
5. explicit orthopedic-documented bedside time
6. reduction/procedure note time

## Future Product Fields

Not for implementation yet, but this doc supports later structured
fields such as:

- `meets_ortho_emergency`
- `ortho_emergency_basis`
- `esa_ortho_call_time`
- `ortho_response_note_time`
- `ortho_response_documented_time`
- `reduced`
- `reduction_time`
- `reduction_documented_by`
- `ortho_response_status`
- `ortho_response_attribution`

## Out of Scope

This doc does not yet define:

- exact structured source hierarchy when diagnosis wording conflicts
- final precedence between ortho and vascular in overlap cases
- exact renderer placement
- how to integrate this with broader fracture coding logic
- how to integrate this with NTDS

Those will be handled later.
