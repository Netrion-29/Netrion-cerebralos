#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True, choices=[2025, 2026])
    args = ap.parse_args()

    p = REPO_ROOT / "rules" / "ntds" / str(args.year) / f"ntds_events_raw_{args.year}_v1.json"
    if not p.exists():
        raise SystemExit(f"Missing: {p}")

    obj = json.loads(p.read_text(encoding="utf-8"))
    events = obj.get("events", [])

    print("PASS ✅ JSON parsed")
    print("Year:", args.year)
    print("Event count:", len(events))

    # Heuristic sanity only (PDF extraction may create extra blocks)
    if len(events) < 10:
        raise SystemExit("FAIL ❌ Too few blocks extracted — heading detection likely too strict.")
    if len(events) > 200:
        raise SystemExit("FAIL ❌ Too many blocks — heading detection likely too permissive.")

    required = {"event_id", "event_name", "pages", "raw_text", "extraction_warnings"}
    for i, e in enumerate(events[:20]):
        missing = required - set(e.keys())
        if missing:
            raise SystemExit(f"FAIL ❌ events[{i}] missing keys: {sorted(missing)}")

    ids = [e["event_id"] for e in events]
    if len(ids) != len(set(ids)):
        raise SystemExit("FAIL ❌ Duplicate event_id detected.")

    print("PASS ✅ Basic schema + duplicates ok")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

