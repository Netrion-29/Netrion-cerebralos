#!/usr/bin/env python3
"""
Regression tests for PE mapper regex word-boundary fixes (PRs #78–#82).

Verifies that pe_history_noise, pe_dx, pe_dx_positive, pe_onset, and
pe_subsegmental_only patterns in epic_deaconess_mapper_v1.json correctly
match full-word variants ("pulmonary embolism", "pulmonary embolus") and
do not silently regress to bare `embol` patterns that truncate at \b.

These tests operate directly on the mapper JSON regex patterns — no engine
invocation needed. They catch regex regressions at the pattern level before
they can affect downstream NTDS evaluation.
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REPO_ROOT = Path(__file__).resolve().parents[1]
MAPPER_PATH = REPO_ROOT / "rules" / "mappers" / "epic_deaconess_mapper_v1.json"


def _load_patterns() -> dict:
    with open(MAPPER_PATH) as f:
        data = json.load(f)
    return data.get("query_patterns", {})


def _any_pattern_matches(patterns: list, text: str) -> bool:
    """Return True if any pattern in the list matches the text (case-insensitive)."""
    for pat in patterns:
        if re.search(pat, text, re.IGNORECASE):
            return True
    return False


# ─── pe_history_noise: must match full-word variants (PR #78, #80) ─────


def test_pe_history_noise_matches_embolism():
    """pe_history_noise must match 'history of pulmonary embolism'."""
    pats = _load_patterns()["pe_history_noise"]
    assert _any_pattern_matches(pats, "history of pulmonary embolism"), \
        "pe_history_noise failed to match 'history of pulmonary embolism'"


def test_pe_history_noise_matches_embolus():
    """pe_history_noise must match 'prior pulmonary embolus'."""
    pats = _load_patterns()["pe_history_noise"]
    assert _any_pattern_matches(pats, "prior pulmonary embolus"), \
        "pe_history_noise failed to match 'prior pulmonary embolus'"


def test_pe_history_noise_matches_hx_pe():
    """pe_history_noise must match 'hx of PE'."""
    pats = _load_patterns()["pe_history_noise"]
    assert _any_pattern_matches(pats, "hx of PE"), \
        "pe_history_noise failed to match 'hx of PE'"


def test_pe_history_noise_matches_anticoag_for_embolism():
    """pe_history_noise must match anticoagulant-for-PE patterns."""
    pats = _load_patterns()["pe_history_noise"]
    assert _any_pattern_matches(pats, "on eliquis for pulmonary embolism"), \
        "pe_history_noise failed to match 'on eliquis for pulmonary embolism'"


def test_pe_history_noise_matches_old_embolism():
    """pe_history_noise must match 'old pulmonary embolism'."""
    pats = _load_patterns()["pe_history_noise"]
    assert _any_pattern_matches(pats, "old pulmonary embolism"), \
        "pe_history_noise failed to match 'old pulmonary embolism'"


def test_pe_history_noise_no_bare_embol():
    """No pe_history_noise pattern should use bare (pulmonary\\s+embol|PE)
    without \\w* — regression guard for PRs #78, #80."""
    pats = _load_patterns()["pe_history_noise"]
    bare_re = re.compile(r"\(pulmonary\\s\+embol(?!\\w\*)\|PE\)")
    for pat in pats:
        assert not bare_re.search(pat), \
            f"Bare embol pattern found (missing \\w*): {pat}"


# ─── pe_dx / pe_dx_positive: segmental lines (PR #78) ────────────────


def test_pe_dx_segmental_matches_embolism():
    """pe_dx segmental/subsegmental pattern must match 'segmental pulmonary embolism'."""
    pats = _load_patterns()["pe_dx"]
    assert _any_pattern_matches(pats, "segmental pulmonary embolism"), \
        "pe_dx failed to match 'segmental pulmonary embolism'"


def test_pe_dx_segmental_matches_embolus():
    """pe_dx segmental/subsegmental pattern must match 'subsegmental pulmonary embolus'."""
    pats = _load_patterns()["pe_dx"]
    assert _any_pattern_matches(pats, "subsegmental pulmonary embolus"), \
        "pe_dx failed to match 'subsegmental pulmonary embolus'"


def test_pe_dx_positive_segmental_matches_embolism():
    """pe_dx_positive segmental/subsegmental must match 'segmental pulmonary embolism'."""
    pats = _load_patterns()["pe_dx_positive"]
    assert _any_pattern_matches(pats, "segmental pulmonary embolism"), \
        "pe_dx_positive failed to match 'segmental pulmonary embolism'"


def test_pe_dx_positive_segmental_matches_embolus():
    """pe_dx_positive segmental/subsegmental must match 'subsegmental pulmonary embolus'."""
    pats = _load_patterns()["pe_dx_positive"]
    assert _any_pattern_matches(pats, "subsegmental pulmonary embolus"), \
        "pe_dx_positive failed to match 'subsegmental pulmonary embolus'"


# ─── pe_onset: word-boundary fixes (PR #81) ───────────────────────────


def test_pe_onset_hospital_acquired_embolism():
    """pe_onset must match 'hospital acquired pulmonary embolism'."""
    pats = _load_patterns()["pe_onset"]
    assert _any_pattern_matches(pats, "hospital acquired pulmonary embolism"), \
        "pe_onset failed to match 'hospital acquired pulmonary embolism'"


def test_pe_onset_postop_embolism():
    """pe_onset must match 'postoperative pulmonary embolism'."""
    pats = _load_patterns()["pe_onset"]
    assert _any_pattern_matches(pats, "postoperative pulmonary embolism"), \
        "pe_onset failed to match 'postoperative pulmonary embolism'"


def test_pe_onset_newly_diagnosed_embolism():
    """pe_onset must match 'newly diagnosed pulmonary embolism'."""
    pats = _load_patterns()["pe_onset"]
    assert _any_pattern_matches(pats, "newly diagnosed pulmonary embolism"), \
        "pe_onset failed to match 'newly diagnosed pulmonary embolism'"


def test_pe_onset_interval_development_embolism():
    """pe_onset must match 'interval development of pulmonary embolism'."""
    pats = _load_patterns()["pe_onset"]
    assert _any_pattern_matches(pats, "interval development of pulmonary embolism"), \
        "pe_onset failed to match 'interval development of pulmonary embolism'"


def test_pe_onset_in_hospital_embolus():
    """pe_onset must match 'in-hospital pulmonary embolus'."""
    pats = _load_patterns()["pe_onset"]
    assert _any_pattern_matches(pats, "in-hospital pulmonary embolus"), \
        "pe_onset failed to match 'in-hospital pulmonary embolus'"


def test_pe_onset_no_bare_embol():
    """No pe_onset pattern should use bare (pulmonary\\s+embol|PE\\b)
    without \\w* — regression guard for PR #81."""
    pats = _load_patterns()["pe_onset"]
    bare_re = re.compile(r"\(pulmonary\\s\+embol(?!\\w\*|(?:\?\:ism\)))\|PE\\b\)")
    for pat in pats:
        assert not bare_re.search(pat), \
            f"Bare embol pattern found (missing \\w*): {pat}"


# ─── pe_subsegmental_only: normalization (PR #82) ─────────────────────


def test_pe_subsegmental_matches_embolism():
    """pe_subsegmental_only must match 'subsegmental pulmonary embolism'."""
    pats = _load_patterns()["pe_subsegmental_only"]
    assert _any_pattern_matches(pats, "subsegmental pulmonary embolism"), \
        "pe_subsegmental_only failed to match 'subsegmental pulmonary embolism'"


def test_pe_subsegmental_matches_embolus():
    """pe_subsegmental_only must match 'subsegmental pulmonary embolus'."""
    pats = _load_patterns()["pe_subsegmental_only"]
    assert _any_pattern_matches(pats, "subsegmental pulmonary embolus"), \
        "pe_subsegmental_only failed to match 'subsegmental pulmonary embolus'"


def test_pe_subsegmental_matches_bare_embol():
    """pe_subsegmental_only must still match bare 'subsegmental pulmonary embol' prefix."""
    pats = _load_patterns()["pe_subsegmental_only"]
    assert _any_pattern_matches(pats, "subsegmental pulmonary embol"), \
        "pe_subsegmental_only failed to match 'subsegmental pulmonary embol'"


# ─── structural: no duplicate keys (PR #79) ───────────────────────────


def test_no_duplicate_pe_dx_positive_key():
    """Mapper must have exactly one pe_dx_positive key (raw parse).
    Regression guard for PR #79 dedup."""
    with open(MAPPER_PATH) as f:
        raw = f.read()
    count = raw.count('"pe_dx_positive"')
    assert count == 1, \
        f"Expected 1 pe_dx_positive key, found {count} — duplicate key regression"


# ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        ("test_pe_history_noise_matches_embolism", test_pe_history_noise_matches_embolism),
        ("test_pe_history_noise_matches_embolus", test_pe_history_noise_matches_embolus),
        ("test_pe_history_noise_matches_hx_pe", test_pe_history_noise_matches_hx_pe),
        ("test_pe_history_noise_matches_anticoag_for_embolism", test_pe_history_noise_matches_anticoag_for_embolism),
        ("test_pe_history_noise_matches_old_embolism", test_pe_history_noise_matches_old_embolism),
        ("test_pe_history_noise_no_bare_embol", test_pe_history_noise_no_bare_embol),
        ("test_pe_dx_segmental_matches_embolism", test_pe_dx_segmental_matches_embolism),
        ("test_pe_dx_segmental_matches_embolus", test_pe_dx_segmental_matches_embolus),
        ("test_pe_dx_positive_segmental_matches_embolism", test_pe_dx_positive_segmental_matches_embolism),
        ("test_pe_dx_positive_segmental_matches_embolus", test_pe_dx_positive_segmental_matches_embolus),
        ("test_pe_onset_hospital_acquired_embolism", test_pe_onset_hospital_acquired_embolism),
        ("test_pe_onset_postop_embolism", test_pe_onset_postop_embolism),
        ("test_pe_onset_newly_diagnosed_embolism", test_pe_onset_newly_diagnosed_embolism),
        ("test_pe_onset_interval_development_embolism", test_pe_onset_interval_development_embolism),
        ("test_pe_onset_in_hospital_embolus", test_pe_onset_in_hospital_embolus),
        ("test_pe_onset_no_bare_embol", test_pe_onset_no_bare_embol),
        ("test_pe_subsegmental_matches_embolism", test_pe_subsegmental_matches_embolism),
        ("test_pe_subsegmental_matches_embolus", test_pe_subsegmental_matches_embolus),
        ("test_pe_subsegmental_matches_bare_embol", test_pe_subsegmental_matches_bare_embol),
        ("test_no_duplicate_pe_dx_positive_key", test_no_duplicate_pe_dx_positive_key),
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
