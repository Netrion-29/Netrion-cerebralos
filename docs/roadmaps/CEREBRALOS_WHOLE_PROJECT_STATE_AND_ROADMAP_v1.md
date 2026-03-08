# CerebralOS — Whole-Project State and Roadmap v1

| Field       | Value                                                    |
|-------------|----------------------------------------------------------|
| Date        | 2026-03-07                                               |
| Baseline    | `b197cc2` (main, after PR #152)                          |
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
| #139 | `43f094d` | docs(roadmap): close out N3 precision phase — mark P1–P6 complete |
| #140 | `1156d7d` | docs(roadmap): fix N3 summary table inaccuracies |
| #141 | `c60ddf8` | feat(ntds): N4-P1 AKI UTD reduction — timing gate + onset patterns |
| #143 | `7ec0d45` | fix(parser): word-boundary anchors + block-words for source detection (N4-P2b) |
| #145 | `4e76301` | fix(parser): anchor DISCHARGE detection to line start (N5) |
| #147 | `8fe032d` | fix(parser): DISCHARGE first-word block logic — N6 residual false-flip hardening |
| #148 | `2231054` | docs(roadmap): record PR #147 completion — N6 DISCHARGE first-word block closeout |
| #149 | `1713e7a` | fix(parser): block residual DISCHARGE prose flips (N7) |
| #150 | `b742f82` | docs(roadmap): record PR #149 completion — N7 DISCHARGE prose residual cleanup closeout |
| #151 | `0866ca7` | docs(roadmap): record D1 full-cohort NTDS refresh completion |
| #152 | `b197cc2` | fix(parser): anchor IMAGING/RADIOLOGY/PROCEDURE detection to line start (D2) |

### Open PRs

None.

### Suite Health

| Metric              | Value            |
|---------------------|------------------|
| Total tests         | 2640 passed (pytest)  |
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

#### N4 — Parser & Recall Improvement (IN PROGRESS)

##### N4-P1 — AKI UTD Reduction ✅ COMPLETE (PR #141)

Added `aki_onset` timing patterns and `timing_after_arrival` gate to E01 rule.
Reduces UTD rate by detecting post-arrival AKI onset language.

##### N4-P2b — Parser Word-Boundary Fix ✅ COMPLETE (PR #143)

Anchored `_SECTION_PATTERNS` in `build_patientfacts_from_txt.py` with word
boundaries (`LAB` → `LABS?\b`, `MAR` → `MAR\b`) and added `_BLOCK_WORDS`
set for trailing-word rejection.

**Validated all-21 delta (8 changes, 0 regressions):**

| Change | Count | Patients | Classification |
|--------|-------|----------|----------------|
| YES→NO (FP eliminated) | 3 | E16 Larry_Corne, E16 Mary_King, E21 Ronald_Marshall | TP — validated, mapper hardened |
| NO→YES (TP gained) | 3 | E09 Dallas_Clark, E13 Ronald_Marshall, E21 Ronald_Bittner | TP — validated |
| UTD→NO (E01) | 1 | Margaret_Rudd | Correct — false LAB from prose "laboratory" eliminated |
| NO→UTD (E01) | 1 | William_Simmons | Correct — false MAR from "PRIMARY" eliminated |

##### N5 — DISCHARGE Source-Detection Hardening ✅ COMPLETE (PR #145)

Anchored the DISCHARGE section pattern in `_detect_source_type()` from bare
substring `r"DISCHARGE"` to line-start `r"^\[?\s*DISCHARGE"`. Eliminates 95%
of false DISCHARGE section flips caused by prose lines ("Problem: Discharge
Goals", "Barriers to Discharge", "EYES: No complaints of discharge", etc.).

**Validated all-21 delta (5 changes, 0 regressions):**

| Patient | Event | Old | New | Classification |
|---------|-------|-----|-----|----------------|
| Margaret_Rudd | E01 AKI | UTD | NO | Correction — false DISCHARGE evidence eliminated |
| William_Simmons | E01 AKI | NO | UTD | Correction — section cascade restored correct attribution |
| Larry_Corne | E16 Stroke | YES | NO | Correction — stroke_dx gate lost false DISCHARGE evidence |
| Mary_King | E16 Stroke | YES | NO | Correction — stroke_dx gate lost false DISCHARGE evidence |
| Ronald_Marshall | E21 VAP | YES | NO | Correction — vap_evidence gate lost false DISCHARGE evidence |

YES count: 17 → 14 (−3). All 5 deltas are corrections — outcomes were based on
evidence falsely attributed to DISCHARGE sections via substring matching.

##### N6 — DISCHARGE First-Word Block Logic ✅ COMPLETE (PR #147)

Changed `_BLOCK_WORDS` check from exact-match (`trailing in _BLOCK_WORDS`) to
first-word matching (`trailing.split()[0].rstrip(":.") in _DISCHARGE_BLOCK_FIRST_WORDS`),
scoped to DISCHARGE patterns only. Added expanded block words: PATIENTON,
RECOMMENDATIONS, MIM, /TRANSFER, COMMENTS, ASSESSMENT.

**Eliminates 109/118 residual DISCHARGE false flips (92%), 5,482/5,723
contaminated content lines (96%). 0 NTDS outcome deltas across all 33 patients
(693 events, YES 14→14).**

22 new tests added (admin-field rejection + true header preservation).

##### N7 — DISCHARGE Prose Residual Cleanup ✅ COMPLETE (PR #149)

Expanded `_DISCHARGE_BLOCK_FIRST_WORDS` with 7 additional block words
(AT, ORDERS, ORTHO, PENDING, PER, PT, TO) and added bare-period
trailing guard (`trailing == "."`) in both `_detect_source_type()` and
`_is_section_header()`. Eliminates **all 14 remaining false DISCHARGE
flips** (450 blast lines) across 8 patients.

**0 NTDS outcome deltas across all 33 patients (693 events, YES 14→14).**

18 new tests added (11 `_detect_source_type` rejections, 4
`_is_section_header` rejections, 3 preservation tests).

##### D1 — Full Cohort Output Refresh ✅ COMPLETE (operational, no code changes)

Refreshed all 33 patients' NTDS outputs to pick up parser fixes N5/N6/N7.
Executed on main after PR #150.

| Metric | Result |
|--------|--------|
| Patients refreshed | 33/33 |
| Pre/post all-21 distribution diff | **Empty — zero NTDS outcome deltas** |
| Cohort invariant | PASS (33 canonical, 33 adjusted, 0 extra, 0 missing) |
| Predicted flips (Gary_Linder E01, Ronald_Marshall E13) | Did NOT materialize |
| Tracked working tree | Clean |

The D1 scoping predicted 2 possible outcome flips (Gary_Linder E01 UTD→NO,
Ronald_Marshall E13 YES→NO) based on stale evidence analysis. Neither flip
occurred because the current parser + engine combination preserved gate
outcomes despite evidence source-type reclassification.

##### D2 — IMAGING/RADIOLOGY/PROCEDURE Line-Start Anchor ✅ COMPLETE (PR #152)

Anchored three section-detection patterns to line start (`^\[?\s*`) in
`build_patientfacts_from_txt.py`, matching the DISCHARGE anchor from N5:

| Pattern | Before | After |
|---------|--------|-------|
| IMAGING | `r"IMAGING"` | `r"^\[?\s*IMAGING"` |
| RADIOLOGY | `r"RADIOLOGY"` | `r"^\[?\s*RADIOLOGY"` |
| PROCEDURE | `r"PROCEDURE"` | `r"^\[?\s*PROCEDURE"` |

68 focused regression tests added covering true-header acceptance and
prose-mention rejection.

| Metric | Result |
|--------|--------|
| pytest source-detection | 112 passed |
| pytest event fixtures + cohort invariant | 68 passed |
| audit_cohort_counts --check | PASS (33/33) |
| A/B all-21 distribution | **0 NTDS outcome deltas** |

##### Remaining Queue (post-D2)

| Item | Scope | Priority |
|------|-------|----------|
| D3 — `\b` word-boundary on DISCHARGE regex for future-proofing | Parser hardening | Low |
| D4 — Precision audit across all 16 DISCHARGE-using events | Per-event evidence review | Medium |
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
