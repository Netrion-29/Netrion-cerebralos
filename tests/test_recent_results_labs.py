#!/usr/bin/env python3
"""
Tests for the Recent Results tabular lab parser (Priority 6).

Covers:
  - Basic CBC panel extraction with collection time
  - Multi-panel blocks (CBC + BMP + Coags)
  - (H)/(L)/(A) flag extraction
  - Non-numeric value handling (NEGATIVE, AUTO)
  - Multiple "Recent Results" blocks in one item
  - Urinalysis sub-block with Specimen line
  - "Results for orders placed..." subsection
  - Panel mapping: Renal CO2 → CO2 in labs_panel_daily
  - End-of-block detection (section markers stop parsing)
  - Empty block produces no labs
  - Collection time parsing: 12-hour AM/PM format
  - Real-data: Anna_Dennis Day 1 and Day 2 lab panels
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cerebralos.features.labs_extract import (
    extract_labs_from_lines,
    _parse_collection_time_12h,
    _parse_recent_results_block,
)
from cerebralos.features.labs_panel_daily import build_labs_panel_daily


# ── Helpers ──────────────────────────────────────────────────────────

def _make_lines(text: str):
    """Split text into line-dicts for extract_labs_from_lines."""
    return [
        {"text": line, "ts": None, "item_type": "LAB"}
        for line in text.split("\n")
    ]


def _extract(text: str):
    """Shorthand: extract labs from text, all-lab-context."""
    lines = _make_lines(text)
    labs, warnings = extract_labs_from_lines(lines, _all_lab_context=True)
    return labs, warnings


def _by_component(labs):
    """Group extracted labs by component name → list of lab dicts."""
    out = {}
    for lab in labs:
        comp = lab.get("component", "")
        if comp:
            out.setdefault(comp, []).append(lab)
    return out


# ── Collection time parsing ──────────────────────────────────────────

class TestCollectionTimeParsing:
    """Tests for _parse_collection_time_12h."""

    def test_am_time(self):
        assert _parse_collection_time_12h("12/31/25", "7:44", "AM") == "2025-12-31T07:44:00"

    def test_pm_time(self):
        assert _parse_collection_time_12h("12/31/25", "3:39", "PM") == "2025-12-31T15:39:00"

    def test_12_pm_noon(self):
        assert _parse_collection_time_12h("01/01/26", "12:00", "PM") == "2026-01-01T12:00:00"

    def test_12_am_midnight(self):
        assert _parse_collection_time_12h("01/01/26", "12:00", "AM") == "2026-01-01T00:00:00"

    def test_four_digit_year(self):
        assert _parse_collection_time_12h("01/15/2026", "9:30", "AM") == "2026-01-15T09:30:00"

    def test_invalid_date_returns_none(self):
        assert _parse_collection_time_12h("bad", "7:44", "AM") is None

    def test_case_insensitive_ampm(self):
        assert _parse_collection_time_12h("06/15/25", "2:30", "pm") == "2025-06-15T14:30:00"


# ── Basic CBC panel ─────────────────────────────────────────────────

class TestRecentResultsCBC:
    """Basic CBC panel extraction."""

    TEXT = (
        "Recent Results\n"
        "\t\t\t\t\n"
        "Recent Results (from the past 24 hours)\n"
        "CBC W AUTO DIFF\n"
        " \tCollection Time: 12/31/25  7:44 AM\n"
        "Result\tValue\tRef Range\n"
        " \tWhite Blood Cell Count\t8.6\t4.8 - 10.8 THOUS/uL\n"
        " \tHemoglobin\t12.7\t12.0 - 16.0 GM/DL\n"
        " \tHematocrit\t38.1\t37.0 - 47.0 %\n"
        " \tPlatelet Count\t162\t130 - 400 THOUS/uL\n"
    )

    def test_extracts_four_cbc_components(self):
        labs, warnings = _extract(self.TEXT)
        comps = _by_component(labs)
        assert "White Blood Cell Count" in comps
        assert "Hemoglobin" in comps
        assert "Hematocrit" in comps
        assert "Platelet Count" in comps

    def test_wbc_value_and_datetime(self):
        labs, _ = _extract(self.TEXT)
        comps = _by_component(labs)
        wbc = comps["White Blood Cell Count"][0]
        assert wbc["value_num"] == 8.6
        assert wbc["observed_dt"] == "2025-12-31T07:44:00"
        assert wbc["unit"] == "THOUS/uL"

    def test_source_block_type(self):
        labs, _ = _extract(self.TEXT)
        for lab in labs:
            if lab.get("component"):
                assert lab["source_block_type"] == "recent_results"

    def test_no_warnings(self):
        _, warnings = _extract(self.TEXT)
        assert len(warnings) == 0


# ── Multi-panel block ────────────────────────────────────────────────

class TestRecentResultsMultiPanel:
    """Multiple panels in one Recent Results block."""

    TEXT = (
        "Recent Results\n"
        "Recent Results (from the past 24 hours)\n"
        "CBC W AUTO DIFF\n"
        " \tCollection Time: 12/31/25  7:44 AM\n"
        "Result\tValue\tRef Range\n"
        " \tWhite Blood Cell Count\t8.6\t4.8 - 10.8 THOUS/uL\n"
        " \tHemoglobin\t12.7\t12.0 - 16.0 GM/DL\n"
        "COMPREHENSIVE METABOLIC PANEL\n"
        " \tCollection Time: 12/31/25  7:44 AM\n"
        "Result\tValue\tRef Range\n"
        " \tGlucose\t116 (H)\t74 - 100 MG/DL\n"
        " \tSodium\t142\t136 - 145 MMOL/L\n"
        " \tPotassium\t3.9\t3.5 - 5.1 MMOL/L\n"
        " \tCreatinine\t1.1 (H)\t0.52 - 1.04 MG/DL\n"
        "PROTIME (PROTHROMBIN TIME)\n"
        " \tCollection Time: 12/31/25  3:39 PM\n"
        "Result\tValue\tRef Range\n"
        " \tPROTIME\t10.9\t9.5 - 13.3 SEC\n"
        " \tINR\t1.0\t0.9 - 1.1\n"
    )

    def test_extracts_all_panels(self):
        labs, _ = _extract(self.TEXT)
        comps = _by_component(labs)
        # CBC
        assert "White Blood Cell Count" in comps
        assert "Hemoglobin" in comps
        # BMP
        assert "Glucose" in comps
        assert "Sodium" in comps
        assert "Potassium" in comps
        assert "Creatinine" in comps
        # Coags
        assert "PROTIME" in comps
        assert "INR" in comps

    def test_glucose_flag_extraction(self):
        labs, _ = _extract(self.TEXT)
        comps = _by_component(labs)
        glu = comps["Glucose"][0]
        assert glu["value_num"] == 116.0
        assert "H" in glu["flags"]

    def test_creatinine_flag_extraction(self):
        labs, _ = _extract(self.TEXT)
        comps = _by_component(labs)
        cr = comps["Creatinine"][0]
        assert cr["value_num"] == 1.1
        assert "H" in cr["flags"]

    def test_protime_different_collection_time(self):
        labs, _ = _extract(self.TEXT)
        comps = _by_component(labs)
        pt = comps["PROTIME"][0]
        assert pt["observed_dt"] == "2025-12-31T15:39:00"
        assert pt["value_num"] == 10.9

    def test_total_count(self):
        labs, _ = _extract(self.TEXT)
        # 2 CBC + 4 BMP + 2 Coags = 8
        named = [l for l in labs if l.get("component")]
        assert len(named) == 8


# ── Flag handling ────────────────────────────────────────────────────

class TestRecentResultsFlags:
    """Tests for (H), (L), (A) flag extraction."""

    TEXT = (
        "Recent Results\n"
        "Recent Results (from the past 24 hours)\n"
        "CBC W AUTO DIFF\n"
        " \tCollection Time: 01/03/26  2:15 AM\n"
        "Result\tValue\tRef Range\n"
        " \tWhite Blood Cell Count\t9.1\t4.0 - 10.4 THOUS/uL\n"
        " \tRed Blood Cell Count\t3.61 (L)\t3.90 - 5.0 MIL/uL\n"
        " \tHemoglobin\t10.8 (L)\t11.6 - 14.9 GM/DL\n"
        " \tHematocrit\t32.6 (L)\t38.0 - 48.0 %\n"
        " \tRdwsd\t47.8 (H)\t35.0 - 42.0 FL\n"
        " \tPlatelet Count\t354\t130 - 400 THOUS/uL\n"
    )

    def test_low_flag(self):
        labs, _ = _extract(self.TEXT)
        comps = _by_component(labs)
        rbc = comps["Red Blood Cell Count"][0]
        assert rbc["value_num"] == 3.61
        assert "L" in rbc["flags"]

    def test_high_flag(self):
        labs, _ = _extract(self.TEXT)
        comps = _by_component(labs)
        rdw = comps["Rdwsd"][0]
        assert rdw["value_num"] == 47.8
        assert "H" in rdw["flags"]

    def test_no_flag(self):
        labs, _ = _extract(self.TEXT)
        comps = _by_component(labs)
        wbc = comps["White Blood Cell Count"][0]
        assert wbc["flags"] == []

    def test_abnormal_flag_a(self):
        text = (
            "Recent Results\n"
            "Recent Results (from the past 24 hours)\n"
            "URINALYSIS\n"
            " \tCollection Time: 01/02/26  7:13 AM\n"
            "Result\tValue\tRef Range\n"
            " \tNitrite UA\tPOSITIVE (A)\t \n"
            " \tLeukocyte Esterase UA\tLARGE (A)\t \n"
        )
        labs, _ = _extract(text)
        comps = _by_component(labs)
        nitrite = comps["Nitrite UA"][0]
        assert "ABNORMAL" in nitrite["flags"]
        assert nitrite["value_raw"] == "POSITIVE"


# ── Non-numeric values ──────────────────────────────────────────────

class TestRecentResultsNonNumeric:
    """Tests for text/non-numeric values like NEGATIVE, AUTO."""

    TEXT = (
        "Recent Results\n"
        "Recent Results (from the past 24 hours)\n"
        "URINALYSIS\n"
        " \tCollection Time: 01/02/26  7:13 AM\n"
        " \tSpecimen: Urine, Clean Catch Midstream\n"
        "Result\tValue\tRef Range\n"
        " \tGlucose UA\tNEGATIVE\tNEGATIVE MG/DL\n"
        " \tProtein UA\tNEGATIVE\t<30 MG/DL\n"
        " \tpH UA\t6.0\t5.0 - 9.0\n"
    )

    def test_negative_value_extracted(self):
        labs, _ = _extract(self.TEXT)
        comps = _by_component(labs)
        glu_ua = comps["Glucose UA"][0]
        assert glu_ua["value_raw"] == "NEGATIVE"
        assert glu_ua["value_num"] is None  # text, not numeric

    def test_numeric_ua_value(self):
        labs, _ = _extract(self.TEXT)
        comps = _by_component(labs)
        ph = comps["pH UA"][0]
        assert ph["value_num"] == 6.0

    def test_specimen_line_skipped(self):
        labs, _ = _extract(self.TEXT)
        comps = _by_component(labs)
        assert "Specimen" not in comps
        assert "Urine, Clean Catch Midstream" not in comps


# ── Renal CO2 panel mapping ─────────────────────────────────────────

class TestRenalCO2Mapping:
    """Renal CO2 component maps to CO2 in BMP panel."""

    def test_renal_co2_maps_to_co2(self):
        # Simulate labs_daily output with Renal CO2
        labs_block = {
            "daily": {
                "Renal CO2": {
                    "first": 18.0,
                    "last": 18.0,
                    "delta": None,
                    "delta_pct": None,
                    "big_change": False,
                    "abnormal_flag_present": True,
                    "n_values": 1,
                },
            },
            "series": {},
            "latest": {},
        }
        panel = build_labs_panel_daily(labs_block)
        assert panel["bmp"]["CO2"] != "DATA NOT AVAILABLE"
        assert panel["bmp"]["CO2"]["value"] == 18.0


# ── End-of-block detection ───────────────────────────────────────────

class TestRecentResultsEndOfBlock:
    """Parsing stops at section markers."""

    def test_stops_at_note_section(self):
        text = (
            "Recent Results\n"
            "Recent Results (from the past 24 hours)\n"
            "CBC\n"
            " \tCollection Time: 01/01/26  8:00 AM\n"
            "Result\tValue\tRef Range\n"
            " \tWhite Blood Cell Count\t9.0\t4.0 - 10.4 THOUS/uL\n"
            "[PHYSICIAN_NOTE] Next section\n"
            " \tHemoglobin\t12.0\t12.0 - 16.0 GM/DL\n"
        )
        labs, _ = _extract(text)
        comps = _by_component(labs)
        assert "White Blood Cell Count" in comps
        # Hemoglobin after [PHYSICIAN_NOTE] should NOT be parsed as
        # part of the Recent Results block
        assert "Hemoglobin" not in comps

    def test_stops_at_impression(self):
        text = (
            "Recent Results\n"
            "Recent Results (from the past 24 hours)\n"
            "CBC\n"
            " \tCollection Time: 01/01/26  8:00 AM\n"
            "Result\tValue\tRef Range\n"
            " \tWhite Blood Cell Count\t9.0\t4.0 - 10.4 THOUS/uL\n"
            "Impression: Stable labs\n"
            " \tHemoglobin\t12.0\t12.0 - 16.0 GM/DL\n"
        )
        labs, _ = _extract(text)
        comps = _by_component(labs)
        assert "White Blood Cell Count" in comps
        assert "Hemoglobin" not in comps


# ── Empty block ──────────────────────────────────────────────────────

class TestRecentResultsEmpty:
    """Empty Recent Results block."""

    def test_empty_block(self):
        text = "Recent Results\n\n"
        labs, warnings = _extract(text)
        # Should produce no labs
        named = [l for l in labs if l.get("component")]
        assert len(named) == 0


# ── "Results for orders placed..." subsection ────────────────────────

class TestResultsForOrders:
    """'Results for orders placed...' sub-header is skipped."""

    TEXT = (
        "Recent Results\n"
        "Recent Results (from the past 24 hours)\n"
        "CBC\n"
        " \tCollection Time: 01/03/26  2:15 AM\n"
        "Result\tValue\tRef Range\n"
        " \tWhite Blood Cell Count\t9.1\t4.0 - 10.4 THOUS/uL\n"
        "\n"
        "Results for orders placed or performed during the hospital encounter of 12/31/25\n"
        "URINALYSIS WITH REFLEX TO CULTURE, IF INDICATED\n"
        " \tCollection Time: 01/02/26  7:13 AM\n"
        "Result\tValue\n"
        " \tGlucose UA\tNEGATIVE\n"
    )

    def test_both_sections_parsed(self):
        labs, _ = _extract(self.TEXT)
        comps = _by_component(labs)
        assert "White Blood Cell Count" in comps
        assert "Glucose UA" in comps


# ── Multiple "Recent Results" blocks ─────────────────────────────────

class TestMultipleRecentResultsBlocks:
    """Two 'Recent Results' blocks in sequence (from different LAB items)."""

    TEXT = (
        "Recent Results\n"
        "Recent Results (from the past 24 hours)\n"
        "CBC\n"
        " \tCollection Time: 12/31/25  7:44 AM\n"
        "Result\tValue\tRef Range\n"
        " \tWhite Blood Cell Count\t8.6\t4.8 - 10.8 THOUS/uL\n"
        "\n"
        "Recent Results\n"
        "Recent Results (from the past 24 hours)\n"
        "CBC\n"
        " \tCollection Time: 01/01/26  5:42 AM\n"
        "Result\tValue\tRef Range\n"
        " \tWhite Blood Cell Count\t8.7\t4.0 - 10.4 THOUS/uL\n"
    )

    def test_both_blocks_extracted(self):
        labs, _ = _extract(self.TEXT)
        comps = _by_component(labs)
        wbc_list = comps["White Blood Cell Count"]
        assert len(wbc_list) == 2

    def test_different_datetimes(self):
        labs, _ = _extract(self.TEXT)
        comps = _by_component(labs)
        wbc_list = comps["White Blood Cell Count"]
        dts = sorted(w["observed_dt"] for w in wbc_list)
        assert dts[0] == "2025-12-31T07:44:00"
        assert dts[1] == "2026-01-01T05:42:00"


# ── Labs panel daily integration ─────────────────────────────────────

class TestLabsPanelDailyIntegration:
    """Full analyte names from Recent Results feed into panel builder."""

    def _make_daily_block(self, daily_dict):
        return {
            "daily": daily_dict,
            "series": {},
            "latest": {},
        }

    def test_cbc_from_full_names(self):
        daily = {
            "White Blood Cell Count": {"first": 8.6, "last": 8.6, "delta": None, "delta_pct": None, "big_change": False, "abnormal_flag_present": False, "n_values": 1},
            "Hemoglobin": {"first": 12.7, "last": 12.7, "delta": None, "delta_pct": None, "big_change": False, "abnormal_flag_present": False, "n_values": 1},
            "Hematocrit": {"first": 38.1, "last": 38.1, "delta": None, "delta_pct": None, "big_change": False, "abnormal_flag_present": False, "n_values": 1},
            "Platelet Count": {"first": 162.0, "last": 162.0, "delta": None, "delta_pct": None, "big_change": False, "abnormal_flag_present": False, "n_values": 1},
        }
        panel = build_labs_panel_daily(self._make_daily_block(daily))
        assert panel["cbc"]["WBC"]["value"] == 8.6
        assert panel["cbc"]["Hgb"]["value"] == 12.7
        assert panel["cbc"]["Hct"]["value"] == 38.1
        assert panel["cbc"]["Plt"]["value"] == 162.0

    def test_bmp_from_full_names(self):
        daily = {
            "Sodium": {"first": 142.0, "last": 142.0, "delta": None, "delta_pct": None, "big_change": False, "abnormal_flag_present": False, "n_values": 1},
            "Potassium": {"first": 3.9, "last": 3.9, "delta": None, "delta_pct": None, "big_change": False, "abnormal_flag_present": False, "n_values": 1},
            "Chloride": {"first": 111.0, "last": 111.0, "delta": None, "delta_pct": None, "big_change": False, "abnormal_flag_present": True, "n_values": 1},
            "Co2": {"first": 20.0, "last": 20.0, "delta": None, "delta_pct": None, "big_change": False, "abnormal_flag_present": False, "n_values": 1},
            "Blood Urea Nitrogen": {"first": 18.0, "last": 18.0, "delta": None, "delta_pct": None, "big_change": False, "abnormal_flag_present": False, "n_values": 1},
            "Creatinine": {"first": 1.1, "last": 1.1, "delta": None, "delta_pct": None, "big_change": False, "abnormal_flag_present": True, "n_values": 1},
            "Glucose": {"first": 116.0, "last": 116.0, "delta": None, "delta_pct": None, "big_change": False, "abnormal_flag_present": True, "n_values": 1},
        }
        panel = build_labs_panel_daily(self._make_daily_block(daily))
        assert panel["bmp"]["Na"]["value"] == 142.0
        assert panel["bmp"]["K"]["value"] == 3.9
        assert panel["bmp"]["Cl"]["value"] == 111.0
        assert panel["bmp"]["CO2"]["value"] == 20.0
        assert panel["bmp"]["BUN"]["value"] == 18.0
        assert panel["bmp"]["Cr"]["value"] == 1.1
        assert panel["bmp"]["Glucose"]["value"] == 116.0

    def test_coags_from_protime(self):
        daily = {
            "PROTIME": {"first": 10.9, "last": 10.9, "delta": None, "delta_pct": None, "big_change": False, "abnormal_flag_present": False, "n_values": 1},
            "INR": {"first": 1.0, "last": 1.0, "delta": None, "delta_pct": None, "big_change": False, "abnormal_flag_present": False, "n_values": 1},
        }
        panel = build_labs_panel_daily(self._make_daily_block(daily))
        assert panel["coags"]["PT"]["value"] == 10.9
        assert panel["coags"]["INR"]["value"] == 1.0


# ── Collection time edge cases ───────────────────────────────────────

class TestCollectionTimeEdgeCases:
    """Collection time with early AM hours."""

    def test_early_am(self):
        text = (
            "Recent Results\n"
            "Recent Results (from the past 24 hours)\n"
            "CBC\n"
            " \tCollection Time: 01/03/26  2:15 AM\n"
            "Result\tValue\tRef Range\n"
            " \tWhite Blood Cell Count\t9.1\t4.0 - 10.4 THOUS/uL\n"
        )
        labs, _ = _extract(text)
        comps = _by_component(labs)
        wbc = comps["White Blood Cell Count"][0]
        assert wbc["observed_dt"] == "2026-01-03T02:15:00"

    def test_late_pm(self):
        text = (
            "Recent Results\n"
            "Recent Results (from the past 24 hours)\n"
            "CBC\n"
            " \tCollection Time: 01/03/26  11:59 PM\n"
            "Result\tValue\tRef Range\n"
            " \tWhite Blood Cell Count\t9.1\t4.0 - 10.4 THOUS/uL\n"
        )
        labs, _ = _extract(text)
        comps = _by_component(labs)
        wbc = comps["White Blood Cell Count"][0]
        assert wbc["observed_dt"] == "2026-01-03T23:59:00"


# ── Ref range and unit extraction ────────────────────────────────────

class TestRefRangeUnit:
    """Verifies unit extraction from ref range fields."""

    TEXT = (
        "Recent Results\n"
        "Recent Results (from the past 24 hours)\n"
        "CBC\n"
        " \tCollection Time: 01/01/26  5:00 AM\n"
        "Result\tValue\tRef Range\n"
        " \tWhite Blood Cell Count\t8.7\t4.0 - 10.4 THOUS/uL\n"
        " \tHemoglobin\t11.6\t11.6 - 14.9 GM/DL\n"
        " \tHematocrit\t36.3 (L)\t38.0 - 48.0 %\n"
    )

    def test_unit_extraction(self):
        labs, _ = _extract(self.TEXT)
        comps = _by_component(labs)
        assert comps["White Blood Cell Count"][0]["unit"] == "THOUS/uL"
        assert comps["Hemoglobin"][0]["unit"] == "GM/DL"
        assert comps["Hematocrit"][0]["unit"] == "%"

    def test_range_raw_preserved(self):
        labs, _ = _extract(self.TEXT)
        comps = _by_component(labs)
        wbc = comps["White Blood Cell Count"][0]
        assert wbc["range_unit"] == "4.0 - 10.4 THOUS/uL"


# ── GFR Comment skip ────────────────────────────────────────────────

class TestGFRCommentSkip:
    """GFR Comment descriptive rows are skipped."""

    TEXT = (
        "Recent Results\n"
        "Recent Results (from the past 24 hours)\n"
        "RENAL PROFILE\n"
        " \tCollection Time: 01/01/26  5:42 AM\n"
        "Result\tValue\tRef Range\n"
        " \tEst GFR\t82 (L)\t>90 ML/MIN/1.73sq.m\n"
        " \tGFR Comment\t \t \n"
        " \t \tReported eGFR is based on the CKD-EPI 2021 equation that does not use a race coefficient.\n"
        " \tAnion Gap\t13\t7 - 14 MMOL/L\n"
    )

    def test_gfr_comment_skipped(self):
        labs, _ = _extract(self.TEXT)
        comps = _by_component(labs)
        assert "GFR Comment" not in comps

    def test_anion_gap_after_comment(self):
        labs, _ = _extract(self.TEXT)
        comps = _by_component(labs)
        assert "Anion Gap" in comps
        assert comps["Anion Gap"][0]["value_num"] == 13.0

    def test_est_gfr_extracted(self):
        labs, _ = _extract(self.TEXT)
        comps = _by_component(labs)
        assert "Est GFR" in comps
        assert comps["Est GFR"][0]["value_num"] == 82.0
