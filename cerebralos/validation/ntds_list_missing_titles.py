#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
P = REPO_ROOT / "rules" / "ntds" / "2025" / "ntds_events_raw_2025_v2.json"

def main() -> int:
    obj = json.loads(P.read_text(encoding="utf-8"))
    events = obj.get("events", [])

    missing = [
        e["event_name"]
        for e in events
        if "TITLE_NOT_FOUND_IN_PDF" in (e.get("extraction_warnings") or [])
    ]

    print("Missing count:", len(missing))
    for t in missing:
        print("-", t)

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
