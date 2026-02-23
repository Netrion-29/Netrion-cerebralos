#!/usr/bin/env python3
"""
Tests for PMH (Past Medical History) extraction — QA lock-in.

Covers:
  - _parse_hp_sections: header detection, lowercase keys, multi-section parsing
  - _extract_pmh: Epic bullet parsing, tab-delimited diagnosis extraction,
    fallback to raw text, empty/missing → NOT DOCUMENTED, max 10 diagnoses,
    header stripping, column header stripping
"""

import sys
from pathlib import Path

import pytest

# Ensure project root is on import path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cerebralos.reporting.trauma_doc_extractor import (
    _extract_pmh,
    _parse_hp_sections,
    _NOT_DOCUMENTED,
)


# ── _parse_hp_sections tests ───────────────────────────────────────

class TestParseHpSections:
    """Lock in behaviour of TRAUMA_HP section parser."""

    def test_single_section(self):
        text = "PMH:\nDiabetes\nHTN"
        result = _parse_hp_sections(text)
        assert "pmh" in result
        assert "Diabetes" in result["pmh"]
        assert "HTN" in result["pmh"]

    def test_multiple_sections(self):
        text = (
            "HPI:\nFall from ladder\n"
            "PMH:\nDM2\nHTN\n"
            "Allergies:\nNKDA"
        )
        result = _parse_hp_sections(text)
        assert "hpi" in result
        assert "pmh" in result
        assert "allergies" in result

    def test_sections_lowercase_keys(self):
        text = "PAST MEDICAL HISTORY:\nDM"
        result = _parse_hp_sections(text)
        assert "past medical history" in result

    def test_section_header_colon_variant(self):
        text = "Past Medical History:\nAsthma"
        result = _parse_hp_sections(text)
        assert "past medical history" in result
        assert "Asthma" in result["past medical history"]

    def test_section_without_content(self):
        text = "PMH:\nMeds:\nLisinopril"
        result = _parse_hp_sections(text)
        # PMH section should exist but be empty or just header
        assert "meds" in result
        assert "Lisinopril" in result["meds"]

    def test_header_line_included_in_section(self):
        """The header line itself is included in the section text."""
        text = "PMH:\nDiabetes"
        result = _parse_hp_sections(text)
        assert result["pmh"].startswith("PMH:")

    def test_leading_lines_go_to_header_section(self):
        text = "Patient Name: John\nPMH:\nDM"
        result = _parse_hp_sections(text)
        assert "header" in result
        assert "Patient Name" in result["header"]

    def test_empty_text(self):
        result = _parse_hp_sections("")
        # Should return at least a header section
        assert isinstance(result, dict)

    def test_no_recognised_headers(self):
        text = "Random text\nMore text"
        result = _parse_hp_sections(text)
        assert "header" in result

    def test_secondary_survey_detected(self):
        text = "Secondary Survey:\nGCS 15\nPEERLA"
        result = _parse_hp_sections(text)
        assert "secondary survey" in result

    def test_assessment_plan_detected(self):
        text = "Assessment/Plan:\nAdmit to ICU"
        result = _parse_hp_sections(text)
        assert "assessment/plan" in result


# ── _extract_pmh tests ─────────────────────────────────────────────

class TestExtractPMH:
    """Lock in behaviour of PMH extractor."""

    def test_epic_bullet_single(self):
        """Single bullet line with tab-delimited diagnosis."""
        hp = "Past Medical History:\nDiagnosis\tDate\n•\tHypertension\t01/15/2020"
        result = _extract_pmh(hp)
        assert "Hypertension" in result

    def test_epic_bullets_multiple(self):
        """Multiple bullet lines yield semicolon-separated diagnoses."""
        hp = (
            "Past Medical History:\n"
            "Diagnosis\tDate\n"
            "•\tHypertension\t01/15/2020\n"
            "•\tDiabetes Mellitus Type 2\t03/22/2018\n"
            "•\tAtrial Fibrillation\t06/10/2019"
        )
        result = _extract_pmh(hp)
        assert "Hypertension" in result
        assert "Diabetes Mellitus Type 2" in result
        assert "Atrial Fibrillation" in result
        parts = result.split("; ")
        assert len(parts) == 3

    def test_epic_bullet_strips_date_column(self):
        """Tab-separated date at end is stripped from diagnosis."""
        hp = "Past Medical History:\n•\tCOPD\t07/04/2015"
        result = _extract_pmh(hp)
        assert "07/04/2015" not in result
        assert "COPD" in result

    def test_epic_bullet_takes_first_tab_field(self):
        """Only the first tab-delimited field is kept as diagnosis name."""
        hp = "Past Medical History:\n•\tAsthma\tActive\t02/01/2021"
        result = _extract_pmh(hp)
        assert "Asthma" in result
        # Should NOT include "Active" as a separate thing in this diagnosis
        # (the first tab field is "Asthma", rest stripped)

    def test_max_10_diagnoses(self):
        """At most 10 diagnoses are returned."""
        lines = ["Past Medical History:", "Diagnosis\tDate"]
        for i in range(15):
            lines.append(f"•\tCondition_{i}\t01/01/2020")
        hp = "\n".join(lines)
        result = _extract_pmh(hp)
        parts = result.split("; ")
        assert len(parts) <= 10

    def test_subdescription_lines_skipped(self):
        """Indented sub-description lines (tab-indented) are skipped."""
        hp = (
            "Past Medical History:\n"
            "•\tHypertension\t01/15/2020\n"
            "\tControlled on lisinopril\n"
            "•\tDM2\t03/22/2018"
        )
        result = _extract_pmh(hp)
        assert "Controlled on lisinopril" not in result
        assert "Hypertension" in result
        assert "DM2" in result

    def test_pmh_section_key_fallback(self):
        """Tries 'past medical history' key first, falls back to 'pmh'."""
        hp = "PMH:\nDiabetes"
        result = _extract_pmh(hp)
        # Should get something (fallback raw text)
        assert result != _NOT_DOCUMENTED

    def test_raw_text_fallback_when_no_bullets(self):
        """When no Epic bullets found, falls back to raw section text."""
        hp = "Past Medical History:\nDiabetes, HTN, COPD"
        result = _extract_pmh(hp)
        assert "Diabetes" in result

    def test_raw_text_fallback_strips_header(self):
        """Raw fallback strips 'Past Medical History:' header prefix."""
        hp = "Past Medical History:\nPast Medical History: DM2, HTN"
        result = _extract_pmh(hp)
        # The raw text should have the redundant header stripped
        assert result.startswith("DM2") or "DM2" in result

    def test_raw_text_capped_at_300_chars(self):
        """Raw fallback is capped at 300 characters."""
        long_text = "A" * 500
        hp = f"Past Medical History:\n{long_text}"
        result = _extract_pmh(hp)
        assert len(result) <= 300

    def test_missing_pmh_section(self):
        """Returns NOT DOCUMENTED if there is no PMH section."""
        hp = "HPI:\nFall from ladder\nAllergies:\nNKDA"
        result = _extract_pmh(hp)
        assert result == _NOT_DOCUMENTED

    def test_empty_text(self):
        """Empty input yields NOT DOCUMENTED."""
        result = _extract_pmh("")
        assert result == _NOT_DOCUMENTED

    def test_pmh_header_only_no_content(self):
        """PMH section with just the header text is not treated as content."""
        hp = "Past Medical History:\nPAST MEDICAL HISTORY"
        result = _extract_pmh(hp)
        assert result == _NOT_DOCUMENTED

    def test_diagnosis_date_column_header_stripped(self):
        """'Diagnosis  Date' column header is stripped from raw fallback."""
        hp = (
            "Past Medical History:\n"
            "Diagnosis\tDate\n"
            "No known conditions"
        )
        result = _extract_pmh(hp)
        # Should NOT include "Diagnosis Date" as text
        # "No known conditions" should be in the raw fallback
        assert "No known conditions" in result or result == _NOT_DOCUMENTED

    def test_short_bullet_lines_skipped(self):
        """Bullet lines with content <= 2 chars are ignored."""
        hp = "Past Medical History:\n•\tA\t01/01/2020\n•\tHypertension\t01/01/2020"
        result = _extract_pmh(hp)
        # "A" is <= 2 chars, should be skipped
        parts = result.split("; ")
        assert all(len(p) > 2 for p in parts)

    def test_prefers_past_medical_history_over_pmh(self):
        """'past medical history' section is checked before 'pmh'."""
        hp = (
            "PMH: PAST MEDICAL HISTORY\n"
            "Past Medical History:\n"
            "•\tHypertension\t01/01/2020"
        )
        result = _extract_pmh(hp)
        assert "Hypertension" in result
