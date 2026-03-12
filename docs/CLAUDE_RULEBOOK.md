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

## Mandatory handoff fields
Every Claude→Codex handoff must include:
- Branch name and HEAD commit hash
- PR URL/number (or explicit "no PR")
- `git diff --name-only`
- `git status --short`
- Unresolved Copilot/GitHub review comments summary (path:line, author, must-fix-now vs defer)
- Blockers/open questions

End.
