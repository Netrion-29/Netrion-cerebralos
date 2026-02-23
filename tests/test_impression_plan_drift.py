#!/usr/bin/env python3
"""
Tests for Impression/Plan Drift Diff v1.

Covers:
  - Normalisation pipeline (deterministic, idempotent)
  - Section extraction from note text
  - Drift detection across synthetic multi-day timelines
  - Fail-closed behaviour (no notes, single-day)
  - Evidence traceability (raw_line_id present)
  - Stable hashing (same input → same output)
"""

import copy
import pytest

from cerebralos.features.impression_plan_drift_v1 import (
    _normalise_item,
    _stable_hash,
    _extract_impression_items,
    _extract_assessment_plan_items,
    _extract_all_impression_plan_from_note,
    _collect_daily_impressions,
    _compute_drift_events,
    extract_impression_plan_drift,
)


# ── Normalisation tests ─────────────────────────────────────────────

class TestNormaliseItem:
    def test_lowercase(self):
        assert "acute fracture" in _normalise_item("Acute Fracture")

    def test_strip_bullet_marker_dash(self):
        result = _normalise_item("- Acute fracture of the left humerus")
        assert not result.startswith("-")
        assert "acute fracture" in result

    def test_strip_bullet_marker_number(self):
        result = _normalise_item("1. No acute intracranial process")
        assert not result.startswith("1")
        assert "no acute intracranial process" in result

    def test_strip_bullet_marker_bullet(self):
        result = _normalise_item("• No acute findings")
        assert not result.startswith("•")

    def test_replace_date_tokens(self):
        result = _normalise_item("Compared to 12/18/2025 study")
        assert "<date>" in result
        assert "12/18/2025" not in result

    def test_replace_numeric_tokens(self):
        result = _normalise_item("SBP 120 mmHg")
        assert "<num>" in result
        assert "120" not in result

    def test_collapse_whitespace(self):
        result = _normalise_item("  no   acute    findings  ")
        assert "  " not in result

    def test_strip_trailing_punctuation(self):
        result = _normalise_item("No acute findings.")
        assert not result.endswith(".")

    def test_idempotent(self):
        """Normalising an already-normalised string produces same result."""
        raw = "1. Acute comminuted fracture on 12/18/2025, SBP 90."
        first = _normalise_item(raw)
        second = _normalise_item(first)
        assert first == second

    def test_deterministic(self):
        """Same input always produces same output."""
        text = "2. Nondisplaced rib fractures."
        results = [_normalise_item(text) for _ in range(10)]
        assert len(set(results)) == 1


class TestStableHash:
    def test_deterministic(self):
        h1 = _stable_hash("no acute findings")
        h2 = _stable_hash("no acute findings")
        assert h1 == h2

    def test_different_inputs(self):
        h1 = _stable_hash("no acute findings")
        h2 = _stable_hash("acute fracture present")
        assert h1 != h2

    def test_length(self):
        h = _stable_hash("test")
        assert len(h) == 16


# ── Section extraction tests ────────────────────────────────────────

class TestExtractImpressionItems:
    def test_basic_impression(self):
        text = (
            "FINDINGS:\nNormal chest.\n\n"
            "IMPRESSION:\n"
            "1. No acute findings.\n"
            "2. Stable granulomatous calcifications.\n"
            "\n"
            "Electronically signed by: Dr. Smith\n"
        )
        items = _extract_impression_items(text)
        assert len(items) == 2
        assert "No acute findings." in items[0]
        assert "Stable granulomatous" in items[1]

    def test_impression_inline(self):
        text = "IMPRESSION: No acute intracranial process.\n"
        items = _extract_impression_items(text)
        assert len(items) == 1
        assert "No acute intracranial process." in items[0]

    def test_narrative_and_impression(self):
        text = (
            "Narrative & Impression\n"
            "INDICATION:\ntrauma\n\n"
            "FINDINGS:\nNormal.\n\n"
            "IMPRESSION:\n"
            "No acute findings.\n"
        )
        items = _extract_impression_items(text)
        assert any("No acute findings" in it for it in items)

    def test_no_impression(self):
        text = "HISTORY: Trauma.\nFINDINGS: Normal chest.\n"
        items = _extract_impression_items(text)
        assert items == []

    def test_section_terminated_by_electronically_signed(self):
        text = (
            "IMPRESSION:\n"
            "1. No acute fracture.\n"
            "2. Mild degenerative changes.\n"
            "Electronically signed by: Dr. Jones 12/18/2025\n"
            "Some other text that should not be captured.\n"
        )
        items = _extract_impression_items(text)
        assert len(items) == 2


class TestExtractAssessmentPlanItems:
    def test_basic_ap(self):
        text = (
            "Assessment/Plan\n"
            "1. 65-year-old female with dementia.\n"
            "2. Continue home medications.\n"
            "3. PT/OT consult.\n"
            "\n"
            "Attestation\n"
            "I have reviewed the above.\n"
        )
        items = _extract_assessment_plan_items(text)
        assert len(items) == 3
        assert "65-year-old" in items[0]

    def test_ap_with_slash(self):
        text = (
            "A/P:\n"
            "Continue current management.\n"
            "______\n"
        )
        items = _extract_assessment_plan_items(text)
        assert len(items) == 1

    def test_no_ap(self):
        text = "HISTORY: Trauma.\nFINDINGS: Normal.\nIMPRESSION: Fine.\n"
        items = _extract_assessment_plan_items(text)
        assert items == []


class TestExtractAllImpressionPlan:
    def test_combined(self):
        text = (
            "IMPRESSION:\n"
            "1. Left humerus fracture.\n"
            "\n"
            "Assessment/Plan\n"
            "1. Left humerus fracture.\n"
            "2. Ortho consult.\n"
            "3. Pain management.\n"
            "\n"
            "Attestation\n"
        )
        items = _extract_all_impression_plan_from_note(text)
        # "Left humerus fracture." appears in both but should be deduplicated
        assert len(items) == 3
        assert items[0] == "1. Left humerus fracture."
        assert "Ortho consult" in items[1]
        assert "Pain management" in items[2]


# ── Synthetic timeline helpers ──────────────────────────────────────

def _make_days_data(day_notes):
    """
    Build a minimal patient_days_v1.json structure.

    day_notes: dict of { "YYYY-MM-DD": [note_text, ...] }
    """
    days = {}
    for day_iso, notes in day_notes.items():
        items = []
        for i, note_text in enumerate(notes):
            items.append({
                "type": "PHYSICIAN_NOTE",
                "dt": f"{day_iso}T10:{i:02d}:00",
                "payload": {"text": note_text},
            })
        days[day_iso] = {"items": items}
    return {"meta": {"patient_id": "Test_Patient"}, "days": days}


# ── Integration tests: drift detection ──────────────────────────────

class TestDriftDetection:
    def test_no_notes(self):
        """No impression sections at all → DATA NOT AVAILABLE."""
        days_data = _make_days_data({
            "2025-12-18": ["HISTORY: Trauma.\nFINDINGS: Normal.\n"],
            "2025-12-19": ["HISTORY: follow-up.\nFINDINGS: Stable.\n"],
        })
        result = extract_impression_plan_drift({}, days_data)
        assert result["drift_detected"] == "DATA NOT AVAILABLE"
        assert result["days_compared_count"] == 0
        assert result["days_with_impression_count"] == 0

    def test_single_day(self):
        """Only one day with impression → DATA NOT AVAILABLE."""
        days_data = _make_days_data({
            "2025-12-18": [
                "IMPRESSION:\n1. No acute findings.\n"
            ],
            "2025-12-19": [
                "HISTORY: follow-up.\n"
            ],
        })
        result = extract_impression_plan_drift({}, days_data)
        assert result["drift_detected"] == "DATA NOT AVAILABLE"
        assert result["days_with_impression_count"] == 1
        assert result["days_compared_count"] == 0

    def test_identical_days_no_drift(self):
        """Same impression on two days → drift_detected = False."""
        note = "IMPRESSION:\n1. No acute findings.\n2. Stable rib fractures.\n"
        days_data = _make_days_data({
            "2025-12-18": [note],
            "2025-12-19": [note],
        })
        result = extract_impression_plan_drift({}, days_data)
        assert result["drift_detected"] is False
        assert result["days_compared_count"] == 1
        assert result["days_with_impression_count"] == 2
        assert len(result["drift_events"]) == 1
        ev = result["drift_events"][0]
        assert len(ev["added_items"]) == 0
        assert len(ev["removed_items"]) == 0
        assert ev["persisted_count"] == 2
        assert ev["drift_ratio"] == 0.0

    def test_drift_detected(self):
        """Different impressions across days → drift_detected = True."""
        note1 = "IMPRESSION:\n1. Acute humerus fracture.\n2. Rib fractures.\n"
        note2 = "IMPRESSION:\n1. Healing humerus fracture.\n2. Rib fractures.\n3. New pneumonia.\n"
        days_data = _make_days_data({
            "2025-12-18": [note1],
            "2025-12-19": [note2],
        })
        result = extract_impression_plan_drift({}, days_data)
        assert result["drift_detected"] is True
        assert result["days_compared_count"] == 1
        ev = result["drift_events"][0]
        assert len(ev["added_items"]) > 0  # "healing humerus" + "new pneumonia"
        assert len(ev["removed_items"]) > 0  # "acute humerus fracture"
        assert ev["drift_ratio"] > 0.0

    def test_three_days(self):
        """Three days produce two drift events."""
        note1 = "IMPRESSION:\n1. Acute fracture.\n"
        note2 = "IMPRESSION:\n1. Acute fracture.\n2. Pneumonia.\n"
        note3 = "IMPRESSION:\n1. Healing fracture.\n2. Pneumonia resolving.\n"
        days_data = _make_days_data({
            "2025-12-18": [note1],
            "2025-12-19": [note2],
            "2025-12-20": [note3],
        })
        result = extract_impression_plan_drift({}, days_data)
        assert result["drift_detected"] is True
        assert result["days_compared_count"] == 2
        assert len(result["drift_events"]) == 2

    def test_numbers_normalised_away(self):
        """Vitals/labs numbers change but text is otherwise same → no drift."""
        note1 = "IMPRESSION:\nSBP 120 stable.\n"
        note2 = "IMPRESSION:\nSBP 135 stable.\n"
        days_data = _make_days_data({
            "2025-12-18": [note1],
            "2025-12-19": [note2],
        })
        result = extract_impression_plan_drift({}, days_data)
        assert result["drift_detected"] is False

    def test_dates_normalised_away(self):
        """Date references change but text is otherwise same → no drift."""
        note1 = "IMPRESSION:\nCompared to 12/18/2025 study, no change.\n"
        note2 = "IMPRESSION:\nCompared to 12/19/2025 study, no change.\n"
        days_data = _make_days_data({
            "2025-12-18": [note1],
            "2025-12-19": [note2],
        })
        result = extract_impression_plan_drift({}, days_data)
        assert result["drift_detected"] is False


# ── Evidence traceability tests ─────────────────────────────────────

class TestEvidenceTraceability:
    def test_evidence_has_raw_line_id(self):
        """All evidence entries must have raw_line_id."""
        note = "IMPRESSION:\n1. No acute findings.\n"
        days_data = _make_days_data({
            "2025-12-18": [note],
            "2025-12-19": [note],
        })
        result = extract_impression_plan_drift({}, days_data)
        for ev in result["evidence"]:
            assert "raw_line_id" in ev
            assert isinstance(ev["raw_line_id"], str)
            assert len(ev["raw_line_id"]) > 0

    def test_drift_event_evidence_has_raw_line_id(self):
        """Evidence within drift events must have raw_line_id."""
        note1 = "IMPRESSION:\n1. Acute fracture.\n"
        note2 = "IMPRESSION:\n1. Healing fracture.\n"
        days_data = _make_days_data({
            "2025-12-18": [note1],
            "2025-12-19": [note2],
        })
        result = extract_impression_plan_drift({}, days_data)
        for de in result["drift_events"]:
            for ev in de["evidence"]:
                assert "raw_line_id" in ev

    def test_evidence_has_snippet(self):
        """Evidence entries have snippet field."""
        note = "IMPRESSION:\n1. No acute findings.\n"
        days_data = _make_days_data({
            "2025-12-18": [note],
            "2025-12-19": [note],
        })
        result = extract_impression_plan_drift({}, days_data)
        for ev in result["evidence"]:
            assert "snippet" in ev
            assert "day" in ev
            assert "source_type" in ev


# ── Determinism tests ───────────────────────────────────────────────

class TestDeterminism:
    def test_same_input_same_output(self):
        """Running twice on identical input produces same output."""
        note1 = "IMPRESSION:\n1. Acute fracture.\n2. Rib fractures.\n"
        note2 = "IMPRESSION:\n1. Healing fracture.\n2. Rib fractures.\n"
        days_data = _make_days_data({
            "2025-12-18": [note1],
            "2025-12-19": [note2],
        })

        r1 = extract_impression_plan_drift({}, days_data)
        r2 = extract_impression_plan_drift({}, copy.deepcopy(days_data))

        assert r1["drift_detected"] == r2["drift_detected"]
        assert r1["days_compared_count"] == r2["days_compared_count"]
        assert len(r1["drift_events"]) == len(r2["drift_events"])
        for e1, e2 in zip(r1["drift_events"], r2["drift_events"]):
            assert e1["added_items"] == e2["added_items"]
            assert e1["removed_items"] == e2["removed_items"]
            assert e1["drift_ratio"] == e2["drift_ratio"]


# ── Schema compliance tests ──────────────────────────────────────────

class TestSchemaCompliance:
    def test_dna_result_schema(self):
        """DATA NOT AVAILABLE result has correct top-level keys."""
        days_data = _make_days_data({"2025-12-18": ["No impression here.\n"]})
        result = extract_impression_plan_drift({}, days_data)
        required_keys = {
            "drift_detected", "days_compared_count",
            "days_with_impression_count", "drift_events",
            "evidence", "notes", "warnings",
        }
        assert set(result.keys()) == required_keys

    def test_drift_event_schema(self):
        """Drift events have correct keys."""
        note1 = "IMPRESSION:\n1. Acute fracture.\n"
        note2 = "IMPRESSION:\n1. Healing fracture.\n"
        days_data = _make_days_data({
            "2025-12-18": [note1],
            "2025-12-19": [note2],
        })
        result = extract_impression_plan_drift({}, days_data)
        for ev in result["drift_events"]:
            assert "date" in ev
            assert "prev_date" in ev
            assert "source_note_types" in ev
            assert "added_items" in ev
            assert "removed_items" in ev
            assert "persisted_count" in ev
            assert "drift_ratio" in ev
            assert "evidence" in ev


# ── Assessment/Plan integration ──────────────────────────────────────

class TestAssessmentPlanIntegration:
    def test_assessment_plan_captured(self):
        """Assessment/Plan sections are included in drift comparison."""
        note1 = (
            "Assessment/Plan\n"
            "1. 60 yo male s/p fall.\n"
            "2. Ortho consult.\n"
            "\n"
            "Attestation\n"
        )
        note2 = (
            "Assessment/Plan\n"
            "1. 60 yo male s/p fall.\n"
            "2. Ortho consult.\n"
            "3. Discharge planning.\n"
            "\n"
            "Attestation\n"
        )
        days_data = _make_days_data({
            "2025-12-18": [note1],
            "2025-12-19": [note2],
        })
        result = extract_impression_plan_drift({}, days_data)
        assert result["drift_detected"] is True
        ev = result["drift_events"][0]
        assert len(ev["added_items"]) == 1  # "discharge planning"
        assert "discharge planning" in ev["added_items"][0]
