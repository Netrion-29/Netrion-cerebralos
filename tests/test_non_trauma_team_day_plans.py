#!/usr/bin/env python3
"""
Tests for non_trauma_team_day_plans_v1 feature extractor
and v5 renderer integration.
"""

from __future__ import annotations

import pytest
from cerebralos.features.non_trauma_team_day_plans_v1 import (
    extract_non_trauma_team_day_plans,
    _detect_service,
    _extract_brief_lines,
    _extract_note_header,
    _is_trauma_note,
    _is_radiology_read,
    _make_raw_line_id,
)
from cerebralos.reporting.render_trauma_daily_notes_v5 import (
    _render_non_trauma_day_plans,
)


# ════════════════════════════════════════════════════════════════════
# Helpers — build minimal timeline data
# ════════════════════════════════════════════════════════════════════

def _make_item(
    item_type: str = "PHYSICIAN_NOTE",
    text: str = "",
    dt: str = "2026-01-02T08:30:00",
    source_id: str = "42",
) -> dict:
    return {
        "type": item_type,
        "dt": dt,
        "source_id": source_id,
        "payload": {"text": text},
    }


def _make_days_data(items_by_day: dict) -> dict:
    """Build a minimal patient_days_v1.json structure."""
    days = {}
    for day_iso, items in items_by_day.items():
        days[day_iso] = {"items": items}
    return {"days": days}


def _make_pat_features(feature_days: dict | None = None) -> dict:
    return {"days": feature_days or {}}


# ════════════════════════════════════════════════════════════════════
# Unit tests: _is_trauma_note
# ════════════════════════════════════════════════════════════════════

class TestIsTraumaNote:
    def test_trauma_progress_note(self):
        text = "Trauma Progress Note\nAllison Kimmel, PA-C\nImps ..."
        assert _is_trauma_note(text) is True

    def test_esa_brief_update(self):
        text = "ESA Brief Update\nShort update on patient status."
        assert _is_trauma_note(text) is True

    def test_daily_progress_note_esa(self):
        text = "Daily Progress Note\nEvansville Surgical Associates\nSome text"
        assert _is_trauma_note(text) is True

    def test_daily_progress_note_non_esa(self):
        """Daily Progress Note without ESA affiliation = NOT trauma."""
        text = "Daily Progress Note\nDeaconess Care Group\nSome text"
        assert _is_trauma_note(text) is False

    def test_hospitalist_note(self):
        text = "Deaconess Care Group\nHospital Progress Note\nAssessment: ..."
        assert _is_trauma_note(text) is False

    def test_neurosurgery_note(self):
        text = "Neurosurgery - T8 fracture (Uluc)\nPlan: Continue brace."
        assert _is_trauma_note(text) is False

    def test_critical_care_note(self):
        text = "Deaconess Pulmonary / Critical Care Group\nICU Day 3"
        assert _is_trauma_note(text) is False


# ════════════════════════════════════════════════════════════════════
# Unit tests: _is_radiology_read
# ════════════════════════════════════════════════════════════════════

class TestIsRadiologyRead:
    def test_narrative_impression(self):
        assert _is_radiology_read("Narrative & Impression\nSome text") is True

    def test_indication_findings(self):
        text = "INDICATION: fall\nTECHNIQUE: CT\nFINDINGS: normal"
        assert _is_radiology_read(text) is True

    def test_clinical_note(self):
        text = "Hospital Progress Note\nAssessment: Stable."
        assert _is_radiology_read(text) is False


# ════════════════════════════════════════════════════════════════════
# Unit tests: _detect_service
# ════════════════════════════════════════════════════════════════════

class TestDetectService:
    def test_hospitalist(self):
        text = "Deaconess Care Group\nHospital Progress Note"
        assert _detect_service(text, "PHYSICIAN_NOTE") == "Hospitalist"

    def test_hospital_progress_note(self):
        text = "Hospital Progress Note\nDay 3 assessment"
        assert _detect_service(text, "PHYSICIAN_NOTE") == "Hospitalist"

    def test_critical_care(self):
        text = "Deaconess Pulmonary / Critical Care Group\nICU Day 2"
        assert _detect_service(text, "PHYSICIAN_NOTE") == "Critical Care"

    def test_pccm(self):
        text = "PCCM team evaluated patient.\nPlan: Wean ventilator."
        assert _detect_service(text, "PHYSICIAN_NOTE") == "Critical Care"

    def test_neurosurgery(self):
        text = "Neurosurgery - T8 fracture (Uluc)\nFollow up."
        assert _detect_service(text, "PHYSICIAN_NOTE") == "Neurosurgery"

    def test_physical_therapy(self):
        text = "PHYSICAL THERAPY\nEARLY MOBILITY\nPatient assessment"
        assert _detect_service(text, "PHYSICIAN_NOTE") == "Physical Therapy"

    def test_occupational_therapy(self):
        text = "OCCUPATIONAL THERAPY\nASSESSMENT NOTE\nFunctional eval"
        assert _detect_service(text, "PHYSICIAN_NOTE") == "Occupational Therapy"

    def test_early_mobility_ot(self):
        text = "EARLY MOBILITY - ASSESSMENT\nOT evaluation"
        assert _detect_service(text, "PHYSICIAN_NOTE") == "Occupational Therapy"

    def test_speech_language_pathology(self):
        text = "Speech Language Pathology:\nClinical Swallow Evaluation"
        assert _detect_service(text, "PHYSICIAN_NOTE") == "Speech Language Pathology"

    def test_case_mgmt(self):
        text = "Any text here, CASE_MGMT type overrides detection"
        assert _detect_service(text, "CASE_MGMT") == "Case Management"

    def test_pharmacy_skip(self):
        text = "DEA #: BR1234\nOrdering User: Smith\nMedication info"
        assert _detect_service(text, "PHYSICIAN_NOTE") is None

    def test_oncall_np_skip(self):
        text = "On-call NP notified by RN about patient status"
        assert _detect_service(text, "PHYSICIAN_NOTE") is None

    def test_unknown_service(self):
        text = "Some random progress note without identifiable header."
        assert _detect_service(text, "PHYSICIAN_NOTE") == "Other Physician"


# ════════════════════════════════════════════════════════════════════
# Unit tests: _extract_brief_lines
# ════════════════════════════════════════════════════════════════════

class TestExtractBriefLines:
    def test_extract_assessment_plan(self):
        text = (
            "Hospital Progress Note\n"
            "Deaconess Care Group\n"
            "Date: 2026-01-02\n"
            "\n"
            "Assessment:\n"
            "  Patient stable, improving.\n"
            "  Continue current management.\n"
            "Plan:\n"
            "  Advance diet.\n"
            "  Physical therapy consult.\n"
        )
        lines = _extract_brief_lines(text)
        assert len(lines) >= 2
        assert any("Assessment" in ln for ln in lines)

    def test_terminators_stop_extraction(self):
        text = (
            "Assessment:\n"
            "  Patient stable.\n"
            "I have seen and examined patient on this date.\n"
            "  More text that should NOT appear.\n"
        )
        lines = _extract_brief_lines(text)
        assert not any("More text" in ln for ln in lines)

    def test_signature_stops_extraction(self):
        text = (
            "Assessment:\n"
            "  Patient stable.\n"
            "John Smith, MD\n"
            "  More text after signature.\n"
        )
        lines = _extract_brief_lines(text)
        assert not any("More text" in ln for ln in lines)

    def test_fallback_extraction(self):
        """When no Assessment/Plan section, extract from body."""
        text = (
            "PHYSICAL THERAPY\n"
            "EARLY MOBILITY\n"
            "Patient Name: Test\n"
            "Patient mobilised to chair with moderate assistance.\n"
            "Ambulated 50 feet with rolling walker.\n"
        )
        lines = _extract_brief_lines(text)
        assert len(lines) >= 1

    def test_max_lines_cap(self):
        text = "Assessment:\n" + "\n".join(
            f"  Line {i}: clinical content here." for i in range(20)
        )
        lines = _extract_brief_lines(text)
        assert len(lines) <= 12  # _MAX_BRIEF_LINES

    def test_empty_note(self):
        lines = _extract_brief_lines("")
        assert lines == []


# ════════════════════════════════════════════════════════════════════
# Unit tests: _extract_note_header
# ════════════════════════════════════════════════════════════════════

class TestExtractNoteHeader:
    def test_simple_header(self):
        text = "Hospital Progress Note\nSome content"
        assert _extract_note_header(text) == "Hospital Progress Note"

    def test_skips_blank_lines(self):
        text = "\n\nNeurosurgery - T8 fracture\nContent"
        assert _extract_note_header(text) == "Neurosurgery - T8 fracture"

    def test_truncates_long_header(self):
        text = "A" * 200 + "\nContent"
        header = _extract_note_header(text)
        assert len(header) <= 100


# ════════════════════════════════════════════════════════════════════
# Unit tests: _make_raw_line_id
# ════════════════════════════════════════════════════════════════════

class TestMakeRawLineId:
    def test_deterministic(self):
        h1 = _make_raw_line_id("42", "2026-01-02T08:30", "preview")
        h2 = _make_raw_line_id("42", "2026-01-02T08:30", "preview")
        assert h1 == h2

    def test_different_inputs(self):
        h1 = _make_raw_line_id("42", "2026-01-02T08:30", "a")
        h2 = _make_raw_line_id("42", "2026-01-02T08:30", "b")
        assert h1 != h2

    def test_length(self):
        h = _make_raw_line_id("42", "2026-01-02T08:30", "preview")
        assert len(h) == 16


# ════════════════════════════════════════════════════════════════════
# Integration tests: extract_non_trauma_team_day_plans
# ════════════════════════════════════════════════════════════════════

class TestExtractNonTraumaTeamDayPlans:
    def test_empty_timeline(self):
        result = extract_non_trauma_team_day_plans(
            _make_pat_features(),
            _make_days_data({}),
        )
        assert result["source_rule_id"] == "no_qualifying_notes"
        assert result["total_notes"] == 0
        assert result["days"] == {}

    def test_only_trauma_notes(self):
        """Timeline with only trauma notes → no_qualifying_notes."""
        items = [
            _make_item(text="Trauma Progress Note\nAllison Kimmel, PA-C\nPlan:\n  Continue care."),
        ]
        result = extract_non_trauma_team_day_plans(
            _make_pat_features(),
            _make_days_data({"2026-01-02": items}),
        )
        assert result["source_rule_id"] == "no_qualifying_notes"
        assert result["total_notes"] == 0

    def test_hospitalist_note_extracted(self):
        """A hospitalist note should be extracted and classified."""
        text = (
            "Deaconess Care Group\n"
            "Hospital Progress Note\n"
            "John Smith, MD\n"
            "\n"
            "Assessment:\n"
            "  Patient stable, improving.\n"
            "  Continue current management.\n"
            "Plan:\n"
            "  Advance diet.\n"
        )
        items = [_make_item(text=text, dt="2026-01-02T09:00:00")]
        result = extract_non_trauma_team_day_plans(
            _make_pat_features(),
            _make_days_data({"2026-01-02": items}),
        )
        assert result["source_rule_id"] == "non_trauma_day_plans_extracted"
        assert result["total_notes"] == 1
        assert "Hospitalist" in result["services_seen"]
        day = result["days"]["2026-01-02"]
        assert "Hospitalist" in day["services"]
        hosp = day["services"]["Hospitalist"]
        assert hosp["note_count"] == 1
        assert hosp["notes"][0]["service"] == "Hospitalist"
        assert len(hosp["notes"][0]["brief_lines"]) > 0

    def test_critical_care_note(self):
        text = (
            "Deaconess Pulmonary / Critical Care Group\n"
            "ICU Day 3\n"
            "Jane Doe, MD\n"
            "Assessment:\n"
            "  Respiratory failure, improving.\n"
            "Plan:\n"
            "  Continue vent wean.\n"
        )
        items = [_make_item(text=text)]
        result = extract_non_trauma_team_day_plans(
            _make_pat_features(),
            _make_days_data({"2026-01-02": items}),
        )
        assert result["total_notes"] == 1
        assert "Critical Care" in result["services_seen"]

    def test_case_mgmt_item(self):
        text = (
            "Case Manager Update\n"
            "Patient stable for discharge planning.\n"
            "Assessment:\n"
            "  Discharge to rehab facility.\n"
        )
        items = [_make_item(item_type="CASE_MGMT", text=text)]
        result = extract_non_trauma_team_day_plans(
            _make_pat_features(),
            _make_days_data({"2026-01-02": items}),
        )
        assert result["total_notes"] == 1
        assert "Case Management" in result["services_seen"]

    def test_multiple_services_same_day(self):
        """Multiple services on the same day, grouped correctly."""
        hosp_text = "Deaconess Care Group\nAssessment:\n  Patient stable.\n"
        pt_text = (
            "PHYSICAL THERAPY\nEARLY MOBILITY\nHeader\n"
            "Assessment:\n"
            "  Patient walked 100 ft with rolling walker.\n"
            "  Plan: Continue mobilisation twice daily.\n"
        )
        items = [
            _make_item(text=hosp_text, dt="2026-01-02T08:00:00", source_id="1"),
            _make_item(text=pt_text, dt="2026-01-02T10:00:00", source_id="2"),
        ]
        result = extract_non_trauma_team_day_plans(
            _make_pat_features(),
            _make_days_data({"2026-01-02": items}),
        )
        assert result["total_notes"] == 2
        assert result["total_services"] == 2
        day = result["days"]["2026-01-02"]
        assert day["service_count"] == 2
        assert "Hospitalist" in day["services"]
        assert "Physical Therapy" in day["services"]

    def test_multi_day(self):
        hosp_text = "Deaconess Care Group\nAssessment:\n  Day 1 stable.\n"
        hosp_text2 = "Deaconess Care Group\nAssessment:\n  Day 2 improving.\n"
        days_data = _make_days_data({
            "2026-01-02": [_make_item(text=hosp_text, dt="2026-01-02T09:00:00", source_id="1")],
            "2026-01-03": [_make_item(text=hosp_text2, dt="2026-01-03T09:00:00", source_id="2")],
        })
        result = extract_non_trauma_team_day_plans(
            _make_pat_features(), days_data,
        )
        assert result["total_days"] == 2
        assert result["total_notes"] == 2

    def test_skips_radiology_reads(self):
        text = "Narrative & Impression\nINDICATION: fall\nFINDINGS: normal"
        items = [_make_item(text=text)]
        result = extract_non_trauma_team_day_plans(
            _make_pat_features(),
            _make_days_data({"2026-01-02": items}),
        )
        assert result["total_notes"] == 0

    def test_skips_consult_note_type(self):
        """CONSULT_NOTE items should NOT be processed (handled by consultant pipeline)."""
        text = "Neurosurgery Consult\nAssessment: fracture stable.\n"
        items = [_make_item(item_type="CONSULT_NOTE", text=text)]
        result = extract_non_trauma_team_day_plans(
            _make_pat_features(),
            _make_days_data({"2026-01-02": items}),
        )
        assert result["total_notes"] == 0

    def test_skips_undated(self):
        items = [_make_item(text="Deaconess Care Group\nAssessment:\n  Stable.\n")]
        result = extract_non_trauma_team_day_plans(
            _make_pat_features(),
            _make_days_data({"__UNDATED__": items}),
        )
        assert result["total_notes"] == 0

    def test_deterministic(self):
        """Same input → same output always."""
        text = "Deaconess Care Group\nAssessment:\n  Stable.\nPlan:\n  Continue.\n"
        items = [_make_item(text=text)]
        dd = _make_days_data({"2026-01-02": items})
        pf = _make_pat_features()
        r1 = extract_non_trauma_team_day_plans(pf, dd)
        r2 = extract_non_trauma_team_day_plans(pf, dd)
        assert r1 == r2

    def test_empty_text_skipped(self):
        items = [_make_item(text="")]
        result = extract_non_trauma_team_day_plans(
            _make_pat_features(),
            _make_days_data({"2026-01-02": items}),
        )
        assert result["total_notes"] == 0

    def test_raw_line_id_present(self):
        text = "Deaconess Care Group\nAssessment:\n  Stable.\n"
        items = [_make_item(text=text)]
        result = extract_non_trauma_team_day_plans(
            _make_pat_features(),
            _make_days_data({"2026-01-02": items}),
        )
        note = result["days"]["2026-01-02"]["services"]["Hospitalist"]["notes"][0]
        assert "raw_line_id" in note
        assert len(note["raw_line_id"]) == 16

    def test_schema_keys(self):
        """Output schema has all required top-level keys."""
        result = extract_non_trauma_team_day_plans(
            _make_pat_features(),
            _make_days_data({}),
        )
        expected_keys = {
            "days", "total_days", "total_notes", "total_services",
            "services_seen", "source_rule_id", "warnings", "notes",
        }
        assert set(result.keys()) == expected_keys

    def test_note_schema_keys(self):
        text = "Deaconess Care Group\nAssessment:\n  Stable.\n"
        items = [_make_item(text=text)]
        result = extract_non_trauma_team_day_plans(
            _make_pat_features(),
            _make_days_data({"2026-01-02": items}),
        )
        note = result["days"]["2026-01-02"]["services"]["Hospitalist"]["notes"][0]
        expected = {
            "dt", "source_id", "author", "service", "note_header",
            "brief_lines", "brief_line_count", "raw_line_id",
        }
        assert set(note.keys()) == expected


# ════════════════════════════════════════════════════════════════════
# v5 Renderer tests: _render_non_trauma_day_plans
# ════════════════════════════════════════════════════════════════════

class TestRenderNonTraumaDayPlans:
    def test_empty_features(self):
        lines = _render_non_trauma_day_plans({}, "2026-01-02")
        assert lines == []

    def test_no_data_for_day(self):
        feats = {
            "non_trauma_team_day_plans_v1": {
                "days": {},
            },
        }
        lines = _render_non_trauma_day_plans(feats, "2026-01-02")
        assert lines == []

    def test_renders_header(self):
        feats = {
            "non_trauma_team_day_plans_v1": {
                "days": {
                    "2026-01-02": {
                        "services": {
                            "Hospitalist": {
                                "notes": [{
                                    "dt": "2026-01-02T09:00:00",
                                    "author": "John Smith, MD",
                                    "service": "Hospitalist",
                                    "note_header": "Hospital Progress Note",
                                    "brief_lines": ["Assessment:", "  Patient stable."],
                                    "brief_line_count": 2,
                                    "raw_line_id": "abc123def456",
                                    "source_id": "42",
                                }],
                                "note_count": 1,
                            },
                        },
                        "service_count": 1,
                        "note_count": 1,
                    },
                },
            },
        }
        lines = _render_non_trauma_day_plans(feats, "2026-01-02")
        assert lines[0] == "Non-Trauma Day Plans:"
        assert any("[Hospitalist]" in ln for ln in lines)
        assert any("John Smith, MD" in ln for ln in lines)
        assert any("Patient stable" in ln for ln in lines)

    def test_multiple_services_sorted(self):
        feats = {
            "non_trauma_team_day_plans_v1": {
                "days": {
                    "2026-01-02": {
                        "services": {
                            "Physical Therapy": {
                                "notes": [{
                                    "dt": "2026-01-02T10:00:00",
                                    "author": "DATA NOT AVAILABLE",
                                    "service": "Physical Therapy",
                                    "note_header": "PHYSICAL THERAPY",
                                    "brief_lines": ["Mobilised patient."],
                                    "brief_line_count": 1,
                                    "raw_line_id": "def456",
                                    "source_id": "43",
                                }],
                                "note_count": 1,
                            },
                            "Hospitalist": {
                                "notes": [{
                                    "dt": "2026-01-02T09:00:00",
                                    "author": "John Smith, MD",
                                    "service": "Hospitalist",
                                    "note_header": "Hospital Progress Note",
                                    "brief_lines": ["Patient stable."],
                                    "brief_line_count": 1,
                                    "raw_line_id": "abc123",
                                    "source_id": "42",
                                }],
                                "note_count": 1,
                            },
                        },
                        "service_count": 2,
                        "note_count": 2,
                    },
                },
            },
        }
        lines = _render_non_trauma_day_plans(feats, "2026-01-02")
        # Services should be alphabetically sorted
        hosp_idx = next(i for i, ln in enumerate(lines) if "[Hospitalist]" in ln)
        pt_idx = next(i for i, ln in enumerate(lines) if "[Physical Therapy]" in ln)
        assert hosp_idx < pt_idx

    def test_no_dna_when_empty(self):
        """Empty feature should NOT produce any output (no DNA line)."""
        feats = {
            "non_trauma_team_day_plans_v1": {
                "days": {},
                "source_rule_id": "no_qualifying_notes",
            },
        }
        lines = _render_non_trauma_day_plans(feats, "2026-01-02")
        assert lines == []
        assert not any("DATA NOT AVAILABLE" in ln for ln in lines)
