# NTDS Event Test Framework

## Overview

This directory contains testing infrastructure for validating NTDS 2026 event logic files against mock patient clinical data.

## Components

### Test Harness Scripts

1. **tests/test_ntds_simple.py** - Simplified standalone test runner
   - Evaluates basic event logic against patient fixtures
   - Supports `evidence_any` gates and simple exclusions
   - Limitations: Does not fully implement `timing_after_arrival` or `requires_treatment_any` gates

2. **tests/test_ntds_events.py** - Full test runner (requires complete engine)
   - Integrates with cerebralos.ntds_logic.engine
   - Requires: model.py, build_patientfacts_from_txt.py (not yet implemented)
   - Will provide complete evaluation when dependencies are available

### Test Fixtures

Location: `tests/fixtures/patients/`

Naming convention: `<event_id>_<slug>_<expected_outcome>.txt`

Examples:
- `08_dvt_yes.txt` - DVT case expecting YES outcome
- `08_dvt_no.txt` - DVT case expecting NO outcome
- `14_pe_excluded.txt` - PE case expecting EXCLUDED outcome
- `21_vap_unable.txt` - VAP case expecting UNABLE_TO_DETERMINE outcome

### Fixture Format

```
PATIENT_ID: TEST_<EVENT>_<NUMBER>
ARRIVAL_TIME: 2026-01-15 08:30:00

[SOURCE_TYPE] 2026-01-15 10:00:00
Clinical text goes here...

[IMAGING] 2026-01-17 14:30:00
Imaging findings...

[PHYSICIAN_NOTE] 2026-01-17 15:00:00
Physician assessment...
```

Source types: PHYSICIAN_NOTE, IMAGING, LAB, RADIOLOGY, NURSING_NOTE, etc.

## Usage

### List Available Fixtures

```bash
python3 tests/test_ntds_simple.py --list-fixtures
```

### Run Tests for Specific Event

```bash
python3 tests/test_ntds_simple.py --event 8
python3 tests/test_ntds_simple.py --event 14 --verbose
```

### Run All Tests

```bash
python3 tests/test_ntds_simple.py --event all
```

## Current Status

✅ **Completed:**
- Test harness framework created
- Fixture discovery and loading logic
- Sample fixtures for DVT (Event 8) and PE (Event 14)
- Basic gate evaluation for evidence_any gates
- Test result reporting with pass/fail summary

⚠️ **Known Limitations (Simplified Harness):**
- `timing_after_arrival` gates not fully implemented (need timestamp comparison logic)
- `requires_treatment_any` gates treated same as `evidence_any` (functional but not semantically distinct)
- `require_context_keys` exclusion logic not implemented (causes false positive exclusions)

🚧 **In Progress:**
- Full evaluator integration (requires engine dependencies)
- Complete fixture library for all 21 events
- Integration testing with actual Epic EHR exports

## Next Steps

1. **Complete Engine Dependencies:**
   - Implement cerebralos/ntds_logic/model.py (data classes for Evidence, PatientFacts, EventResult)
   - Implement cerebralos/ntds_logic/build_patientfacts_from_txt.py (parser for clinical text)

2. **Expand Fixture Library:**
   - Create positive/negative/excluded/unable test cases for each of 21 events
   - Focus on edge cases: timing boundaries, exclusion criteria, near-misses

3. **Add Integration Tests:**
   - Test with redacted real Epic exports
   - Validate against known manual chart review outcomes
   - Performance benchmarking for large patient datasets

4. **CI/CD Integration:**
   - Automate test runs on git push
   - Track test coverage per event
   - Regression detection for mapper pattern changes

## Design Philosophy

The test framework follows CerebralOS principles:
- **Deterministic**: Same input always produces same output
- **Fail-closed**: Ambiguous cases return UNABLE_TO_DETERMINE, never guess
- **Auditable**: Gate-by-gate trace shows evaluation logic
- **PHI-safe**: All fixtures use synthetic patient data

## File Structure

```
tests/
├── test_ntds_simple.py          # Simplified test runner
├── test_ntds_events.py          # Full test runner (requires engine)
├── README.md                     # This file
├── fixtures/
│   └── patients/
│       ├── 08_dvt_yes.txt
│       ├── 08_dvt_no.txt
│       ├── 14_pe_yes.txt
│       ├── 14_pe_no.txt
│       └── ... (expand to all 21 events)
└── results/                      # Test run outputs (git-ignored)
```

## Contributing

When adding new test fixtures:
1. Use the naming convention: `<event_id>_<slug>_<expected>.txt`
2. Include realistic clinical language matching mapper patterns
3. Annotate with source types and timestamps
4. Test both positive and negative cases
5. Include exclusion criteria tests where applicable

## Validation

Before considering an event "test-complete":
- [ ] Positive case (YES)
- [ ] Negative case (NO)
- [ ] Exclusion case (EXCLUDED)
- [ ] Uncertain case (UNABLE_TO_DETERMINE)
- [ ] Edge case: timing boundary
- [ ] Edge case: minimum evidence threshold
