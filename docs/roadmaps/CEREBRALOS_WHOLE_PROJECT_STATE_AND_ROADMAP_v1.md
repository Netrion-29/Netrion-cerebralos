# CerebralOS — Whole-Project State and Roadmap v1

| Field       | Value                                                    |
|-------------|----------------------------------------------------------|
| Date        | 2026-03-17                                               |
| Baseline    | `9266f3c` (main, after PR #250)                          |
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
| #153 | `f99c297` | docs(roadmap): record D2 parser anchor completion |
| #154 | `8fe7bbe` | fix(parser): anchor LAB and MAR detection to line start (D5) |
| #155 | `d7fda62` | docs(roadmap): record D5 LAB/MAR anchor completion |
| #156 | `56a67c5` | fix(parser): anchor MEDICATION_ADMIN and ED_NOTE detection to line start (D6-P1) |
| #157 | `be0f4a6` | docs(roadmap): record D6-P1 MEDICATION_ADMIN/ED_NOTE anchor completion |
| #158 | `ac31ac0` | fix(parser): anchor PHYSICIAN_NOTE detection to line start (D6-P2) |
| #161 | — | fix(parser): anchor NURSING_NOTE detection to line start (D6-P3) |
| — | — | fix(parser): block prose-only CONSULT_NOTE false matches (D6-P4) |
| — | — | fix(parser): harden EMERGENCY source detection (D6-P5) |
| — | — | fix(parser): compound-prefix anchor for OPERATIVE_NOTE (D6-P6) |
| — | — | fix(parser): compound-prefix anchor for PROGRESS_NOTE (D6-P7) |
| #173 | — | feat(ntds): add ED_NOTE to 12 NTDS event allowed_sources |
| #174 | `e5426d5` | feat(ntds): add ANESTHESIA_NOTE SourceType + wire E19/E20 |
| #175 | `3215247` | fix(protocols): remove stale ROLE_OF_TRAUMA_SERVICES artifacts |
| #184 | `b6dffbc` | fix(ntds): AKI UTD reduction v2 — noise + onset + arrival-time extraction |
| #185 | `80d61da` | feat(gate): per-event NTDS distribution baseline + CI check |
| #186 | `ee214d9` | docs(design): source alignment + geriatric delirium nursing shift design v1 |
| #187 | `8030ee6` | feat(ntds): Tier 1 source alignment + CAM/bCAM delirium patterns |
| #188 | `b3757cc` | feat(E05): CAUTI Tier-1 spec fidelity — CDC SUTI 1a gates |
| #189 | `7f004b4` | chore(baselines): refresh NTDS hashes + distribution post-CAUTI v2 |
| #190 | `8a51e35` | feat(E05): CAUTI follow-up — culture/symptom pattern coverage hardening |
| #191 | `d9aec71` | docs(design): CAUTI engine design — LDA duration gate + alternative-source exclusion |
| #192 | `af4fd74` | feat(E01): AKI Tier-2 spec fidelity — KDIGO Stage 3 gates + chronic-RRT exclusion |
| #193 | `2cea25c` | chore: ignore tmp scratch files, protocol PDFs, and handoff artifacts |
| #194 | `adb1eb2` | feat(E06): CLABSI spec fidelity — multi-gate NHSN criteria |
| #195 | `385d896` | fix(E06): enforce >2d central line duration; doc formatting |
| #196 | `c3efd5a` | fix(E06): require central-line mention in duration patterns |
| #197 | `a34a63d` | docs: add raw-.txt and post-handoff workflow to build plan |
| #198 | `e52dc7a` | test(E06): punctuation variant tests for CLABSI duration patterns |
| #199 | `0de081e` | docs: add protocol data element master list and backlog hook |
| #200 | `d0b7f5c` | docs: add protocol data coverage scaffold |
| #201 | `7c8d37f` | fix(E05): require urinary catheter mention in CAUTI duration patterns |
| #202 | `b75bd0d` | docs: LDA engine design for device duration (Lines/Drains/Airways) |
| #203 | `27da1f2` | feat(engine): add LDA device duration gates (Foley/central line/vent) |
| #205 | `1e6777b` | docs: fill protocol data coverage status (doc-only) |
| #206 | `5659d46` | feat(engine): add text-derived LDA episodes from flowsheet day counters |
| #207 | `4774b74` | feat(ntds): infer LDA start/stop episodes and calendar-day durations |
| #208 | `b3f3e2f` | docs: sync roadmap and startup docs for merged PR #207 (LDA start/stop inference) |
| #209 | `cf23cad` | docs: revert PR208 template additions and dedupe E06 status |
| #210 | `cf23cad` | docs: tighten DAILY_STARTUP scope after PR #208 merge        |
| #211 | `eb53813` | docs: add lean review mode and record completed branch cleanup |
| #212 | `5180887` | docs: align handoff template reminders in boot header and claude rulebook |
| #213 | `6f62b37` | chore: add pre-commit config for local guardrails            |
| #214 | `8224bb1` | fix(lda): correctness hardening — overlap semantics, merge backfill, chest tube + drain patterns |
| #215 | `64781e5` | docs(roadmap): add LDA intake loop and post-PR214 intake ledger |
| #216 | `156c86f` | fix(lda): add [REMOVED] bracket patterns for Urethral Catheter and Non-Surgical Airway |
| #217 | `156c86f` | docs(roadmap): add LDA intake loop and post-PR214 intake ledger (re-merge) — same commit as #216; docs branch rebased onto LDA code commit before re-merge |
| #218 | `85f06c7` | docs(roadmap): sync merged state through PR #217 — add PRs #208-#217, fix stale refs |
| #219 | `29754bd` | docs(process): persist codex operating contract and new-chat master prompt |
| #220 | `a0866ce` | docs(protocol): add first-pass protocol data coverage mapping matrix — `docs/audits/PROTOCOL_DATA_COVERAGE_MAPPING_v1.md` |
| #221 | `9dcff65` | docs(roadmap): sync post-PR220 protocol coverage kickoff status |
| #222 | `f9aa6ec` | docs(protocol): add slice A raw-evidence plan for sex and discharge disposition extraction |
| #223 | `185bab8` | feat(protocol): implement Slice A sex + discharge disposition extraction |
| #224 | `91feb58` | chore(protocol): address PR223 review comments and add demographics_v1 contract doc |
| #225 | `58c8ce2` | docs(contract): make demographics_v1 schema example JSON-valid |
| #226 | `4460dec` | feat(protocol): slice C structured labs foundation (cbc/bmp/coag/abg + pf support) |
| #227 | `120e800` | fix(protocol): align structured_labs FiO2 behavior and add contract enforcement |
| #228 | `5f8ba54` | fix(protocol): resolve PR227 copilot comments on schema JSON and candidate fallback |
| #229 | `a5cbde3` | feat(protocol): Slice B transfusion/blood product extraction foundation (pRBC, FFP, platelets, TXA, MTP) |
| #230 | `5b04e4e` | fix(protocol): resolve PR229 copilot review comments for transfusion extraction |
| #231 | `21d9a91` | fix(protocol): harden Slice B transfusion extraction with newer-format raw evidence |
| #232 | `1ac5db9` | feat(protocol): expand Slice C structured lab coverage with cardiac and sepsis panels |
| #233 | `3455a76` | feat(protocol): ventilator settings extraction foundation (FiO2/PEEP/Vt/RR/vent status) |
| #234 | `bc2517a` | feat(protocol): add deterministic ventilator mode extraction |
| #235 | `1784a09` | feat(protocol): add deterministic NIV IPAP/EPAP extraction |
| #236 | `83080af` | feat(protocol): add deterministic NIV backup-rate extraction |
| #237 | `e079dbd` | fix(protocol): tighten NIV rate FP guard and align docs/tests |
| #238 | `e03eb95` | feat(protocol): add deterministic GCS E/V/M component extraction in gcs_daily |
| #239 | `3a6f05f` | fix(protocol): resolve PR238 copilot findings for gcs components |
| #243 | `40e6984` | feat(protocol): add deterministic tabular GCS flowsheet extraction |
| #244 | `ca810ca` | feat(ntds): enable E05 CAUTI LDA gate |
| #245 | `869b818` | feat(ntds): enable E06 CLABSI LDA gate |
| #246 | `63c9789` | feat(ntds): enable E21 VAP LDA gate |
| #247 | `7ce70de` | docs(roadmap): sync status after LDA per-event rollout |
| #248 | `15899ec` | feat(lda): improve vent start/stop episode extraction for E21 recall |
| #249 | `ee38274` | docs(roadmap): sync status after PR #248 vent start/stop recall merge |
| #250 | `aaa00ee` | feat(lda): multi-episode start/stop support for MECHANICAL_VENTILATOR and ENDOTRACHEAL_TUBE |

### Closed PRs

| PR | Notes |
|----|-------|
| #142 | Closed as stale (N4-P2 source detection); superseded by D6 parser hardening (P1–P7), branch conflicting |
| #204 | Closed — superseded by PR #205 (protocol data coverage fill, doc-only) |

### Open PRs

None.

### Suite Health

| Metric              | Value            |
|---------------------|------------------|
| Total tests         | last verified: ≥3616 passed (pytest, 2026-03-17, baseline `9266f3c`; lower bound, exact total may vary across environments) |
| NTDS event rules    | 21 (all mapped)  |
| Fixture files       | 47               |
| Fixture runner      | **56 passed, 0 xfailed** |
| Precision tests     | 10 suites (E01×2, E05, E06, E10, E15, E16, E18, E19, E21) |
| Cohort invariant    | 39 canonical = 39 adjusted |
| NTDS distribution   | 21 events baselined (YES/NO/UTD/EXCLUDED per event) |
| Canonical patients  | 39               |
| Known flaky         | `test_ntds_runtime_wire_e2e::test_ntds_on_exit_zero` (intermittent, passes in isolation) |
| .gitignore cleanup   | ✅ `_tmp_*`, `rules/deaconess/*.pdf`, `docs/handoffs/`, audit log — status noise reduced |

### Engine Inventory

| Module                              | Lines | Protected | Notes                    |
|-------------------------------------|-------|-----------|--------------------------|
| `cerebralos/ntds_logic/engine.py`   | 870   | Yes       | proximity_mode audited on all 21 events; LDA gate types added (PR #203/#207); `ENABLE_LDA_GATES` default False; per-event LDA gates enabled for E05/E06/E21 in runner (PRs #244–#246) — engine.py not modified |
| `cerebralos/protocol_engine/engine.py` | —  | Yes       | Not modified recently    |
| Mapper: `epic_deaconess_mapper_v1.json` | — | No        | Patterns for all 21 events + 7 negation noise buckets (N3 + CLABSI) |

---

## 2. Canonical Cohort Counting Rules

**Ground truth:** `data_raw/*.txt` — currently **39 files = 39 patients**.

When counting output directories in `outputs/ntds/`:

1. **Exclude test-fixture directories** whose names start with a two-digit
   event prefix (e.g. `08_dvt_no`, `14_pe_yes`). Currently 4 such dirs.
2. **Exclude stale space-variant duplicates** — directories with spaces in
   the name that duplicate an underscore-normalized sibling (e.g.
   `Charlotte Howlett` when `Charlotte_Howlett` also exists). Currently 0
   (prior duplicates archived to `_stale_space_dups_20260304_172106`).
3. **Exclude admin directories** whose names start with `_` (archives,
   stale backups). Currently 1 (`_stale_space_dups_20260304_172106`).
4. After exclusions, **adjusted output count must equal canonical count (39)**.
5. Any discrepancy means either a new patient was added to `data_raw/`
   without a full cohort re-run, or a stale artifact was not cleaned up.
6. Always report both raw slug count and adjusted count in audits.

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
| Automate NTDS outcome distribution check per event | `scripts/check_ntds_distribution.py`, `scripts/baselines/ntds_distribution_v1.json`, `scripts/gate_pr.sh` | ✅ COMPLETE |
| ~~Baseline hash coverage for NTDS event outputs~~ | ~~`scripts/baselines/`~~ | **✅ COMPLETE** — 39-patient composite hash baseline in `ntds_hashes_v1.json`, standalone `scripts/check_ntds_hashes.py` checker, wired into `gate_pr.sh` NTDS drift check |

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

##### D5 — LAB/MAR Line-Start Anchor ✅ COMPLETE (PR #154)

Anchored two section-detection patterns to line start (`^\[?\s*`) in
`build_patientfacts_from_txt.py`, matching the D2 anchor approach:

| Pattern | Before | After |
|---------|--------|-------|
| LAB | `r"LABS?\b"` | `r"^\[?\s*LABS?\b"` |
| MAR | `r"MAR\b"` | `r"^\[?\s*MAR\b"` |

D5 scoping found 3,017 mid-line LAB false matches across all 33 patients
and 144 mid-line MAR false matches across 12 patients. Top false triggers:
"Recent Labs" (1,397×), "Print Lab Result Report" (251×), physician name
"Kumar, Anup, MD" matching MAR\b (36×).

2 focused tests added (`test_recent_labs_reviewed_rejected_when_not_header`,
`test_kumar_name_not_treated_as_mar_header`).

| Metric | Result |
|--------|--------|
| pytest source-detection | 114 passed |
| Branch-vs-main all-21 distribution | **0 NTDS outcome deltas** |

##### D6-P1 — MEDICATION_ADMIN / ED_NOTE Line-Start Anchor ✅ COMPLETE (PR #156)

Anchored two section-detection patterns to line start (`^\[?\s*`) in
`build_patientfacts_from_txt.py`, matching the D2/D5 anchor approach:

| Pattern | Before | After |
|---------|--------|-------|
| MEDICATION_ADMIN | `r"MEDICATION[\s_]+ADMIN"` | `r"^\[?\s*MEDICATION[\s_]+ADMIN"` |
| ED_NOTE | `r"ED[\s_]+NOTE"` | `r"^\[?\s*ED[\s_]+NOTE"` |

D6 scoping found 3 mid-line MEDICATION_ADMIN false matches (1 NTDS gate:
E08 DVT `dvt_treated`) and 728 mid-line ED_NOTE false matches (0 NTDS gates).

11 focused tests added (5 MEDICATION_ADMIN, 6 ED_NOTE).

| Metric | Result |
|--------|--------|
| pytest source-detection | 125 passed |
| pytest event fixtures + cohort invariant | 68 passed |
| audit_cohort_counts --check | PASS (33/33) |
| A/B all-21 distribution | **0 NTDS outcome deltas** |

##### D6-P2 — PHYSICIAN_NOTE Line-Start Anchor ✅ COMPLETE (PR #158)

Anchored the PHYSICIAN_NOTE section-detection pattern to line start (`^\[?\s*`)
in `build_patientfacts_from_txt.py`, matching the D2/D5/D6-P1 anchor approach:

| Pattern | Before | After |
|---------|--------|-------|
| PHYSICIAN_NOTE | `r"PHYSICIAN[\s_]+NOTE"` | `r"^\[?\s*PHYSICIAN[\s_]+NOTE"` |

D6-P2 scoping found 1,148 total hits: 1,145 line-start bracket headers
(`[PHYSICIAN_NOTE]`) and 3 mid-line noise hits across 3 patients. All 3
noise lines are "DEACONESS HEALTH SYSTEM EMERGENCY [DEPARTMENT] PHYSICIAN
NOTE" headers that correctly reclassify from PHYSICIAN_NOTE → ED_NOTE
(via EMERGENCY fallback). 645 content lines across 3 patients change section
assignment.

**Note:** ED_NOTE was absent from all 21 NTDS `allowed_sources` lists (now resolved — see ED_NOTE `allowed_sources` gap closure in Remaining Queue).
ED_NOTE added to 12/21 events (17 gates). Zero NTDS outcome deltas across 39 patients confirmed;
all affected evidence is near-miss on NO-outcome events only.

6 focused tests added (4 acceptance + 2 mid-line rejection).

| Metric | Result |
|--------|--------|
| pytest source-detection | 131 passed |
| pytest event fixtures + cohort invariant | 68 passed |
| audit_cohort_counts --check | PASS (33/33) |
| A/B all-21 distribution (33 patients re-run) | **0 NTDS outcome deltas** |

##### D6-P3 — NURSING_NOTE Line-Start Anchor ✅ COMPLETE (PR #159)

Anchored the NURSING_NOTE section-detection pattern to line start (`^\[?\s*`)
in `build_patientfacts_from_txt.py`, matching the D2/D5/D6-P1/D6-P2 anchor
approach. Also widened E09 Delirium `allowed_sources` to include CONSULT_NOTE
to preserve clinically correct Barbara_Burgdorf E09 detection after section
reclassification.

| Pattern | Before | After |
|---------|--------|-------|
| NURSING_NOTE | `r"NURSING[\s_]+NOTE"` | `r"^\[?\s*NURSING[\s_]+NOTE"` |

D6-P3 scoping found 268 total hits across 29/33 patients: 248 line-start
(92.5%) and 20 mid-line noise (7.5%). All 20 noise triggers are prose
references ("Vitals and nursing note reviewed.", "Triage vitals and nursing
note reviewed.", etc.) that falsely re-entered NURSING_NOTE from other
sections. 15 patients, 2,034 content lines reclassified to correct parent
sections (PHYSICIAN_NOTE, CONSULT_NOTE, PROCEDURE, IMAGING, ED_NOTE, etc.).

Barbara_Burgdorf E09 Delirium had 3 passing NURSING_NOTE evidence lines in a
diff zone that reclassified NURSING_NOTE → CONSULT_NOTE (the content is
genuinely a hospitalist consult note). Adding CONSULT_NOTE to E09
`allowed_sources` preserves the clinically correct YES outcome.

8 focused source-detection tests added + 1 E09 CONSULT_NOTE fixture.

| Metric | Result |
|--------|--------|
| pytest source-detection | 139 passed |
| pytest event fixtures | 44 passed |
| pytest cohort invariant | 25 passed |
| audit_cohort_counts --check | PASS (33/33) |
| A/B all-21 distribution (33 patients re-run) | **0 NTDS outcome deltas** |


##### D6-P4 — CONSULT_NOTE prose-before block filter

**Problem:** The `CONSULT[\s_]+NOTE` pattern in `_SECTION_PATTERNS` had no `^` anchor
(unlike PHYSICIAN_NOTE, NURSING_NOTE, etc.). This caused 75 mid-line matches, of
which 49 were clinical prose — not section headers. 42 of these false triggers
actually changed parser state, misattributing 2,060 lines of clinical data across
10 patients (PROGRESS_NOTE/IMAGING → CONSULT_NOTE).

**Design:** A bare `^` anchor was rejected because it would drop all 26 legitimate
specialty sub-headers ("Ortho Consult Note", "Cardiac Electrophysiology Consult Note",
etc.). Instead, a `_CONSULT_PROSE_BEFORE` regex constant blocks lines where text
before "CONSULT NOTE" contains prose indicators (`from`, `see`, `per`, `refer`,
`history of`, `HPI from`, `please see`, `this note will`, `score is`, `*Refer`).

**Files changed:**
- `cerebralos/ntds_logic/build_patientfacts_from_txt.py` — added `_CONSULT_PROSE_BEFORE` constant; added before-text block in `_detect_source_type()` and `_is_section_header()`
- `tests/test_build_patientfacts_source_detection.py` — 25 new tests (13 sub-header preservation + 9 prose rejection + 3 `_is_section_header` consistency)

| Metric | Result |
|--------|--------|
| pytest source-detection | 163 passed |
| pytest event fixtures | 44 passed |
| pytest cohort invariant | 25 passed |
| Full cohort re-run (34 patients) | **0 NTDS outcome deltas** |
| Mid-line false triggers eliminated | 49 |
| Legitimate sub-headers preserved | 26/26 |


##### D6-P5 — EMERGENCY source-detection hardening

**Problem:** The bare `EMERGENCY` pattern in `_SECTION_PATTERNS` had no anchor
and no word-boundary constraint. It matched the substring "EMERGENCY" anywhere
in a line, triggering 464 mid-line false matches across 33 of 34 patients.
172 of these actually changed parser state, misattributing 20,850 lines of
clinical data (PROGRESS_NOTE/LAB/PROCEDURE/IMAGING → ED_NOTE). The biggest
offenders were ADT event lines (`EMERGENCY DEPT MC`), admin fields
(`Patient Class: Emergency`, `Specialty: Emergency Medicine`), and clinical
prose (`performed in the Emergency Department`).

**Design:** Replaced `r"EMERGENCY"` with `r"EMERGENCY[\s_]+(?:DEPARTMENT|DEPT)"`
and added two block filters:
1. **Trailing-word whitelist** (`_EMERGENCY_DEPT_ALLOW_AFTER`): only `NOTE` and
   `ENCOUNTER` are allowed as the first word after DEPARTMENT/DEPT. Everything
   else (MC, dates, clinical prose) is rejected.
2. **Before-text prose filter** (`_EMERGENCY_PROSE_BEFORE`): blocks when text
   before the match contains `in`, `from`, `performed`, `results`, `closed`.

**Files changed:**
- `cerebralos/ntds_logic/build_patientfacts_from_txt.py` — tightened EMERGENCY pattern; added `_EMERGENCY_DEPT_ALLOW_AFTER` and `_EMERGENCY_PROSE_BEFORE` constants; added block logic in `_detect_source_type()` and `_is_section_header()`
- `tests/test_build_patientfacts_source_detection.py` — 18 new tests (5 header preservation + 10 noise rejection + 3 `_is_section_header` consistency)

| Metric | Result |
|--------|--------|
| pytest source-detection | 181 passed |
| pytest event fixtures | 44 passed |
| pytest cohort invariant | 25 passed |
| Full cohort re-run (34 patients) | **0 NTDS outcome deltas** |
| NTDS output files compared | 760/760 identical |
| Mid-line false triggers eliminated | 464 |
| Legitimate ED headers preserved | "Emergency Department [Encounter] Note", "ED NOTE" |


##### Remaining Queue (post-D6-P5)

| Item | Scope | Priority |
|------|-------|----------|
| ~~D3 — `\b` word-boundary on DISCHARGE regex~~ | ~~Parser hardening~~ | **CLOSED (won't do)** — `\b` after PROCEDURE breaks 262 legitimate "Procedures:" plural headers; DISCHARGE/IMAGING/RADIOLOGY `\b` = zero practical impact |
| D4 — Precision audit across all 16 DISCHARGE-using events | Per-event evidence review | Medium |
| ~~D6-P2 — PHYSICIAN_NOTE line-start anchor~~ | ~~Parser hardening~~ | **✅ COMPLETE (PR #158)** — 1 pattern anchored, 6 tests added, 0 NTDS outcome deltas |
| ~~D6-P3 — NURSING_NOTE line-start anchor~~ | ~~Parser hardening~~ | **✅ COMPLETE (PR #159)** — 1 pattern anchored + E09 rule widened, 9 tests added, 0 NTDS outcome deltas |
| ~~D6-P4 — CONSULT_NOTE prose-before block~~ | ~~Parser hardening~~ | **✅ COMPLETE** — prose-before filter added, 49 false triggers eliminated, 26 sub-headers preserved, 25 tests added, 0 NTDS outcome deltas |
| D6-P5 — EMERGENCY anchor | ~~Parser hardening — 420/424 prose noise but 4 legitimate headers need block-word approach~~ | **✅ COMPLETE** — pattern tightened to EMERGENCY DEPT/DEPARTMENT + trailing whitelist + prose-before filter, 464 false triggers eliminated, 18 tests added, 0 NTDS outcome deltas |
| ~~D6-P6 — OPERATIVE_NOTE anchor~~ | ~~Parser hardening — "Brief Operative Note" regression risk; needs design~~ | **✅ COMPLETE** — compound-prefix anchor, 3860 false triggers eliminated, 14 tests added, 0 NTDS outcome deltas |
| ~~OP_NOTE — NO-GO~~ | ~~92% (45/49) prose hits are legitimate POSTOP/Post-Op sub-headers — simple anchoring would break them~~ | **RESOLVED by D6-P6** — compound-prefix design preserves POSTOP/Brief Operative sub-headers |
| ~~PROGRESS_NOTE — NO-GO~~ | ~~~67% (450/667) prose hits are legitimate sub-headers ("Hospital Progress Note", "Trauma Progress Note")~~ | **RESOLVED by D6-P7** — compound-prefix anchor with 20 specialty prefixes, 308 false triggers eliminated, 438 sub-headers preserved, 13 tests added, 0 NTDS outcome deltas |
| ~~ED_NOTE `allowed_sources` gap~~ | ~~ED_NOTE absent from all 21 NTDS rule `allowed_sources` lists~~ | **✅ COMPLETE** — ED_NOTE added to 12/21 events (17 gates across E01, E02, E03, E04, E08, E09, E10, E14, E15, E16, E18, E19), 0 NTDS outcome deltas across 39 patients. 9 events excluded (CAUTI, CLABSI, Deep SSI, Osteomyelitis, Pressure Ulcer, Superficial SSI, OR Return, VAP — hospital-acquired/surgical, ED evidence not clinically relevant) |
| ~~Anesthesia SourceType~~ | ~~New SourceType for anesthesia post-op/follow-up notes~~ | **✅ COMPLETE** — ANESTHESIA_NOTE enum added to NTDS + protocol engine models, `^\[?\s*ANESTHESIA[\s_]` parser pattern, E19 Unplanned Intubation + E20 OR Return rules wired, 12 tests added, 0 NTDS outcome deltas across 39 patients |
| ~~Protocol coverage audit~~ | ~~Sync index/validator/fixtures after v1.1.0 restructure~~ | **✅ COMPLETE (PR #175)** — stale ROLE_OF_TRAUMA_SERVICES removed from index (44→43), validator prefix_map (36→35), 3 fixture files deleted, 0 NTDS outcome deltas |

##### Prioritized Backlog (post-Protocol-Audit)

| # | Item | Scope | Priority | Effort | Notes |
|---|------|-------|----------|--------|-------|
| ~~1~~ | ~~**FLAG 002 — E21 VAP vent gate**~~ | ~~`rules/ntds/logic/2026/21_vap.json`~~ | ~~**High**~~ | ~~Small~~ | **✅ COMPLETE** — required vent_evidence gate (7 vent_dx patterns, history_noise exclusion), 1 fixture added, Cheryl_Burton YES→NO, Ronald_Bittner stays YES, 39-patient cohort verified |
| ~~2~~ | ~~**FLAG 001 — Spinal protocol 36 h timing**~~ | ~~`rules/deaconess/protocols_deaconess_structured_v1.json`~~ | ~~**High**~~ | ~~Small~~ | **✅ COMPLETE** — REQ_REQUIRED_DATA_ELEMENTS + REQ_TIMING_CRITICAL (`temporal:within:36:hours`) added, 12 `protocol_spinal_stabilization_surgery` patterns in shared_action_buckets, 1 fixture added (spinal_timing_noncompliant → NON_COMPLIANT), 1 fixture updated (spinal_compliant + surgery within 36h), 0 NTDS outcome deltas |
| ~~3~~ | ~~**Baseline hash coverage for NTDS outputs**~~ | ~~`scripts/baselines/`, `scripts/gate_pr.sh`~~ | ~~**High**~~ | ~~Small~~ | **✅ COMPLETE** — 39-patient composite hash baseline (`ntds_hashes_v1.json`), standalone checker (`scripts/check_ntds_hashes.py`), wired into `gate_pr.sh` NTDS drift check section, 0 NTDS outcome deltas |
| ~~4~~ | ~~**D4 — DISCHARGE precision audit (14 events, 17 gates)**~~ | ~~Per-event evidence review; `rules/ntds/logic/2026/`~~ | ~~Medium~~ | ~~Medium~~ | **✅ COMPLETE** — 14 events audited across 39 patients, 0 false positives, 1 TP (Ronald_Bittner E13 Pressure Ulcer), no rule changes needed, baseline realigned (Anna_Dennis hash), audit doc in `docs/audits/D4_DISCHARGE_PRECISION_AUDIT.md` |
| ~~5~~ | ~~**Remaining 15-event precision pass**~~ | ~~Per-event mapper/rule/tests~~ | ~~Medium~~ | ~~Medium–Large~~ | **✅ COMPLETE (phase 1)** — E09 Delirium: `delirium_negation_noise` (10 patterns) added, 2 FP corrections (Barbara_Burgdorf YES→NO, Christine_Adelitzo YES→NO); E08 DVT: `dvt_dx_noise_prophylaxis` wired to `dvt_dx` gate (defensive, 0 outcome changes); fixture `09_delirium_consult_yes.txt` updated; 2 NTDS outcome deltas |
| ~~6~~ | ~~Source alignment (PROGRESS_NOTE + NURSING_NOTE)~~ | ~~Docs/design: per-event allowed_sources vs raw DATA SOURCE hierarchy~~ | ~~High~~ | ~~Medium~~ | **✅ COMPLETE (design doc + Tier 1 impl)** — Design: `docs/audits/SOURCE_ALIGNMENT_AND_GERI_DELIRIUM_v1.md` §1. Implementation: CONSULT_NOTE added to 4 gates (aki_dx, mi_dx, sepsis_dx, stroke_dx), NURSING_NOTE added to 3 gates (cauti_dx, clabsi_dx, sepsis_dx), 3 fixtures added, 0 NTDS outcome deltas |
| ~~7~~ | ~~Geriatric delirium nursing shift assessments~~ | ~~E09: shift-based nursing delirium assessments~~ | ~~High~~ | ~~Medium~~ | **✅ COMPLETE (design doc + CAM/bCAM impl)** — Design: `docs/audits/SOURCE_ALIGNMENT_AND_GERI_DELIRIUM_v1.md` §2. Implementation: 4 CAM-ICU/bCAM positive patterns added to `delirium_dx`, 4 negative patterns added to `delirium_negation_noise`, 1 CAM-ICU fixture added, 0 NTDS outcome deltas |
| ~~8~~ | ~~Ronald_Bittner targeted audit follow-up~~ | ~~Patient-level trace check~~ | ~~Low~~ | ~~Small~~ | **✅ COMPLETE (design doc)** — `docs/audits/SOURCE_ALIGNMENT_AND_GERI_DELIRIUM_v1.md` §3: E01 UTD root cause ("Held" SourceType not recognised), E13 TP confirmed (D4 audit), E21 VAP TP confirmed, 4 actionable items listed |
| ~~9~~ | ~~**5 AKI UTD residuals**~~ | ~~`rules/ntds/logic/2026/01_aki.json`, evidence tuning~~ | ~~Medium~~ | ~~Hard~~ | **✅ COMPLETE (v2)** — 3 `aki_negation_noise` patterns (PMH date format, chemo history, parenthetical format), 1 `aki_onset` pattern (clinical trajectory), arrival-time extraction added to runner; E01 UTD 7→3; 4 outcome deltas: Barbara_Burgdorf UTD→NO, Gary_Linder UTD→NO, William_Simmons UTD→NO, Floy_Geary UTD→YES; 3 residual UTDs (Carlton_Van_Ness, David_Gross, Ronald_Bittner) — genuine clinical ambiguity or source-detection limitation |
| ~~10~~ | ~~**Automate per-event NTDS outcome distribution in gate/CI**~~ | ~~CI/gate script~~ | ~~Low~~ | ~~Small~~ | **✅ COMPLETE** — `scripts/check_ntds_distribution.py` + baseline `scripts/baselines/ntds_distribution_v1.json` (21 events × 39 patients); per-event YES/NO/UTD/EXCLUDED counts computed from `outputs/ntds/`, compared against stored baseline; wired into `gate_pr.sh` between NTDS hash check and pytest; `--update` and `--summary` modes; 0 NTDS outcome deltas |
| ~~11~~ | ~~**E05 CAUTI Tier-1 spec fidelity (CDC SUTI 1a)**~~ | ~~`rules/ntds/logic/2026/05_cauti.json`, `rules/mappers/epic_deaconess_mapper_v1.json`, tests~~ | ~~**High**~~ | ~~Medium~~ | **✅ COMPLETE** — 5 required gates (cauti_dx, cauti_catheter_gt2d, cauti_symptoms, cauti_culture, cauti_after_arrival) + 2 exclusions (POA, chronic catheter); 6 new mapper keys (cauti_negation_noise, cauti_catheter_in_place, cauti_symptoms, cauti_culture_positive, cauti_onset, cauti_chronic_catheter) with 52 patterns total; cauti_dx expanded (UTI standalone + noise filter); 52 precision tests + 3 fixtures (YES, nursing-YES, no-catheter-NO); baseline refreshed post-rerun: E05 NO=39→NO=35 EXCLUDED=4 (4 patients excluded by catheter/chronic gates) |
| ~~11b~~ | ~~**Baseline refresh post-CAUTI v2**~~ | ~~`scripts/baselines/ntds_hashes_v1.json`, `scripts/baselines/ntds_distribution_v1.json`~~ | ~~**High**~~ | ~~Small~~ | **✅ COMPLETE** — 39-patient cohort rerun, hash + distribution baselines updated; E05 distribution delta: NO=39→NO=35 EXCLUDED=4; all other events unchanged; 2313 tests passed, cohort invariant PASS, 0 drift |
| ~~11c~~ | ~~**E05 CAUTI follow-up (culture/symptom variants)**~~ | ~~`rules/mappers/epic_deaconess_mapper_v1.json`, tests~~ | ~~High~~ | ~~Small~~ | **✅ COMPLETE** (PR #190) — symptoms 14→15 (adds altered mental status, temp regex 38–42°C); culture patterns 11→14 (1e5 CFU, spaced caret, ">100,000" forms); 13 new precision tests; 0 NTDS deltas |
| 12 | PMH-aware gate handling | Engine proposal (PROTECTED `cerebralos/ntds_logic/engine.py`) | Medium | Large | Requires engine modification + design doc + explicit authorization; protocol engine has reference impl |
| 13 | **CAUTI engine design (LDA duration gate + alt-source exclusion)** | Design doc `docs/audits/CAUTI_ENGINE_DESIGN_v1.md` | **High** | Medium–Large | ✅ DESIGN COMPLETE — requires engine-change authorization for implementation. LDA SourceType + catheter duration gate + alternative-source exclusion. See design doc for phased migration plan. |
| ~~14~~ | ~~**E06 CLABSI spec fidelity (NHSN CLABSI)**~~ | ~~`rules/ntds/logic/2026/06_clabsi.json`, `rules/mappers/epic_deaconess_mapper_v1.json`, tests~~ | ~~**High**~~ | ~~Medium~~ | **✅ COMPLETE** — 5 required gates (clabsi_dx, clabsi_central_line_gt2d, clabsi_lab_positive, clabsi_symptoms, clabsi_after_arrival) + 2 exclusions (POA, chronic line); 7 mapper keys (clabsi_negation_noise, clabsi_central_line_in_place, clabsi_blood_culture_positive, clabsi_symptoms, clabsi_onset, clabsi_chronic_line + refined clabsi_dx) with ~56 patterns total; clabsi_dx noise filter; 76 precision tests + 3 new fixtures (chronic-line-excluded, no-culture-no, noncentral-line-no); baseline refreshed: E06 stays NO=39, 0 NTDS outcome deltas |
| 15 | **Protocol Data Coverage Mapping** | `docs/audits/PROTOCOL_DATA_COVERAGE_MAPPING_v1.md` | Medium | Medium | **Slices A/B/C COMPLETE.** First-pass coverage matrix: 60 EXTRACTED, 57 PARTIAL, 97 MISSING, 16 N/A (PR #220). Slice A (sex + discharge disposition): ✅ COMPLETE (PRs #222–#225) — `demographics_v1` feature module + contract doc. Slice B (blood product transfusion): ✅ COMPLETE (PRs #229–#231) — `transfusion_blood_products_v1` foundation + hardening. Slice C (structured labs): ✅ COMPLETE (PRs #226–#228, #232) — `structured_labs_v1` foundation (CBC/BMP/coag/ABG/PF) + cardiac/sepsis expansion. Ventilator settings extraction: ✅ COMPLETE (PRs #233–#237) — FiO2/PEEP/Vt/RR/vent status, mode, NIV IPAP/EPAP/rate. GCS component extraction: ✅ COMPLETE (PRs #238–#239) — E/V/M from inline + flowsheet blocks, sum-mismatch guard. |
| 16 | **LDA engine support (Lines, Drains, Airways)** | `cerebralos/ntds_logic/engine.py`, `cerebralos/ntds_logic/build_patientfacts_from_txt.py`, `cerebralos/ntds_logic/model.py` | **High** | Large | ✅ IMPLEMENTED (v1+text+startstop+correctness+bracket-removed+per-event-enabled+vent-recall+multi-episode) — PRs #203, #206, #207, #214, #216, #244, #245, #246, #248, #250 (all merged). SourceType `LDA` added to model; `LDAEpisode` dataclass; `build_lda_episodes()` builder (structured JSON + text-derived flowsheet day-counter + insertion/removal start/stop inference); 4 gate types in engine incl. `eval_lda_overlap` (interval overlap, one-sided admission window — PR #214); `TEXT_DERIVED_STARTSTOP` confidence level; merge precedence: structured > startstop > day-counter (backfill episode_days — PR #214); `ENABLE_LDA_GATES` feature flag (default False); per-event LDA gates enabled for E05/E06/E21 via runner toggle + rule `required: true` (PRs #244–#246); bracket `[REMOVED]` patterns for Urethral Catheter + Non-Surgical Airway ETT (PR #216); vent start/stop episode extraction for E21 recall (intubation/extubation, placed-on/removed-from ventilator patterns, NIV exclusion — PR #248); multi-episode start/stop support for MECHANICAL_VENTILATOR and ENDOTRACHEAL_TUBE — sequential insert→remove pairing produces multiple non-overlapping episodes per device (PR #250); 180+ dedicated tests. LDA per-event rollout COMPLETE. |

##### Post-#250 Next Candidates

| # | Item | Scope | Priority | Effort | Notes |
|---|------|-------|----------|--------|-------|
| 17 | **Arrival vitals hardening (Primary Survey priority + ED fallback)** | `cerebralos/features/vitals_daily.py`, tests, contract doc | **High** | Medium | Add structured Primary-Survey-first extraction for arrival HR/BP/RR/SpO2/Temp, mirroring `gcs_daily` priority logic (TRAUMA_HP → ED fallback → DNA). Raw-file scan required. |
| 18 | **Tabular GCS flowsheet parsing follow-up** | `cerebralos/features/gcs_daily.py`, tests | Medium | Small | Extend GCS extraction for tabular flowsheet layouts (time-column headers with component rows) seen in some patients. |
| ~~19~~ | ~~**LDA gate enablement decision track**~~ | ~~`rules/ntds/logic/2026/`, config~~ | ~~Medium~~ | ~~Small~~ | **✅ COMPLETE** (PRs #244, #245, #246) — LDA gates enabled per-event for E05 CAUTI (PR #244), E06 CLABSI (PR #245), E21 VAP (PR #246). Each event rule updated `required: false` → `required: true`; per-event LDA set in `run_all_events.py` expanded to {5, 6, 21}; test fixtures + precision tests updated. Protected `engine.py` not modified — toggle handled in runner + rule JSON only. |
| ~~20~~ | ~~**Vent start/stop recall for E21 VAP**~~ | ~~`cerebralos/ntds_logic/build_patientfacts_from_txt.py`, tests~~ | ~~**High**~~ | ~~Small~~ | **✅ COMPLETE** (PR #248) — Citation-backed ventilator start/stop extraction patterns added: intubation/extubation, placed-on/removed-from ventilator, negated-phrase guards; NIV/BiPAP/CPAP excluded; 37 new LDA tests (positive+negative+negation); 0 NTDS outcome deltas; protected `engine.py` not modified. |
| ~~21~~ | ~~**Multi-episode vent start/stop (E21 recall hardening)**~~ | ~~`cerebralos/ntds_logic/build_patientfacts_from_txt.py`, tests~~ | ~~**High**~~ | ~~Small~~ | **✅ COMPLETE** (PR #250) — Sequential insert→remove pairing for MECHANICAL_VENTILATOR and ENDOTRACHEAL_TUBE; produces multiple non-overlapping episodes per device; orphan removes emit stop-only episode; orphan inserts emit open episode; merge logic updated to list-per-device with tier-based replacement and episode_days backfill; 10 new regression tests; 0 NTDS outcome deltas; protected `engine.py` not modified. |

##### LDA Analysis Intake Loop (Roadmap-First)

Use this whenever Terminal-Claude provides analysis-only findings:

1. Classify each finding as `KEEP NOW`, `TIGHTEN NEXT`, or `DEFER`.
2. Require raw citations (`Patient_File:line`) for new pattern/gate proposals.
3. State deterministic/fail-closed rationale for each `KEEP NOW` item.
4. Map `KEEP NOW` to one single-goal PR scope.
5. Record deferred items explicitly to prevent scope creep.

##### Item 16A — PR #214 Correctness Hardening Intake (2026-03-12)

Accepted into merged PR #214:
- Admission overlap semantics corrected to one-sided admission window.
- Mixed tz-aware/naive timestamp guard added to avoid runtime type errors.
- Merge-precedence backfill preserves `episode_days` when higher-tier episode lacks duration.
- CHEST_TUBE and DRAIN_SURGICAL text patterns expanded from cited raw lines.
- `TEXT_DERIVED_STARTSTOP` doc/runtime schema sync completed.

##### Item 16B — Post-PR #214 Raw-Scan Intake (2026-03-12) ✅ COMPLETE (PR #216)

Source: Terminal-Claude analysis report over newer patient set (11 found, 2 missing: `Mark_King`, `Andrew_Paez`).

`KEEP NOW` — **all implemented in PR #216** (merged):
- ~~Add bracketed remove pattern for urinary catheter:~~
  - ~~`"[REMOVED] Urethral Catheter ..."` -> `URINARY_CATHETER` remove.~~ ✅
- ~~Add bracketed remove pattern for ETT/airway:~~
  - ~~`"[REMOVED] Non-Surgical Airway ETT- Cuffed"` -> `ENDOTRACHEAL_TUBE` remove.~~ ✅
- ~~Add focused negatives in tests:~~
  - ~~`"[REMOVED] Peripheral IV"` must not match LDA start/stop extraction.~~ ✅

3 tests added (2 positive, 1 negative). 0 NTDS outcome deltas. `ENABLE_LDA_GATES` unchanged (False).

`TIGHTEN NEXT` (separate follow-up track, not same PR):
- Multi-line structured LDA block parsing (`header -> status -> datetime`) for richer placement/removal extraction.
- Inline `Placement Date/Time` and `Removal Date/Time` dual-date parsing.
- Handling of `Resolved: <date>` suffixes as possible stop-bound evidence.
- Explicit NIV classification decision (`Non-Invasive Mechanical Ventilation` vs invasive ventilator semantics).
- Prose date parsing (`January 4, 2026`, `1/6 -`) if needed for additional recall.

`DEFER` (out of current scope):
- Maintenance/status/context lines (for example water seal, care actions, present-tense status, plan-only language).
- Admin-routing language (for example "given via central line").
- DNI/DNR order lines unless they produce demonstrated false positives.

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
| **Pre-merge / final gate**   | Full 39  | Before merge to main           |

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

The sentinel cohort is a speed optimization (12/39 = 31% of patients).
It does NOT replace the full gate — it accelerates the inner dev loop.

---

## 5. Persistent Codex Operating Contract (Long-Horizon)

This section codifies the full Codex workflow so it remains visible 6+ months
from now, regardless of chat-session turnover.

### Roles

| Role | Actor | Responsibility |
|------|-------|----------------|
| Operator | Sarah | Copy/pastes terminal commands, reports outputs, makes final merge decisions |
| Executor | Claude (VS Code) | Edits code, runs commands, produces structured handoffs |
| Architect / Reviewer | Codex (ChatGPT in VS Code) | Proposes plan, writes exact Claude prompts, audits locally, provides findings-first review |

### Non-Negotiables

1. **Deterministic output only; fail-closed logic.** No LLM, no ML, no clinical inference.
2. **No silent schema drift.** If schema changes, update docs + validators + consumers in the same PR.
3. **Protected-engine rule.** Do NOT modify `cerebralos/ntds_logic/engine.py` or `cerebralos/protocol_engine/engine.py` unless explicitly instructed.
4. **One PR = one goal.** No scope creep — each PR states what it changes and what it does NOT change.
5. **Raw evidence policy.** Every stored evidence item must include `raw_line_id`. All `KEEP NOW` items require `Patient_File:line` citations before acceptance.

### Mandatory Workflow Loop

```text
1. CEREBRALOS PREFLIGHT FIRST
   └─ Run preflight commands before any merge / branch / PR guidance.
2. Codex triage scope
   └─ Classify findings as KEEP NOW | TIGHTEN NEXT | DEFER.
3. Codex writes exact Claude prompt
   └─ Branch name, goal, allowed files, terminal commands, acceptance criteria.
4. Claude executes + structured handoff
   └─ Files changed, gate output, diff, status, blockers.
5. Codex audits locally
   └─ Spec alignment, validation results, gaps/risks, 2-patient raw spot-check.
6. Codex gives full response:
   a) Findings-first (spec alignment, validation, risk)
   b) Pre-merge commands
   c) GitHub UI instructions
   d) Post-merge verification
   e) Next prompt (exact text for next Claude session)
   f) Deferred items list
```

### Required Preflight Command Block

```bash
cd ~/NetrionSystems/netrion-cerebralos
git branch --show-current
git rev-parse --short HEAD
git status --short
gh pr status || echo "GH_STATUS:UNAVAILABLE"
```

### Required Codex Response Format (7-Part Findings-First)

Every Codex response after a Claude handoff must include:

1. **Findings** — spec alignment, precision/recall impact, risk assessment.
2. **Pre-merge checklist** — targeted tests, full suite, cohort invariant, hash/distribution checks, `git diff --check`.
3. **Merge commands** — exact terminal commands for Sarah to execute.
4. **GitHub UI instructions** — PR merge button, delete branch, etc.
5. **Post-merge verification** — `git switch main && git pull --ff-only`, re-run hash + distribution checks.
6. **Next prompt** — exact copy/paste text for the next Claude session.
7. **Deferred items** — anything triaged out of current scope, with rationale.

### Lean Review Mode (Default)

Use lean mode by default to reduce cycle time:

1. Run `CEREBRALOS PREFLIGHT FIRST` once per cycle.
2. One scope check: `git diff --name-only origin/main...HEAD`.
3. One validation pass appropriate to scope.
4. One final merge-readiness audit + command set.

**Escalate to deep audit** when:
- Protected files (`engine.py`) are touched.
- Baseline or test output changes unexpectedly.
- Branch/PR state changes mid-cycle.
- Operator explicitly requests deep audit mode.

### Raw Evidence Policy

All pattern/gate proposals require:
- `Patient_File:line` citations from raw `.txt` files in `data_raw/`.
- Classification as `KEEP NOW`, `TIGHTEN NEXT`, or `DEFER`.
- Deterministic/fail-closed rationale for every `KEEP NOW` item.

### Completion Gate Requirement

Codex/Claude may not declare "done" until:

```bash
./scripts/gate_pr.sh
```

passes with exit 0. Default gate patients: Anna_Dennis, William_Simmons,
Timothy_Cowan, Timothy_Nachtwey.

---

## 6. Execution Protocol for New Chats

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
8. **Handoff reminder (Claude → Codex)**: Every handoff must include a concise post-handoff analysis (spec alignment, validation results, remaining gaps/risks, next actions) and a raw-data cross-check: compare raw NTDS/protocol sources vs current extraction, and spot-check two patient raw `.txt` files (one questionable, one baseline) for capture accuracy.

### Standard PR Workflow

Every mapper, rule, or test change **must** follow this workflow:

> See also §5 "Persistent Codex Operating Contract" for the full
> findings-first response format and lean/deep audit triggers.

1. **Raw-data evidence first.** Before editing mapper patterns or rule JSON, scan ≥2 raw patient `.txt` files (`data_raw/`) — one questionable case (potential edge case or near-miss) and one baseline (expected NO). Record the exact phrases that will drive pattern changes.
2. **Implement scoped changes.** Mapper patterns, rule JSON, precision tests, and fixtures — all in one branch, one commit. No engine changes unless explicitly approved.
3. **Run pre-merge validation checklist:**
   ```bash
   pytest -q tests/<targeted_precision_file>.py
   pytest -q tests/                                  # full suite
   python3 scripts/audit_cohort_counts.py --check     # 39-patient invariant
   python3 scripts/check_ntds_hashes.py               # 0 NTDS drift
   python3 scripts/check_ntds_distribution.py         # 0 distribution drift
   git diff --check                                   # no whitespace errors
   ```
4. **Address Copilot review comments** before completing the handoff.
5. **Post-handoff analysis (Codex).** Codex performs: spec alignment check, validation summary, gaps/risks assessment, next-actions list, and raw-data spot-check note (2 patients: one questionable, one baseline).
6. **Post-merge verification:**
   ```bash
   git switch main && git pull --ff-only
   python3 scripts/check_ntds_hashes.py
   python3 scripts/check_ntds_distribution.py
   ```

---

## 7. Key References

| Doc | Purpose |
|-----|---------|
| `AGENTS.md` | Non-negotiable constraints, roles, locked contracts |
| `docs/DAILY_STARTUP.md` | Daily startup checklist, gate commands |
| `docs/CHATGPT_BOOT_HEADER.md` | ChatGPT/Codex session bootstrap |
| `docs/roadmaps/TRAUMA_BUILD_FORWARD_PLAN_v1.md` | Original build-forward plan (historical) |
| `README.md` | Repo overview + scratch policy |

---

_End of document._
