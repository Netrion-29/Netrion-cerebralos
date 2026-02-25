# Vitals Coverage Audit — 2026-02-25

| Field      | Value                                              |
|------------|----------------------------------------------------|
| Date       | 2026-02-25                                         |
| Author     | Claude (repo agent)                                |
| Branch     | tier0/vitals-coverage-audit-and-roadmap-refresh     |
| Base       | main @ a4f46a0 (PR #47 merged)                     |
| Scope      | Audit only — no code changes                       |

---

## 1. Executive Summary

**Finding: The "Arrival Vitals: DATA NOT AVAILABLE" problem is a SELECTOR BUG
in 4 of 5 patients, compounded by SOURCE TYPE GAPS in the selector's priority
list. One patient (Ronald Bittner) also has an UPSTREAM CAPTURE GAP on the
arrival day.**

All 5 audited patients have vitals data in the raw source files. All 5 have
vitals extracted into `patient_features_v1.json` (canonical records exist).
But the arrival vitals selector fails for every patient because:

1. **INLINE → NURSING_NOTE mapping not in selector priority list** (affects 4/5)
2. **VISIT_VITALS → TRAUMA_HP mapping creates wrong time windows** (affects 2/5)
3. **TABULAR source type not in selector priority list** (affects 1/5)
4. **Ronald Bittner arrival-day has 0 canonical records** (upstream gap on
   arrival day specifically — vitals exist on other days)

---

## 2. Layer-by-Layer Coverage Audit

### Patient Summary Table

| Patient           | Raw Vitals? | Evidence Vitals Section? | Timeline Vitals Items? | Canonical Records | Arrival Day Records | Arrival Status         | Selector Rule          | Classification         |
|-------------------|-------------|--------------------------|------------------------|-------------------|---------------------|------------------------|------------------------|------------------------|
| Timothy_Cowan     | YES (1 hdr, 0 tab) | NO (0/92 items)  | NO (0 vitals items)    | 5 total           | 1                   | DATA NOT AVAILABLE     | no_qualifying_record   | **selector_bug**       |
| Ronald_Bittner    | YES (120 hdr, 350 tab) | NO (0/241 items) | NO (0 vitals items)  | 289 total         | 0                   | DATA NOT AVAILABLE     | no_viable_records      | **mixed**              |
| Timothy_Nachtwey  | YES (51 hdr, 94 tab) | NO (0/149 items) | NO (0 vitals items)  | 82 total          | 12                  | DATA NOT AVAILABLE     | no_qualifying_record   | **selector_bug**       |
| Anna_Dennis       | YES (13 hdr, 10 tab) | NO (0/49 items)  | NO (0 vitals items)  | 29 total          | 5                   | DATA NOT AVAILABLE     | no_qualifying_record   | **selector_bug**       |
| Charlotte_Howlett | YES (17 hdr, 18 tab) | NO (0/62 items)  | NO (0 vitals items)  | 26 total          | 6                   | DATA NOT AVAILABLE     | no_qualifying_record   | **selector_bug**       |

### Key Observations

1. **Evidence JSON**: No patient has a "Vitals" section in evidence. All evidence
   items have `section=""`. Vitals data IS captured but is embedded within other
   sections (H&P notes, flowsheet snapshots, nursing notes). The `vitals_daily.py`
   extractor reads individual evidence items' `content` field and parses vitals
   from inline text, tabular blocks, and visit vitals blocks. This is working.

2. **Timeline**: The timeline `items` list contains evidence items, but none are
   flagged as "vitals" in their section field. This is expected — vitals extraction
   happens at the features layer, not the timeline layer.

3. **Features — per-day vitals**: All patients have extracted vitals with full
   metric coverage (sbp, hr, temp_f, etc.) on most days. The extraction is working.

4. **Features — canonical records**: All patients have canonical vitals records
   with timestamps, sources, and values. The canonical layer is working.

5. **Features — arrival selector**: **ALL 5 patients fail.** This is the loss point.

---

## 3. Root Cause Analysis

### Root Cause 1: Source Type Priority List Gap (PRIMARY — 4/5 patients)

**File**: `cerebralos/features/vitals_canonical_v1.py`
**Function**: `select_arrival_vitals()` (lines 260-300)
**Constant**: `_ARRIVAL_SOURCE_PRIORITY` (line 252)

The selector only considers three source types:
```python
_ARRIVAL_SOURCE_PRIORITY = {
    "TRAUMA_HP":    0,
    "ED_NOTE":      1,
    "FLOWSHEET":    2,
}
```

But canonical records carry these source types (via `_SOURCE_MAP`):
- `INLINE` → `NURSING_NOTE` — **not in priority list**
- `VISIT_VITALS` → `TRAUMA_HP` — in list but timestamp issues (see RC2)
- `FLOWSHEET` → `FLOWSHEET` — in list
- `ED_TRIAGE` → `ED_NOTE` — in list
- `TABULAR` → `TABULAR` — **not in priority list** (no mapping in `_SOURCE_MAP` either; passes through as-is)

**Impact**: When a patient's only arrival-day vitals come from INLINE/NURSING_NOTE or TABULAR sources, the selector skips them entirely.

**Affected patients**:
- **Timothy_Cowan**: 1 viable record, source=NURSING_NOTE (from INLINE), ts=16:17 (23 min after arrival 15:54). Would qualify within a reasonable window. **Rejected because NURSING_NOTE not in priority list.**
- **Timothy_Nachtwey**: 12 viable records, source=NURSING_NOTE (2) + TABULAR (10). NURSING_NOTE record at 01:00 is 23 min after arrival (00:37). **Rejected because neither NURSING_NOTE nor TABULAR in priority list.**
- **Anna_Dennis**: 5 viable records. 1 NURSING_NOTE at 15:44 (45 min after arrival 14:59). **Rejected because NURSING_NOTE not in priority list.**
- **Charlotte_Howlett**: 6 viable records. 1 NURSING_NOTE at 18:31 (1h50m after arrival 16:41). **Rejected because NURSING_NOTE not in priority list.**

### Root Cause 2: VISIT_VITALS → TRAUMA_HP Mapping + Tight Time Window (SECONDARY — 2/5 patients)

**File**: `cerebralos/features/vitals_canonical_v1.py`
**Constant**: `_SOURCE_MAP` (line 38) maps `VISIT_VITALS` → `TRAUMA_HP`
**Constant**: `_ARRIVAL_WINDOW_MINUTES["TRAUMA_HP"]` = 30 minutes

The `Visit Vitals` section (source_type=VISIT_VITALS) gets mapped to `TRAUMA_HP`.
But Visit Vitals blocks often have timestamps hours after arrival, because they
represent the attending's examination, not the initial triage/arrival assessment.

**Affected patients**:
- **Anna_Dennis**: TRAUMA_HP records at 16:43 are 1h44m after arrival (14:59). Delta exceeds 30-min window. Visit Vitals with sbp=145 available but rejected.
- **Charlotte_Howlett**: TRAUMA_HP records at 23:33 are 6h52m after arrival (16:41). Delta exceeds 30-min window. Visit Vitals with sbp=126 available but rejected.

### Root Cause 3: Ronald Bittner Arrival-Day Has 0 Records (UPSTREAM GAP)

**Patient**: Ronald_Bittner
**Arrival**: 2025-12-31 20:38

Ronald Bittner has 289 canonical vitals records across 27 days, but **zero on the
arrival day (2025-12-31)**. The first day with records is 2026-01-01.

This is an **upstream capture gap** — the raw file has vitals headers at line 162
(`Vitals: Blood pressure (!) 164/86, pulse (!) 107, temperature 98.1 °F...`) but
this appears to be ingested with a timestamp that places it on 2026-01-01 rather
than 2025-12-31. The extractor successfully captures vitals starting from day 1,
but misses the arrival-day assignment.

**Classification**: mixed (upstream date assignment issue + selector would still
fail because INLINE→NURSING_NOTE isn't in the priority list)

### Root Cause 4: Canonicalization Fragmentation (MINOR)

Some records carry only partial metrics (e.g., sbp but not hr, or temp_f but
not sbp). The `build_canonical_vitals()` grouping key is `(dt, source_type,
source_id, preview)`, which correctly groups metrics from the same evidence line.
However, TABULAR records are emitted with separate preview strings per metric
(e.g., `"BP: 116/80"` vs `"Pulse: 86"`), creating separate canonical records
that each have only one metric populated.

This fragmentation doesn't prevent selection (the records are still "viable" if
they have any metric), but it means the selected arrival vitals record may be
missing some metrics even though they were extracted on the same timestamp from
different evidence lines.

---

## 4. Impact / Priority Recommendation

### Immediate fix: `arrival-vitals-selector-v2`

**Recommendation**: Fix the arrival vitals selector FIRST. This is a pure selector
bug in one file (`vitals_canonical_v1.py`) that can be resolved with:

1. Add `NURSING_NOTE` and `TABULAR` to `_ARRIVAL_SOURCE_PRIORITY` with appropriate
   tier levels and time windows (e.g., NURSING_NOTE tier 3 at 60 min, TABULAR
   tier 4 at 60 min)
2. Widen the TRAUMA_HP window from 30 min to at least 120 min (or consider the
   VISIT_VITALS mapping — these aren't actual Trauma H&P vitals in the clinical
   sense; they're Visit Vitals from the attending/clinician's exam)
3. Consider adding a NURSING_NOTE/INLINE record between ED_NOTE and FLOWSHEET
   in priority, since inline vitals from the Trauma H&P narrative are clinically
   equivalent to Visit Vitals

**Estimated scope**: ~50 lines changed in 1 file + tests + contract doc update.
Single-goal PR. No renderer/engine changes needed.

**Downstream impact**:
- `shock_trigger_v1` depends on arrival vitals → will immediately start producing
  results (currently DNA because arrival vitals is DNA)
- v5 renderer: Arrival Vitals line will populate (no renderer code change needed;
  the template already handles the data-present case)
- v5 per-day "Arrival GCS" DNA issues are separate (GCS extraction, not vitals)

### Deferred: `vitals-section-capture-v2`

Ronald Bittner's arrival-day gap may also need an upstream fix (evidence date
assignment or evidence section parsing), but this is lower priority because:
- Only 1 of 5 patients affected at the upstream level
- Even after the upstream fix, the selector bug must also be fixed for it to work
- The selector fix alone will resolve 4 of 5 patients immediately

**Recommendation**: Do selector fix first, then revisit Bittner's arrival-day gap
as a separate, targeted investigation.

---

## 5. Artifacts Reviewed

### Raw patient files
- `data_raw/Timothy_Cowan.txt` (30,295 lines)
- `data_raw/Ronald Bittner.txt` (74,185 lines)
- `data_raw/Timothy_Nachtwey.txt`
- `data_raw/Anna_Dennis.txt`
- `data_raw/Charlotte Howlett.txt`

### Evidence JSON
- `outputs/evidence/{Timothy_Cowan,Ronald_Bittner,Timothy_Nachtwey,Anna_Dennis,Charlotte_Howlett}/patient_evidence_v1.json`

### Timeline JSON
- `outputs/timeline/{all 5}/patient_days_v1.json`

### Features JSON
- `outputs/features/{all 5}/patient_features_v1.json`

### v5 Rendered Output
- `outputs/reporting/{all 5}/TRAUMA_DAILY_NOTES_v5.txt`

### Code files reviewed
- `cerebralos/features/vitals_canonical_v1.py` (397 lines — full read)
- `cerebralos/features/vitals_daily.py` (1,174 lines — source_type usage)
- `cerebralos/features/build_patient_features_v1.py` (lines 285–325 — arrival selector call site)
- `cerebralos/reporting/render_trauma_daily_notes_v5.py` (arrival vitals rendering, lines 149–164)

---

## 6. Commands Run

```bash
# Preflight
cd ~/NetrionSystems/netrion-cerebralos
git checkout main && git pull --ff-only
git status --short --branch
git log --oneline --decorate -8
gh pr list --state open

# Branch creation
git checkout -b tier0/vitals-coverage-audit-and-roadmap-refresh

# Patient rebuilds (all succeeded)
./run_patient.sh Timothy_Cowan
./run_patient.sh "Ronald Bittner"
./run_patient.sh Timothy_Nachtwey
./run_patient.sh Anna_Dennis
./run_patient.sh "Charlotte Howlett"

# Audit scripts (temporary, not staged)
python3 _tmp_vitals_audit.py        # Layer 1-5 audit, all 5 patients
python3 _tmp_vitals_deep.py         # Arrival-day record inspection
python3 _tmp_selector_trace.py      # Step-by-step selector logic trace
```
