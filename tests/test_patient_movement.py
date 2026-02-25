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
  - Summary statistics (incl. v2 enrichments)
  - Determinism (same input → same output)
  - Dedup on (unit, date_raw, time_raw, event_type)
  - Bare entry headers (Checked In/Out — no body fields)
  - Medication-line guard (reject false-match med lines)
  - Additional section boundaries (Procedures, Orders, etc.)
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
        assert s["admission_ts"] is None
        assert s["discharge_ts"] is None
        assert s["discharge_disposition_final"] is None
        assert s["transfer_count"] == 0
        assert s["units_visited"] == []
        assert s["rooms_visited"] == []
        assert s["event_type_counts"] == {}

    def test_with_entries(self):
        entries = [
            {
                "unit": "ICU",
                "date_raw": "01/02",
                "time_raw": "1803",
                "event_type": "Discharge",
                "level_of_care": "ICU",
                "service": "Trauma",
                "room": "4810",
                "discharge_disposition": "Home",
            },
            {
                "unit": "ICU",
                "date_raw": "01/01",
                "time_raw": "0504",
                "event_type": "Transfer In",
                "level_of_care": "ICU",
                "service": "Trauma",
                "room": "4810",
                "discharge_disposition": None,
            },
            {
                "unit": "ED",
                "date_raw": "01/01",
                "time_raw": "0138",
                "event_type": "Admission",
                "level_of_care": None,
                "service": "Emergency",
                "room": "1858",
                "discharge_disposition": None,
            },
        ]
        s = _build_summary(entries)
        assert s["movement_event_count"] == 3
        assert s["first_movement_ts"] == "01/01 0138"
        assert s["admission_ts"] == "01/01 0138"
        assert s["discharge_ts"] == "01/02 1803"
        assert s["discharge_disposition_final"] == "Home"
        assert s["transfer_count"] == 1
        assert s["units_visited"] == ["ICU", "ED"]
        assert s["rooms_visited"] == ["4810", "1858"]
        assert "ICU" in s["levels_of_care"]
        assert "Trauma" in s["services_seen"]
        assert "Emergency" in s["services_seen"]
        assert s["event_type_counts"] == {
            "Discharge": 1, "Transfer In": 1, "Admission": 1,
        }


class TestExtractPatientMovement:
    def test_fail_closed_no_source_file(self):
        result = extract_patient_movement(
            {"days": {}},
            {"meta": {}},
        )
        assert result["source_rule_id"] == "no_patient_movement_section"
        assert result["entries"] == []
        assert result["summary"]["movement_event_count"] == 0
        assert result["summary"]["admission_ts"] is None
        assert result["summary"]["discharge_disposition_final"] is None
        assert result["summary"]["event_type_counts"] == {}
        assert result["summary"]["rooms_visited"] == []

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


# ── v2 refinement tests ────────────────────────────────────────────

SAMPLE_PM_BARE_ENTRIES = textwrap.dedent("""\
    Patient Movement\t\t\t\r
    Ortho Neuro Trauma Care Center\t01/02\t1741\tDischarge

    Room
    4630

    Bed
    4630-01

    Patient Class
    Inpatient

    Level of Care
    Med/Surg

    Service
    Trauma

    Discharge Provider
    Kuhlenschmidt, Kali Marie

    Discharge Disposition
    Home

    Deaconess Clinic Urgent Care North\t12/31\t1511\tChecked Out

    Deaconess Clinic Urgent Care North\t12/31\t1323\tChecked In

""")


SAMPLE_PM_WITH_DUPLICATES = textwrap.dedent("""\
    Patient Movement\t\t\t\r
    ICU\t01/02\t1803\tDischarge

    Room
    4637

    Bed
    4637-01

    Patient Class
    Inpatient

    Service
    General Medical

    ICU\t01/02\t1803\tDischarge

    Room
    4637

    Bed
    4637-01

    Patient Class
    Inpatient

    Service
    General Medical

    ED\t01/01\t0138\tAdmission

    Room
    1858

    Bed
    09

    Patient Class
    Emergency

    Service
    Emergency

""")


SAMPLE_PM_WITH_MEDS_AFTER_SCHEDULED = textwrap.dedent("""\
    Patient Movement\t\t\t\r
    ICU\t01/01\t0227\tTransfer In

    Room
    4814

    Bed
    4814-01

    Patient Class
    Inpatient

    Service
    Trauma

    Scheduled
    acetaminophen (TYLENOL) tablet 1,000 mg\t01/24\t0511\t33 more
    Given
    Dose 1,000 mg Oral
""")


class TestBareEntryHeaders:
    """Checked In / Checked Out entries have zero body fields."""

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

    def test_bare_entries_parsed(self):
        lines = self._get_section_lines(SAMPLE_PM_BARE_ENTRIES)
        assert lines is not None
        entries, warnings = _parse_movement_entries(lines)

        assert len(entries) == 3

        # Checked Out
        e1 = entries[1]
        assert e1["event_type"] == "Checked Out"
        assert e1["unit"] == "Deaconess Clinic Urgent Care North"
        assert e1["room"] is None
        assert e1["bed"] is None
        assert e1["patient_class"] is None
        assert e1["service"] is None
        assert e1["providers"] == {}

        # Checked In
        e2 = entries[2]
        assert e2["event_type"] == "Checked In"
        assert e2["room"] is None

    def test_event_type_counts_include_checked(self):
        lines = self._get_section_lines(SAMPLE_PM_BARE_ENTRIES)
        entries, _ = _parse_movement_entries(lines)
        s = _build_summary(entries)
        assert s["event_type_counts"]["Checked Out"] == 1
        assert s["event_type_counts"]["Checked In"] == 1
        assert s["event_type_counts"]["Discharge"] == 1
        # Checked In/Out should NOT count as transfers
        assert s["transfer_count"] == 0


class TestDedup:
    """Deterministic dedup on (unit, date_raw, time_raw, event_type)."""

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

    def test_dedup_removes_exact_duplicate(self):
        lines = self._get_section_lines(SAMPLE_PM_WITH_DUPLICATES)
        assert lines is not None
        entries, warnings = _parse_movement_entries(lines)

        # Should have 2 unique entries (the duplicate Discharge removed)
        assert len(entries) == 2
        assert entries[0]["event_type"] == "Discharge"
        assert entries[1]["event_type"] == "Admission"

        # Should have a dedup warning
        assert any("dedup_removed" in w for w in warnings)

    def test_dedup_preserves_different_timestamps(self):
        """Entries at same unit with different times are NOT deduped."""
        content = textwrap.dedent("""\
            Patient Movement\t\t\t\r
            ED\t01/01\t1927\tTransfer In

            Room
            1830

            Bed
            09

            Patient Class
            Inpatient

            Service
            Emergency

            ED\t01/01\t1926\tTransfer In

            Room
            MCTRANSITION

            Bed
            NONE

            Patient Class
            Inpatient

            Service
            Emergency

        """)
        lines = self._get_section_lines(content)
        entries, warnings = _parse_movement_entries(lines)
        assert len(entries) == 2
        assert not any("dedup_removed" in w for w in warnings)


class TestMedicationLineGuard:
    """Medication lines after Scheduled should not be matched as entries."""

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

    def test_scheduled_boundary_stops_parsing(self):
        lines = self._get_section_lines(SAMPLE_PM_WITH_MEDS_AFTER_SCHEDULED)
        assert lines is not None
        entries, warnings = _parse_movement_entries(lines)

        # Should only have 1 entry (the Transfer In), NOT the med line
        assert len(entries) == 1
        assert entries[0]["event_type"] == "Transfer In"


class TestAdditionalBoundaries:
    """Section boundaries beyond the original set."""

    def test_procedures_boundary(self):
        content = textwrap.dedent("""\
            Patient Movement\t\t\t\r
            ICU\t01/01\t0227\tTransfer In

            Room
            4814

            Patient Class
            Inpatient

            Service
            Trauma

            Procedures
            Intubation 01/01 0300
        """)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write(content)
            path = f.name

        try:
            lines = _extract_pm_section_lines(path)
            assert lines is not None
            for _, text in lines:
                assert "Procedures" not in text.strip()
                assert "Intubation" not in text.strip()
        finally:
            os.unlink(path)

    def test_orders_boundary(self):
        content = textwrap.dedent("""\
            Patient Movement\t\t\t\r
            ED\t01/01\t0138\tAdmission

            Room
            1858

            Patient Class
            Emergency

            Service
            Emergency

            Orders
            CBC ordered 01/01 0200
        """)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write(content)
            path = f.name

        try:
            lines = _extract_pm_section_lines(path)
            assert lines is not None
            for _, text in lines:
                assert "Orders" not in text.strip()
                assert "CBC" not in text.strip()
        finally:
            os.unlink(path)


class TestSummaryEnrichments:
    """New v2 summary fields: admission_ts, discharge_disposition_final,
    event_type_counts, rooms_visited."""

    def test_admission_ts_earliest(self):
        """admission_ts should be the earliest Admission event."""
        entries = [
            {"unit": "ICU", "date_raw": "01/02", "time_raw": "1803",
             "event_type": "Discharge", "level_of_care": "ICU",
             "service": "Trauma", "room": "4810",
             "discharge_disposition": "Home"},
            {"unit": "ED", "date_raw": "01/01", "time_raw": "0500",
             "event_type": "Admission", "level_of_care": None,
             "service": "Emergency", "room": "1858",
             "discharge_disposition": None},
            {"unit": "External", "date_raw": "12/31", "time_raw": "2000",
             "event_type": "Admission", "level_of_care": None,
             "service": "Emergency", "room": "EX01",
             "discharge_disposition": None},
        ]
        s = _build_summary(entries)
        # Entries are reverse-chron → last Admission is earliest
        assert s["admission_ts"] == "12/31 2000"

    def test_no_admission_event(self):
        """admission_ts is None when no Admission events exist."""
        entries = [
            {"unit": "ICU", "date_raw": "01/01", "time_raw": "0500",
             "event_type": "Transfer In", "level_of_care": "ICU",
             "service": "Trauma", "room": "4814",
             "discharge_disposition": None},
        ]
        s = _build_summary(entries)
        assert s["admission_ts"] is None

    def test_rooms_visited_unique_ordered(self):
        entries = [
            {"unit": "ICU", "date_raw": "01/02", "time_raw": "1803",
             "event_type": "Discharge", "level_of_care": "ICU",
             "service": "Trauma", "room": "4810",
             "discharge_disposition": "Home"},
            {"unit": "ICU", "date_raw": "01/01", "time_raw": "0504",
             "event_type": "Transfer In", "level_of_care": "ICU",
             "service": "Trauma", "room": "4810",
             "discharge_disposition": None},
            {"unit": "ED", "date_raw": "01/01", "time_raw": "0138",
             "event_type": "Admission", "level_of_care": None,
             "service": "Emergency", "room": "1858",
             "discharge_disposition": None},
        ]
        s = _build_summary(entries)
        assert s["rooms_visited"] == ["4810", "1858"]

    def test_null_room_excluded(self):
        """Null rooms (bare entries) should not appear in rooms_visited."""
        entries = [
            {"unit": "Clinic", "date_raw": "12/31", "time_raw": "1511",
             "event_type": "Checked Out", "level_of_care": None,
             "service": None, "room": None,
             "discharge_disposition": None},
        ]
        s = _build_summary(entries)
        assert s["rooms_visited"] == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
