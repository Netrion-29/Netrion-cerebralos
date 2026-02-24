#!/usr/bin/env python3
"""
Tests for cerebralos.features.sbirt_screening_v1

Coverage:
  - Score regex patterns (AUDIT-C, DAST-10, CAGE)
  - Narrative Q&A extraction (Pattern A)
  - Flowsheet Q&A extraction (Pattern B)
  - Nurse marker stripping
  - Refusal / admission detection
  - Completion status logic
  - End-to-end via extract_sbirt_screening()
  - Real-patient pipeline integration (Pattern A patients)
  - Negative controls (no SBIRT data → DATA NOT AVAILABLE)
"""

from __future__ import annotations

import json
import os
import re
import pytest

from cerebralos.features.sbirt_screening_v1 import (
    RE_AUDIT_C,
    RE_DAST_10,
    RE_CAGE,
    RE_AUDIT_C_Q1,
    RE_AUDIT_C_Q2,
    RE_AUDIT_C_Q3,
    RE_DAST_Q,
    RE_INJURY_Q,
    RE_SCREENING_REFUSAL,
    RE_SUBSTANCE_ADMISSION,
    RE_NURSE_MARKER,
    _strip_nurse_marker,
    _is_flowsheet_blank,
    _extract_scores,
    _extract_narrative_responses,
    _extract_flowsheet_responses,
    _extract_refusal_and_admission,
    _build_result,
    extract_sbirt_screening,
)

# ── Helpers ─────────────────────────────────────────────────────────

TIMELINE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "outputs", "timeline"
)


def _load_days(patient_slug: str) -> dict:
    """Load patient_days_v1.json for a real patient."""
    path = os.path.join(TIMELINE_DIR, patient_slug, "patient_days_v1.json")
    if not os.path.isfile(path):
        pytest.skip(f"Timeline not found: {path}")
    with open(path) as f:
        return json.load(f)


def _make_days(text: str, item_type: str = "NURSING_NOTE",
               ts: str = "2025-12-18T14:00:00") -> dict:
    """Build a minimal days_data dict wrapping a single text item."""
    return {
        "days": {
            "2025-12-18": {
                "items": [
                    {
                        "type": item_type,
                        "dt": ts,
                        "id": "test_item_001",
                        "payload": {"text": text},
                    }
                ]
            }
        }
    }


# ====================================================================
# 1. Score regex patterns
# ====================================================================

class TestScoreRegex:
    """Verify score regexes match real-world patterns."""

    def test_audit_c_colon(self):
        assert RE_AUDIT_C.search("Audit-C Score: 4")
        assert RE_AUDIT_C.search("Audit-C Score: 4").group(1) == "4"

    def test_audit_c_equals(self):
        assert RE_AUDIT_C.search("Audit-C Score=6")
        assert RE_AUDIT_C.search("Audit-C Score=6").group(1) == "6"

    def test_audit_c_zero(self):
        m = RE_AUDIT_C.search("Audit-C Score: 0")
        assert m and m.group(1) == "0"

    def test_audit_c_no_match_qualitative(self):
        assert RE_AUDIT_C.search("positive AUDIT-C screen") is None

    def test_audit_c_no_match_text_only(self):
        assert RE_AUDIT_C.search("Audit-C was performed") is None

    def test_dast_10_score(self):
        m = RE_DAST_10.search("DAST-10 Score: 2")
        assert m and m.group(1) == "2"

    def test_dast_10_total(self):
        m = RE_DAST_10.search("DAST-10 total: 3")
        assert m and m.group(1) == "3"

    def test_dast_10_no_match_question(self):
        assert RE_DAST_10.search("Have you used drugs") is None

    def test_cage_basic(self):
        m = RE_CAGE.search("CAGE: 2/4")
        assert m and m.group(1) == "2"

    def test_cage_score_prefix(self):
        m = RE_CAGE.search("CAGE score: 1")
        assert m and m.group(1) == "1"

    def test_cage_no_fraction(self):
        m = RE_CAGE.search("CAGE: 3")
        assert m and m.group(1) == "3"

    def test_cage_no_match_mention(self):
        assert RE_CAGE.search("CAGE questionnaire completed") is None


# ====================================================================
# 2. Narrative Q&A regex patterns (Pattern A)
# ====================================================================

class TestNarrativeRegex:
    """Verify inline Q&A regexes match real patient text."""

    REAL_TEXT = (
        "SBIRT/DAST-10\n"
        "Does the patient have an injury?: Yes\n"
        "How often do you have a drink containing alcohol?: "
        "4 or more times a week\n"
        "How many standard drinks containing alcohol do you have "
        "on a typical day?: 0 to 2 drinks\n"
        "How often do you have six or more drinks on one occasion?: Never\n"
        "Audit-C Score: 4\n"
        "\n"
        "DAST-10\n"
        "Have you used drugs other than those required for medical "
        "reasons? (Or did the paient test positive for un-prescribed "
        "drug use?): No\n"
    )

    def test_audit_c_q1(self):
        m = RE_AUDIT_C_Q1.search(self.REAL_TEXT)
        assert m
        assert m.group(1).strip() == "4 or more times a week"

    def test_audit_c_q2(self):
        m = RE_AUDIT_C_Q2.search(self.REAL_TEXT)
        assert m
        assert m.group(1).strip() == "0 to 2 drinks"

    def test_audit_c_q3(self):
        m = RE_AUDIT_C_Q3.search(self.REAL_TEXT)
        assert m
        assert m.group(1).strip() == "Never"

    def test_dast_q(self):
        m = RE_DAST_Q.search(self.REAL_TEXT)
        assert m
        assert m.group(1).strip() == "No"

    def test_injury_q(self):
        m = RE_INJURY_Q.search(self.REAL_TEXT)
        assert m
        assert m.group(1).strip() == "Yes"


# ====================================================================
# 3. Nurse marker stripping
# ====================================================================

class TestNurseMarker:
    """Verify trailing nurse letter is stripped from flowsheet values."""

    def test_yes_a(self):
        assert _strip_nurse_marker("Yes A") == "Yes"

    def test_no_b(self):
        assert _strip_nurse_marker("No B") == "No"

    def test_plain_yes(self):
        assert _strip_nurse_marker("Yes") == "Yes"

    def test_plain_no(self):
        assert _strip_nurse_marker("No") == "No"

    def test_dash(self):
        assert _strip_nurse_marker("—") == "—"

    def test_multi_word(self):
        # Should strip "C" from "4 or more times a week C"
        assert _strip_nurse_marker("4 or more times a week C") == "4 or more times a week"

    def test_empty(self):
        assert _strip_nurse_marker("") == ""


# ====================================================================
# 4. Flowsheet blank detection
# ====================================================================

class TestFlowsheetBlank:
    def test_dash(self):
        assert _is_flowsheet_blank("—")

    def test_double_dash(self):
        assert _is_flowsheet_blank("--")

    def test_hyphen(self):
        assert _is_flowsheet_blank("-")

    def test_na(self):
        assert _is_flowsheet_blank("N/A")

    def test_empty(self):
        assert _is_flowsheet_blank("")

    def test_whitespace(self):
        assert _is_flowsheet_blank("  ")

    def test_yes_not_blank(self):
        assert not _is_flowsheet_blank("Yes A")

    def test_no_not_blank(self):
        assert not _is_flowsheet_blank("No")


# ====================================================================
# 5. Score extraction (unit level)
# ====================================================================

class TestExtractScores:
    def test_audit_c_from_narrative(self):
        text = "Audit-C Score: 4\nSome other text"
        result = _extract_scores(text, "NURSING_NOTE", "item1", "2025-12-18T14:00:00")
        assert result["audit_c"] is not None
        assert result["audit_c"]["value"] == 4
        assert result["audit_c"]["source_rule_id"] == "sbirt_section_audit_c"

    def test_no_scores(self):
        text = "Patient was admitted with no alcohol history."
        result = _extract_scores(text, "NURSING_NOTE", "item1", "2025-12-18T14:00:00")
        assert result["audit_c"] is None
        assert result["dast_10"] is None
        assert result["cage"] is None
        assert result["evidence"] == []

    def test_multiple_scores(self):
        text = "Audit-C Score: 6\nDAST-10 Score: 2\nCAGE: 1/4"
        result = _extract_scores(text, "CARE_TEAM", "item2", "2025-12-18T14:00:00")
        assert result["audit_c"]["value"] == 6
        assert result["dast_10"]["value"] == 2
        assert result["cage"]["value"] == 1

    def test_evidence_has_raw_line_id(self):
        text = "Audit-C Score: 4"
        result = _extract_scores(text, "NURSING_NOTE", "item1", "2025-12-18T14:00:00")
        for ev in result["evidence"]:
            assert "raw_line_id" in ev
            assert len(ev["raw_line_id"]) == 16


# ====================================================================
# 6. Narrative response extraction (Pattern A)
# ====================================================================

class TestNarrativeResponses:
    REAL_TEXT = (
        "SBIRT/DAST-10\n"
        "Does the patient have an injury?: Yes\n"
        "How often do you have a drink containing alcohol?: "
        "4 or more times a week\n"
        "How many standard drinks containing alcohol do you have "
        "on a typical day?: 0 to 2 drinks\n"
        "How often do you have six or more drinks on one occasion?: Never\n"
        "Audit-C Score: 4\n"
        "\n"
        "DAST-10\n"
        "Have you used drugs other than those required for medical "
        "reasons? (Or did the paient test positive for un-prescribed "
        "drug use?): No\n"
    )

    def test_extracts_audit_c_questions(self):
        result = _extract_narrative_responses(
            self.REAL_TEXT, "NURSING_NOTE", "item1", "2025-12-18T14:00:00"
        )
        audit_c_responses = [
            r for r in result["responses"] if r["instrument"] == "audit_c"
        ]
        assert len(audit_c_responses) == 3
        answers = {r["question_id"]: r["answer"] for r in audit_c_responses}
        assert answers["audit_c_q1"] == "4 or more times a week"
        assert answers["audit_c_q2"] == "0 to 2 drinks"
        assert answers["audit_c_q3"] == "Never"

    def test_extracts_dast_question(self):
        result = _extract_narrative_responses(
            self.REAL_TEXT, "NURSING_NOTE", "item1", "2025-12-18T14:00:00"
        )
        dast_responses = [
            r for r in result["responses"] if r["instrument"] == "dast_10"
        ]
        assert len(dast_responses) == 1
        assert dast_responses[0]["answer"] == "No"

    def test_instruments_detected(self):
        result = _extract_narrative_responses(
            self.REAL_TEXT, "NURSING_NOTE", "item1", "2025-12-18T14:00:00"
        )
        assert "audit_c" in result["instruments_detected"]
        assert "dast_10" in result["instruments_detected"]

    def test_evidence_has_raw_line_id(self):
        result = _extract_narrative_responses(
            self.REAL_TEXT, "NURSING_NOTE", "item1", "2025-12-18T14:00:00"
        )
        for ev in result["evidence"]:
            assert "raw_line_id" in ev

    def test_no_match_returns_empty(self):
        result = _extract_narrative_responses(
            "Patient is stable.", "NURSING_NOTE", "item1", "2025-12-18T14:00:00"
        )
        assert result["responses"] == []
        assert result["instruments_detected"] == []


# ====================================================================
# 7. Flowsheet response extraction (Pattern B, synthetic)
# ====================================================================

class TestFlowsheetResponses:
    """Test flowsheet parsing with synthetic data matching real patterns."""

    SHORT_FORM = (
        "12/8/2025 0000 CST - 1/7/2026 1513 CST\n"
        " \n"
        "Date/Time\tDoes the patient have an injury?\t"
        "Have you used drugs other than those required for medical reasons? "
        "(Or did the paient test positive for un-prescribed drug use?)\t"
        "Do you drink alcohol? (Or did the patient test positive on blood "
        "alcohol testing?)\t"
        "Do you have a history of alcohol use or withdrawals?\n"
        "12/26/25 1707\tYes A\tNo A\tNo A\tNo A\n"
    )

    LONG_FORM = (
        "12/6/2025 0000 CST - 1/5/2026 1311 CST\n"
        " \n"
        "Date/Time\tDoes the patient have an injury?\t"
        "Have you used drugs other than those required for medical reasons? "
        "(Or did the paient test positive for un-prescribed drug use?)\t"
        "Do you drink alcohol? (Or did the patient test positive on blood "
        "alcohol testing?)\t"
        "How often do you have a drink containing alcohol?\t"
        "How many standard drinks containing alcohol do you have on a "
        "typical day?\t"
        "How often do you have six or more drinks on one occasion?\t"
        "Audit-C Score\t"
        "Do you have a history of alcohol use or withdrawals?\n"
        "12/25/25 2300\tYes A\tNo A\tNo A\t\u2014\t\u2014\t\u2014\t\u2014\tNo A\n"
    )

    REORDERED = (
        "12/13/2025 0000 CST - 1/12/2026 1130 CST\n"
        " \n"
        "Date/Time\tDo you have a history of alcohol use or withdrawals?\t"
        "Does the patient have an injury?\t"
        "Have you used drugs other than those required for medical reasons? "
        "(Or did the paient test positive for un-prescribed drug use?)\t"
        "Do you drink alcohol? (Or did the patient test positive on blood "
        "alcohol testing?)\n"
        "12/18/25 1445\tNo A\tYes A\tNo A\tNo A\n"
        "12/18/25 0900\t\u2014\tYes B\t\u2014\t\u2014\n"
        "12/17/25 1923\tNo C\tNo C\t\u2014\t\u2014\n"
    )

    def test_short_form_responses(self):
        result = _extract_flowsheet_responses(
            self.SHORT_FORM, "NURSING_NOTE", "item1", "2025-12-26T17:07:00"
        )
        assert len(result["responses"]) == 4
        answers = {r["question_id"]: r["answer"] for r in result["responses"]}
        assert answers["injury"] == "Yes"
        assert answers["drug_use"] == "No"
        assert answers["alcohol_testing"] == "No"
        assert answers["alcohol_history"] == "No"

    def test_short_form_nurse_markers_stripped(self):
        result = _extract_flowsheet_responses(
            self.SHORT_FORM, "NURSING_NOTE", "item1", "2025-12-26T17:07:00"
        )
        for r in result["responses"]:
            assert not re.search(r"\s+[A-Z]$", r["answer"]), \
                f"Nurse marker not stripped from: {r['answer']}"

    def test_long_form_blanks_skipped(self):
        result = _extract_flowsheet_responses(
            self.LONG_FORM, "NURSING_NOTE", "item1", "2025-12-25T23:00:00"
        )
        # 9 columns: Date/Time + 8 question cols
        # "—" in 4 cols → those should be skipped
        # Should get: injury=Yes, drug_use=No, alcohol_testing=No, alcohol_history=No
        answers = {r["question_id"]: r["answer"] for r in result["responses"]}
        assert answers.get("injury") == "Yes"
        assert answers.get("drug_use") == "No"
        assert "audit_c_q1" not in answers  # was "—"
        assert "audit_c_q2" not in answers  # was "—"
        assert "audit_c_q3" not in answers  # was "—"
        assert "audit_c_score" not in answers  # was "—"

    def test_long_form_instruments(self):
        result = _extract_flowsheet_responses(
            self.LONG_FORM, "NURSING_NOTE", "item1", "2025-12-25T23:00:00"
        )
        assert "audit_c" in result["instruments_detected"]
        assert "sbirt_flowsheet" in result["instruments_detected"]

    def test_reordered_columns(self):
        result = _extract_flowsheet_responses(
            self.REORDERED, "NURSING_NOTE", "item1", "2025-12-18T14:45:00"
        )
        # Only first data row is taken
        answers = {r["question_id"]: r["answer"] for r in result["responses"]}
        assert answers["alcohol_history"] == "No"
        assert answers["injury"] == "Yes"
        assert answers["drug_use"] == "No"
        assert answers["alcohol_testing"] == "No"

    def test_reordered_first_row_only(self):
        result = _extract_flowsheet_responses(
            self.REORDERED, "NURSING_NOTE", "item1", "2025-12-18T14:45:00"
        )
        # Only the first data row should be captured
        assert len(result["responses"]) == 4

    def test_no_flowsheet_returns_empty(self):
        result = _extract_flowsheet_responses(
            "Some random text", "NURSING_NOTE", "item1", "2025-12-18T14:00:00"
        )
        assert result["responses"] == []
        assert result["instruments_detected"] == []

    def test_evidence_has_raw_line_id(self):
        result = _extract_flowsheet_responses(
            self.SHORT_FORM, "NURSING_NOTE", "item1", "2025-12-26T17:07:00"
        )
        for ev in result["evidence"]:
            assert "raw_line_id" in ev


# ====================================================================
# 8. Refusal / admission detection
# ====================================================================

class TestRefusalAdmission:
    def test_screening_refusal(self):
        text = "Patient refused SBIRT screening."
        result = _extract_refusal_and_admission(
            text, "NURSING_NOTE", "item1", "2025-12-18T14:00:00"
        )
        assert result["refusal_documented"] is True
        assert len(result["refusal_evidence"]) == 1

    def test_declined_screening(self):
        text = "Patient declined alcohol screening."
        result = _extract_refusal_and_admission(
            text, "NURSING_NOTE", "item1", "2025-12-18T14:00:00"
        )
        assert result["refusal_documented"] is True

    def test_declined_cd_resources_not_refusal(self):
        """Declining CD resources is NOT refusal of screening itself."""
        text = "Patient declined need for chemical dependency resources."
        result = _extract_refusal_and_admission(
            text, "NURSING_NOTE", "item1", "2025-12-18T14:00:00"
        )
        assert result["refusal_documented"] is False

    def test_substance_admission(self):
        text = "Patient admits to alcohol use daily."
        result = _extract_refusal_and_admission(
            text, "CARE_TEAM", "item1", "2025-12-18T14:00:00"
        )
        assert result["substance_use_admission_documented"] is True

    def test_no_refusal_or_admission(self):
        text = "Patient is stable, vitals normal."
        result = _extract_refusal_and_admission(
            text, "NURSING_NOTE", "item1", "2025-12-18T14:00:00"
        )
        assert result["refusal_documented"] is False
        assert result["substance_use_admission_documented"] is False


# ====================================================================
# 9. Completion status logic
# ====================================================================

class TestCompletionStatus:
    def test_score_documented(self):
        result = _build_result(
            audit_c={"value": 4, "ts": "t", "source_rule_id": "x", "evidence": []},
            dast_10=None, cage=None,
            responses=[], instruments=["audit_c"],
            refusal_documented=False, refusal_evidence=[],
            substance_admission_documented=False, substance_admission_evidence=[],
            evidence=[], notes=[], warnings=[],
        )
        assert result["audit_c"]["completion_status"] == "score_documented"

    def test_responses_complete_3_of_3(self):
        responses = [
            {"question_id": f"audit_c_q{i}", "answer": "x", "instrument": "audit_c", "raw_line_id": f"r{i}"}
            for i in range(1, 4)
        ]
        result = _build_result(
            audit_c=None, dast_10=None, cage=None,
            responses=responses, instruments=["audit_c"],
            refusal_documented=False, refusal_evidence=[],
            substance_admission_documented=False, substance_admission_evidence=[],
            evidence=[], notes=[], warnings=[],
        )
        assert result["audit_c"]["completion_status"] == "responses_complete"

    def test_responses_only_partial(self):
        responses = [
            {"question_id": "audit_c_q1", "answer": "x", "instrument": "audit_c", "raw_line_id": "r1"}
        ]
        result = _build_result(
            audit_c=None, dast_10=None, cage=None,
            responses=responses, instruments=["audit_c"],
            refusal_documented=False, refusal_evidence=[],
            substance_admission_documented=False, substance_admission_evidence=[],
            evidence=[], notes=[], warnings=[],
        )
        assert result["audit_c"]["completion_status"] == "responses_only"

    def test_not_performed(self):
        result = _build_result(
            audit_c=None, dast_10=None, cage=None,
            responses=[], instruments=[],
            refusal_documented=False, refusal_evidence=[],
            substance_admission_documented=False, substance_admission_evidence=[],
            evidence=[], notes=[], warnings=[],
        )
        assert result["audit_c"]["completion_status"] == "not_performed"
        assert result["dast_10"]["completion_status"] == "not_performed"
        assert result["cage"]["completion_status"] == "not_performed"


# ====================================================================
# 10. Screening presence logic
# ====================================================================

class TestScreeningPresence:
    def test_yes_from_score(self):
        result = _build_result(
            audit_c={"value": 4, "ts": "t", "source_rule_id": "x", "evidence": []},
            dast_10=None, cage=None,
            responses=[], instruments=["audit_c"],
            refusal_documented=False, refusal_evidence=[],
            substance_admission_documented=False, substance_admission_evidence=[],
            evidence=[], notes=[], warnings=[],
        )
        assert result["sbirt_screening_present"] == "yes"

    def test_yes_from_responses(self):
        responses = [
            {"question_id": "audit_c_q1", "answer": "Never", "instrument": "audit_c", "raw_line_id": "r1"}
        ]
        result = _build_result(
            audit_c=None, dast_10=None, cage=None,
            responses=responses, instruments=["audit_c"],
            refusal_documented=False, refusal_evidence=[],
            substance_admission_documented=False, substance_admission_evidence=[],
            evidence=[], notes=[], warnings=[],
        )
        assert result["sbirt_screening_present"] == "yes"

    def test_refused(self):
        result = _build_result(
            audit_c=None, dast_10=None, cage=None,
            responses=[], instruments=[],
            refusal_documented=True, refusal_evidence=[{"raw_line_id": "x"}],
            substance_admission_documented=False, substance_admission_evidence=[],
            evidence=[], notes=[], warnings=[],
        )
        assert result["sbirt_screening_present"] == "refused"

    def test_dna_no_data(self):
        result = _build_result(
            audit_c=None, dast_10=None, cage=None,
            responses=[], instruments=[],
            refusal_documented=False, refusal_evidence=[],
            substance_admission_documented=False, substance_admission_evidence=[],
            evidence=[], notes=[], warnings=[],
        )
        assert result["sbirt_screening_present"] == "DATA NOT AVAILABLE"


# ====================================================================
# 11. End-to-end: synthetic narrative (Pattern A)
# ====================================================================

class TestEndToEndNarrative:
    """Full pipeline with synthetic text matching Barbara_Burgdorf pattern."""

    TEXT = (
        "[NURSING_NOTE] 2025-12-18 17:41:00\n"
        "SBIRT\n"
        " \n"
        "SBIRT/DAST-10\n"
        "Does the patient have an injury?: Yes\n"
        "How often do you have a drink containing alcohol?: "
        "4 or more times a week\n"
        "How many standard drinks containing alcohol do you have "
        "on a typical day?: 0 to 2 drinks\n"
        "How often do you have six or more drinks on one occasion?: Never\n"
        "Audit-C Score: 4\n"
        "\n"
        "DAST-10\n"
        "Have you used drugs other than those required for medical "
        "reasons? (Or did the paient test positive for un-prescribed "
        "drug use?): No\n"
    )

    def test_present_yes(self):
        days = _make_days(self.TEXT, "NURSING_NOTE")
        result = extract_sbirt_screening({}, days)
        assert result["sbirt_screening_present"] == "yes"

    def test_audit_c_score(self):
        days = _make_days(self.TEXT, "NURSING_NOTE")
        result = extract_sbirt_screening({}, days)
        assert result["audit_c"]["explicit_score"] is not None
        assert result["audit_c"]["explicit_score"]["value"] == 4

    def test_audit_c_responses(self):
        days = _make_days(self.TEXT, "NURSING_NOTE")
        result = extract_sbirt_screening({}, days)
        assert result["audit_c"]["responses_present"] is True
        assert len(result["audit_c"]["responses"]) == 3

    def test_dast_10_response(self):
        days = _make_days(self.TEXT, "NURSING_NOTE")
        result = extract_sbirt_screening({}, days)
        assert result["dast_10"]["responses_present"] is True
        assert len(result["dast_10"]["responses"]) == 1

    def test_instruments_detected(self):
        days = _make_days(self.TEXT, "NURSING_NOTE")
        result = extract_sbirt_screening({}, days)
        assert "audit_c" in result["instruments_detected"]
        assert "dast_10" in result["instruments_detected"]

    def test_evidence_has_raw_line_id(self):
        days = _make_days(self.TEXT, "NURSING_NOTE")
        result = extract_sbirt_screening({}, days)
        for ev in result["evidence"]:
            assert "raw_line_id" in ev, f"Missing raw_line_id in evidence: {ev}"

    def test_no_refusal(self):
        days = _make_days(self.TEXT, "NURSING_NOTE")
        result = extract_sbirt_screening({}, days)
        assert result["refusal_documented"] is False

    def test_cage_not_performed(self):
        days = _make_days(self.TEXT, "NURSING_NOTE")
        result = extract_sbirt_screening({}, days)
        assert result["cage"]["explicit_score"] is None
        assert result["cage"]["completion_status"] == "not_performed"


# ====================================================================
# 12. End-to-end: synthetic flowsheet (Pattern B)
# ====================================================================

class TestEndToEndFlowsheet:
    """Full pipeline with synthetic flowsheet text."""

    TEXT = (
        "12/8/2025 0000 CST - 1/7/2026 1513 CST\n"
        " \n"
        "Date/Time\tDoes the patient have an injury?\t"
        "Have you used drugs other than those required for medical reasons? "
        "(Or did the paient test positive for un-prescribed drug use?)\t"
        "Do you drink alcohol? (Or did the patient test positive on blood "
        "alcohol testing?)\t"
        "Do you have a history of alcohol use or withdrawals?\n"
        "12/26/25 1707\tYes A\tNo A\tNo A\tNo A\n"
    )

    def test_present_yes(self):
        days = _make_days(self.TEXT, "NURSING_NOTE")
        result = extract_sbirt_screening({}, days)
        assert result["sbirt_screening_present"] == "yes"

    def test_flowsheet_responses_populated(self):
        days = _make_days(self.TEXT, "NURSING_NOTE")
        result = extract_sbirt_screening({}, days)
        assert len(result["flowsheet_responses"]) == 4

    def test_nurse_markers_stripped(self):
        days = _make_days(self.TEXT, "NURSING_NOTE")
        result = extract_sbirt_screening({}, days)
        for r in result["flowsheet_responses"]:
            assert not re.search(r"\s+[A-Z]$", r["answer"])


# ====================================================================
# 13. End-to-end: empty patient (negative control)
# ====================================================================

class TestEndToEndEmpty:
    def test_no_items(self):
        days = {"days": {}}
        result = extract_sbirt_screening({}, days)
        assert result["sbirt_screening_present"] == "DATA NOT AVAILABLE"

    def test_non_sbirt_text(self):
        days = _make_days("Patient stable. Vitals WNL.", "NURSING_NOTE")
        result = extract_sbirt_screening({}, days)
        assert result["sbirt_screening_present"] == "DATA NOT AVAILABLE"

    def test_wrong_item_type_ignored(self):
        days = _make_days("Audit-C Score: 4", "LAB")
        result = extract_sbirt_screening({}, days)
        assert result["sbirt_screening_present"] == "DATA NOT AVAILABLE"


# ====================================================================
# 14. End-to-end: refusal scenario
# ====================================================================

class TestEndToEndRefusal:
    def test_refusal_sets_refused(self):
        text = "SBIRT screening: Patient refused SBIRT screening."
        days = _make_days(text, "NURSING_NOTE")
        result = extract_sbirt_screening({}, days)
        assert result["sbirt_screening_present"] == "refused"
        assert result["refusal_documented"] is True


# ====================================================================
# 15. Real-patient integration tests (Pattern A: narrative)
# ====================================================================

class TestRealPatientNarrative:
    """Integration tests against real patient_days_v1.json files.

    These tests run against the pipeline outputs. They are skipped if
    the timeline files are not present (e.g., in CI without data).
    """

    def test_barbara_burgdorf_score_4(self):
        days = _load_days("Barbara_Burgdorf")
        result = extract_sbirt_screening({}, days)
        assert result["sbirt_screening_present"] == "yes"
        assert result["audit_c"]["explicit_score"] is not None
        assert result["audit_c"]["explicit_score"]["value"] == 4
        assert result["audit_c"]["responses_present"] is True
        assert len(result["audit_c"]["responses"]) == 3

    def test_barbara_burgdorf_dast_response(self):
        days = _load_days("Barbara_Burgdorf")
        result = extract_sbirt_screening({}, days)
        assert result["dast_10"]["responses_present"] is True
        assert result["dast_10"]["responses"][0]["answer"] == "No"

    def test_robert_sauer_score_6(self):
        days = _load_days("Robert_Sauer")
        result = extract_sbirt_screening({}, days)
        assert result["sbirt_screening_present"] == "yes"
        assert result["audit_c"]["explicit_score"] is not None
        assert result["audit_c"]["explicit_score"]["value"] == 6

    def test_susan_barker_score_0(self):
        days = _load_days("Susan_Barker")
        result = extract_sbirt_screening({}, days)
        assert result["sbirt_screening_present"] == "yes"
        assert result["audit_c"]["explicit_score"] is not None
        assert result["audit_c"]["explicit_score"]["value"] == 0

    def test_susan_barker_responses(self):
        days = _load_days("Susan_Barker")
        result = extract_sbirt_screening({}, days)
        answers = {r["question_id"]: r["answer"] for r in result["audit_c"]["responses"]}
        assert answers["audit_c_q1"] == "Never"
        assert answers["audit_c_q3"] == "Never"


# ====================================================================
# 16. Real-patient integration: negative control
# ====================================================================

class TestRealPatientNegative:
    def test_anna_dennis_dna(self):
        days = _load_days("Anna_Dennis")
        result = extract_sbirt_screening({}, days)
        assert result["sbirt_screening_present"] == "DATA NOT AVAILABLE"
        assert result["audit_c"]["explicit_score"] is None
        assert result["audit_c"]["completion_status"] == "not_performed"

    def test_timothy_nachtwey_dna(self):
        """Gate patient with no SBIRT data."""
        days = _load_days("Timothy_Nachtwey")
        result = extract_sbirt_screening({}, days)
        assert result["sbirt_screening_present"] == "DATA NOT AVAILABLE"


# ====================================================================
# 17. Real-patient integration: flowsheet patients
# ====================================================================

class TestRealPatientFlowsheet:
    """Flowsheet SBIRT data is parsed into timeline via the last
    [KIND] or [REMOVED] block that trails into Flowsheet History.
    After re-parsing evidence with the current parser, these patients
    now have SBIRT data available in the timeline.
    """

    def test_larry_corne_present(self):
        days = _load_days("Larry_Corne")
        result = extract_sbirt_screening({}, days)
        assert result["sbirt_screening_present"] == "yes"

    def test_larry_corne_flowsheet_responses(self):
        days = _load_days("Larry_Corne")
        result = extract_sbirt_screening({}, days)
        assert len(result["flowsheet_responses"]) == 4
        answers = {r["question_id"]: r["answer"] for r in result["flowsheet_responses"]}
        assert answers["injury"] == "Yes"
        assert answers["drug_use"] == "No"
        assert answers["alcohol_testing"] == "No"
        assert answers["alcohol_history"] == "No"

    def test_william_simmons_present(self):
        """William_Simmons new-format file has no SBIRT flowsheet data."""
        days = _load_days("William_Simmons")
        result = extract_sbirt_screening({}, days)
        assert result["sbirt_screening_present"] == "DATA NOT AVAILABLE"

    def test_william_simmons_flowsheet_responses(self):
        """No flowsheet responses expected for this new-format patient."""
        days = _load_days("William_Simmons")
        result = extract_sbirt_screening({}, days)
        assert len(result["flowsheet_responses"]) == 0

    def test_timothy_cowan_present(self):
        days = _load_days("Timothy_Cowan")
        result = extract_sbirt_screening({}, days)
        assert result["sbirt_screening_present"] == "yes"

    def test_timothy_cowan_flowsheet_responses(self):
        days = _load_days("Timothy_Cowan")
        result = extract_sbirt_screening({}, days)
        assert len(result["flowsheet_responses"]) == 4
        answers = {r["question_id"]: r["answer"] for r in result["flowsheet_responses"]}
        assert answers["injury"] == "Yes"
        assert answers["drug_use"] == "No"

    def test_valerie_parker_present(self):
        days = _load_days("Valerie_Parker")
        result = extract_sbirt_screening({}, days)
        assert result["sbirt_screening_present"] == "yes"

    def test_valerie_parker_flowsheet_responses(self):
        days = _load_days("Valerie_Parker")
        result = extract_sbirt_screening({}, days)
        assert len(result["flowsheet_responses"]) == 4
        answers = {r["question_id"]: r["answer"] for r in result["flowsheet_responses"]}
        assert answers["injury"] == "Yes"
        assert answers["alcohol_history"] == "No"

    def test_valerie_parker_has_audit_c_instrument(self):
        """Valerie_Parker has AUDIT-C sub-question columns (all blank)."""
        days = _load_days("Valerie_Parker")
        result = extract_sbirt_screening({}, days)
        assert "audit_c" in result["instruments_detected"]


# ====================================================================
# 17b. End-to-end: REMOVED block type with flowsheet data
# ====================================================================

class TestEndToEndRemovedBlock:
    """Verify that SBIRT data in a REMOVED block is extracted."""

    TEXT = (
        "12/8/2025 0000 CST - 1/7/2026 1513 CST\n"
        " \n"
        "Date/Time\tDoes the patient have an injury?\t"
        "Have you used drugs other than those required for medical reasons? "
        "(Or did the paient test positive for un-prescribed drug use?)\t"
        "Do you drink alcohol? (Or did the patient test positive on blood "
        "alcohol testing?)\t"
        "Do you have a history of alcohol use or withdrawals?\n"
        "12/27/25 2259\tYes A\tNo A\tNo A\tNo A\n"
    )

    def test_removed_block_extracted(self):
        days = _make_days(self.TEXT, "REMOVED")
        result = extract_sbirt_screening({}, days)
        assert result["sbirt_screening_present"] == "yes"
        assert len(result["flowsheet_responses"]) == 4


# ====================================================================
# 18. Score range validation
# ====================================================================

class TestScoreRangeValidation:
    def test_out_of_range_audit_c(self):
        days = _make_days("Audit-C Score: 15", "NURSING_NOTE")
        result = extract_sbirt_screening({}, days)
        assert any("out_of_range" in w for w in result["warnings"])

    def test_in_range_no_warning(self):
        days = _make_days("Audit-C Score: 4", "NURSING_NOTE")
        result = extract_sbirt_screening({}, days)
        range_warnings = [w for w in result["warnings"] if "out_of_range" in w]
        assert len(range_warnings) == 0


# ====================================================================
# 19. Evidence traceability (contract requirement)
# ====================================================================

class TestEvidenceTraceability:
    def test_all_evidence_has_raw_line_id(self):
        text = (
            "SBIRT/DAST-10\n"
            "Does the patient have an injury?: Yes\n"
            "How often do you have a drink containing alcohol?: Never\n"
            "How many standard drinks containing alcohol do you have "
            "on a typical day?: 0 to 2 drinks\n"
            "How often do you have six or more drinks on one occasion?: Never\n"
            "Audit-C Score: 0\n"
            "Have you used drugs other than those required for medical "
            "reasons? (Or did the paient test positive for un-prescribed "
            "drug use?): No\n"
        )
        days = _make_days(text, "NURSING_NOTE")
        result = extract_sbirt_screening({}, days)
        for ev in result["evidence"]:
            assert "raw_line_id" in ev, f"Missing raw_line_id: {ev}"
            assert isinstance(ev["raw_line_id"], str)
            assert len(ev["raw_line_id"]) == 16

    def test_all_responses_have_raw_line_id(self):
        text = (
            "How often do you have a drink containing alcohol?: Never\n"
            "How many standard drinks containing alcohol do you have "
            "on a typical day?: 0 to 2 drinks\n"
            "How often do you have six or more drinks on one occasion?: Never\n"
        )
        days = _make_days(text, "NURSING_NOTE")
        result = extract_sbirt_screening({}, days)
        for r in result["audit_c"]["responses"]:
            assert "raw_line_id" in r
