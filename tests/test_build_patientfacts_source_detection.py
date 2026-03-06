"""
Regression tests for source-detection changes in build_patientfacts_from_txt.

Covers:
  - LAB\\b word-boundary anchor (prevents LABBILI, LABALBU, etc.)
  - MAR\\b word-boundary anchor (prevents MARITAL, MARKER, etc.)
  - _BLOCK_WORDS filter (PATIENT, DISPOSITION, PROVIDER, PLANNING)
  - Preservation of existing valid headers
"""

import pytest

from cerebralos.ntds_logic.build_patientfacts_from_txt import (
    _detect_source_type,
    _is_section_header,
)
from cerebralos.ntds_logic.model import SourceType


# ---------------------------------------------------------------------------
# LAB word-boundary tests
# ---------------------------------------------------------------------------
class TestLabWordBoundary:
    """LAB\\b must match LAB, LABS, LAB FLOWSHEET but not LABBILI, LABALBU."""

    def test_lab_bare(self):
        assert _detect_source_type("LAB", SourceType.UNKNOWN) == SourceType.LAB

    def test_lab_colon(self):
        assert _detect_source_type("LAB:", SourceType.UNKNOWN) == SourceType.LAB

    def test_labs_colon(self):
        assert _detect_source_type("LABS:", SourceType.UNKNOWN) == SourceType.LAB

    def test_lab_flowsheet(self):
        assert _detect_source_type("LAB FLOWSHEET", SourceType.UNKNOWN) == SourceType.LAB

    def test_lab_results(self):
        assert _detect_source_type("LAB RESULTS", SourceType.UNKNOWN) == SourceType.LAB

    def test_labbili_rejected(self):
        assert _detect_source_type("LABBILI", SourceType.UNKNOWN) == SourceType.UNKNOWN

    def test_labalbu_rejected(self):
        assert _detect_source_type("LABALBU", SourceType.UNKNOWN) == SourceType.UNKNOWN

    def test_labmono_rejected(self):
        assert _detect_source_type("LABMONO", SourceType.UNKNOWN) == SourceType.UNKNOWN

    def test_labbaso_rejected(self):
        assert _detect_source_type("LABBASO", SourceType.UNKNOWN) == SourceType.UNKNOWN

    def test_lab_ordered_inline(self):
        """Inline mention 'Lab was ordered for CBC' still matches via re.search."""
        result = _detect_source_type("Lab was ordered for CBC", SourceType.UNKNOWN)
        assert result == SourceType.LAB


# ---------------------------------------------------------------------------
# MAR word-boundary tests
# ---------------------------------------------------------------------------
class TestMarWordBoundary:
    """MAR\\b must match MAR, MAR: but not MARITAL, MARKER, MARRIED, MARGARET."""

    def test_mar_bare(self):
        assert _detect_source_type("MAR", SourceType.UNKNOWN) == SourceType.MAR

    def test_mar_colon(self):
        assert _detect_source_type("MAR:", SourceType.UNKNOWN) == SourceType.MAR

    def test_marital_status_rejected(self):
        assert _detect_source_type("MARITAL STATUS", SourceType.UNKNOWN) == SourceType.UNKNOWN

    def test_marker_rejected(self):
        assert _detect_source_type("MARKER", SourceType.UNKNOWN) == SourceType.UNKNOWN

    def test_married_rejected(self):
        assert _detect_source_type("MARRIED", SourceType.UNKNOWN) == SourceType.UNKNOWN

    def test_margaret_rejected(self):
        assert _detect_source_type("MARGARET", SourceType.UNKNOWN) == SourceType.UNKNOWN

    def test_mark_on_tube_rejected(self):
        assert _detect_source_type("MARK ON TUBE", SourceType.UNKNOWN) == SourceType.UNKNOWN


# ---------------------------------------------------------------------------
# Block-words tests
# ---------------------------------------------------------------------------
class TestBlockWords:
    """Lines like DISCHARGE PATIENT must be rejected; DISCHARGE alone accepted."""

    def test_discharge_bare_accepted(self):
        assert _detect_source_type("DISCHARGE", SourceType.UNKNOWN) == SourceType.DISCHARGE

    def test_discharge_summary_accepted(self):
        assert _detect_source_type("DISCHARGE SUMMARY", SourceType.UNKNOWN) == SourceType.DISCHARGE

    def test_discharge_patient_rejected(self):
        assert _detect_source_type("DISCHARGE PATIENT", SourceType.UNKNOWN) == SourceType.UNKNOWN

    def test_discharge_disposition_rejected(self):
        assert _detect_source_type("DISCHARGE DISPOSITION", SourceType.UNKNOWN) == SourceType.UNKNOWN

    def test_discharge_provider_rejected(self):
        assert _detect_source_type("DISCHARGE PROVIDER", SourceType.UNKNOWN) == SourceType.UNKNOWN

    def test_discharge_planning_rejected(self):
        assert _detect_source_type("DISCHARGE PLANNING", SourceType.UNKNOWN) == SourceType.UNKNOWN

    def test_problem_discharge_goals_rejected(self):
        assert _detect_source_type("Problem: Discharge Goals", SourceType.UNKNOWN) == SourceType.UNKNOWN

    def test_inline_discharge_rejected(self):
        assert _detect_source_type("Plan includes discharge tomorrow", SourceType.UNKNOWN) == SourceType.UNKNOWN

    def test_bracketed_discharge_accepted(self):
        assert _detect_source_type("[DISCHARGE]", SourceType.UNKNOWN) == SourceType.DISCHARGE


# ---------------------------------------------------------------------------
# Existing headers must still be accepted
# ---------------------------------------------------------------------------
class TestExistingHeadersPreserved:
    """Verify that standard Epic section headers continue to match."""

    def test_procedure_log(self):
        assert _is_section_header("PROCEDURE LOG")

    def test_imaging_information(self):
        assert _is_section_header("IMAGING INFORMATION")

    def test_imaging_studies_colon(self):
        assert _is_section_header("IMAGING STUDIES:")

    def test_procedure_orders(self):
        assert _is_section_header("PROCEDURE ORDERS")

    def test_progress_note_written(self):
        assert _is_section_header("PROGRESS NOTE WRITTEN")

    def test_radiology_colon(self):
        assert _is_section_header("RADIOLOGY:")

    def test_physician_notes(self):
        assert _is_section_header("PHYSICIAN NOTES")

    def test_nursing_note(self):
        assert _is_section_header("NURSING NOTE")

    def test_ed_note(self):
        assert _is_section_header("ED NOTE")

    def test_emergency_department(self):
        assert _is_section_header("EMERGENCY DEPARTMENT")

    def test_operative_note(self):
        assert _is_section_header("OPERATIVE NOTE")


# ---------------------------------------------------------------------------
# _is_section_header consistency with block words
# ---------------------------------------------------------------------------
class TestIsSectionHeaderBlockWords:
    """_is_section_header must also respect _BLOCK_WORDS."""

    def test_discharge_patient_not_header(self):
        assert not _is_section_header("DISCHARGE PATIENT")

    def test_discharge_planning_not_header(self):
        assert not _is_section_header("DISCHARGE PLANNING")

    def test_discharge_is_header(self):
        assert _is_section_header("DISCHARGE")

    def test_problem_discharge_goals_not_header(self):
        assert not _is_section_header("Problem: Discharge Goals")
