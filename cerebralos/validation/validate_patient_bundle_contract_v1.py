#!/usr/bin/env python3
"""
Validate patient_bundle_v1.json against the locked output contract.

Checks:
  1. Top-level keys are EXACTLY the allowed set (no extras, no missing).
  2. Required sub-sections (patient, summary, daily, artifacts) are dicts.
  3. build.bundle_version is present.
  4. patient.slug is a non-empty string.
  5. warnings is a list.

Exit codes:
  0 — contract valid
  1 — contract violation(s) detected

Usage:
    python3 cerebralos/validation/validate_patient_bundle_contract_v1.py \\
        --in outputs/casefile/Betty_Roll/patient_bundle_v1.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

# ── Contract constants ──────────────────────────────────────────────

ALLOWED_TOP_LEVEL_KEYS = frozenset({
    "build",
    "patient",
    "summary",
    "compliance",
    "daily",
    "consultants",
    "artifacts",
    "warnings",
})


# ── Validation logic ───────────────────────────────────────────────

def validate_contract(data: Any) -> List[str]:
    """
    Validate patient_bundle_v1.json against the locked contract.

    Returns a list of error strings (empty = valid).
    """
    errors: List[str] = []

    # 0. Root must be a JSON object (dict)
    if not isinstance(data, dict):
        errors.append(
            f"ROOT_TYPE_ERROR: bundle root must be a JSON object (dict), "
            f"got {type(data).__name__}"
        )
        return errors

    top_keys = set(data.keys())

    # 1. No unexpected top-level keys
    extra_keys = sorted(top_keys - ALLOWED_TOP_LEVEL_KEYS)
    if extra_keys:
        errors.append(
            f"TOP_LEVEL_EXTRA_KEYS: unexpected keys at top level: {extra_keys}"
        )

    # 2. No missing required top-level keys
    missing_keys = sorted(ALLOWED_TOP_LEVEL_KEYS - top_keys)
    if missing_keys:
        errors.append(
            f"TOP_LEVEL_MISSING_KEYS: required keys missing: {missing_keys}"
        )

    # 3. build must be a dict with bundle_version
    build_val = data.get("build")
    if not isinstance(build_val, dict):
        errors.append(
            f"BUILD_TYPE_ERROR: 'build' must be dict, "
            f"got {type(build_val).__name__}"
        )
    elif not build_val.get("bundle_version"):
        errors.append("BUILD_MISSING_VERSION: build.bundle_version is missing")

    # 4. patient must be a dict with a non-empty slug
    patient_val = data.get("patient")
    if not isinstance(patient_val, dict):
        errors.append(
            f"PATIENT_TYPE_ERROR: 'patient' must be dict, "
            f"got {type(patient_val).__name__}"
        )
    elif not patient_val.get("slug"):
        errors.append("PATIENT_MISSING_SLUG: patient.slug is empty or missing")

    # 5. summary must be a dict
    summary_val = data.get("summary")
    if not isinstance(summary_val, dict):
        errors.append(
            f"SUMMARY_TYPE_ERROR: 'summary' must be dict, "
            f"got {type(summary_val).__name__}"
        )
    else:
        # Validate required summary sub-keys exist (value may be dict or null)
        for skey in ("injuries", "imaging", "procedures",
                     "devices", "dvt_prophylaxis", "gi_prophylaxis",
                     "seizure_prophylaxis"):
            if skey not in summary_val:
                errors.append(
                    f"SUMMARY_MISSING_KEY: summary.{skey} is missing"
                )

    # 6. compliance must be a dict
    compliance_val = data.get("compliance")
    if not isinstance(compliance_val, dict):
        errors.append(
            f"COMPLIANCE_TYPE_ERROR: 'compliance' must be dict, "
            f"got {type(compliance_val).__name__}"
        )

    # 7. daily must be a dict (date-keyed)
    daily_val = data.get("daily")
    if not isinstance(daily_val, dict):
        errors.append(
            f"DAILY_TYPE_ERROR: 'daily' must be dict, "
            f"got {type(daily_val).__name__}"
        )

    # 8. artifacts must be a dict
    artifacts_val = data.get("artifacts")
    if not isinstance(artifacts_val, dict):
        errors.append(
            f"ARTIFACTS_TYPE_ERROR: 'artifacts' must be dict, "
            f"got {type(artifacts_val).__name__}"
        )

    # 9. consultants must be a dict or null
    consultants_val = data.get("consultants")
    if consultants_val is not None and not isinstance(consultants_val, dict):
        errors.append(
            f"CONSULTANTS_TYPE_ERROR: 'consultants' must be dict or null, "
            f"got {type(consultants_val).__name__}"
        )

    # 10. warnings must be a list
    warnings_val = data.get("warnings")
    if not isinstance(warnings_val, list):
        errors.append(
            f"WARNINGS_TYPE_ERROR: 'warnings' must be list, "
            f"got {type(warnings_val).__name__}"
        )

    return errors


# ── CLI ─────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate patient_bundle_v1.json contract."
    )
    parser.add_argument(
        "--in",
        dest="infile",
        required=True,
        help="Path to patient_bundle_v1.json",
    )
    args = parser.parse_args()

    path = Path(args.infile)
    if not path.is_file():
        print(f"Error: file not found: {path}", file=sys.stderr)
        return 1

    data = json.loads(path.read_text(encoding="utf-8"))
    errors = validate_contract(data)

    if errors:
        print(f"FAIL  {len(errors)} contract violation(s):", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print(f"OK  Bundle contract valid: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
