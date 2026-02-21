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

---

## 5) Default Regression Patients

Anna_Dennis
William_Simmons
Timothy_Cowan
Timothy_Nachtwey

End of rulebook.
