---
title: CerebralOS — Handoff to Codex
description: Template for handing Claude's completed work back to Codex for audit
---

Paste the following into Codex after Claude finishes and the gate passes.

---

## Claude summary

- **Changed**: <list files modified or created>
- **Verified**: `./scripts/gate_pr.sh` exited 0
- **Baseline**: MATCH (all 4 patients) / updated with `--update-baseline` (reason: ...)
- **Regression**: PASS
- **Notes**: <anything unusual or requiring review>

## Terminal output (gate tail)

```
<paste last ~30 lines of ./scripts/gate_pr.sh output here>
```

## Request

Please audit the diff and provide:
1. `git add` / `git commit` / `git push` commands
2. Any corrections or follow-ups before merge
