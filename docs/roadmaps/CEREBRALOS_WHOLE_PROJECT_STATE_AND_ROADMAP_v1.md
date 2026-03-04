# CerebralOS — Whole-Project State and Roadmap v1

| Field       | Value                                                    |
|-------------|----------------------------------------------------------|
| Date        | 2026-03-04                                               |
| Baseline    | `2c1263d` (main, after PR #124)                          |
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

### Open PRs

None.

### Suite Health

| Metric              | Value            |
|---------------------|------------------|
| Total tests         | 2224             |
| NTDS event rules    | 21 (all mapped)  |
| Fixture files       | 43               |
| Fixture runner      | **43 passed, 0 xfailed** |
| Canonical patients  | 33               |
| Known flaky         | `test_ntds_runtime_wire_e2e::test_ntds_on_exit_zero` (intermittent, passes in isolation) |

### Engine Inventory

| Module                              | Lines | Protected | Notes                    |
|-------------------------------------|-------|-----------|--------------------------|
| `cerebralos/ntds_logic/engine.py`   | 645   | Yes       | proximity_mode audited on all 21 events |
| `cerebralos/protocol_engine/engine.py` | —  | Yes       | Not modified recently    |
| Mapper: `epic_deaconess_mapper_v1.json` | — | No        | Patterns for all 21 events |

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

#### N1 — Output Slug Normalization

| Item | Scope |
|------|-------|
| Normalize ingestion to always produce underscore slugs | `batch_eval.py`, `__main__.py` |
| Remove stale space-named duplicate output dirs | One-time cleanup |
| Add invariant check: output count == canonical count | Validation script |

#### N2 — Audit / Report Flow Integration

| Item | Scope |
|------|-------|
| Integrate sentinel + full cohort runs into `gate_pr.sh` | Script change |
| Automate NTDS outcome distribution check per event | CI/gate script |
| Baseline hash coverage for NTDS event outputs | `scripts/baselines/` |

#### N3 — Precision Tuning / False-Positive Audits

| Item | Scope |
|------|-------|
| Per-event false-positive audit across full 33-patient cohort | Manual review + fixture additions |
| Tighten patterns that overmatch (prophylaxis noise, negation leaks) | Rule JSON files |
| Expand fixture coverage for edge-case patients | `tests/fixtures/ntds/` |

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
