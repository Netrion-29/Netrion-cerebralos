# Protocol Coverage Audit v1

**Date:** 2026-03-05
**Branch:** `tier2/protocol-coverage-fixes-v1`

## Summary

Comprehensive audit of protocol validator, protocol index, structured definitions,
test fixtures, and source PDFs. Identified and cleaned stale artifacts from the
v1.1.0 protocol restructuring that removed `ROLE_OF_TRAUMA_SERVICES`.

## Findings

### 1. Stale Artifacts Removed

| Artifact | File | Action |
|----------|------|--------|
| `role_trauma` prefix mapping | `cerebralos/validation/validate_all_protocols.py` | Removed |
| `ROLE_OF_TRAUMA_SERVICES_IN_THE_ADMISSION_OR_CONSULTATION_OF_TRAUMA_PATIENTS` entry | `rules/deaconess/protocol_index_v1.json` | Removed |
| `role_trauma_compliant.txt` | `tests/fixtures/protocols/` | Deleted |
| `role_trauma_indeterminate.txt` | `tests/fixtures/protocols/` | Deleted |
| `role_trauma_not_triggered.txt` | `tests/fixtures/protocols/` | Deleted |

**Rationale:** `ROLE_OF_TRAUMA_SERVICES` was removed from
`protocols_deaconess_structured_v1.json` in v1.1.0. The index (44 entries) was
out of sync with structured (43 entries). Now both have 43 protocols.

### 2. CONTEXT_ONLY Protocols — No Fixtures Needed

Seven protocols in structured JSON have no test fixtures. All are `CONTEXT_ONLY`
(no evaluable compliance rules), so no fixtures are expected:

1. `MANAGEMENT_OF_THE_ORTHOPEDICNEUROLOGIC_SPLINT_ANDOR_BRACE`
2. `REHABILITATIVE_SERVICES_AND_DISCHARGE_PLANNING`
3. `RESUSCITATION_ROLE_ASSIGNMENTS`
4. `SPECIAL_CONSIDERATION_PEDIATRIC`
5. `TRANSFER_FROM_DEACONESS`
6. `TRANSFER_TO_DEACONESS`
7. `TRAUMA_SURGEON_CONSULT`

### 3. Keyword Fallback Usage

33 of 36 evaluable protocols use keyword-based fallback matching (no structured
pattern maps wired yet). This is expected — pattern map wiring is a future phase.
The validator reports these as warnings, not errors.

### 4. Fixture Test Baseline

- **54 PASS / 40 FAIL** (pre-existing engine issues)
- The 40 failures are pre-existing protocol engine limitations, not regressions.
- The protocol engine is PROTECTED and not in scope for this PR.

### 5. PDF Naming Note

Source PDF `Vascular Emergency Guideline.pdf` corresponds to protocol ID
`VASCULAR_INTERVENTION_GUIDELINE`. The content matches; the naming difference
is cosmetic and does not affect functionality. No action needed.

## Post-Fix Validation

- Protocol validator: 43 protocols loaded, 0 errors
- Protocol index: 43 entries (synced with structured JSON)
- Prefix map: 35 entries (stale `role_trauma` removed)
- Cohort invariant: PASS
