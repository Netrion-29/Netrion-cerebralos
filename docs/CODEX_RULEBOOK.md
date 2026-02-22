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
  `TRAUMA_DAILY_NOTES_v4.txt` against `scripts/baselines/v4_hashes_v1.json`.
  Fails on any mismatch, missing patient, or missing baseline file.
- **Update** (`./scripts/gate_pr.sh --update-baseline`): overwrites the
  baseline JSON with current hashes, then runs regression. Use only after
  intentional output changes have been reviewed and approved.

---

## 5) Default Regression Patients

Anna_Dennis
William_Simmons
Timothy_Cowan
Timothy_Nachtwey

---

## 6) raw_line_id Format Policy

Every stored evidence item and every feature-layer evidence entry
must include a non-empty `raw_line_id`. Two formats are currently
in use:

| Layer           | Format                                    | Example                            |
|-----------------|-------------------------------------------|------------------------------------|
| Layer 0 (evidence) | `L{line_start}-L{line_end}`            | `L42-L47`                          |
| Feature layer      | `sha256(source_id|dt|preview)[:16]`    | `a3f8c01b7e2d4916`                 |

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

End of rulebook.
