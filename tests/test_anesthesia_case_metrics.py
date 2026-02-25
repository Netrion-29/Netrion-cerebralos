#!/usr/bin/env python3
"""
Tests for anesthesia_case_metrics_v1 extractor.

Covers:
  1. Empty input → fail-closed (no cases, null hypothermia)
  2. No anesthesia items → fail-closed
  3. Full surgical case (PREPROCEDURE + PROCEDURE + POSTPROCEDURE + FOLLOWUP)
  4. Nerve block case (CONSULT + PROCEDURE)
  5. Airway extraction (LMA with all fields)
  6. Temperature extraction + hypothermia flagging
  7. EBL extraction from OP_NOTE
  8. Determinism (same input → same output)
  9. Multiple cases on different days
"""

import copy
import json

from cerebralos.features.anesthesia_case_metrics_v1 import (
    extract_anesthesia_case_metrics,
    OR_HYPOTHERMIA_THRESHOLD_F,
    _parse_ebl,
    _extract_airway,
    _extract_temps,
    _normalise_text,
)


# ── Test Data ──────────────────────────────────────────────────────

_EMPTY_DAYS = {"meta": {}, "days": []}

_NO_ANESTHESIA_DAYS = {
    "meta": {},
    "days": [
        {
            "date": "2026-01-05",
            "items": [
                {
                    "type": "PROGRESS_NOTE",
                    "text": "Patient stable.",
                    "dt": "2026-01-05T08:00:00",
                    "raw_line_id": "pn_001",
                },
            ],
        }
    ],
}

_FULL_CASE_DAYS = {
    "meta": {"patient_id": "Michael_Dougan"},
    "days": [
        {
            "date": "2026-01-10",
            "items": [
                {
                    "type": "ANESTHESIA_PREPROCEDURE",
                    "text": (
                        "ASA Status: 3\n"
                        "Mallampati: II\n"
                        "Anesthesia Plan: General\n"
                        "Diagnosis: Metatarsal fracture\n"
                        "Vitals:\n"
                        "Temp: 98.2 °F (36.8 °C)\n"
                        "BP: 120/80\n"
                    ),
                    "dt": "2026-01-10T07:30:00",
                    "raw_line_id": "anes_pre_001",
                },
                {
                    "type": "ANESTHESIA_PROCEDURE",
                    "text": (
                        "Type of Airway: LMA\n"
                        "Airway Device: LMA\n"
                        "ETT/LMA Size: 5\n"
                        "Difficult Airway?: airway not difficult\n"
                        "Airway Difficulty: Easy\n"
                        "Atraumatic: Yes\n"
                        "Insertion Attempts: 1\n"
                        "Placement verified by: Auscultation and Capnometry\n"
                    ),
                    "dt": "2026-01-10T08:00:00",
                    "raw_line_id": "anes_proc_001",
                },
                {
                    "type": "ANESTHESIA_POSTPROCEDURE",
                    "text": (
                        "Anesthesia Type: General\n"
                        "Airway: Nasal Cannula\n"
                        "Patient Condition: Stable\n"
                        "Temp: 98.4\n"
                    ),
                    "dt": "2026-01-10T10:00:00",
                    "raw_line_id": "anes_post_001",
                },
                {
                    "type": "ANESTHESIA_FOLLOWUP",
                    "text": (
                        "Location: PACU\n"
                        "Airway: Room Air\n"
                        "Level of Consciousness: Awake\n"
                        "Pain: Adequate analgesia\n"
                        "Nausea: None\n"
                        "Assessment: No apparent anesthetic complications\n"
                        "Temp: 98.6 °F (37 °C)\n"
                    ),
                    "dt": "2026-01-10T11:00:00",
                    "raw_line_id": "anes_fu_001",
                },
            ],
        }
    ],
}

_NERVE_BLOCK_DAYS = {
    "meta": {"patient_id": "Ronald_Bittner"},
    "days": [
        {
            "date": "2026-01-02",
            "items": [
                {
                    "type": "ANESTHESIA_CONSULT",
                    "text": (
                        "Consult for pain management.\n"
                        "Block type: Erector Spinae (ES)\n"
                        "Diagnosis: Rib fractures\n"
                    ),
                    "dt": "2026-01-02T09:00:00",
                    "raw_line_id": "anes_consult_001",
                },
                {
                    "type": "ANESTHESIA_PROCEDURE",
                    "text": (
                        "Peripheral nerve block performed.\n"
                        "Block type: Erector Spinae (ES)\n"
                        "Ultrasound-guided.\n"
                        "Ropivacaine 0.5% 20 mL.\n"
                    ),
                    "dt": "2026-01-02T10:00:00",
                    "raw_line_id": "anes_proc_nb_001",
                },
            ],
        }
    ],
}

_HYPOTHERMIA_DAYS = {
    "meta": {"patient_id": "Test_Hypothermia"},
    "days": [
        {
            "date": "2026-01-15",
            "items": [
                {
                    "type": "ANESTHESIA_PREPROCEDURE",
                    "text": "ASA Status: 2\nAnesthesia Plan: General\nTemp: 98.6\n",
                    "dt": "2026-01-15T07:00:00",
                    "raw_line_id": "hypo_pre",
                },
                {
                    "type": "ANESTHESIA_POSTPROCEDURE",
                    "text": "Anesthesia Type: General\nTemp: 96.2\n",
                    "dt": "2026-01-15T10:00:00",
                    "raw_line_id": "hypo_post",
                },
            ],
        }
    ],
}

_EBL_DAYS = {
    "meta": {"patient_id": "Test_EBL"},
    "days": [
        {
            "date": "2026-01-15",
            "items": [
                {
                    "type": "ANESTHESIA_PREPROCEDURE",
                    "text": "ASA Status: 3\nAnesthesia Plan: General\n",
                    "dt": "2026-01-15T07:00:00",
                    "raw_line_id": "ebl_pre",
                },
                {
                    "type": "ANESTHESIA_POSTPROCEDURE",
                    "text": "Anesthesia Type: General\nTemp: 98.0\n",
                    "dt": "2026-01-15T10:00:00",
                    "raw_line_id": "ebl_post",
                },
                {
                    "type": "OP_NOTE",
                    "text": (
                        "Procedure: Percutaneous tracheostomy\n"
                        "EBL: <5cc\n"
                        "Complications: None\n"
                    ),
                    "dt": "2026-01-15T12:00:00",
                    "raw_line_id": "ebl_opnote",
                },
            ],
        }
    ],
}

_MULTI_DAY_DAYS = {
    "meta": {"patient_id": "Test_MultiDay"},
    "days": [
        {
            "date": "2026-01-10",
            "items": [
                {
                    "type": "ANESTHESIA_PREPROCEDURE",
                    "text": "ASA Status: 2\nAnesthesia Plan: Spinal\n",
                    "dt": "2026-01-10T07:00:00",
                    "raw_line_id": "md_d1_pre",
                },
            ],
        },
        {
            "date": "2026-01-12",
            "items": [
                {
                    "type": "ANESTHESIA_PREPROCEDURE",
                    "text": "ASA Status: 3\nAnesthesia Plan: General\n",
                    "dt": "2026-01-12T08:00:00",
                    "raw_line_id": "md_d2_pre",
                },
            ],
        },
    ],
}


# ── Tests ──────────────────────────────────────────────────────────


def test_empty_input_fail_closed():
    """Empty days → no cases, null hypothermia."""
    result = extract_anesthesia_case_metrics({}, _EMPTY_DAYS)
    assert result["case_count"] == 0
    assert result["cases"] == []
    assert result["or_hypothermia_any"] is None
    assert "no_anesthesia_items_found" in result["notes"]
    assert result["source_rule_id"] == "anesthesia_case_metrics_v1"


def test_no_anesthesia_items_fail_closed():
    """Days with only PROGRESS_NOTE → no cases."""
    result = extract_anesthesia_case_metrics({}, _NO_ANESTHESIA_DAYS)
    assert result["case_count"] == 0
    assert "no_anesthesia_items_found" in result["notes"]


def test_full_surgical_case():
    """Full case with all 4 anesthesia phases → complete extraction."""
    result = extract_anesthesia_case_metrics({}, _FULL_CASE_DAYS)
    assert result["case_count"] == 1
    case = result["cases"][0]
    assert case["case_index"] == 1
    assert case["case_day"] == "2026-01-10"
    assert case["asa_status"] == "3"
    assert case["mallampati"] == "II"
    assert case["anesthesia_type"] == "General"
    assert case["preop_diagnosis"] == "Metatarsal fracture"

    # Airway
    aw = case.get("airway", {})
    assert aw["device"] == "LMA"
    assert aw["size"] == "5"
    assert aw["difficulty"] is not None  # "Easy" or "airway not difficult"
    assert aw["atraumatic"] == "Yes"
    assert aw["attempts"] == "1"
    assert aw["placement_verification"] == "Auscultation and Capnometry"

    # Temps
    assert case["min_temp_f"] is not None
    assert case["or_hypothermia_flag"] is False  # 98.4 > 96.8
    assert result["or_hypothermia_any"] is False

    # Evidence
    assert len(case["evidence"]) >= 4  # one per item
    for ev in case["evidence"]:
        assert "raw_line_id" in ev


def test_nerve_block_case():
    """Nerve block (CONSULT + PROCEDURE) → case with block_type label."""
    result = extract_anesthesia_case_metrics({}, _NERVE_BLOCK_DAYS)
    assert result["case_count"] == 1
    case = result["cases"][0]
    assert "Nerve Block" in case["case_label"]
    assert "Erector Spinae" in case["case_label"]
    # No temps → hypothermia flag null
    assert case["or_hypothermia_flag"] is None


def test_hypothermia_flag():
    """Post-op temp 96.2 < 96.8 → hypothermia flagged."""
    result = extract_anesthesia_case_metrics({}, _HYPOTHERMIA_DAYS)
    assert result["case_count"] == 1
    case = result["cases"][0]
    assert case["or_hypothermia_flag"] is True
    assert case["min_temp_f"] == 96.2
    assert result["or_hypothermia_any"] is True
    assert len(result["flags"]) >= 1
    assert "or_hypothermia" in result["flags"][0]


def test_ebl_from_op_note():
    """EBL from OP_NOTE cross-referenced by day → numeric extraction."""
    result = extract_anesthesia_case_metrics({}, _EBL_DAYS)
    assert result["case_count"] == 1
    case = result["cases"][0]
    assert case["ebl_ml"] == 5.0
    assert case["ebl_raw"] == "<5"  # raw preserves '<', numeric strips it


def test_multiple_cases_different_days():
    """Items on different days → separate cases."""
    result = extract_anesthesia_case_metrics({}, _MULTI_DAY_DAYS)
    assert result["case_count"] == 2
    days = [c["case_day"] for c in result["cases"]]
    assert "2026-01-10" in days
    assert "2026-01-12" in days


def test_determinism():
    """Same input produces identical output (no randomness)."""
    r1 = extract_anesthesia_case_metrics({}, _FULL_CASE_DAYS)
    r2 = extract_anesthesia_case_metrics({}, copy.deepcopy(_FULL_CASE_DAYS))
    assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)


def test_evidence_has_raw_line_id():
    """All evidence entries must have raw_line_id."""
    result = extract_anesthesia_case_metrics({}, _FULL_CASE_DAYS)
    for case in result["cases"]:
        for ev in case["evidence"]:
            assert "raw_line_id" in ev, f"Missing raw_line_id in evidence: {ev}"
    for ev in result["evidence"]:
        assert "raw_line_id" in ev


# ── Unit tests for helper functions ────────────────────────────────


def test_parse_ebl_numeric():
    assert _parse_ebl("EBL: <5cc") == (5.0, "<5")
    assert _parse_ebl("EBL: 20 ml") == (20.0, "20")
    assert _parse_ebl("Estimated Blood Loss: 100cc") == (100.0, "100")


def test_parse_ebl_minimal():
    ml, raw = _parse_ebl("EBL: Minimal")
    assert ml is None
    assert raw == "minimal"


def test_parse_ebl_none():
    ml, raw = _parse_ebl("No EBL mentioned here")
    assert ml is None
    assert raw is None


def test_extract_airway_full():
    text = _normalise_text(
        "Type of Airway: LMA\n"
        "ETT/LMA Size: 5\n"
        "Airway Difficulty: Easy\n"
        "Atraumatic: Yes\n"
        "Insertion Attempts: 1\n"
        "Placement verified by: Auscultation and Capnometry\n"
    )
    aw = _extract_airway(text)
    assert aw["device"] == "LMA"
    assert aw["size"] == "5"
    assert aw["atraumatic"] == "Yes"
    assert aw["attempts"] == "1"


def test_extract_temps():
    text = _normalise_text("Temp: 98.4\nBP: 120/80\nTemp: 97.2 °F (36.2 °C)\n")
    temps = _extract_temps(text, "postprocedure", "test_lid")
    assert len(temps) == 2
    values = sorted(t["value_f"] for t in temps)
    assert values == [97.2, 98.4]


def test_hypothermia_threshold_constant():
    """Threshold is exactly 96.8."""
    assert OR_HYPOTHERMIA_THRESHOLD_F == 96.8
