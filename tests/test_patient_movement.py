#!/usr/bin/env python3
"""
Tests for patient_movement_v1 feature extractor.

Covers:
  - Parsing of entry headers (unit, date, time, event type)
  - Field extraction (room, bed, patient class, level of care, service)
  - Provider extraction (admitting, attending, discharge)
  - Discharge disposition extraction
  - Section boundary detection
  - Fail-closed when no Patient Movement section
  - Summary statistics
  - Determinism (same input → same output)
"""

import hashlib
import os
import tempfile
import textwrap

import pytest

from cerebralos.features.patient_movement_v1 import (
    _extract_pm_section_lines,
    _make_raw_line_id,
    _parse_movement_entries,
    _build_summary,
    extract_patient_movement,
)


# ── Fixtures ────────────────────────────────────────────────────────

SAMPLE_PM_SECTION = textwrap.dedent("""\
    Patient Movement\t\t\t\r
    Ortho Neuro Trauma Care Center\t01/02\t1803\tDischarge

    Room
    4637

    Bed
    4637-01

    Patient Class
    Inpatient

    Level of Care
    Med/Surg

    Service
    General Medical

    Discharge Provider
    Iglesias, Roberto

    Discharge Disposition
    Home

    Surgical Trauma Cardiovascular ICU\t01/01\t0504\tTransfer In

    Room
    4810

    Bed
    4810-01

    Patient Class
    Inpatient

    Level of Care
    ICU

    Service
    Trauma

    Admitting Provider
    Iglesias, Roberto

    Attending Provider
    Iglesias, Roberto

    Deaconess Midtown Hospital ED\t01/01\t0138\tAdmission

    Room
    1858

    Bed
    09

    Patient Class
    Emergency

    Service
    Emergency

""")

SAMPLE_PM_WITH_BOUNDARY = SAMPLE_PM_SECTION + """\
Meds
Scheduled
Acetaminophen 500mg
"""


# ── Unit tests ──────────────────────────────────────────────────────

class TestExtractPmSectionLines:
    def test_finds_section(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write("Some header content\n\n")
            f.write(SAMPLE_PM_SECTION)
            f.write("\n01/01/26 03:43\nWBC: 8.0\n")
            path = f.name

        try:
            lines = _extract_pm_section_lines(path)
            assert lines is not None
            assert len(lines) > 0
            # Should NOT include the header line itself
            for _, text in lines:
                assert "Patient Movement" not in text.strip() or "\t" in text
        finally:
            os.unlink(path)

    def test_no_section_returns_none(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write("No patient movement here\nJust labs\nWBC: 8.0\n")
            path = f.name

        try:
            lines = _extract_pm_section_lines(path)
            assert lines is None
        finally:
            os.unlink(path)

    def test_nonexistent_file_returns_none(self):
        assert _extract_pm_section_lines("/nonexistent/file.txt") is None

    def test_empty_path_returns_none(self):
        assert _extract_pm_section_lines("") is None

    def test_section_boundary_meds(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write(SAMPLE_PM_WITH_BOUNDARY)
            path = f.name

        try:
            lines = _extract_pm_section_lines(path)
            assert lines is not None
            # Should not include lines after "Meds"
            for _, text in lines:
                stripped = text.strip()
                assert stripped != "Meds"
                assert stripped != "Scheduled"
                assert "Acetaminophen" not in stripped
        finally:
            os.unlink(path)

    def test_section_boundary_labs(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write("Some header\n")
            f.write(SAMPLE_PM_SECTION)
            f.write("01/01/26 03:43\nWBC: 8.0\n")
            path = f.name

        try:
            lines = _extract_pm_section_lines(path)
            assert lines is not None
            for _, text in lines:
                assert "WBC" not in text
        finally:
            os.unlink(path)


class TestParseMovementEntries:
    def _get_section_lines(self, content):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write(content)
            path = f.name

        try:
            lines = _extract_pm_section_lines(path)
            return lines
        finally:
            os.unlink(path)

    def test_parse_three_entries(self):
        lines = self._get_section_lines(SAMPLE_PM_SECTION)
        assert lines is not None
        entries, warnings = _parse_movement_entries(lines)

        assert len(entries) == 3

        # First entry (reverse chron → Discharge)
        e0 = entries[0]
        assert e0["unit"] == "Ortho Neuro Trauma Care Center"
        assert e0["date_raw"] == "01/02"
        assert e0["time_raw"] == "1803"
        assert e0["event_type"] == "Discharge"
        assert e0["room"] == "4637"
        assert e0["bed"] == "4637-01"
        assert e0["patient_class"] == "Inpatient"
        assert e0["level_of_care"] == "Med/Surg"
        assert e0["service"] == "General Medical"
        assert e0["providers"] == {"discharge": "Iglesias, Roberto"}
        assert e0["discharge_disposition"] == "Home"

        # Second entry (Transfer In)
        e1 = entries[1]
        assert e1["unit"] == "Surgical Trauma Cardiovascular ICU"
        assert e1["event_type"] == "Transfer In"
        assert e1["level_of_care"] == "ICU"
        assert e1["service"] == "Trauma"
        assert e1["providers"] == {
            "admitting": "Iglesias, Roberto",
            "attending": "Iglesias, Roberto",
        }
        assert e1["discharge_disposition"] is None

        # Third entry (Admission)
        e2 = entries[2]
        assert e2["unit"] == "Deaconess Midtown Hospital ED"
        assert e2["event_type"] == "Admission"
        assert e2["patient_class"] == "Emergency"
        assert e2["service"] == "Emergency"
        assert e2["providers"] == {}
        assert e2["level_of_care"] is None  # no Level of Care

    def test_raw_line_id_deterministic(self):
        lines = self._get_section_lines(SAMPLE_PM_SECTION)
        entries1, _ = _parse_movement_entries(lines)

        lines2 = self._get_section_lines(SAMPLE_PM_SECTION)
        entries2, _ = _parse_movement_entries(lines2)

        for e1, e2 in zip(entries1, entries2):
            assert e1["raw_line_id"] == e2["raw_line_id"]


class TestBuildSummary:
    def test_empty(self):
        s = _build_summary([])
        assert s["movement_event_count"] == 0
        assert s["first_movement_ts"] is None
        assert s["discharge_ts"] is None
        assert s["transfer_count"] == 0
        assert s["units_visited"] == []

    def test_with_entries(self):
        entries = [
            {
                "unit": "ICU",
                "date_raw": "01/02",
                "time_raw": "1803",
                "event_type": "Discharge",
                "level_of_care": "ICU",
                "service": "Trauma",
            },
            {
                "unit": "ICU",
                "date_raw": "01/01",
                "time_raw": "0504",
                "event_type": "Transfer In",
                "level_of_care": "ICU",
                "service": "Trauma",
            },
            {
                "unit": "ED",
                "date_raw": "01/01",
                "time_raw": "0138",
                "event_type": "Admission",
                "level_of_care": None,
                "service": "Emergency",
            },
        ]
        s = _build_summary(entries)
        assert s["movement_event_count"] == 3
        assert s["first_movement_ts"] == "01/01 0138"
        assert s["discharge_ts"] == "01/02 1803"
        assert s["transfer_count"] == 1
        assert s["units_visited"] == ["ICU", "ED"]
        assert "ICU" in s["levels_of_care"]
        assert "Trauma" in s["services_seen"]
        assert "Emergency" in s["services_seen"]


class TestExtractPatientMovement:
    def test_fail_closed_no_source_file(self):
        result = extract_patient_movement(
            {"days": {}},
            {"meta": {}},
        )
        assert result["source_rule_id"] == "no_patient_movement_section"
        assert result["entries"] == []
        assert result["summary"]["movement_event_count"] == 0

    def test_fail_closed_no_section(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write("No movement section here\nJust text\n")
            path = f.name

        try:
            result = extract_patient_movement(
                {"days": {}},
                {"meta": {"source_file": path}},
            )
            assert result["source_rule_id"] == "no_patient_movement_section"
            assert result["entries"] == []
        finally:
            os.unlink(path)

    def test_full_extraction(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write("Header lines\n\n")
            f.write(SAMPLE_PM_SECTION)
            path = f.name

        try:
            result = extract_patient_movement(
                {"days": {}},
                {"meta": {"source_file": path}},
            )
            assert result["source_rule_id"] == "patient_movement_raw_file"
            assert len(result["entries"]) == 3
            assert result["summary"]["movement_event_count"] == 3
            assert result["summary"]["transfer_count"] == 1
            assert result["summary"]["discharge_ts"] == "01/02 1803"

            # Evidence
            assert len(result["evidence"]) == 3
            for ev in result["evidence"]:
                assert ev["role"] == "patient_movement_entry"
                assert "raw_line_id" in ev
                assert len(ev["raw_line_id"]) == 64  # SHA-256 hex

            # Output entries should not have line_number
            for e in result["entries"]:
                assert "line_number" not in e
                assert "raw_line_id" in e
        finally:
            os.unlink(path)

    def test_determinism(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write("Header\n\n")
            f.write(SAMPLE_PM_SECTION)
            path = f.name

        try:
            r1 = extract_patient_movement(
                {"days": {}},
                {"meta": {"source_file": path}},
            )
            r2 = extract_patient_movement(
                {"days": {}},
                {"meta": {"source_file": path}},
            )
            assert r1["entries"] == r2["entries"]
            assert r1["summary"] == r2["summary"]
            assert r1["evidence"] == r2["evidence"]
        finally:
            os.unlink(path)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
