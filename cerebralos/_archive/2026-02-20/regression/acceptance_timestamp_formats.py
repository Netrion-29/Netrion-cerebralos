#!/usr/bin/env python3
"""
Acceptance test: multi-format EHR timestamp normalization.

Runs William_Simmons, Cody_Givens, Timothy_Nachtwey through the evidence
pipeline and reports timestamp_format_counts QA block.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import datetime

_PROJECT = Path(__file__).resolve().parent
_DATA_DIR = _PROJECT / "data_raw"

# Patient files under test
PATIENTS = [
    "William_Simmons",
    "Cody_Givens",
    "Timothy_Nachtwey",
]


def _run_evidence(patient_name: str) -> dict:
    """Run the evidence pipeline for a patient and return the JSON object."""
    from cerebralos.ingest.parse_patient_txt import (
        _build_evidence_object, _slugify, get_timestamp_format_counts,
    )

    src = _DATA_DIR / f"{patient_name}.txt"
    if not src.exists():
        print(f"  ERROR: {src} not found")
        return {}

    slug = _slugify(patient_name)
    evidence = _build_evidence_object(src, slug)

    # Write evidence to outputs
    out_dir = _PROJECT / "outputs" / "evidence" / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "patient_evidence_v1.json"
    out_path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    return evidence


def _run_medication_check(patient_name: str) -> dict:
    """Run a quick medication administration timestamp check."""
    from cerebralos.ingest.parse_patient_txt import _build_evidence_object, _slugify

    src = _DATA_DIR / f"{patient_name}.txt"
    slug = _slugify(patient_name)
    evidence = _build_evidence_object(src, slug)

    items = evidence.get("items", [])
    mar_items = [it for it in items if it.get("kind") == "MAR"]

    # Count All Administrations sections found
    import re
    admin_table_count = 0
    admin_rows_with_ts = 0
    for it in mar_items:
        text = it.get("text", "")
        admin_headers = re.findall(r"All Administrations of (.+?)$", text, re.MULTILINE)
        admin_table_count += len(admin_headers)
        # Count action time rows
        action_times = re.findall(
            r"(?:Given|Not Given|New Bag|Rate Change|Bolus)\s*:.*?(\d{1,2}/\d{1,2}/\d{2,4}\s+\d{4})",
            text, re.IGNORECASE
        )
        admin_rows_with_ts += len(action_times)

    return {
        "mar_blocks": len(mar_items),
        "all_administrations_tables": admin_table_count,
        "admin_rows_with_action_time": admin_rows_with_ts,
    }


def main():
    print("=" * 72)
    print("  ACCEPTANCE TEST: Multi-Format EHR Timestamp Normalization")
    print(f"  Run: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 72)
    print()

    combined_format_counts: dict[str, int] = {}
    combined_total_parsed = 0
    combined_total_failed = 0

    for patient in PATIENTS:
        print(f"{'─' * 60}")
        print(f"  Patient: {patient}")
        print(f"{'─' * 60}")

        # 1. Evidence pipeline with timestamp format counts
        evidence = _run_evidence(patient)
        if not evidence:
            continue

        ts_qa = evidence.get("timestamp_format_counts", {})
        format_counts = ts_qa.get("format_counts", {})
        total_parsed = ts_qa.get("total_parsed", 0)
        total_failed = ts_qa.get("total_failed", 0)

        items = evidence.get("items", [])
        n_total = len(items)
        n_with_ts = sum(1 for it in items if it.get("datetime") is not None)

        print(f"  Items total:      {n_total}")
        print(f"  Items with ts:    {n_with_ts}")
        print(f"  Items missing ts: {n_total - n_with_ts}")
        print(f"  Timestamps parsed:{total_parsed}")
        print(f"  Timestamps failed:{total_failed}")
        print()

        # Format breakdown
        print("  timestamp_format_counts:")
        for fmt_name, count in sorted(format_counts.items(), key=lambda x: -x[1]):
            print(f"    {count:5d}  {fmt_name}")
        print()

        # Aggregate
        for k, v in format_counts.items():
            combined_format_counts[k] = combined_format_counts.get(k, 0) + v
        combined_total_parsed += total_parsed
        combined_total_failed += total_failed

        # 2. Medication admin check
        med_info = _run_medication_check(patient)
        print(f"  Medication admin tables:     {med_info['all_administrations_tables']}")
        print(f"  Admin rows with action_time: {med_info['admin_rows_with_action_time']}")
        print()

    # Combined summary
    print()
    print("=" * 72)
    print("  COMBINED QA SUMMARY (all 3 patients)")
    print("=" * 72)
    print()
    print(f"  Total timestamps parsed: {combined_total_parsed}")
    print(f"  Total timestamps failed: {combined_total_failed}")
    if combined_total_parsed + combined_total_failed > 0:
        success_rate = combined_total_parsed / (combined_total_parsed + combined_total_failed) * 100
        print(f"  Success rate:            {success_rate:.1f}%")
    print()
    print("  timestamp_format_counts (combined):")
    for fmt_name, count in sorted(combined_format_counts.items(), key=lambda x: -x[1]):
        print(f"    {count:5d}  {fmt_name}")
    print()

    # Write QA JSON
    qa_output = {
        "acceptance_test": "multi_format_ehr_timestamps",
        "run_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "patients": PATIENTS,
        "combined_format_counts": combined_format_counts,
        "combined_total_parsed": combined_total_parsed,
        "combined_total_failed": combined_total_failed,
    }
    qa_path = _PROJECT / "outputs" / "audit" / "timestamp_format_counts_qa.json"
    qa_path.parent.mkdir(parents=True, exist_ok=True)
    qa_path.write_text(json.dumps(qa_output, indent=2) + "\n", encoding="utf-8")
    print(f"  QA JSON: {qa_path}")
    print()
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
