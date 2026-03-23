# Collaboration Model

**Status:** Authoritative working agreement  
**Decision Date:** March 23, 2026  
**Owners:** Sarah + Codex + Claude  
**Applies To:** Day-to-day build decisions for the trauma summary / PI RN casefile work

## Why This Doc Exists

This document locks in the new working model chosen on March 23, 2026 so the project does not drift back into:

- small disconnected fixes
- unclear ownership
- ad hoc prompt direction
- repeated re-explanation of the same product intent

This is the operating agreement for how Sarah, Codex, Claude, and the separate Copilot audit chat should work together.

## Core Principle

Sarah provides the workflow truth.

Codex translates that workflow truth into architecture, sequence, decisions, and implementation direction.

Claude implements against explicit specs and build plans.

Copilot audit chat is a sidecar audit/explorer tool, not the source of product direction.

## Roles

## Sarah

Sarah is:

- domain expert
- PI RN workflow owner
- trauma-review truth source
- final judge of whether the output is clinically useful

Sarah is **not** expected to know:

- software architecture patterns
- repo design patterns
- prompt architecture
- implementation sequencing strategy
- all technical options available

Sarah's main responsibilities:

- explain the real trauma-review workflow
- explain hospital process and protocol reality
- identify when output is clinically wrong, incomplete, or noisy
- define what matters most for PI review
- answer targeted workflow/process questions from Codex

## Codex

Codex is:

- architect
- reviewer
- build director
- workflow translator

Codex's responsibilities:

- direct the flow of work
- prevent drift into low-value small fixes
- translate Sarah's workflow into dated specs, build plans, and implementation targets
- ask targeted workflow/process questions when domain clarification is needed
- decide when raw-note audits are required and what they should answer
- review Claude output against product intent, not just code diff quality
- push back when a proposed path is the wrong layer, wrong sequence, or wrong scope

Codex should not default to:

- letting implementation wander
- assuming the current output model is correct
- asking Sarah to decide technical architecture details she should not need to own

## Claude

Claude is:

- implementation agent
- repo execution agent

Claude's responsibilities:

- implement against the current dated spec/build plan
- verify raw-source reality when the prompt requires it
- keep changes deterministic and fail-closed
- update docs/contracts/tests/validators when required
- run the gate before declaring completion
- return concrete handoffs suitable for Codex review

Claude should not define product direction independently when a current dated spec exists.

## Copilot Audit Chat

The separate Copilot chat is available and useful, but its role is now constrained.

Copilot audit chat is:

- sidecar explorer
- parallel audit tool
- hypothesis checker

Its best uses:

- narrow raw-note audits
- source-coverage audits
- compare two implementation options
- identify missing source containers or service patterns
- spot likely test/doc drift

It is **not**:

- final product architect
- final source of truth for workflow direction
- a replacement for Codex review

If Copilot findings conflict with Claude or Codex, Codex resolves the disagreement using:

- raw source evidence
- current dated specs/build plans
- product workflow fit

## Working Pattern Going Forward

The standard build pattern is now:

1. Sarah explains workflow truth or a pain point.
2. Codex translates that into:
   - a decision
   - a dated spec or build plan
   - a concrete implementation target
3. Claude implements against that target.
4. Codex reviews the result against:
   - the spec
   - the workflow
   - raw-source reality where needed
5. If more exploration is needed, Copilot audit chat is used narrowly and explicitly.

## Question Policy

Codex should ask Sarah targeted questions about:

- PI RN workflow
- Deaconess process
- what fields are mandatory vs nice-to-have
- what the reviewer looks at first
- what counts as clinically useful output
- what would make the output trustworthy enough to use directly

Codex should **not** keep asking vague technical or open-ended architecture questions that Sarah should not need to answer.

## Product Control Policy

When there is a risk of drift, Codex should:

- slow down implementation
- write/update the controlling doc
- define scope
- then resume implementation

This is preferred over letting another unstructured PR happen.

## Current Product Direction

As of March 23, 2026, the active product direction is:

- [TRAUMA_SUMMARY_V1_SPEC_2026-03-23.md](./TRAUMA_SUMMARY_V1_SPEC_2026-03-23.md)
- [TRAUMA_SUMMARY_INITIAL_EVALUATION_V1_BUILD_PLAN_2026-03-23.md](./TRAUMA_SUMMARY_INITIAL_EVALUATION_V1_BUILD_PLAN_2026-03-23.md)

These docs supersede older informal assumptions about how the casefile should evolve.

## Immediate Practical Meaning

This means:

- no more drifting into tiny fixes without asking whether they advance the Trauma Summary workflow
- no more assuming more sections equals better product
- no more treating the H&P as just another source fragment
- no more letting sidecar audits become product direction by accident

## What Success Looks Like

This collaboration model is working if:

- Sarah does not have to keep re-explaining the same product truth
- Codex is actively steering the build
- Claude is implementing against explicit targets
- Copilot is used as a bounded helper, not another decision center
- the product gets closer to the real trauma-review workflow with each major slice

This is the working agreement chosen on **March 23, 2026**.
