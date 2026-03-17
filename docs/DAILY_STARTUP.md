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
- All NTDS baseline hashes: MATCH (39 patients)
- All NTDS distribution: MATCH (21 events)
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
- [LDA Engine Design v1](audits/LDA_ENGINE_DESIGN_v1.md) — ✅ IMPLEMENTED (v1+text+startstop+per-event+vent-recall) Lines/Drains/Airways device-duration engine design; text-derived flowsheet day-counter extraction; insertion/removal start/stop inference (`TEXT_DERIVED_STARTSTOP`); `eval_lda_overlap` interval overlap gate; `ENABLE_LDA_GATES` feature flag (default False); per-event LDA gates enabled for E05/E06/E21 via runner toggle + rule `required: true` (PRs #244–#246); vent start/stop episode extraction for E21 recall (PR #248); 180+ dedicated tests (PRs #203, #206, #207, #244, #245, #246, #248)
- [CAUTI Engine Design v1](audits/CAUTI_ENGINE_DESIGN_v1.md) — CAUTI-specific LDA duration gate + alternative-source exclusion design (predecessor; CAUTI clinical requirements still authoritative; engine approval needed)
- [Protocol Data Element Master v1](audits/PROTOCOL_DATA_ELEMENT_MASTER_v1.md) — comprehensive inventory of all data elements across 51 protocol PDFs; coverage Slices A/B/C COMPLETE (PRs #222–#232); vent settings COMPLETE (PRs #233–#237); GCS components COMPLETE (PRs #238–#239); tabular GCS flowsheet COMPLETE (PR #243); see Roadmap §3 item 15 for next candidates

> **NTDS Coverage:** 21/21 events fully mapped (PRs #118 – #124).
> Fixture runner: 43 fixtures passed (56 tests), 0 xfailed.
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
> - D3 (DISCHARGE word-boundary): **CLOSED (won't do)** — `\b` after PROCEDURE breaks 262 legitimate "Procedures:" headers; zero practical impact on other patterns
> - D5 (LAB/MAR line-start anchor): ✅ COMPLETE (PR #154) — 2 patterns anchored, 2 tests added, 0 NTDS outcome deltas
> - D6-P1 (MEDICATION_ADMIN/ED_NOTE anchor): ✅ COMPLETE (PR #156) — 2 patterns anchored, 11 tests added, 0 NTDS outcome deltas
> - D6-P2 (PHYSICIAN_NOTE anchor): ✅ COMPLETE (PR #158) — 1 pattern anchored, 6 tests added, 0 NTDS outcome deltas
> - D6-P3 (NURSING_NOTE anchor): ✅ COMPLETE (PR #159) — 1 pattern anchored + E09 rule widened, 9 tests added, 0 NTDS outcome deltas
> - D6-P4 (CONSULT_NOTE prose-before block): ✅ COMPLETE — prose-before filter added, 49 false triggers eliminated, 26 sub-headers preserved, 25 tests added, 0 NTDS outcome deltas
> - D6-P5 (EMERGENCY hardening): ✅ COMPLETE — pattern tightened to EMERGENCY DEPT/DEPARTMENT + trailing whitelist + prose-before filter, 464 false triggers eliminated, 18 tests added, 0 NTDS outcome deltas
> - D6-P6 (OPERATIVE_NOTE anchor): ✅ COMPLETE — compound-prefix anchor, 3860 false triggers eliminated, 14 tests added, 0 NTDS outcome deltas
> - D6-P7 (PROGRESS_NOTE anchor): ✅ COMPLETE — compound-prefix anchor with 20 specialty prefixes, 308 false triggers eliminated, 438 sub-headers preserved, 13 tests added, 0 NTDS outcome deltas
> - ED_NOTE allowed_sources gap: ✅ COMPLETE — ED_NOTE added to 12 NTDS events (E01 AKI, E02 ARDS, E03 Alcohol Withdrawal, E04 Cardiac Arrest, E08 DVT, E09 Delirium, E10 MI, E14 PE, E15 Severe Sepsis, E16 Stroke, E18 Unplanned ICU, E19 Unplanned Intubation), 17 gates total, 0 NTDS outcome deltas across 39 patients
> - Anesthesia SourceType: ✅ COMPLETE — ANESTHESIA_NOTE enum + `^\[?\s*ANESTHESIA[\s_]` parser pattern + E19/E20 rules wired, 12 tests added, 0 NTDS outcome deltas across 39 patients
> - Protocol coverage audit: ✅ COMPLETE (PR #175) — stale ROLE_OF_TRAUMA_SERVICES removed from index/validator/fixtures, 43 protocols synced, 0 NTDS outcome deltas
> - FLAG 002 E21 VAP vent gate: ✅ COMPLETE — required mechanical-ventilation gate added to E21 VAP rule, 7 vent_dx mapper patterns, history_noise exclusion, 1 fixture added, Cheryl_Burton YES→NO, 39-patient cohort verified
> - FLAG 001 Spinal 36 h timing: ✅ COMPLETE — REQ_REQUIRED_DATA_ELEMENTS + REQ_TIMING_CRITICAL (temporal:within:36:hours) added to spinal protocol, 12 surgery patterns in shared_action_buckets, 1 fixture added (spinal_timing_noncompliant), 1 fixture updated (spinal_compliant +surgery), 0 NTDS outcome deltas
> - Baseline hash coverage: ✅ COMPLETE — 39-patient NTDS event hash baseline + gate wiring + standalone checker, 0 NTDS outcome deltas
> - D4 DISCHARGE precision audit: ✅ COMPLETE — 14 events audited, 39 patients, 0 false positives, 1 TP (Ronald_Bittner E13 Pressure Ulcer), no rule changes needed, baseline realigned (Anna_Dennis hash), 0 NTDS outcome deltas
> - N3 residual precision pass (E08 DVT + E09 Delirium): ✅ COMPLETE — E09 `delirium_negation_noise` (10 patterns), 2 FP corrections (Barbara_Burgdorf YES→NO, Christine_Adelitzo YES→NO); E08 `dvt_dx_noise_prophylaxis` wired (defensive, 0 outcome changes); 2 NTDS outcome deltas
> - AKI UTD reduction v2: ✅ COMPLETE — 3 noise patterns + 1 onset pattern + arrival-time extraction in runner; 4 outcome deltas (Barbara_Burgdorf UTD→NO, Gary_Linder UTD→NO, William_Simmons UTD→NO, Floy_Geary UTD→YES); E01 UTD 7→3
> - Per-event distribution CI: ✅ COMPLETE — `scripts/check_ntds_distribution.py` + baseline (21 events × 39 patients), wired into `gate_pr.sh`, 0 NTDS outcome deltas
> - Source alignment + geri delirium design: ✅ COMPLETE (design doc) — 3-tier source recommendations, CAM/bCAM mapper gaps, shift compliance design, Ronald_Bittner follow-up; 0 NTDS outcome deltas
> - Tier 1 source alignment + CAM/bCAM patterns: ✅ COMPLETE — CONSULT_NOTE added to 4 gates (aki_dx, mi_dx, sepsis_dx, stroke_dx), NURSING_NOTE added to 3 gates (cauti_dx, clabsi_dx, sepsis_dx), 4 CAM-ICU/bCAM positive patterns to delirium_dx, 4 negative patterns to delirium_negation_noise, 3 fixtures added, 0 NTDS outcome deltas
> - E05 CAUTI Tier-1 spec fidelity (CDC SUTI 1a): ✅ COMPLETE — 5 required gates (cauti_dx, cauti_catheter_gt2d, cauti_symptoms, cauti_culture, cauti_after_arrival) + 2 exclusions (POA, chronic catheter); 6 new mapper keys (52 patterns total); cauti_dx expanded with UTI standalone + negation noise filter; 52 precision tests + 3 fixtures (YES, nursing-YES, no-catheter-NO); baseline refreshed: E05 NO=39→NO=35 EXCLUDED=4
> - Baseline refresh post-CAUTI v2: ✅ COMPLETE — 39-patient cohort rerun, hash + distribution baselines updated; E05 delta: NO=39→NO=35 EXCLUDED=4 (4 patients excluded by catheter/chronic gates); all other 20 events unchanged; 2313 tests passed, cohort invariant PASS, 0 drift
> - E05 CAUTI follow-up (culture/symptom variants): ✅ COMPLETE (PR #190) — symptoms 14→15 (adds altered mental status, temp regex 38–42°C); culture patterns 11→14 (1e5 CFU, spaced caret, ">100,000" forms); +13 precision tests; 0 NTDS deltas
> - E01 AKI Tier-2 spec fidelity (KDIGO Stage 3): ✅ COMPLETE — 3 gates (aki_dx tightened + ATN, aki_stage3 KDIGO OR criteria, aki_after_arrival enhanced onset) + 2 exclusions (POA, chronic RRT); 3 new mapper keys (aki_stage3_lab, aki_new_dialysis, aki_chronic_rrt); aki_onset 6→11 patterns; NURSING_NOTE + PROGRESS_NOTE added to all gates; 68 precision tests + 4 fixtures; 0 NTDS outcome deltas across 39 patients
> - E06 CLABSI spec fidelity (NHSN CLABSI): ✅ COMPLETE (PR #194) — 5 required gates + 2 exclusions, 7 mapper keys (~56 patterns), 76 precision tests + 3 new fixtures, 0 NTDS outcome deltas
> - E05/E06 duration-scope tightening: ✅ COMPLETE (PRs #195, #196, #198, #201) — duration patterns require explicit device mention; punctuation variant tests added
> - LDA engine design: ✅ COMPLETE (PR #202) — Lines/Drains/Airways device-duration engine design doc
> - LDA engine implementation (v1+text+startstop): ✅ COMPLETE (PRs #203, #206, #207) — LDAEpisode model, build_lda_episodes() builder (structured JSON + text day-counter + insertion/removal start/stop inference), 4 gate types incl. eval_lda_overlap, TEXT_DERIVED_STARTSTOP confidence level, ENABLE_LDA_GATES=False, 118 dedicated tests
> - Slice A (sex + discharge disposition): ✅ COMPLETE (PRs #222–#225) — `demographics_v1` feature module + contract doc
> - Slice B (blood product transfusion): ✅ COMPLETE (PRs #229–#231) — `transfusion_blood_products_v1` foundation + hardening
> - Slice C (structured labs foundation + expansion): ✅ COMPLETE (PRs #226–#228, #232) — CBC/BMP/coag/ABG/PF + cardiac/sepsis panels
> - Ventilator settings extraction: ✅ COMPLETE (PRs #233–#237) — FiO2/PEEP/Vt/RR/vent status, mode, NIV IPAP/EPAP/rate
> - GCS component extraction (E/V/M): ✅ COMPLETE (PRs #238–#239) — inline + flowsheet block parsing, sum-mismatch guard, compact-intubated fix
> - Tabular GCS flowsheet extraction: ✅ COMPLETE (PR #243) — deterministic tabular GCS flowsheet parsing
> - LDA per-event gate enablement: ✅ COMPLETE (PRs #244–#246) — E05 CAUTI, E06 CLABSI, E21 VAP LDA gates set `required: true`; per-event toggle in runner; protected engine.py not modified
> - Vent start/stop recall for E21 VAP: ✅ COMPLETE (PR #248) — citation-backed ventilator start/stop patterns (intubation/extubation, placed-on/removed-from ventilator), negated-phrase guards, NIV exclusion; 37 new LDA tests; 0 NTDS outcome deltas; protected engine.py not modified
> - Open PRs: none
> - .gitignore cleanup: ✅ COMPLETE — `_tmp_*`, `rules/deaconess/*.pdf`, `docs/handoffs/`, audit log added to `.gitignore`

> - E05 CAUTI duration-scope tightening: ✅ COMPLETE — duration gate requires explicit urinary device (foley/indwelling/urethral/urinary catheter) + duration ≥3d/>48h; `cauti_catheter_duration` (6 patterns); 65→89 E05 precision tests; 0 NTDS outcome deltas
> - **Backlog priority:** (1) Arrival vitals hardening (Primary Survey priority + ED fallback), (2) Tabular GCS flowsheet parsing follow-up, (3) CAUTI engine implementation (requires authorization) — see Roadmap §3
> - Handoff reminder: Every Claude handoff must include Codex post-handoff analysis (spec alignment, validation results, gaps/risks, next actions) plus a raw-data cross-check: compare raw NTDS/protocol sources vs current extraction and spot-check two patient raw `.txt` files (one questionable, one baseline) for capture accuracy.
> - **Standard PR workflow:** (1) Raw-data evidence first — scan ≥2 patient `.txt` files, record exact phrases before mapper/rule edits; (2) Pre-merge checklist: targeted pytest → full pytest → `audit_cohort_counts.py --check` → `check_ntds_hashes.py` → `check_ntds_distribution.py` → `git diff --check`; (3) Address all Copilot review comments before handoff; (4) Post-handoff analysis by Codex (spec alignment, validation, gaps/risks, next actions, 2-patient raw-data spot-check); (5) Post-merge: `git switch main && git pull --ff-only`, re-run hash + distribution checks.
>
> See Roadmap doc §3 for full backlog detail, N3 residuals, and N4 queue.

> **Dev-loop default:** use the 12-patient sentinel cohort for fast validation.
> Full 39-patient cohort runs only at the pre-merge gate (`./scripts/gate_pr.sh`).
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

## 10) Lean Review Mode (Default)

To reduce cycle time, use **lean mode** unless a high-risk condition exists.

Default lean sequence (one pass each):

1. Run `CEREBRALOS PREFLIGHT FIRST` once per cycle.
2. Run one scope check: `git diff --name-only origin/main...HEAD`.
3. Run one validation pass appropriate to scope (targeted tests and/or gate).
4. Run one final merge-readiness audit + command set.

Re-run checks only when one of these happens:

- Branch/PR state changes mid-cycle.
- Protected files are touched.
- Baseline/test output changes unexpectedly.
- Operator explicitly requests deep audit mode.

---

## 11) Branch Cleanup Status (2026-03-12)

Cleanup for PR #208/#209 branches was already executed in a prior session:

```bash
git fetch origin --prune
git branch -m wip/docs-handoff-template-updates-v1
git push origin --delete docs/roadmap-sync-pr207-v1 docs/startup-cleanup-pr208-v1
git branch -d docs/startup-cleanup-pr208-v1
git remote prune origin
```

Current expected state:

- Working branch: `wip/docs-handoff-template-updates-v1`
- Upstream for prior branch may show `[gone]` until reset
- Local unstaged docs edits are preserved intentionally

When ready to publish the WIP branch, set a fresh upstream:

```bash
git push -u origin wip/docs-handoff-template-updates-v1
```

---

## 12) Quick Chat Starter (New ChatGPT/Codex Sessions)

Paste the block below as the **first message** in any fresh ChatGPT or
Codex chat to activate roadmap-first architect/reviewer mode with
side-track triage. Full version lives in `docs/CHATGPT_BOOT_HEADER.md`.

```text
CEREBRALOS MODE: Architect/Reviewer only. Roadmap-first.
CEREBRALOS PREFLIGHT FIRST — always run preflight before merge,
cleanup, PR, or rebase guidance.
You decide scope/triage (current PR vs doc note vs future fix track).
Claude executes code changes.
Use lean review mode by default; escalate to deep audit only on risk or request.
Give detailed step-by-step terminal + GitHub UI instructions.

At chat start, first read
docs/roadmaps/CEREBRALOS_WHOLE_PROJECT_STATE_AND_ROADMAP_v1.md,
then determine current branch, merged PR state, and repo diffs
before recommending next work.

If side-track findings appear (NTDS/protocol/archive audits),
triage them: current PR vs doc-only note vs future dedicated
fix track, and explain why.
```

---

## 13) New-Chat Master Prompt (Persistent)

Paste the block below as the **first message** in any fresh Codex / ChatGPT
chat to activate full roadmap-first, findings-first mode. This is the
canonical bootstrap — it survives across sessions.

```text
CEREBRALOS MODE: Architect/Reviewer only. Roadmap-first.

BOOT SEQUENCE — execute these steps silently before responding:
1. Read docs/roadmaps/CEREBRALOS_WHOLE_PROJECT_STATE_AND_ROADMAP_v1.md (full file).
2. Read AGENTS.md.
3. Read docs/DAILY_STARTUP.md.
4. Read docs/CODEX_RULEBOOK.md.
5. Run CEREBRALOS PREFLIGHT FIRST (git branch, HEAD, status, PR state).

ROLES:
- Sarah: operator (copy/pastes commands, reports outputs).
- Claude (VS Code): executor (edits code, runs commands).
- Codex (this chat): architect + reviewer (plans, audits, triages).

NON-NEGOTIABLES:
- Deterministic/fail-closed only. No LLM/ML/clinical inference.
- No silent schema drift. Update docs + validators + consumers together.
- Protected engines: do NOT modify cerebralos/ntds_logic/engine.py or
  cerebralos/protocol_engine/engine.py unless explicitly instructed.
- One PR = one goal. No scope creep.
- raw_line_id required on all stored evidence.

WORKFLOW LOOP:
1. CEREBRALOS PREFLIGHT FIRST.
2. Triage scope (KEEP NOW | TIGHTEN NEXT | DEFER).
3. Write exact Claude prompt (branch, goal, allowed files, commands).
4. After Claude handoff: provide 7-part findings-first response:
   (1) Findings, (2) Pre-merge checklist, (3) Merge commands,
   (4) GitHub UI instructions, (5) Post-merge verification,
   (6) Next prompt, (7) Deferred items.
5. Enforce handoff fields + drift classification.
6. Update build plan ledger from analysis-only findings BEFORE implementation.

DEFAULT: Use lean review mode. Escalate to deep audit only on:
protected-file changes, unexpected baseline drift, mid-cycle state change,
or operator request.

COMPLETION GATE: ./scripts/gate_pr.sh must exit 0 before declaring done.
```

---

## 14) Analysis-Only Intake (Build Plan Required)

When Terminal-Claude runs analysis-only passes (no edits), Codex must:

1. Triage findings into `KEEP NOW`, `TIGHTEN NEXT`, and `DEFER`.
2. Explain deterministic/fail-closed rationale for all `KEEP NOW` items.
3. Require raw citations (`Patient_File:line`) before any pattern/gate proposal is accepted.
4. Update the build plan ledger in
   `docs/roadmaps/CEREBRALOS_WHOLE_PROJECT_STATE_AND_ROADMAP_v1.md`
   under the relevant backlog item before implementation starts.

Current LDA intake ledger:
- `Roadmap §3, Item 16A` (PR #214 correctness hardening intake)
- `Roadmap §3, Item 16B` (post-PR #214 raw-scan intake)
