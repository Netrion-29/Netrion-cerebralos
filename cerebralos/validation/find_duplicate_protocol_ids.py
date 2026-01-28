#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
P = REPO_ROOT / "rules" / "deaconess" / "protocols_deaconess_raw_v1.json"

def main() -> int:
    obj = json.loads(P.read_text(encoding="utf-8"))
    protos = obj.get("protocols", [])
    ids = [p.get("protocol_id") for p in protos]

    c = Counter(ids)
    dupes = [pid for pid, n in c.items() if n and n > 1]

    print(f"Total protocols: {len(protos)}")
    print(f"Unique IDs: {len(set(ids))}")
    print(f"Duplicate IDs: {len(dupes)}")

    for pid in sorted(dupes):
        print("\nDUPLICATE protocol_id:", pid)
        for p in protos:
            if p.get("protocol_id") == pid:
                print(" - name:", p.get("name"))

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
