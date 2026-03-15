#!/usr/bin/env python3
"""
Tests for gcs_daily — per-day GCS extraction with E/V/M component support.

Covers:
  - Simple total extraction (GCS: 15, GCS 14, GCS: 8T)
  - Component-parenthesized extraction with eye/verbal/motor
  - Inline components extraction with eye/verbal/motor
  - Descriptive components (GCS: 4 (spontaneously),5 (oriented),6 (follows commands) = 15)
  - Structured 4-line flowsheet block extraction
  - Structured block fail-closed (sum mismatch, unknown text)
  - Simple totals do NOT produce eye/verbal/motor
  - Arrival GCS from Primary Survey Disability line
  - best_gcs / worst_gcs computation
  - Questionnaire line exclusion
  - Narrative-only line exclusion
  - Intubated marker (T suffix)
  - Deduplication within same text block
  - ED fallback when TRAUMA_HP missing primary survey GCS
"""

from __future__ import annotations

import pytest

from cerebralos.features.gcs_daily import (
    _extract_gcs_from_text,
    extract_gcs_for_day,
)


# ── Helpers ─────────────────────────────────────────────────────────

def _timeline_item(text: str, dt: str = "2025-12-18T14:30:00",
                   item_type: str = "ED_NOTE") -> dict:
    """Build a minimal timeline item."""
    return {
        "type": item_type,
        "dt": dt,
        "source_id": "test",
        "payload": {"text": text},
    }


# ── Simple total extraction ─────────────────────────────────────────

class TestSimpleTotal:
    def test_gcs_colon_15(self):
        readings, _ = _extract_gcs_from_text("GCS: 15", "2025-12-18", "ED_NOTE", None)
        assert len(readings) == 1
        assert readings[0]["value"] == 15
        assert readings[0]["source"] == "ED_NOTE:simple"
        assert "eye" not in readings[0]
        assert "verbal" not in readings[0]
        assert "motor" not in readings[0]

    def test_gcs_no_colon(self):
        readings, _ = _extract_gcs_from_text("GCS 14", "2025-12-18", "ED_NOTE", None)
        assert len(readings) == 1
        assert readings[0]["value"] == 14

    def test_gcs_intubated(self):
        readings, _ = _extract_gcs_from_text("GCS: 8T", "2025-12-18", "ED_NOTE", None)
        assert len(readings) == 1
        assert readings[0]["value"] == 8
        assert readings[0]["intubated"] is True

    def test_gcs_with_period(self):
        readings, _ = _extract_gcs_from_text("GCS: 15.", "2025-12-18", "ED_NOTE", None)
        assert len(readings) == 1
        assert readings[0]["value"] == 15

    def test_gcs_out_of_range_excluded(self):
        readings, _ = _extract_gcs_from_text("GCS: 2", "2025-12-18", "ED_NOTE", None)
        assert len(readings) == 0

    def test_gcs_16_excluded(self):
        readings, _ = _extract_gcs_from_text("GCS: 16", "2025-12-18", "ED_NOTE", None)
        assert len(readings) == 0


# ── Component extractions with eye/verbal/motor ─────────────────────

class TestComponentParen:
    def test_paren_form(self):
        text = "GCS (E:4 V:5 M:6) 15"
        readings, _ = _extract_gcs_from_text(text, "2025-12-18", "ED_NOTE", None)
        assert len(readings) == 1
        r = readings[0]
        assert r["value"] == 15
        assert r["eye"] == 4
        assert r["verbal"] == 5
        assert r["motor"] == 6
        assert r["source"] == "ED_NOTE:component_paren"

    def test_paren_intubated(self):
        text = "GCS (E:2 V:1T M:4) 7T"
        readings, _ = _extract_gcs_from_text(text, "2025-12-18", "ED_NOTE", None)
        assert len(readings) == 1
        r = readings[0]
        assert r["value"] == 7
        assert r["intubated"] is True
        assert r["eye"] == 2
        assert r["verbal"] == 1
        assert r["motor"] == 4


class TestInlineComponents:
    def test_inline_form(self):
        text = "GCS E:4 V:5 M:6 15"
        readings, _ = _extract_gcs_from_text(text, "2025-12-18", "ED_NOTE", None)
        assert len(readings) == 1
        r = readings[0]
        assert r["value"] == 15
        assert r["eye"] == 4
        assert r["verbal"] == 5
        assert r["motor"] == 6
        assert r["source"] == "ED_NOTE:inline_components"


class TestDescComponents:
    def test_parenthetical_descriptions(self):
        text = "GCS: 4 (spontaneously),5 (oriented),6 (follows commands) = 15"
        readings, _ = _extract_gcs_from_text(text, "2025-12-18", "ED_NOTE", None)
        assert len(readings) == 1
        r = readings[0]
        assert r["value"] == 15
        assert r["eye"] == 4
        assert r["verbal"] == 5
        assert r["motor"] == 6
        assert r["source"] == "ED_NOTE:desc_components"

    def test_does_not_extract_wrong_simple_value(self):
        """The desc_components pattern must prevent the simple regex
        from incorrectly extracting GCS=4 from this format."""
        text = "GCS: 4 (spontaneously),5 (oriented),6 (follows commands) = 15"
        readings, _ = _extract_gcs_from_text(text, "2025-12-18", "ED_NOTE", None)
        # Should only have ONE reading with value 15, not a second with value 4
        assert len(readings) == 1
        assert readings[0]["value"] == 15


# ── Structured 4-line flowsheet block ───────────────────────────────

class TestStructuredBlock:
    def test_basic_block(self):
        text = "\n".join([
            "Eye Opening: Spontaneous",
            "Best Verbal Response: Oriented",
            "Best Motor Response: Obeys commands",
            "Glasgow Coma Scale Score: 15",
        ])
        readings, _ = _extract_gcs_from_text(text, "2025-12-18", "ED_NOTE", None)
        assert len(readings) == 1
        r = readings[0]
        assert r["value"] == 15
        assert r["eye"] == 4
        assert r["verbal"] == 5
        assert r["motor"] == 6
        assert r["source"] == "ED_NOTE:structured_block"

    def test_block_to_speech_confused(self):
        text = "\n".join([
            "Eye Opening: To speech",
            "Best Verbal Response: Confused",
            "Best Motor Response: Obeys commands",
            "Glasgow Coma Scale Score: 13",
        ])
        readings, _ = _extract_gcs_from_text(text, "2025-12-18", "ED_NOTE", None)
        assert len(readings) == 1
        r = readings[0]
        assert r["value"] == 13
        assert r["eye"] == 3
        assert r["verbal"] == 4
        assert r["motor"] == 6

    def test_block_low_gcs(self):
        text = "\n".join([
            "Eye Opening: To pain",
            "Best Verbal Response: Incomprehensible sounds",
            "Best Motor Response: Withdrawal",
            "Glasgow Coma Scale Score: 8",
        ])
        readings, _ = _extract_gcs_from_text(text, "2025-12-18", "ED_NOTE", None)
        assert len(readings) == 1
        r = readings[0]
        assert r["value"] == 8
        assert r["eye"] == 2
        assert r["verbal"] == 2
        assert r["motor"] == 4

    def test_block_sum_mismatch_skipped(self):
        """Fail-closed: if components don't sum to total, skip entirely."""
        text = "\n".join([
            "Eye Opening: Spontaneous",
            "Best Verbal Response: Oriented",
            "Best Motor Response: Obeys commands",
            "Glasgow Coma Scale Score: 12",  # 4+5+6=15 != 12
        ])
        readings, _ = _extract_gcs_from_text(text, "2025-12-18", "ED_NOTE", None)
        assert len(readings) == 0

    def test_block_unknown_text_skipped(self):
        """Fail-closed: unknown component text → skip block."""
        text = "\n".join([
            "Eye Opening: Wide open",  # not in map
            "Best Verbal Response: Oriented",
            "Best Motor Response: Obeys commands",
            "Glasgow Coma Scale Score: 15",
        ])
        readings, _ = _extract_gcs_from_text(text, "2025-12-18", "ED_NOTE", None)
        assert len(readings) == 0

    def test_block_incomplete_skipped(self):
        """If only 3 of the 4 lines are present, no block match."""
        text = "\n".join([
            "Eye Opening: Spontaneous",
            "Best Verbal Response: Oriented",
            "Glasgow Coma Scale Score: 15",
        ])
        readings, _ = _extract_gcs_from_text(text, "2025-12-18", "ED_NOTE", None)
        assert len(readings) == 0

    def test_multiple_blocks(self):
        text = "\n".join([
            "Eye Opening: Spontaneous",
            "Best Verbal Response: Oriented",
            "Best Motor Response: Obeys commands",
            "Glasgow Coma Scale Score: 15",
            "Purposeful Movement: Grasps-releases",
            "Eye Opening: To speech",
            "Best Verbal Response: Confused",
            "Best Motor Response: Obeys commands",
            "Glasgow Coma Scale Score: 13",
        ])
        readings, _ = _extract_gcs_from_text(text, "2025-12-18", "ED_NOTE", None)
        assert len(readings) == 2
        vals = sorted([r["value"] for r in readings])
        assert vals == [13, 15]

    def test_block_with_context_lines(self):
        """Block preceded by a header line (mirrors real data)."""
        text = "\n".join([
            "Neuro (WDL): Exceptions to WDL",
            "Glasgow Coma Scale",
            "Eye Opening: Spontaneous",
            "Best Verbal Response: Oriented",
            "Best Motor Response: Obeys commands",
            "Glasgow Coma Scale Score: 15",
            "Purposeful Movement (Completed Only if Best Motor Response = 6)",
        ])
        readings, _ = _extract_gcs_from_text(text, "2025-12-18", "ED_NOTE", None)
        assert len(readings) == 1
        assert readings[0]["value"] == 15
        assert readings[0]["eye"] == 4


# ── Exclusions ──────────────────────────────────────────────────────

class TestExclusions:
    def test_questionnaire_excluded(self):
        text = "GCS 3-4?"
        readings, _ = _extract_gcs_from_text(text, "2025-12-18", "ED_NOTE", None)
        assert len(readings) == 0

    def test_narrative_excluded(self):
        text = "GCS changes noted over the course of the day"
        readings, _ = _extract_gcs_from_text(text, "2025-12-18", "ED_NOTE", None)
        assert len(readings) == 0


# ── Arrival GCS from Primary Survey ─────────────────────────────────

class TestArrivalGCS:
    def test_arrival_from_disability(self):
        text = "\n".join([
            "Primary Survey:",
            "  Airway: patent",
            "  Disability: GCS 15",
            "Secondary Survey:",
        ])
        readings, arrival = _extract_gcs_from_text(text, "2025-12-18", "TRAUMA_HP", None)
        assert arrival is not None
        assert arrival["value"] == 15
        assert arrival["is_arrival"] is True

    def test_disability_double_gcs(self):
        """Pattern seen in real data: 'Disability: GCS GCS 15'."""
        text = "\n".join([
            "Primary Survey:",
            "  Disability: GCS GCS 15",
            "Secondary Survey:",
        ])
        readings, arrival = _extract_gcs_from_text(text, "2025-12-18", "TRAUMA_HP", None)
        assert arrival is not None
        assert arrival["value"] == 15


# ── extract_gcs_for_day integration ─────────────────────────────────

class TestExtractForDay:
    def test_best_worst(self):
        items = [
            _timeline_item("GCS: 15"),
            _timeline_item("GCS: 12"),
            _timeline_item("GCS: 14"),
        ]
        result, warnings = extract_gcs_for_day(items, "2025-12-18")
        assert result["best_gcs"]["value"] == 15
        assert result["worst_gcs"]["value"] == 12

    def test_components_in_all_readings(self):
        text = "\n".join([
            "Eye Opening: Spontaneous",
            "Best Verbal Response: Oriented",
            "Best Motor Response: Obeys commands",
            "Glasgow Coma Scale Score: 15",
        ])
        items = [_timeline_item(text)]
        result, _ = extract_gcs_for_day(items, "2025-12-18")
        assert len(result["all_readings"]) == 1
        r = result["all_readings"][0]
        assert r["eye"] == 4
        assert r["verbal"] == 5
        assert r["motor"] == 6

    def test_simple_total_no_components_in_output(self):
        items = [_timeline_item("GCS: 15")]
        result, _ = extract_gcs_for_day(items, "2025-12-18")
        r = result["all_readings"][0]
        assert "eye" not in r
        assert "verbal" not in r
        assert "motor" not in r

    def test_no_readings_dna(self):
        items = [_timeline_item("No neuro findings")]
        result, _ = extract_gcs_for_day(items, "2025-12-18")
        assert result["arrival_gcs"] == "DATA NOT AVAILABLE"
        assert result["best_gcs"] == "DATA NOT AVAILABLE"
        assert result["worst_gcs"] == "DATA NOT AVAILABLE"
        assert result["all_readings"] == []

    def test_arrival_gcs_with_components_preserved(self):
        """When arrival GCS has components, they should appear in output."""
        text = "\n".join([
            "Primary Survey:",
            "  Disability: GCS 15",
            "Secondary Survey:",
            "GCS: 12",
        ])
        items = [_timeline_item(text, item_type="TRAUMA_HP")]
        result, _ = extract_gcs_for_day(items, "2025-12-18")
        assert result["arrival_gcs"]["value"] == 15
        assert result["worst_gcs"]["value"] == 12

    def test_ed_fallback_when_trauma_hp_missing_primary_survey(self):
        items = [
            _timeline_item("No disability line here", item_type="TRAUMA_HP",
                           dt="2025-12-18T14:00:00"),
            _timeline_item("GCS: 14", item_type="ED_NOTE",
                           dt="2025-12-18T14:30:00"),
        ]
        result, warnings = extract_gcs_for_day(
            items, "2025-12-18",
            arrival_datetime="2025-12-18T14:00:00",
        )
        assert result["arrival_gcs_missing_in_trauma_hp"] is True
        assert "arrival_gcs_missing_in_trauma_hp" in warnings

    def test_components_in_best_gcs(self):
        """best_gcs should include eye/verbal/motor if source had components."""
        text = "\n".join([
            "Eye Opening: Spontaneous",
            "Best Verbal Response: Oriented",
            "Best Motor Response: Obeys commands",
            "Glasgow Coma Scale Score: 15",
        ])
        items = [
            _timeline_item("GCS: 10"),
            _timeline_item(text),
        ]
        result, _ = extract_gcs_for_day(items, "2025-12-18")
        assert result["best_gcs"]["value"] == 15
        assert result["best_gcs"]["eye"] == 4
        assert result["best_gcs"]["verbal"] == 5
        assert result["best_gcs"]["motor"] == 6
        # worst should NOT have components (simple total)
        assert result["worst_gcs"]["value"] == 10
        assert "eye" not in result["worst_gcs"]


# ── Regression: compact form always sets intubated ──────────────────

class TestCompactIntubated:
    def test_compact_without_trailing_t_still_intubated(self):
        """Compact form E4V1tM5 GCS 10 (no trailing T) must set intubated=True
        because the 't' between V and M *is* the intubated marker."""
        text = "E4V1tM5 GCS 10"
        readings, _ = _extract_gcs_from_text(text, "2025-12-18", "ED_NOTE", None)
        assert len(readings) == 1
        assert readings[0]["intubated"] is True

    def test_compact_with_trailing_t_also_intubated(self):
        text = "E2VtM4 GCS 7T"
        readings, _ = _extract_gcs_from_text(text, "2025-12-18", "ED_NOTE", None)
        assert len(readings) == 1
        assert readings[0]["intubated"] is True


# ── Regression: component sum mismatch omits eye/verbal/motor ───────

class TestComponentSumMismatch:
    def test_paren_mismatch_omits_components(self):
        """GCS (E:4 V:5 M:6) 14 — sum 4+5+6=15 != 14 → total kept, no components."""
        text = "GCS (E:4 V:5 M:6) 14"
        readings, _ = _extract_gcs_from_text(text, "2025-12-18", "ED_NOTE", None)
        assert len(readings) == 1
        assert readings[0]["value"] == 14
        assert "eye" not in readings[0]
        assert "verbal" not in readings[0]
        assert "motor" not in readings[0]

    def test_inline_mismatch_omits_components(self):
        """GCS E:4 V:5 M:6 13 — sum 15 != 13 → total kept, no components."""
        text = "GCS E:4 V:5 M:6 13"
        readings, _ = _extract_gcs_from_text(text, "2025-12-18", "ED_NOTE", None)
        assert len(readings) == 1
        assert readings[0]["value"] == 13
        assert "eye" not in readings[0]
        assert "verbal" not in readings[0]
        assert "motor" not in readings[0]

    def test_desc_mismatch_omits_components(self):
        """GCS: 4 (spontaneously),5 (oriented),6 (follows commands) = 14 → no components."""
        text = "GCS: 4 (spontaneously),5 (oriented),6 (follows commands) = 14"
        readings, _ = _extract_gcs_from_text(text, "2025-12-18", "ED_NOTE", None)
        assert len(readings) == 1
        assert readings[0]["value"] == 14
        assert "eye" not in readings[0]
        assert "verbal" not in readings[0]
        assert "motor" not in readings[0]

    def test_matching_sum_keeps_components(self):
        """GCS (E:4 V:5 M:6) 15 — sum matches → components present."""
        text = "GCS (E:4 V:5 M:6) 15"
        readings, _ = _extract_gcs_from_text(text, "2025-12-18", "ED_NOTE", None)
        assert len(readings) == 1
        assert readings[0]["eye"] == 4
        assert readings[0]["verbal"] == 5
        assert readings[0]["motor"] == 6


# ── Text-to-number mapping ─────────────────────────────────────────

class TestComponentMappings:
    def test_all_eye_values(self):
        from cerebralos.features.gcs_daily import _lookup_component, _EYE_MAP
        assert _lookup_component("Spontaneous", _EYE_MAP) == 4
        assert _lookup_component("To speech", _EYE_MAP) == 3
        assert _lookup_component("To pain", _EYE_MAP) == 2
        assert _lookup_component("None", _EYE_MAP) == 1
        assert _lookup_component("Unknown thing", _EYE_MAP) is None

    def test_all_verbal_values(self):
        from cerebralos.features.gcs_daily import _lookup_component, _VERBAL_MAP
        assert _lookup_component("Oriented", _VERBAL_MAP) == 5
        assert _lookup_component("Confused", _VERBAL_MAP) == 4
        assert _lookup_component("Inappropriate words", _VERBAL_MAP) == 3
        assert _lookup_component("Incomprehensible sounds", _VERBAL_MAP) == 2
        assert _lookup_component("None", _VERBAL_MAP) == 1

    def test_all_motor_values(self):
        from cerebralos.features.gcs_daily import _lookup_component, _MOTOR_MAP
        assert _lookup_component("Obeys commands", _MOTOR_MAP) == 6
        assert _lookup_component("Localizes pain", _MOTOR_MAP) == 5
        assert _lookup_component("Withdrawal", _MOTOR_MAP) == 4
        assert _lookup_component("Abnormal flexion", _MOTOR_MAP) == 3
        assert _lookup_component("Extension", _MOTOR_MAP) == 2
        assert _lookup_component("None", _MOTOR_MAP) == 1
