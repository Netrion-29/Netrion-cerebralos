#!/usr/bin/env python3
"""
Tests for BD arterial source validation — Tier 1 Metric #3.

Covers:
  - Arterial (ABG) detection from component name and source line
  - Venous (VBG) detection
  - Unknown specimen when no context present
  - category1_bd_validated field derivation
  - validation_failure_reason field derivation
  - Empty series handling
"""

import pytest

from cerebralos.features.base_deficit_monitoring_v1 import (
    _infer_specimen,
    _is_bd_component,
    _is_be_component,
    _validate_category1_bd,
    _empty_result,
    extract_base_deficit_monitoring,
)


# ── _infer_specimen tests ──────────────────────────────────────────

class TestInferSpecimen:
    """Test _infer_specimen classifies specimen source correctly."""

    def test_arterial_from_abg_in_component(self):
        assert _infer_specimen("Base Deficit, ABG", "") == "arterial"

    def test_arterial_from_abg_in_source_line(self):
        assert _infer_specimen("Base Deficit", "ABG 12/18/2025 2.6 Final") == "arterial"

    def test_arterial_from_arterial_keyword(self):
        assert _infer_specimen("Base Deficit", "arterial blood gas panel") == "arterial"

    def test_arterial_from_art_poc(self):
        assert _infer_specimen("Base Deficit, Art POC", "") == "arterial"

    def test_arterial_from_art_poc_in_line(self):
        assert _infer_specimen("Base Deficit", "Base Deficit, Art POC    3.0 High") == "arterial"

    def test_venous_from_vbg_in_component(self):
        assert _infer_specimen("Base Deficit, VBG", "") == "venous"

    def test_venous_from_vbg_in_source_line(self):
        assert _infer_specimen("Base Deficit", "VBG results: BD 2.6") == "venous"

    def test_venous_from_venous_keyword(self):
        assert _infer_specimen("Base Deficit", "venous blood gas panel") == "venous"

    def test_unknown_when_no_context(self):
        assert _infer_specimen("Base Deficit", "2.6 (H)  0  Final") == "unknown"

    def test_unknown_empty_source(self):
        assert _infer_specimen("Base Deficit", "") == "unknown"

    def test_arterial_takes_priority_over_venous(self):
        """If both arterial and venous context present, arterial wins
        (it's checked first)."""
        result = _infer_specimen("Base Deficit", "ABG VBG arterial venous")
        assert result == "arterial"


# ── _is_bd_component / _is_be_component tests ─────────────────────

class TestComponentDetection:
    def test_base_deficit_match(self):
        assert _is_bd_component("Base Deficit") is True

    def test_base_deficit_art_poc_match(self):
        assert _is_bd_component("Base Deficit, Art POC") is True

    def test_bd_abbreviation(self):
        assert _is_bd_component("BD") is True

    def test_base_excess(self):
        assert _is_be_component("Base Excess") is True

    def test_random_component_not_bd(self):
        assert _is_bd_component("Hemoglobin") is False

    def test_random_component_not_be(self):
        assert _is_be_component("INR") is False


# ── _validate_category1_bd tests ──────────────────────────────────

class TestValidateCategory1BD:
    def test_arterial_validated(self):
        initial = {"specimen": "arterial", "value": 5.0, "ts": "2025-12-18T10:00:00"}
        series = [initial]
        validated, reason = _validate_category1_bd(initial, series)
        assert validated is True
        assert reason is None

    def test_venous_not_validated(self):
        initial = {"specimen": "venous", "value": 5.0, "ts": "2025-12-18T10:00:00"}
        series = [initial]
        validated, reason = _validate_category1_bd(initial, series)
        assert validated is False
        assert "venous" in reason.lower()
        assert "VBG" in reason

    def test_unknown_not_validated(self):
        initial = {"specimen": "unknown", "value": 5.0, "ts": "2025-12-18T10:00:00"}
        series = [initial]
        validated, reason = _validate_category1_bd(initial, series)
        assert validated is False
        assert "not confirmed arterial" in reason

    def test_venous_with_later_arterial_noted(self):
        initial = {"specimen": "venous", "value": 5.0, "ts": "2025-12-18T10:00:00"}
        later = {"specimen": "arterial", "value": 4.0, "ts": "2025-12-18T12:00:00"}
        series = [initial, later]
        validated, reason = _validate_category1_bd(initial, series)
        assert validated is False
        assert "later arterial BD exists" in reason

    def test_unknown_with_later_arterial_noted(self):
        initial = {"specimen": "unknown", "value": 5.0, "ts": "2025-12-18T10:00:00"}
        later = {"specimen": "arterial", "value": 4.0, "ts": "2025-12-18T12:00:00"}
        series = [initial, later]
        validated, reason = _validate_category1_bd(initial, series)
        assert validated is False
        assert "later arterial BD exists" in reason


# ── _empty_result tests ───────────────────────────────────────────

class TestEmptyResult:
    def test_empty_result_has_validation_fields(self):
        result = _empty_result("DATA NOT AVAILABLE: no BD values found")
        assert result["category1_bd_validated"] is False
        assert result["validation_failure_reason"] is not None
        assert "DATA NOT AVAILABLE" in result["validation_failure_reason"]
        assert result["initial_bd_value"] is None


# ── Full extraction integration tests ──────────────────────────────

class TestExtractBDMonitoringValidation:
    """Integration tests for extract_base_deficit_monitoring with validation."""

    def _make_features_with_bd(self, series_entries, day_iso="2025-12-18"):
        """Helper to build a minimal pat_features dict with BD in series."""
        series = {}
        for entry in series_entries:
            comp = entry.get("component", "Base Deficit")
            if comp not in series:
                series[comp] = []
            series[comp].append({
                "observed_dt": entry.get("dt", f"{day_iso}T10:00:00"),
                "value_num": entry["value"],
                "value_raw": str(entry["value"]),
                "source_line": entry.get("source_line", ""),
                "flags": [],
            })
        return {
            "days": {
                day_iso: {
                    "labs": {
                        "series": series,
                        "daily": {},
                    },
                },
            },
        }

    def _make_days_json(self, day_iso="2025-12-18"):
        return {"days": {day_iso: {"items": []}}}

    def test_no_bd_values(self):
        pat = {"days": {"2025-12-18": {"labs": {"series": {}, "daily": {}}}}}
        days = {"days": {"2025-12-18": {"items": []}}}
        result = extract_base_deficit_monitoring(pat, days)
        assert result["category1_bd_validated"] is False
        assert result["validation_failure_reason"] is not None
        assert result["initial_bd_value"] is None

    def test_bd_arterial_via_abg_context(self):
        pat = self._make_features_with_bd([
            {"value": 5.2, "source_line": "ABG Base Deficit 5.2 Final"},
        ])
        result = extract_base_deficit_monitoring(pat, self._make_days_json())
        assert result["initial_bd_source"] == "arterial"
        assert result["category1_bd_validated"] is True
        assert result["validation_failure_reason"] is None

    def test_bd_venous_via_vbg_context(self):
        pat = self._make_features_with_bd([
            {"value": 3.0, "source_line": "VBG Base Deficit 3.0"},
        ])
        result = extract_base_deficit_monitoring(pat, self._make_days_json())
        assert result["initial_bd_source"] == "venous"
        assert result["category1_bd_validated"] is False
        assert "venous" in result["validation_failure_reason"].lower()

    def test_bd_unknown_specimen(self):
        pat = self._make_features_with_bd([
            {"value": 2.6, "source_line": "Base Deficit 2.6 (H) 0 Final"},
        ])
        result = extract_base_deficit_monitoring(pat, self._make_days_json())
        assert result["initial_bd_source"] == "unknown"
        assert result["category1_bd_validated"] is False
        assert "not confirmed arterial" in result["validation_failure_reason"]

    def test_art_poc_component_name_arterial(self):
        pat = self._make_features_with_bd([
            {
                "value": 3.0,
                "component": "Base Deficit, Art POC",
                "source_line": "Base Deficit, Art POC    3.0 High",
            },
        ])
        result = extract_base_deficit_monitoring(pat, self._make_days_json())
        assert result["initial_bd_source"] == "arterial"
        assert result["category1_bd_validated"] is True
