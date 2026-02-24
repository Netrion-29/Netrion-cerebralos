#!/usr/bin/env python3
"""
Tests for note_sections_v1 — deterministic trauma note section extraction.

Covers:
  1. Standard TRAUMA_HP with all five sections
  2. TRAUMA_HP with missing sections
  3. No qualifying source → DATA NOT AVAILABLE
  4. Primary Survey sub-field extraction
  5. Radiological IMPRESSION exclusion
  6. Fallback source (ED_NOTE when no TRAUMA_HP)
  7. Anna Dennis outlier ("History of Present Illness")
  8. Assessment/Plan fallback for Plan
  9. Evidence raw_line_id present
  10. Empty note text
"""

from __future__ import annotations

import pytest

from cerebralos.features.note_sections_v1 import extract_note_sections

# ── Helpers ─────────────────────────────────────────────────────────

def _make_days(items, day="2025-01-15"):
    """Wrap timeline items into a minimal days_data structure."""
    return {
        "days": {
            day: {
                "items": items,
            }
        }
    }


def _make_item(text, item_type="TRAUMA_HP", dt="2025-01-15T08:00:00"):
    """Build a minimal timeline item."""
    return {
        "type": item_type,
        "dt": dt,
        "source_id": "test_source_1",
        "payload": {"text": text},
    }


STANDARD_TRAUMA_HP = """\
HPI: 42 year old male involved in a motorcycle crash at approximately 0300.
Patient was found at scene with helmet on. GCS 15 at scene.
Primary Survey:
            Airway: Patent, no issues
            Breathing: Clear bilateral breath sounds
            Circulation: 2+ pulses in all extremities, no active hemorrhage
            Disability: GCS 15 (E4V5M6), PERRL
            Exposure: Abrasions to left shoulder and left hip
            FAST: Yes - negative
Secondary Survey:
Head: No lacerations, no step-offs
Neck: Midline cervical tenderness
Chest: No crepitus, no deformity
Abdomen: Soft, non-tender
Pelvis: Stable
Extremities: Left shoulder abrasion, ROM intact
Radiographs:
CT Head: No acute intracranial pathology
CT C-spine: No fracture
IMPRESSION: No acute findings
Labs:
WBC 12.1, H/H 14.2/42, Plt 245
Impression:
1. Motorcycle crash with helmet
2. Left shoulder abrasion
3. Cervical strain
Plan:
1. Admit to trauma service for observation
2. Serial neuro checks
3. Pain management
4. Follow up CT if symptoms change
"""

# ── Tests ───────────────────────────────────────────────────────────


class TestStandardTraumaHP:
    """Standard TRAUMA_HP with all five sections."""

    def setup_method(self):
        item = _make_item(STANDARD_TRAUMA_HP)
        days_data = _make_days([item])
        self.result = extract_note_sections({"days": {}}, days_data)

    def test_sections_present(self):
        assert self.result["sections_present"] is True

    def test_source_type(self):
        assert self.result["source_type"] == "TRAUMA_HP"

    def test_source_rule_id(self):
        assert self.result["source_rule_id"] == "trauma_hp_sections"

    def test_hpi_present(self):
        assert self.result["hpi"]["present"] is True
        assert "motorcycle crash" in self.result["hpi"]["text"].lower()

    def test_hpi_line_count(self):
        assert self.result["hpi"]["line_count"] >= 1

    def test_primary_survey_present(self):
        assert self.result["primary_survey"]["present"] is True

    def test_primary_survey_fields(self):
        fields = self.result["primary_survey"]["fields"]
        assert fields["airway"] is not None
        assert "patent" in fields["airway"].lower()
        assert fields["breathing"] is not None
        assert fields["circulation"] is not None
        assert fields["disability"] is not None
        assert "gcs 15" in fields["disability"].lower()
        assert fields["exposure"] is not None
        assert fields["fast"] is not None
        assert "negative" in fields["fast"].lower()

    def test_secondary_survey_present(self):
        assert self.result["secondary_survey"]["present"] is True
        assert "head" in self.result["secondary_survey"]["text"].lower()

    def test_impression_present(self):
        assert self.result["impression"]["present"] is True
        assert "motorcycle crash" in self.result["impression"]["text"].lower()

    def test_impression_excludes_radiological(self):
        """Clinical Impression should NOT contain radiological content."""
        imp_text = self.result["impression"]["text"]
        assert "no acute findings" not in imp_text.lower()

    def test_plan_present(self):
        assert self.result["plan"]["present"] is True
        assert "admit" in self.result["plan"]["text"].lower()

    def test_evidence_has_raw_line_id(self):
        for ev in self.result["evidence"]:
            assert "raw_line_id" in ev
            assert len(ev["raw_line_id"]) == 16

    def test_evidence_count(self):
        # Should have one evidence entry per section found
        assert len(self.result["evidence"]) == 5

    def test_evidence_sections(self):
        sections = {ev["section"] for ev in self.result["evidence"]}
        assert sections == {"hpi", "primary_survey", "secondary_survey", "impression", "plan"}


class TestNoQualifyingSource:
    """No qualifying note types at all → DATA NOT AVAILABLE."""

    def test_dna_no_items(self):
        days_data = {"days": {"2025-01-15": {"items": []}}}
        result = extract_note_sections({"days": {}}, days_data)
        assert result["sections_present"] == "DATA NOT AVAILABLE"
        assert result["source_type"] is None
        assert result["source_rule_id"] == "no_qualifying_source"
        assert "no_qualifying_source" in result["warnings"]

    def test_dna_empty_days(self):
        result = extract_note_sections({"days": {}}, {"days": {}})
        assert result["sections_present"] == "DATA NOT AVAILABLE"

    def test_dna_non_qualifying_type(self):
        item = _make_item("Some note text", item_type="LAB_RESULT")
        days_data = _make_days([item])
        result = extract_note_sections({"days": {}}, days_data)
        assert result["sections_present"] == "DATA NOT AVAILABLE"


class TestMissingSections:
    """TRAUMA_HP with only some sections present."""

    def test_hpi_only(self):
        text = "HPI: Patient fell from standing height.\nPMH: HTN, DM"
        item = _make_item(text)
        result = extract_note_sections({"days": {}}, _make_days([item]))
        assert result["sections_present"] is True
        assert result["hpi"]["present"] is True
        assert result["primary_survey"]["present"] is False
        assert result["secondary_survey"]["present"] is False
        assert result["impression"]["present"] is False
        assert result["plan"]["present"] is False

    def test_no_plan(self):
        text = """\
HPI: MVC at highway speed.
Primary Survey:
            Airway: Patent
            Breathing: CTA bilaterally
            Circulation: Normal
            Disability: GCS 15
            Exposure: No injuries
            FAST: No
Secondary Survey:
Head: Normal
Impression:
Polytrauma, MVC
"""
        item = _make_item(text)
        result = extract_note_sections({"days": {}}, _make_days([item]))
        assert result["impression"]["present"] is True
        assert result["plan"]["present"] is False
        assert "plan" in result["notes"][1] if len(result["notes"]) > 1 else True


class TestPrimarySurveyFields:
    """Primary Survey sub-field extraction."""

    def test_partial_fields(self):
        text = """\
Primary Survey:
            Airway: Intubated in field
            Breathing: Decreased left
            Circulation: Tachycardic, HR 120
Secondary Survey:
Head: Laceration
"""
        item = _make_item(text)
        result = extract_note_sections({"days": {}}, _make_days([item]))
        fields = result["primary_survey"]["fields"]
        assert fields["airway"] is not None
        assert "intubated" in fields["airway"].lower()
        assert fields["breathing"] is not None
        assert fields["circulation"] is not None
        # These were not present in the text
        assert fields["disability"] is None
        assert fields["exposure"] is None
        assert fields["fast"] is None


class TestRadiologicalImpressionExclusion:
    """Radiological IMPRESSION: inside Radiographs block is excluded."""

    def test_only_radiological_impression(self):
        text = """\
HPI: Fall from ladder.
Radiographs:
CT Head without contrast:
IMPRESSION: No acute intracranial hemorrhage.
Plan:
1. Discharge home
"""
        item = _make_item(text)
        result = extract_note_sections({"days": {}}, _make_days([item]))
        # The clinical Impression section should NOT be present
        # (only radiological IMPRESSION exists, which is excluded)
        assert result["impression"]["present"] is False
        assert result["plan"]["present"] is True


class TestFallbackSource:
    """ED_NOTE used when TRAUMA_HP has no sections."""

    def test_ed_note_fallback(self):
        ed_text = """\
HPI: Patient presents after ground-level fall.
Assessment/Plan:
1. Left hip fracture
2. Ortho consult
"""
        item = _make_item(ed_text, item_type="ED_NOTE")
        result = extract_note_sections({"days": {}}, _make_days([item]))
        assert result["sections_present"] is True
        assert result["source_type"] == "ED_NOTE"
        assert result["source_rule_id"] == "ed_note_sections"
        assert "non_trauma_hp_source" in result["warnings"]
        assert result["hpi"]["present"] is True
        # Assessment/Plan fallback for Plan
        assert result["plan"]["present"] is True

    def test_trauma_hp_preferred_over_ed(self):
        trauma_item = _make_item("HPI: MVC.\nPrimary Survey:\n            Airway: Patent\nSecondary Survey:\nHead: Normal",
                                  item_type="TRAUMA_HP", dt="2025-01-15T08:00:00")
        ed_item = _make_item("HPI: MVC.\nAssessment/Plan:\n1. Admit",
                              item_type="ED_NOTE", dt="2025-01-15T07:00:00")
        days_data = _make_days([ed_item, trauma_item])
        result = extract_note_sections({"days": {}}, days_data)
        assert result["source_type"] == "TRAUMA_HP"


class TestAnnaDennisOutlier:
    """Anna Dennis uses 'History of Present Illness:' instead of 'HPI:'."""

    def test_history_of_present_illness(self):
        text = """\
History of Present Illness: 67-year-old female presents after syncopal
episode with fall. Found on floor by family.
Plan:
1. CT head
2. Admit for observation
"""
        item = _make_item(text)
        result = extract_note_sections({"days": {}}, _make_days([item]))
        assert result["hpi"]["present"] is True
        assert "syncopal" in result["hpi"]["text"].lower()


class TestAssessmentPlanFallback:
    """Assessment/Plan: is used when no standalone Plan: exists."""

    def test_assessment_plan(self):
        text = """\
HPI: Fall from standing.
Assessment/Plan:
1. Ground level fall
2. Contusion left hip
3. Discharge with follow up
"""
        item = _make_item(text, item_type="ED_NOTE")
        result = extract_note_sections({"days": {}}, _make_days([item]))
        assert result["plan"]["present"] is True
        assert "ground level fall" in result["plan"]["text"].lower()


class TestEmptyNoteText:
    """Notes with empty text should be skipped."""

    def test_empty_payload(self):
        item = {"type": "TRAUMA_HP", "dt": "2025-01-15T08:00:00",
                "source_id": "x", "payload": {"text": ""}}
        result = extract_note_sections({"days": {}}, _make_days([item]))
        assert result["sections_present"] == "DATA NOT AVAILABLE"

    def test_whitespace_only(self):
        item = {"type": "TRAUMA_HP", "dt": "2025-01-15T08:00:00",
                "source_id": "x", "payload": {"text": "   \n\n  "}}
        result = extract_note_sections({"days": {}}, _make_days([item]))
        assert result["sections_present"] == "DATA NOT AVAILABLE"


class TestEvidenceIntegrity:
    """Evidence entries must have all required fields."""

    def test_evidence_fields(self):
        item = _make_item(STANDARD_TRAUMA_HP)
        result = extract_note_sections({"days": {}}, _make_days([item]))
        for ev in result["evidence"]:
            assert "raw_line_id" in ev
            assert "source_type" in ev
            assert "ts" in ev
            assert "section" in ev
            assert "snippet" in ev
            assert isinstance(ev["raw_line_id"], str)
            assert len(ev["raw_line_id"]) == 16
