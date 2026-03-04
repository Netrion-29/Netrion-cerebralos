"""
Tests for runtime NTDS slug normalization at source.

Validates that _slugify in run_all_events.py produces correct,
deterministic, filesystem-safe slugs and matches the canonical
_slugify behavior from cerebralos/ingest/parse_patient_txt.py.
"""

from __future__ import annotations

import pytest

from cerebralos.ntds_logic.run_all_events import _slugify


# ── Space normalization ──────────────────────────────────────────────


class TestSlugifySpaces:
    def test_space_to_underscore(self):
        assert _slugify("Charlotte Howlett") == "Charlotte_Howlett"

    def test_multiple_spaces(self):
        assert _slugify("Betty  Roll") == "Betty_Roll"

    def test_leading_trailing_spaces(self):
        assert _slugify("  Anna Dennis  ") == "Anna_Dennis"

    def test_tabs_and_spaces(self):
        assert _slugify("Robert\t Altmeyer") == "Robert_Altmeyer"


# ── Already-normalized names ─────────────────────────────────────────


class TestSlugifyAlreadyNormalized:
    def test_underscore_name_unchanged(self):
        assert _slugify("Anna_Dennis") == "Anna_Dennis"

    def test_simple_name_unchanged(self):
        assert _slugify("TimothyCowan") == "TimothyCowan"


# ── Special character handling ───────────────────────────────────────


class TestSlugifySpecialChars:
    def test_dots_stripped(self):
        assert _slugify("Dr. Smith") == "Dr_Smith"

    def test_hyphens_stripped(self):
        assert _slugify("Mary-Jane Watson") == "Mary_Jane_Watson"

    def test_consecutive_specials_collapsed(self):
        assert _slugify("A---B...C") == "A_B_C"


# ── Edge cases ───────────────────────────────────────────────────────


class TestSlugifyEdgeCases:
    def test_empty_string(self):
        assert _slugify("") == "UNKNOWN_PATIENT"

    def test_whitespace_only(self):
        assert _slugify("   ") == "UNKNOWN_PATIENT"

    def test_only_special_chars(self):
        assert _slugify("...---") == "UNKNOWN_PATIENT"

    def test_single_word(self):
        assert _slugify("Anna") == "Anna"


# ── Canonical parity ────────────────────────────────────────────────


class TestSlugifyCanonicalParity:
    """Verify run_all_events._slugify matches parse_patient_txt._slugify."""

    def test_matches_canonical(self):
        from cerebralos.ingest.parse_patient_txt import _slugify as canonical_slugify
        test_names = [
            "Charlotte Howlett",
            "William Simmons",
            "Anna_Dennis",
            "Betty Roll",
            "  Ronald Bittner  ",
            "Dr. Smith",
            "Mary-Jane Watson",
            "",
            "   ",
        ]
        for name in test_names:
            assert _slugify(name) == canonical_slugify(name), (
                f"Parity mismatch for {name!r}: "
                f"run_all={_slugify(name)!r}, canonical={canonical_slugify(name)!r}"
            )


# ── Determinism ──────────────────────────────────────────────────────


class TestSlugifyDeterminism:
    def test_repeated_calls_identical(self):
        for _ in range(100):
            assert _slugify("Charlotte Howlett") == "Charlotte_Howlett"

    def test_order_independent(self):
        names = ["Charlotte Howlett", "William Simmons", "Betty Roll"]
        results_forward = [_slugify(n) for n in names]
        results_reverse = [_slugify(n) for n in reversed(names)]
        assert results_forward == list(reversed(results_reverse))
