#!/usr/bin/env python3
"""
Tests for procedure_operatives_v1 feature extractor.

Validates deterministic, fail-closed extraction of procedure/operative
events from timeline items.
"""

import pytest

from cerebralos.features.procedure_operatives_v1 import (
    extract_procedure_operatives,
    _extract_cpt_codes,
    _extract_label,
    _extract_milestones,
    _extract_preop_dx,
    _extract_status,
    _extract_anesthesia_details,
    _KIND_CATEGORY,
    _PROC_KINDS,
)


# ── Helpers ────────────────────────────────────────────────────────

def _make_days_data(items_by_day):
    """
    Build a minimal patient_days_v1 dict.

    items_by_day: dict mapping day_iso → list of item dicts.
    Each item has at minimum: type, dt, payload.text
    """
    days = {}
    for day_iso, items in items_by_day.items():
        day_items = []
        for item in items:
            day_items.append({
                "type": item.get("type", "NOTE"),
                "dt": item.get("dt"),
                "payload": {"text": item.get("text", "")},
                "raw_line_id": item.get("raw_line_id"),
            })
        days[day_iso] = {"items": day_items}
    return {"meta": {}, "days": days}


def _empty_features():
    return {"days": {}}


# ── Tests: empty / fail-closed ─────────────────────────────────────

class TestEmptyFailClosed:

    def test_empty_days(self):
        result = extract_procedure_operatives(
            _empty_features(),
            {"meta": {}, "days": {}},
        )
        assert result["events"] == []
        assert result["procedure_event_count"] == 0
        assert result["operative_event_count"] == 0
        assert result["anesthesia_event_count"] == 0
        assert result["categories_present"] == []
        assert "no_procedure_operative_events_found" in result["notes"]
        assert result["source_rule_id"] == "procedure_operatives_v1"

    def test_no_procedure_items(self):
        days_data = _make_days_data({
            "2026-01-01": [
                {"type": "PHYSICIAN_NOTE", "dt": "2026-01-01T08:00:00",
                 "text": "Progress note text"},
                {"type": "RADIOLOGY", "dt": "2026-01-01T09:00:00",
                 "text": "CT scan results"},
            ],
        })
        result = extract_procedure_operatives(_empty_features(), days_data)
        assert result["events"] == []
        assert "no_procedure_operative_events_found" in result["notes"]


# ── Tests: basic extraction ────────────────────────────────────────

class TestBasicExtraction:

    def test_procedure_item(self):
        days_data = _make_days_data({
            "2026-01-03": [{
                "type": "PROCEDURE",
                "dt": "2026-01-03T11:04:00",
                "text": (
                    "Signed  |||EMERGENT ENDOTRACHEAL INTUBATION| |"
                    "Patient Name: Ronald E Bittner |"
                    "Procedure: Endotracheal intubation"
                ),
            }],
        })
        result = extract_procedure_operatives(_empty_features(), days_data)
        assert len(result["events"]) == 1
        ev = result["events"][0]
        assert ev["ts"] == "2026-01-03T11:04:00"
        assert ev["source_kind"] == "PROCEDURE"
        assert ev["category"] == "operative"
        assert ev["label"] == "Endotracheal intubation"
        assert "raw_line_id" in ev
        assert result["procedure_event_count"] == 1
        assert result["operative_event_count"] == 0
        assert "operative" in result["categories_present"]

    def test_op_note_item(self):
        days_data = _make_days_data({
            "2026-01-15": [{
                "type": "OP_NOTE",
                "dt": "2026-01-15T12:28:00",
                "text": (
                    "Signed  |||Operative Notation| |"
                    "Date of Procedure: 1/15/2026| |"
                    "Pre-op Diagnoses: 1) rib fractures| |"
                    "Procedure: Percutaneous tracheostomy"
                ),
            }],
        })
        result = extract_procedure_operatives(_empty_features(), days_data)
        assert len(result["events"]) == 1
        ev = result["events"][0]
        assert ev["source_kind"] == "OP_NOTE"
        assert ev["category"] == "operative"
        assert ev["label"] == "Percutaneous tracheostomy"
        assert result["operative_event_count"] == 1

    def test_pre_procedure_item(self):
        days_data = _make_days_data({
            "2026-01-12": [{
                "type": "PRE_PROCEDURE",
                "dt": "2026-01-12T18:13:00",
                "text": (
                    "Addendum        |||PCCM Consent documentation| |"
                    "Informed consent was obtained"
                ),
            }],
        })
        result = extract_procedure_operatives(_empty_features(), days_data)
        assert len(result["events"]) == 1
        assert result["events"][0]["category"] == "pre-op"

    def test_significant_event(self):
        days_data = _make_days_data({
            "2026-01-11": [{
                "type": "SIGNIFICANT_EVENT",
                "dt": "2026-01-11T07:33:00",
                "text": "Signed  |||Overnight pt became increasingly agitated",
            }],
        })
        result = extract_procedure_operatives(_empty_features(), days_data)
        assert len(result["events"]) == 1
        assert result["events"][0]["category"] == "significant_event"

    def test_multiple_events_across_days(self):
        days_data = _make_days_data({
            "2026-01-01": [{
                "type": "ANESTHESIA_CONSULT",
                "dt": "2026-01-01T15:11:00",
                "text": "Signed  |||Patient seen for ES block",
            }],
            "2026-01-02": [{
                "type": "ANESTHESIA_PROCEDURE",
                "dt": "2026-01-02T12:32:00",
                "text": (
                    "Procedure Orders|Peripheral Nerve Block ordered| |"
                    "Procedure: Peripheral Nerve Block|"
                    "Block type: Erector Spinae"
                ),
            }],
            "2026-01-03": [{
                "type": "PROCEDURE",
                "dt": "2026-01-03T11:04:00",
                "text": "Signed  |||Bronchoscopy Procedure Note",
            }],
        })
        result = extract_procedure_operatives(_empty_features(), days_data)
        assert len(result["events"]) == 3
        assert result["anesthesia_event_count"] == 2
        assert result["procedure_event_count"] == 1
        cats = result["categories_present"]
        assert "anesthesia" in cats
        assert "operative" in cats


# ── Tests: anesthesia categories ───────────────────────────────────

class TestAnesthesiaCategories:

    def test_anesthesia_preprocedure(self):
        days_data = _make_days_data({
            "2025-12-31": [{
                "type": "ANESTHESIA_PREPROCEDURE",
                "dt": "2025-12-31T11:36:00",
                "text": (
                    "Pre-anesthesia History and Physical|"
                    "Diagnosis: Metatarsal fracture|"
                    "Anesthesia Plan: General|"
                    "ASA Status: 3"
                ),
            }],
        })
        result = extract_procedure_operatives(_empty_features(), days_data)
        assert len(result["events"]) == 1
        ev = result["events"][0]
        assert ev["category"] == "anesthesia"
        assert ev.get("anesthesia_type") == "General"
        assert ev.get("asa_status") == "3"

    def test_anesthesia_postprocedure(self):
        days_data = _make_days_data({
            "2025-12-31": [{
                "type": "ANESTHESIA_POSTPROCEDURE",
                "dt": "2025-12-31T13:33:00",
                "text": (
                    "Signed  |||Anesthesia Immediate Post-Op Note|"
                    "Anesthesia Type: General|"
                    "Airway: Nasal Cannula|"
                    "Patient Condition: Stable"
                ),
            }],
        })
        result = extract_procedure_operatives(_empty_features(), days_data)
        ev = result["events"][0]
        assert ev["category"] == "anesthesia"
        assert ev.get("anesthesia_type") == "General"

    def test_anesthesia_followup(self):
        days_data = _make_days_data({
            "2025-12-31": [{
                "type": "ANESTHESIA_FOLLOWUP",
                "dt": "2025-12-31T14:22:00",
                "text": "Signed  |||Anesthesia Follow Up Post-Op Note",
            }],
        })
        result = extract_procedure_operatives(_empty_features(), days_data)
        assert result["events"][0]["category"] == "anesthesia"
        assert result["anesthesia_event_count"] == 1


# ── Tests: label extraction ────────────────────────────────────────

class TestLabelExtraction:

    def test_procedure_colon_label(self):
        text = "|Procedure: Endotracheal intubation|Indication: Airway"
        label = _extract_label(text)
        assert label == "Endotracheal intubation"

    def test_operation_colon_label(self):
        text = "|Operation: Flexible fiberoptic bronchoscopy|"
        label = _extract_label(text)
        assert label == "Flexible fiberoptic bronchoscopy"

    def test_block_type_label(self):
        text = "|Block type: Erector Spinae|Performed at surgeon's request"
        label = _extract_label(text)
        assert label == "Erector Spinae"

    def test_heading_label(self):
        text = "Signed  |||EMERGENT ENDOTRACHEAL INTUBATION| |Patient Name"
        label = _extract_label(text)
        assert label == "EMERGENT ENDOTRACHEAL INTUBATION"

    def test_no_label(self):
        text = "Some random text without any procedure heading"
        label = _extract_label(text)
        assert label is None

    def test_heading_filters_noise(self):
        text = "Signed  |||Patient seen and evaluated| |Details"
        label = _extract_label(text)
        # "Patient seen..." starts with "Patient" → filtered
        assert label is None


# ── Tests: preop dx extraction ─────────────────────────────────────

class TestPreopDx:

    def test_preop_dx(self):
        text = "|PreOp Dx:  Left 5th metatarsal fracture|"
        dx = _extract_preop_dx(text)
        assert dx == "Left 5th metatarsal fracture"

    def test_pre_op_diagnoses(self):
        text = "|Pre-op Diagnoses: 1) rib fractures|"
        dx = _extract_preop_dx(text)
        assert dx == "1) rib fractures"

    def test_no_preop(self):
        text = "Procedure note without preop diagnosis"
        dx = _extract_preop_dx(text)
        assert dx is None


# ── Tests: milestone extraction ────────────────────────────────────

class TestMilestoneExtraction:

    def test_anesthesia_start_stop(self):
        text = "|Anesthesia Start: 1136|Anesthesia Stop: 1320|"
        milestones = _extract_milestones(text)
        labels = {m["milestone"] for m in milestones}
        assert "anesthesia_start" in labels
        assert "anesthesia_stop" in labels

    def test_incision(self):
        text = "|Incision: 11:42|"
        milestones = _extract_milestones(text)
        assert len(milestones) == 1
        assert milestones[0]["milestone"] == "incision"
        assert milestones[0]["time_raw"] == "11:42"

    def test_tourniquet(self):
        text = "|Tourniquet Inflated: 0845|Tourniquet Deflated: 0930|"
        milestones = _extract_milestones(text)
        labels = {m["milestone"] for m in milestones}
        assert "tourniquet_inflated" in labels
        assert "tourniquet_deflated" in labels

    def test_no_milestones(self):
        text = "Regular procedure note without timestamped milestones"
        milestones = _extract_milestones(text)
        assert milestones == []


# ── Tests: status extraction ──────────────────────────────────────

class TestStatusExtraction:

    def test_completed(self):
        text = "|Status: Completed|"
        status = _extract_status(text)
        assert status == "completed"

    def test_cancelled(self):
        text = "|Case Status: Cancelled|"
        status = _extract_status(text)
        assert status == "cancelled"

    def test_no_status(self):
        text = "Procedure note without status"
        status = _extract_status(text)
        assert status is None


# ── Tests: anesthesia details ──────────────────────────────────────

class TestAnesthesiaDetails:

    def test_type_and_asa(self):
        text = "|Anesthesia Type: General|ASA Status: 3|"
        details = _extract_anesthesia_details(text)
        assert details["anesthesia_type"] == "General"
        assert details["asa_status"] == "3"

    def test_plan_variant(self):
        text = "|Anesthesia Plan: Regional|"
        details = _extract_anesthesia_details(text)
        assert details["anesthesia_type"] == "Regional"

    def test_no_details(self):
        text = "Note without anesthesia details"
        details = _extract_anesthesia_details(text)
        assert details["anesthesia_type"] is None
        assert details["asa_status"] is None


# ── Tests: evidence traceability ───────────────────────────────────

class TestEvidence:

    def test_raw_line_id_preserved(self):
        days_data = _make_days_data({
            "2026-01-03": [{
                "type": "PROCEDURE",
                "dt": "2026-01-03T11:04:00",
                "text": "Signed  |||Bronchoscopy",
                "raw_line_id": "line:2710",
            }],
        })
        result = extract_procedure_operatives(_empty_features(), days_data)
        ev = result["events"][0]
        assert ev["raw_line_id"] == "line:2710"
        assert ev["evidence"][0]["raw_line_id"] == "line:2710"
        assert result["evidence"][0]["raw_line_id"] == "line:2710"

    def test_fallback_item_ref_when_no_raw_line_id(self):
        days_data = _make_days_data({
            "2026-01-03": [{
                "type": "PROCEDURE",
                "dt": "2026-01-03T11:04:00",
                "text": "Signed  |||Bronchoscopy",
            }],
        })
        result = extract_procedure_operatives(_empty_features(), days_data)
        ev = result["events"][0]
        assert ev["raw_line_id"] == "item:2026-01-03:0"


# ── Tests: kind category mapping ──────────────────────────────────

class TestKindMapping:

    def test_all_kinds_have_categories(self):
        for kind in _PROC_KINDS:
            assert kind in _KIND_CATEGORY

    def test_proc_kinds_match_map(self):
        assert _PROC_KINDS == frozenset(_KIND_CATEGORY.keys())


# ── Tests: determinism ────────────────────────────────────────────

class TestDeterminism:

    def test_same_input_same_output(self):
        days_data = _make_days_data({
            "2026-01-01": [
                {"type": "PROCEDURE", "dt": "2026-01-01T08:00:00",
                 "text": "Signed  |||Bronchoscopy"},
                {"type": "OP_NOTE", "dt": "2026-01-01T09:00:00",
                 "text": "Signed  |||Operative Notation|"
                         "Procedure: ORIF distal radius"},
            ],
            "2026-01-02": [
                {"type": "ANESTHESIA_PROCEDURE", "dt": "2026-01-02T10:00:00",
                 "text": "Signed  |||Airway Procedure Note|"
                         "Anesthesia Type: General"},
            ],
        })
        r1 = extract_procedure_operatives(_empty_features(), days_data)
        r2 = extract_procedure_operatives(_empty_features(), days_data)
        assert r1 == r2


# ── Tests: CPT code extraction ─────────────────────────────────────

class TestCPTCodeExtraction:
    """Unit tests for _extract_cpt_codes helper."""

    def test_explicit_cpt_space(self):
        """'CPT 30905' → ['30905']."""
        assert _extract_cpt_codes("Control of nasal bleeding  CPT 30905") == ["30905"]

    def test_explicit_cpt_colon(self):
        """'CPT: 31622' → ['31622']."""
        assert _extract_cpt_codes("Bronchoscopy CPT: 31622") == ["31622"]

    def test_explicit_cpt_hash(self):
        """'CPT #27236' → ['27236']."""
        assert _extract_cpt_codes("ORIF femur CPT #27236") == ["27236"]

    def test_case_insensitive(self):
        """'cpt 30905' → ['30905']."""
        assert _extract_cpt_codes("nasal bleeding  cpt 30905") == ["30905"]

    def test_multiple_cpts(self):
        """Two CPT codes on one line."""
        text = "Procedure: ORIF  CPT 27236|Bronchoscopy  CPT 31622"
        codes = _extract_cpt_codes(text)
        assert codes == ["27236", "31622"]

    def test_duplicate_cpts_deduped(self):
        """Same CPT repeated → single entry."""
        text = "CPT 30905|Repeated: CPT 30905"
        assert _extract_cpt_codes(text) == ["30905"]

    def test_no_cpt_present(self):
        """No CPT token → empty list."""
        assert _extract_cpt_codes("ORIF distal radius fracture") == []

    def test_empty_string(self):
        """Empty text → empty list."""
        assert _extract_cpt_codes("") == []

    def test_vest_cpt_excluded(self):
        """'VEST CPT' (chest physiotherapy) is not a CPT code."""
        assert _extract_cpt_codes("Continue VEST CPT with saline") == []

    def test_narrative_cpt_codes_no_number(self):
        """Narrative 'CPT Codes for chemo' without actual code → empty."""
        assert _extract_cpt_codes("billing (CPT Codes for chemo)") == []

    def test_partial_4_digit_code(self):
        """4-digit code after CPT is not valid (must be 5)."""
        assert _extract_cpt_codes("CPT 3090") == []

    def test_6_digit_code_rejected(self):
        """6-digit code → only first 5 digits captured if boundary exists."""
        # "309050" has no word boundary after 5 digits, so no match
        assert _extract_cpt_codes("CPT 309050") == []


class TestCPTIntegration:
    """Integration tests: CPT codes in full extractor output."""

    def test_cpt_on_procedure_event(self):
        """Procedure item with explicit CPT → cpt_codes in event."""
        days_data = _make_days_data({
            "2026-01-05": [{
                "type": "PROCEDURE",
                "dt": "2026-01-05T14:00:00",
                "text": "Surgical Procedure Performed:  "
                        "Control of posterior nasal bleeding    CPT 30905",
            }]
        })
        result = extract_procedure_operatives(_empty_features(), days_data)
        assert result["events"][0]["cpt_codes"] == ["30905"]

    def test_no_cpt_field_when_absent(self):
        """Procedure item without CPT → no cpt_codes key on event."""
        days_data = _make_days_data({
            "2026-01-05": [{
                "type": "PROCEDURE",
                "dt": "2026-01-05T14:00:00",
                "text": "Procedure: ORIF distal radius fracture",
            }]
        })
        result = extract_procedure_operatives(_empty_features(), days_data)
        assert "cpt_codes" not in result["events"][0]

    def test_multiple_cpts_on_event(self):
        """Multiple CPT codes in one procedure text."""
        days_data = _make_days_data({
            "2026-01-05": [{
                "type": "OP_NOTE",
                "dt": "2026-01-05T10:00:00",
                "text": "Procedure: Debridement and closure\n"
                        "CPT 27236\nCPT 31622",
            }]
        })
        result = extract_procedure_operatives(_empty_features(), days_data)
        assert result["events"][0]["cpt_codes"] == ["27236", "31622"]

    def test_raw_line_id_present_with_cpt(self):
        """Event with CPT still has raw_line_id for traceability."""
        days_data = _make_days_data({
            "2026-01-05": [{
                "type": "PROCEDURE",
                "dt": "2026-01-05T14:00:00",
                "text": "Control of bleeding CPT 30905",
                "raw_line_id": "abc123",
            }]
        })
        result = extract_procedure_operatives(_empty_features(), days_data)
        ev = result["events"][0]
        assert ev["cpt_codes"] == ["30905"]
        assert ev["raw_line_id"] == "abc123"
