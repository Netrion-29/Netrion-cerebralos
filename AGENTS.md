# CerebralOS — AGENTS.md (Codex Operating Contract)

These instructions are authoritative for Codex operating inside this repository.

## Roles
- Sarah: operator; only copy/pastes terminal commands and reports outputs.
- Claude (VS Code): repo agent; edits code and runs commands.
- Codex (ChatGPT in VS Code): architect + reviewer; proposes plan + exact commands.

## Non-negotiable constraints
1) Deterministic output only; fail-closed logic. No clinical inference.
2) Do NOT change v3/v4 renderer outputs unless explicitly instructed.
3) Do NOT modify protected engines unless explicitly instructed:
   - cerebralos/ntds_logic/engine.py
   - cerebralos/protocol_engine/engine.py
4) No silent schema changes. If schema changes, update docs + validators + consumers in same PR.
5) Every stored evidence item must include raw_line_id.
6) No scope creep: one PR = one goal.

## Canonical pipeline
Entry point: ./run_patient.sh $PAT

Artifacts:
- outputs/evidence/$PAT/patient_evidence_v1.json
- outputs/timeline/$PAT/patient_days_v1.json
- outputs/features/$PAT/patient_features_v1.json
- outputs/reporting/$PAT/TRAUMA_DAILY_NOTES_v4.txt

## Locked contract: patient_features_v1.json
Allowed top-level keys (exactly):
build, patient_id, days, evidence_gaps, features, warnings, warnings_summary

All feature modules MUST live ONLY under top-level "features" dict.
Forbidden: any feature module keys at the top-level.

Enforced by:
cerebralos/validation/validate_patient_features_contract_v1.py

## Completion gate (mandatory)
Codex/Claude may not declare "done" until:
./scripts/gate_pr.sh
passes.

Default gate patients:
Anna_Dennis, William_Simmons, Timothy_Cowan, Timothy_Nachtwey

## Baseline drift checking
- Normal mode (`./scripts/gate_pr.sh`): compares sha256 of each
  patient's rendered output (v3, v4, v5) against persisted hashes in
  `scripts/baselines/v3_hashes_v1.json`, `scripts/baselines/v4_hashes_v1.json`,
  and `scripts/baselines/v5_hashes_v1.json`. FAILS on any mismatch,
  missing patient, or missing baseline file.
- Update mode (per-version):
  - `./scripts/gate_pr.sh --update-baseline`    → regenerates v4 baseline
  - `./scripts/gate_pr.sh --update-baseline-v3` → regenerates v3 baseline
  - `./scripts/gate_pr.sh --update-baseline-v5` → regenerates v5 baseline
  Use only after intentional output changes have been reviewed.
- The baseline files are committed to the repo; drift is caught in CI.

End.
