#!/usr/bin/env python3
"""Tests for tabular note-internal vitals parsing fallback.

Covers three sub-formats:
  A) Horizontal tabular — tab-separated timestamp header + label rows
  B) Vertical tabular   — consecutive timestamp lines + label/value groups
  C) Vital Signs block  — 'Vital Signs:' header + key: value per line
"""

import pytest
from cerebralos.features.vitals_daily import (
    _extract_metric_from_cell,
    _parse_tabular_note_vitals,
    _compute_map,
)


# ── Default guardrails (same as production config) ──────────────────
GUARDRAILS = {
    "bp": {"sbp_min": 40, "sbp_max": 300, "dbp_min": 20, "dbp_max": 200},
    "hr": {"min": 20, "max": 300},
    "temp_f": {"min": 85, "max": 115},
    "rr": {"min": 4, "max": 60},
    "spo2": {"min": 50, "max": 100},
}

SRC = "test-note-001"


# ═════════════════════════════════════════════════════════════════════
#  _extract_metric_from_cell unit tests
# ═════════════════════════════════════════════════════════════════════

class TestExtractMetricFromCell:
    """Unit tests for the cell-level metric extractor."""

    def test_bp_normal(self):
        result = _extract_metric_from_cell("BP", "120/80", GUARDRAILS)
        assert len(result) == 3
        assert ("sbp", 120.0) in result
        assert ("dbp", 80.0) in result
        assert ("map", _compute_map(120, 80)) in result

    def test_bp_with_abnormal_marker(self):
        result = _extract_metric_from_cell("BP", "(!) 162/87", GUARDRAILS)
        assert ("sbp", 162.0) in result
        assert ("dbp", 87.0) in result

    def test_bp_empty_cell(self):
        assert _extract_metric_from_cell("BP", "", GUARDRAILS) == []
        assert _extract_metric_from_cell("BP", "   ", GUARDRAILS) == []

    def test_bp_out_of_range(self):
        """SBP > 300 rejected."""
        assert _extract_metric_from_cell("BP", "350/80", GUARDRAILS) == []

    def test_pulse(self):
        result = _extract_metric_from_cell("Pulse", "96", GUARDRAILS)
        assert result == [("hr", 96.0)]

    def test_pulse_with_abnormal(self):
        result = _extract_metric_from_cell("Pulse", "(!) 120", GUARDRAILS)
        assert result == [("hr", 120.0)]

    def test_temp_fahrenheit(self):
        result = _extract_metric_from_cell("Temp", "97.3 °F (36.3 °C)", GUARDRAILS)
        assert result == [("temp_f", 97.3)]

    def test_temp_no_degree_symbol(self):
        result = _extract_metric_from_cell("Temp", "98.6 F", GUARDRAILS)
        assert result == [("temp_f", 98.6)]

    def test_resp(self):
        result = _extract_metric_from_cell("Resp", "18", GUARDRAILS)
        assert result == [("rr", 18.0)]

    def test_resp_abnormal(self):
        result = _extract_metric_from_cell("Resp", "(!) 29", GUARDRAILS)
        assert result == [("rr", 29.0)]

    def test_spo2_with_percent(self):
        result = _extract_metric_from_cell("SpO2", "95%", GUARDRAILS)
        assert result == [("spo2", 95.0)]

    def test_spo2_with_space_percent(self):
        result = _extract_metric_from_cell("SpO2", "94 %", GUARDRAILS)
        assert result == [("spo2", 94.0)]

    def test_spo2_out_of_range(self):
        """SpO2 < 50 rejected."""
        assert _extract_metric_from_cell("SpO2", "30%", GUARDRAILS) == []

    def test_unknown_label(self):
        assert _extract_metric_from_cell("Weight", "185 lb", GUARDRAILS) == []

    def test_only_abnormal_marker(self):
        """Cell that is just '(!)' → empty after stripping."""
        assert _extract_metric_from_cell("BP", "(!)", GUARDRAILS) == []


# ═════════════════════════════════════════════════════════════════════
#  Format A: Horizontal tabular tests
# ═════════════════════════════════════════════════════════════════════

class TestHorizontalTabular:
    """Horizontal tabular: tab-separated timestamp header + label:val rows."""

    HORIZONTAL_BLOCK = (
        "Vitals:\n"
        " \t01/03/26 1847\t01/03/26 2251\n"
        "BP:\t116/65\t124/75\n"
        "Pulse:\t96\t89\n"
        "Resp:\t18\t17\n"
        "Temp:\t97.3 °F (36.3 °C)\t97.7 °F (36.5 °C)\n"
        "TempSrc:\tOral\tOral\n"
        "SpO2:\t95%\t94%\n"
        "Weight:\t \t \n"
    )

    def test_parses_all_metrics(self):
        readings, gaps = _parse_tabular_note_vitals(
            self.HORIZONTAL_BLOCK, "2026-01-03", None, SRC, GUARDRAILS,
        )
        assert len(gaps) == 0
        metrics = {r["metric"] for r in readings}
        assert {"sbp", "dbp", "map", "hr", "rr", "temp_f", "spo2"} <= metrics

    def test_correct_values_per_timestamp(self):
        readings, _ = _parse_tabular_note_vitals(
            self.HORIZONTAL_BLOCK, "2026-01-03", None, SRC, GUARDRAILS,
        )
        # Filter BP at first timestamp
        sbp_1847 = [r for r in readings if r["metric"] == "sbp"
                     and r["dt"] == "2026-01-03T18:47:00"]
        assert len(sbp_1847) == 1
        assert sbp_1847[0]["value"] == 116.0

        sbp_2251 = [r for r in readings if r["metric"] == "sbp"
                     and r["dt"] == "2026-01-03T22:51:00"]
        assert len(sbp_2251) == 1
        assert sbp_2251[0]["value"] == 124.0

    def test_source_type(self):
        readings, _ = _parse_tabular_note_vitals(
            self.HORIZONTAL_BLOCK, "2026-01-03", None, SRC, GUARDRAILS,
        )
        for r in readings:
            assert r["source_type"] == "TABULAR"

    def test_abnormal_marker_stripped(self):
        text = (
            " \t01/03/26 1847\t01/03/26 2251\n"
            "BP:\t(!) 162/87\t120/80\n"
        )
        readings, gaps = _parse_tabular_note_vitals(
            text, "2026-01-03", None, SRC, GUARDRAILS,
        )
        sbp = [r for r in readings if r["metric"] == "sbp"]
        assert len(sbp) == 2
        vals = sorted([r["value"] for r in sbp])
        assert vals == [120.0, 162.0]

    def test_filters_by_day(self):
        """Timestamps not matching day_iso are excluded."""
        text = (
            " \t01/03/26 1847\t01/04/26 0737\n"
            "BP:\t116/65\t119/58\n"
        )
        readings, _ = _parse_tabular_note_vitals(
            text, "2026-01-03", None, SRC, GUARDRAILS,
        )
        sbp = [r for r in readings if r["metric"] == "sbp"]
        assert len(sbp) == 1
        assert sbp[0]["dt"] == "2026-01-03T18:47:00"

    def test_empty_cells_skipped(self):
        """Columns with empty cells produce no readings."""
        text = (
            " \t01/03/26 0500\t01/03/26 0530\n"
            "BP:\t\t128/82\n"
        )
        readings, _ = _parse_tabular_note_vitals(
            text, "2026-01-03", None, SRC, GUARDRAILS,
        )
        sbp = [r for r in readings if r["metric"] == "sbp"]
        assert len(sbp) == 1
        assert sbp[0]["value"] == 128.0

    def test_gap_when_no_vitals_parsed(self):
        """Timestamp row with no parseable vital rows → gap record."""
        text = (
            " \t01/03/26 1847\t01/03/26 2251\n"
            "SomeOtherMetric:\t42\t43\n"
        )
        readings, gaps = _parse_tabular_note_vitals(
            text, "2026-01-03", None, SRC, GUARDRAILS,
        )
        assert len(readings) == 0
        assert len(gaps) == 1
        assert gaps[0]["gap_type"] == "TABULAR_NOTE_VITALS_UNSUPPORTED"


# ═════════════════════════════════════════════════════════════════════
#  Format B: Vertical tabular tests
# ═════════════════════════════════════════════════════════════════════

class TestVerticalTabular:
    """Vertical tabular: consecutive timestamp lines + label/value groups."""

    VERTICAL_BLOCK = (
        "Vitals:\n"
        " \n"
        "12/28/25 1940\n"
        "12/28/25 2339\n"
        "12/29/25 0421\n"
        "12/29/25 0738\n"
        "BP:\n"
        "137/73\n"
        "116/67\n"
        "110/63\n"
        "125/71\n"
        "Pulse:\n"
        "72\n"
        "65\n"
        "61\n"
        "79\n"
        "Resp:\n"
        "18\n"
        "18\n"
        "16\n"
        "16\n"
        "Temp:\n"
        "98.1 °F (36.7 °C)\n"
        "97.7 °F (36.5 °C)\n"
        "98.3 °F (36.8 °C)\n"
        "97.5 °F (36.4 °C)\n"
        "TempSrc:\n"
        "Oral\n"
        "Oral\n"
        "Oral\n"
        "Oral\n"
        "SpO2:\n"
        "95%\n"
        "95%\n"
        "94%\n"
        "95%\n"
        "Weight:\n"
        " \n"
    )

    def test_parses_all_metrics_day1(self):
        readings, gaps = _parse_tabular_note_vitals(
            self.VERTICAL_BLOCK, "2025-12-28", None, SRC, GUARDRAILS,
        )
        assert len(gaps) == 0
        metrics = {r["metric"] for r in readings}
        assert {"sbp", "dbp", "map", "hr", "rr", "temp_f", "spo2"} <= metrics

    def test_parses_day2_timestamps(self):
        readings, _ = _parse_tabular_note_vitals(
            self.VERTICAL_BLOCK, "2025-12-29", None, SRC, GUARDRAILS,
        )
        sbp = [r for r in readings if r["metric"] == "sbp"]
        assert len(sbp) == 2
        dts = {r["dt"] for r in sbp}
        assert "2025-12-29T04:21:00" in dts
        assert "2025-12-29T07:38:00" in dts

    def test_correct_value_mapping(self):
        readings, _ = _parse_tabular_note_vitals(
            self.VERTICAL_BLOCK, "2025-12-28", None, SRC, GUARDRAILS,
        )
        # BP at 1940 should be 137/73
        sbp_1940 = [r for r in readings if r["metric"] == "sbp"
                     and r["dt"] == "2025-12-28T19:40:00"]
        assert len(sbp_1940) == 1
        assert sbp_1940[0]["value"] == 137.0

        # Pulse at 2339 should be 65
        hr_2339 = [r for r in readings if r["metric"] == "hr"
                    and r["dt"] == "2025-12-28T23:39:00"]
        assert len(hr_2339) == 1
        assert hr_2339[0]["value"] == 65.0

    def test_source_type(self):
        readings, _ = _parse_tabular_note_vitals(
            self.VERTICAL_BLOCK, "2025-12-28", None, SRC, GUARDRAILS,
        )
        for r in readings:
            assert r["source_type"] == "TABULAR"

    def test_skip_label_does_not_break_block(self):
        """TempSrc and Weight are skipped without disrupting parsing."""
        readings, gaps = _parse_tabular_note_vitals(
            self.VERTICAL_BLOCK, "2025-12-28", None, SRC, GUARDRAILS,
        )
        # Should have readings for both Temp and SpO2 (after TempSrc skip)
        assert any(r["metric"] == "temp_f" for r in readings)
        assert any(r["metric"] == "spo2" for r in readings)

    def test_gap_when_timestamps_but_no_vitals(self):
        """Timestamp cluster near vital keywords but no parseable labels → gap."""
        text = (
            "12/28/25 1940\n"
            "12/28/25 2339\n"
            "Some BP narrative here\n"
            "No parseable structure\n"
        )
        readings, gaps = _parse_tabular_note_vitals(
            text, "2025-12-28", None, SRC, GUARDRAILS,
        )
        assert len(readings) == 0
        assert len(gaps) == 1
        assert gaps[0]["gap_type"] == "TABULAR_NOTE_VITALS_UNSUPPORTED"


# ═════════════════════════════════════════════════════════════════════
#  Format C: Vital Signs block tests
# ═════════════════════════════════════════════════════════════════════

class TestVitalSignsBlock:
    """Vital Signs block: 'Vital Signs:' header + key: value per line."""

    VS_BLOCK = (
        "OBJECTIVE:\n"
        " \n"
        "Vital Signs:\n"
        "Temp: 97.7 °F (36.5 °C)\n"
        "BP: 102/73\n"
        "Pulse: 90\n"
        "Resp: 16\n"
        "SpO2: 94 %\n"
        "Temp (24hrs), Avg:97.7 °F, Min:95.5 °F, Max:98.8 °F\n"
    )

    def test_parses_all_metrics(self):
        readings, gaps = _parse_tabular_note_vitals(
            self.VS_BLOCK, "2026-01-02",
            "2026-01-02T12:30:00", SRC, GUARDRAILS,
        )
        assert len(gaps) == 0
        metrics = {r["metric"] for r in readings}
        assert {"sbp", "dbp", "map", "hr", "rr", "temp_f", "spo2"} <= metrics

    def test_correct_values(self):
        readings, _ = _parse_tabular_note_vitals(
            self.VS_BLOCK, "2026-01-02",
            "2026-01-02T12:30:00", SRC, GUARDRAILS,
        )
        vals = {r["metric"]: r["value"] for r in readings}
        assert vals["sbp"] == 102.0
        assert vals["dbp"] == 73.0
        assert vals["hr"] == 90.0
        assert vals["rr"] == 16.0
        assert vals["temp_f"] == 97.7
        assert vals["spo2"] == 94.0

    def test_uses_item_dt(self):
        readings, _ = _parse_tabular_note_vitals(
            self.VS_BLOCK, "2026-01-02",
            "2026-01-02T12:30:00", SRC, GUARDRAILS,
        )
        for r in readings:
            assert r["dt"] == "2026-01-02T12:30:00"

    def test_no_item_dt_no_readings(self):
        """Without item_dt, Format C produces no readings (fail-closed)."""
        readings, gaps = _parse_tabular_note_vitals(
            self.VS_BLOCK, "2026-01-02", None, SRC, GUARDRAILS,
        )
        # No readings from Format C (no timestamp available)
        assert len(readings) == 0

    def test_wrong_day_no_readings(self):
        """item_dt on different day → no readings."""
        readings, _ = _parse_tabular_note_vitals(
            self.VS_BLOCK, "2026-01-03",
            "2026-01-02T12:30:00", SRC, GUARDRAILS,
        )
        assert len(readings) == 0

    def test_vital_signs_on_discharge_header(self):
        """'Vital signs on discharge:' header variant."""
        text = (
            "5. Vital signs on discharge:\n"
            "Temp: 97.8 °F (36.6 °C)\n"
            "BP: 120/69\n"
            "Pulse: 63\n"
            "Resp: 18\n"
            "SpO2: 94 %\n"
        )
        readings, _ = _parse_tabular_note_vitals(
            text, "2025-12-30",
            "2025-12-30T10:00:00", SRC, GUARDRAILS,
        )
        vals = {r["metric"]: r["value"] for r in readings}
        assert vals["sbp"] == 120.0
        assert vals["hr"] == 63.0

    def test_abnormal_bp(self):
        text = (
            "Vital Signs:\n"
            "BP: (!) 157/80\n"
            "Pulse: 69\n"
        )
        readings, _ = _parse_tabular_note_vitals(
            text, "2026-01-02",
            "2026-01-02T12:00:00", SRC, GUARDRAILS,
        )
        sbp = [r for r in readings if r["metric"] == "sbp"]
        assert sbp[0]["value"] == 157.0

    def test_stops_at_non_vital_section(self):
        """Parsing stops at non-vital content after the block."""
        text = (
            "Vital Signs:\n"
            "BP: 120/80\n"
            "Pulse: 72\n"
            "\n"
            "GENERAL APPEARANCE: Alert and oriented.\n"
        )
        readings, _ = _parse_tabular_note_vitals(
            text, "2026-01-02",
            "2026-01-02T12:00:00", SRC, GUARDRAILS,
        )
        # Should have BP and Pulse only — not random text
        metrics = {r["metric"] for r in readings}
        assert "sbp" in metrics
        assert "hr" in metrics

    def test_skips_temp_24hr_summary(self):
        """'Temp (24hrs), Avg:...' is not parsed as a Temp reading."""
        readings, _ = _parse_tabular_note_vitals(
            self.VS_BLOCK, "2026-01-02",
            "2026-01-02T12:30:00", SRC, GUARDRAILS,
        )
        temps = [r for r in readings if r["metric"] == "temp_f"]
        assert len(temps) == 1
        assert temps[0]["value"] == 97.7

    def test_time_missing_flag(self):
        readings, _ = _parse_tabular_note_vitals(
            self.VS_BLOCK, "2026-01-02",
            "2026-01-02T12:30:00", SRC, GUARDRAILS,
            time_missing=True,
        )
        for r in readings:
            assert r.get("time_missing") is True

    def test_narrative_after_header_produces_no_readings(self):
        """'Vital signs:' followed by narrative (no metrics) → no crash."""
        text = (
            "Vital signs:\n"
            "GENERAL:  Well-nourished, well-developed.\n"
        )
        readings, gaps = _parse_tabular_note_vitals(
            text, "2026-01-02",
            "2026-01-02T12:00:00", SRC, GUARDRAILS,
        )
        assert len(readings) == 0


# ═════════════════════════════════════════════════════════════════════
#  Guardrail / edge-case tests
# ═════════════════════════════════════════════════════════════════════

class TestGuardrails:
    """Guardrail validation rejects out-of-range values."""

    def test_sbp_too_low(self):
        text = (
            "Vital Signs:\n"
            "BP: 30/20\n"
        )
        readings, _ = _parse_tabular_note_vitals(
            text, "2026-01-02",
            "2026-01-02T12:00:00", SRC, GUARDRAILS,
        )
        assert len(readings) == 0

    def test_hr_too_high(self):
        text = (
            "Vital Signs:\n"
            "Pulse: 999\n"
        )
        readings, _ = _parse_tabular_note_vitals(
            text, "2026-01-02",
            "2026-01-02T12:00:00", SRC, GUARDRAILS,
        )
        assert len(readings) == 0

    def test_temp_impossible(self):
        text = (
            "Vital Signs:\n"
            "Temp: 200.0 °F\n"
        )
        readings, _ = _parse_tabular_note_vitals(
            text, "2026-01-02",
            "2026-01-02T12:00:00", SRC, GUARDRAILS,
        )
        assert len(readings) == 0


# ═════════════════════════════════════════════════════════════════════
#  No cross-format overlap / dedup integration
# ═════════════════════════════════════════════════════════════════════

class TestNoOverlap:
    """Ensure horizontal blocks don't re-trigger vertical scanner."""

    def test_horizontal_blocks_excluded_from_vertical(self):
        """A horizontal block's lines should not be re-parsed by vertical."""
        text = (
            " \t01/03/26 1847\t01/03/26 2251\n"
            "BP:\t116/65\t124/75\n"
            "Pulse:\t96\t89\n"
        )
        readings, gaps = _parse_tabular_note_vitals(
            text, "2026-01-03", None, SRC, GUARDRAILS,
        )
        # Count: 2 timestamps × (sbp+dbp+map+hr) = 2 × (3+1) = 8 readings
        sbp = [r for r in readings if r["metric"] == "sbp"]
        assert len(sbp) == 2  # exactly 2, not duplicated

    def test_mixed_block_horizontal_plus_vital_signs(self):
        """Both horizontal and vital signs block in same text."""
        text = (
            " \t01/03/26 1847\t01/03/26 2251\n"
            "BP:\t116/65\t124/75\n"
            "\n"
            "Vital Signs:\n"
            "BP: 102/73\n"
            "Pulse: 90\n"
        )
        readings, _ = _parse_tabular_note_vitals(
            text, "2026-01-03",
            "2026-01-03T12:00:00", SRC, GUARDRAILS,
        )
        sbp = [r for r in readings if r["metric"] == "sbp"]
        # 2 from horizontal + 1 from vital signs block = 3
        assert len(sbp) == 3
