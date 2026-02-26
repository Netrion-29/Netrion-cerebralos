#!/usr/bin/env python3
"""
Tests for category_activation_v1 — Trauma Category Detection.

Covers:
  - Source 1: evidence meta header detection
  - Source 2: note-body TRAUMA CATEGORY field detection
  - Source 3: regex-based activation text scan (original v1)
  - Detection cascade priority
  - Category I / II normalisation
  - Fail-closed behaviour
  - Determinism
  - v5 rendering of category line
"""

from __future__ import annotations

import pytest

from cerebralos.features.category_activation_v1 import build_category_activation_v1


# ── Helpers ─────────────────────────────────────────────────────────

def _make_days_json(
    items_text_lines=None,
    evidence_trauma_category=None,
    day="2025-12-31",
    source_id="CONSULT_NOTE",
    item_dt="2025-12-31 15:00:00",
):
    """Build a minimal days_json dict for testing."""
    meta = {}
    if evidence_trauma_category is not None:
        meta["evidence_trauma_category"] = evidence_trauma_category

    items = []
    if items_text_lines:
        text = "\n".join(items_text_lines)
        items.append({
            "dt": item_dt,
            "source_id": source_id,
            "payload": {"text": text},
        })

    return {
        "meta": meta,
        "days": {
            day: {"items": items},
        },
    }


# ════════════════════════════════════════════════════════════════════
# Source 1: Evidence Meta Header
# ════════════════════════════════════════════════════════════════════


class TestEvidenceMetaHeader:

    def test_category_1_from_header(self):
        dj = _make_days_json(evidence_trauma_category="1")
        result = build_category_activation_v1(dj)
        assert result["detected"] is True
        assert result["category"] == "I"
        assert result["source_rule_id"] == "evidence_meta_header"

    def test_category_2_from_header(self):
        dj = _make_days_json(evidence_trauma_category="2")
        result = build_category_activation_v1(dj)
        assert result["detected"] is True
        assert result["category"] == "II"
        assert result["source_rule_id"] == "evidence_meta_header"

    def test_category_I_roman_from_header(self):
        dj = _make_days_json(evidence_trauma_category="I")
        result = build_category_activation_v1(dj)
        assert result["detected"] is True
        assert result["category"] == "I"

    def test_category_II_roman_from_header(self):
        dj = _make_days_json(evidence_trauma_category="II")
        result = build_category_activation_v1(dj)
        assert result["detected"] is True
        assert result["category"] == "II"

    def test_dna_header_skipped(self):
        dj = _make_days_json(evidence_trauma_category="DATA_NOT_AVAILABLE")
        result = build_category_activation_v1(dj)
        # Should NOT detect from DNA value
        assert result["source_rule_id"] != "evidence_meta_header"

    def test_empty_header_skipped(self):
        dj = _make_days_json(evidence_trauma_category="")
        result = build_category_activation_v1(dj)
        assert result["source_rule_id"] != "evidence_meta_header"

    def test_evidence_list_has_raw_line_id(self):
        dj = _make_days_json(evidence_trauma_category="1")
        result = build_category_activation_v1(dj)
        assert len(result["evidence"]) == 1
        assert "raw_line_id" in result["evidence"][0]
        assert len(result["evidence"][0]["raw_line_id"]) == 16


# ════════════════════════════════════════════════════════════════════
# Source 2: Note Body TRAUMA CATEGORY Field
# ════════════════════════════════════════════════════════════════════


class TestNoteBodyField:

    def test_trauma_category_2_in_note(self):
        dj = _make_days_json(items_text_lines=[
            "Trauma consult Note",
            "TRAUMA CATEGORY: 2",
            "ACTIVATION TIME: 1533",
        ])
        result = build_category_activation_v1(dj)
        assert result["detected"] is True
        assert result["category"] == "II"
        assert result["source_rule_id"] == "note_body_trauma_category_field"

    def test_trauma_category_1_in_note(self):
        dj = _make_days_json(items_text_lines=[
            "TRAUMA CATEGORY: 1",
            "Some other text",
        ])
        result = build_category_activation_v1(dj)
        assert result["detected"] is True
        assert result["category"] == "I"
        assert result["source_rule_id"] == "note_body_trauma_category_field"

    def test_underscore_variant(self):
        dj = _make_days_json(items_text_lines=[
            "TRAUMA_CATEGORY: 2",
        ])
        result = build_category_activation_v1(dj)
        assert result["detected"] is True
        assert result["category"] == "II"

    def test_lowercase_trauma_category(self):
        dj = _make_days_json(items_text_lines=[
            "trauma category: 1",
        ])
        result = build_category_activation_v1(dj)
        assert result["detected"] is True
        assert result["category"] == "I"

    def test_category_n_trauma_activation_prose(self):
        """Prose form: 'category 2 trauma activation'"""
        dj = _make_days_json(items_text_lines=[
            "Patient has made a category 2 trauma activation to Trauma Services.",
        ])
        result = build_category_activation_v1(dj)
        assert result["detected"] is True
        assert result["category"] == "II"
        assert result["source_rule_id"] == "note_body_trauma_category_field"

    def test_category_1_trauma_activation_prose(self):
        dj = _make_days_json(items_text_lines=[
            "This is a category 1 trauma activation.",
        ])
        result = build_category_activation_v1(dj)
        assert result["detected"] is True
        assert result["category"] == "I"

    def test_category_ii_alert_prose(self):
        """Alert history format: 'Category II alert at 0143'"""
        dj = _make_days_json(items_text_lines=[
            "Alert History: Category II alert at 0143. Patient evaluated in the ED.",
        ])
        result = build_category_activation_v1(dj)
        assert result["detected"] is True
        assert result["category"] == "II"
        assert result["source_rule_id"] == "note_body_trauma_category_field"

    def test_category_2_alert_prose(self):
        """Numeric category alert: 'Category 2 alert at 1743'"""
        dj = _make_days_json(items_text_lines=[
            "Category 2 alert at 1743.",
        ])
        result = build_category_activation_v1(dj)
        assert result["detected"] is True
        assert result["category"] == "II"

    def test_category_2_trauma_activated_prose(self):
        """Activated variant: 'category 2 trauma was activated'"""
        dj = _make_days_json(items_text_lines=[
            "a category 2 trauma was activated as patient was transferred.",
        ])
        result = build_category_activation_v1(dj)
        assert result["detected"] is True
        assert result["category"] == "II"

    def test_evidence_has_raw_line_id(self):
        dj = _make_days_json(items_text_lines=["TRAUMA CATEGORY: 2"])
        result = build_category_activation_v1(dj)
        assert len(result["evidence"]) == 1
        assert "raw_line_id" in result["evidence"][0]
        assert len(result["evidence"][0]["raw_line_id"]) == 16

    def test_evidence_has_ts(self):
        dj = _make_days_json(
            items_text_lines=["TRAUMA CATEGORY: 1"],
            item_dt="2025-12-31 15:44:00",
        )
        result = build_category_activation_v1(dj)
        assert result["evidence"][0]["ts"] == "2025-12-31 15:44:00"


# ════════════════════════════════════════════════════════════════════
# Source 3: Regex-Based Activation Text Scan
# ════════════════════════════════════════════════════════════════════


class TestActivationRegexScan:

    def test_category_i_activation_detected(self):
        dj = _make_days_json(items_text_lines=[
            "Patient is a Category I trauma activation.",
        ])
        result = build_category_activation_v1(dj)
        assert result["detected"] is True
        assert result["category"] == "I"
        # Now caught by Source 2 prose pattern (higher priority than Source 3)
        assert result["source_rule_id"] == "note_body_trauma_category_field"

    def test_cat_i_activation_variant(self):
        dj = _make_days_json(items_text_lines=[
            "Cat I activation noted",
        ])
        result = build_category_activation_v1(dj)
        assert result["detected"] is True
        assert result["category"] == "I"

    def test_ambiguous_line_fails_closed(self):
        dj = _make_days_json(items_text_lines=[
            "Category I and Category II discussed",
        ])
        result = build_category_activation_v1(dj)
        assert result["detected"] is False
        assert "AMBIGUOUS_CAT_I_CAT_II_SAME_LINE" in result["notes"]


# ════════════════════════════════════════════════════════════════════
# Detection Cascade Priority
# ════════════════════════════════════════════════════════════════════


class TestCascadePriority:

    def test_meta_header_beats_note_body(self):
        """Evidence meta header should take priority over note body."""
        dj = _make_days_json(
            evidence_trauma_category="1",
            items_text_lines=["TRAUMA CATEGORY: 2"],
        )
        result = build_category_activation_v1(dj)
        assert result["category"] == "I"
        assert result["source_rule_id"] == "evidence_meta_header"

    def test_note_body_beats_activation_regex(self):
        """Note body field should take priority over activation regex."""
        dj = _make_days_json(items_text_lines=[
            "TRAUMA CATEGORY: 2",
            "Category I trauma activation",
        ])
        result = build_category_activation_v1(dj)
        assert result["category"] == "II"
        assert result["source_rule_id"] == "note_body_trauma_category_field"


# ════════════════════════════════════════════════════════════════════
# Fail-Closed / Not Detected
# ════════════════════════════════════════════════════════════════════


class TestFailClosed:

    def test_no_data_not_detected(self):
        dj = {"meta": {}, "days": {}}
        result = build_category_activation_v1(dj)
        assert result["detected"] is False
        assert result["category"] is None
        assert result["source_rule_id"] == "not_detected"

    def test_empty_items_not_detected(self):
        dj = _make_days_json(items_text_lines=["Regular clinical note content."])
        result = build_category_activation_v1(dj)
        assert result["detected"] is False
        assert result["source_rule_id"] == "not_detected"

    def test_invalid_category_value_not_detected(self):
        dj = _make_days_json(evidence_trauma_category="XYZ")
        result = build_category_activation_v1(dj)
        assert result["source_rule_id"] != "evidence_meta_header"

    def test_unknown_numeric_category_ignored(self):
        """Category 3 or higher is not normalised."""
        dj = _make_days_json(items_text_lines=["TRAUMA CATEGORY: 3"])
        result = build_category_activation_v1(dj)
        # Source 2 should not match because _normalize_category("3") is None
        assert result["source_rule_id"] != "note_body_trauma_category_field"

    def test_method_always_present(self):
        dj = {"meta": {}, "days": {}}
        result = build_category_activation_v1(dj)
        assert "method" in result

    def test_notes_always_list(self):
        dj = {"meta": {}, "days": {}}
        result = build_category_activation_v1(dj)
        assert isinstance(result["notes"], list)


# ════════════════════════════════════════════════════════════════════
# Determinism
# ════════════════════════════════════════════════════════════════════


class TestDeterminism:

    def test_repeated_calls_identical(self):
        dj = _make_days_json(
            evidence_trauma_category="1",
            items_text_lines=["TRAUMA CATEGORY: 2"],
        )
        r1 = build_category_activation_v1(dj)
        r2 = build_category_activation_v1(dj)
        assert r1 == r2

    def test_note_body_deterministic_across_runs(self):
        dj = _make_days_json(items_text_lines=[
            "Some preamble",
            "TRAUMA CATEGORY: 2",
            "More text",
        ])
        results = [build_category_activation_v1(dj) for _ in range(5)]
        assert all(r == results[0] for r in results)


# ════════════════════════════════════════════════════════════════════
# v5 Category Rendering
# ════════════════════════════════════════════════════════════════════


class TestV5CategoryRendering:
    """Test that the v5 renderer produces correct category display lines."""

    def _render_patient_summary_category(self, cat_feature):
        """
        Simulate the v5 renderer's category display logic.
        (Extracted from render_trauma_daily_notes_v5.py patient summary block.)
        """
        _DNA = "DATA_NOT_AVAILABLE"
        if cat_feature.get("detected"):
            cat_label = cat_feature.get("category", "I")
            return f"  Category:         {cat_label}"
        elif cat_feature:
            return f"  Category:         Not detected"
        else:
            return f"  Category:         {_DNA}"

    def test_category_i_display(self):
        feat = {"detected": True, "category": "I", "source_rule_id": "evidence_meta_header"}
        line = self._render_patient_summary_category(feat)
        assert "Category:" in line
        assert "I" in line
        assert "activation" not in line

    def test_category_ii_display(self):
        feat = {"detected": True, "category": "II", "source_rule_id": "note_body_trauma_category_field"}
        line = self._render_patient_summary_category(feat)
        assert "II" in line
        assert "Not detected" not in line

    def test_not_detected_display(self):
        feat = {"detected": False, "category": None, "source_rule_id": "not_detected"}
        line = self._render_patient_summary_category(feat)
        assert "Not detected" in line

    def test_dna_display_when_empty(self):
        line = self._render_patient_summary_category({})
        assert "DATA_NOT_AVAILABLE" in line

    def test_category_label_no_trailing_activation(self):
        """Old rendering appended 'activation' — new rendering should not."""
        feat = {"detected": True, "category": "I", "source_rule_id": "text_scan_activation_regex"}
        line = self._render_patient_summary_category(feat)
        assert line.strip().endswith("I")


# ════════════════════════════════════════════════════════════════════
# Schema Contract
# ════════════════════════════════════════════════════════════════════


class TestSchemaContract:

    def test_output_keys_detected(self):
        dj = _make_days_json(evidence_trauma_category="1")
        result = build_category_activation_v1(dj)
        expected_keys = {"detected", "category", "source_rule_id", "method", "evidence", "notes"}
        assert set(result.keys()) == expected_keys

    def test_output_keys_not_detected(self):
        dj = {"meta": {}, "days": {}}
        result = build_category_activation_v1(dj)
        expected_keys = {"detected", "category", "source_rule_id", "method", "evidence", "notes"}
        assert set(result.keys()) == expected_keys

    def test_source_rule_id_values(self):
        """source_rule_id must be one of the documented values."""
        valid_ids = {
            "evidence_meta_header",
            "note_body_trauma_category_field",
            "text_scan_activation_regex",
            "not_detected",
        }
        # Test each variant
        for tc, expected in [
            (_make_days_json(evidence_trauma_category="1"), "evidence_meta_header"),
            (_make_days_json(items_text_lines=["TRAUMA CATEGORY: 2"]), "note_body_trauma_category_field"),
            ({"meta": {}, "days": {}}, "not_detected"),
        ]:
            result = build_category_activation_v1(tc)
            assert result["source_rule_id"] in valid_ids
            assert result["source_rule_id"] == expected
