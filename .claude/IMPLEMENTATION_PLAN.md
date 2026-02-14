# CerebralOS Implementation Plan — Data Accuracy + Reporting Quality

## Status Summary

| Phase | Description | Status |
|-------|-------------|--------|
| 1A | Epic Evidence Text Cleanup | COMPLETED |
| 1B | Historical Data False Trigger Fix | COMPLETED |
| 2 | Device Tracking (extraction, timeline, formatting) | COMPLETED |
| 3B | MatchDetail model + match_evidence_with_details() | COMPLETED |
| 3C | Timing Failure Details | COMPLETED |
| 3D | batch_eval match_details serialization | COMPLETED |
| 4A | Vitals Extraction | COMPLETED |
| 4B | Daily Notes Structure (per-day hemodynamics/labs/devices/imaging) | COMPLETED |
| 5A | Python CLI (__main__.py) | COMPLETED |
| 5B | Excel PI Tracking Columns | COMPLETED |
| 5C | Failure Log (governance/failure_log.py) | COMPLETED |
| 5D | Governance Version in Outputs | COMPLETED |
| 6 | Integration Testing + Validation | COMPLETED |

---

## Phase 1: Epic Evidence Cleanup + Historical Data Filtering

**Goal:** Fix the two most critical data accuracy problems — garbage text in evidence and false triggers from historical data.

### 1A: Evidence Text Cleanup

**File:** `cerebralos/reporting/evidence_utils.py`

- `clean_evidence_text()` — strips Epic UI noise ("Signed", "Expand All", "Collapse All", provider attestation blocks, navigation elements)
- `extract_clinical_content()` — identifies and extracts clinical sections (HPI, Assessment, Impression, Findings)
- `_EPIC_NOISE_PATTERNS` — 13 line-level noise patterns
- `_EPIC_INLINE_NOISE` — 6 inline noise patterns
- `_is_noise_line()` — smart line classification
- `extract_hp_sections()` — extracts HPI, Assessment, etc.

**File:** `cerebralos/ingestion/batch_eval.py`

- `_serialize_protocol_evidence()` and `_serialize_ntds_evidence()` apply `clean_evidence_text()` BEFORE truncation
- Stores both `text_raw` (original) and `text` (cleaned) in output

### 1B: Historical Data False Trigger Fix

**File:** `cerebralos/protocol_engine/engine.py`

- `_HISTORICAL_PATTERNS` — 19 regex patterns for historical references
- `_is_historical_reference()` — checks for history markers
- `_is_match_in_historical_context()` — context-aware checking:
  - Looks back 400 chars for section markers ("Past Surgical History", "PMH:", etc.)
  - Detects when you've left a history section
  - Checks inline historical markers within 100 chars
  - Detects date-based historical context ("4 months ago", etc.)
  - Checks for past-tense procedure language
- `match_evidence()` — includes `skip_historical=True` parameter by default
- `match_evidence_with_details()` — tracks which patterns matched and why
- Temporal filtering with `admission_window_hours` parameter (default 24 hours)

**Verification:** Dallas Clark — Geriatric Hip Fracture protocol correctly NOT_TRIGGERED (was previously false-triggering from "femur fracture surgery 8 months ago" in past surgical history).

---

## Phase 2: Device Tracking

**Goal:** Track all invasive devices — what, when placed, when removed, how many days.

**New file:** `cerebralos/reporting/devices.py`

- `DeviceEvent` dataclass — device_type, device_subtype, action, timestamp, source_type, source_text, location
- `DeviceTimeline` dataclass — device_type, device_subtype, placed, removed, days_in_place, events
- `extract_device_events(evidence_blocks)` — regex-based extraction from all evidence types
- `build_device_timelines(events)` — group events by device, calculate duration
- `format_device_report(timelines)` — human-readable device summary

**Device types:** CVC, PICC, Arterial Line, Foley, Chest Tube, NG/OG Tube, ET Tube
**Actions detected:** PLACED, REMOVED, DOCUMENTED_IN_SITU

---

## Phase 3: Human-Readable Protocol Output

**Goal:** Make protocol results comprehensible to clinicians — explain WHAT triggered, WHY, and WHAT timing constraint failed.

### 3B: Pattern Match Tracking

**File:** `cerebralos/protocol_engine/model.py`

- `MatchDetail` dataclass — pattern_key, matched_text, context (200 chars)
- Added `match_details` field to `StepResult`

**File:** `cerebralos/protocol_engine/engine.py`

- `match_evidence_with_details()` — returns MatchDetail objects tracking which patterns matched

### 3C: Timing Failure Details

**File:** `cerebralos/protocol_engine/engine.py`

- Timing failures now show: pattern key, evidence timestamp, arrival time, window requirement
- Example: `"protocol_dvt_within_24_hours: evidence found at 2025-12-19 14:30:00 but required within 24 hours of arrival"`

### 3D: Report Integration

**File:** `cerebralos/reporting/protocol_explainer.py`

- `explain_pattern_key()` — converts `protocol_tbi_gcs_documented@TRAUMA_HP` to plain language
- `_PATTERN_DESCRIPTIONS` — 60+ pattern translations
- `explain_requirement()` — maps requirement IDs to plain language (REQ_TRIGGER_CRITERIA -> "Protocol Trigger", etc.)

**File:** `cerebralos/ingestion/batch_eval.py`

- `_append_protocol_detail()` includes match_details, human-readable requirement names
- Evidence snippets cleaned via `get_clean_snippet()`

---

## Phase 4: Daily Notes Enhancement

**Goal:** Per-calendar-day notes must include numeric vitals, numeric labs, device status, and verbatim imaging impressions.

### 4A: Vitals Extraction

**New file:** `cerebralos/reporting/vitals.py`

- `VitalSign` dataclass — name, value, timestamp, source_type
- `extract_vitals(evidence_blocks, target_date)` — regex-based extraction
- `format_vitals_summary(vitals)` — human-readable summary
- Patterns: HR, BP, RR, SpO2, Temp, MAP, GCS

### 4B: Daily Notes Structure

**File:** `cerebralos/reporting/narrative_report.py`

Per-day structure:
```
## Hospital Day X (YYYY-MM-DD)
### Hemodynamics — HR, BP, RR, SpO2, Temp, MAP (or "Vitals not documented")
### Labs — Hgb, Plt, Cr, Lactate, INR (or "No labs documented")
### Devices — Active devices with day count
### Imaging — Verbatim radiologist impression
### Clinical Notes — Source-attributed content
### Disposition Status
```

---

## Phase 5: Workflow + Infrastructure

### 5A: Python CLI Entry Point

**New file:** `cerebralos/__main__.py`

- `python -m cerebralos run <patient.txt>`
- `python -m cerebralos run-all`
- `python -m cerebralos live <patient.txt>`
- `python -m cerebralos excel`
- `python -m cerebralos help`

### 5B: Excel PI Tracking Columns

**File:** `cerebralos/reporting/excel_dashboard.py`

5 new columns (operator-only, never auto-populated):
- ImageTrend Status — dropdown: Not Started / In Progress / Complete
- PI Review Status — dropdown: Pending / In Review / Reviewed / Presented
- PI Committee Date
- Reviewer Notes
- Last PI Update

Data validation dropdowns via openpyxl `DataValidation`. PI columns preserved across engine re-runs (append-not-overwrite).

### 5C: Failure Log

**New files:** `cerebralos/governance/__init__.py`, `cerebralos/governance/failure_log.py`

- `FailureEntry` dataclass — timestamp, section, category, description, command, detection_source, patient_id, protocol_id, metadata
- `FailureLog` class — append-only JSON Lines at `outputs/failure_log.jsonl`
- Convenience functions: `log_unanchored_evidence()`, `log_missing_required_element()`, `log_negation_miss()`, `log_historical_false_trigger()`
- Observational only — never modifies execution behavior

### 5D: Governance Version in Outputs

**File:** `cerebralos/__init__.py`

```python
__version__ = "1.0.0"
GOVERNANCE_VERSION = "v2026.01"
ENGINE_VERSION = __version__
RULES_VERSIONS = {"ntds": "2026_v1", "protocols": "deaconess_v1.1.0"}
```

Imported and included in all `evaluate_patient()` return dicts and report footers.

---

## Phase 6: Integration Testing + Validation

### Test Results (All Passed)

| Test | Result |
|------|--------|
| pytest (12 unit tests) | 12/12 passed |
| Dallas Clark (historical data test) | Hip Fracture correctly NOT_TRIGGERED |
| All 22 patients batch run | 0 crashes, 0 errors |
| Python CLI | Works (`python -m cerebralos help`) |
| Governance version | Present in all JSON outputs |

### Aggregate Results (22 patients)
- Protocols: 152 triggered, all COMPLIANT, 0 NON_COMPLIANT
- NTDS: 0 YES events, 391 NO, 4 EXCLUDED, 23 UNABLE_TO_DETERMINE
- 3 LIVE patients detected (no discharge): Lolita Calcia, Ronald Marshall, Timothy Cowan

---

## Files Created (5)

| File | Purpose |
|------|---------|
| `cerebralos/reporting/devices.py` | Device extraction + timeline |
| `cerebralos/reporting/vitals.py` | Vital sign extraction |
| `cerebralos/__main__.py` | Python CLI entry point |
| `cerebralos/governance/__init__.py` | Governance package |
| `cerebralos/governance/failure_log.py` | Append-only failure log |

## Files Modified

| File | Changes |
|------|---------|
| `cerebralos/reporting/evidence_utils.py` | Epic noise cleanup, clinical content extraction |
| `cerebralos/protocol_engine/engine.py` | Historical filtering, admission window, match tracking |
| `cerebralos/protocol_engine/model.py` | MatchDetail dataclass added to StepResult |
| `cerebralos/reporting/narrative_report.py` | Daily notes with vitals/labs/devices per day |
| `cerebralos/reporting/html_report.py` | Human-readable protocol cards |
| `cerebralos/ingestion/batch_eval.py` | Clean evidence, match_details, governance version |
| `cerebralos/reporting/excel_dashboard.py` | PI tracking columns with dropdowns |
| `cerebralos/__init__.py` | Version constants |

## Design Principles

- **Deterministic evaluation**: Same input -> same output, no inference
- **Fail-closed**: Missing data -> UNABLE_TO_DETERMINE or INDETERMINATE, never guess
- **Append-not-overwrite**: Excel dashboard preserves operator-entered PI data across re-runs
- **Operator-only fields**: PI tracking columns never auto-populated by engine
- **Append-only failure log**: JSON Lines, observational only, never modifies execution
- **Evidence proxy pattern**: Lightweight objects to make snippet dicts look like evidence objects
