#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_FILE_RE = re.compile(r"^ntds_events_raw_(?P<year>\d{4})_v(?P<v>\d+)\.json$")

HEADINGS = [
    "DESCRIPTION",
    "DEFINITION",
    "ELEMENT INTENT",
    "ELEMENT VALUES",
    "ELEMENT VALUE",
    "ADDITIONAL INFORMATION",
    "DATA SOURCE HIERARCHY GUIDE",
    "ASSOCIATED EDIT CHECKS",
    "EXCLUDE",
]


def find_latest_raw(year: int) -> Path:
    folder = REPO_ROOT / "rules" / "ntds" / str(year)
    if not folder.exists():
        raise SystemExit(f"Missing folder: {folder}")

    best_v = -1
    best: Optional[Path] = None
    for p in folder.iterdir():
        m = RAW_FILE_RE.match(p.name)
        if not m:
            continue
        if int(m.group("year")) != year:
            continue
        v = int(m.group("v"))
        if v > best_v:
            best_v = v
            best = p

    if not best:
        raise SystemExit(f"No RAW files found for year {year} in {folder}")
    return best


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True, choices=[2025, 2026])
    ap.add_argument("--event", type=int, required=True, choices=list(range(1, 22)))
    ap.add_argument("--lines", type=int, default=120, help="How many lines to print (default 120)")
    args = ap.parse_args()

    raw_path = find_latest_raw(args.year)
    obj = json.loads(raw_path.read_text(encoding="utf-8"))
    events: List[Dict[str, Any]] = obj.get("events", [])

    ev = next((e for e in events if int(e.get("event_id", -1)) == args.event), None)
    if not ev:
        raise SystemExit(f"Could not find RAW event_id={args.event} in {raw_path}")

    name = (ev.get("event_name") or "").strip()
    raw_text = ev.get("raw_text") or ""
    u = raw_text.upper()

    print(f"\nRAW DEBUG — year={args.year} event_id={args.event} name={name}")
    print(f"RAW file: {raw_path}")
    print(f"raw_text length: {len(raw_text)}")
    print("-" * 60)

    for h in HEADINGS:
        print(f"{h:26} present? {'YES' if h in u else 'NO'}")

    print("-" * 60)
    print(f"FIRST {args.lines} LINES (verbatim):")
    lines = raw_text.splitlines()
    for i, ln in enumerate(lines[: args.lines], start=1):
        print(f"{i:03d}: {ln}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
