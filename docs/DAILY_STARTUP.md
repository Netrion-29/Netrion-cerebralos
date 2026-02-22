# CerebralOS — Daily Startup Checklist

## 1) Daily Workflow

1. Open VS Code in repo root (`~/NetrionSystems/netrion-cerebralos`).
2. Run:
   ```
   ./scripts/dev_start.sh
   ```
3. Copy or open `outputs/audit/codex_handoff.md`.
4. Paste the standardized **Codex Audit Step** (§7 below) into Codex chat.
5. Follow Codex's commit instructions.
6. Commit and push.

---

## 2) First-message templates

### A) Codex first message (planner / reviewer role)

> You are Codex operating as architect + reviewer for CerebralOS.
>
> Read: AGENTS.md, docs/CODEX_RULEBOOK.md
>
> Current branch: `tier1/<TICKET>`
> Goal for this session: `<ONE-LINE GOAL>`
>
> Propose:
> 1. Allowed files to modify
> 2. Exact terminal commands for Claude to run
> 3. Expected outputs / acceptance criteria
>
> Do NOT modify renderers, NTDS engine, protocol engine, or feature logic
> unless explicitly instructed.

### B) Claude first message (executor role)

> You are Claude operating as repo agent (executor) for CerebralOS.
>
> Read: AGENTS.md, docs/CLAUDE_RULEBOOK.md
>
> Current branch: `tier1/<TICKET>`
> Goal for this session: `<ONE-LINE GOAL>`
>
> Implement the changes, then run:
> ```
> cd ~/NetrionSystems/netrion-cerebralos
> git status
> ./scripts/gate_pr.sh
> ```
> Always include this exact `Return:` block at the end of the prompt:
> ```
> Return:
> 1) Claude SUMMARY (files changed + why)
> 2) Terminal output tail (include baseline drift check block + final gate line)
> 3) git diff --name-only
> 4) git status --short
> 5) Any blockers/open questions
> ```

---

## 3) Standard gate run

```bash
cd ~/NetrionSystems/netrion-cerebralos
git status
./scripts/gate_pr.sh
```

Gate must exit 0 with:
- All v4 baseline hashes: MATCH
- Regression: PASS
- Zero unintended artifact drift: True

---

## 4) When to use `--update-baseline`

Use **only** when:
- An intentional, reviewed change alters v4 report output.
- You have confirmed the new output is correct.

When you do:
```bash
./scripts/gate_pr.sh --update-baseline
```

**Required**: include an explicit note in the commit message explaining
why the baseline changed, e.g.:

```
feat: add GI prophylaxis section to v4 report

Baseline updated: v4 output now includes GI prophylaxis rows.
```

Never use `--update-baseline` to silence an unexpected mismatch.

---

## 5) Handoff format (Claude → Codex)

After Claude completes work and the gate passes, paste **exactly** this
back to Codex:

```
## Claude summary
<2-5 bullet points: what changed, what was verified>

## Gate output (tail)
<paste last ~30 lines of gate output, including baseline drift check
 and "Gate complete.">

## Request
Please audit the changes and provide commit + push commands.
```

---

## 6) End-of-day closeout

```bash
cd ~/NetrionSystems/netrion-cerebralos
git diff --stat
git status
# stage + commit
git add <files>
git commit -m "<type>: <description>"
git push -u origin HEAD
```

Verify the push succeeded and note the branch name for tomorrow.

---

## Planning docs

- [Trauma Build-Forward Plan v1](roadmaps/TRAUMA_BUILD_FORWARD_PLAN_v1.md)

---

## 7) Codex Audit Step (Required After Gate)

After `./scripts/dev_start.sh` completes, paste this block into Codex:

> Review `outputs/audit/codex_handoff.md`.
>
> Do the following:
> 1) Verify changes obey AGENTS.md constraints.
> 2) Confirm no renderer/NTDS/protocol drift.
> 3) Confirm baseline gate behavior matches spec.
> 4) List any risks or edge cases.
> 5) If clean, give commit message and exact git commands.

If `codex_handoff.md` contains placeholders, treat as FAIL and re-run the gate.

---

## 8) Standard Claude Return Block

Use this in every Codex→Claude prompt so handoffs are consistent and
review-ready:

```text
Return:
1) Claude SUMMARY (files changed + why)
2) Terminal output tail (include baseline drift check block + final gate line)
3) git diff --name-only
4) git status --short
5) Any blockers/open questions
```
