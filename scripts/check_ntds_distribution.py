#!/usr/bin/env python3
"""Check (or update) per-event NTDS outcome distribution against a stored baseline.

Scans all patient output directories in outputs/ntds/ and tallies
YES / NO / UNABLE_TO_DETERMINE / EXCLUDED counts per event.  Compares
against the baseline in scripts/baselines/ntds_distribution_v1.json.

Usage:
    python3 scripts/check_ntds_distribution.py               # verify
    python3 scripts/check_ntds_distribution.py --update       # regenerate baseline
    python3 scripts/check_ntds_distribution.py --summary      # print table only
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
NTDS_DIR = REPO_ROOT / "outputs" / "ntds"
BASELINE_FILE = REPO_ROOT / "scripts" / "baselines" / "ntds_distribution_v1.json"

# Canonical outcome ordering for display
_OUTCOME_ORDER = ["YES", "NO", "UNABLE_TO_DETERMINE", "EXCLUDED"]


def _patient_dirs() -> list[Path]:
    """Return sorted real patient directories (skip admin/fixture dirs)."""
    dirs = []
    for d in sorted(NTDS_DIR.iterdir()):
        if not d.is_dir():
            continue
        name = d.name
        if name.startswith("_") or name[0].isdigit():
            continue
        dirs.append(d)
    return dirs


def collect_current() -> dict[str, dict[str, int]]:
    """Return {event_key: {outcome: count}} for all 2026 event files."""
    dist: dict[str, Counter[str]] = {}
    for pdir in _patient_dirs():
        for ef in sorted(pdir.glob("ntds_event_*_2026_v1.json")):
            data = json.loads(ef.read_text(encoding="utf-8"))
            eid = ef.name.replace("ntds_event_", "").replace("_2026_v1.json", "")
            key = f"E{eid}"
            dist.setdefault(key, Counter())[data["outcome"]] += 1
    # Convert Counter to plain dict (sorted by canonical order)
    result: dict[str, dict[str, int]] = {}
    for key in sorted(dist):
        c = dist[key]
        result[key] = {o: c[o] for o in _OUTCOME_ORDER if c.get(o, 0) > 0}
    return result


def _fmt_dist(d: dict[str, int]) -> str:
    """Format a single event distribution for human display."""
    parts = []
    for o in _OUTCOME_ORDER:
        v = d.get(o, 0)
        if v:
            parts.append(f"{o}={v}")
    return " ".join(parts)


def print_summary(current: dict[str, dict[str, int]]) -> None:
    """Print a human-readable distribution table."""
    total_patients = 0
    for eid in sorted(current):
        row = current[eid]
        n = sum(row.values())
        if n > total_patients:
            total_patients = n
        print(f"  {eid:>3}: {_fmt_dist(row):50s} (n={n})")
    print(f"\n  Patients: {total_patients}")


def check() -> bool:
    """Compare current distribution against stored baseline. Returns True on pass."""
    if not BASELINE_FILE.is_file():
        print(f"ERROR: distribution baseline not found: {BASELINE_FILE}")
        print("Run: python3 scripts/check_ntds_distribution.py --update")
        return False

    baseline = json.loads(BASELINE_FILE.read_text(encoding="utf-8"))
    current = collect_current()

    all_events = sorted(set(list(current) + list(baseline)))
    ok = True
    deltas: list[str] = []

    for eid in all_events:
        cur = current.get(eid, {})
        base = baseline.get(eid, {})
        if cur == base:
            print(f"MATCH    {eid}: {_fmt_dist(cur)}")
        else:
            ok = False
            # Build delta description
            all_outcomes = sorted(set(list(cur) + list(base)))
            changes = []
            for o in all_outcomes:
                bv = base.get(o, 0)
                cv = cur.get(o, 0)
                if bv != cv:
                    changes.append(f"{o} {bv}→{cv}")
            delta_str = ", ".join(changes)
            print(f"DELTA    {eid}: {delta_str}")
            deltas.append(f"{eid}: {delta_str}")

    if ok:
        print(f"\nNo NTDS distribution drift. {len(all_events)} events verified.")
    else:
        print(f"\nNTDS DISTRIBUTION DRIFT DETECTED ({len(deltas)} event(s) changed):")
        for d in deltas:
            print(f"  {d}")
    return ok


def update() -> None:
    """Regenerate the baseline file from current outputs."""
    current = collect_current()
    BASELINE_FILE.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_FILE.write_text(
        json.dumps(current, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Updated NTDS distribution baseline: {BASELINE_FILE} ({len(current)} events)")
    print_summary(current)


def main() -> None:
    parser = argparse.ArgumentParser(description="NTDS per-event distribution checker")
    parser.add_argument("--update", action="store_true", help="Regenerate baseline")
    parser.add_argument("--summary", action="store_true", help="Print distribution table only")
    args = parser.parse_args()

    if args.update:
        update()
    elif args.summary:
        current = collect_current()
        print_summary(current)
    else:
        if not check():
            sys.exit(1)


if __name__ == "__main__":
    main()
