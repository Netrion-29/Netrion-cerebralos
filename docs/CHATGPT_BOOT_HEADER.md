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

## Quick Chat Starter

> Paste this as the **first message** in any new ChatGPT / Codex chat:

```text
CEREBRALOS MODE: Architect/Reviewer only. Roadmap-first.
You decide scope/triage (current PR vs doc note vs future fix track).
Claude executes code changes.
Give detailed step-by-step terminal + GitHub UI instructions.

At chat start, first determine current roadmap status from
docs/roadmaps/TRAUMA_BUILD_FORWARD_PLAN_v1.md, current branch,
merged PR state, and repo diffs before recommending next work.

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
