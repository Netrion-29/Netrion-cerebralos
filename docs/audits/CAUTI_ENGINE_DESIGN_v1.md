# CAUTI Engine Design — LDA Duration Gate & Alternative-Source Exclusion

| Field       | Value                                                    |
|-------------|----------------------------------------------------------|
| Date        | 2026-03-11                                               |
| Author      | Design doc (Copilot / Sarah)                             |
| Status      | DRAFT — requires engine-change authorization             |
| Baseline    | `8a51e35` (main)                                         |
| Depends on  | PR #188 (E05 CAUTI Tier-1), PR #190 (culture/symptom follow-up) |

---

## 1. Problem Statement

### 1a. LDA-Based Catheter Duration Gate

CDC SUTI 1a (NTDS 2026 E05 CAUTI) requires:

> "An indwelling urinary catheter was in place for **>2 consecutive
> calendar days** on the date of event."

The current implementation (`cauti_catheter_gt2d` gate in
`rules/ntds/logic/2026/05_cauti.json`) uses `gate_type: evidence_any`
with text patterns in `cauti_catheter_in_place` (9 mapper patterns).
This approach has inherent limitations:

1. **Duration cannot be verified.** Text patterns can detect mentions of
   a catheter being in place, but cannot compute whether the catheter
   was present for >2 consecutive calendar days. A note stating "Foley
   catheter in place" on Day 1 satisfies the pattern match, but says
   nothing about Day 2 or Day 3.

2. **Insertion/removal dates are in LDA data, not clinical prose.** Epic
   Lines/Drains/Airways (LDA) records contain structured `placed_ts` and
   `removed_ts` timestamps. The existing feature layer
   (`cerebralos/features/lda_events_v1.py`, 1097 lines) already parses
   these from two raw formats (Summary LDA and Event-log Active LDA)
   and produces per-device records with `placed_ts`, `removed_ts`,
   `duration_text`, `site`, and `device_type`.

3. **"LDA" in `allowed_sources` is a dead reference.** The
   `cauti_catheter_gt2d` gate currently lists `"LDA"` in
   `allowed_sources`, but `SourceType` (`cerebralos/ntds_logic/model.py`
   line 37) has only 14 values — none is `LDA`. The `match_evidence()`
   function (engine line 82) filters evidence by `e.source_type.name`
   against the allowed set, so the `"LDA"` entry silently matches
   nothing.

4. **LDA feature data is not wired into PatientFacts.** The LDA feature
   layer operates independently — it reads the raw `.txt` file directly
   (via `meta.source_file`), produces structured device records in
   `features/lda_events_v1`, and stores its own `raw_line_id` hashes.
   This output is never ingested into the `PatientFacts.evidence` list
   that the NTDS engine consumes.

### 1b. Alternative-Source Exclusion

Some NTDS events should exclude evidence from specific documentation
sources rather than requiring it from them. For example, a rule might
want to state: "Exclude catheter mentions that appear only in DISCHARGE
summaries (commonly retrospective)" or "Exclude evidence that appears
only in a single low-confidence source type."

The current engine supports:
- `exclude_if_any` / `exclude_noise_keys` — excludes based on **content
  patterns** (text matches), not evidence source.
- `allowed_sources` — **includes** evidence from listed sources, but
  there is no `excluded_sources` or `exclude_if_only_source` mechanism.

There is no gate type or field that allows excluding evidence based on
which `SourceType` it came from.

---

## 2. Proposed Design: LDA-Based Catheter Duration Gate

### 2a. New SourceType: `LDA`

Add a new enum value to `SourceType` in `cerebralos/ntds_logic/model.py`:

```python
class SourceType(Enum):
    # ... existing 14 values ...
    LDA = "LDA"  # Lines/Drains/Airways structured data
```

This allows the engine to recognize `"LDA"` in `allowed_sources` and
enables LDA evidence to flow through `match_evidence()`.

### 2b. Wire LDA Device Data into PatientFacts

Two integration approaches (choose one):

#### Option A: Synthesize Evidence Lines (recommended)

During `PatientFacts` construction (in
`cerebralos/ntds_logic/build_patientfacts_from_txt.py`), after the
standard line-by-line parse:

1. Run the LDA feature extractor (`extract_lda_events()`) against the
   same source file.
2. For each device record, synthesize one `Evidence` item:
   - `source_type = SourceType.LDA`
   - `timestamp = placed_ts` (insertion timestamp)
   - `text` = a canonical string encoding the device data, e.g.:
     `"LDA: Foley Catheter | placed: 2026-01-15T08:30 | removed: 2026-01-19T14:00 | duration: 4d 5h"`
   - `pointer` = reference back to the raw LDA section lines
3. Append these synthesized `Evidence` items to `patient.evidence`.

**Advantages:** Minimal engine changes — existing `match_evidence()` can
regex-match against the synthesized text. The `evidence_any` gate would
still work for basic catheter detection.

**Disadvantages:** Duration semantics (>2 calendar days) still require
regex parsing of the synthesized text string, which is fragile.

#### Option B: Structured Gate Type (full solution)

Add a new gate type `lda_catheter_duration` to the engine dispatch
(engine.py line 350–358):

```python
elif gt == "lda_catheter_duration":
    gr = eval_lda_catheter_duration(gate, patient, contract)
```

The evaluator would:

1. Access LDA device data from `patient.facts["lda_devices"]` (a new
   field populated during `PatientFacts` construction).
2. Filter devices by `device_type` matching gate-specified patterns
   (e.g., `"foley"`, `"indwelling"`, `"urinary catheter"`).
3. For each matching device with valid `placed_ts`:
   - Compute `removal_or_now = removed_ts or discharge_date or current_run_date`
   - Calculate calendar days: `(removal_or_now.date() - placed_ts.date()).days`
   - Check: `calendar_days > gate["min_calendar_days"]` (default: 2)
4. If any device passes the duration threshold, the gate passes.
5. Optionally check overlap with admission: device must be in place on
   or after `arrival_time`.

**Gate JSON (proposed):**

```json
{
  "gate_type": "lda_catheter_duration",
  "gate_id": "cauti_catheter_gt2d",
  "gate_name": "Indwelling urinary catheter >2 calendar days (LDA-verified)",
  "required": true,
  "device_patterns": ["foley", "indwelling.*catheter", "urinary catheter"],
  "min_calendar_days": 2,
  "arrival_field": "arrival_time",
  "fail_outcome": "NO",
  "fail_reason": "No LDA evidence of indwelling urinary catheter in place for >2 calendar days."
}
```

**Advantages:** Precise, deterministic duration calculation. No regex
hacking on synthesized text. Directly models the CDC criterion.

**Disadvantages:** Requires a new gate type in PROTECTED engine code.

### 2c. Recommended Approach

**Phase 1 (Option A):** Wire LDA device data as synthesized `Evidence`
lines with `SourceType.LDA`. This makes the existing `"LDA"` in
`allowed_sources` functional and allows basic catheter-mention detection
from structured data. Changes required:

| File | Change | Protected |
|------|--------|-----------|
| `cerebralos/ntds_logic/model.py` | Add `LDA` to `SourceType` | No (data model) |
| `cerebralos/ntds_logic/build_patientfacts_from_txt.py` | Import LDA extractor, synthesize `Evidence` items | Partially (builder, not engine) |
| `rules/mappers/epic_deaconess_mapper_v1.json` | Add patterns for synthesized LDA text | No |

**Phase 2 (Option B):** After Phase 1 proves the LDA data pipeline, add
`lda_catheter_duration` gate type for precise >2-day computation.
Requires explicit engine-change authorization:

| File | Change | Protected |
|------|--------|-----------|
| `cerebralos/ntds_logic/engine.py` | Add `eval_lda_catheter_duration()` + dispatch entry | **YES** |
| `rules/ntds/logic/2026/05_cauti.json` | Change gate type from `evidence_any` to `lda_catheter_duration` | No |

### 2d. Fallback Strategy

If LDA data is absent or unparseable for a patient (e.g., older Epic
exports without LDA sections), the gate should fall back to
text-pattern matching (current behavior). Implementation:

- Phase 1: Automatic — if no LDA `Evidence` items are synthesized, the
  existing text patterns in `cauti_catheter_in_place` still match
  against clinical prose from other `SourceType`s.
- Phase 2: The `eval_lda_catheter_duration()` function should check
  `patient.facts.get("lda_devices")`. If empty/absent, delegate to
  `eval_evidence_any()` with the same gate config as a fallback.

### 2e. Why Text-Only Is Insufficient

| Limitation | Impact |
|------------|--------|
| Cannot compute calendar days from prose | Catheter described on Day 1 may not be documented on Day 2–3; gate incorrectly passes on single mention |
| Free-text duration phrases are ambiguous | "Foley catheter x3 days" vs "Foley catheter placed 3 days ago" vs "day 3 of Foley" — all require different parsing |
| Time-of-event date depends on placement date | CDC criterion ties the date-of-event to Day 3 (day after >2 days); prose mentions don't carry computed dates |
| False negatives on short stays | Patient admitted <48h with catheter — text mentions catheter but <2 calendar days; current text gate would incorrectly pass |
| LDA data exists but is unused | The feature layer already parses `placed_ts`, `removed_ts`, `duration_text` — ignoring this is a data waste |

---

## 3. Proposed Design: Alternative-Source Exclusion

### 3a. Definition

Alternative-source exclusion allows a gate rule to specify that evidence
matching from certain documentation sources should be **excluded** or
**deprioritized**. This is distinct from:

- `allowed_sources` (inclusion filter — "only accept evidence from these")
- `exclude_noise_keys` (content filter — "reject evidence matching these patterns")

Use case: "Exclude catheter mentions if they appear **only** in
DISCHARGE summaries, which may be retrospective documentation rather
than real-time clinical observation."

### 3b. Required Engine Capability

Two possible implementations:

#### Option 1: `excluded_sources` field (simple)

Add an `excluded_sources` field to gate definitions, processed in
`match_evidence()`:

```python
def match_evidence(patient, query_key, allowed_sources=None,
                   excluded_sources=None, max_hits=8):
    # ...
    excluded_set = set(excluded_sources) if excluded_sources else None
    for e in patient.evidence:
        if allowed_set and e.source_type.name not in allowed_set:
            continue
        if excluded_set and e.source_type.name in excluded_set:
            continue
        # ... regex match ...
```

**Gate JSON:**
```json
{
  "gate_type": "evidence_any",
  "gate_id": "cauti_catheter_gt2d",
  "query_keys": ["cauti_catheter_in_place"],
  "allowed_sources": ["NURSING_NOTE", "PHYSICIAN_NOTE", "LDA", ...],
  "excluded_sources": ["DISCHARGE"],
  "fail_outcome": "NO"
}
```

**Advantages:** Minimal engine change (2 lines in `match_evidence`).
Backward-compatible — `excluded_sources` defaults to `None`.

**Disadvantages:** Binary exclude/include. Cannot express "exclude if
ONLY from DISCHARGE" (evidence exists in DISCHARGE but also in
PHYSICIAN_NOTE should still pass).

#### Option 2: `exclude_if_only_source` gate modifier (semantic)

Add a post-filter step: after collecting hits from `match_evidence()`,
check whether ALL hits came from a single excluded source type:

```python
if gate.get("exclude_if_only_source"):
    excluded = set(gate["exclude_if_only_source"])
    source_types_in_hits = {h.source_type.name for h in hits}
    if source_types_in_hits and source_types_in_hits.issubset(excluded):
        hits = []  # all evidence is from excluded-only sources
```

This is more nuanced: "We have catheter evidence, but ALL of it comes
from DISCHARGE summaries — treat as insufficient."

**Gate JSON:**
```json
{
  "gate_type": "evidence_any",
  "gate_id": "cauti_catheter_gt2d",
  "query_keys": ["cauti_catheter_in_place"],
  "allowed_sources": ["NURSING_NOTE", "PHYSICIAN_NOTE", "LDA", "DISCHARGE"],
  "exclude_if_only_source": ["DISCHARGE"],
  "fail_outcome": "NO"
}
```

### 3c. Example Scenarios

| Scenario | Current Behavior | With `exclude_if_only_source` |
|----------|-----------------|------------------------------|
| Catheter mentioned in NURSING_NOTE + DISCHARGE | Gate passes (evidence_any) | Gate passes (NURSING_NOTE is not excluded) |
| Catheter mentioned ONLY in DISCHARGE | Gate passes (evidence_any) | Gate **fails** (all evidence from excluded-only source) |
| Catheter mentioned ONLY in PHYSICIAN_NOTE | Gate passes | Gate passes (PHYSICIAN_NOTE not in excluded set) |
| No catheter evidence at all | Gate fails | Gate fails (no change) |

### 3d. Risks and Considerations

| Risk | Mitigation |
|------|------------|
| Over-exclusion could cause false negatives | Start with `exclude_if_only_source` (softer) rather than hard `excluded_sources` |
| Backward compatibility | New fields default to `None`/empty — existing rules unaffected |
| Gate complexity growth | Document clearly which gates use source exclusion; audit trail in rule JSON comments |
| Cross-event applicability | Design is generic — could apply to any `evidence_any` gate, not just CAUTI; document scope boundaries per event |

---

## 4. Impact Assessment

### 4a. Files Requiring Modification (Engine-Protected)

| File | Change | Risk |
|------|--------|------|
| `cerebralos/ntds_logic/engine.py` (645 lines, **PROTECTED**) | New gate type + `match_evidence` excluded_sources param | Medium — core dispatch logic, requires full regression |
| `cerebralos/ntds_logic/model.py` | Add `LDA` to `SourceType` enum | Low — additive, no existing code affected |
| `cerebralos/ntds_logic/build_patientfacts_from_txt.py` | Import + call LDA feature extractor, append synthesized Evidence | Medium — builder changes affect all patients |

### 4b. Files NOT Requiring Engine Authorization

| File | Change | Risk |
|------|--------|------|
| `rules/ntds/logic/2026/05_cauti.json` | Update gate config (type, fields) | Low |
| `rules/mappers/epic_deaconess_mapper_v1.json` | Add LDA-text patterns if using Option A | Low |
| `tests/test_e05_cauti_precision.py` | Add LDA-aware test cases | Low |
| New fixtures in `tests/fixtures/ntds/` | LDA-specific test patients | None |

### 4c. Expected Outcome Deltas

- **Phase 1 (SourceType + synthesized Evidence):** Likely 0 outcome
  deltas — the existing text patterns already cover catheter mentions
  in clinical prose. LDA evidence adds redundant confirmation.
- **Phase 2 (duration gate):** Potentially 0–4 outcome deltas in the
  current 39-patient cohort. Patients currently matching on a single
  catheter mention without >2-day evidence might shift from YES/UTD to
  NO. This is a **precision improvement** (fewer false positives).
- **Alternative-source exclusion:** Likely 0 outcome deltas for CAUTI
  in the current cohort. Primary value is future-proofing for edge
  cases.

---

## 5. Migration Plan

### 5a. Phased Rollout

| Phase | Scope | Engine Auth | PR |
|-------|-------|-------------|-----|
| Phase 0 (this PR) | Design doc only — no code changes | No | Current |
| Phase 1 | Add `LDA` SourceType + wire LDA into PatientFacts | Partial (`model.py` + `build_patientfacts`) | Future |
| Phase 2a | Add `excluded_sources` / `exclude_if_only_source` to `match_evidence()` | **Yes** (engine.py) | Future |
| Phase 2b | Add `lda_catheter_duration` gate type | **Yes** (engine.py) | Future |
| Phase 3 | Update E05 CAUTI rule to use new gate type + source exclusion | No | Future |

### 5b. Backward Compatibility

- **New SourceType `LDA`:** Additive — no existing code references `LDA`
  (the dead reference in `allowed_sources` becomes functional, which is
  the intended behavior).
- **New gate type `lda_catheter_duration`:** Additive — existing gate
  types unchanged. The engine dispatch falls through to "Unknown gate_type"
  for unrecognized types, so adding a new one is safe.
- **`excluded_sources` / `exclude_if_only_source`:** New optional fields
  with `None` default — existing rules unaffected.
- **LDA synthesized Evidence in PatientFacts:** Additive — existing
  `match_evidence()` already handles any SourceType in the enum. New
  Evidence items are simply additional entries in the list.

### 5c. Testing Strategy

| Test Layer | What to Test |
|------------|-------------|
| Unit: LDA parsing | `lda_events_v1.py` already has implicit coverage; add explicit pytest for `placed_ts` / `removed_ts` extraction |
| Unit: SourceType | Verify `SourceType.LDA` resolves correctly |
| Unit: `match_evidence` | Test `excluded_sources` / `exclude_if_only_source` filtering |
| Unit: duration gate | Mock `PatientFacts` with LDA devices, test >2 day / ≤2 day / missing data branches |
| Integration: E05 CAUTI | Full cohort run (39 patients) pre/post, compare distributions |
| Regression: all 21 events | `gate_pr.sh` — no other event should be affected |

---

## 6. Decision Required

This design doc requires **engine-change authorization** before
implementation can proceed. Specifically:

1. **Approve `LDA` SourceType addition** in `model.py`
2. **Approve `build_patientfacts` modification** to wire LDA feature data
3. **Approve engine.py modification** for:
   - `excluded_sources` parameter in `match_evidence()`
   - `lda_catheter_duration` gate type and evaluator function

Until authorized, the current text-pattern approach
(`cauti_catheter_in_place` with 9 patterns via `evidence_any`) remains
the active implementation. This is functional but cannot verify the >2
calendar day duration criterion.

---

## 7. References

| Item | Location |
|------|----------|
| NTDS 2026 E05 CAUTI spec | `rules/ntds/structured/2026/E05_CAUTI_structured_v1.md` |
| Current E05 rule | `rules/ntds/logic/2026/05_cauti.json` |
| LDA feature layer | `cerebralos/features/lda_events_v1.py` (1097 lines) |
| NTDS engine | `cerebralos/ntds_logic/engine.py` (645 lines, PROTECTED) |
| SourceType model | `cerebralos/ntds_logic/model.py` line 37 |
| PatientFacts builder | `cerebralos/ntds_logic/build_patientfacts_from_txt.py` |
| E05 mapper patterns | `rules/mappers/epic_deaconess_mapper_v1.json` (8 CAUTI keys) |
| E05 precision tests | `tests/test_e05_cauti_precision.py` |
| Source alignment design | `docs/audits/SOURCE_ALIGNMENT_AND_GERI_DELIRIUM_v1.md` |

---

_End of document._
