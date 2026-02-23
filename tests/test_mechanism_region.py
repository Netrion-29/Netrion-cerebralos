#!/usr/bin/env python3
"""
Tests for Mechanism of Injury + Body Region Extraction v1.

Covers:
  - Mechanism extraction from HPI (all major pattern families)
  - Body region extraction from HPI + Secondary Survey
  - Penetrating vs blunt classification
  - Source priority (TRAUMA_HP > ED_NOTE > PHYSICIAN_NOTE)
  - History/chronic context exclusion
  - Fail-closed: no qualifying source → DNA
  - Fail-closed: source present but no pattern match → "no"
  - Evidence traceability (raw_line_id on every evidence entry)
  - Multiple mechanisms in a single HPI
  - Multiple body regions
  - Edge cases (whitespace, case insensitivity)
"""

import sys
from pathlib import Path

import pytest

# Ensure project root is on import path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cerebralos.features.mechanism_region_v1 import (
    _extract_mechanisms_from_text,
    _extract_body_regions_from_text,
    _extract_section,
    _make_raw_line_id,
    extract_mechanism_region,
    RE_HPI_START,
    RE_HPI_END,
)


# ── Helpers ─────────────────────────────────────────────────────────

def _make_days_data(items_by_day):
    """Build a minimal days_data dict from {day_iso: [items]}."""
    days = {}
    for day_iso, items in items_by_day.items():
        days[day_iso] = {"items": items}
    return {"days": days, "meta": {}}


def _make_trauma_hp_item(text, dt="2025-12-18T16:17:00", source_id="0"):
    """Build a minimal TRAUMA_HP timeline item."""
    return {
        "type": "TRAUMA_HP",
        "dt": dt,
        "source_id": source_id,
        "payload": {"text": text},
    }


def _make_ed_note_item(text, dt="2025-12-18T17:00:00", source_id="99"):
    """Build a minimal ED_NOTE timeline item."""
    return {
        "type": "ED_NOTE",
        "dt": dt,
        "source_id": source_id,
        "payload": {"text": text},
    }


def _make_physician_note_item(text, dt="2025-12-18T17:30:00", source_id="50"):
    """Build a minimal PHYSICIAN_NOTE timeline item."""
    return {
        "type": "PHYSICIAN_NOTE",
        "dt": dt,
        "source_id": source_id,
        "payload": {"text": text},
    }


_HP_TEMPLATE = """\
[TRAUMA_HP] {dt}
Signed

Trauma H & P

Alert History: Category 1 alert at 1558.
HPI: {hpi_text}
Primary Survey:
            Airway: patent
            Breathing: even, nonlabored

Secondary Survey:
{secondary_survey_text}

PMH: PAST MEDICAL HISTORY
"""


def _hp_text(hpi_text, secondary_survey_text="General: NAD", dt="2025-12-18 16:17:00"):
    """Build TRAUMA_HP text with given HPI and Secondary Survey."""
    return _HP_TEMPLATE.format(
        hpi_text=hpi_text,
        secondary_survey_text=secondary_survey_text,
        dt=dt,
    )


# ═══════════════════════════════════════════════════════════════════
# § Mechanism extraction — individual patterns
# ═══════════════════════════════════════════════════════════════════

class TestMechanismFall:
    """Fall mechanism extraction."""

    def test_fall_presents_after(self):
        text = _hp_text("78 yo female presents after a fall at home.")
        days_data = _make_days_data({"2025-12-18": [_make_trauma_hp_item(text)]})
        result = extract_mechanism_region({"days": {}}, days_data)
        assert result["mechanism_present"] == "yes"
        assert result["mechanism_primary"] == "fall"
        assert "fall" in result["mechanism_labels"]
        assert result["penetrating_mechanism"] is False

    def test_fall_ground_level(self):
        text = _hp_text("70 yo male presents via ED transfer from OSH s/p ground level fall.")
        days_data = _make_days_data({"2025-12-18": [_make_trauma_hp_item(text)]})
        result = extract_mechanism_region({"days": {}}, days_data)
        assert result["mechanism_present"] == "yes"
        assert "fall" in result["mechanism_labels"]

    def test_fall_found_down(self):
        text = _hp_text("84 yo male reportedly being found down in the basement by family.")
        days_data = _make_days_data({"2025-12-18": [_make_trauma_hp_item(text)]})
        result = extract_mechanism_region({"days": {}}, days_data)
        assert result["mechanism_present"] == "yes"
        assert "fall" in result["mechanism_labels"]

    def test_fell_today(self):
        text = _hp_text("Patient states she fell today and hit her head.")
        days_data = _make_days_data({"2025-12-18": [_make_trauma_hp_item(text)]})
        result = extract_mechanism_region({"days": {}}, days_data)
        assert result["mechanism_present"] == "yes"
        assert "fall" in result["mechanism_labels"]

    def test_fell_striking(self):
        text = _hp_text("Patient was stepping down and fell striking on her right side.")
        days_data = _make_days_data({"2025-12-18": [_make_trauma_hp_item(text)]})
        result = extract_mechanism_region({"days": {}}, days_data)
        assert result["mechanism_present"] == "yes"
        assert "fall" in result["mechanism_labels"]

    def test_experienced_fall(self):
        text = _hp_text("She experienced a fall on the way to the bathroom.")
        days_data = _make_days_data({"2025-12-18": [_make_trauma_hp_item(text)]})
        result = extract_mechanism_region({"days": {}}, days_data)
        assert result["mechanism_present"] == "yes"
        assert "fall" in result["mechanism_labels"]

    def test_fell_to_the_ground(self):
        text = _hp_text("She had a syncopal episode and fell to the ground.")
        days_data = _make_days_data({"2025-12-18": [_make_trauma_hp_item(text)]})
        result = extract_mechanism_region({"days": {}}, days_data)
        assert result["mechanism_present"] == "yes"
        assert "fall" in result["mechanism_labels"]


class TestMechanismMVC:
    """Motor vehicle crash mechanism extraction."""

    def test_mvc_abbreviation(self):
        text = _hp_text("47 year old male following MVC in which patient had an unknown medical event.")
        days_data = _make_days_data({"2025-12-18": [_make_trauma_hp_item(text)]})
        result = extract_mechanism_region({"days": {}}, days_data)
        assert result["mechanism_present"] == "yes"
        assert "mvc" in result["mechanism_labels"]
        assert result["penetrating_mechanism"] is False

    def test_mva_abbreviation(self):
        text = _hp_text("Patient involved in MVA yesterday.")
        days_data = _make_days_data({"2025-12-18": [_make_trauma_hp_item(text)]})
        result = extract_mechanism_region({"days": {}}, days_data)
        assert result["mechanism_present"] == "yes"
        assert "mva" in result["mechanism_labels"]

    def test_motor_vehicle_crash(self):
        text = _hp_text("She reports she was the unrestrained driver involved in a motor vehicle crash.")
        days_data = _make_days_data({"2025-12-18": [_make_trauma_hp_item(text)]})
        result = extract_mechanism_region({"days": {}}, days_data)
        assert result["mechanism_present"] == "yes"
        assert "mvc" in result["mechanism_labels"]

    def test_had_mvc(self):
        text = _hp_text("89 yo female reportedly had an MVC yesterday, she was running errands.")
        days_data = _make_days_data({"2025-12-18": [_make_trauma_hp_item(text)]})
        result = extract_mechanism_region({"days": {}}, days_data)
        assert result["mechanism_present"] == "yes"
        assert "mvc" in result["mechanism_labels"]

    def test_rollover(self):
        text = _hp_text("Patient was in single vehicle rollover accident.")
        days_data = _make_days_data({"2025-12-18": [_make_trauma_hp_item(text)]})
        result = extract_mechanism_region({"days": {}}, days_data)
        assert result["mechanism_present"] == "yes"
        assert "mvc" in result["mechanism_labels"]


class TestMechanismPenetrating:
    """Penetrating mechanism extraction (GSW, stab)."""

    def test_gsw(self):
        text = _hp_text("25 yo male presents with GSW to the abdomen.")
        days_data = _make_days_data({"2025-12-18": [_make_trauma_hp_item(text)]})
        result = extract_mechanism_region({"days": {}}, days_data)
        assert result["mechanism_present"] == "yes"
        assert "gsw" in result["mechanism_labels"]
        assert result["penetrating_mechanism"] is True

    def test_gunshot_wound(self):
        text = _hp_text("Patient sustained a gunshot wound to the chest.")
        days_data = _make_days_data({"2025-12-18": [_make_trauma_hp_item(text)]})
        result = extract_mechanism_region({"days": {}}, days_data)
        assert result["mechanism_present"] == "yes"
        assert "gsw" in result["mechanism_labels"]
        assert result["penetrating_mechanism"] is True

    def test_stab_wound(self):
        text = _hp_text("30 yo male presents with stab wound to the left chest.")
        days_data = _make_days_data({"2025-12-18": [_make_trauma_hp_item(text)]})
        result = extract_mechanism_region({"days": {}}, days_data)
        assert result["mechanism_present"] == "yes"
        assert "stab" in result["mechanism_labels"]
        assert result["penetrating_mechanism"] is True

    def test_stabbing(self):
        text = _hp_text("Patient involved in a stabbing incident.")
        days_data = _make_days_data({"2025-12-18": [_make_trauma_hp_item(text)]})
        result = extract_mechanism_region({"days": {}}, days_data)
        assert result["mechanism_present"] == "yes"
        assert "stab" in result["mechanism_labels"]
        assert result["penetrating_mechanism"] is True


class TestMechanismIndustrial:
    """Industrial/crush mechanism extraction."""

    def test_auger_injury(self):
        text = _hp_text("Patient was working in a grain bin today and got caught in the auger.")
        days_data = _make_days_data({"2025-12-18": [_make_trauma_hp_item(text)]})
        result = extract_mechanism_region({"days": {}}, days_data)
        assert result["mechanism_present"] == "yes"
        assert "industrial" in result["mechanism_labels"]

    def test_coal_mining(self):
        text = _hp_text("36 yo male who was involved in a coal mining accident.")
        days_data = _make_days_data({"2025-12-18": [_make_trauma_hp_item(text)]})
        result = extract_mechanism_region({"days": {}}, days_data)
        assert result["mechanism_present"] == "yes"
        assert "industrial" in result["mechanism_labels"]

    def test_trapped_between(self):
        text = _hp_text("The patient reports that his leg got trapped between 2 objects.")
        days_data = _make_days_data({"2025-12-18": [_make_trauma_hp_item(text)]})
        result = extract_mechanism_region({"days": {}}, days_data)
        assert result["mechanism_present"] == "yes"
        assert "crush" in result["mechanism_labels"]


class TestMechanismOther:
    """Other mechanism types."""

    def test_assault(self):
        text = _hp_text("22 yo male presents after being assaulted outside a bar.")
        days_data = _make_days_data({"2025-12-18": [_make_trauma_hp_item(text)]})
        result = extract_mechanism_region({"days": {}}, days_data)
        assert result["mechanism_present"] == "yes"
        assert "assault" in result["mechanism_labels"]

    def test_pedestrian_struck(self):
        text = _hp_text("45 yo female pedestrian struck by vehicle in parking lot.")
        days_data = _make_days_data({"2025-12-18": [_make_trauma_hp_item(text)]})
        result = extract_mechanism_region({"days": {}}, days_data)
        assert result["mechanism_present"] == "yes"
        assert "pedestrian_struck" in result["mechanism_labels"]

    def test_motorcycle_crash(self):
        text = _hp_text("28 yo male involved in a motorcycle crash at high speed.")
        days_data = _make_days_data({"2025-12-18": [_make_trauma_hp_item(text)]})
        result = extract_mechanism_region({"days": {}}, days_data)
        assert result["mechanism_present"] == "yes"
        assert "mcc" in result["mechanism_labels"]

    def test_burn(self):
        text = _hp_text("Patient presents with burns to bilateral upper extremities.")
        days_data = _make_days_data({"2025-12-18": [_make_trauma_hp_item(text)]})
        result = extract_mechanism_region({"days": {}}, days_data)
        assert result["mechanism_present"] == "yes"
        assert "burn" in result["mechanism_labels"]


# ═══════════════════════════════════════════════════════════════════
# § Body region extraction
# ═══════════════════════════════════════════════════════════════════

class TestBodyRegions:
    """Body region label extraction from HPI + Secondary Survey."""

    def test_head_from_hpi(self):
        text = _hp_text("Patient fell and hit her head on the floor.",
                        "HEENT: forehead laceration")
        days_data = _make_days_data({"2025-12-18": [_make_trauma_hp_item(text)]})
        result = extract_mechanism_region({"days": {}}, days_data)
        assert "head" in result["body_region_labels"]

    def test_chest_from_secondary_survey(self):
        text = _hp_text(
            "78 yo female presents after a fall.",
            "Chest wall: Right-sided chest wall tenderness.\n"
            "Abdomen: Soft, non-tender.",
        )
        days_data = _make_days_data({"2025-12-18": [_make_trauma_hp_item(text)]})
        result = extract_mechanism_region({"days": {}}, days_data)
        assert "chest" in result["body_region_labels"]

    def test_multiple_regions(self):
        text = _hp_text(
            "Patient presents after a fall with head and chest injuries.",
            "HEENT: frontal abrasion\n"
            "Chest wall: rib tenderness\n"
            "Pelvis: Stable\n"
            "Extremities: Left femur deformity",
        )
        days_data = _make_days_data({"2025-12-18": [_make_trauma_hp_item(text)]})
        result = extract_mechanism_region({"days": {}}, days_data)
        assert result["body_region_present"] == "yes"
        assert "head" in result["body_region_labels"]
        assert "chest" in result["body_region_labels"]
        assert "pelvis" in result["body_region_labels"]
        assert "extremity" in result["body_region_labels"]

    def test_abdomen_from_hpi(self):
        text = _hp_text("Patient presents with GSW to the abdomen.")
        days_data = _make_days_data({"2025-12-18": [_make_trauma_hp_item(text)]})
        result = extract_mechanism_region({"days": {}}, days_data)
        assert "abdomen" in result["body_region_labels"]

    def test_spine_from_hpi(self):
        text = _hp_text("CT of thoracolumbar spine shows compression fractures.")
        days_data = _make_days_data({"2025-12-18": [_make_trauma_hp_item(text)]})
        result = extract_mechanism_region({"days": {}}, days_data)
        assert "spine" in result["body_region_labels"]

    def test_neck_cervical(self):
        text = _hp_text(
            "Patient has neck pain.",
            "Neck: C-collar in place. Cervical spine tender.",
        )
        days_data = _make_days_data({"2025-12-18": [_make_trauma_hp_item(text)]})
        result = extract_mechanism_region({"days": {}}, days_data)
        assert "neck" in result["body_region_labels"]

    def test_extremity_from_hpi(self):
        text = _hp_text(
            "Patient was found to have a left upper extremity that was pulseless.",
        )
        days_data = _make_days_data({"2025-12-18": [_make_trauma_hp_item(text)]})
        result = extract_mechanism_region({"days": {}}, days_data)
        assert "extremity" in result["body_region_labels"]

    def test_rib_mapping_to_chest(self):
        text = _hp_text(
            "CT imaging reveals right-sided fractures of 1st, 3rd, 4th ribs.",
        )
        days_data = _make_days_data({"2025-12-18": [_make_trauma_hp_item(text)]})
        result = extract_mechanism_region({"days": {}}, days_data)
        assert "chest" in result["body_region_labels"]

    def test_face_region(self):
        text = _hp_text(
            "Patient has facial lacerations.",
            "HEENT: facial abrasions, mandible stable",
        )
        days_data = _make_days_data({"2025-12-18": [_make_trauma_hp_item(text)]})
        result = extract_mechanism_region({"days": {}}, days_data)
        assert "face" in result["body_region_labels"]


# ═══════════════════════════════════════════════════════════════════
# § Source priority and fail-closed
# ═══════════════════════════════════════════════════════════════════

class TestSourcePriority:
    """TRAUMA_HP > ED_NOTE > PHYSICIAN_NOTE source precedence."""

    def test_trauma_hp_wins_over_ed_note(self):
        hp_text = _hp_text("Patient presents after a fall at home.")
        ed_text = "[ED_NOTE]\nHPI: Patient was in an MVC.\nPrimary Survey:\n"
        days_data = _make_days_data({"2025-12-18": [
            _make_trauma_hp_item(hp_text),
            _make_ed_note_item(ed_text),
        ]})
        result = extract_mechanism_region({"days": {}}, days_data)
        assert result["mechanism_primary"] == "fall"
        assert result["source_rule_id"] == "trauma_hp_hpi"

    def test_ed_note_fallback(self):
        ed_text = "[ED_NOTE]\nHPI: Patient was in an MVC.\nPrimary Survey:\n"
        days_data = _make_days_data({"2025-12-18": [
            _make_ed_note_item(ed_text),
        ]})
        result = extract_mechanism_region({"days": {}}, days_data)
        assert result["mechanism_present"] == "yes"
        assert result["mechanism_primary"] == "mvc"
        assert result["source_rule_id"] == "ed_note_hpi"


class TestFailClosed:
    """Fail-closed behavior."""

    def test_no_items_at_all(self):
        days_data = _make_days_data({"2025-12-18": []})
        result = extract_mechanism_region({"days": {}}, days_data)
        assert result["mechanism_present"] == "DATA NOT AVAILABLE"
        assert result["body_region_present"] == "DATA NOT AVAILABLE"
        assert result["mechanism_primary"] is None
        assert result["mechanism_labels"] == []

    def test_only_radiology_items(self):
        rad_item = {
            "type": "RADIOLOGY",
            "dt": "2025-12-18",
            "source_id": "1",
            "payload": {"text": "CT chest shows rib fractures from fall injury"},
        }
        days_data = _make_days_data({"2025-12-18": [rad_item]})
        result = extract_mechanism_region({"days": {}}, days_data)
        assert result["mechanism_present"] == "DATA NOT AVAILABLE"

    def test_trauma_hp_no_mechanism_match(self):
        text = _hp_text("Patient presents for evaluation.")
        days_data = _make_days_data({"2025-12-18": [_make_trauma_hp_item(text)]})
        result = extract_mechanism_region({"days": {}}, days_data)
        assert result["mechanism_present"] == "no"
        assert result["mechanism_primary"] is None
        assert result["mechanism_labels"] == []

    def test_no_hpi_section(self):
        text = "[TRAUMA_HP] 2025-12-18\nSigned\nTrauma H & P\nPrimary Survey:\nAirway: patent\n"
        days_data = _make_days_data({"2025-12-18": [_make_trauma_hp_item(text)]})
        result = extract_mechanism_region({"days": {}}, days_data)
        # No HPI section found — should result in "no" (source exists but no match)
        assert result["mechanism_present"] in ("no", "DATA NOT AVAILABLE")


# ═══════════════════════════════════════════════════════════════════
# § History context exclusion
# ═══════════════════════════════════════════════════════════════════

class TestHistoryExclusion:
    """History/chronic context suppression."""

    def test_history_of_fall_excluded(self):
        text = _hp_text("70 yo male with PMH of previous SDH from fall presents with chest pain.")
        days_data = _make_days_data({"2025-12-18": [_make_trauma_hp_item(text)]})
        result = extract_mechanism_region({"days": {}}, days_data)
        # The "fall" should be excluded because it's in history context
        assert "fall" not in result["mechanism_labels"]

    def test_acute_fall_not_excluded(self):
        text = _hp_text("Patient presents after a fall today from a ladder.")
        days_data = _make_days_data({"2025-12-18": [_make_trauma_hp_item(text)]})
        result = extract_mechanism_region({"days": {}}, days_data)
        assert "fall" in result["mechanism_labels"]


# ═══════════════════════════════════════════════════════════════════
# § Evidence traceability
# ═══════════════════════════════════════════════════════════════════

class TestEvidence:
    """Evidence entries have required fields."""

    def test_all_evidence_has_raw_line_id(self):
        text = _hp_text(
            "Patient presents after a fall with head injury.",
            "HEENT: forehead laceration\nChest wall: tenderness",
        )
        days_data = _make_days_data({"2025-12-18": [_make_trauma_hp_item(text)]})
        result = extract_mechanism_region({"days": {}}, days_data)
        for ev in result["evidence"]:
            assert "raw_line_id" in ev, f"Evidence entry missing raw_line_id: {ev}"
            assert isinstance(ev["raw_line_id"], str)
            assert len(ev["raw_line_id"]) > 0

    def test_evidence_has_source_and_role(self):
        text = _hp_text("Patient presents after a fall.")
        days_data = _make_days_data({"2025-12-18": [_make_trauma_hp_item(text)]})
        result = extract_mechanism_region({"days": {}}, days_data)
        for ev in result["evidence"]:
            assert "source" in ev
            assert "role" in ev
            assert ev["role"] in ("mechanism", "body_region")

    def test_mechanism_evidence_has_label(self):
        text = _hp_text("Patient presents after a fall at home.")
        days_data = _make_days_data({"2025-12-18": [_make_trauma_hp_item(text)]})
        result = extract_mechanism_region({"days": {}}, days_data)
        mech_evidence = [e for e in result["evidence"] if e["role"] == "mechanism"]
        assert len(mech_evidence) > 0
        for ev in mech_evidence:
            assert "label" in ev
            assert ev["label"] == "fall"


# ═══════════════════════════════════════════════════════════════════
# § Multiple mechanisms
# ═══════════════════════════════════════════════════════════════════

class TestMultipleMechanisms:
    """Multiple mechanism labels in a single HPI."""

    def test_grain_bin_auger_yields_multiple(self):
        text = _hp_text(
            "Patient was working in a grain bin today and got caught in the auger. "
            "His leg got trapped between 2 objects."
        )
        days_data = _make_days_data({"2025-12-18": [_make_trauma_hp_item(text)]})
        result = extract_mechanism_region({"days": {}}, days_data)
        assert result["mechanism_present"] == "yes"
        # Should capture multiple mechanism labels
        assert len(result["mechanism_labels"]) >= 2
        # First match is primary
        assert result["mechanism_primary"] == result["mechanism_labels"][0]


# ═══════════════════════════════════════════════════════════════════
# § Output schema completeness
# ═══════════════════════════════════════════════════════════════════

class TestOutputSchema:
    """Output schema has all required keys."""

    _REQUIRED_KEYS = {
        "mechanism_present",
        "mechanism_primary",
        "mechanism_labels",
        "penetrating_mechanism",
        "body_region_present",
        "body_region_labels",
        "source_rule_id",
        "evidence",
        "notes",
        "warnings",
    }

    def test_schema_with_matches(self):
        text = _hp_text("Patient presents after a fall with head injury.")
        days_data = _make_days_data({"2025-12-18": [_make_trauma_hp_item(text)]})
        result = extract_mechanism_region({"days": {}}, days_data)
        assert self._REQUIRED_KEYS <= set(result.keys())

    def test_schema_dna(self):
        days_data = _make_days_data({"2025-12-18": []})
        result = extract_mechanism_region({"days": {}}, days_data)
        assert self._REQUIRED_KEYS <= set(result.keys())

    def test_body_region_labels_sorted(self):
        text = _hp_text(
            "Patient presents after a fall with head and chest pain.",
            "Pelvis: stable\nExtremities: no deformity\nAbdomen: soft",
        )
        days_data = _make_days_data({"2025-12-18": [_make_trauma_hp_item(text)]})
        result = extract_mechanism_region({"days": {}}, days_data)
        labels = result["body_region_labels"]
        assert labels == sorted(labels), "body_region_labels should be sorted"


# ═══════════════════════════════════════════════════════════════════
# § Real patient HPI patterns (from data_raw samples)
# ═══════════════════════════════════════════════════════════════════

class TestRealPatientPatterns:
    """Test against patterns observed in actual patient data."""

    def test_timothy_cowan_auger(self):
        """Timothy Cowan: grain bin / auger industrial accident."""
        text = _hp_text(
            "60 yo male with unknown PMH who presents as a trauma transfer. "
            "It was reported that the patient was working in a grain bin today "
            "and got caught in the auger.",
            "Extremities: left upper extremity pulseless, dusky and cold.",
        )
        days_data = _make_days_data({"2025-12-18": [_make_trauma_hp_item(text)]})
        result = extract_mechanism_region({"days": {}}, days_data)
        assert result["mechanism_present"] == "yes"
        assert "industrial" in result["mechanism_labels"]
        assert "extremity" in result["body_region_labels"]

    def test_barbara_burgdorf_fall(self):
        """Barbara Burgdorf: fall from counter with rib fractures."""
        text = _hp_text(
            "78 yo female presents to Midtown ED after a fall. "
            "Patient was standing up on counter and was stepping down and fell "
            "striking on her right side. CT imaging shows right-sided rib fractures.",
            "Chest wall: Right-sided chest wall tenderness.",
        )
        days_data = _make_days_data({"2025-12-17": [_make_trauma_hp_item(text)]})
        result = extract_mechanism_region({"days": {}}, days_data)
        assert result["mechanism_present"] == "yes"
        assert "fall" in result["mechanism_labels"]
        assert "chest" in result["body_region_labels"]

    def test_david_gross_mvc(self):
        """David Gross: MVC with unknown medical event."""
        text = _hp_text(
            "47-year-old male following MVC in which patient had an unknown "
            "medical event.",
            "General: Critically ill male.\nHEENT: L forehead abrasion.",
        )
        days_data = _make_days_data({"2025-12-17": [_make_trauma_hp_item(text)]})
        result = extract_mechanism_region({"days": {}}, days_data)
        assert result["mechanism_present"] == "yes"
        assert "mvc" in result["mechanism_labels"]
        assert result["penetrating_mechanism"] is False
        assert "head" in result["body_region_labels"]

    def test_susan_barker_mvc_unrestrained(self):
        """Susan Barker: unrestrained driver in MVC."""
        text = _hp_text(
            "40 yo female. She reports she was the unrestrained driver involved "
            "in a MVC. She does not recall the events.",
        )
        days_data = _make_days_data({"2025-12-18": [_make_trauma_hp_item(text)]})
        result = extract_mechanism_region({"days": {}}, days_data)
        assert result["mechanism_present"] == "yes"
        assert "mvc" in result["mechanism_labels"]

    def test_cody_givens_mining(self):
        """Cody Givens: coal mining accident with leg trapped."""
        text = _hp_text(
            "36 yo male who was involved in a coal mining accident. The patient "
            "reports that his leg got trapped between 2 objects for about a minute.",
            "Extremities: Distal medial RLE with 5cm open wound.",
        )
        days_data = _make_days_data({"2025-12-11": [_make_trauma_hp_item(text)]})
        result = extract_mechanism_region({"days": {}}, days_data)
        assert result["mechanism_present"] == "yes"
        assert any(l in result["mechanism_labels"] for l in ["industrial", "crush"])
        assert "extremity" in result["body_region_labels"]

    def test_carlton_van_ness_gait_fall(self):
        """Carlton Van Ness: ground level fall due to tripping."""
        text = _hp_text(
            "70 yo male presents via ED transfer from OSH s/p ground level fall. "
            "Patient states he fell at home due to tripping.",
        )
        days_data = _make_days_data({"2025-12-18": [_make_trauma_hp_item(text)]})
        result = extract_mechanism_region({"days": {}}, days_data)
        assert result["mechanism_present"] == "yes"
        assert "fall" in result["mechanism_labels"]

    def test_wilma_yates_mvc(self):
        """Wilma Yates: MVC while running errands."""
        text = _hp_text(
            "89 yo female who reportedly had an MVC yesterday, she was running errands.",
        )
        days_data = _make_days_data({"2025-12-18": [_make_trauma_hp_item(text)]})
        result = extract_mechanism_region({"days": {}}, days_data)
        assert result["mechanism_present"] == "yes"
        assert "mvc" in result["mechanism_labels"]


# ═══════════════════════════════════════════════════════════════════
# § Internal helpers
# ═══════════════════════════════════════════════════════════════════

class TestHelpers:
    """Unit tests for internal helper functions."""

    def test_extract_section_hpi(self):
        text = "Before\nHPI: Some text here.\nMore HPI.\nPrimary Survey:\nAfter"
        result = _extract_section(text, RE_HPI_START, RE_HPI_END)
        assert result is not None
        assert "Some text here" in result
        assert "After" not in result

    def test_extract_section_missing(self):
        text = "No HPI here at all."
        result = _extract_section(text, RE_HPI_START, RE_HPI_END)
        assert result is None

    def test_make_raw_line_id_deterministic(self):
        id1 = _make_raw_line_id("TRAUMA_HP", "0", "some text")
        id2 = _make_raw_line_id("TRAUMA_HP", "0", "some text")
        assert id1 == id2
        assert len(id1) == 16

    def test_make_raw_line_id_varies_by_input(self):
        id1 = _make_raw_line_id("TRAUMA_HP", "0", "text a")
        id2 = _make_raw_line_id("TRAUMA_HP", "0", "text b")
        assert id1 != id2
