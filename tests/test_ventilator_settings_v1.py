#!/usr/bin/env python3
"""
Tests for ventilator_settings_v1 — Vent Settings Foundation.

Covers:
  - Vent Settings block extraction (RR, Vt, PEEP, FiO2)
  - O2 Device: Ventilator detection
  - Ventilated Patient?: Yes detection
  - Non-Invasive Mechanical Ventilation detection
  - Inline FiO2 + PEEP narrative patterns
  - Range-gate rejection (fail-closed)
  - Noise exclusion (SLUMS, Isbt, respiratory rate alerts)
  - raw_line_id determinism
  - Empty/missing input handling
"""

import pytest

from cerebralos.features.ventilator_settings_v1 import (
    _extract_from_lines,
    _in_range,
    _is_noise,
    _make_raw_line_id,
    extract_ventilator_settings,
)


# ── Helpers ─────────────────────────────────────────────────────────

def _days_data_from_lines(lines, day="2026-01-10"):
    """Build minimal days_data dict from raw line strings."""
    return {"days": {day: {"raw_lines": lines}}}


# ── raw_line_id determinism ─────────────────────────────────────────

class TestRawLineId:
    def test_deterministic(self):
        a = _make_raw_line_id("fio2", "2026-01-10", 5, "FIO2 : 60 %")
        b = _make_raw_line_id("fio2", "2026-01-10", 5, "FIO2 : 60 %")
        assert a == b
        assert len(a) == 16

    def test_different_positions_differ(self):
        a = _make_raw_line_id("fio2", "2026-01-10", 5, "FIO2 : 60 %")
        b = _make_raw_line_id("fio2", "2026-01-10", 99, "FIO2 : 60 %")
        assert a != b


# ── Range gates ────────────────────────────────────────────────────

class TestRangeGates:
    def test_fio2_valid(self):
        assert _in_range("fio2", 21)
        assert _in_range("fio2", 100)
        assert _in_range("fio2", 0.4)

    def test_fio2_invalid(self):
        assert not _in_range("fio2", 0.1)    # below 0.2
        assert not _in_range("fio2", 101)     # above 100

    def test_peep_valid(self):
        assert _in_range("peep", 5)
        assert _in_range("peep", 20)

    def test_peep_invalid(self):
        assert not _in_range("peep", -1)
        assert not _in_range("peep", 31)

    def test_tidal_volume_valid(self):
        assert _in_range("tidal_volume", 460)
        assert _in_range("tidal_volume", 500)

    def test_tidal_volume_invalid(self):
        assert _in_range("tidal_volume", 50)   # at boundary
        assert not _in_range("tidal_volume", 49)
        assert not _in_range("tidal_volume", 2001)

    def test_resp_rate_valid(self):
        assert _in_range("resp_rate_set", 24)

    def test_resp_rate_invalid(self):
        assert not _in_range("resp_rate_set", 0)
        assert not _in_range("resp_rate_set", 61)


# ── Noise exclusion ────────────────────────────────────────────────

class TestNoiseExclusion:
    def test_slums_excluded(self):
        assert _is_noise("Saint Louis University Mental Status (SLUMS)")

    def test_isbt_excluded(self):
        assert _is_noise("Isbt Product Code    E8341V00    DHI")

    def test_respiratory_rate_alert_excluded(self):
        assert _is_noise(
            "Respiratory rate is less than 5 breaths/minute ALSO stop PCA"
        )

    def test_naloxone_excluded(self):
        assert _is_noise("administer naloxone (NARCAN) 0.2 mg IV")

    def test_normal_vent_not_noise(self):
        assert not _is_noise("O2 Device: Ventilator")
        assert not _is_noise("Vent Settings")
        assert not _is_noise("FIO2 : 60 %")


# ── Vent Settings block extraction ─────────────────────────────────

class TestVentSettingsBlock:
    def test_full_block(self):
        lines = [
            "Vent Settings",
            "Resp Rate (Set): 24",
            "Vt (Set, ml): 460 ml",
            "PEEP/CPAP : 14 cm H20",
            "FIO2 : 60 %",
        ]
        events = _extract_from_lines(lines, "2026-01-10")
        params = {e["param"]: e["value"] for e in events}
        assert params["resp_rate_set"] == 24
        assert params["tidal_volume"] == 460
        assert params["peep"] == 14
        assert params["fio2"] == 60

    def test_block_all_have_raw_line_id(self):
        lines = [
            "Vent Settings",
            "Resp Rate (Set): 24",
            "Vt (Set, ml): 460 ml",
            "PEEP/CPAP : 14 cm H20",
            "FIO2 : 60 %",
        ]
        events = _extract_from_lines(lines, "2026-01-10")
        for ev in events:
            assert "raw_line_id" in ev
            assert len(ev["raw_line_id"]) == 16

    def test_block_source_tag(self):
        lines = [
            "Vent Settings",
            "Resp Rate (Set): 24",
        ]
        events = _extract_from_lines(lines, "2026-01-10")
        assert events[0]["source"] == "vent_settings_block"

    def test_out_of_range_rr_rejected(self):
        lines = [
            "Vent Settings",
            "Resp Rate (Set): 999",
        ]
        events = _extract_from_lines(lines, "2026-01-10")
        assert len(events) == 0

    def test_out_of_range_tidal_volume_rejected(self):
        lines = [
            "Vent Settings",
            "Vt (Set, ml): 5000 ml",
        ]
        events = _extract_from_lines(lines, "2026-01-10")
        assert len(events) == 0


# ── O2 Device / Ventilated Patient / NIV ───────────────────────────

class TestDeviceFlags:
    def test_o2_device_ventilator(self):
        lines = ["O2 Device: Ventilator"]
        events = _extract_from_lines(lines, "2026-01-10")
        assert len(events) == 1
        assert events[0]["param"] == "vent_status"
        assert events[0]["value"] == "mechanical"

    def test_ventilated_patient_yes(self):
        lines = ["Ventilated Patient?: Yes"]
        events = _extract_from_lines(lines, "2026-01-10")
        assert len(events) == 1
        assert events[0]["param"] == "ventilated_flag"
        assert events[0]["value"] is True

    def test_niv_header(self):
        lines = ["Non-Invasive Mechanical Ventilation\t01/02\t0558\t1 more"]
        events = _extract_from_lines(lines, "2026-01-02")
        assert len(events) == 1
        assert events[0]["param"] == "vent_status"
        assert events[0]["value"] == "niv"


# ── Inline FiO2 + PEEP narrative ──────────────────────────────────

class TestInlinePatterns:
    def test_fio2_peep_inline(self):
        """'FiO2 50% peep is 12' pattern."""
        lines = ["Patient on O2 saturation is 94%, FiO2 50% peep is 12."]
        events = _extract_from_lines(lines, "2026-01-10")
        params = {e["param"]: e["value"] for e in events}
        assert params["fio2"] == 50
        assert params["peep"] == 12

    def test_peep_fio2_inline(self):
        """'PEEP 14/ FiO2 70%' pattern."""
        lines = ["PEEP 14/ FiO2 70%"]
        events = _extract_from_lines(lines, "2026-01-10")
        params = {e["param"]: e["value"] for e in events}
        assert params["peep"] == 14
        assert params["fio2"] == 70

    def test_peep_fio2_space(self):
        """'PEEP 12 FiO2 70%' pattern."""
        lines = ["Remains high ventilator requirements, PEEP 12 FiO2 70%, wean FiO2."]
        events = _extract_from_lines(lines, "2026-01-10")
        params = {e["param"]: e["value"] for e in events}
        assert params["peep"] == 12
        assert params["fio2"] == 70

    def test_fio2_comma_peep(self):
        """'FiO2 40%, peep 8' pattern."""
        lines = ["Continue lung protective ventilation, FiO2 40%, peep 8."]
        events = _extract_from_lines(lines, "2026-01-10")
        params = {e["param"]: e["value"] for e in events}
        assert params["fio2"] == 40
        assert params["peep"] == 8

    def test_standalone_fio2_flowsheet(self):
        """'FIO2 : 0.2 %' standalone."""
        lines = ["FIO2 : 60 %"]
        events = _extract_from_lines(lines, "2026-01-10")
        assert len(events) == 1
        assert events[0]["param"] == "fio2"
        assert events[0]["value"] == 60


# ── Negative tests ─────────────────────────────────────────────────

class TestNegatives:
    def test_empty_lines(self):
        events = _extract_from_lines([], "2026-01-10")
        assert events == []

    def test_no_vent_content(self):
        lines = [
            "Patient resting comfortably.",
            "Vitals stable.",
            "Plan: continue current management.",
        ]
        events = _extract_from_lines(lines, "2026-01-10")
        assert events == []

    def test_slums_not_extracted(self):
        lines = ["Saint Louis University Mental Status (SLUMS)"]
        events = _extract_from_lines(lines, "2026-01-10")
        assert events == []

    def test_isbt_not_extracted(self):
        lines = ["•    Isbt Product Code       01/01/2026      E8341V00"]
        events = _extract_from_lines(lines, "2026-01-10")
        assert events == []


# ── Public API integration ─────────────────────────────────────────

class TestExtractVentilatorSettings:
    def test_none_days_data(self):
        result = extract_ventilator_settings({}, None)
        assert result["events"] == []
        assert result["summary"]["total_events"] == 0

    def test_empty_days(self):
        result = extract_ventilator_settings({}, {"days": {}})
        assert result["events"] == []

    def test_full_pipeline(self):
        days_data = _days_data_from_lines([
            "O2 Device: Ventilator",
            "Vent Settings",
            "Resp Rate (Set): 24",
            "Vt (Set, ml): 460 ml",
            "PEEP/CPAP : 14 cm H20",
            "FIO2 : 60 %",
            "Ventilated Patient?: Yes",
        ])
        result = extract_ventilator_settings({}, days_data)
        assert result["summary"]["total_events"] >= 5
        assert "2026-01-10" in result["summary"]["mechanical_vent_days"]
        assert "fio2" in result["summary"]["params_found"]
        assert "peep" in result["summary"]["params_found"]
        assert "tidal_volume" in result["summary"]["params_found"]
        assert "resp_rate_set" in result["summary"]["params_found"]

        # Every event has raw_line_id
        for ev in result["events"]:
            assert "raw_line_id" in ev
            assert len(ev["raw_line_id"]) == 16

    def test_dedup_across_days(self):
        """Same content on two different days → distinct events."""
        days_data = {
            "days": {
                "2026-01-10": {"raw_lines": ["O2 Device: Ventilator"]},
                "2026-01-11": {"raw_lines": ["O2 Device: Ventilator"]},
            }
        }
        result = extract_ventilator_settings({}, days_data)
        assert result["summary"]["total_events"] == 2
        assert result["summary"]["days_with_vent_data"] == 2

    def test_niv_summary(self):
        days_data = _days_data_from_lines([
            "Non-Invasive Mechanical Ventilation\t01/02\t0558\t1 more",
        ], day="2026-01-02")
        result = extract_ventilator_settings({}, days_data)
        assert "2026-01-02" in result["summary"]["niv_days"]
