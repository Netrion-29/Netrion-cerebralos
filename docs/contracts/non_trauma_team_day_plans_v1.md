# Non-Trauma Team Day Plans v1 — Feature Contract
**Feature key:** `non_trauma_team_day_plans_v1`  
**Branch:** `tier1/non-trauma-team-day-plans-v1`  
**Status:** Active  

## Purpose

Extracts per-day brief plan/update entries from non-trauma-team services
(hospitalist, critical care, neurosurgery, therapy, case management, etc.)
and organises them by calendar day and service for the v5 daily notes
renderer.

## Scope

### In scope
- `PHYSICIAN_NOTE` items that do **not** match the trauma daily plan
  allowlist (hospitalist, critical care, neurosurgery, PT, OT, SLP, etc.)
- `CASE_MGMT` items (Plan of Care — case management, discharge planning)
- Service identification via header-text heuristics
- Brief clinical update extraction (Assessment/Plan snippet)
- Per-day, per-service grouping with deterministic ordering
- Evidence traceability via `raw_line_id` (SHA-256 hash)
- v5 section: "Non-Trauma Day Plans:" after Consultant Day Plans,
  before Clinical Narrative

### Out of scope
- Trauma-team progress notes → `trauma_daily_plan_by_day_v1`
- Consultant initial notes → `consultant_day_plans_by_day_v1`
- v3/v4 renderer changes
- Protocol/NTDS engine changes
- Radiology reads, labs, MAR, flowsheet items

## Service Detection

Header-text heuristics applied to the first 500 chars of note text:

| Service | Detection Pattern |
|---------|------------------|
| Hospitalist | Deaconess Care Group, Hospital Progress Note, Hospitalist |
| Critical Care | Pulmonary/Critical Care Group, PCCM, Intensivist |
| Neurosurgery | Neurosurgery -, Neurosurgical Progress |
| Neurology | Neurology Inpatient/Progress/Consult |
| Physical Therapy | PHYSICAL THERAPY, PT Eval/Treatment, EARLY MOBILITY |
| Occupational Therapy | OCCUPATIONAL THERAPY, OT Eval, EARLY MOBILITY - ASSESSMENT |
| Speech Language Pathology | Speech Language Pathology, SLP, Clinical Swallow |
| Wound/Ostomy | Wound Care/Ostomy, WOCN |
| Palliative Care | Palliative Care/Medicine |
| Case Management | Case Manager/Management, Discharge Planning, Social Work |
| Respiratory Therapy | Respiratory Therapy, RT Progress |
| Cardiology | Cardiology Progress/Consult |
| Infectious Disease | Infectious Disease, ID Progress/Consult |
| Pastoral Care | Pastoral Care, Chaplain |
| Other Physician | Fallback for unclassifiable notes |

## Output Schema

```json
{
    "days": {
        "<ISO-date>": {
            "services": {
                "<service-name>": {
                    "notes": [
                        {
                            "dt": "<ISO datetime>",
                            "source_id": "<item source_id>",
                            "author": "<name, credential>",
                            "service": "<service-name>",
                            "note_header": "<first meaningful header line>",
                            "brief_lines": ["line1", ...],
                            "brief_line_count": "<int>",
                            "raw_line_id": "<sha256 hash>"
                        }
                    ],
                    "note_count": "<int>"
                }
            },
            "service_count": "<int>",
            "note_count": "<int>"
        }
    },
    "total_days": "<int>",
    "total_notes": "<int>",
    "total_services": "<int>",
    "services_seen": ["<service>", ...],
    "source_rule_id": "non_trauma_day_plans_extracted | no_qualifying_notes",
    "warnings": [],
    "notes": []
}
```

## v5 Rendering

Section header: `Non-Trauma Day Plans:`  
Position: After "Consultant Day Plans:", before "Clinical Narrative:"  
Behaviour when empty: **No output** (no DNA line)

Caps:
- `_MAX_NON_TRAUMA_BRIEF_LINES = 8` per note
- `_MAX_NON_TRAUMA_NOTES_PER_SERVICE = 6` per service per day

## Brief Update Extraction Rules

1. Prefer Assessment/Plan section content when present
2. Fall back to first meaningful clinical lines after header
3. Skip admin boilerplate (attestation, MyChart, revision history, etc.)
4. Stop at signature lines, terminators
5. Maximum 12 brief lines per note in raw extraction

## Files

| File | Purpose |
|------|---------|
| `cerebralos/features/non_trauma_team_day_plans_v1.py` | Feature extractor |
| `cerebralos/features/build_patient_features_v1.py` | Integration (import + call) |
| `cerebralos/reporting/render_trauma_daily_notes_v5.py` | v5 renderer (section + call) |
| `tests/test_non_trauma_team_day_plans.py` | 55 tests (unit + integration + v5) |
| `docs/contracts/non_trauma_team_day_plans_v1.md` | This contract |

## Fail-Closed Behaviour

- No qualifying notes → `source_rule_id = "no_qualifying_notes"`, empty days
- Pharmacy/prescription misclassified notes → skipped via `_RE_SKIP_NOTE`
- Radiology reads → skipped via `_is_radiology_read` heuristic
- Empty note text → skipped
- Unidentifiable service → classified as "Other Physician" (still included)
