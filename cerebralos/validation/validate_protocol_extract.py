#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

# This file lives at: cerebralos/validation/validate_protocol_extract.py
# Repo root is:      netrion-cerebralos/
REPO_ROOT = Path(__file__).resolve().parents[2]

P = REPO_ROOT / "rules" / "deaconess" / "protocols_deaconess_raw_v1.json"

def main() -> int:
    if not P.exists():
        raise SystemExit(f"Missing: {P}")

    obj = json.loads(P.read_text(encoding="utf-8"))
    protos = obj.get("protocols", [])

    print("PASS ✅ JSON parsed")
    print("Protocol count:", len(protos))

    if len(protos) < 30:
        raise SystemExit("FAIL ❌ Too few protocols extracted — likely split issue.")

    # required keys sanity check (first 10)
    for i, p in enumerate(protos[:10]):
        for k in ("protocol_id", "name", "class", "sections", "raw_block"):
            if k not in p:
                raise SystemExit(f"FAIL ❌ Missing key {k} in protocol[{i}]")

    # duplicates
    ids = [p.get("protocol_id") for p in protos]
    if len(ids) != len(set(ids)):
        raise SystemExit("FAIL ❌ Duplicate protocol_id detected.")

    print("PASS ✅ Basic schema + duplicates ok")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

