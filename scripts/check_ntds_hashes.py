#!/usr/bin/env python3
"""Check (or update) NTDS event output hashes against a stored baseline.

Usage:
    python3 scripts/check_ntds_hashes.py              # verify against baseline
    python3 scripts/check_ntds_hashes.py --update      # regenerate baseline
    python3 scripts/check_ntds_hashes.py --patient X   # verify single patient
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
NTDS_DIR = REPO_ROOT / "outputs" / "ntds"
BASELINE_FILE = REPO_ROOT / "scripts" / "baselines" / "ntds_hashes_v1.json"


def _hash_patient(patient_dir: Path) -> str:
    """SHA-256 composite hash of all ntds_event_*_v1.json files (sorted)."""
    event_files = sorted(patient_dir.glob("ntds_event_*_v1.json"))
    h = hashlib.sha256()
    for ef in event_files:
        h.update(ef.read_bytes())
    return h.hexdigest()


def collect_current(patient_filter: str | None = None) -> dict[str, str]:
    """Return {patient_slug: composite_hash} for all real patient dirs."""
    hashes: dict[str, str] = {}
    for patient_dir in sorted(NTDS_DIR.iterdir()):
        if not patient_dir.is_dir():
            continue
        name = patient_dir.name
        # Skip admin dirs (underscore prefix) and fixture dirs (digit prefix)
        if name.startswith("_") or name[0].isdigit():
            continue
        if patient_filter and name != patient_filter:
            continue
        event_files = list(patient_dir.glob("ntds_event_*_v1.json"))
        if not event_files:
            continue
        hashes[name] = _hash_patient(patient_dir)
    return hashes


def check(patient_filter: str | None = None) -> bool:
    """Compare current NTDS hashes against stored baseline. Returns True on pass."""
    if not BASELINE_FILE.is_file():
        print(f"ERROR: baseline file not found: {BASELINE_FILE}")
        print("Run: python3 scripts/check_ntds_hashes.py --update")
        return False

    baseline = json.loads(BASELINE_FILE.read_text(encoding="utf-8"))
    current = collect_current(patient_filter)

    if patient_filter:
        # Only check the single patient
        all_pats = sorted(set(list(current) + [p for p in baseline if p == patient_filter]))
    else:
        all_pats = sorted(set(list(current) + list(baseline)))

    ok = True
    for pat in all_pats:
        cur = current.get(pat)
        base = baseline.get(pat)
        if cur is None:
            print(f"MISSING in current outputs: {pat}")
            ok = False
        elif base is None:
            print(f"MISSING in baseline: {pat} (present in outputs)")
            ok = False
        elif base != cur:
            print(f"MISMATCH {pat}: baseline={base[:16]}... current={cur[:16]}...")
            ok = False
        else:
            print(f"MATCH    {pat}")

    if ok:
        print(f"\nNo NTDS drift. {len(all_pats)} patients verified.")
    else:
        print(f"\nNTDS DRIFT DETECTED.")
    return ok


def update() -> None:
    """Regenerate the baseline file from current outputs."""
    current = collect_current()
    BASELINE_FILE.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_FILE.write_text(
        json.dumps(current, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Updated NTDS baseline: {BASELINE_FILE} ({len(current)} patients)")


def main() -> None:
    parser = argparse.ArgumentParser(description="NTDS event output hash checker")
    parser.add_argument("--update", action="store_true", help="Regenerate baseline")
    parser.add_argument("--patient", type=str, default=None, help="Check single patient")
    args = parser.parse_args()

    if args.update:
        update()
    else:
        ok = check(args.patient)
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
