#!/usr/bin/env python3
"""
Guard test: ensure epic_deaconess_mapper_v1.json has no duplicate JSON keys.

Python's json.load silently keeps only the last value when a JSON object
contains duplicate keys.  This caused a real bug where a second
"pe_dx_positive" block silently overwrote the first (fixed in PR #79).

This test parses the mapper with a custom object_pairs_hook that raises
on the first duplicate key at any nesting depth, preventing silent data loss.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REPO_ROOT = Path(__file__).resolve().parents[1]
MAPPER_PATH = REPO_ROOT / "rules" / "mappers" / "epic_deaconess_mapper_v1.json"


class DuplicateKeyError(ValueError):
    """Raised when a duplicate key is found in a JSON object."""


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    """object_pairs_hook that raises on the first duplicate key."""
    seen: dict[str, object] = {}
    for key, value in pairs:
        if key in seen:
            raise DuplicateKeyError(
                f"Duplicate JSON key: {key!r}"
            )
        seen[key] = value
    return seen


# ── Tests ────────────────────────────────────────────────────────────────


def test_no_duplicate_keys_in_mapper():
    """Mapper JSON must not contain any duplicate keys at any depth."""
    with open(MAPPER_PATH) as f:
        raw = f.read()
    # Raises DuplicateKeyError on the first duplicate
    data = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    # Sanity: top-level structure is a dict with expected sections
    assert isinstance(data, dict), "Mapper root must be a JSON object"
    assert "query_patterns" in data, "Mapper must contain 'query_patterns'"


def test_hook_catches_duplicates():
    """Verify the hook itself detects duplicates (self-test)."""
    bad_json = '{"a": 1, "b": 2, "a": 3}'
    try:
        json.loads(bad_json, object_pairs_hook=_reject_duplicate_keys)
        assert False, "Should have raised DuplicateKeyError"
    except DuplicateKeyError as exc:
        assert "a" in str(exc)


def test_hook_catches_nested_duplicates():
    """Verify the hook detects duplicates inside nested objects."""
    bad_json = '{"outer": {"x": 1, "x": 2}}'
    try:
        json.loads(bad_json, object_pairs_hook=_reject_duplicate_keys)
        assert False, "Should have raised DuplicateKeyError"
    except DuplicateKeyError as exc:
        assert "x" in str(exc)


# ── CLI runner ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        ("test_no_duplicate_keys_in_mapper", test_no_duplicate_keys_in_mapper),
        ("test_hook_catches_duplicates", test_hook_catches_duplicates),
        ("test_hook_catches_nested_duplicates", test_hook_catches_nested_duplicates),
    ]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ✓ {name}")
        except Exception as exc:
            print(f"  ✗ {name}: {exc}")
            failed += 1
    print()
    print(f"{len(tests)} tests, {failed} failed")
    sys.exit(1 if failed else 0)
