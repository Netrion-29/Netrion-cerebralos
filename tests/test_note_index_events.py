#!/usr/bin/env python3
"""
Tests for note_index_events_v1 — Note Index / Event-Log Extraction.

Validates:
  - Entry parsing from tab-delimited format
  - Author credential extraction
  - Service field association
  - Section boundary detection
  - Fail-closed on missing/empty data
  - Determinism
  - Summary statistics
"""

import hashlib
import os
import tempfile
import textwrap

import pytest

from cerebralos.features.note_index_events_v1 import (
    _parse_author,
    _extract_notes_section_lines,
    _parse_note_entries,
    _build_summary,
    extract_note_index_events,
)


# ── Helper ──────────────────────────────────────────────────────────

def _make_raw_file(content: str) -> str:
    """Write content to a temp file and return the path."""
    fd, path = tempfile.mkstemp(suffix=".txt")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    return path


# ── Realistic Notes section content ────────────────────────────────

NOTES_SECTION_RICH = textwrap.dedent("""\
    Imaging, EKG, and Radiology
    Some imaging content here

    Notes\t\t\t\t\r
    Consults\t01/01\t1020\tChacko, Chris E, MD

    Service
    Otolaryngology

    Consults\t01/01\t0553\tDuran, Adriano M, DO

    Service
    Internal Medicine

    Discharge Summary\t01/02\t1549\tIglesias, Roberto, MD

    Service
    General Surgeon

    ED Notes\t01/01\t0002\tPROVIDER, SCANNING

    ED Provider Notes\t01/01\t0213\tYoder, Lindsay, DO

    H&P\t01/01\t0252\tIglesias, Roberto, MD

    Service
    General Surgeon

    Plan of Care\t01/01\t1611\tLauer, Jenna L, RN

    Service
    Nurse to Nurse

    Progress Notes\t01/02\t1351\tAdams, Phillip, MD

    Service
    Hospitalist

    Triage Assessment\t01/01\t0207\tService, Kalynn M, RN
    LDAs
    Some LDA content
""")

NOTES_SECTION_EMPTY = textwrap.dedent("""\
    Some header content
    Notes\t\t\r
    LDAs
    Some LDA content
""")

NO_NOTES_SECTION = textwrap.dedent("""\
    Some header content
    Patient details here
    Labs
    Some lab data
""")


# ── Tests: _parse_author ───────────────────────────────────────────

class TestParseAuthor:
    def test_md_credential(self):
        name, cred = _parse_author("Chacko, Chris E, MD")
        assert name == "Chacko, Chris E"
        assert cred == "MD"

    def test_do_credential(self):
        name, cred = _parse_author("Duran, Adriano M, DO")
        assert name == "Duran, Adriano M"
        assert cred == "DO"

    def test_rn_credential(self):
        name, cred = _parse_author("Lauer, Jenna L, RN")
        assert name == "Lauer, Jenna L"
        assert cred == "RN"

    def test_multi_credential(self):
        name, cred = _parse_author("Sharp, Kelsey, PT, DPT")
        assert name == "Sharp, Kelsey"
        assert cred == "PT, DPT"

    def test_scanning_provider(self):
        name, cred = _parse_author("PROVIDER, SCANNING")
        assert name == "PROVIDER"
        assert cred == "SCANNING"

    def test_no_credential(self):
        name, cred = _parse_author("Smith")
        assert name == "Smith"
        assert cred is None

    def test_np_credential(self):
        name, cred = _parse_author("Meehan, Sarah M, NP")
        assert name == "Meehan, Sarah M"
        assert cred == "NP"


# ── Tests: _extract_notes_section_lines ─────────────────────────────

class TestExtractNotesSectionLines:
    def test_rich_notes_section(self):
        path = _make_raw_file(NOTES_SECTION_RICH)
        try:
            result = _extract_notes_section_lines(path)
            assert result is not None
            assert len(result) > 0
            # Should not include the Notes header line itself
            for _, line in result:
                assert line.strip().replace("\r", "") != "Notes"
            # Should not include lines after LDAs
            texts = [line.strip() for _, line in result]
            assert "Some LDA content" not in texts
        finally:
            os.unlink(path)

    def test_empty_notes_section(self):
        path = _make_raw_file(NOTES_SECTION_EMPTY)
        try:
            result = _extract_notes_section_lines(path)
            assert result is not None
            # Section exists but is empty (only blank lines between Notes and LDAs)
            non_blank = [t for _, t in result if t.strip()]
            assert len(non_blank) == 0
        finally:
            os.unlink(path)

    def test_no_notes_section(self):
        path = _make_raw_file(NO_NOTES_SECTION)
        try:
            result = _extract_notes_section_lines(path)
            assert result is None
        finally:
            os.unlink(path)

    def test_nonexistent_file(self):
        result = _extract_notes_section_lines("/tmp/nonexistent_file_xyz.txt")
        assert result is None

    def test_none_path(self):
        result = _extract_notes_section_lines("")
        assert result is None


# ── Tests: _parse_note_entries ──────────────────────────────────────

class TestParseNoteEntries:
    def test_rich_entries(self):
        path = _make_raw_file(NOTES_SECTION_RICH)
        try:
            section_lines = _extract_notes_section_lines(path)
            assert section_lines is not None
            entries, warnings = _parse_note_entries(section_lines)
            assert len(entries) == 9
            # First entry
            assert entries[0]["note_type"] == "Consults"
            assert entries[0]["date_raw"] == "01/01"
            assert entries[0]["time_raw"] == "1020"
            assert entries[0]["author_name"] == "Chacko, Chris E"
            assert entries[0]["author_credential"] == "MD"
            assert entries[0]["service"] == "Otolaryngology"
            # ED Notes entry (no service)
            ed_entries = [e for e in entries if e["note_type"] == "ED Notes"]
            assert len(ed_entries) == 1
            assert ed_entries[0]["service"] is None
            # All entries have raw_line_id
            for e in entries:
                assert "raw_line_id" in e
                assert len(e["raw_line_id"]) == 64  # SHA-256 hex
        finally:
            os.unlink(path)

    def test_empty_section(self):
        path = _make_raw_file(NOTES_SECTION_EMPTY)
        try:
            section_lines = _extract_notes_section_lines(path)
            assert section_lines is not None
            entries, warnings = _parse_note_entries(section_lines)
            assert len(entries) == 0
        finally:
            os.unlink(path)

    def test_service_association(self):
        """Service field is correctly associated with the preceding entry."""
        path = _make_raw_file(NOTES_SECTION_RICH)
        try:
            section_lines = _extract_notes_section_lines(path)
            entries, _ = _parse_note_entries(section_lines)
            # Consults entry 1 should have Otolaryngology
            assert entries[0]["service"] == "Otolaryngology"
            # Consults entry 2 should have Internal Medicine
            assert entries[1]["service"] == "Internal Medicine"
            # H&P should have General Surgeon
            hp_entries = [e for e in entries if e["note_type"] == "H&P"]
            assert len(hp_entries) == 1
            assert hp_entries[0]["service"] == "General Surgeon"
        finally:
            os.unlink(path)


# ── Tests: _build_summary ───────────────────────────────────────────

class TestBuildSummary:
    def test_empty_entries(self):
        summary = _build_summary([])
        assert summary["note_index_event_count"] == 0
        assert summary["unique_authors_count"] == 0
        assert summary["unique_note_types_count"] == 0
        assert summary["services_detected"] == []
        assert summary["consult_note_count"] == 0

    def test_rich_summary(self):
        path = _make_raw_file(NOTES_SECTION_RICH)
        try:
            section_lines = _extract_notes_section_lines(path)
            entries, _ = _parse_note_entries(section_lines)
            summary = _build_summary(entries)
            assert summary["note_index_event_count"] == 9
            assert summary["unique_authors_count"] > 0
            assert summary["unique_note_types_count"] > 0
            assert summary["consult_note_count"] == 2
            assert "Otolaryngology" in summary["services_detected"]
            assert "Internal Medicine" in summary["services_detected"]
        finally:
            os.unlink(path)


# ── Tests: extract_note_index_events (full API) ────────────────────

class TestExtractNoteIndexEvents:
    def test_fail_closed_no_source_file(self):
        """No source_file in meta → fail-closed."""
        result = extract_note_index_events(
            {"days": {}},
            {"meta": {}, "days": {}},
        )
        assert result["source_rule_id"] == "no_notes_section"
        assert result["entries"] == []
        assert result["summary"]["note_index_event_count"] == 0

    def test_fail_closed_nonexistent_file(self):
        """source_file points to nonexistent file → fail-closed."""
        result = extract_note_index_events(
            {"days": {}},
            {"meta": {"source_file": "/nonexistent/path.txt"}, "days": {}},
        )
        assert result["source_rule_id"] == "no_notes_section"
        assert result["entries"] == []
        assert "source_file_not_found" in result["warnings"]

    def test_fail_closed_no_notes_section(self):
        """File exists but no Notes section → fail-closed."""
        path = _make_raw_file(NO_NOTES_SECTION)
        try:
            result = extract_note_index_events(
                {"days": {}},
                {"meta": {"source_file": path}, "days": {}},
            )
            assert result["source_rule_id"] == "no_notes_section"
            assert result["entries"] == []
        finally:
            os.unlink(path)

    def test_rich_extraction(self):
        """Full extraction from rich Notes section."""
        path = _make_raw_file(NOTES_SECTION_RICH)
        try:
            result = extract_note_index_events(
                {"days": {}},
                {"meta": {"source_file": path}, "days": {}},
            )
            assert result["source_rule_id"] == "note_index_raw_file"
            assert len(result["entries"]) == 9
            assert result["summary"]["note_index_event_count"] == 9
            assert result["summary"]["consult_note_count"] == 2
            assert len(result["evidence"]) == 9
            # Every evidence entry has raw_line_id
            for ev in result["evidence"]:
                assert "raw_line_id" in ev
                assert ev["role"] == "note_index_entry"
        finally:
            os.unlink(path)

    def test_determinism(self):
        """Two runs produce identical output."""
        path = _make_raw_file(NOTES_SECTION_RICH)
        try:
            r1 = extract_note_index_events(
                {"days": {}},
                {"meta": {"source_file": path}, "days": {}},
            )
            r2 = extract_note_index_events(
                {"days": {}},
                {"meta": {"source_file": path}, "days": {}},
            )
            assert r1 == r2
        finally:
            os.unlink(path)

    def test_entries_have_no_internal_fields(self):
        """Output entries should not have line_number (internal only)."""
        path = _make_raw_file(NOTES_SECTION_RICH)
        try:
            result = extract_note_index_events(
                {"days": {}},
                {"meta": {"source_file": path}, "days": {}},
            )
            for e in result["entries"]:
                assert "line_number" not in e
        finally:
            os.unlink(path)


# ── Tests: Section boundary detection ───────────────────────────────

class TestSectionBoundary:
    def test_ldas_boundary(self):
        """Notes section ends at LDAs."""
        content = "Notes\r\nH&P\t01/01\t0252\tDr. Smith, MD\n\nLDAs\nSome LDA\n"
        path = _make_raw_file(content)
        try:
            lines = _extract_notes_section_lines(path)
            assert lines is not None
            texts = [t.strip() for _, t in lines]
            assert "Some LDA" not in texts
        finally:
            os.unlink(path)

    def test_patient_movement_boundary(self):
        """Notes section ends at Patient Movement."""
        content = "Notes\r\nH&P\t01/01\t0252\tDr. Smith, MD\n\nPatient Movement\nSome PM\n"
        path = _make_raw_file(content)
        try:
            lines = _extract_notes_section_lines(path)
            assert lines is not None
            texts = [t.strip() for _, t in lines]
            assert "Some PM" not in texts
        finally:
            os.unlink(path)

    def test_flowsheets_boundary(self):
        """Notes section ends at Flowsheets."""
        content = "Notes\r\nH&P\t01/01\t0252\tDr. Smith, MD\n\nFlowsheets\nSome FS\n"
        path = _make_raw_file(content)
        try:
            lines = _extract_notes_section_lines(path)
            assert lines is not None
            texts = [t.strip() for _, t in lines]
            assert "Some FS" not in texts
        finally:
            os.unlink(path)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
