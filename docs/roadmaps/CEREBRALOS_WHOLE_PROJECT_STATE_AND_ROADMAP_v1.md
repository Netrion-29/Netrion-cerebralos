# CerebralOS — Whole-Project State and Roadmap v1

| Field       | Value                                                    |
|-------------|----------------------------------------------------------|
| Date        | 2026-03-03                                               |
| Baseline    | `693723a` (main, after PR #115)                          |
| Owner       | Sarah                                                    |
| Status      | Active — this is the primary context-recovery doc        |

---

## 1. Current State Snapshot

### Merged PRs (recent stack on main)

| PR   | Commit    | Title                                                        |
|------|-----------|--------------------------------------------------------------|
| #110 | `7d063cb` | feat: standardize --ntds CLI flag parity                     |
| #111 | `16a40b7` | fix(ntds): tighten osh_or mapper (transfer-only FP)          |
| #112 | `5032ff6` | feat(ntds): proximity_mode sentence_window for excl gates    |
| #113 | `ba108c8` | feat(ntds): extend proximity_mode to DVT/PE POA exclusions   |
| #114 | `19b1c4d` | feat(cli): CEREBRAL_NO_OPEN=1 for sandboxed runs             |
| #115 | `693723a` | feat(audit): canonical cohort count utility                  |

### Open PRs

| PR   | Branch                              | Status            |
|------|-------------------------------------|-------------------|
| #116 | `tier2/ntds-fixture-runner-v1`      | Open, checks pass |

PR #116 adds `tests/test_ntds_event_fixtures.py` (pytest-native runner for
all 43 fixture files).  22 pass, 21 xfail (mapper/parser gaps — see §4).

### Suite Health

| Metric              | Value            |
|---------------------|------------------|
| Total tests         | 2181 (+ 43 in #116) |
| Test files          | 57 (+ 1 in #116) |
| NTDS event rules    | 21               |
| Fixture files       | 43               |
| Canonical patients  | 33               |
| Known flaky         | `test_ntds_runtime_wire_e2e::test_ntds_on_exit_zero` (intermittent, passes in isolation) |

### Engine Inventory

| Module                              | Lines | Protected | Notes                    |
|-------------------------------------|-------|-----------|--------------------------|
| `cerebralos/ntds_logic/engine.py`   | 645   | Yes       | proximity_mode on 3/21   |
| `cerebralos/protocol_engine/engine.py` | —  | Yes       | Not modified recently    |
| Mapper: `epic_deaconess_mapper_v1.json` | — | No        | Patterns for events 08, 14, 20 only |

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

### Batch 0 — Reliability Baseline (IN PROGRESS)

| Item | Status | PR |
|------|--------|----|
| Pytest-native NTDS fixture runner (43 fixtures) | PR open | #116 |
| Scratch-file staging policy in README | PR open | #116 |
| Whole-project state + roadmap doc (this file) | This PR | — |
| Sentinel cohort validation policy | This PR | — |

### Batch 1 — Mapper + Parser Coverage

| Item | Scope |
|------|-------|
| Add mapper query-patterns for remaining 18 events | `epic_deaconess_mapper_v1.json` |
| Tolerate underscore section headers in parser | `build_patientfacts_from_txt.py` (`[\s_]+`) |
| Promote xfails → pass in fixture runner | Auto (strict=False xfails become XPASS) |

**Success gate:** All 43 fixtures pass (0 xfail).

### Batch 2 — Extended Proximity + Exclusion Quality

| Item | Scope |
|------|-------|
| Audit remaining events for proximity-eligible exclusion gates | Rule JSON files |
| Add `proximity_mode: sentence_window` to 2–4 high-ambiguity events | e.g. events 15, 10, 16 |
| Per-event targeted fixture tests | `tests/test_ntds_engine_proximity.py` |

### Batch 3 — Output Slug Normalization

| Item | Scope |
|------|-------|
| Normalize ingestion to always produce underscore slugs | `batch_eval.py`, `__main__.py` |
| Remove stale space-named duplicate output dirs | One-time cleanup |
| Add invariant check: output count == canonical count | Validation script |

### Batch 4 — Full Cohort CI Gate

| Item | Scope |
|------|-------|
| Integrate sentinel + full cohort runs into `gate_pr.sh` | Script change |
| Automate NTDS outcome distribution check per event | CI/gate script |
| Baseline hash coverage for NTDS event outputs | `scripts/baselines/` |

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
