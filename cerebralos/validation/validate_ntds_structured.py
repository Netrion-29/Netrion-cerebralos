#!/usr/bin/env python3
"""
CerebralOS — NTDS STRUCTURED Validator (v1)

Validates:
  rules/ntds/<YEAR>/ntds_events_structured_<YEAR>_v1.json

Hard fails:
- Must contain exactly 21 events.
- Must contain event_id 1..21 exactly once.
- Each event must include provenance.raw_text_sha256.
- Each event must include canonical_name and ntds_year.
- Event 20 name must match year:
    2025: Unplanned Visit to the Operating Room
    2026: Unplanned Return to the Operating Room

Warnings:
- Missing DESCRIPTION section
- Missing ELEMENT VALUES section
- Excessive warnings_count
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_structured(year: int) -> Dict[str, Any]:
    p = REPO_ROOT / "rules" / "ntds" / str(year) / f"ntds_events_structured_{year}_v1.json"
    if not p.exists():
        raise SystemExit(f"Missing: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True, choices=[2025, 2026])
    args = ap.parse_args()
    year = args.year

    obj = load_structured(year)
    events: List[Dict[str, Any]] = obj.get("events", [])

    print(f"\nCerebralOS — Validate NTDS STRUCTURED — {year}")
    print("PASS ✅ JSON parsed")
    print("Event count:", len(events))

    # Hard: count must be 21
    if len(events) != 21:
        raise SystemExit("FAIL ❌ Expected exactly 21 events.")

    # Hard: event_id 1..21 exactly once
    ids = [e.get("event_id") for e in events]
    if any(not isinstance(i, int) for i in ids):
        raise SystemExit("FAIL ❌ Non-integer event_id found.")

    expected = set(range(1, 22))
    got = set(ids)

    missing_ids = sorted(expected - got)
    extra_ids = sorted(got - expected)

    if missing_ids or extra_ids:
        raise SystemExit(f"FAIL ❌ event_id inventory mismatch. missing={missing_ids} extra={extra_ids}")

    if len(ids) != len(set(ids)):
        raise SystemExit("FAIL ❌ Duplicate event_id detected.")

    # Hard: required keys + provenance hash
    for i, e in enumerate(events):
        if e.get("ntds_year") != year:
            raise SystemExit(f"FAIL ❌ events[{i}] ntds_year mismatch (expected {year}).")

        if not e.get("canonical_name"):
            raise SystemExit(f"FAIL ❌ events[{i}] missing canonical_name.")

        prov = e.get("provenance") or {}
        if not prov.get("raw_text_sha256"):
            raise SystemExit(f"FAIL ❌ events[{i}] missing provenance.raw_text_sha256.")

        if not isinstance(e.get("sections"), dict):
            raise SystemExit(f"FAIL ❌ events[{i}] sections is not a dict.")

    # Hard: year-specific Event 20 naming
    ev20 = [e for e in events if e.get("event_id") == 20]
    if len(ev20) != 1:
        raise SystemExit("FAIL ❌ Could not locate event_id=20 exactly once.")

    ev20_name = (ev20[0].get("canonical_name") or "").strip()
    if year == 2025 and "Unplanned Visit to the Operating Room" != ev20_name:
        raise SystemExit(f"FAIL ❌ 2025 event 20 name mismatch: {ev20_name!r}")
    if year == 2026 and "Unplanned Return to the Operating Room" != ev20_name:
        raise SystemExit(f"FAIL ❌ 2026 event 20 name mismatch: {ev20_name!r}")

    # Soft warnings
    warn_missing_desc = 0
    warn_missing_vals = 0
    high_warn = 0

    for e in events:
        sections = e.get("sections") or {}
        if "DESCRIPTION" not in sections and "UNPARSED" not in sections:
            warn_missing_desc += 1
        if "ELEMENT VALUES" not in sections and "UNPARSED" not in sections:
            warn_missing_vals += 1

        w = e.get("warnings") or []
        if isinstance(w, list) and len(w) >= 12:
            high_warn += 1

    print("PASS ✅ Hard gates satisfied")
    if warn_missing_desc:
        print(f"⚠️  WARNING: {warn_missing_desc} events missing DESCRIPTION section (or only UNPARSED).")
    if warn_missing_vals:
        print(f"⚠️  WARNING: {warn_missing_vals} events missing ELEMENT VALUES section (or only UNPARSED).")
    if high_warn:
        print(f"⚠️  WARNING: {high_warn} events have >=12 warnings (review recommended).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
