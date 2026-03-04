#!/usr/bin/env python3
"""
audit_cohort_counts.py — Canonical cohort counting audit for NTDS outputs.

Purpose:
  - Define the canonical population from data_raw/*.txt
  - Compare against outputs/ntds/* directory slugs
  - Separate true patient output dirs from fixture/stale artifact dirs

Usage:
  python3 scripts/audit_cohort_counts.py
  python3 scripts/audit_cohort_counts.py --json
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List


RE_FIXTURE_SLUG = re.compile(r"^\d{2}_.+")


def _slugify(stem: str) -> str:
    """Match runtime slug convention: spaces -> underscores."""
    return stem.replace(" ", "_")


def _collect(repo_root: Path) -> Dict[str, object]:
    data_raw = repo_root / "data_raw"
    outputs_ntds = repo_root / "outputs" / "ntds"

    canonical_files = sorted(data_raw.glob("*.txt"))
    canonical_slugs = sorted({_slugify(p.stem) for p in canonical_files})
    canonical_set = set(canonical_slugs)

    output_dirs = sorted([p.name for p in outputs_ntds.iterdir() if p.is_dir()]) if outputs_ntds.exists() else []
    output_slug_count = len(output_dirs)

    fixture_dirs: List[str] = []
    non_fixture_dirs: List[str] = []
    for name in output_dirs:
        if RE_FIXTURE_SLUG.match(name):
            fixture_dirs.append(name)
        else:
            non_fixture_dirs.append(name)

    groups: Dict[str, List[str]] = defaultdict(list)
    for name in non_fixture_dirs:
        groups[_slugify(name)].append(name)

    space_variant_duplicates: List[str] = []
    for norm, names in sorted(groups.items()):
        if len(names) > 1 and any(" " in n for n in names):
            space_named = sorted([n for n in names if " " in n])
            underscore_named = sorted([n for n in names if " " not in n])
            if underscore_named:
                for s in space_named:
                    for u in underscore_named:
                        space_variant_duplicates.append(f"{s} / {u}")

    deduped_output_slugs = sorted(groups.keys())
    deduped_output_count = len(deduped_output_slugs)

    extra_slugs = sorted([slug for slug in deduped_output_slugs if slug not in canonical_set])
    missing_slugs = sorted([slug for slug in canonical_slugs if slug not in groups])

    adjusted_output_count = len([slug for slug in deduped_output_slugs if slug in canonical_set])

    return {
        "canonical_count": len(canonical_slugs),
        "output_slug_count": output_slug_count,
        "fixture_dirs": fixture_dirs,
        "space_variant_duplicates": space_variant_duplicates,
        "true_patient_dirs_after_dedup_count": adjusted_output_count,
        "extra_slugs": extra_slugs,
        "missing_slugs": missing_slugs,
        "policy": (
            "Canonical cohort is data_raw/*.txt. Report raw outputs/ntds dir count, then adjusted count "
            "after excluding test fixture dirs (NN_*) and space/underscore duplicate slugs."
        ),
    }


def _print_text(report: Dict[str, object]) -> None:
    fixture_dirs = report["fixture_dirs"]
    dupes = report["space_variant_duplicates"]

    print("Cohort Counting Audit")
    print("=" * 60)
    print(f"canonical_count: {report['canonical_count']}")
    print(f"output_slug_count: {report['output_slug_count']}")
    print("")
    print("Breakdown")
    print("-" * 60)
    print(f"test_fixture_dirs: {len(fixture_dirs)}")
    if fixture_dirs:
        print("  " + ", ".join(fixture_dirs))
    print(f"space_variant_duplicates: {len(dupes)}")
    if dupes:
        print("  " + ", ".join(dupes))
    print(f"true_patient_dirs_after_dedup_count: {report['true_patient_dirs_after_dedup_count']}")
    print("")
    print(f"extra_slugs: {report['extra_slugs']}")
    print(f"missing_slugs: {report['missing_slugs']}")
    print("")
    print("Cohort Counting Policy")
    print("-" * 60)
    print(report["policy"])


def check_invariant(report: Dict[str, object]) -> tuple[bool, list[str]]:
    """Return (ok, messages).  ok=True iff cohort is consistent.

    Invariant:
      - true_patient_dirs_after_dedup_count == canonical_count
      - extra_slugs is empty
      - missing_slugs is empty
    """
    messages: list[str] = []
    ok = True

    canonical = report["canonical_count"]
    adjusted = report["true_patient_dirs_after_dedup_count"]
    extra = report["extra_slugs"]
    missing = report["missing_slugs"]

    if adjusted != canonical:
        messages.append(
            f"FAIL: adjusted output count ({adjusted}) != canonical count ({canonical})"
        )
        ok = False

    if extra:
        messages.append(f"FAIL: extra slugs in outputs/ntds: {extra}")
        ok = False

    if missing:
        messages.append(f"FAIL: missing slugs from outputs/ntds: {missing}")
        ok = False

    if ok:
        messages.append(
            f"PASS: cohort invariant holds — {canonical} canonical, "
            f"{adjusted} adjusted output dirs, 0 extra, 0 missing."
        )

    return ok, messages


def main() -> int:
    ap = argparse.ArgumentParser(description="Audit canonical cohort count vs outputs/ntds slugs.")
    ap.add_argument("--json", action="store_true", help="Emit JSON output only.")
    ap.add_argument(
        "--check",
        action="store_true",
        help="Enforce cohort invariant: exit non-zero on mismatch.",
    )
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    report = _collect(repo_root)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_text(report)

    if args.check:
        ok, messages = check_invariant(report)
        print()
        for msg in messages:
            print(msg)
        if not ok:
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
