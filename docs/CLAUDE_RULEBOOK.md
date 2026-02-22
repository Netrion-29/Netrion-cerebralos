# CerebralOS — Claude Rulebook (Authoritative)

This file defines how Claude must operate inside this repository.

## Hard constraints
- Deterministic + fail-closed only
- No renderer drift unless explicitly instructed
- Do not modify protected engines unless explicitly instructed
- No silent schema changes (docs + validators + consumers in same PR)
- raw_line_id required on stored evidence
- No scope creep

## Mandatory verification for every change
Run:
./scripts/gate_pr.sh
and paste full output.

End.
