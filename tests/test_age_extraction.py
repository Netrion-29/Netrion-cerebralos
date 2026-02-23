#!/usr/bin/env python3
"""
Tests for age_extraction_v1 — deterministic patient age extraction.

Covers:
  - DOB from note header → correct age computation
  - Birthday-edge cases (before/after birthday in arrival year)
  - HPI narrative age fallback when no DOB
  - HPI patterns: "65 y.o.", "60 yo", "70 year-old", "55 yr"
  - DATA NOT AVAILABLE when no arrival_datetime
  - DATA NOT AVAILABLE when no timeline items
  - DATA NOT AVAILABLE when no DOB and no HPI age
  - DOB parse failure falls back to HPI
  - Age out of bounds [0, 120] → DNA / skip
  - Evidence traceability (raw_line_id on every entry)
  - Evidence is deterministic (same inputs → same hash)
  - Schema completeness
  - TRAUMA_HP priority over other note types
  - DOB priority order (TRAUMA_HP before PHYSICIAN_NOTE)
  - dob_iso populated when DOB-sourced, null when HPI-sourced
  - Narrative age note appended when fallback used
"""

from __future__ import annotations

import pytest

from cerebralos.features.age_extraction_v1 import (
    extract_patient_age,
    _AGE_MAX,
    _AGE_MIN,
)


# ── Helpers ─────────────────────────────────────────────────────────

def _make_item(
    *,
    item_type: str = "TRAUMA_HP",
    dt: str = "2025-12-18T16:17:00",
    text: str = "",
) -> dict:
    """Build a minimal timeline item."""
    return {
        "type": item_type,
        "dt": dt,
        "payload": {"text": text},
    }


def _make_days_data(
    *,
    arrival_datetime: str | None = "2025-12-18 15:54:00",
    items_by_day: dict[str, list[dict]] | None = None,
) -> dict:
    """Build a minimal days_data structure."""
    meta: dict = {}
    if arrival_datetime:
        meta["arrival_datetime"] = arrival_datetime
        meta["patient_id"] = "test_patient"

    days: dict = {}
    if items_by_day:
        for day_iso, items in items_by_day.items():
            days[day_iso] = {"items": items}

    return {"meta": meta, "days": days}


def _dob_text(dob: str = "3/20/1960") -> str:
    """Build a physician note header with DOB."""
    return (
        f"Deaconess Care Group\n"
        f"Hospital Progress Note\n"
        f"\n"
        f"DOB:  {dob}\n"
        f"\n"
        f"Hospital Course: Patient is doing well.\n"
    )


def _hpi_text(age: int = 65, suffix: str = "y.o. female") -> str:
    """Build a Trauma H&P with HPI narrative age."""
    return (
        f"Trauma H & P\n"
        f"Rachel N Bertram, NP\n"
        f"\n"
        f"HPI: {age} {suffix} with unknown PMH who presents as a trauma.\n"
        f"\n"
        f"Primary Survey:\n"
        f"    Airway: patent\n"
    )


ARRIVAL_TS = "2025-12-18 15:54:00"
ARRIVAL_DAY = "2025-12-18"


# ── Schema validation helper ────────────────────────────────────────

REQUIRED_TOP_KEYS = {
    "age_years", "age_available", "age_source_rule_id",
    "age_source_text", "dob_iso", "evidence", "notes", "warnings",
}

REQUIRED_EVIDENCE_KEYS = {"raw_line_id", "source", "ts", "snippet", "role"}


def _assert_schema(result: dict) -> None:
    """Verify all required keys exist in result."""
    missing = REQUIRED_TOP_KEYS - set(result.keys())
    assert not missing, f"Missing top-level keys: {missing}"
    assert isinstance(result["evidence"], list)
    assert isinstance(result["notes"], list)
    assert isinstance(result["warnings"], list)
    for ev in result["evidence"]:
        ev_missing = REQUIRED_EVIDENCE_KEYS - set(ev.keys())
        assert not ev_missing, f"Evidence entry missing keys: {ev_missing}"
        assert ev["raw_line_id"], "Evidence raw_line_id must be non-empty"


# ── Tests: DOB from note header ─────────────────────────────────────

class TestAgeDobExtraction:
    """DOB-based age extraction (primary strategy)."""

    def test_dob_basic(self) -> None:
        """DOB 3/20/1960, arrival 12/18/2025 → age 65."""
        items = [_make_item(
            item_type="PHYSICIAN_NOTE",
            dt="2025-12-18T12:00:00",
            text=_dob_text("3/20/1960"),
        )]
        days = _make_days_data(
            arrival_datetime=ARRIVAL_TS,
            items_by_day={ARRIVAL_DAY: items},
        )
        result = extract_patient_age(days)
        _assert_schema(result)
        assert result["age_available"] == "yes"
        assert result["age_years"] == 65
        assert result["age_source_rule_id"] == "dob_note_header"
        assert result["dob_iso"] == "1960-03-20"

    def test_dob_before_birthday(self) -> None:
        """DOB 12/25/1960, arrival 12/18/2025 → age 64 (birthday not yet)."""
        items = [_make_item(
            item_type="PHYSICIAN_NOTE",
            dt="2025-12-18T12:00:00",
            text=_dob_text("12/25/1960"),
        )]
        days = _make_days_data(
            arrival_datetime=ARRIVAL_TS,
            items_by_day={ARRIVAL_DAY: items},
        )
        result = extract_patient_age(days)
        _assert_schema(result)
        assert result["age_years"] == 64

    def test_dob_on_birthday(self) -> None:
        """DOB 12/18/1960, arrival 12/18/2025 → age 65 (birthday today)."""
        items = [_make_item(
            item_type="PHYSICIAN_NOTE",
            dt="2025-12-18T12:00:00",
            text=_dob_text("12/18/1960"),
        )]
        days = _make_days_data(
            arrival_datetime=ARRIVAL_TS,
            items_by_day={ARRIVAL_DAY: items},
        )
        result = extract_patient_age(days)
        assert result["age_years"] == 65

    def test_dob_after_birthday(self) -> None:
        """DOB 12/10/1960, arrival 12/18/2025 → age 65."""
        items = [_make_item(
            item_type="PHYSICIAN_NOTE",
            dt="2025-12-18T12:00:00",
            text=_dob_text("12/10/1960"),
        )]
        days = _make_days_data(
            arrival_datetime=ARRIVAL_TS,
            items_by_day={ARRIVAL_DAY: items},
        )
        result = extract_patient_age(days)
        assert result["age_years"] == 65

    def test_dob_date_of_birth_format(self) -> None:
        """Handles 'Date of Birth: M/D/YYYY' format."""
        text = "Patient Name: John Doe   Date of Birth: 5/15/1950   MRN: 12345"
        items = [_make_item(
            item_type="DISCHARGE",
            dt="2025-12-18T12:00:00",
            text=text,
        )]
        days = _make_days_data(
            arrival_datetime=ARRIVAL_TS,
            items_by_day={ARRIVAL_DAY: items},
        )
        result = extract_patient_age(days)
        _assert_schema(result)
        assert result["age_years"] == 75
        assert result["dob_iso"] == "1950-05-15"

    def test_dob_from_non_arrival_day(self) -> None:
        """DOB appears in a note on a later day → still extracted."""
        items_day2 = [_make_item(
            item_type="PHYSICIAN_NOTE",
            dt="2025-12-19T11:00:00",
            text=_dob_text("7/4/1955"),
        )]
        days = _make_days_data(
            arrival_datetime=ARRIVAL_TS,
            items_by_day={"2025-12-19": items_day2},
        )
        result = extract_patient_age(days)
        _assert_schema(result)
        assert result["age_years"] == 70
        assert result["age_source_rule_id"] == "dob_note_header"

    def test_dob_source_text(self) -> None:
        """age_source_text prefixed with DOB:."""
        items = [_make_item(
            item_type="PHYSICIAN_NOTE",
            text=_dob_text("1/1/1990"),
        )]
        days = _make_days_data(
            arrival_datetime=ARRIVAL_TS,
            items_by_day={ARRIVAL_DAY: items},
        )
        result = extract_patient_age(days)
        assert "DOB: 1/1/1990" in result["age_source_text"]


# ── Tests: HPI narrative age (fallback) ─────────────────────────────

class TestAgeHpiFallback:
    """HPI narrative age extraction (fallback strategy)."""

    def test_hpi_yo(self) -> None:
        """'60 yo male' → age 60."""
        items = [_make_item(
            item_type="TRAUMA_HP",
            text=_hpi_text(60, "yo male"),
        )]
        days = _make_days_data(
            arrival_datetime=ARRIVAL_TS,
            items_by_day={ARRIVAL_DAY: items},
        )
        result = extract_patient_age(days)
        _assert_schema(result)
        assert result["age_years"] == 60
        assert result["age_source_rule_id"] == "hpi_narrative_age"
        assert result["dob_iso"] is None

    def test_hpi_y_o_dot(self) -> None:
        """'65 y.o. female' → age 65."""
        items = [_make_item(
            item_type="TRAUMA_HP",
            text=_hpi_text(65, "y.o. female"),
        )]
        days = _make_days_data(
            arrival_datetime=ARRIVAL_TS,
            items_by_day={ARRIVAL_DAY: items},
        )
        result = extract_patient_age(days)
        assert result["age_years"] == 65
        assert result["age_source_rule_id"] == "hpi_narrative_age"

    def test_hpi_year_old(self) -> None:
        """'70 year-old male' → age 70."""
        items = [_make_item(
            item_type="TRAUMA_HP",
            text=_hpi_text(70, "year-old male"),
        )]
        days = _make_days_data(
            arrival_datetime=ARRIVAL_TS,
            items_by_day={ARRIVAL_DAY: items},
        )
        result = extract_patient_age(days)
        assert result["age_years"] == 70

    def test_hpi_year_old_space(self) -> None:
        """'55 year old' → age 55."""
        items = [_make_item(
            item_type="TRAUMA_HP",
            text=_hpi_text(55, "year old female"),
        )]
        days = _make_days_data(
            arrival_datetime=ARRIVAL_TS,
            items_by_day={ARRIVAL_DAY: items},
        )
        result = extract_patient_age(days)
        assert result["age_years"] == 55

    def test_hpi_yr(self) -> None:
        """'45 yr' → age 45."""
        items = [_make_item(
            item_type="TRAUMA_HP",
            text="HPI: 45 yr old patient presents with fall.\n",
        )]
        days = _make_days_data(
            arrival_datetime=ARRIVAL_TS,
            items_by_day={ARRIVAL_DAY: items},
        )
        result = extract_patient_age(days)
        assert result["age_years"] == 45

    def test_hpi_note_appended(self) -> None:
        """Fallback to HPI → note about approximate age."""
        items = [_make_item(
            item_type="TRAUMA_HP",
            text=_hpi_text(60, "yo male"),
        )]
        days = _make_days_data(
            arrival_datetime=ARRIVAL_TS,
            items_by_day={ARRIVAL_DAY: items},
        )
        result = extract_patient_age(days)
        assert any("approximate" in n for n in result["notes"])

    def test_hpi_consult_note_fallback(self) -> None:
        """HPI age from CONSULT_NOTE when no TRAUMA_HP."""
        items = [_make_item(
            item_type="CONSULT_NOTE",
            text="HPI: 72 y.o. male with chest pain.\n",
        )]
        days = _make_days_data(
            arrival_datetime=ARRIVAL_TS,
            items_by_day={ARRIVAL_DAY: items},
        )
        result = extract_patient_age(days)
        assert result["age_years"] == 72


# ── Tests: DOB takes priority over HPI ──────────────────────────────

class TestAgePriorityOrder:
    """DOB should take priority over narrative age."""

    def test_dob_wins_over_hpi(self) -> None:
        """Both DOB and HPI present → DOB wins."""
        items = [
            _make_item(
                item_type="PHYSICIAN_NOTE",
                dt="2025-12-18T12:00:00",
                text=_dob_text("3/20/1960"),  # age 65
            ),
            _make_item(
                item_type="TRAUMA_HP",
                text=_hpi_text(65, "y.o. female"),
            ),
        ]
        days = _make_days_data(
            arrival_datetime=ARRIVAL_TS,
            items_by_day={ARRIVAL_DAY: items},
        )
        result = extract_patient_age(days)
        assert result["age_source_rule_id"] == "dob_note_header"

    def test_trauma_hp_dob_searched_first(self) -> None:
        """TRAUMA_HP DOB has priority over PHYSICIAN_NOTE DOB."""
        items = [
            _make_item(
                item_type="PHYSICIAN_NOTE",
                dt="2025-12-18T12:00:00",
                text=_dob_text("1/1/1970"),  # would give age 55
            ),
            _make_item(
                item_type="TRAUMA_HP",
                dt="2025-12-18T16:00:00",
                text="Trauma H&P\nDOB: 6/15/1960\nHPI: ...\n",  # age 65
            ),
        ]
        days = _make_days_data(
            arrival_datetime=ARRIVAL_TS,
            items_by_day={ARRIVAL_DAY: items},
        )
        result = extract_patient_age(days)
        assert result["age_source_rule_id"] == "dob_note_header"
        # TRAUMA_HP searched first → DOB 6/15/1960 → age 65
        assert result["age_years"] == 65
        assert result["dob_iso"] == "1960-06-15"


# ── Tests: DATA NOT AVAILABLE ──────────────────────────────────────

class TestAgeDNA:
    """Fail-closed DATA NOT AVAILABLE scenarios."""

    def test_no_arrival_datetime(self) -> None:
        """Missing arrival_datetime → DNA."""
        days = _make_days_data(
            arrival_datetime=None,
            items_by_day={ARRIVAL_DAY: [_make_item(text=_dob_text())]},
        )
        result = extract_patient_age(days)
        _assert_schema(result)
        assert result["age_available"] == "DATA NOT AVAILABLE"
        assert result["age_years"] is None

    def test_no_items(self) -> None:
        """Empty days → DNA."""
        days = _make_days_data(arrival_datetime=ARRIVAL_TS, items_by_day={})
        result = extract_patient_age(days)
        _assert_schema(result)
        assert result["age_available"] == "DATA NOT AVAILABLE"

    def test_no_dob_no_hpi(self) -> None:
        """Items present but no DOB or age patterns → DNA."""
        items = [_make_item(
            item_type="NURSING_NOTE",
            text="Patient resting comfortably. Vitals stable.\n",
        )]
        days = _make_days_data(
            arrival_datetime=ARRIVAL_TS,
            items_by_day={ARRIVAL_DAY: items},
        )
        result = extract_patient_age(days)
        _assert_schema(result)
        assert result["age_available"] == "DATA NOT AVAILABLE"
        assert result["age_years"] is None
        assert result["age_source_rule_id"] is None

    def test_empty_meta(self) -> None:
        """Empty meta dict → DNA."""
        result = extract_patient_age({"meta": {}, "days": {}})
        _assert_schema(result)
        assert result["age_available"] == "DATA NOT AVAILABLE"

    def test_hpi_only_on_non_arrival_day(self) -> None:
        """HPI age on non-arrival day only → DNA (HPI only searched on arrival day)."""
        items = [_make_item(
            item_type="TRAUMA_HP",
            text=_hpi_text(60, "yo male"),
        )]
        days = _make_days_data(
            arrival_datetime=ARRIVAL_TS,
            items_by_day={"2025-12-19": items},  # NOT arrival day
        )
        result = extract_patient_age(days)
        _assert_schema(result)
        assert result["age_available"] == "DATA NOT AVAILABLE"


# ── Tests: Edge cases ──────────────────────────────────────────────

class TestAgeEdgeCases:
    """Edge cases and error handling."""

    def test_dob_nonsensical_age_falls_back(self) -> None:
        """DOB yields age > 120 → falls back to HPI, warning added."""
        items = [
            _make_item(
                item_type="PHYSICIAN_NOTE",
                text=_dob_text("1/1/1800"),  # age > 120
            ),
            _make_item(
                item_type="TRAUMA_HP",
                text=_hpi_text(65, "y.o. female"),
            ),
        ]
        days = _make_days_data(
            arrival_datetime=ARRIVAL_TS,
            items_by_day={ARRIVAL_DAY: items},
        )
        result = extract_patient_age(days)
        _assert_schema(result)
        # Should fall back to HPI
        assert result["age_source_rule_id"] == "hpi_narrative_age"
        assert result["age_years"] == 65
        assert any("out of bounds" in w for w in result["warnings"])

    def test_hpi_age_zero_skipped(self) -> None:
        """Narrative age '0 yo' → skipped (< 1), DNA."""
        items = [_make_item(
            item_type="TRAUMA_HP",
            text="HPI: 0 yo patient.\n",
        )]
        days = _make_days_data(
            arrival_datetime=ARRIVAL_TS,
            items_by_day={ARRIVAL_DAY: items},
        )
        result = extract_patient_age(days)
        assert result["age_available"] == "DATA NOT AVAILABLE"

    def test_hpi_age_200_skipped(self) -> None:
        """Narrative age '200 yo' → skipped (> 120), DNA."""
        items = [_make_item(
            item_type="TRAUMA_HP",
            text="HPI: 200 yo patient.\n",
        )]
        days = _make_days_data(
            arrival_datetime=ARRIVAL_TS,
            items_by_day={ARRIVAL_DAY: items},
        )
        result = extract_patient_age(days)
        assert result["age_available"] == "DATA NOT AVAILABLE"

    def test_bad_dob_format_falls_back(self) -> None:
        """Unparseable DOB falls back to HPI, warning added."""
        items = [
            _make_item(
                item_type="PHYSICIAN_NOTE",
                text="DOB: 99/99/9999\n",  # invalid date
            ),
            _make_item(
                item_type="TRAUMA_HP",
                text=_hpi_text(40, "yo male"),
            ),
        ]
        days = _make_days_data(
            arrival_datetime=ARRIVAL_TS,
            items_by_day={ARRIVAL_DAY: items},
        )
        result = extract_patient_age(days)
        assert result["age_source_rule_id"] == "hpi_narrative_age"
        assert result["age_years"] == 40
        assert any("could not parse" in w for w in result["warnings"])

    def test_pediatric_age(self) -> None:
        """Pediatric patient: DOB 1/15/2010, arrival 12/18/2025 → age 15."""
        items = [_make_item(
            item_type="PHYSICIAN_NOTE",
            text=_dob_text("1/15/2010"),
        )]
        days = _make_days_data(
            arrival_datetime=ARRIVAL_TS,
            items_by_day={ARRIVAL_DAY: items},
        )
        result = extract_patient_age(days)
        assert result["age_years"] == 15
        assert result["dob_iso"] == "2010-01-15"

    def test_geriatric_age(self) -> None:
        """Geriatric patient: DOB 2/26/1939, arrival 12/17/2025 → age 86."""
        items = [_make_item(
            item_type="PHYSICIAN_NOTE",
            text=_dob_text("2/26/1939"),
        )]
        days = _make_days_data(
            arrival_datetime="2025-12-17 11:14:00",
            items_by_day={"2025-12-17": items},
        )
        result = extract_patient_age(days)
        assert result["age_years"] == 86


# ── Tests: Evidence traceability ────────────────────────────────────

class TestAgeEvidence:
    """Evidence integrity checks."""

    def test_evidence_has_raw_line_id(self) -> None:
        """Every evidence entry must have a non-empty raw_line_id."""
        items = [_make_item(
            item_type="PHYSICIAN_NOTE",
            text=_dob_text("3/20/1960"),
        )]
        days = _make_days_data(
            arrival_datetime=ARRIVAL_TS,
            items_by_day={ARRIVAL_DAY: items},
        )
        result = extract_patient_age(days)
        assert len(result["evidence"]) == 1
        for ev in result["evidence"]:
            assert ev["raw_line_id"]
            assert len(ev["raw_line_id"]) == 16

    def test_evidence_deterministic(self) -> None:
        """Same inputs → same raw_line_id (deterministic hash)."""
        items = [_make_item(
            item_type="PHYSICIAN_NOTE",
            text=_dob_text("3/20/1960"),
        )]
        days = _make_days_data(
            arrival_datetime=ARRIVAL_TS,
            items_by_day={ARRIVAL_DAY: items},
        )
        r1 = extract_patient_age(days)
        r2 = extract_patient_age(days)
        assert r1["evidence"][0]["raw_line_id"] == r2["evidence"][0]["raw_line_id"]

    def test_dna_has_empty_evidence(self) -> None:
        """DNA results have no evidence entries."""
        result = extract_patient_age({"meta": {}, "days": {}})
        assert result["evidence"] == []

    def test_hpi_evidence_source(self) -> None:
        """HPI fallback evidence source is the item type."""
        items = [_make_item(
            item_type="TRAUMA_HP",
            text=_hpi_text(60, "yo male"),
        )]
        days = _make_days_data(
            arrival_datetime=ARRIVAL_TS,
            items_by_day={ARRIVAL_DAY: items},
        )
        result = extract_patient_age(days)
        assert result["evidence"][0]["source"] == "TRAUMA_HP"


# ── Tests: Schema completeness ──────────────────────────────────────

class TestAgeSchema:
    """Output schema completeness."""

    def test_full_schema_dob(self) -> None:
        """DOB-sourced result has all required keys."""
        items = [_make_item(
            item_type="PHYSICIAN_NOTE",
            text=_dob_text("3/20/1960"),
        )]
        days = _make_days_data(
            arrival_datetime=ARRIVAL_TS,
            items_by_day={ARRIVAL_DAY: items},
        )
        result = extract_patient_age(days)
        _assert_schema(result)
        assert result["dob_iso"] is not None
        assert isinstance(result["age_years"], int)

    def test_full_schema_hpi(self) -> None:
        """HPI-sourced result has all required keys."""
        items = [_make_item(
            item_type="TRAUMA_HP",
            text=_hpi_text(60, "yo male"),
        )]
        days = _make_days_data(
            arrival_datetime=ARRIVAL_TS,
            items_by_day={ARRIVAL_DAY: items},
        )
        result = extract_patient_age(days)
        _assert_schema(result)
        assert result["dob_iso"] is None

    def test_full_schema_dna(self) -> None:
        """DNA result has all required keys."""
        result = extract_patient_age({"meta": {}, "days": {}})
        _assert_schema(result)
        assert result["age_years"] is None
        assert result["age_available"] == "DATA NOT AVAILABLE"

    def test_age_bounds_constants(self) -> None:
        """Sanity constants in expected range."""
        assert _AGE_MIN == 0
        assert _AGE_MAX == 120
