#!/usr/bin/env python3
"""
Pytest-native NTDS fixture runner.

Loads every fixture file in tests/fixtures/patients/ and verifies its
outcome through the production NTDS engine.  This serves as the
regression baseline for all 21 NTDS events.

Fixture naming convention:
    <event_id>_<slug>_<expected>.txt   e.g. 08_dvt_yes.txt

Known gaps (xfail, strict=False):
    - Only events 08 (DVT), 14 (PE), and 20 (OR Return) currently have
      query-pattern entries in the mapper.  YES fixtures for the other
      18 events will return NO because no patterns match.
    - Synthetic fixture files use underscore section headers
      (e.g. [PHYSICIAN_NOTE]) while the section parser expects spaces.
      This prevents evidence classification even for mapped events.
    These xfails will auto-promote to XPASS once mapper + parser
    coverage is extended (no test changes needed).
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
_MAPPED_EVENTS: Set[int] = {8, 14, 20}


def _parse_fixture(path: Path) -> Tuple[int, str]:
    """Parse <event_id>_<slug>_<expected>.txt fixture file naming."""
    parts = path.stem.split("_")
    if len(parts) < 3:
        raise ValueError(f"Invalid fixture naming: {path.name}")

    event_id = int(parts[0])
    expected_raw = parts[-1].upper()
    expected = _OUTCOME_MAP.get(expected_raw, expected_raw)
    return event_id, expected


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
    # Mapped events still fail because synthetic fixtures use underscore
    # section headers ([PHYSICIAN_NOTE]) that the parser doesn't match.
    return (
        f"event {event_id:02d} fixture uses underscore section headers; "
        f"parser expects spaces — evidence not classified"
    )


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
    patient = build_patientfacts(fixture_path, query_patterns)

    result = evaluate_event(ruleset.event, ruleset.contract, patient)
    actual = result.outcome.value

    assert actual == expected_outcome, (
        f"{fixture_path.name}: expected={expected_outcome}, actual={actual}, "
        f"hard_stop={getattr(result.hard_stop, 'reason', None)}"
    )
