#!/usr/bin/env python3
"""
Tests for exclude_noise_keys enforcement in eval_evidence_any().

Verifies:
  1. Historical/noise PE text does NOT satisfy pe_dx when excluded by pe_history_noise.
  2. True-positive PE diagnosis still passes pe_dx (overall outcome may be UTD
     due to pre-existing timing fixture gap — not related to this change).
  3. DVT negation behavior (PR #73) does not regress.
  4. Existing fixture expectations remain stable.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cerebralos.ntds_logic.engine import evaluate_event, load_mapper
from cerebralos.ntds_logic.rules_loader import load_ruleset
from cerebralos.ntds_logic.build_patientfacts_from_txt import build_patientfacts

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "patients"


def _run_event(fixture_name: str, event_id: int) -> dict:
    """Run a single event against a fixture, return outcome + gate trace."""
    mapper = load_mapper()
    query_patterns = mapper.get("query_patterns", {})
    rs = load_ruleset(2026, event_id)
    patient = build_patientfacts(FIXTURES_DIR / fixture_name, query_patterns)
    result = evaluate_event(rs.event, rs.contract, patient)
    gate_map = {g.gate: g for g in result.gate_trace}
    return {
        "outcome": result.outcome.value,
        "gate_trace": gate_map,
        "hard_stop": result.hard_stop,
    }


# ─── PE exclude_noise_keys tests ───────────────────────────────────────


def test_pe_history_noise_excluded():
    """Historical PE PMH text matches pe_dx_positive but also pe_history_noise.
    With exclude_noise_keys enforcement, pe_dx should FAIL → outcome NO."""
    r = _run_event("14_pe_history_noise_no.txt", 14)
    assert r["outcome"] == "NO", (
        f"Expected NO for historical PE, got {r['outcome']}"
    )
    pe_dx = r["gate_trace"].get("pe_dx")
    assert pe_dx is not None, "pe_dx gate missing from trace"
    assert pe_dx.passed is False, (
        f"pe_dx should fail when all hits are noise-excluded, but passed={pe_dx.passed}"
    )


def test_pe_true_positive_dx_passes():
    """Fixture with genuine in-hospital PE: pe_dx gate should still PASS even
    with noise filtering active (overall outcome may be UTD due to pre-existing
    timing fixture gap — that is not related to this change)."""
    r = _run_event("14_pe_yes.txt", 14)
    pe_dx = r["gate_trace"].get("pe_dx")
    assert pe_dx is not None, "pe_dx gate missing from trace"
    assert pe_dx.passed is True, (
        f"pe_dx should pass for genuine PE diagnosis, but passed={pe_dx.passed}"
    )


def test_pe_negative_imaging_still_no():
    """Fixture with negative CTA should still reach NO."""
    r = _run_event("14_pe_no.txt", 14)
    assert r["outcome"] == "NO", (
        f"Expected NO for negative PE imaging, got {r['outcome']}"
    )


# ─── DVT negation regression (PR #73) ──────────────────────────────────


def test_dvt_no_fixture_stable():
    """DVT negative fixture should still produce NO."""
    r = _run_event("08_dvt_no.txt", 8)
    assert r["outcome"] == "NO", (
        f"Expected NO for DVT negative fixture, got {r['outcome']}"
    )


def test_dvt_yes_dx_passes():
    """DVT positive fixture: dvt_dx gate should PASS (overall may be UTD due
    to pre-existing timing fixture gap — not related to this change)."""
    r = _run_event("08_dvt_yes.txt", 8)
    dvt_dx = r["gate_trace"].get("dvt_dx")
    assert dvt_dx is not None, "dvt_dx gate missing from trace"
    assert dvt_dx.passed is True, (
        f"dvt_dx should pass for genuine DVT diagnosis, but passed={dvt_dx.passed}"
    )


if __name__ == "__main__":
    tests = [
        ("test_pe_history_noise_excluded", test_pe_history_noise_excluded),
        ("test_pe_true_positive_dx_passes", test_pe_true_positive_dx_passes),
        ("test_pe_negative_imaging_still_no", test_pe_negative_imaging_still_no),
        ("test_dvt_no_fixture_stable", test_dvt_no_fixture_stable),
        ("test_dvt_yes_dx_passes", test_dvt_yes_dx_passes),
    ]
    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ✓ {name}")
            passed += 1
        except AssertionError as e:
            print(f"  ✗ {name}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ✗ {name}: ERROR: {e}")
            failed += 1

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
