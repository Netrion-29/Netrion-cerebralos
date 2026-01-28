#!/usr/bin/env python3
"""
CerebralOS — Deaconess Protocol Extractor (RAW v1)

Reads:
  rules/deaconess/Protocols.txt

Writes:
  rules/deaconess/protocols_deaconess_raw_v1.json
  rules/deaconess/protocol_index_v1.json

Design goals:
- Extract ALL protocols in one deterministic run
- Preserve raw source blocks verbatim
- Fail-closed: never drop data
- Deterministic protocol_id generation (handles duplicates safely)
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List


# -------------------------
# Paths
# -------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_PATH = REPO_ROOT / "rules" / "deaconess" / "Protocols.txt"
OUT_PROTOCOLS = REPO_ROOT / "rules" / "deaconess" / "protocols_deaconess_raw_v1.json"
OUT_INDEX = REPO_ROOT / "rules" / "deaconess" / "protocol_index_v1.json"


# -------------------------
# Helpers
# -------------------------

def slugify(text: str) -> str:
    text = text.upper().strip()
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", "_", text)
    return text


def infer_class(sections: Dict[str, List[str]]) -> str:
    cls = sections.get("Protocol Class", [])
    if not cls:
        return "UNKNOWN"
    if any("CLASS I" in line.upper() for line in cls):
        return "CLASS I"
    if any("CLASS II" in line.upper() for line in cls):
        return "CLASS II"
    return "UNKNOWN"


def build_warnings(sections: Dict[str, List[str]], name: str) -> List[str]:
    warnings = []
    if not sections:
        warnings.append("No sections parsed")
    if "Protocol Class" not in sections:
        warnings.append("Missing Protocol Class")
    if "Trigger Criteria (Exact)" not in sections and "Trigger Criteria" not in sections:
        warnings.append("Missing Trigger Criteria")
    return warnings


# -------------------------
# Main extractor
# -------------------------

def main() -> int:
    print("CerebralOS — Deaconess Protocol Extractor (RAW v1)")
    print(f"Repo root: {REPO_ROOT}")
    print(f"Reading:   {SRC_PATH}")

    if not SRC_PATH.exists():
        raise SystemExit(f"Source file not found: {SRC_PATH}")

    text = SRC_PATH.read_text(encoding="utf-8")

    # Split into protocol blocks
    blocks = re.split(r"\n(?=PROTOCOL:\s*)", text)
    blocks = [b.strip() for b in blocks if b.strip().startswith("PROTOCOL:")]

    protocols = []
    index = []

    # Track duplicate names deterministically
    seen_ids: Dict[str, int] = {}

    for block in blocks:
        lines = block.splitlines()
        header = lines[0]
        name = header.replace("PROTOCOL:", "").strip()

        sections: Dict[str, List[str]] = {}
        current_section = None

        for line in lines[1:]:
            if not line.strip():
                continue

            if re.match(r"^[A-Z][A-Za-z\s/()\-]+:$", line.strip()):
                current_section = line.strip().rstrip(":")
                sections[current_section] = []
            elif current_section:
                sections[current_section].append(line.strip())

        # ---- protocol_id (deterministic + unique) ----
        base_id = slugify(name)
        n = seen_ids.get(base_id, 0) + 1
        seen_ids[base_id] = n
        proto_id = base_id if n == 1 else f"{base_id}__{n}"

        pclass = infer_class(sections)
        warnings = build_warnings(sections, name)

        protocols.append(
            {
                "protocol_id": proto_id,
                "name": name,
                "class": pclass,
                "sections": sections,
                "raw_block": block,
                "extraction_warnings": warnings,
            }
        )

        index.append(
            {
                "protocol_id": proto_id,
                "name": name,
                "class": pclass,
                "warnings_count": len(warnings),
            }
        )

    payload = {
        "meta": {
            "system": "Netrion Systems",
            "product": "CerebralOS",
            "ruleset": "Deaconess Protocols (RAW)",
            "version": "1.0.0",
            "source_file": str(SRC_PATH),
            "protocol_count": len(protocols),
        },
        "protocols": protocols,
    }

    OUT_PROTOCOLS.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    OUT_INDEX.write_text(
        json.dumps(
            {
                "meta": {
                    "version": "1.0.0",
                    "protocol_count": len(index),
                },
                "protocols": index,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"OK ✅ Extracted protocols: {len(protocols)}")
    print(f"Wrote: {OUT_PROTOCOLS}")
    print(f"Wrote: {OUT_INDEX}")

    warned = [p for p in index if p["warnings_count"] > 0]
    if warned:
        print(f"⚠️  Protocols with warnings: {len(warned)} (review later; extraction still succeeded)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

