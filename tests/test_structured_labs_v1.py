#!/usr/bin/env python3
"""
Tests for structured_labs_v1 — Protocol Coverage Slice C foundation.

Covers:
  - CBC/BMP/Coag/ABG panel extraction with positives/negatives
  - Range-gate rejection (fail-closed)
  - P/F ratio computation (explicit PaO2 + FiO2 required)
  - raw_line_id determinism
  - Timestamp ordering within series
  - DATA NOT AVAILABLE propagation for missing components
"""

import pytest

from cerebralos.features.structured_labs_v1 import (
    _build_component_block,
    _build_panel,
    _compute_pf_ratio,
    _in_range,
    _make_raw_line_id,
    extract_structured_labs,
    _CBC_COMPONENTS,
    _BMP_COMPONENTS,
    _COAG_COMPONENTS,
    _ABG_COMPONENTS,
)

_DNA = "DATA NOT AVAILABLE"


# ── Helpers ─────────────────────────────────────────────────────────

def _make_series_entry(comp, dt, value, flags=None, source_line=1):
    """Build a minimal lab series entry."""
    return {
        "observed_dt": dt,
        "value_num": value,
        "value_raw": str(value),
        "flags": flags or [],
        "source_line": source_line,
    }


def _make_day_labs(series_dict):
    """Build a minimal day labs block."""
    return {"series": series_dict, "daily": {}, "latest": {}}


def _wrap_features(day_iso, series_dict):
    """Build minimal pat_features with one day."""
    return {
        "days": {
            day_iso: {
                "labs": _make_day_labs(series_dict),
            }
        }
    }


# ── raw_line_id tests ──────────────────────────────────────────────

class TestRawLineId:
    def test_deterministic(self):
        id1 = _make_raw_line_id("Hgb", "2025-12-18T10:00:00", 12.5, 100)
        id2 = _make_raw_line_id("Hgb", "2025-12-18T10:00:00", 12.5, 100)
        assert id1 == id2
        assert len(id1) == 16

    def test_different_inputs_differ(self):
        id1 = _make_raw_line_id("Hgb", "2025-12-18T10:00:00", 12.5, 100)
        id2 = _make_raw_line_id("Hgb", "2025-12-18T10:00:00", 12.6, 100)
        assert id1 != id2


# ── Range gate tests ──────────────────────────────────────────────

class TestRangeGates:
    def test_hgb_valid(self):
        assert _in_range("Hgb", 12.5) is True

    def test_hgb_below_min(self):
        assert _in_range("Hgb", 0.5) is False

    def test_hgb_above_max(self):
        assert _in_range("Hgb", 35.0) is False

    def test_inr_valid(self):
        assert _in_range("INR", 1.1) is True

    def test_inr_too_low(self):
        assert _in_range("INR", 0.3) is False

    def test_ph_valid(self):
        assert _in_range("pH", 7.35) is True

    def test_ph_too_high(self):
        assert _in_range("pH", 8.5) is False

    def test_unknown_component_always_valid(self):
        assert _in_range("UnknownComp", 999.0) is True

    def test_glucose_boundary_valid(self):
        assert _in_range("Glucose", 10.0) is True
        assert _in_range("Glucose", 2000.0) is True

    def test_glucose_boundary_invalid(self):
        assert _in_range("Glucose", 9.9) is False
        assert _in_range("Glucose", 2001.0) is False


# ── Component block tests ──────────────────────────────────────────

class TestBuildComponentBlock:
    def test_single_value(self):
        series = {
            "Hemoglobin": [_make_series_entry("Hemoglobin", "2025-12-18T10:00:00", 12.5)],
        }
        block = _build_component_block("Hgb", series, ["Hemoglobin", "HGB"])
        assert block["status"] == "available"
        assert block["first"] == 12.5
        assert block["last"] == 12.5
        assert block["n_values"] == 1
        assert block["delta"] == 0.0
        assert len(block["series"]) == 1
        assert "raw_line_id" in block["series"][0]

    def test_multiple_values_delta(self):
        series = {
            "HGB": [
                _make_series_entry("HGB", "2025-12-18T06:00:00", 12.7, source_line=10),
                _make_series_entry("HGB", "2025-12-18T14:00:00", 10.8, flags=["L"], source_line=20),
            ],
        }
        block = _build_component_block("Hgb", series, ["Hemoglobin", "HGB"])
        assert block["status"] == "available"
        assert block["first"] == 12.7
        assert block["last"] == 10.8
        assert block["delta"] == pytest.approx(-1.9, abs=0.01)
        assert block["n_values"] == 2
        assert block["abnormal"] is True

    def test_empty_series(self):
        block = _build_component_block("Hgb", {}, ["Hemoglobin", "HGB"])
        assert block["status"] == _DNA

    def test_no_numeric_values(self):
        series = {
            "Hemoglobin": [{"observed_dt": "2025-12-18T10:00:00", "value_num": None, "flags": []}],
        }
        block = _build_component_block("Hgb", series, ["Hemoglobin"])
        assert block["status"] == _DNA

    def test_out_of_range_rejected(self):
        series = {
            "Hemoglobin": [_make_series_entry("Hemoglobin", "2025-12-18T10:00:00", 50.0)],
        }
        block = _build_component_block("Hgb", series, ["Hemoglobin"])
        assert block["status"] == _DNA

    def test_case_insensitive_matching(self):
        series = {
            "hemoglobin": [_make_series_entry("hemoglobin", "2025-12-18T10:00:00", 14.0)],
        }
        block = _build_component_block("Hgb", series, ["Hemoglobin", "HGB"])
        assert block["status"] == "available"
        assert block["first"] == 14.0

    def test_series_ordered_by_timestamp(self):
        series = {
            "WBC": [
                _make_series_entry("WBC", "2025-12-18T14:00:00", 8.0, source_line=20),
                _make_series_entry("WBC", "2025-12-18T06:00:00", 12.0, source_line=10),
            ],
        }
        block = _build_component_block("WBC", series, ["WBC"])
        assert block["series"][0]["value"] == 12.0  # earlier first
        assert block["series"][1]["value"] == 8.0   # later second


# ── Panel tests ────────────────────────────────────────────────────

class TestBuildPanel:
    def test_cbc_complete(self):
        series = {
            "White Blood Cell Count": [_make_series_entry("WBC", "2025-12-18T10:00:00", 25.2, ["H"])],
            "Hemoglobin": [_make_series_entry("Hgb", "2025-12-18T10:00:00", 12.7, ["L"])],
            "Hematocrit": [_make_series_entry("Hct", "2025-12-18T10:00:00", 39.4)],
            "Platelet Count": [_make_series_entry("Plt", "2025-12-18T10:00:00", 271.0)],
        }
        panel = _build_panel(_CBC_COMPONENTS, series, "2025-12-18")
        assert panel["complete"] is True
        assert panel["available_count"] == 4
        assert panel["total_count"] == 4
        assert panel["components"]["WBC"]["status"] == "available"
        assert panel["components"]["Hgb"]["status"] == "available"

    def test_cbc_partial(self):
        series = {
            "WBC": [_make_series_entry("WBC", "2025-12-18T10:00:00", 8.0)],
        }
        panel = _build_panel(_CBC_COMPONENTS, series, "2025-12-18")
        assert panel["complete"] is False
        assert panel["available_count"] == 1
        assert panel["components"]["WBC"]["status"] == "available"
        assert panel["components"]["Hgb"]["status"] == _DNA
        assert panel["components"]["Plt"]["status"] == _DNA

    def test_bmp_complete(self):
        series = {
            "Sodium": [_make_series_entry("Na", "2025-12-18T10:00:00", 133.0, ["L"])],
            "Potassium": [_make_series_entry("K", "2025-12-18T10:00:00", 4.8)],
            "Chloride": [_make_series_entry("Cl", "2025-12-18T10:00:00", 98.0)],
            "Co2": [_make_series_entry("CO2", "2025-12-18T10:00:00", 20.0)],
            "Blood Urea Nitrogen": [_make_series_entry("BUN", "2025-12-18T10:00:00", 12.0)],
            "Creatinine": [_make_series_entry("Cr", "2025-12-18T10:00:00", 1.2)],
            "Glucose": [_make_series_entry("Glucose", "2025-12-18T10:00:00", 364.0, ["H"])],
        }
        panel = _build_panel(_BMP_COMPONENTS, series, "2025-12-18")
        assert panel["complete"] is True
        assert panel["available_count"] == 7

    def test_coag_panel(self):
        series = {
            "PROTIME": [_make_series_entry("PT", "2025-12-18T10:00:00", 11.9)],
            "INR": [_make_series_entry("INR", "2025-12-18T10:00:00", 1.1)],
            "APTT": [_make_series_entry("PTT", "2025-12-18T10:00:00", 25.6)],
        }
        panel = _build_panel(_COAG_COMPONENTS, series, "2025-12-18")
        assert panel["available_count"] == 3
        # Fibrinogen missing -> not complete
        assert panel["complete"] is False
        assert panel["components"]["Fibrinogen"]["status"] == _DNA

    def test_abg_panel(self):
        series = {
            "pH Arterial": [_make_series_entry("pH", "2025-12-18T10:00:00", 7.34)],
            "pCO2 Arterial": [_make_series_entry("pCO2", "2025-12-18T10:00:00", 40.6)],
            "Po2 Arterial": [_make_series_entry("pO2", "2025-12-18T10:00:00", 65.3, ["L"])],
            "Base Deficit": [_make_series_entry("BD", "2025-12-18T10:00:00", 2.6, ["H"])],
            "Lactate": [_make_series_entry("Lactate", "2025-12-18T10:00:00", 1.8)],
        }
        panel = _build_panel(_ABG_COMPONENTS, series, "2025-12-18")
        assert panel["complete"] is True
        assert panel["available_count"] == 5

    def test_empty_panel(self):
        panel = _build_panel(_CBC_COMPONENTS, {}, "2025-12-18")
        assert panel["complete"] is False
        assert panel["available_count"] == 0
        assert panel["total_count"] == 4


# ── P/F ratio tests ────────────────────────────────────────────────

class TestPFRatio:
    def _make_abg_with_po2(self, po2_value, dt="2025-12-18T10:00:00"):
        series = {
            "Po2 Arterial": [_make_series_entry("pO2", dt, po2_value)],
        }
        return _build_panel(_ABG_COMPONENTS, series, "2025-12-18"), series

    def test_pf_with_explicit_fio2(self):
        abg, series = self._make_abg_with_po2(434.0)
        series["FIO2"] = [_make_series_entry("FIO2", "2025-12-18T10:00:00", 30.0)]
        result = _compute_pf_ratio(abg, series, "2025-12-18")
        assert result["status"] == "available"
        assert result["pf_ratio"] == pytest.approx(434.0 / 0.30, abs=0.1)
        assert result["fio2"] == 0.30
        assert result["pao2"] == 434.0

    def test_pf_no_po2(self):
        series = {}
        abg = _build_panel(_ABG_COMPONENTS, series, "2025-12-18")
        result = _compute_pf_ratio(abg, series, "2025-12-18")
        assert result["status"] == _DNA
        assert result["reason"] == "pO2_not_available"

    def test_pf_no_fio2(self):
        abg, series = self._make_abg_with_po2(100.0)
        result = _compute_pf_ratio(abg, series, "2025-12-18")
        assert result["status"] == _DNA
        assert result["reason"] == "fio2_not_available"

    def test_pf_fio2_percentage_normalized(self):
        """FiO2 given as 100 (percent) should be normalized to 1.0."""
        abg, series = self._make_abg_with_po2(434.0)
        series["FIO2"] = [_make_series_entry("FIO2", "2025-12-18T10:00:00", 100.0)]
        result = _compute_pf_ratio(abg, series, "2025-12-18")
        assert result["status"] == "available"
        assert result["fio2"] == 1.0
        assert result["pf_ratio"] == pytest.approx(434.0, abs=0.1)

    def test_pf_has_raw_line_id(self):
        abg, series = self._make_abg_with_po2(100.0)
        series["FIO2"] = [_make_series_entry("FIO2", "2025-12-18T10:00:00", 40.0)]
        result = _compute_pf_ratio(abg, series, "2025-12-18")
        assert result["status"] == "available"
        assert "raw_line_id" in result
        assert len(result["raw_line_id"]) == 16


# ── Integration tests (extract_structured_labs) ────────────────────

class TestExtractStructuredLabs:
    def test_basic_extraction(self):
        features = _wrap_features("2025-12-18", {
            "WBC": [_make_series_entry("WBC", "2025-12-18T10:00:00", 25.2)],
            "Hemoglobin": [_make_series_entry("Hgb", "2025-12-18T10:00:00", 12.7)],
            "Hematocrit": [_make_series_entry("Hct", "2025-12-18T10:00:00", 39.4)],
            "Platelet Count": [_make_series_entry("Plt", "2025-12-18T10:00:00", 271.0)],
        })
        result = extract_structured_labs(features)
        assert result["summary"]["days_with_labs"] == 1
        day_data = result["panels_by_day"]["2025-12-18"]
        assert day_data["cbc"]["complete"] is True

    def test_multi_day(self):
        features = {
            "days": {
                "2025-12-18": {
                    "labs": _make_day_labs({
                        "WBC": [_make_series_entry("WBC", "2025-12-18T10:00:00", 25.2)],
                    }),
                },
                "2025-12-19": {
                    "labs": _make_day_labs({
                        "WBC": [_make_series_entry("WBC", "2025-12-19T10:00:00", 18.5)],
                        "Sodium": [_make_series_entry("Na", "2025-12-19T10:00:00", 140.0)],
                    }),
                },
            }
        }
        result = extract_structured_labs(features)
        assert result["summary"]["days_with_labs"] == 2
        assert "2025-12-18" in result["panels_by_day"]
        assert "2025-12-19" in result["panels_by_day"]

    def test_undated_skipped(self):
        features = {
            "days": {
                "__UNDATED__": {
                    "labs": _make_day_labs({
                        "WBC": [_make_series_entry("WBC", None, 10.0)],
                    }),
                },
            }
        }
        result = extract_structured_labs(features)
        assert result["summary"]["days_with_labs"] == 0
        assert "__UNDATED__" not in result["panels_by_day"]

    def test_empty_days(self):
        result = extract_structured_labs({"days": {}})
        assert result["summary"]["days_with_labs"] == 0
        assert result["panels_by_day"] == {}

    def test_no_labs_in_day(self):
        features = {"days": {"2025-12-18": {"labs": {"series": {}, "daily": {}}}}}
        result = extract_structured_labs(features)
        assert result["summary"]["days_with_labs"] == 0

    def test_pf_ratio_summary(self):
        features = _wrap_features("2025-12-18", {
            "Po2 Arterial": [_make_series_entry("pO2", "2025-12-18T10:00:00", 434.0)],
            "FIO2": [_make_series_entry("FIO2", "2025-12-18T10:00:00", 30.0)],
        })
        result = extract_structured_labs(features)
        assert result["summary"]["pf_available_count"] == 1
        pf = result["panels_by_day"]["2025-12-18"]["pf_ratio"]
        assert pf["status"] == "available"

    def test_all_series_have_raw_line_id(self):
        """Every series entry must have raw_line_id for traceability."""
        features = _wrap_features("2025-12-18", {
            "WBC": [
                _make_series_entry("WBC", "2025-12-18T06:00:00", 12.0),
                _make_series_entry("WBC", "2025-12-18T14:00:00", 8.0),
            ],
            "Sodium": [_make_series_entry("Na", "2025-12-18T10:00:00", 140.0)],
            "INR": [_make_series_entry("INR", "2025-12-18T10:00:00", 1.1)],
            "pH Arterial": [_make_series_entry("pH", "2025-12-18T10:00:00", 7.35)],
        })
        result = extract_structured_labs(features)
        day_data = result["panels_by_day"]["2025-12-18"]
        for panel_name in ("cbc", "bmp", "coag", "abg"):
            panel = day_data[panel_name]
            for comp_name, comp_data in panel["components"].items():
                if comp_data.get("status") == "available":
                    for entry in comp_data["series"]:
                        assert "raw_line_id" in entry, (
                            f"{panel_name}.{comp_name} series entry missing raw_line_id"
                        )
                        assert len(entry["raw_line_id"]) == 16


# ── False-positive control tests ──────────────────────────────────

class TestFalsePositiveControls:
    def test_negative_values_rejected_for_hgb(self):
        """Negative hemoglobin values should be rejected by range gate."""
        series = {
            "HGB": [_make_series_entry("HGB", "2025-12-18T10:00:00", -5.0)],
        }
        block = _build_component_block("Hgb", series, ["Hemoglobin", "HGB"])
        assert block["status"] == _DNA

    def test_extreme_glucose_rejected(self):
        """Glucose > 2000 should be rejected."""
        series = {
            "Glucose": [_make_series_entry("Glucose", "2025-12-18T10:00:00", 5000.0)],
        }
        block = _build_component_block("Glucose", series, ["Glucose"])
        assert block["status"] == _DNA

    def test_ph_out_of_range_rejected(self):
        """pH values outside 6.5-8.0 should be rejected."""
        series = {
            "pH Arterial": [_make_series_entry("pH", "2025-12-18T10:00:00", 14.0)],
        }
        block = _build_component_block("pH", series, ["pH Arterial"])
        assert block["status"] == _DNA

    def test_partial_out_of_range_keeps_valid(self):
        """If one value is out of range but another is valid, keep the valid one."""
        series = {
            "HGB": [
                _make_series_entry("HGB", "2025-12-18T06:00:00", 50.0, source_line=1),
                _make_series_entry("HGB", "2025-12-18T10:00:00", 12.0, source_line=2),
            ],
        }
        block = _build_component_block("Hgb", series, ["HGB"])
        assert block["status"] == "available"
        assert block["n_values"] == 1
        assert block["first"] == 12.0
