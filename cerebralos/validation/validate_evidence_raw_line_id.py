#!/usr/bin/env python3
"""
Validate that every item in patient_evidence_v1.json has a non-empty raw_line_id.

This enforces AGENTS.md §5: "Every stored evidence item must include raw_line_id."

Exit codes:
  0 — all items have raw_line_id
  1 — one or more items missing raw_line_id (fail-closed)

Usage:
    python3 cerebralos/validation/validate_evidence_raw_line_id.py \
        --in outputs/evidence/Anna_Dennis/patient_evidence_v1.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def validate(data: dict) -> list[str]:
    """Return a list of error strings (empty = valid)."""
    errors: list[str] = []
    items = data.get("items")
    if items is None:
        errors.append("MISSING_ITEMS_KEY: 'items' key not found in evidence JSON")
        return errors
    if not isinstance(items, list):
        errors.append(f"ITEMS_NOT_LIST: 'items' is {type(items).__name__}, expected list")
        return errors

    missing_count = 0
    first_missing_idx: int | None = None
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        rid = item.get("raw_line_id")
        if not rid:  # None, empty string, or missing
            missing_count += 1
            if first_missing_idx is None:
                first_missing_idx = i

    if missing_count > 0:
        errors.append(
            f"EVIDENCE_MISSING_RAW_LINE_ID: {missing_count}/{len(items)} item(s) "
            f"lack raw_line_id (first at idx={first_missing_idx})"
        )
    return errors


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Validate raw_line_id on patient_evidence_v1.json items",
    )
    ap.add_argument(
        "--in", dest="in_path", required=True,
        help="Path to patient_evidence_v1.json",
    )
    args = ap.parse_args()

    in_path = Path(args.in_path).expanduser().resolve()
    if not in_path.is_file():
        print(f"FAIL: input not found: {in_path}", file=sys.stderr)
        return 1

    with open(in_path, encoding="utf-8", errors="replace") as f:
        data = json.load(f)

    errors = validate(data)

    if errors:
        print(f"FAIL  evidence raw_line_id: {len(errors)} violation(s):")
        for err in errors:
            print(f"  • {err}")
        return 1

    item_count = len(data.get("items", []))
    patient = data.get("meta", {}).get("patient_slug", "?")
    print(f"OK  evidence raw_line_id valid: {patient} ({item_count} items)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
