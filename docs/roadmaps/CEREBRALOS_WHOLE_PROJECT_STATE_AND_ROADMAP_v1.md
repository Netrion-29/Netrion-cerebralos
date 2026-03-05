# CerebralOS — Whole-Project State and Roadmap v1

| Field       | Value                                                    |
|-------------|----------------------------------------------------------|
| Date        | 2026-03-04                                               |
| Baseline    | `cd887ce` (main, after PR #138)                          |
| Owner       | Sarah                                                    |
| Status      | Active — this is the primary context-recovery doc        |

---

## 1. Current State Snapshot

### NTDS Coverage Milestone

> **21 / 21 NTDS events fully mapped.** All fixture tests pass (43 passed,
> 0 xfailed). Coverage completed across PRs #118 – #124 (Clusters A – E).

### Merged PRs (recent stack on main)

| PR   | Commit    | Title                                                        |
|------|-----------|--------------------------------------------------------------|
| #110 | `7d063cb` | feat: standardize --ntds CLI flag parity                     |
| #111 | `16a40b7` | fix(ntds): tighten osh_or mapper (transfer-only FP)          |
| #112 | `5032ff6` | feat(ntds): proximity_mode sentence_window for excl gates    |
| #113 | `ba108c8` | feat(ntds): extend proximity_mode to DVT/PE POA exclusions   |
| #114 | `19b1c4d` | feat(cli): CEREBRAL_NO_OPEN=1 for sandboxed runs             |
| #115 | `693723a` | feat(audit): canonical cohort count utility                  |
| #116 | `4d0be05` | test(ntds): add pytest-native fixture runner and scratch policy baseline |
| #117 | `bbc16ef` | docs(roadmap): add whole-project state, roadmap baseline, and sentinel cohort policy |
| #118 | `396e9e0` | feat(ntds): batch1 mapper coverage for cauti/delirium/pressure ulcer |
| #119 | `021e9e3` | fix(ntds): scope batch1 POA exclusions with event context and sentence-window proximity |
| #120 | `27c7b7b` | test(ntds): close 08/14 fixture timing gaps in pytest runner |
| #121 | `6a2a9e7` | feat(ntds): batch2 mapper coverage for mi/stroke/sepsis      |
| #122 | `2d188dd` | feat(ntds): Batch 3 coverage cluster C (01/02/18/19/21)      |
| #123 | `0962638` | feat(ntds): add mapper coverage for SSI cluster events 06/07/11/17 |
| #124 | `2c1263d` | feat(ntds): add mapper coverage for final events 03/04/12    |
| #125 | `b9066c2` | docs(roadmap): mark NTDS 21/21 coverage complete and define next-phase backlog |
| #126 | `e920d57` | docs(roadmap): fix PR #116-#124 hash table and date accuracy |
| #127 | `5713e1e` | feat(outputs): add safe slug-normalization utility with dry-run/apply modes |
| #128 | `b51f950` | fix(outputs): normalize NTDS slug names at output creation time |
| #129 | `5c4be91` | feat(gate): enforce canonical-vs-output cohort invariant |
| #130 | `9181423` | fix(gate): exclude _-prefixed admin dirs from cohort invariant audit |
| #131 | `55c8cc5` | feat(audit): embed cohort invariant summary in codex handoff |
| #132 | `b4911de` | fix(ntds): tighten event16 stroke/cva precision (N3-P1)  |
| #134 | `596bee7` | fix(ntds): tighten event10 MI precision (N3-P2)          |
| #135 | `259d4a4` | fix(ntds): tighten event19 unplanned intubation precision (N3-P3) |
| #136 | `3009584` | fix(ntds): tighten event15 severe sepsis precision (N3-P4) |
| #137 | `ddef507` | fix(ntds): tighten event18 unplanned ICU admission precision (N3-P5) |
| #138 | `cd887ce` | fix(ntds): tighten event01 AKI precision — reduce UTD rate (N3-P6) |

### Open PRs

None.

### Suite Health

| Metric              | Value            |
|---------------------|------------------|
| Total tests         | 2224 + 6 precision suites |
| NTDS event rules    | 21 (all mapped)  |
| Fixture files       | 43               |
| Fixture runner      | **43 passed, 0 xfailed** |
| Precision tests     | 6 suites (E01, E10, E15, E16, E18, E19) |
| Cohort invariant    | 33 canonical = 33 adjusted |
| Canonical patients  | 33               |
| Known flaky         | `test_ntds_runtime_wire_e2e::test_ntds_on_exit_zero` (intermittent, passes in isolation) |

### Engine Inventory

| Module                              | Lines | Protected | Notes                    |
|-------------------------------------|-------|-----------|--------------------------|
| `cerebralos/ntds_logic/engine.py`   | 645   | Yes       | proximity_mode audited on all 21 events; no changes in N3 |
| `cerebralos/protocol_engine/engine.py` | —  | Yes       | Not modified recently    |
| Mapper: `epic_deaconess_mapper_v1.json` | — | No        | Patterns for all 21 events + 6 negation noise buckets (N3) |

---

## 2. Canonical Cohort Counting Rules

**Ground truth:** `data_raw/*.txt` — currently **33 files = 33 patients**.

When counting output directories in `outputs/ntds/`:

1. **Exclude test-fixture directories** whose names start with a two-digit
   event prefix (e.g. `08_dvt_no`, `14_pe_yes`). Currently 4 such dirs.
2. **Exclude stale space-variant duplicates** — directories with spaces in
   the name that duplicate an underscore-normalized sibling (e.g.
   `Charlotte Howlett` when `Charlotte_Howlett` also exists). Currently 2.
3. After exclusions, **adjusted output count must equal canonical count (33)**.
4. Any discrepancy means either a new patient was added to `data_raw/`
   without a full cohort re-run, or a stale artifact was not cleaned up.
5. Always report both raw slug count and adjusted count in audits.

---

## 3. Approved Whole-Project Roadmap

**Strategy:** Coverage-First, Medium Batches.

Each batch is a single-goal PR (or small set of tightly scoped PRs).
Batches are sequenced so later work builds on earlier foundations.

### Batch 0 — Reliability Baseline ✅ COMPLETE

| Item | PR |
|------|----|
| Pytest-native NTDS fixture runner (43 fixtures) | #116 |
| Scratch-file staging policy in README | #116 |
| Whole-project state + roadmap doc (this file) | #116 |
| Sentinel cohort validation policy | #116 |

### Batch 1 — Mapper + Parser Coverage ✅ COMPLETE

| Item | PRs |
|------|-----|
| Add mapper query-patterns for remaining 18 events | #117, #118 |
| Tolerate underscore section headers in parser | #117 |
| Promote xfails → pass in fixture runner | #118 – #124 |

**Success gate achieved:** All 43 fixtures pass (0 xfail).

### Batch 2 — Extended Proximity + Exclusion Quality ✅ COMPLETE

| Item | PRs |
|------|-----|
| Audit all events for proximity-eligible exclusion gates | #118 – #124 |
| Add `proximity_mode: sentence_window` to high-ambiguity events | #112, #113, #118 – #124 |
| Per-event targeted fixture tests | #118 – #124 |

---

### What's Next — Post-Coverage Backlog

With NTDS coverage at 21/21, the following items define the next phase:

#### N1 — Output Slug Normalization ✅ COMPLETE (PRs #127, #128)

| Item | Scope | Status |
|------|-------|--------|
| Safe slug-normalization utility (dry-run + --apply) | `scripts/normalize_output_slugs.py` | ✅ PR #127 |
| Normalize ingestion to always produce underscore slugs | `batch_eval.py`, `__main__.py` | ✅ PR #128 |
| Add invariant check: output count == canonical count | `scripts/audit_cohort_counts.py` + gate | ✅ PR #129 |

#### N2 — Audit / Report Flow Integration — Phase 1 ✅ COMPLETE (PRs #129, #130, #131)

| Item | Scope | Status |
|------|-------|--------|
| Enforce canonical-vs-output cohort invariant in gate | `scripts/gate_pr.sh` | ✅ PR #129 |
| Exclude `_`-prefixed admin dirs from invariant audit | `scripts/audit_cohort_counts.py` | ✅ PR #130 |
| Embed cohort invariant summary in codex handoff artifact | `scripts/gate_pr.sh` | ✅ PR #131 |
| Automate NTDS outcome distribution check per event | CI/gate script | Planned |
| Baseline hash coverage for NTDS event outputs | `scripts/baselines/` | Planned |

#### N3 — Precision Tuning / False-Positive Audits ✅ COMPLETE (PRs #132–#138)

Six precision passes executed across the highest-impact NTDS events.
Each PR added a negation-noise bucket to the mapper, wired `exclude_noise_keys`
in the event rule, and added a dedicated precision test suite.

| Pass | Event | PR   | Mapper bucket            | Tests | Distribution shift |
|------|-------|------|--------------------------|-------|--------------------|
| N3-P1 | E16 Stroke/CVA           | #132 | `stroke_negation_noise` (11) | `test_e16_stroke_precision.py` | YES 14→2 |
| N3-P2 | E10 MI                   | #134 | `mi_negation_noise` (12)     | `test_e10_mi_precision.py`     | YES 6→1 |
| N3-P3 | E19 Unplanned Intubation | #135 | `intubation_negation_noise` (15) | `test_e19_unplanned_intubation_precision.py` | YES 5→2 |
| N3-P4 | E15 Severe Sepsis        | #136 | `sepsis_negation_noise` (13) | `test_e15_severe_sepsis_precision.py` | YES 2→1 |
| N3-P5 | E18 Unplanned ICU        | #137 | `icu_negation_noise` (11)    | `test_e18_unplanned_icu_precision.py` | YES 2→1 |
| N3-P6 | E01 AKI                  | #138 | `aki_negation_noise` (12)    | `test_e01_aki_precision.py`    | UTD 7→5, NO 26→28 |

**Zero engine changes across all six passes.** All changes are mapper patterns + rule JSON wiring.

##### N3 Residuals / Known Deferred Items

| Item | Events | Reason deferred |
|------|--------|------------------|
| 5 AKI patients remain UNABLE_TO_DETERMINE | E01 | Genuine AKI evidence but no explicit onset-after-arrival language; resolving requires broadened `aki_onset` patterns (FP risk) or lab-trend inference (engine change) |
| Gary_Linder AKI lab hits not filterable | E01 | LAB/DISCHARGE "AKI (acute kidney injury)" entries lack PMH context in the same line; noise pattern can't distinguish from active diagnosis |
| Remaining precision noise in other 15 events | E02–E09, E11–E14, E17, E20–E21 | Not audited in N3; lower cohort impact; queue for future N4 pass |

#### N4 — Next Phase Queue (PLANNED)

| Item | Scope | Priority |
|------|-------|----------|
| Recall improvement: broaden `aki_onset` timing patterns safely | E01 rule + mapper | High |
| PMH-aware gate handling: allow engine to filter PMH context across non-adjacent lines | Engine proposal (protected) | Medium |
| Precision audit pass for remaining 15 events | Per-event mapper/rule/tests | Medium |
| Automate NTDS outcome distribution check per event | CI/gate script | Low |
| Baseline hash coverage for NTDS event outputs | `scripts/baselines/` | Low |

---

## 4. Fast Validation Policy (Sentinel vs Full Cohort)

### Sentinel Cohort (12 patients)

These patients are selected for diversity of clinical content, edge
cases, and coverage of the 3 mapped NTDS events (DVT, PE, OR Return):

```
Anna_Dennis
Carlton_Van_Ness
Charlotte_Howlett
David_Gross
Mary_King
Michael_Dougan
Robert_Sauer
Ronald_Bittner
Timothy_Cowan
Timothy_Nachtwey
Valerie_Parker
Lolita_Calcia
```

### Execution Rules

| Gate                          | Cohort   | When                           |
|-------------------------------|----------|--------------------------------|
| **Every PR (dev loop)**       | Sentinel | After each meaningful change   |
| **Pre-merge / final gate**   | Full 33  | Before merge to main           |

**Dev-loop sentinel run:**
```bash
for PAT in Anna_Dennis Carlton_Van_Ness Charlotte_Howlett David_Gross \
  Mary_King Michael_Dougan Robert_Sauer Ronald_Bittner \
  Timothy_Cowan Timothy_Nachtwey Valerie_Parker Lolita_Calcia; do
  ./run_patient.sh "$PAT"
done
```

**Pre-merge full run:**
```bash
./scripts/gate_pr.sh
```

The sentinel cohort is a speed optimization (12/33 = 36% of patients).
It does NOT replace the full gate — it accelerates the inner dev loop.

---

## 5. Execution Protocol for New Chats

When starting a new ChatGPT, Codex, or Claude session for this repo:

1. **Read this file first** (`docs/roadmaps/CEREBRALOS_WHOLE_PROJECT_STATE_AND_ROADMAP_v1.md`).
2. **Read `AGENTS.md`** for non-negotiable constraints.
3. **Run preflight:**
   ```bash
   cd ~/NetrionSystems/netrion-cerebralos
   git branch --show-current
   git rev-parse --short HEAD
   git status --short
   gh pr status || echo "GH_STATUS:UNAVAILABLE"
   ```
4. **Identify the current batch and next item** from §3 above.
5. **Create a single-goal PR** — one branch, one purpose, one commit message.
6. **Use sentinel cohort** for dev-loop validation; **full cohort** only at pre-merge gate.
7. **Never stage** `_tmp_*`, `docs/handoffs/`, `tests/test_negation.py`, `tests/test_ntds_events.py`, `tests/test_ntds_simple.py`.

---

## 6. Key References

| Doc | Purpose |
|-----|---------|
| `AGENTS.md` | Non-negotiable constraints, roles, locked contracts |
| `docs/DAILY_STARTUP.md` | Daily startup checklist, gate commands |
| `docs/CHATGPT_BOOT_HEADER.md` | ChatGPT/Codex session bootstrap |
| `docs/roadmaps/TRAUMA_BUILD_FORWARD_PLAN_v1.md` | Original build-forward plan (historical) |
| `README.md` | Repo overview + scratch policy |

---

_End of document._
