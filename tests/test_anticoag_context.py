#!/usr/bin/env python3
"""
Tests for Anticoagulation Context Extraction v1.

Covers:
  - Home anticoagulant detection (DOAC, VKA) from outpatient med section
  - Home antiplatelet detection (aspirin, clopidogrel, ticagrelor, prasugrel)
  - [DISCONTINUED] handling (captured but flagged, does NOT set present=yes)
  - Negative control (patient with no anticoag/antiplatelet meds)
  - Inpatient-only meds NOT captured as home meds
  - Evidence traceability (raw_line_id on every evidence + drug entry)
  - Deduplication across multiple timeline items
  - Section boundary detection
  - Fail-closed behavior when no outpatient section present
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cerebralos.features.anticoag_context_v1 import (
    extract_anticoag_context,
    _extract_med_name,
    _extract_dose,
    _extract_indication,
    _find_outpatient_med_sections,
    _DNA,
)


# ── Helper: build minimal days_data ─────────────────────────────────

def _make_days_data(
    items_by_day: dict | None = None,
    arrival_datetime: str | None = "2025-01-15T14:30:00",
) -> dict:
    """Build a minimal patient_days_v1 structure."""
    days = {}
    if items_by_day:
        for day_iso, items in items_by_day.items():
            days[day_iso] = {"items": items}
    return {
        "meta": {
            "arrival_datetime": arrival_datetime,
            "patient_id": "Test_Patient",
        },
        "days": days,
    }


def _make_item(text: str, item_type: str = "TRAUMA_HP",
               item_id: str = "item_001",
               dt: str = "2025-01-15T14:30:00") -> dict:
    """Build a minimal timeline item."""
    return {
        "type": item_type,
        "id": item_id,
        "dt": dt,
        "payload": {"text": text},
    }


def _pat_features() -> dict:
    return {"days": {}}


# ── Sample outpatient sections ─────────────────────────────────────

SECTION_ELIQUIS_ASPIRIN = """\
Some header text

Current Outpatient Medications on File Prior to Encounter
Medication\tSig\tDispense\tRefill
•\tapixaban (ELIQUIS) 5 MG tablet\tTake 1 tablet (5 mg) by mouth every 12 hours Indications: Atrial Fibrillation\t60 tablet\t2
•\taspirin EC (HALFPRIN) 81 MG tablet\tTake 1 tablet (81 mg) by mouth daily\t
•\tmetformin (GLUCOPHAGE) 500 MG tablet\tTake 1 tablet (500 mg) by mouth twice daily\t

Allergies
No known allergies
"""

SECTION_WARFARIN_ASPIRIN = """\
Current Outpatient Medications on File Prior to Encounter
Medication\tSig\tDispense\tRefill
•\twarfarin (COUMADIN) 5 MG tablet\tTake 1 tablet (5 mg) by mouth daily\t
•\taspirin (ASPIRIN LOW DOSE) 81 MG EC tablet\tTake 1 tablet (81 mg) by mouth daily\t
•\tlisinopril (PRINIVIL) 10 MG tablet\tTake 1 tablet (10 mg) by mouth daily\t

Social Hx
Non-smoker
"""

SECTION_DISCONTINUED_ELIQUIS = """\
Current Outpatient Medications on File Prior to Encounter
Medication\tSig\tDispense\tRefill
•\t[DISCONTINUED] apixaban (ELIQUIS) 5 MG tablet\tTake 1 tablet by mouth every 12 hours\t
•\tmetformin (GLUCOPHAGE) 500 MG tablet\tTake 1 tablet twice daily\t

Allergies
NKDA
"""

SECTION_CLOPIDOGREL_ONLY = """\
Current Outpatient Medications on File Prior to Encounter
Medication\tSig\tDispense\tRefill
•\tclopidogrel (PLAVIX) 75 MG tablet\tTake 1 tablet (75 mg) by mouth daily\t
•\tatorvastatin (LIPITOR) 40 MG tablet\tTake 1 tablet daily\t

ROS:
Negative
"""

SECTION_NO_ANTICOAG = """\
Current Outpatient Medications on File Prior to Encounter
Medication\tSig\tDispense\tRefill
•\tmetformin (GLUCOPHAGE) 500 MG tablet\tTake 1 tablet twice daily\t
•\tlisinopril (PRINIVIL) 10 MG tablet\tTake 1 tablet daily\t
•\tatorvastatin (LIPITOR) 40 MG tablet\tTake 1 tablet daily\t

Allergies
NKDA
"""

TEXT_NO_OUTPATIENT_SECTION = """\
TRAUMA HISTORY AND PHYSICAL

Chief Complaint: Fall from standing height
HPI: 78 year old male presents after fall.
Physical Exam:
General: Alert, oriented
"""

TEXT_INPATIENT_ONLY_MEDS = """\
Medications Ordered During This Visit:
enoxaparin (LOVENOX) 40 MG subcutaneous injection daily

Assessment and Plan:
DVT prophylaxis initiated.
"""


# ── Tests: helper functions ─────────────────────────────────────────

class TestHelpers:
    def test_extract_med_name_basic(self):
        line = "•\tapixaban (ELIQUIS) 5 MG tablet\tTake 1 tablet (5 mg)"
        result = _extract_med_name(line)
        assert "apixaban" in result
        assert "ELIQUIS" in result

    def test_extract_med_name_discontinued(self):
        line = "•\t[DISCONTINUED] apixaban (ELIQUIS) 5 MG tablet\tTake 1"
        result = _extract_med_name(line)
        assert "apixaban" in result
        assert "[DISCONTINUED]" not in result

    def test_extract_dose_mg(self):
        assert _extract_dose("apixaban (ELIQUIS) 5 MG tablet") == "5 MG tablet"

    def test_extract_dose_81_mg(self):
        dose = _extract_dose("aspirin EC (HALFPRIN) 81 MG tablet")
        assert dose is not None
        assert "81" in dose

    def test_extract_dose_none(self):
        assert _extract_dose("some random text") is None

    def test_extract_indication_present(self):
        line = "Take 1 tablet by mouth every 12 hours Indications: Atrial Fibrillation\t60 tablet"
        result = _extract_indication(line)
        assert result == "Atrial Fibrillation"

    def test_extract_indication_absent(self):
        assert _extract_indication("Take 1 tablet by mouth daily") is None

    def test_find_outpatient_sections_found(self):
        sections = _find_outpatient_med_sections(SECTION_ELIQUIS_ASPIRIN)
        assert len(sections) >= 1

    def test_find_outpatient_sections_not_found(self):
        sections = _find_outpatient_med_sections(TEXT_NO_OUTPATIENT_SECTION)
        assert len(sections) == 0


# ── Tests: full extractor ──────────────────────────────────────────

class TestExtractAnticoagContext:
    """Tests for extract_anticoag_context()."""

    def test_eliquis_and_aspirin(self):
        """Apixaban (DOAC) + aspirin detected from outpatient section."""
        days_data = _make_days_data({
            "2025-01-15": [_make_item(SECTION_ELIQUIS_ASPIRIN)],
        })
        result = extract_anticoag_context(_pat_features(), days_data)

        assert result["anticoag_present"] == "yes"
        assert result["antiplatelet_present"] == "yes"
        assert result["anticoag_count"] == 1
        assert result["antiplatelet_count"] == 1
        assert result["source_rule_id"] == "anticoag_context_v1"

        # Check anticoagulant details
        ac_list = result["home_anticoagulants"]
        assert len(ac_list) == 1
        ac = ac_list[0]
        assert ac["normalized_name"] == "apixaban"
        assert ac["class"] == "DOAC"
        assert ac["context"] == "home_outpatient"
        assert ac["discontinued"] is False
        assert "raw_line_id" in ac
        assert ac.get("indication") == "Atrial Fibrillation"

        # Check antiplatelet details
        ap_list = result["home_antiplatelets"]
        assert len(ap_list) == 1
        ap = ap_list[0]
        assert ap["normalized_name"] == "aspirin"
        assert ap["class"] == "antiplatelet"
        assert ap["discontinued"] is False
        assert "raw_line_id" in ap

    def test_warfarin_and_aspirin(self):
        """Warfarin (VKA) + aspirin detected."""
        days_data = _make_days_data({
            "2025-01-15": [_make_item(SECTION_WARFARIN_ASPIRIN)],
        })
        result = extract_anticoag_context(_pat_features(), days_data)

        assert result["anticoag_present"] == "yes"
        assert result["antiplatelet_present"] == "yes"

        ac = result["home_anticoagulants"]
        assert len(ac) == 1
        assert ac[0]["normalized_name"] == "warfarin"
        assert ac[0]["class"] == "VKA"

        ap = result["home_antiplatelets"]
        assert len(ap) == 1
        assert ap[0]["normalized_name"] == "aspirin"

    def test_discontinued_anticoag(self):
        """[DISCONTINUED] apixaban captured but anticoag_present = no."""
        days_data = _make_days_data({
            "2025-01-15": [_make_item(SECTION_DISCONTINUED_ELIQUIS)],
        })
        result = extract_anticoag_context(_pat_features(), days_data)

        assert result["anticoag_present"] == "no"
        assert result["anticoag_count"] == 1

        ac = result["home_anticoagulants"]
        assert len(ac) == 1
        assert ac[0]["normalized_name"] == "apixaban"
        assert ac[0]["discontinued"] is True

    def test_antiplatelet_only_clopidogrel(self):
        """Clopidogrel only — no anticoag."""
        days_data = _make_days_data({
            "2025-01-15": [_make_item(SECTION_CLOPIDOGREL_ONLY)],
        })
        result = extract_anticoag_context(_pat_features(), days_data)

        assert result["anticoag_present"] == _DNA
        assert result["antiplatelet_present"] == "yes"
        assert result["anticoag_count"] == 0
        assert result["antiplatelet_count"] == 1

        ap = result["home_antiplatelets"]
        assert len(ap) == 1
        assert ap[0]["normalized_name"] == "clopidogrel"

    def test_negative_control_no_anticoag_meds(self):
        """No anticoag/antiplatelet in outpatient section."""
        days_data = _make_days_data({
            "2025-01-15": [_make_item(SECTION_NO_ANTICOAG)],
        })
        result = extract_anticoag_context(_pat_features(), days_data)

        assert result["anticoag_present"] == _DNA
        assert result["antiplatelet_present"] == _DNA
        assert result["anticoag_count"] == 0
        assert result["antiplatelet_count"] == 0
        assert result["home_anticoagulants"] == []
        assert result["home_antiplatelets"] == []

    def test_no_outpatient_section(self):
        """No outpatient medication section at all — DNA."""
        days_data = _make_days_data({
            "2025-01-15": [_make_item(TEXT_NO_OUTPATIENT_SECTION)],
        })
        result = extract_anticoag_context(_pat_features(), days_data)

        assert result["anticoag_present"] == _DNA
        assert result["antiplatelet_present"] == _DNA
        assert result["evidence"] == []

    def test_inpatient_only_meds_not_captured(self):
        """Inpatient enoxaparin NOT in outpatient section — not captured."""
        days_data = _make_days_data({
            "2025-01-15": [_make_item(TEXT_INPATIENT_ONLY_MEDS)],
        })
        result = extract_anticoag_context(_pat_features(), days_data)

        assert result["anticoag_present"] == _DNA
        assert result["home_anticoagulants"] == []

    def test_non_target_source_type_ignored(self):
        """Items with non-target source types are skipped."""
        days_data = _make_days_data({
            "2025-01-15": [_make_item(
                SECTION_ELIQUIS_ASPIRIN,
                item_type="RADIOLOGY_REPORT",
            )],
        })
        result = extract_anticoag_context(_pat_features(), days_data)

        assert result["anticoag_present"] == _DNA
        assert result["antiplatelet_present"] == _DNA

    def test_empty_days_data(self):
        """No days → DNA."""
        result = extract_anticoag_context(_pat_features(), {"days": {}})

        assert result["anticoag_present"] == _DNA
        assert result["antiplatelet_present"] == _DNA
        assert "no_days_data" in result["notes"]


class TestEvidenceTraceability:
    """Every evidence and drug entry must have raw_line_id."""

    def test_evidence_has_raw_line_id(self):
        days_data = _make_days_data({
            "2025-01-15": [_make_item(SECTION_ELIQUIS_ASPIRIN)],
        })
        result = extract_anticoag_context(_pat_features(), days_data)

        for ev in result["evidence"]:
            assert "raw_line_id" in ev, f"Evidence missing raw_line_id: {ev}"
            assert len(ev["raw_line_id"]) == 16

    def test_drug_entries_have_raw_line_id(self):
        days_data = _make_days_data({
            "2025-01-15": [_make_item(SECTION_ELIQUIS_ASPIRIN)],
        })
        result = extract_anticoag_context(_pat_features(), days_data)

        for ac in result["home_anticoagulants"]:
            assert "raw_line_id" in ac, f"Anticoag missing raw_line_id: {ac}"
        for ap in result["home_antiplatelets"]:
            assert "raw_line_id" in ap, f"Antiplatelet missing raw_line_id: {ap}"

    def test_evidence_has_snippet(self):
        days_data = _make_days_data({
            "2025-01-15": [_make_item(SECTION_ELIQUIS_ASPIRIN)],
        })
        result = extract_anticoag_context(_pat_features(), days_data)

        for ev in result["evidence"]:
            assert "snippet" in ev
            assert len(ev["snippet"]) > 0


class TestDeduplication:
    """Duplicate medication entries across items should be deduplicated."""

    def test_same_drug_in_two_items(self):
        """Same drug in two TRAUMA_HP items → only one entry."""
        days_data = _make_days_data({
            "2025-01-15": [
                _make_item(SECTION_ELIQUIS_ASPIRIN, item_id="item_001"),
                _make_item(SECTION_ELIQUIS_ASPIRIN, item_id="item_002"),
            ],
        })
        result = extract_anticoag_context(_pat_features(), days_data)

        assert result["anticoag_count"] == 1
        assert result["antiplatelet_count"] == 1

    def test_same_drug_across_days(self):
        """Same drug appearing on different days → deduplicated."""
        days_data = _make_days_data({
            "2025-01-15": [_make_item(SECTION_ELIQUIS_ASPIRIN, item_id="a")],
            "2025-01-16": [_make_item(SECTION_ELIQUIS_ASPIRIN, item_id="b")],
        })
        result = extract_anticoag_context(_pat_features(), days_data)

        assert result["anticoag_count"] == 1
        assert result["antiplatelet_count"] == 1


class TestOutputShape:
    """Verify the output dict has all required keys."""

    def test_required_keys_present(self):
        days_data = _make_days_data({
            "2025-01-15": [_make_item(SECTION_ELIQUIS_ASPIRIN)],
        })
        result = extract_anticoag_context(_pat_features(), days_data)

        required = {
            "anticoag_present", "antiplatelet_present",
            "home_anticoagulants", "home_antiplatelets",
            "anticoag_count", "antiplatelet_count",
            "source_rule_id", "evidence", "notes", "warnings",
        }
        assert required.issubset(set(result.keys()))

    def test_source_rule_id(self):
        result = extract_anticoag_context(_pat_features(), {"days": {}})
        assert result["source_rule_id"] == "anticoag_context_v1"
