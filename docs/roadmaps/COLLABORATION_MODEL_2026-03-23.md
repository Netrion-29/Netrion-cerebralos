# Collaboration Model

**Status:** Authoritative working agreement  
**Decision Date:** March 23, 2026  
**Applies To:** Sarah, Codex, Claude, and the Copilot sidecar chat

## Purpose

This document locks in how the build work should operate so the project
does not drift back into:

- disconnected small fixes
- prompt-by-prompt product changes
- repeated re-explanation of the same workflow
- unclear ownership between tools

## Core Principle

Sarah provides workflow truth.  
Codex directs architecture and sequence.  
Claude implements against current dated specs/build plans.  
The Copilot sidecar chat provides bounded audits and cross-checks.

## Named Panels / Roles

### Left panel: `Codex`

Role:

- architect
- build director
- workflow translator
- reviewer

Responsibilities:

- convert Sarah's workflow truth into specs, build plans, and prompts
- decide what should be built next
- ask targeted workflow/process questions
- prevent drift into disconnected small fixes
- reconcile conflicts between Claude and Scout findings
- review implementation against product intent

### Right panel: `Claude`

Role:

- implementation agent
- repo execution agent

Responsibilities:

- implement against current dated docs
- run the main audit or implementation work
- keep behavior deterministic and fail-closed
- update tests/docs/contracts/validators when required
- run `./scripts/gate_pr.sh` before completion

### Middle/top panel: `Scout`

`Scout` is the fixed name for the separate Copilot sidecar chat.

Role:

- sidecar explorer
- bounded audit tool
- cross-check tool

Responsibilities:

- run parallel audits Codex explicitly defines
- look for misses, conflicts, and source-boundary issues
- challenge assumptions with raw-source evidence

Non-responsibilities:

- Scout does not define the product
- Scout does not decide final architecture
- Scout does not override current dated specs/build plans

## Sarah's Role

Sarah is:

- workflow owner
- trauma review domain expert
- Deaconess process truth source
- final judge of whether output is clinically useful

Sarah is not expected to know:

- architecture options
- repo design patterns
- prompt strategy
- coding patterns

Sarah's job is to define:

- what the PI RN workflow actually is
- what matters clinically
- what is wrong or missing in the output
- what fields/processes are mandatory vs secondary

## Working Pattern

This is now the default pattern:

1. Sarah explains workflow truth, a pain point, or a goal.
2. Codex turns that into:
   - a decision
   - a dated spec/build plan
   - an audit or implementation prompt
3. Claude performs the main audit or implementation.
4. Scout performs a bounded sidecar audit when useful.
5. Codex reconciles the results and sets the next move.

## Question Policy

Codex should ask Sarah targeted questions about:

- workflow
- hospital process
- review priorities
- mandatory fields
- what the PI RN looks at first
- what makes output trustworthy enough to use

Codex should not ask Sarah to choose architecture details she should
not need to own.

## Current Product Direction

As of March 23, 2026, the active product direction is defined by:

- [TRAUMA_SUMMARY_V1_SPEC_2026-03-23.md](./TRAUMA_SUMMARY_V1_SPEC_2026-03-23.md)
- [TRAUMA_SUMMARY_INITIAL_EVALUATION_V1_BUILD_PLAN_2026-03-23.md](./TRAUMA_SUMMARY_INITIAL_EVALUATION_V1_BUILD_PLAN_2026-03-23.md)

## Guardrail

If work starts drifting toward:

- "just one more card"
- "just one more small patch"
- "maybe this section alone solves it"

return to these docs before continuing.

This working model was chosen on **March 23, 2026**.
