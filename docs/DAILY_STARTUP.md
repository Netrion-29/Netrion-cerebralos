# CerebralOS — Daily Startup Checklist

## 1) Daily Workflow

1. Open VS Code in repo root (`~/NetrionSystems/netrion-cerebralos`).
2. Run:

   ```bash
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
>
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
>
> ```bash
> cd ~/NetrionSystems/netrion-cerebralos
> git status
> ./scripts/gate_pr.sh
> ```
>
> Always include this exact `Return:` block at the end of the prompt:
>
> ```text
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

```text
feat: add GI prophylaxis section to v4 report

Baseline updated: v4 output now includes GI prophylaxis rows.
```

Never use `--update-baseline` to silence an unexpected mismatch.

---

## 5) Handoff format (Claude → Codex)

After Claude completes work and the gate passes, paste **exactly** this
back to Codex:

```text
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

- **[Whole-Project State and Roadmap v1](roadmaps/CEREBRALOS_WHOLE_PROJECT_STATE_AND_ROADMAP_v1.md)** ← primary context-recovery doc
- [Trauma Build-Forward Plan v1](roadmaps/TRAUMA_BUILD_FORWARD_PLAN_v1.md) (historical)

> **NTDS Coverage:** 21/21 events fully mapped (PRs #118 – #124).
> Fixture runner: 43 passed, 0 xfailed.
>
> **Phase status (as of PR #147):**
> - N1 (slug normalization): ✅ COMPLETE (PRs #127–#128)
> - N2 Phase 1 (gate cohort invariant + handoff embedding): ✅ COMPLETE (PRs #129–#131)
> - N3 (precision tuning): ✅ COMPLETE (PRs #132–#138) — 6 events tightened (E16, E10, E19, E15, E18, E01)
> - N4-P1 (AKI UTD reduction): ✅ COMPLETE (PR #141) — timing gate + onset patterns
> - N4-P2b (parser word-boundary fix): ✅ COMPLETE (PR #143) — 8 validated deltas, 0 regressions
> - N5 (DISCHARGE line-start anchor): ✅ COMPLETE (PR #145) — 5 validated deltas (all corrections), 0 regressions
> - N6 (DISCHARGE first-word block): ✅ COMPLETE (PR #147) — 109/118 residual false flips eliminated, 0 NTDS outcome deltas
> - N7 (DISCHARGE prose residual cleanup): ✅ COMPLETE (PR #149) — all 14 remaining false flips eliminated, 0 NTDS outcome deltas
> - D1 (full cohort output refresh): ✅ COMPLETE — 33/33 patients refreshed, 0 NTDS outcome deltas, cohort invariant PASS
> - D2 (IMAGING/RADIOLOGY/PROCEDURE line-start anchor): ✅ COMPLETE (PR #152) — 3 patterns anchored, 68 tests added, 0 NTDS outcome deltas
> - Next phase: source-pattern audits (D3/D4) + remaining event precision — see Roadmap doc §3
>
> See Roadmap doc §3 for full backlog detail, N3 residuals, and N4 queue.

> **Dev-loop default:** use the 12-patient sentinel cohort for fast validation.
> Full 33-patient cohort runs only at the pre-merge gate (`./scripts/gate_pr.sh`).
> See the Whole-Project State doc §4 for the sentinel patient list.

---

## 7) Codex Audit Step (Required After Gate)

After `./scripts/dev_start.sh` completes, paste this block into Codex:

> Review `outputs/audit/codex_handoff.md`.
>
> Do the following:
>
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

---

## 9) CEREBRALOS PREFLIGHT FIRST

> **Shortcut phrase: `CEREBRALOS PREFLIGHT FIRST`**
>
> Run these commands **before** giving or following merge, branch
> cleanup, or PR creation/retarget/rebase guidance.

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

> **Note:** Pre-existing untracked local files (e.g.,
> `tests/test_negation.py`, `tests/test_ntds_events.py`,
> `tests/test_ntds_simple.py`) may appear in `git status`.
> Distinguish these local-only files from PR scope — do not
> stage or include them unless they belong to the current PR.

---

## 10) Quick Chat Starter (New ChatGPT/Codex Sessions)

Paste the block below as the **first message** in any fresh ChatGPT or
Codex chat to activate roadmap-first architect/reviewer mode with
side-track triage. Full version lives in `docs/CHATGPT_BOOT_HEADER.md`.

```text
CEREBRALOS MODE: Architect/Reviewer only. Roadmap-first.
CEREBRALOS PREFLIGHT FIRST — always run preflight before merge,
cleanup, PR, or rebase guidance.
You decide scope/triage (current PR vs doc note vs future fix track).
Claude executes code changes.
Give detailed step-by-step terminal + GitHub UI instructions.

At chat start, first read
docs/roadmaps/CEREBRALOS_WHOLE_PROJECT_STATE_AND_ROADMAP_v1.md,
then determine current branch, merged PR state, and repo diffs
before recommending next work.

If side-track findings appear (NTDS/protocol/archive audits),
triage them: current PR vs doc-only note vs future dedicated
fix track, and explain why.
```
