#!/usr/bin/env python3
"""
CerebralOS — NTDS STRUCTURED GAP REPORT

Reads:
  rules/ntds/<YEAR>/ntds_events_structured_<YEAR>_v1.json

Reports:
- Missing DESCRIPTION section (unless UNPARSED)
- Missing ELEMENT VALUES / ELEMENT VALUE section (unless UNPARSED)
- UNPARSED-only events
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
        raise SystemExit(f"Missing structured file: {p} (run convert_raw_to_structured.py first)")
    return json.loads(p.read_text(encoding="utf-8"))


def has_element_values(sections: Dict[str, Any]) -> bool:
    keys = set((sections or {}).keys())
    return ("ELEMENT VALUES" in keys) or ("ELEMENT VALUE" in keys)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True, choices=[2025, 2026])
    args = ap.parse_args()

    obj = load_structured(args.year)
    events: List[Dict[str, Any]] = obj.get("events", [])

    missing_desc: List[Dict[str, Any]] = []
    missing_vals: List[Dict[str, Any]] = []
    unparsed_only: List[Dict[str, Any]] = []

    for e in events:
        sections = e.get("sections", {}) or {}
        keys = set(sections.keys())

        if keys == {"UNPARSED"}:
            unparsed_only.append(e)

        if ("DESCRIPTION" not in keys) and ("UNPARSED" not in keys):
            missing_desc.append(e)

        if (not has_element_values(sections)) and ("UNPARSED" not in keys):
            missing_vals.append(e)

    print(f"\nNTDS STRUCTURED GAP REPORT — {args.year}")
    print("-" * 60)

    print(f"Missing DESCRIPTION: {len(missing_desc)}")
    for e in missing_desc:
        print(f"  - {str(e.get('event_id')).rjust(2)}  {e.get('canonical_name')}   (UNPARSED={'UNPARSED' in (e.get('sections', {}) or {})})")

    print("\nMissing ELEMENT VALUES: " + str(len(missing_vals)))
    for e in missing_vals:
        print(f"  - {str(e.get('event_id')).rjust(2)}  {e.get('canonical_name')}   (UNPARSED={'UNPARSED' in (e.get('sections', {}) or {})})")

    print("\nUNPARSED-only events: " + str(len(unparsed_only)))
    for e in unparsed_only:
        print(f"  - {str(e.get('event_id')).rjust(2)}  {e.get('canonical_name')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
