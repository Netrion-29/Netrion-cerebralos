#!/usr/bin/env python3
"""
CerebralOS — NTDS Convert RAW → STRUCTURED (v2)

Key guarantee:
- Always reads the *latest* RAW file for the year (e.g., v9) so you can't accidentally
  convert an older, broken extract.
- Deterministic section parsing (case-insensitive headers).
- Adds provenance.raw_text_sha256 + source_raw filename + page receipts.

Writes:
  rules/ntds/<YEAR>/ntds_events_structured_<YEAR>_v1.json
  rules/ntds/<YEAR>/ntds_index_structured_<YEAR>_v1.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]

SECTION_HEADERS = [
    "ELEMENT INTENT",
    "DESCRIPTION",
    "DEFINITION",
    "EXCLUDE",
    "ELEMENT VALUES",
    "ELEMENT VALUE",
    "ADDITIONAL INFORMATION",
    "DATA SOURCE HIERARCHY GUIDE",
    "ASSOCIATED EDIT CHECKS",
]

_SECTION_SET = {h.upper() for h in SECTION_HEADERS}


def sha256_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clean(s: str) -> str:
    s = (s or "").replace("\u00a0", " ").replace("\r", "\n")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def norm_header(line: str) -> str:
    """
    Normalize a line so headers match even if:
    - "Element intent" vs "Element Intent" vs "ELEMENT INTENT"
    - extra spaces
    - trailing colon
    """
    t = (line or "").strip().strip(":")
    t = re.sub(r"\s+", " ", t)
    return t.upper()


def split_sections(raw_text: str) -> Dict[str, str]:
    """
    Case-insensitive, deterministic section splitter.
    Returns dict {HEADER: CONTENT}.
    """
    sections: Dict[str, List[str]] = {}
    current: Optional[str] = None

    for ln in (raw_text or "").splitlines():
        h = norm_header(ln)
        if h in _SECTION_SET:
            current = h
            sections[current] = []
            continue

        if current is not None:
            sections[current].append(ln)

    # finalize
    out: Dict[str, str] = {}
    for k, lines in sections.items():
        out[k] = clean("\n".join(lines))

    return out


def latest_raw_path(year: int) -> Path:
    """
    Picks the highest vN file in:
      rules/ntds/<YEAR>/ntds_events_raw_<YEAR>_vN.json

    This prevents converting stale/broken extracts.
    """
    folder = REPO_ROOT / "rules" / "ntds" / str(year)
    pat = re.compile(rf"^ntds_events_raw_{year}_v(\d+)\.json$")

    best_v = -1
    best_path: Optional[Path] = None

    for p in folder.glob(f"ntds_events_raw_{year}_v*.json"):
        m = pat.match(p.name)
        if not m:
            continue
        v = int(m.group(1))
        if v > best_v:
            best_v = v
            best_path = p

    if not best_path:
        raise SystemExit(f"No RAW files found in {folder} for year={year}. Run extract first.")
    return best_path


def run(year: int) -> int:
    raw_path = latest_raw_path(year)

    out_struct = REPO_ROOT / "rules" / "ntds" / str(year) / f"ntds_events_structured_{year}_v1.json"
    out_index = REPO_ROOT / "rules" / "ntds" / str(year) / f"ntds_index_structured_{year}_v1.json"

    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    meta = raw.get("meta", {})

    events_out: List[Dict[str, Any]] = []
    index_out: List[Dict[str, Any]] = []

    for ev in raw.get("events", []):
        event_id = ev.get("event_id")
        event_name = ev.get("event_name")

        raw_text = ev.get("raw_text", "") or ""
        sections = split_sections(raw_text)

        # Fail-closed: if nothing split but raw_text exists, park it under UNPARSED
        if not sections and raw_text.strip():
            sections = {"UNPARSED": clean(raw_text)}

        # Some RAWs include these
        pages = ev.get("pages", []) or []
        pdf_start_page = ev.get("pdf_start_page", None)
        pdf_end_page = ev.get("pdf_end_page", None)

        # Minimal warnings
        warnings: List[str] = []
        if not raw_text.strip():
            warnings.append("EMPTY_RAW_TEXT")
        if "DESCRIPTION" not in sections and "UNPARSED" not in sections:
            warnings.append("MISSING_DESCRIPTION_SECTION")
        if ("ELEMENT VALUES" not in sections and "ELEMENT VALUE" not in sections and "UNPARSED" not in sections):
            warnings.append("MISSING_ELEMENT_VALUES_SECTION")

        payload_event = {
            "event_id": event_id,
            "canonical_name": event_name,
            "ntds_year": year,
            "sections": sections,
            "provenance": {
                "source_pdf": meta.get("source_pdf"),
                "source_raw": str(raw_path),
                "raw_text_sha256": sha256_text(raw_text),
                "pdf_start_page": pdf_start_page,
                "pdf_end_page": pdf_end_page,
                "pages": pages,
                "converted_at_utc": now_utc_iso(),
                "converter_version": "2.0.0",
            },
            "warnings": warnings,
        }

        events_out.append(payload_event)

        index_out.append(
            {
                "event_id": event_id,
                "canonical_name": event_name,
                "ntds_year": year,
                "sections_present": list(sections.keys()),
                "warnings_count": len(warnings),
                "source_raw": str(raw_path),
            }
        )

    struct = {
        "meta": {
            "system": meta.get("system", "Netrion Systems"),
            "product": meta.get("product", "CerebralOS"),
            "ruleset": "NTDS Hospital Events (STRUCTURED)",
            "year": year,
            "version": "1.0.0",
            "source_pdf": meta.get("source_pdf"),
            "source_raw": str(raw_path),
            "event_count": len(events_out),
            "converted_at_utc": now_utc_iso(),
            "converter_version": "2.0.0",
        },
        "events": events_out,
    }

    out_struct.write_text(json.dumps(struct, indent=2), encoding="utf-8")
    out_index.write_text(json.dumps({"meta": struct["meta"], "events": index_out}, indent=2), encoding="utf-8")

    print(f"OK ✅ Structured NTDS events written: {out_struct}")
    print(f"OK ✅ Structured index written:      {out_index}")
    print(f"Using RAW: {raw_path.name}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True, choices=[2025, 2026])
    args = ap.parse_args()
    return run(args.year)


if __name__ == "__main__":
    raise SystemExit(main())
