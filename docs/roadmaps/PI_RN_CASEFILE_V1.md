# PI RN Casefile v1 — Product Direction

| Field       | Value                                                    |
|-------------|----------------------------------------------------------|
| Date        | 2026-03-22                                               |
| Status      | **APPROVED DIRECTION** — docs + soft-archive phase       |
| Owner       | Sarah                                                    |
| Primary User | Single PI RN (trauma program)                           |

---

## 1. Product Goal

Build a **single-patient case file / chart** — one beautiful document per
trauma patient — that gives the PI RN everything she needs to review a case
without switching between raw text logs, rendered reports, and spreadsheets.

This is the primary product surface for CerebralOS going forward.

---

## 2. Primary User

One PI RN responsible for trauma quality improvement. She
reviews ~40 patients per quarter for NTDS compliance, protocol adherence,
and documentation completeness. Her current workflow is manual and
fragmented across multiple artifacts.

---

## 3. Primary Workflow

```text
Operator runs:  ./run_patient.sh "Patient Name" --ntds --protocols
                (or one-click launcher — Phase 5)

Pipeline produces:
  outputs/evidence/Patient_Name/patient_evidence_v1.json
  outputs/timeline/Patient_Name/patient_days_v1.json
  outputs/features/Patient_Name/patient_features_v1.json
  outputs/ntds/Patient_Name/ntds_summary_2026_v1.json
  outputs/protocols/Patient_Name/protocol_results_v1.json

[FUTURE] Bundle assembler produces:
  outputs/bundles/Patient_Name/patient_bundle_v1.json

[FUTURE] Casefile renderer produces:
  outputs/casefiles/Patient_Name/casefile_v1.html  (or .pdf)

Operator opens casefile in browser and reviews the patient.
```

---

## 4. Primary Artifact: Patient Casefile

The casefile is a rendered single-patient document (HTML initially, PDF
export later). It is the final-mile product — what the PI RN actually
reads and uses for case review.

### 4.1 Casefile Structure

**Trauma Summary Header (above the fold)**

| Field | Source |
|-------|--------|
| Patient name | `patient_evidence_v1.json → meta.patient_name` |
| Date of birth | `patient_evidence_v1.json → meta.dob` |
| Age | Computed from DOB + admission date |
| Mechanism of injury (MOI) | `patient_features_v1.json → features.mechanism_region_v1` |
| PMH / especially anticoagulants | `patient_features_v1.json → features.pmh_social_allergies_v1` + `features.anticoag_context_v1` |
| Injuries | `patient_features_v1.json → features` (injury-related modules) |
| Consultants | `patient_features_v1.json → features.consultant_day_plans_by_day_v1` |
| Admission / discharge dates | `patient_days_v1.json` day range |
| Length of stay | Computed from day range |

**Daily Admission Notes (by hospital day)**

Each hospital day shows:

| Section | Source |
|---------|--------|
| Procedures | `patient_features_v1.json → features` (procedure modules) |
| Labs (structured) | `patient_features_v1.json → features.structured_labs_v1` |
| Imaging | `patient_features_v1.json → features` (imaging modules) |
| Consultant plans | `patient_features_v1.json → features.consultant_day_plans_by_day_v1` |
| Changes in course | `patient_features_v1.json → features.trauma_daily_plan_by_day_v1` |
| Vitals snapshot | `patient_features_v1.json → features.vitals_canonical_v1` |
| Ventilator settings | `patient_features_v1.json → features.ventilator_settings_v1` |
| GCS | `patient_features_v1.json → days[YYYY-MM-DD].gcs_daily` |

**NTDS + Protocol Non-Compliance (prominently visible)**

| Section | Source |
|---------|--------|
| NTDS event outcomes (21 events) | `ntds_summary_2026_v1.json` |
| NTDS event detail + gate traces | `ntds_event_NN_2026_v1.json` per event |
| Protocol compliance outcomes | `protocol_results_v1.json` |
| Non-compliant protocols highlighted | Filtered from protocol results |

### 4.2 Design Principles

1. **Single-patient first.** The casefile is one patient at a time.
2. **Everything on one page.** No tab-switching or artifact-hunting.
3. **Non-compliance jumps out.** NTDS events and protocol violations are
   visually prominent — not buried in a table.
4. **Deterministic.** Every field traces back to extracted evidence with
   `raw_line_id` provenance.
5. **No clinical inference.** Display what was extracted, not what was inferred.

---

## 5. Proposed Architecture

### 5.1 Layers (what exists today — no changes)

```text
Layer 0: Ingest       → patient_evidence_v1.json
Layer 1: Timeline     → patient_days_v1.json
Layer 2: Features     → patient_features_v1.json
Layer 3: NTDS Engine  → ntds_summary / per-event JSONs
Layer 4: Protocol Engine → protocol_results_v1.json
Layer 5: Renderers    → v3/v4/v5 text reports (keep as-is)
```

### 5.2 New Layers (future implementation)

```text
Layer 6: Bundle Assembler → patient_bundle_v1.json
         Combines L0–L4 outputs into a single self-contained JSON.

Layer 7: Casefile Renderer → casefile_v1.html
         Renders the bundle into the PI RN's primary review document.
```

### 5.3 Bundle Contract (future — `patient_bundle_v1.json`)

The bundle is a convenience aggregation layer. It does NOT recompute
anything — it assembles existing pipeline outputs into one file so the
renderer has a single input.

Proposed top-level shape (to be formalized in a future contract PR):

```json
{
  "bundle_version": "1.0",
  "patient_id": "Patient_Name",
  "generated_at": "2026-03-22T12:00:00Z",
  "demographics": { },
  "admission": { },
  "days": [ ],
  "features": { },
  "ntds": {
    "summary": [ ],
    "events": { }
  },
  "protocols": {
    "results": [ ]
  },
  "evidence_metadata": { }
}
```

This shape is **not locked** until the contract PR is merged.

---

## 6. Phased Build Plan

### Phase 1 — Docs + Soft-Archive (THIS PR)

- [x] Product direction doc (this file)
- [x] Soft-archive old Next.js dashboard (README banner, no deletion)
- [x] Update main roadmap to reference new direction
- [ ] No runtime changes
- [ ] No file moves or deletions

### Phase 2 — `patient_bundle_v1` Contract

- Define exact JSON schema for the bundle
- Write contract doc (`docs/contracts/patient_bundle_v1.md`)
- Write schema validator
- Lock top-level keys (same pattern as `patient_features_v1.json`)

### Phase 3 — Bundle Assembler

- Implement `cerebralos/bundle/assemble_patient_bundle.py`
- Wire into pipeline (after features + NTDS + protocols)
- Output: `outputs/bundles/$SLUG/patient_bundle_v1.json`
- Validate with contract validator

### Phase 4 — Single-Patient Casefile Renderer

- Implement casefile renderer (HTML output)
- Input: `patient_bundle_v1.json`
- Output: `outputs/casefiles/$SLUG/casefile_v1.html`
- Trauma summary header + daily notes + NTDS/protocol compliance
- Wire into `run_patient.sh` and `__main__.py`

### Phase 5 — One-Click Run/Open Workflow

- [x] Shell wrapper: `scripts/run_casefile_v1.sh` — runs full pipeline + opens casefile
- [x] Interactive prompt when no patient argument given
- [x] VS Code task: `.vscode/tasks.json` — "PI RN Casefile — Run Patient"
- [x] Auto-open casefile in default browser (macOS `open`, Linux `xdg-open`)
- [x] `CEREBRAL_NO_OPEN=1` for CI/sandbox suppression
- [x] `README.md` quick-start section
- [ ] macOS Automator action (deferred — documentation only)

### Phase 6 — Cross-Patient Hub

- [x] Hub renderer: `cerebralos/reporting/render_casefile_hub_v1.py` — reads all `patient_bundle_v1.json` files
- [x] Output: `outputs/casefile/hub_v1.html` — self-contained local HTML index
- [x] Patient cards: name, age/sex, arrival/discharge, LOS, mechanism, NTDS YES/UTD, protocol NC
- [x] Client-side search by name, filter by discharge status, sort (arrival/name/LOS/NTDS)
- [x] One-click link to each patient's `casefile_v1.html`
- [x] Shell wrapper: `scripts/run_casefile_hub_v1.sh`
- [x] Tests: `tests/test_casefile_hub_v1.py` (51 tests)
- [ ] Wire hub refresh into patient pipeline (deferred — separate scope)

### Phase 7 — Excel Secondary Refinement

- Refine existing Excel dashboard as a secondary/export surface
- Not the primary review tool
- Useful for quarterly reporting, data export, PI committee presentations
- Builds on same bundle data

---

## 7. What Stays

| Component | Status | Notes |
|-----------|--------|-------|
| Ingest pipeline (`parse_patient_txt.py`) | **KEEP** | Foundation — no changes |
| Timeline builder | **KEEP** | Foundation — no changes |
| Feature builder + all feature modules | **KEEP** | Foundation — no changes |
| NTDS engine + 21 event rules | **KEEP** | Foundation — no changes |
| Protocol engine + protocol rules | **KEEP** | Foundation — no changes |
| v3 renderer | **KEEP** | Legacy text output — useful for diff/debug |
| v4 renderer | **KEEP** | Clinically self-sufficient text report |
| v5 renderer | **KEEP** | Enhanced narrative text — useful but not end-state |
| `run_patient.sh` | **KEEP** | Entry point — will be extended, not replaced |
| `__main__.py` CLI | **KEEP** | Python entry point — will be extended |
| Validation layer | **KEEP** | Contract enforcement — no changes |
| Gate infrastructure (`gate_pr.sh`, baselines) | **KEEP** | CI/quality — no changes |
| Test suites (3700+ tests) | **KEEP** | Quality foundation — no changes |
| Excel dashboard | **KEEP (secondary)** | Future Phase 7 refinement surface |

---

## 8. What Is Legacy

| Component | Status | Notes |
|-----------|--------|-------|
| `dashboard/` (Next.js app) | **LEGACY — soft-archived** | Preserved for reference; not the active product path; superseded by casefile direction |
| HTML report (`html_report.py`) | **LEGACY — evaluate** | Current HTML report may be replaced or evolved by casefile renderer (Phase 4); keep for now |

---

## 9. What Is Explicitly Out of Scope for v1

| Item | Reason |
|------|--------|
| Cross-patient dashboard / hub | Phase 6 — PI RN reviews one patient at a time |
| PDF export | Phase 4+ refinement — HTML first |
| Real-time / live mode | Not needed for retrospective PI review |
| Multi-hospital support | Single site |
| Authentication / user management | Single operator, local machine |
| Cloud deployment | Local-first; Vercel path documented but not prioritized |
| LLM / ML inference | Violates deterministic constraint |
| Engine modifications | Protected — out of scope for product direction PR |
| New feature extraction | Separate PRs per AGENTS.md |
| Old dashboard resurrection | Legacy — do not invest |

---

## 10. Recommended Implementation Sequence

| Phase | PR Goal | Dependencies |
|-------|---------|--------------|
| 1 | Docs + soft-archive (this PR) | None |
| 2 | `patient_bundle_v1` contract | Phase 1 merged |
| 3 | Bundle assembler implementation | Phase 2 merged |
| 4 | Single-patient casefile renderer (HTML) | Phase 3 merged |
| 5 | One-click run/open workflow | Phase 4 merged |
| 6 | Cross-patient hub | Phase 4 merged (Phase 5 optional) |
| 7 | Excel secondary refinement | Phase 3 merged |

Each phase is one PR (or a small set of tightly scoped PRs). Each
phase builds on the prior foundation. No phase requires engine changes
or protected-file modifications.

---

## 11. Relationship to Existing Roadmap

This direction does NOT replace or conflict with ongoing extraction work
(NTDS hardening, protocol coverage, feature extraction). Those efforts
continue independently — they improve the data quality that feeds the
casefile.

```text
Extraction work (ongoing)     →  richer patient_features_v1.json
                                  richer NTDS/protocol results
                                          ↓
Bundle assembler (Phase 3)    →  patient_bundle_v1.json
                                          ↓
Casefile renderer (Phase 4)   →  casefile_v1.html  ← PI RN reads this
```

The casefile is the **consumer** of extraction quality improvements. Better
extraction → better casefile. The two tracks are complementary.

---

End.
