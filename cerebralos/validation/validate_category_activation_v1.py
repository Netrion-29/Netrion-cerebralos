#!/usr/bin/env python3
"""
Validate category_activation_v1 feature blob.

Checks:
  1. features.category_activation_v1 exists
  2. Types: detected bool, category "I" or null
  3. method matches "fail_closed_regex_v1"
  4. Every evidence item has raw_line_id
  5. Evidence is deterministically sorted
  6. If ambiguity note present → detected must be false

Usage:
    python3 -m cerebralos.validation.validate_category_activation_v1 \
        --in outputs/features/<PAT>/patient_features_v1.json

Design:
- Deterministic, fail-closed.
- No LLM, no ML, no clinical inference.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


def _evidence_sort_key(ev: Dict[str, Any]) -> tuple:
    """Mirror the sort key used in category_activation_v1.py."""
    ts = ev.get("ts")
    return (ts is None, ts or "", ev.get("raw_line_id", ""))


def validate(features: Dict[str, Any]) -> List[str]:
    """
    Validate the category_activation_v1 blob inside a patient_features_v1 dict.

    Returns a list of error strings (empty ⇒ valid).
    """
    errors: List[str] = []

    # 1. Existence
    feats = features.get("features", {})
    blob = feats.get("category_activation_v1")
    if blob is None:
        errors.append("MISSING: features.category_activation_v1 not present")
        return errors

    if not isinstance(blob, dict):
        errors.append(
            f"TYPE_ERROR: category_activation_v1 must be dict, "
            f"got {type(blob).__name__}"
        )
        return errors

    # 2. Type checks
    detected = blob.get("detected")
    if not isinstance(detected, bool):
        errors.append(
            f"TYPE_ERROR: detected must be bool, got {type(detected).__name__}"
        )

    category = blob.get("category")
    if category is not None and category != "I":
        errors.append(
            f"VALUE_ERROR: category must be 'I' or null, got {category!r}"
        )

    # detected/category consistency
    if isinstance(detected, bool):
        if detected and category != "I":
            errors.append(
                "CONSISTENCY_ERROR: detected=true but category is not 'I'"
            )
        if not detected and category is not None:
            errors.append(
                "CONSISTENCY_ERROR: detected=false but category is not null"
            )

    # 3. Method check
    method = blob.get("method")
    if method != "fail_closed_regex_v1":
        errors.append(
            f"VALUE_ERROR: method must be 'fail_closed_regex_v1', got {method!r}"
        )

    # 4. Evidence: raw_line_id required
    evidence = blob.get("evidence")
    if not isinstance(evidence, list):
        errors.append(
            f"TYPE_ERROR: evidence must be list, got {type(evidence).__name__}"
        )
    else:
        for i, ev in enumerate(evidence):
            if not isinstance(ev, dict):
                errors.append(f"TYPE_ERROR: evidence[{i}] must be dict")
                continue
            if "raw_line_id" not in ev:
                errors.append(f"MISSING: evidence[{i}] lacks raw_line_id")
            elif not isinstance(ev["raw_line_id"], str) or not ev["raw_line_id"]:
                errors.append(
                    f"VALUE_ERROR: evidence[{i}].raw_line_id must be non-empty string"
                )

        # 5. Deterministic sort
        sorted_evidence = sorted(evidence, key=_evidence_sort_key)
        if evidence != sorted_evidence:
            errors.append(
                "SORT_ERROR: evidence is not in deterministic order "
                "(ts is None, ts or '', raw_line_id)"
            )

    # 6. Ambiguity → detected must be false
    notes = blob.get("notes")
    if isinstance(notes, list):
        if "AMBIGUOUS_CAT_I_CAT_II_SAME_LINE" in notes:
            if detected is True:
                errors.append(
                    "FAIL_CLOSED_VIOLATION: ambiguity note present but "
                    "detected is true"
                )
            if isinstance(evidence, list) and len(evidence) > 0:
                errors.append(
                    "FAIL_CLOSED_VIOLATION: ambiguity note present but "
                    "evidence is non-empty"
                )
    elif notes is not None:
        errors.append(
            f"TYPE_ERROR: notes must be list or null, got {type(notes).__name__}"
        )

    return errors


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Validate category_activation_v1 in patient_features_v1.json",
    )
    ap.add_argument(
        "--in", dest="in_path", required=True,
        help="Path to patient_features_v1.json",
    )
    args = ap.parse_args()

    in_path = Path(args.in_path).expanduser().resolve()
    if not in_path.is_file():
        print(f"FAIL: input not found: {in_path}", file=sys.stderr)
        return 1

    with open(in_path, encoding="utf-8", errors="replace") as f:
        features = json.load(f)

    errors = validate(features)

    if errors:
        print(f"FAIL ❌  {len(errors)} validation error(s):")
        for err in errors:
            print(f"  • {err}")
        return 1

    # Print summary on success
    feats_main = features.get("features", {})
    blob = feats_main.get("category_activation_v1", {})
    detected = blob.get("detected", False)
    n_ev = len(blob.get("evidence", []))
    notes = blob.get("notes", [])
    print(
        f"OK ✅  category_activation_v1: "
        f"detected={detected}, evidence_count={n_ev}, notes={notes}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
