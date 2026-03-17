#!/usr/bin/env python3
"""
Tests for pupil reactivity extraction v1.

Covers:
  - Structured flowsheet extraction (Size R/L Pupil, Reaction R/L Pupil)
  - Prose pattern extraction (PERRL, equal/reactive, fixed/dilated, pinpoint, sluggish, nonreactive)
  - Abnormality detection (fixed, dilated, pinpoint, asymmetric)
  - Edge cases and fail-closed behavior (empty items, unknown source types)
"""

import pytest

from cerebralos.features.pupil_reactivity_v1 import (
    extract_pupil_reactivity_for_day,
    _normalize_reaction,
    _is_abnormal,
    _is_asymmetric,
)


# ── helpers ──────────────────────────────────────────────────────────

def _make_item(text: str, item_type: str = "FLOWSHEET", dt: str = "2026-01-01T12:00:00") -> dict:
    return {
        "type": item_type,
        "dt": dt,
        "source_id": "test_source",
        "payload": {"text": text},
    }


# ── test _normalize_reaction ─────────────────────────────────────────

class TestNormalizeReaction:
    def test_brisk(self):
        assert _normalize_reaction("Brisk") == "Brisk"

    def test_brisk_lower(self):
        assert _normalize_reaction("brisk") == "Brisk"

    def test_sluggish(self):
        assert _normalize_reaction("Sluggish") == "Sluggish"

    def test_fixed(self):
        assert _normalize_reaction("Fixed") == "Fixed"

    def test_no_response(self):
        assert _normalize_reaction("No Response") == "Fixed"

    def test_nonreactive(self):
        assert _normalize_reaction("Nonreactive") == "Nonreactive"

    def test_non_reactive_hyphen(self):
        assert _normalize_reaction("non-reactive") == "Nonreactive"

    def test_unknown(self):
        assert _normalize_reaction("Unknown") is None

    def test_empty(self):
        assert _normalize_reaction("") is None


# ── test _is_abnormal ────────────────────────────────────────────────

class TestIsAbnormal:
    def test_normal(self):
        assert _is_abnormal(3.0, 3.0, "Brisk", "Brisk") is False

    def test_fixed_right(self):
        assert _is_abnormal(3.0, 3.0, "Fixed", "Brisk") is True

    def test_fixed_left(self):
        assert _is_abnormal(3.0, 3.0, "Brisk", "Fixed") is True

    def test_nonreactive(self):
        assert _is_abnormal(3.0, 3.0, "Nonreactive", "Brisk") is True

    def test_dilated(self):
        assert _is_abnormal(7.0, 3.0, "Brisk", "Brisk") is True

    def test_pinpoint(self):
        assert _is_abnormal(1.0, 1.0, "Brisk", "Brisk") is True

    def test_asymmetric(self):
        assert _is_abnormal(4.0, 3.0, "Brisk", "Brisk") is True

    def test_symmetric_boundary(self):
        # 0.5mm difference is below 1mm threshold
        assert _is_abnormal(3.0, 3.5, "Brisk", "Brisk") is False

    def test_all_none(self):
        assert _is_abnormal(None, None, None, None) is False

    def test_sluggish_not_abnormal(self):
        # Sluggish alone is NOT flagged as abnormal
        assert _is_abnormal(3.0, 3.0, "Sluggish", "Sluggish") is False


# ── test _is_asymmetric ──────────────────────────────────────────────

class TestIsAsymmetric:
    def test_symmetric(self):
        assert _is_asymmetric(3.0, 3.0) is False

    def test_asymmetric(self):
        assert _is_asymmetric(4.0, 2.0) is True

    def test_one_none(self):
        assert _is_asymmetric(3.0, None) is False

    def test_both_none(self):
        assert _is_asymmetric(None, None) is False


# ── Structured flowsheet extraction ──────────────────────────────────

class TestFlowsheetExtraction:
    def test_standard_4line_block(self):
        """George_Kraus standard flowsheet: Size R, Size L, Reaction R, Reaction L."""
        text = (
            "Photophobia: Not Present\n"
            "Size R Pupil (mm): 3\n"
            "Size L Pupil (mm): 3\n"
            "Reaction R Pupil: Brisk\n"
            "Reaction L Pupil: Brisk\n"
            "Motor Response LUE: Responds to command; Tremors\n"
        )
        result, warnings = extract_pupil_reactivity_for_day(
            [_make_item(text)], "2026-01-01",
        )
        assert len(result["assessments"]) == 1
        a = result["assessments"][0]
        assert a["right_size_mm"] == 3.0
        assert a["left_size_mm"] == 3.0
        assert a["right_reaction"] == "Brisk"
        assert a["left_reaction"] == "Brisk"
        assert a["source_type"] == "FLOWSHEET"
        assert a["abnormal"] is False
        assert a["raw_line_id"]  # non-empty

    def test_interleaved_order(self):
        """Jamie_Hunter variant: Size R, Reaction R, Size L, Reaction L."""
        text = (
            "Photophobia: Not Present\n"
            "Size R Pupil (mm): 3\n"
            "Reaction R Pupil: Brisk\n"
            "Size L Pupil (mm): 3\n"
            "Reaction L Pupil: Brisk\n"
            "Motor Response LUE: Responds to command\n"
        )
        result, _ = extract_pupil_reactivity_for_day(
            [_make_item(text)], "2026-01-01",
        )
        assert len(result["assessments"]) == 1
        a = result["assessments"][0]
        assert a["right_size_mm"] == 3.0
        assert a["left_size_mm"] == 3.0
        assert a["right_reaction"] == "Brisk"
        assert a["left_reaction"] == "Brisk"

    def test_multiple_assessment_blocks(self):
        """Multiple flowsheet blocks separated by non-pupil lines."""
        text = (
            "Size R Pupil (mm): 3\n"
            "Size L Pupil (mm): 3\n"
            "Reaction R Pupil: Brisk\n"
            "Reaction L Pupil: Brisk\n"
            "Motor Response LUE: Normal\n"
            "Size R Pupil (mm): 4\n"
            "Size L Pupil (mm): 4\n"
            "Reaction R Pupil: Sluggish\n"
            "Reaction L Pupil: Sluggish\n"
            "Motor Response LUE: Weak\n"
        )
        result, _ = extract_pupil_reactivity_for_day(
            [_make_item(text)], "2026-01-01",
        )
        assert len(result["assessments"]) == 2
        assert result["assessments"][0]["right_size_mm"] == 3.0
        assert result["assessments"][1]["right_size_mm"] == 4.0
        assert result["assessments"][1]["right_reaction"] == "Sluggish"

    def test_fixed_reaction_abnormal(self):
        """Fixed reaction should flag abnormal."""
        text = (
            "Size R Pupil (mm): 6\n"
            "Size L Pupil (mm): 6\n"
            "Reaction R Pupil: Fixed\n"
            "Reaction L Pupil: Fixed\n"
            "Motor Response LUE: None\n"
        )
        result, _ = extract_pupil_reactivity_for_day(
            [_make_item(text)], "2026-01-01",
        )
        assert len(result["assessments"]) == 1
        a = result["assessments"][0]
        assert a["abnormal"] is True
        assert a["right_reaction"] == "Fixed"
        assert result["summary"]["any_fixed"] is True

    def test_asymmetric_sizes(self):
        """Unequal pupil sizes should flag asymmetric."""
        text = (
            "Size R Pupil (mm): 5\n"
            "Size L Pupil (mm): 3\n"
            "Reaction R Pupil: Brisk\n"
            "Reaction L Pupil: Brisk\n"
            "Motor: Normal\n"
        )
        result, _ = extract_pupil_reactivity_for_day(
            [_make_item(text)], "2026-01-01",
        )
        a = result["assessments"][0]
        assert a["abnormal"] is True
        assert result["summary"]["any_asymmetric"] is True


# ── Prose pattern extraction ─────────────────────────────────────────

class TestProseExtraction:
    def test_perrl(self):
        """PERRL should produce bilateral Brisk, not abnormal."""
        text = "HEENT:  Head atraumatic. PERRL. Sclera anicteric."
        result, _ = extract_pupil_reactivity_for_day(
            [_make_item(text, "TRAUMA_HP")], "2026-01-01",
        )
        assert len(result["assessments"]) == 1
        a = result["assessments"][0]
        assert a["right_reaction"] == "Brisk"
        assert a["left_reaction"] == "Brisk"
        assert a["source_type"] == "PROSE"
        assert a["abnormal"] is False

    def test_perrla(self):
        """PERRLA variant should also match."""
        text = "Eyes: PERRLA, no nystagmus."
        result, _ = extract_pupil_reactivity_for_day(
            [_make_item(text, "PHYSICIAN_NOTE")], "2026-01-01",
        )
        assert len(result["assessments"]) == 1
        assert result["assessments"][0]["abnormal"] is False

    def test_pupils_equal_round_reactive(self):
        """Anna_Dennis style: 'Pupils equal in size, round, and reactive to light bilaterally'."""
        text = "Cranial Nerves: Pupils equal in size, round, and reactive to light bilaterally."
        result, _ = extract_pupil_reactivity_for_day(
            [_make_item(text, "PHYSICIAN_NOTE")], "2026-01-01",
        )
        assert len(result["assessments"]) == 1
        a = result["assessments"][0]
        assert a["right_reaction"] == "Brisk"
        assert a["left_reaction"] == "Brisk"
        assert a["abnormal"] is False

    def test_pupils_symmetric_briskly_reactive(self):
        """'pupils are symmetric and briskly reactive'."""
        text = "Cranial nerves:  The pupils are symmetric and briskly reactive."
        result, _ = extract_pupil_reactivity_for_day(
            [_make_item(text, "PHYSICIAN_NOTE")], "2026-01-01",
        )
        assert len(result["assessments"]) == 1
        assert result["assessments"][0]["abnormal"] is False

    def test_pinpoint_pupils(self):
        """Timothy_Nachtwey: 'pinpoint pupils / nonreactive'."""
        text = "HEENT:  NC/AT, pinpoint pupils / nonreactive.  ETT, OG in place."
        result, _ = extract_pupil_reactivity_for_day(
            [_make_item(text, "TRAUMA_HP")], "2026-01-01",
        )
        # Should match pinpoint (checked first)
        assert len(result["assessments"]) >= 1
        a = result["assessments"][0]
        assert a["right_size_mm"] == 1.0
        assert a["left_size_mm"] == 1.0
        assert a["abnormal"] is True

    def test_bilateral_pinpoint(self):
        """'Bilateral pinpoint pupils'."""
        text = "   Comments: Bilateral pinpoint pupils "
        result, _ = extract_pupil_reactivity_for_day(
            [_make_item(text, "NURSING_NOTE")], "2026-01-01",
        )
        assert len(result["assessments"]) == 1
        a = result["assessments"][0]
        assert a["abnormal"] is True

    def test_fixed_and_dilated(self):
        """'Fixed and dilated pupils'."""
        text = "NEUROLOGIC:  Unresponsive.  Fixed and dilated pupils."
        result, _ = extract_pupil_reactivity_for_day(
            [_make_item(text, "PHYSICIAN_NOTE")], "2026-01-01",
        )
        assert len(result["assessments"]) == 1
        a = result["assessments"][0]
        assert a["right_reaction"] == "Fixed"
        assert a["left_reaction"] == "Fixed"
        assert a["abnormal"] is True
        assert result["summary"]["any_fixed"] is True

    def test_pupils_mm_and_fixed(self):
        """'Pupils now 4 mm and fixed'."""
        text = "Mentation has worsened.  Pupils now 4 mm and fixed."
        result, _ = extract_pupil_reactivity_for_day(
            [_make_item(text, "PHYSICIAN_NOTE")], "2026-01-01",
        )
        assert len(result["assessments"]) == 1
        a = result["assessments"][0]
        assert a["right_size_mm"] == 4.0
        assert a["left_size_mm"] == 4.0
        assert a["right_reaction"] == "Fixed"
        assert a["abnormal"] is True

    def test_pupils_6mm_and_fixed(self):
        """'Pupils 6mm and fixed' — dilated + fixed."""
        text = "Cranial Nerves: Pupils 6mm and fixed, gaze dysconjugate."
        result, _ = extract_pupil_reactivity_for_day(
            [_make_item(text, "PHYSICIAN_NOTE")], "2026-01-01",
        )
        assert len(result["assessments"]) == 1
        a = result["assessments"][0]
        assert a["right_size_mm"] == 6.0
        assert a["abnormal"] is True

    def test_pupils_sluggish(self):
        """'pupils sluggish'."""
        text = "Intubated, gag present, pupils sluggish, withdraws from pain."
        result, _ = extract_pupil_reactivity_for_day(
            [_make_item(text, "NURSING_NOTE")], "2026-01-01",
        )
        assert len(result["assessments"]) == 1
        a = result["assessments"][0]
        assert a["right_reaction"] == "Sluggish"
        assert a["left_reaction"] == "Sluggish"
        assert a["abnormal"] is False  # Sluggish alone is not abnormal

    def test_pupils_nonreactive(self):
        """'pupils nonreactive'."""
        text = "Neuro: fixed gaze, pupils nonreactive bilaterally."
        result, _ = extract_pupil_reactivity_for_day(
            [_make_item(text, "PHYSICIAN_NOTE")], "2026-01-01",
        )
        assert len(result["assessments"]) == 1
        a = result["assessments"][0]
        assert a["right_reaction"] == "Nonreactive"
        assert a["left_reaction"] == "Nonreactive"
        assert a["abnormal"] is True


# ── Edge cases / fail-closed ─────────────────────────────────────────

class TestEdgeCases:
    def test_no_items(self):
        """Empty items list should produce empty assessments."""
        result, warnings = extract_pupil_reactivity_for_day([], "2026-01-01")
        assert result["assessments"] == []
        assert result["summary"]["total_assessments"] == 0
        assert result["summary"]["any_abnormal"] is False
        assert result["summary"]["any_fixed"] is False

    def test_unknown_source_type_ignored(self):
        """Items with unrecognized source types should be skipped."""
        text = "Size R Pupil (mm): 3\nReaction R Pupil: Brisk\nDone.\n"
        result, _ = extract_pupil_reactivity_for_day(
            [_make_item(text, "UNKNOWN_SOURCE")], "2026-01-01",
        )
        assert result["assessments"] == []

    def test_no_pupil_content(self):
        """Items without pupil content should produce empty assessments."""
        text = "BP: 120/80\nHR: 72\nRR: 16\nSpO2: 98%\n"
        result, _ = extract_pupil_reactivity_for_day(
            [_make_item(text, "FLOWSHEET")], "2026-01-01",
        )
        assert result["assessments"] == []

    def test_empty_text(self):
        """Items with empty text should produce empty assessments."""
        item = {"type": "FLOWSHEET", "dt": "2026-01-01T12:00:00",
                "source_id": "test", "payload": {"text": ""}}
        result, _ = extract_pupil_reactivity_for_day([item], "2026-01-01")
        assert result["assessments"] == []

    def test_pupil_mention_without_matching_pattern(self):
        """'pupil and GCS changes' should not match any pattern."""
        text = "Noted pupil and GCS changes overnight."
        result, _ = extract_pupil_reactivity_for_day(
            [_make_item(text, "NURSING_NOTE")], "2026-01-01",
        )
        assert result["assessments"] == []

    def test_multiple_items_same_day(self):
        """Multiple items on same day should all be processed."""
        items = [
            _make_item("PERRL noted.", "TRAUMA_HP", "2026-01-01T08:00:00"),
            _make_item(
                "Size R Pupil (mm): 4\nSize L Pupil (mm): 4\n"
                "Reaction R Pupil: Brisk\nReaction L Pupil: Brisk\nDone.\n",
                "FLOWSHEET", "2026-01-01T14:00:00",
            ),
        ]
        result, _ = extract_pupil_reactivity_for_day(items, "2026-01-01")
        assert result["summary"]["total_assessments"] == 2


# ── Summary logic ────────────────────────────────────────────────────

class TestSummary:
    def test_summary_all_normal(self):
        text = (
            "Size R Pupil (mm): 3\n"
            "Size L Pupil (mm): 3\n"
            "Reaction R Pupil: Brisk\n"
            "Reaction L Pupil: Brisk\n"
            "Done.\n"
        )
        result, _ = extract_pupil_reactivity_for_day(
            [_make_item(text)], "2026-01-01",
        )
        s = result["summary"]
        assert s["total_assessments"] == 1
        assert s["any_abnormal"] is False
        assert s["any_fixed"] is False
        assert s["any_asymmetric"] is False

    def test_summary_with_abnormal(self):
        items = [
            _make_item("PERRL.", "TRAUMA_HP", "2026-01-01T08:00:00"),
            _make_item(
                "NEUROLOGIC: Fixed and dilated pupils.",
                "PHYSICIAN_NOTE", "2026-01-01T20:00:00",
            ),
        ]
        result, _ = extract_pupil_reactivity_for_day(items, "2026-01-01")
        s = result["summary"]
        assert s["total_assessments"] == 2
        assert s["any_abnormal"] is True
        assert s["any_fixed"] is True


# ── Raw line ID traceability ─────────────────────────────────────────

class TestRawLineId:
    def test_raw_line_id_present(self):
        text = "PERRL bilateral."
        result, _ = extract_pupil_reactivity_for_day(
            [_make_item(text, "TRAUMA_HP")], "2026-01-01",
        )
        assert len(result["assessments"]) == 1
        rid = result["assessments"][0]["raw_line_id"]
        assert isinstance(rid, str)
        assert len(rid) == 16  # SHA-256 truncated to 16 hex chars

    def test_raw_line_id_deterministic(self):
        text = "PERRL bilateral."
        r1, _ = extract_pupil_reactivity_for_day(
            [_make_item(text, "TRAUMA_HP")], "2026-01-01",
        )
        r2, _ = extract_pupil_reactivity_for_day(
            [_make_item(text, "TRAUMA_HP")], "2026-01-01",
        )
        assert r1["assessments"][0]["raw_line_id"] == r2["assessments"][0]["raw_line_id"]
