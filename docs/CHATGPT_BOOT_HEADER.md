# CerebralOS — ChatGPT Boot Header

> **Paste this into the first message of every new ChatGPT session.**

---

## Project

| Key | Value |
| --- | --- |
| Project | Netrion CerebralOS |
| Repo path | `~/NetrionSystems/netrion-cerebralos` |
| Primary branch | `main` |
| Language | Python 3.12+, bash |
| Date format | ISO-8601 everywhere |
| NTDS coverage | **21/21 events mapped** — 43 fixtures, 0 xfailed (PRs #118 – #124) |
| N1 slug norm | ✅ COMPLETE (PRs #127–#128) |
| N2 gate invariant | ✅ COMPLETE — Phase 1 (PRs #129–#131) |
| N3 precision tuning | ✅ COMPLETE — 6 events tightened (PRs #132–#138): E16, E10, E19, E15, E18, E01 |
| N4-P1 AKI UTD reduction | ✅ COMPLETE (PR #141) — timing gate + onset patterns |
| N4-P2b parser word-boundary | ✅ COMPLETE (PR #143) — 8 validated deltas, 0 regressions |
| N5 DISCHARGE line-start anchor | ✅ COMPLETE (PR #145) — 5 validated deltas (all corrections), 0 regressions |
| N6 DISCHARGE first-word block | ✅ COMPLETE (PR #147) — 109/118 residual false flips eliminated, 0 NTDS outcome deltas |
| N7 DISCHARGE prose residual cleanup | ✅ COMPLETE (PR #149) — all 14 remaining false flips eliminated, 0 NTDS outcome deltas |
| D1 full cohort output refresh | ✅ COMPLETE — 33/33 patients refreshed, 0 NTDS outcome deltas, cohort invariant PASS |
| D2 IMAGING/RADIOLOGY/PROCEDURE anchor | ✅ COMPLETE (PR #152) — 3 patterns anchored, 68 tests added, 0 NTDS outcome deltas |
| D3 DISCHARGE word-boundary | **CLOSED (won't do)** — `\b` after PROCEDURE breaks 262 legitimate plural headers; zero practical impact |
| D5 LAB/MAR line-start anchor | ✅ COMPLETE (PR #154) — 2 patterns anchored, 2 tests added, 0 NTDS outcome deltas |
| D6-P1 MEDICATION_ADMIN/ED_NOTE anchor | ✅ COMPLETE (PR #156) — 2 patterns anchored, 11 tests added, 0 NTDS outcome deltas |
| D6-P2 PHYSICIAN_NOTE anchor | ✅ COMPLETE (PR #158) — 1 pattern anchored, 6 tests added, 0 NTDS outcome deltas |
| D6-P3 NURSING_NOTE anchor | ✅ COMPLETE (PR #159) — 1 pattern anchored + E09 rule widened, 9 tests added, 0 NTDS outcome deltas |
| D6-P4 CONSULT_NOTE prose-before block | ✅ COMPLETE — prose-before filter added, 49 false triggers eliminated, 26 sub-headers preserved, 25 tests added, 0 NTDS outcome deltas |
| D6-P5 EMERGENCY hardening | ✅ COMPLETE — pattern tightened to EMERGENCY DEPT/DEPARTMENT + trailing whitelist + prose-before filter, 464 false triggers eliminated, 18 tests added, 0 NTDS outcome deltas |
| D6-P6 OPERATIVE_NOTE anchor | ✅ COMPLETE — compound-prefix anchor, 3860 false triggers eliminated, 14 tests added, 0 NTDS outcome deltas |
| D6-P7 PROGRESS_NOTE anchor | ✅ COMPLETE — compound-prefix anchor with 20 specialty prefixes, 308 false triggers eliminated, 438 sub-headers preserved, 13 tests added, 0 NTDS outcome deltas |
| ED_NOTE allowed_sources gap | ✅ COMPLETE — ED_NOTE added to 12 NTDS events (17 gates), 0 NTDS outcome deltas across 39 patients |
| Anesthesia SourceType | ✅ COMPLETE — ANESTHESIA_NOTE enum + parser pattern + wired E19/E20 rules, 12 tests added, 0 NTDS outcome deltas across 39 patients |
| Protocol coverage audit | ✅ COMPLETE (PR #175) — stale ROLE_OF_TRAUMA_SERVICES removed from index/validator/fixtures, 43 protocols synced, 0 NTDS outcome deltas |
| Open PRs | None (PR #175 merged, PR #142 closed as stale) |
| Next phase | **Backlog priority:** (1) FLAG 002 E21 VAP vent gate, (2) FLAG 001 Spinal 36 h timing, (3) Baseline hash coverage, (4) D4 DISCHARGE precision audit — see Roadmap §3 |

## Quick Chat Starter

> Paste this as the **first message** in any new ChatGPT / Codex chat:

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

## Execution Model

- **ChatGPT** designs architecture + produces copy/paste instructions.
- **Claude (VS Code)** edits code and runs commands inside the repo.
- **Operator (Sarah)** copy/pastes commands and returns: (1) Claude SUMMARY, (2) terminal output.

## Non-Negotiable Constraints

1. **Deterministic output only; fail-closed logic.** No LLM, no ML, no clinical inference.
2. Do NOT change v3/v4 renderer outputs unless explicitly planned.
3. Do NOT modify NTDS engine (`cerebralos/ntds_logic/engine.py`) unless explicitly planned.
4. Do NOT modify protocol engine (`cerebralos/protocol_engine/engine.py`) unless explicitly planned.
5. Every evidence item stored must include `raw_line_id`.
   - Layer-0 evidence format: `L{line_start}-L{line_end}` (line-range).
   - Feature-layer format: `sha256(source_id|dt|preview)[:16]` (hash).
   - Both are acceptable if deterministic and traceable.
   - See `docs/CODEX_RULEBOOK.md` §6 for full policy.
6. No scope creep — each PR must state what it changes and what it does NOT change.

## Canonical Pipeline

```text
data_raw/$PAT.txt
→ cerebralos/ingest/parse_patient_txt.py          → outputs/evidence/$PAT/patient_evidence_v1.json
→ cerebralos/timeline/build_patient_days.py        → outputs/timeline/$PAT/patient_days_v1.json
→ cerebralos.features.build_patient_features_v1    → outputs/features/$PAT/patient_features_v1.json
→ cerebralos/reporting/render_trauma_daily_notes_v3.py → outputs/reporting/$PAT/TRAUMA_DAILY_NOTES_v3.txt
→ cerebralos/reporting/render_trauma_daily_notes_v4.py → outputs/reporting/$PAT/TRAUMA_DAILY_NOTES_v4.txt
```

Entry point: `./run_patient.sh $PAT`

## patient_features_v1.json Contract (LOCKED)

**Allowed top-level keys (exactly):**

```text
build, patient_id, days, evidence_gaps, features, warnings, warnings_summary
```

**All feature modules live ONLY under `"features"` dict:**

```json
{
  "patient_id": "...",
  "build": {"version": "v1"},
  "days": { "<ISO-date>": { "labs": {}, "devices": {}, "services": {}, "vitals": {}, "gcs_daily": {} } },
  "evidence_gaps": { "gap_count": 0, "max_gap_days": 0, "gaps": [] },
  "features": {
    "vitals_canonical_v1": {},
    "dvt_prophylaxis_v1": {},
    "gi_prophylaxis_v1": {},
    "base_deficit_monitoring_v1": {},
    "category_activation_v1": {},
    "vitals_qa": {}
  },
  "warnings": [],
  "warnings_summary": {}
}
```

**Forbidden:** Any feature module key (`vitals_canonical_v1`, `dvt_prophylaxis_v1`, etc.) at the top level.

**Enforced by:** `cerebralos/validation/validate_patient_features_contract_v1.py` — runs automatically in `run_patient.sh` after features generation. Non-zero exit = pipeline halt.

## Verification Gates (Required for Every PR)

```bash
# 1. Pipeline runs clean
./run_patient.sh $PAT

# 2. Renderer output unchanged (compare SHA-256)
shasum -a 256 outputs/reporting/$PAT/TRAUMA_DAILY_NOTES_v4.txt

# 3. Regression passes
python3 _regression_phase1_v2.py
#   → Deterministic: True
#   → Zero unintended artifact drift: True

# 4. Contract check (automatic in pipeline, but can run manually)
python3 cerebralos/validation/validate_patient_features_contract_v1.py \
  --in outputs/features/$PAT/patient_features_v1.json
```

## CEREBRALOS PREFLIGHT FIRST

> **Shortcut phrase: `CEREBRALOS PREFLIGHT FIRST`**
>
> Run these commands before giving merge, branch cleanup, or
> PR creation/retarget/rebase guidance.

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

## Side-Track Audit Triage

When an audit or review surfaces findings outside the active PR's scope:

1. **Current roadmap PR** — only if the finding is squarely within the stated goal.
2. **Separate doc-only note** (`docs/audits/`) — default for useful findings that are out-of-scope.
3. **Future dedicated fix track** — required when protected engines/rules (NTDS, protocol, renderers) are involved, unless explicitly approved.

Codex must explain the triage decision and preserve useful findings in-repo so they are not lost between sessions.

## Key Test Patients

| Patient | Notes |
| --- | --- |
| Anna_Dennis | Baseline regression patient (determinism anchor) |
| William_Simmons | Abnormal vitals alignment patient |
| Timothy_Cowan | BD monitoring, device carry-forward |
| Timothy_Nachtwey | Multi-day, GI/DVT prophylaxis evidence |

## Rules / Config Files

| Path | Purpose |
| --- | --- |
| `rules/features/*.json` | Feature extraction configs (thresholds, patterns) |
| `rules/ntds/*.json` | NTDS event definitions |
| `rules/protocols/*.json` | Protocol definitions |
| `rules/mappers/*.json` | Service/device/vitals mapping configs |

## Directory Layout (Key Paths)

```text
cerebralos/
  features/          ← Layer 2: per-day + cross-day feature extraction
  ingest/            ← Layer 0: raw text → evidence JSON
  timeline/          ← Layer 1: evidence → patient_days
  reporting/         ← Layer 3: features → human-readable notes
  validation/        ← QA validators (contract, features, NTDS, protocols)
  ntds_logic/        ← NTDS event engine (PROTECTED)
  protocol_engine/   ← Protocol compliance engine (PROTECTED)
  green_card/        ← Green card extraction (opt-in)
```
