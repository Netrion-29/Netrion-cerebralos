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

    def test_recent_labs_reviewed_rejected_when_not_header(self):
        result = _detect_source_type("Recent Labs reviewed", SourceType.UNKNOWN)
        assert result == SourceType.UNKNOWN


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

    def test_kumar_name_not_treated_as_mar_header(self):
        result = _detect_source_type("Kumar, Anup, MD", SourceType.UNKNOWN)
        assert result == SourceType.UNKNOWN


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
# N6 – DISCHARGE first-word block tests
# ---------------------------------------------------------------------------
class TestDischargeFirstWordBlock:
    """Admin-field lines with trailing text beyond a block word must be rejected."""

    def test_disposition_with_value_rejected(self):
        result = _detect_source_type("Discharge Disposition: Rehab-Inpt", SourceType.UNKNOWN)
        assert result == SourceType.UNKNOWN

    def test_disposition_skilled_nursing_rejected(self):
        result = _detect_source_type("Discharge Disposition: Skilled Nursing Facility", SourceType.UNKNOWN)
        assert result == SourceType.UNKNOWN

    def test_recommendations_prose_rejected(self):
        result = _detect_source_type("Discharge Recommendations: Pt would benefit from therapy", SourceType.UNKNOWN)
        assert result == SourceType.UNKNOWN

    def test_patienton_adt_rejected(self):
        result = _detect_source_type("DISCHARGE PATIENTon Discharge Date: 12/19/2025", SourceType.UNKNOWN)
        assert result == SourceType.UNKNOWN

    def test_mim_provided_rejected(self):
        result = _detect_source_type("Discharge MIM provided: yes", SourceType.UNKNOWN)
        assert result == SourceType.UNKNOWN

    def test_transfer_to_rejected(self):
        result = _detect_source_type("Discharge/Transfer To: Skilled Nursing", SourceType.UNKNOWN)
        assert result == SourceType.UNKNOWN

    def test_comments_rejected(self):
        result = _detect_source_type("Discharge Comments: 12/15 Kyoho today", SourceType.UNKNOWN)
        assert result == SourceType.UNKNOWN

    def test_assessment_rejected(self):
        result = _detect_source_type("Discharge Assessment: Complete", SourceType.UNKNOWN)
        assert result == SourceType.UNKNOWN

    def test_planning_with_prose_rejected(self):
        result = _detect_source_type("Discharge Planning: Follow up with primary hematologist", SourceType.UNKNOWN)
        assert result == SourceType.UNKNOWN

    # --- True DISCHARGE headers must still be accepted ---
    def test_discharge_bare_still_accepted(self):
        assert _detect_source_type("DISCHARGE", SourceType.UNKNOWN) == SourceType.DISCHARGE

    def test_discharge_summary_still_accepted(self):
        assert _detect_source_type("DISCHARGE SUMMARY", SourceType.UNKNOWN) == SourceType.DISCHARGE

    def test_discharge_medications_still_accepted(self):
        assert _detect_source_type("DISCHARGE MEDICATIONS", SourceType.UNKNOWN) == SourceType.DISCHARGE

    def test_discharge_instructions_still_accepted(self):
        assert _detect_source_type("DISCHARGE INSTRUCTIONS", SourceType.UNKNOWN) == SourceType.DISCHARGE

    def test_discharge_note_still_accepted(self):
        assert _detect_source_type("DISCHARGE NOTE", SourceType.UNKNOWN) == SourceType.DISCHARGE

    def test_discharge_date_still_accepted(self):
        assert _detect_source_type("DISCHARGE DATE", SourceType.UNKNOWN) == SourceType.DISCHARGE

    def test_discharge_colon_still_accepted(self):
        assert _detect_source_type("DISCHARGE:", SourceType.UNKNOWN) == SourceType.DISCHARGE

    def test_bracketed_discharge_still_accepted(self):
        assert _detect_source_type("[DISCHARGE]", SourceType.UNKNOWN) == SourceType.DISCHARGE

    # --- Non-DISCHARGE patterns unaffected ---
    def test_procedure_patient_still_matches(self):
        """PROCEDURE PATIENT should still match — first-word block is DISCHARGE-only."""
        result = _detect_source_type("PROCEDURE PATIENT", SourceType.UNKNOWN)
        assert result == SourceType.UNKNOWN  # blocked by existing _BLOCK_WORDS


class TestIsSectionHeaderFirstWordBlock:
    """_is_section_header must also respect first-word blocking for DISCHARGE."""

    def test_disposition_with_value_not_header(self):
        assert not _is_section_header("Discharge Disposition: Rehab-Inpt")

    def test_recommendations_not_header(self):
        assert not _is_section_header("Discharge Recommendations: Pt would benefit from therapy")

    def test_discharge_summary_is_header(self):
        assert _is_section_header("DISCHARGE SUMMARY")


# ---------------------------------------------------------------------------
# N7 – DISCHARGE prose residual cleanup tests
# ---------------------------------------------------------------------------
class TestDischargeProseResidualsN7:
    """Residual prose lines should not be treated as DISCHARGE headers."""

    @pytest.mark.parametrize(
        "line",
        [
            "Discharge: PT recommending continued therapy...",
            "Discharge: pending PT",
            "Discharge at 12/19/2025 1216",
            "Discharge: Per attending.",
            "Discharge: per attending.",
            "Discharge to home with son...",
            "Discharge to home will start OP PT...",
            "Discharge: Ortho stable for dc",
            "discharge.",
            "Discharge orders placed and patient's family notified",
            "Discharge to home with wife...",
        ],
    )
    def test_detect_source_type_rejects_residual_prose(self, line):
        assert _detect_source_type(line, SourceType.UNKNOWN) == SourceType.UNKNOWN

    @pytest.mark.parametrize(
        "line",
        [
            "Discharge: PT recommending continued therapy...",
            "Discharge at 12/19/2025 1216",
            "Discharge to home with son...",
            "discharge.",
        ],
    )
    def test_is_section_header_rejects_residual_prose(self, line):
        assert not _is_section_header(line)

    def test_discharge_summary_still_detects(self):
        assert _detect_source_type("DISCHARGE SUMMARY", SourceType.UNKNOWN) == SourceType.DISCHARGE

    def test_bracketed_discharge_with_timestamp_still_detects(self):
        line = "[DISCHARGE] 2026-01-04 09:08:00"
        assert _detect_source_type(line, SourceType.UNKNOWN) == SourceType.DISCHARGE

    def test_discharge_date_still_detects(self):
        assert _detect_source_type("DISCHARGE DATE", SourceType.UNKNOWN) == SourceType.DISCHARGE


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


# ---------------------------------------------------------------------------
# D2 – IMAGING line-start anchor tests
# ---------------------------------------------------------------------------
class TestImagingLineStartAnchor:
    """IMAGING must only match at line start (with optional bracket/whitespace)."""

    def test_imaging_bare(self):
        assert _detect_source_type("IMAGING", SourceType.UNKNOWN) == SourceType.IMAGING

    def test_imaging_colon(self):
        assert _detect_source_type("IMAGING:", SourceType.UNKNOWN) == SourceType.IMAGING

    def test_imaging_studies(self):
        assert _detect_source_type("IMAGING STUDIES:", SourceType.UNKNOWN) == SourceType.IMAGING

    def test_bracketed_imaging(self):
        assert _detect_source_type("[IMAGING]", SourceType.UNKNOWN) == SourceType.IMAGING

    def test_imaging_information(self):
        assert _detect_source_type("IMAGING INFORMATION", SourceType.UNKNOWN) == SourceType.IMAGING

    def test_prose_link_to_imaging_rejected(self):
        assert _detect_source_type("Link to Imaging Results", SourceType.UNKNOWN) == SourceType.UNKNOWN

    def test_prose_print_imaging_rejected(self):
        assert _detect_source_type("Print Imaging Report", SourceType.UNKNOWN) == SourceType.UNKNOWN

    def test_prose_reviewed_imaging_rejected(self):
        assert _detect_source_type("Reviewed imaging with radiology", SourceType.UNKNOWN) == SourceType.UNKNOWN

    def test_prose_order_imaging_rejected(self):
        assert _detect_source_type("Please order imaging of chest", SourceType.UNKNOWN) == SourceType.UNKNOWN


# ---------------------------------------------------------------------------
# D2 – RADIOLOGY line-start anchor tests
# ---------------------------------------------------------------------------
class TestRadiologyLineStartAnchor:
    """RADIOLOGY must only match at line start (with optional bracket/whitespace)."""

    def test_radiology_bare(self):
        assert _detect_source_type("RADIOLOGY", SourceType.UNKNOWN) == SourceType.IMAGING

    def test_radiology_colon(self):
        assert _detect_source_type("RADIOLOGY:", SourceType.UNKNOWN) == SourceType.IMAGING

    def test_bracketed_radiology(self):
        assert _detect_source_type("[RADIOLOGY]", SourceType.UNKNOWN) == SourceType.IMAGING

    def test_radiology_report(self):
        assert _detect_source_type("RADIOLOGY REPORT", SourceType.UNKNOWN) == SourceType.IMAGING

    def test_prose_reviewed_radiology_rejected(self):
        assert _detect_source_type("Reviewed radiology findings with team", SourceType.UNKNOWN) == SourceType.UNKNOWN

    def test_prose_pending_radiology_rejected(self):
        assert _detect_source_type("Pending radiology read", SourceType.UNKNOWN) == SourceType.UNKNOWN

    def test_prose_link_to_radiology_rejected(self):
        assert _detect_source_type("Link to Radiology Report", SourceType.UNKNOWN) == SourceType.UNKNOWN


# ---------------------------------------------------------------------------
# D2 – PROCEDURE line-start anchor tests
# ---------------------------------------------------------------------------
class TestProcedureLineStartAnchor:
    """PROCEDURE must only match at line start (with optional bracket/whitespace)."""

    def test_procedure_bare(self):
        assert _detect_source_type("PROCEDURE", SourceType.UNKNOWN) == SourceType.PROCEDURE

    def test_procedure_colon(self):
        assert _detect_source_type("PROCEDURE:", SourceType.UNKNOWN) == SourceType.PROCEDURE

    def test_procedure_log(self):
        assert _detect_source_type("PROCEDURE LOG", SourceType.UNKNOWN) == SourceType.PROCEDURE

    def test_procedure_orders(self):
        assert _detect_source_type("PROCEDURE ORDERS", SourceType.UNKNOWN) == SourceType.PROCEDURE

    def test_bracketed_procedure(self):
        assert _detect_source_type("[PROCEDURE]", SourceType.UNKNOWN) == SourceType.PROCEDURE

    def test_prose_link_to_procedure_rejected(self):
        assert _detect_source_type("Link to Procedure Log", SourceType.UNKNOWN) == SourceType.UNKNOWN

    def test_prose_print_procedure_rejected(self):
        assert _detect_source_type("Print Procedure...", SourceType.UNKNOWN) == SourceType.UNKNOWN

    def test_prose_completed_procedure_rejected(self):
        assert _detect_source_type("Completed procedure without complication", SourceType.UNKNOWN) == SourceType.UNKNOWN

    def test_prose_schedule_procedure_rejected(self):
        assert _detect_source_type("Schedule procedure for tomorrow", SourceType.UNKNOWN) == SourceType.UNKNOWN

    def test_prose_consent_for_procedure_rejected(self):
        assert _detect_source_type("Consent for procedure obtained", SourceType.UNKNOWN) == SourceType.UNKNOWN


# ---------------------------------------------------------------------------
# D2 – _is_section_header consistency for anchored patterns
# ---------------------------------------------------------------------------
class TestIsSectionHeaderD2Anchors:
    """_is_section_header must also respect line-start anchors for D2 patterns."""

    def test_imaging_header(self):
        assert _is_section_header("IMAGING")

    def test_radiology_header(self):
        assert _is_section_header("RADIOLOGY:")

    def test_procedure_header(self):
        assert _is_section_header("PROCEDURE LOG")

    def test_prose_link_imaging_not_header(self):
        assert not _is_section_header("Link to Imaging Results")

    def test_prose_print_procedure_not_header(self):
        assert not _is_section_header("Print Procedure...")

    def test_prose_reviewed_radiology_not_header(self):
        assert not _is_section_header("Reviewed radiology findings")


# ---------------------------------------------------------------------------
# D6-P1 – MEDICATION_ADMIN line-start anchor tests
# ---------------------------------------------------------------------------
class TestMedicationAdminLineStartAnchor:
    """MEDICATION_ADMIN must only match at line start (with optional bracket/whitespace)."""

    def test_medication_admin_bare(self):
        assert _detect_source_type("MEDICATION ADMINISTRATION", SourceType.UNKNOWN) == SourceType.MAR

    def test_medication_admin_colon(self):
        assert _detect_source_type("MEDICATION ADMIN:", SourceType.UNKNOWN) == SourceType.MAR

    def test_bracketed_medication_admin(self):
        assert _detect_source_type("[MEDICATION_ADMIN]", SourceType.UNKNOWN) == SourceType.MAR

    def test_prose_stopping_medication_admin_rejected(self):
        result = _detect_source_type(
            "NOTIFY ATTENDING PHYSICIAN IF STOPPING CURRENT MEDICATION ADMINISTRATION",
            SourceType.UNKNOWN,
        )
        assert result == SourceType.UNKNOWN

    def test_prose_comorbidities_medication_admin_rejected(self):
        result = _detect_source_type(
            "Such co-morbidities need to be monitored during the inpatient encounter as evidenced by continued Medication Admin",
            SourceType.UNKNOWN,
        )
        assert result == SourceType.UNKNOWN


# ---------------------------------------------------------------------------
# D6-P1 – ED_NOTE line-start anchor tests
# ---------------------------------------------------------------------------
class TestEdNoteLineStartAnchor:
    """ED_NOTE must only match at line start (with optional bracket/whitespace)."""

    def test_ed_note_bare(self):
        assert _detect_source_type("ED NOTE", SourceType.UNKNOWN) == SourceType.ED_NOTE

    def test_ed_note_colon(self):
        assert _detect_source_type("ED NOTE:", SourceType.UNKNOWN) == SourceType.ED_NOTE

    def test_bracketed_ed_note(self):
        assert _detect_source_type("[ED_NOTE] 2025-12-31 15:12:00", SourceType.UNKNOWN) == SourceType.ED_NOTE

    def test_prose_reviewed_ed_note_rejected(self):
        result = _detect_source_type(
            "I have seen and examined patient on the above stated date.  I have reviewed pertinent data/lab and radiology as noted. Scribed note reviewed, errors corrected, independently verified.",
            SourceType.UNKNOWN,
        )
        assert result == SourceType.UNKNOWN

    def test_prose_mychart_shared_ed_note_rejected(self):
        result = _detect_source_type(
            "The patient can view the shared note after they get an after-visit summary. ED Note: visible",
            SourceType.UNKNOWN,
        )
        assert result == SourceType.UNKNOWN

    def test_prose_medications_reorganized_ed_note_rejected(self):
        result = _detect_source_type(
            "POTASSIUM CHLORIDE CRYS ER medications were reorganized on 11/18/2023. The possibly related notes have been updated.",
            SourceType.UNKNOWN,
        )
        assert result == SourceType.UNKNOWN
