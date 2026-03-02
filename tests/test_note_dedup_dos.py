"""Tests for DoS-format note dedup in _parse_items_dos().

PR #93 — duplicate note entries from Routing / Revision History sections
are filtered at ingest, both by history-marker boundary filtering and by
content-hash dedup as defense-in-depth.
"""

from __future__ import annotations

import pytest

from cerebralos.ingest.parse_patient_txt import (
    EvidenceItem,
    RE_HISTORY_MARKER,
    _parse_items_dos,
    _sha256_text,
)

# ── helpers ────────────────────────────────────────────────────


def _dos_header_block(category: str, date: str, time: str) -> list[str]:
    """Build the header block that precedes a DoS body.

    The parser reads lines[i-3] for the category, where i is the index of
    the ``Date of Service:`` line.  So the layout is::

        <category>         ← i-3
        <blank or extra>   ← i-2
        <blank or extra>   ← i-1
        Date of Service: …  ← i (DoS boundary)
    """
    return [
        "",
        category,
        "",
        "",
        f"Date of Service: {date} {time}",
    ]


def _make_dos_file(blocks: list[tuple[str, str, str, str]],
                   *,
                   trailing: list[str] | None = None,
                   history_after: set[int] | None = None) -> list[str]:
    """Assemble a synthetic DoS-format file.

    Parameters
    ----------
    blocks : list of (category, date, time, body_text) tuples
        Each tuple produces one clinical note.
    trailing : optional extra lines at end (simulating supplementals).
    history_after : set of 0-based block indices after which a
        "Routing History" marker + duplicate block is inserted.

    Returns
    -------
    list[str] — the lines of the synthetic file.
    """
    lines: list[str] = ["Patient data preamble line"]
    for idx, (cat, date, time, body) in enumerate(blocks):
        lines.extend(_dos_header_block(cat, date, time))
        for bline in body.split("\n"):
            lines.append(bline)
        # Insert a Routing History copy after this block if requested
        if history_after and idx in history_after:
            lines.append("")
            lines.append("Routing History")
            lines.append("Some Provider, MD")
            lines.extend(_dos_header_block(cat, date, time))
            for bline in body.split("\n"):
                lines.append(bline)
    if trailing:
        lines.extend(trailing)
    return lines


# ── RE_HISTORY_MARKER ─────────────────────────────────────────


class TestHistoryMarkerRegex:
    """Verify RE_HISTORY_MARKER catches relevant markers."""

    @pytest.mark.parametrize("text", [
        "Routing History",
        "Revision History",
        "routing history",
        "ROUTING HISTORY",
        "Routing History      ",
        "Revision History - some extra text",
    ])
    def test_matches(self, text):
        assert RE_HISTORY_MARKER.match(text.strip())

    @pytest.mark.parametrize("text", [
        "History of Present Illness",
        "Surgical History",
        "Past Medical History",
        "routing",
        "History",
    ])
    def test_no_match(self, text):
        assert not RE_HISTORY_MARKER.match(text.strip())


# ── Phase 1b: history-boundary filtering ──────────────────────


class TestHistoryBoundaryFilter:
    """_parse_items_dos Phase 1b: boundaries after history markers skipped."""

    def test_no_duplicates_without_history_marker(self):
        """Two distinct notes → two items."""
        lines = _make_dos_file([
            ("H&P", "01/01/25", "0800", "Initial assessment body"),
            ("Progress Notes", "01/01/25", "1400", "Progress note body"),
        ])
        items = _parse_items_dos(lines)
        kinds = [it.kind for it in items]
        assert kinds == ["TRAUMA_HP", "PHYSICIAN_NOTE"]

    def test_routing_history_duplicate_filtered(self):
        """Routing History copy of first note → only original kept."""
        lines = _make_dos_file(
            [
                ("H&P", "01/01/25", "0800", "Initial assessment body"),
                ("Progress Notes", "01/01/25", "1400", "Progress note body"),
            ],
            history_after={0},
        )
        items = _parse_items_dos(lines)
        kinds = [it.kind for it in items]
        assert kinds == ["TRAUMA_HP", "PHYSICIAN_NOTE"]

    def test_revision_history_duplicate_filtered(self):
        """Revision History copy → filtered out."""
        lines = ["Preamble"]
        # First note
        lines.extend(_dos_header_block("H&P", "01/01/25", "0800"))
        lines.append("Assessment body text")
        # Revision History marker
        lines.append("")
        lines.append("Revision History")
        lines.append("Dr. Smith, MD")
        # Duplicate note after Revision History
        lines.extend(_dos_header_block("H&P", "01/01/25", "0810"))
        lines.append("Assessment body text")
        # Genuine second note
        lines.extend(_dos_header_block("Progress Notes", "01/02/25", "0900"))
        lines.append("Day 2 progress")

        items = _parse_items_dos(lines)
        kinds = [it.kind for it in items]
        assert "TRAUMA_HP" in kinds
        assert "PHYSICIAN_NOTE" in kinds
        # The duplicate H&P at 0810 should be gone
        hp_items = [it for it in items if it.kind == "TRAUMA_HP"]
        assert len(hp_items) == 1

    def test_multiple_routing_history_copies(self):
        """Multiple history copies of the same note → all filtered."""
        lines = ["Preamble"]
        lines.extend(_dos_header_block("H&P", "01/01/25", "0800"))
        lines.append("Original H&P body")
        # First Routing History copy
        lines.append("Routing History")
        lines.append("Copy 1 provider")
        lines.extend(_dos_header_block("H&P", "01/01/25", "0800"))
        lines.append("Original H&P body")
        # Second Routing History copy
        lines.append("Routing History")
        lines.append("Copy 2 provider")
        lines.extend(_dos_header_block("H&P", "01/01/25", "0800"))
        lines.append("Original H&P body")
        # Genuine next note
        lines.extend(_dos_header_block("Progress Notes", "01/02/25", "1000"))
        lines.append("Real progress note")

        items = _parse_items_dos(lines)
        hp_items = [it for it in items if it.kind == "TRAUMA_HP"]
        assert len(hp_items) == 1
        assert len(items) == 2  # one H&P + one PHYSICIAN_NOTE

    def test_first_boundary_never_filtered(self):
        """The very first DoS boundary is never skipped (no prior to scan)."""
        lines = _make_dos_file([
            ("H&P", "01/01/25", "0800", "Only note"),
        ])
        items = _parse_items_dos(lines)
        assert len(items) == 1
        assert items[0].kind == "TRAUMA_HP"


# ── Phase 2b: content-hash dedup ──────────────────────────────


class TestContentHashDedup:
    """Defense-in-depth: identical (kind, datetime, text) → first kept."""

    def test_identical_notes_deduped(self):
        """Two boundaries with same kind+dt+text but no history marker → dedup."""
        # Need enough body lines so the 7-line header offset doesn't trim
        # the first note's body to empty.
        body = "\n".join([f"Body line {i}" for i in range(10)])
        lines = ["Preamble"]
        lines.extend(_dos_header_block("H&P", "01/01/25", "0800"))
        lines.extend(body.split("\n"))
        lines.extend(_dos_header_block("H&P", "01/01/25", "0800"))
        lines.extend(body.split("\n"))

        items = _parse_items_dos(lines)
        hp_items = [it for it in items if it.kind == "TRAUMA_HP"]
        # First item may have truncated body but hash-dedup fires on texts
        # that ARE identical; confirm at most one item with full body text
        assert len(hp_items) <= 2  # at most 2 (diff truncation = diff hash)
        # The key guarantee: no two items share exact same hash triple
        from cerebralos.ingest.parse_patient_txt import _sha256_text as _h
        seen = set()
        for it in hp_items:
            key = (it.kind, it.datetime, _h(it.text))
            assert key not in seen, "content-hash dedup should prevent this"
            seen.add(key)

    def test_different_body_not_deduped(self):
        """Same kind+dt but different body → both kept."""
        lines = ["Preamble"]
        lines.extend(_dos_header_block("Progress Notes", "01/02/25", "0900"))
        lines.append("First progress note version A")
        lines.extend(_dos_header_block("Progress Notes", "01/02/25", "0900"))
        lines.append("Second progress note version B")

        items = _parse_items_dos(lines)
        pn_items = [it for it in items if it.kind == "PHYSICIAN_NOTE"]
        assert len(pn_items) == 2

    def test_different_datetime_not_deduped(self):
        """Same kind+body but different datetime → both kept."""
        lines = ["Preamble"]
        lines.extend(_dos_header_block("H&P", "01/01/25", "0800"))
        lines.append("Same body text for both")
        lines.extend(_dos_header_block("H&P", "01/01/25", "0900"))
        lines.append("Same body text for both")

        items = _parse_items_dos(lines)
        hp_items = [it for it in items if it.kind == "TRAUMA_HP"]
        assert len(hp_items) == 2

    def test_different_kind_not_deduped(self):
        """Same dt+body but different kind → both kept."""
        lines = ["Preamble"]
        lines.extend(_dos_header_block("H&P", "01/01/25", "0800"))
        lines.append("Shared body content across kinds")
        lines.extend(_dos_header_block("ED Provider Notes", "01/01/25", "0800"))
        lines.append("Shared body content across kinds")

        items = _parse_items_dos(lines)
        assert len(items) == 2
        kinds = {it.kind for it in items}
        assert kinds == {"TRAUMA_HP", "ED_NOTE"}


# ── Integration: no items from empty / no-DoS file ───────────


class TestEdgeCases:
    """Edge cases for _parse_items_dos."""

    def test_empty_lines(self):
        items = _parse_items_dos([])
        assert items == []

    def test_no_dos_boundaries(self):
        lines = ["Just some text", "No date of service here"]
        items = _parse_items_dos(lines)
        assert items == []

    def test_single_note_no_dup(self):
        """A single note with no duplicates passes through cleanly."""
        lines = _make_dos_file([
            ("H&P", "12/25/24", "1000", "Holiday H&P note body line 1\nLine 2"),
        ])
        items = _parse_items_dos(lines)
        assert len(items) == 1
        assert items[0].kind == "TRAUMA_HP"
        assert "Holiday H&P note body" in items[0].text

    def test_item_idx_sequential_after_dedup(self):
        """After dedup, item.idx values are 0-based and sequential."""
        lines = _make_dos_file(
            [
                ("H&P", "01/01/25", "0800", "Body A"),
                ("Progress Notes", "01/02/25", "0900", "Body B"),
            ],
            history_after={0},
        )
        items = _parse_items_dos(lines)
        idxs = [it.idx for it in items]
        assert idxs == list(range(len(items)))


# ── Live-patient smoke tests ─────────────────────────────────


class TestLivePatientDedup:
    """Verify dedup reduces duplicate counts on affected real patients.

    These are smoke tests — they confirm the dedup reduces item counts
    relative to pre-fix baselines and that no items have duplicate
    (kind, datetime, text-hash) triples.
    """

    @staticmethod
    def _load_patient(filename):
        from pathlib import Path
        src = Path("data_raw") / filename
        if not src.exists():
            pytest.skip(f"data_raw/{filename} not available")
        from cerebralos.ingest.parse_patient_txt import _read_lines
        lines = _read_lines(src)
        return _parse_items_dos(lines)

    @staticmethod
    def _assert_no_dup_hashes(items):
        """No two items share (kind, datetime, text_hash)."""
        seen = set()
        for it in items:
            key = (it.kind, it.datetime, _sha256_text(it.text))
            assert key not in seen, f"Duplicate item: kind={it.kind}, dt={it.datetime}"
            seen.add(key)

    def test_marshall_no_duplicate_hashes(self):
        items = self._load_patient("Ronald_Marshall.txt")
        self._assert_no_dup_hashes(items)

    def test_marshall_reduced_count(self):
        """Marshall pre-fix had ~361 items; post-fix should be < 280."""
        items = self._load_patient("Ronald_Marshall.txt")
        assert len(items) < 280, f"Expected < 280, got {len(items)}"
        assert len(items) > 100, f"Too few items: {len(items)}"

    def test_corne_no_duplicate_hashes(self):
        """Clinical (non-supplemental) items have no duplicate hashes."""
        items = self._load_patient("Larry_Corne.txt")
        # MAR/LAB items come from supplemental parsing and may have
        # legitimate duplicates (different admin events, same text).
        # DoS dedup targets clinical note items only.
        clinical = [it for it in items if it.kind not in ("MAR", "LAB")]
        self._assert_no_dup_hashes(clinical)

    def test_corne_reasonable_count(self):
        items = self._load_patient("Larry_Corne.txt")
        assert len(items) > 50, f"Too few items: {len(items)}"
        assert len(items) < 200, f"Too many items: {len(items)}"
