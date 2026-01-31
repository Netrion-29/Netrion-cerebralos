#!/usr/bin/env python3
"""
CerebralOS — NTDS Convert RAW → STRUCTURED (v1.5)

Fixes:
- Robust section header detection (colons, Title Case, split headers like "ELEMENT"+"VALUES")
- Inline header support (header + body on same line)
- Deterministic fallbacks for events where DESCRIPTION/ELEMENT VALUES are not clean headers (notably DVT)

Reads:
  rules/ntds/<YEAR>/ntds_events_raw_<YEAR>_v7.json

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

CANON_KEYS = {
    "ELEMENT INTENT",
    "DESCRIPTION",
    "DEFINITION",
    "ELEMENT VALUES",
    "ADDITIONAL INFORMATION",
    "DATA SOURCE HIERARCHY GUIDE",
    "ASSOCIATED EDIT CHECKS",
    "EXCLUDE",
}

HEADER_PATTERNS: List[Tuple[str, re.Pattern[str]]] = [
    ("ELEMENT INTENT", re.compile(r"^\s*element\s+intent\s*:?\s*$", re.I)),
    ("DESCRIPTION", re.compile(r"^\s*description\s*:?\s*$", re.I)),
    ("DEFINITION", re.compile(r"^\s*definition\s*:?\s*$", re.I)),
    ("ELEMENT VALUES", re.compile(r"^\s*element\s+values?\s*:?\s*$", re.I)),
    ("ADDITIONAL INFORMATION", re.compile(r"^\s*additional\s+information\s*:?\s*$", re.I)),
    ("DATA SOURCE HIERARCHY GUIDE", re.compile(r"^\s*data\s+source\s+hierarchy\s+guide\s*:?\s*$", re.I)),
    ("ASSOCIATED EDIT CHECKS", re.compile(r"^\s*associated\s+edit\s+checks\s*:?\s*$", re.I)),
    ("EXCLUDE", re.compile(r"^\s*exclude\s*:?\s*$", re.I)),
]

SPLIT_HEADER_PAIRS: Dict[Tuple[str, str], str] = {
    ("ELEMENT", "VALUES"): "ELEMENT VALUES",
    ("ELEMENT", "VALUE"): "ELEMENT VALUES",
    ("DATA", "SOURCE HIERARCHY GUIDE"): "DATA SOURCE HIERARCHY GUIDE",
    ("ASSOCIATED", "EDIT CHECKS"): "ASSOCIATED EDIT CHECKS",
    ("ADDITIONAL", "INFORMATION"): "ADDITIONAL INFORMATION",
    ("ELEMENT", "INTENT"): "ELEMENT INTENT",
}


def sha256(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8", errors="replace")).hexdigest()


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _merge_split_headers(lines: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(lines):
        a = (lines[i] or "").strip()
        if i + 1 < len(lines):
            b = (lines[i + 1] or "").strip()
            a_u = a.upper().rstrip(":").strip()
            b_u = b.upper().rstrip(":").strip()
            key = (a_u, b_u)
            if key in SPLIT_HEADER_PAIRS:
                out.append(SPLIT_HEADER_PAIRS[key])
                i += 2
                continue
        out.append(lines[i])
        i += 1
    return out


def _detect_header_with_inline_body(line: str) -> Tuple[Optional[str], Optional[str]]:
    s = (line or "").strip()
    if not s:
        return (None, None)

    s_clean = re.sub(r"\s+", " ", s).strip()

    # header-only line
    for canon, pat in HEADER_PATTERNS:
        if pat.match(s_clean):
            return (canon, None)

    # inline header: "Description blah blah"
    for canon in CANON_KEYS:
        words = canon.split()
        start_re = r"^\s*" + r"\s+".join(re.escape(w) for w in words) + r"\s*:?\s+(.+)$"
        m = re.match(start_re, s_clean, flags=re.IGNORECASE)
        if m:
            return (canon, m.group(1).strip())

    # exact canonical key
    u = s_clean.upper().rstrip(":").strip()
    if u in CANON_KEYS:
        return (u, None)

    return (None, None)


def split_sections(raw_text: str) -> Dict[str, str]:
    raw_lines = (raw_text or "").splitlines()
    lines = _merge_split_headers(raw_lines)

    sections: Dict[str, List[str]] = {}
    current: Optional[str] = None

    for ln in lines:
        hdr, inline_body = _detect_header_with_inline_body(ln)
        if hdr:
            current = hdr
            sections.setdefault(current, [])
            if inline_body:
                sections[current].append(inline_body)
            continue

        if current:
            sections[current].append(ln)

    out: Dict[str, str] = {}
    for k, v in sections.items():
        body = "\n".join(v).strip()
        if body:
            out[k] = body
    return out


# -------------------------
# Deterministic fallbacks
# -------------------------

_NOISE_PAT = re.compile(
    r"^(?:HOSPITAL EVENTS|PAGE\s+\d+|Copyright|Consistent with|Refer to complete NTDS|=== PAGE)",
    re.IGNORECASE,
)

_STOP_HEADER_ANYWHERE_PAT = re.compile(
    r"\b(?:Additional Information|Data Source Hierarchy Guide|Associated Edit Checks|Element Intent|Element Values?|Exclude|Definition|Description)\b",
    re.IGNORECASE,
)

def _meaningful_lines(raw_text: str) -> List[str]:
    lines = []
    for ln in (raw_text or "").splitlines():
        s = ln.strip()
        if not s:
            continue
        if _NOISE_PAT.search(s):
            continue
        lines.append(s)
    return lines


def fallback_description(event_name: str, raw_text: str) -> str:
    """
    Deterministic DESCRIPTION fallback:
    - Take early meaningful lines after the title if present
    - Otherwise take first meaningful paragraph
    - Stop when another known section header appears (anywhere in a line)
    """
    lines = _meaningful_lines(raw_text)
    if not lines:
        return ""

    title_u = (event_name or "").strip().upper()
    start = 0

    # Try to start after title line if present
    for i, ln in enumerate(lines[:80]):
        if title_u and ln.upper() == title_u:
            start = i + 1
            break
        if title_u and title_u in ln.upper():
            start = i + 1
            break

    buf: List[str] = []
    for ln in lines[start:start + 60]:
        # If we hit another section header line early, stop (but allow first line through)
        hdr, inline = _detect_header_with_inline_body(ln)
        if hdr and buf:
            break

        # Also stop if line contains another section marker prominently
        if _STOP_HEADER_ANYWHERE_PAT.search(ln) and buf:
            # If the line is basically a header-ish line, stop
            if len(ln) <= 40:
                break

        buf.append(ln)

        # Stop at a reasonable paragraph size
        if len(buf) >= 12:
            break

    return "\n".join(buf).strip()


_QUOTE_OPT_PAT = re.compile(r"[“\"](\d+\.\s*[^”\"]+)[”\"]")
_ENUM_OPT_PAT = re.compile(r"^\d+\.\s+\S+")
_REPORT_EV_PAT = re.compile(r"\bReport\b.*\bElement Value\b", re.IGNORECASE)

def fallback_element_values(raw_text: str) -> str:
    """
    Deterministic ELEMENT VALUES fallback:
    - Prefer quoted menu values: “1. Yes” / "2. No"
    - Then enumerated lines: 1. Yes
    - Then lines near 'Report Element Value'
    """
    text = raw_text or ""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    # 1) Quoted menu options anywhere
    found = _QUOTE_OPT_PAT.findall(text)
    if found:
        # preserve order, unique
        seen = set()
        out = []
        for x in found:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return "\n".join(out).strip()

    # 2) Enumerated lines
    opts = []
    for ln in lines:
        if _ENUM_OPT_PAT.match(ln):
            opts.append(ln)
        if len(opts) >= 10:
            break
    if opts:
        return "\n".join(opts).strip()

    # 3) Capture a small block after 'Report Element Value' markers
    for i, ln in enumerate(lines):
        if _REPORT_EV_PAT.search(ln):
            buf = []
            for j in range(i, min(i + 12, len(lines))):
                if _ENUM_OPT_PAT.match(lines[j]):
                    buf.append(lines[j])
            if buf:
                return "\n".join(buf).strip()

    return ""


def apply_fallbacks(event_name: str, raw_text: str, sections: Dict[str, str]) -> Dict[str, str]:
    out = dict(sections)

    if "DESCRIPTION" not in out:
        # if DEFINITION exists, it’s acceptable as DESCRIPTION fallback
        if "DEFINITION" in out and out["DEFINITION"].strip():
            out["DESCRIPTION"] = out["DEFINITION"].strip()
        else:
            desc = fallback_description(event_name, raw_text)
            if desc:
                out["DESCRIPTION"] = desc

    if "ELEMENT VALUES" not in out:
        ev = fallback_element_values(raw_text)
        if ev:
            out["ELEMENT VALUES"] = ev

    return out


# -------------------------
# Main
# -------------------------

def run(year: int) -> int:
    raw_path = REPO_ROOT / "rules" / "ntds" / str(year) / f"ntds_events_raw_{year}_v8.json"
    out_struct = REPO_ROOT / "rules" / "ntds" / str(year) / f"ntds_events_structured_{year}_v1.json"
    out_index = REPO_ROOT / "rules" / "ntds" / str(year) / f"ntds_index_structured_{year}_v1.json"

    if not raw_path.exists():
        raise SystemExit(f"Missing RAW file: {raw_path}")

    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    meta = raw.get("meta", {})

    structured_events: List[Dict[str, Any]] = []

    for ev in raw.get("events", []):
        raw_text = ev.get("raw_text", "") or ""
        name = ev.get("event_name") or ""

        sections = split_sections(raw_text)
        sections = apply_fallbacks(name, raw_text, sections)

        if not sections:
            sections = {"UNPARSED": raw_text}

        pages = ev.get("pages") or []
        pdf_start = int(pages[0]) if pages else 0
        pdf_end = int(pages[-1]) if pages else 0

        structured_events.append(
            {
                "event_id": ev.get("event_id"),
                "canonical_name": name,
                "ntds_year": year,
                "sections": sections,
                "page_receipts": {
                    "pdf_start_page": pdf_start,
                    "pdf_end_page": pdf_end,
                    "doc_start_page": int(ev.get("doc_start_page", 0) or 0),
                    "doc_end_page": int(ev.get("doc_end_page", 0) or 0),
                },
                "warnings": [],
                "provenance": {
                    "raw_text_sha256": sha256(raw_text),
                    "source_pdf": meta.get("source_pdf"),
                    "raw_file": str(raw_path),
                    "raw_event_id": ev.get("event_id"),
                    "converter_version": "1.5.0",
                    "converted_at_utc": now_utc(),
                    "extractor_meta": meta,
                },
            }
        )

    payload = {
        "meta": {
            "system": meta.get("system", "Netrion Systems"),
            "product": meta.get("product", "CerebralOS"),
            "ruleset": "NTDS Hospital Events (STRUCTURED)",
            "year": year,
            "version": "1.5.0",
            "source_raw": str(raw_path),
            "event_count": len(structured_events),
        },
        "events": structured_events,
    }

    out_struct.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    out_index.write_text(
        json.dumps(
            {
                "meta": payload["meta"],
                "events": [
                    {
                        "event_id": e["event_id"],
                        "canonical_name": e["canonical_name"],
                        "sections_present": sorted(list(e["sections"].keys())),
                        "pdf_start_page": e["page_receipts"]["pdf_start_page"],
                        "pdf_end_page": e["page_receipts"]["pdf_end_page"],
                    }
                    for e in structured_events
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"OK ✅ Structured NTDS events written: {out_struct}")
    print(f"OK ✅ Structured index written:      {out_index}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True, choices=[2025, 2026])
    args = ap.parse_args()
    return run(args.year)


if __name__ == "__main__":
    raise SystemExit(main())
