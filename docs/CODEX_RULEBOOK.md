# CerebralOS — CODEX Rulebook (Authoritative)

This document defines how Codex must operate inside this repository.
It is a governance contract. Treat it as binding.

---

## 0) Roles

- Sarah (Operator): runs copy/paste terminal commands and returns output.
- Codex (Repo Agent): edits code, proposes plans, runs verification, produces PR-ready diffs.
- ChatGPT (Auditor/Architect): reviews outputs, catches drift, clarifies constraints.

Codex must not assume context outside repo files.

---

## 1) Non-Negotiable Constraints

1. Deterministic output only; fail-closed logic.
2. Do NOT change v3/v4 renderer outputs unless explicitly instructed.
3. Do NOT modify:
   - cerebralos/ntds_logic/engine.py
   - cerebralos/protocol_engine/engine.py
4. Every stored evidence object must include raw_line_id.
5. No silent schema changes.
6. No scope creep.
7. Update docs in the same PR if necessary (roadmap/startup/boot/contract docs), and explicitly state "Docs update: necessary" or "Docs update: not necessary" in handoff.

If a change affects schema:

- update contract docs
- update validators
- update consumers
- in the same PR

---

## 2) Canonical Entry Point

./run_patient.sh $PAT

---

## 3) Locked Contract: patient_features_v1.json

Allowed top-level keys (exactly):

build, patient_id, days, evidence_gaps, features, warnings, warnings_summary

All feature modules MUST live only under top-level "features" dict.

Forbidden:

- dvt_prophylaxis_v1 at top-level
- gi_prophylaxis_v1 at top-level
- base_deficit_monitoring_v1 at top-level
- category_activation_v1 at top-level
- vitals_canonical_v1 at top-level
- vitals_qa at top-level

Enforced by:
cerebralos/validation/validate_patient_features_contract_v1.py

---

## 4) Required Completion Gate

Codex may not declare work complete until:

./scripts/gate_pr.sh

passes with:

- Deterministic: True
- Zero unintended artifact drift: True
- Contract validator passes
- v4 hashes printed

### Baseline drift modes

- **Normal** (`./scripts/gate_pr.sh`): compares sha256 of each patient's
  rendered output (v3, v4, v5) against persisted baselines:
  - `scripts/baselines/v3_hashes_v1.json`
  - `scripts/baselines/v4_hashes_v1.json`
  - `scripts/baselines/v5_hashes_v1.json`
  Fails on any mismatch, missing patient, or missing baseline file.
- **Update** (per-version):
  - `./scripts/gate_pr.sh --update-baseline`    → v4
  - `./scripts/gate_pr.sh --update-baseline-v3` → v3
  - `./scripts/gate_pr.sh --update-baseline-v5` → v5
  Overwrites the target baseline JSON with current hashes, then runs
  regression. Use only after intentional output changes have been
  reviewed and approved.

---

## 5) Default Regression Patients

Anna_Dennis
William_Simmons
Timothy_Cowan
Timothy_Nachtwey

---

## 6) Side-Track Audit Triage

When an audit or review surfaces findings outside the active PR's scope,
Codex must triage each finding into exactly one track:

1. **Current PR** — only if the finding falls squarely within the PR's stated goal.
2. **Doc-only note** — default for useful but out-of-scope findings. Write to `docs/audits/<topic>.md`.
3. **Future fix track** — required when protected engines/rules (NTDS engine, protocol engine, renderers) are involved, unless the operator explicitly approves an in-PR fix.

Codex must:
- State the triage decision and reasoning.
- Preserve useful findings in-repo (`docs/audits/`) so they survive across sessions.
- Never derail the active roadmap sequence to address a side-track finding.

---

## 7) raw_line_id Format Policy

Every stored evidence item and every feature-layer evidence entry
must include a non-empty `raw_line_id`. Two formats are currently
in use:

| Layer           | Format                                    | Example                            |
|-----------------|-------------------------------------------|------------------------------------|
| Layer 0 (evidence) | `L{line_start}-L{line_end}`            | `L42-L47`                          |
| Feature layer      | `sha256(source_id\|dt\|preview)[:16]`  | `a3f8c01b7e2d4916`                 |

**Rules:**

1. Both formats are acceptable provided they are **deterministic**
   and **traceable** back to the source evidence.
2. A given layer must use exactly one format consistently.
3. `raw_line_id` must never be empty, null, or omitted.
4. Any change to the derivation formula requires a version bump to
   the corresponding contract document.

**Future normalization (doc note — no code changes):**
A future PR may unify both layers to a single format (likely the
line-range format `L{start}-L{end}`) for simpler cross-layer audit
tracing. This will be tracked as a Tier 3 hardening task. Until then,
both formats coexist.

---

## 8) CEREBRALOS PREFLIGHT FIRST

Shortcut phrase: `CEREBRALOS PREFLIGHT FIRST`

Before giving merge, branch cleanup, or PR creation/retarget/rebase
guidance, Codex must request or verify the output of these commands:

### Preflight (merge / cleanup / what-is-open)

```bash
cd ~/NetrionSystems/netrion-cerebralos
git checkout main
git fetch origin
gh pr list --state open
git status --short
```

### Branch PR preflight (before staging / commit / push)

```bash
git rev-parse --abbrev-ref HEAD
git status --short
git diff --name-only origin/main...HEAD
git diff --name-only
git diff --cached --name-only
```

Pre-existing untracked local files (e.g., `tests/test_negation.py`,
`tests/test_ntds_events.py`, `tests/test_ntds_simple.py`) may appear
in `git status`. Distinguish these from PR scope — do not stage or
include them unless they belong to the current PR.

### Lean Verification Mode (Default)

Codex should use lean verification cadence by default to reduce cycle
time while maintaining safety:

1. One preflight block per cycle.
2. One scope check (`git diff --name-only origin/main...HEAD`).
3. One validation pass matched to change scope.
4. One final merge-readiness audit with exact commands.

Escalate to deeper/repeated checks only when:

- branch/PR state changes mid-cycle,
- protected files are touched,
- baseline/test output drifts unexpectedly,
- or the operator explicitly requests deep audit mode.

---

## 9) Post-Handoff Analysis (Codex Required)

After every Claude handoff, Codex must perform and report:

1. **Spec alignment check** against AGENTS.md constraints and current PR scope.
2. **Validation summary** (tests/gate run, pass/fail, any gaps).
3. **Copilot/GitHub comments triage** for unresolved feedback:
   - classify each as `must-fix-now` vs `defer`
   - cite file/line when available.
4. **Risk/gap assessment** (behavioral regressions, drift risk, missing coverage).
5. **Next actions** (exact terminal commands and PR/UI steps).

End of rulebook.
