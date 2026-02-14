# Report Generation Improvements Needed

## User Feedback
**"This output is horrible. The HTML especially, none of the words make any sense. I have no idea why any protocols was triggered or what any of that documentation references. it makes ZERO sense."**

## Core Problems

### 1. Generic Gate Names (CRITICAL)
**Current**: `REQ_TRIGGER_CRITERIA: PASS`
**Problem**: Means nothing to a clinician
**Needed**: Show WHAT was found in plain language

**Example transformation:**
```
BEFORE:
  REQ_TRIGGER_CRITERIA: PASS
    Trigger criteria satisfied

AFTER:
  TRIGGER CRITERIA: PASS
    Patient age 80 years with traumatic injury
    Mechanism: Fall from standing height at home
    Primary injury: Right shoulder fracture (proximal humerus)
```

### 2. Truncated Epic UI Garbage (CRITICAL)
**Current**: Evidence shows first 120 chars including UI text
**Problem**: "Signed Expand All Collapse All Trauma H &amp; P Austin..." is incomprehensible

**Example evidence currently shown:**
```
[TRAUMA_HP] 2025-12-17 18:59:00
  "Signed  Expand All Collapse All  Trauma H & P Austin Mark Buettner, PA-C   Alert History: Category 2 alert at 1822.  I a..."
```

**What's needed:**
- Skip Epic UI headers ("Signed", "Expand All", provider name lines)
- Extract actual clinical content (Chief Complaint, HPI, findings)
- Show relevant sentence/paragraph that matched the pattern

**After fix should show:**
```
[TRAUMA_HP] 2025-12-17 18:59:00
  "80 yo male with past medical history of stroke resulting in left-sided weakness presents after mechanical fall at home. Patient was ambulating and tripped over object on floor, falling onto right shoulder. Reports immediate pain and unable to move shoulder."
```

### 3. No Pattern Match Explanation (HIGH PRIORITY)
**Current**: Shows evidence but not WHY it's relevant
**Problem**: Can't understand why this evidence was selected

**What's needed:**
- Show which pattern(s) matched: e.g., "Matched pattern: geriatric_age_80plus"
- Show the matching text snippet: "80 yo male"
- Explain clinical relevance: "Triggers geriatric trauma protocol for patients ≥ 65 years"

### 4. Timing Failures Lack Detail (HIGH PRIORITY)
**Current**: "Timing-critical elements not documented or timing not met"
**Problem**: Doesn't explain WHAT constraint or WHEN violated

**Example transformation:**
```
BEFORE:
  REQ_TIMING_CRITICAL: FAIL
    Timing-critical elements not documented or timing not met

AFTER:
  TIMING REQUIREMENT: FAIL
    Surgery required within 48 hours of admission
    Patient admitted: 2025-12-17 18:11:00
    No operative procedure documented within 48-hour window
    Last evidence block timestamp: 2025-12-19 14:30:00 (no surgery found)
```

### 5. Historical Data False Triggers (CRITICAL FIX NEEDED)
**Example**: Dallas Clark (80yo with shoulder fracture) triggered "Geriatric Hip Fracture Guideline"
**Cause**: System matched "femur fracture surgery" from **8 months ago** in past surgical history

**What's needed:**
- Temporal filtering: Only match events within current admission timeframe
- Context requirements: Distinguish "History of femur fracture repair 8 months ago" from "Hip fracture on current admission"
- Negative patterns: Exclude historical references ("history of", "past surgical history", "previous", "8 months ago")

**Potential solutions:**
1. Add admission_window check to pattern matching (only evidence within N days of arrival)
2. Add negative context patterns to mapper: `"historical_procedure_exclusion": ["history of", "past surgical history", "previous.*months ago", "prior to admission"]`
3. Require procedures to be documented in OPERATIVE_NOTE or PROCEDURE blocks from current admission
4. Add temporal assertions to protocols: "procedure_during_current_admission"

## Files That Need Changes

### A. Evidence Selection (`cerebralos/protocol_engine/engine.py` or pattern matching)
- **Smart text extraction**: Skip Epic UI headers, extract clinical content
- **Pattern match tracking**: Track which specific pattern matched and show it
- **Temporal filtering**: Only match evidence within current admission window
- **Historical data exclusion**: Reject matches that reference past events

### B. Report Generation (`cerebralos/ingestion/batch_eval.py`)
- **_append_protocol_detail()** (lines 469-498):
  - Replace generic requirement IDs with human-readable labels
  - Show WHAT was found (clinical summary) in addition to pass/fail
  - For timing failures, explain the constraint and when violated
  - Better evidence snippet selection (not just [:120])

### C. HTML Report (`cerebralos/reporting/html_report.py`)
- **_build_protocol_card()** (lines 597-638):
  - Same improvements as text report
  - Add expand/collapse for "Why this matched" explanations
  - Highlight matched text within evidence snippets
  - Show temporal timeline for timing failures

### D. Protocol Definitions (`rules/deaconess/protocols_deaconess_structured_v1.json`)
- Add human-readable `requirement_label` field for each requirement
- Add `timing_explanation` for timing-critical requirements
- Add `trigger_explanation` template that can be filled with extracted values

### E. Mapper Patterns (`rules/mappers/epic_deaconess_mapper_v1.json`)
- Add negative patterns for historical exclusions
- Add context requirements for current-admission-only matching
- Consider pattern priority/specificity scoring

## Example: Before vs After (Dallas Clark Case)

### BEFORE (Current Output)
```
[NON_COMPLIANT] Geriatric Hip Fracture Guideline
  REQ_TRIGGER_CRITERIA: PASS
    Trigger criteria satisfied
    Evidence (8 items):
      [TRAUMA_HP] 2025-12-17 18:59:00
        "Signed  Expand All Collapse All  Trauma H & P Austin Mark Buettner, PA-C   Alert History: Category 2 alert at 1822.  I a..."

  REQ_TIMING_CRITICAL: FAIL
    Timing-critical elements not documented or timing not met
```

### AFTER (Improved Output)
```
[SHOULD NOT HAVE TRIGGERED] Geriatric Hip Fracture Guideline
  TRIGGER CRITERIA: MATCH (BUT INCORRECT)
    Patient age: 80 years ✓ (qualifies for geriatric protocol)
    Hip/femur fracture: HISTORICAL DATA ONLY ⚠

    Evidence from CURRENT admission (2025-12-17):
      [TRAUMA_HP] 2025-12-17 18:59:00
        "80 yo male with past medical history of stroke resulting in left-sided weakness
        presents after mechanical fall at home. Patient was ambulating and tripped over
        object on floor, falling onto right shoulder. Right shoulder pain and limited ROM."

      [IMAGING] 2025-12-17 21:45:00
        "RIGHT SHOULDER XRAY: Comminuted fracture of the proximal humerus with minimal
        displacement. No evidence of hip or femur fracture."

    ⚠ SYSTEM DETECTED: Reference to "femur fracture surgery 8 months ago" in past surgical
    history - this is HISTORICAL and should NOT trigger current admission protocol

    CURRENT INJURY: Right shoulder (proximal humerus) fracture - NOT hip/femur

  CONCLUSION: Protocol triggered incorrectly due to historical data match.
              Patient has shoulder fracture, not hip/femur fracture.
```

## Priority Ranking

1. **CRITICAL** (Fix immediately):
   - Historical data false triggers (affects clinical accuracy)
   - Smart evidence extraction (current output is unreadable)

2. **HIGH** (Fix soon):
   - Pattern match explanations (needed for understanding)
   - Timing failure details (needed for clinical decisions)

3. **MEDIUM** (Enhancement):
   - Human-readable requirement labels
   - Trigger explanation templates

## Implementation Approach

### Phase 1: Evidence Cleanup (1-2 hours)
- Add `_clean_evidence_text()` function to skip Epic UI headers
- Extract clinical content sections (Chief Complaint, HPI, Assessment, etc.)
- Test on Dallas Clark to verify readable output

### Phase 2: Historical Data Filter (2-3 hours)
- Add temporal window check: only match evidence within X days of arrival
- Add negative patterns to mapper for historical references
- Add context requirements: procedures must be in current admission operative notes
- Test on Dallas Clark to verify hip fracture guideline no longer triggers

### Phase 3: Enhanced Explanations (3-4 hours)
- Track which patterns matched and include in step_trace
- Generate human-readable summaries for each requirement
- Add timing constraint explanations for failures
- Update both text and HTML report generators

### Phase 4: Protocol Definition Enhancements (2-3 hours)
- Add `requirement_label`, `timing_explanation`, `trigger_explanation` fields to protocols
- Update evaluation engine to use these fields in results
- Update report generators to display rich explanations

## Testing Strategy
- Use Dallas Clark as primary test case (should NOT trigger Hip Fracture guideline)
- Verify text reports are human-readable
- Verify HTML reports make clinical sense
- Test on all existing patient files to ensure no regressions
