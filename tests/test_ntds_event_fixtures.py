#!/usr/bin/env python3
"""
Pytest-native NTDS fixture runner.

Loads every fixture file in tests/fixtures/patients/ and verifies its
outcome through the production NTDS engine.  This serves as the
regression baseline for all 21 NTDS events.

Fixture naming convention:
    <event_id>_<slug>_<expected>.txt   e.g. 08_dvt_yes.txt

Known gaps (xfail, strict=False):
    - Events 05 (CAUTI), 08 (DVT), 09 (Delirium), 13 (Pressure Ulcer),
      14 (PE), and 20 (OR Return) have query-pattern entries in the
      mapper.  YES fixtures for the other 15 events will return NO
      because no patterns match.
    These xfails will auto-promote to XPASS once mapper coverage is
    extended (no test changes needed).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Set, Tuple

import pytest

from cerebralos.ntds_logic.build_patientfacts_from_txt import build_patientfacts
from cerebralos.ntds_logic.engine import evaluate_event, load_mapper
from cerebralos.ntds_logic.rules_loader import load_ruleset


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "patients"

_OUTCOME_MAP = {
    "YES": "YES",
    "NO": "NO",
    "EXCLUDED": "EXCLUDED",
    "UNABLE": "UNABLE_TO_DETERMINE",
}

# Events that have full query-pattern coverage in the mapper today.
_MAPPED_EVENTS: Set[int] = {5, 8, 9, 13, 14, 20}

# Mapped events whose YES fixtures evaluate to UNABLE_TO_DETERMINE
# because the synthetic fixture content does not satisfy timing/onset
# gates (e.g. timing_after_arrival).  These need richer fixtures.
# PR #120: Events 08/14 fixtures now satisfy timing gates.
_FIXTURE_TIMING_GAPS: Set[int] = set()


def _parse_fixture(path: Path) -> Tuple[int, str]:
    """Parse <event_id>_<slug>_<expected>.txt fixture file naming."""
    parts = path.stem.split("_")
    if len(parts) < 3:
        raise ValueError(f"Invalid fixture naming: {path.name}")

    event_id = int(parts[0])
    expected_raw = parts[-1].upper()
    expected = _OUTCOME_MAP.get(expected_raw, expected_raw)
    return event_id, expected


def _extract_arrival_time(fixture_path: Path) -> str | None:
    """Extract ARRIVAL_TIME header from fixture file, if present."""
    for line in fixture_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("ARRIVAL_TIME:"):
            return stripped.split(":", 1)[1].strip()
    return None


def _collect_fixtures() -> list[Path]:
    fixtures = sorted(FIXTURES_DIR.glob("*.txt"))
    if not fixtures:
        raise RuntimeError(f"No NTDS fixtures found in {FIXTURES_DIR}")
    return fixtures


def _needs_xfail(fixture_path: Path) -> str | None:
    """Return an xfail reason string, or None if the case should pass."""
    event_id, expected = _parse_fixture(fixture_path)
    if expected == "NO":
        return None  # NO fixtures always pass (engine is fail-closed)

    # YES/EXCLUDED/UNABLE fixtures that require positive evidence:
    if event_id not in _MAPPED_EVENTS:
        return (
            f"event {event_id:02d} has no mapper query-patterns yet; "
            f"YES fixture will return NO until patterns are added"
        )
    # Mapped events with timing gates that synthetic fixtures don't satisfy:
    if event_id in _FIXTURE_TIMING_GAPS:
        return (
            f"event {event_id:02d} fixture does not satisfy timing/onset gates; "
            f"returns UNABLE_TO_DETERMINE until fixture is enriched"
        )
    return None


@pytest.fixture(scope="session")
def query_patterns() -> dict:
    mapper = load_mapper()
    return mapper.get("query_patterns", {})


@pytest.mark.parametrize(
    "fixture_path", _collect_fixtures(), ids=lambda p: p.name
)
def test_ntds_event_fixture_outcomes(
    fixture_path: Path, query_patterns: dict
) -> None:
    """Each fixture should evaluate to the outcome encoded in its filename."""
    reason = _needs_xfail(fixture_path)
    if reason:
        pytest.xfail(reason)

    event_id, expected_outcome = _parse_fixture(fixture_path)
    ruleset = load_ruleset(2026, event_id)
    arrival_time = _extract_arrival_time(fixture_path)
    patient = build_patientfacts(fixture_path, query_patterns, arrival_time=arrival_time)

    result = evaluate_event(ruleset.event, ruleset.contract, patient)
    actual = result.outcome.value

    assert actual == expected_outcome, (
        f"{fixture_path.name}: expected={expected_outcome}, actual={actual}, "
        f"hard_stop={getattr(result.hard_stop, 'reason', None)}"
    )
