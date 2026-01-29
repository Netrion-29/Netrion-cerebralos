#!/usr/bin/env python3
"""
CerebralOS — NTDS RAW → STRUCTURED Converter (v1)

Deterministic parser:
- Reads latest RAW extracted NTDS file:
    rules/ntds/<YEAR>/ntds_events_raw_<YEAR>_v*.json   (chooses highest vN)
- Produces:
    rules/ntds/<YEAR>/ntds_events_structured_<YEAR>_v1.json
    rules/ntds/<YEAR>/ntds_index_structured_<YEAR>_v1.json

Strict goals:
- No AI inference.
- Fail-closed: missing/odd sections are recorded as warnings, not guessed.
- Year-aware canonical event list (2025 vs 2026 OR change).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]


# -------------------------
# Canonical event inventory
# -------------------------

CANON_2025: List[Tuple[int, str]] = [
    (1, "Acute Kidney Injury (AKI)"),
    (2, "Acute Respiratory Distress Syndrome (ARDS)"),
    (3, "Alcohol Withdrawal Syndrome"),
    (4, "Cardiac Arrest With CPR"),
    (5, "Catheter-Associated Urinary Tract Infection (CAUTI)"),
    (6, "Central Line-Associated Bloodstream Infection (CLABSI)"),
    (7, "Deep Surgical Site Infection (Deep SSI)"),
    (8, "Deep Vein Thrombosis (DVT)"),
    (9, "Delirium"),
    (10, "Myocardial Infarction (MI)"),
    (11, "Organ/Space Surgical Site Infection"),
    (12, "Osteomyelitis"),
    (13, "Pressure Ulcer"),
    (14, "Pulmonary Embolism (PE)"),
    (15, "Severe Sepsis"),
    (16, "Stroke/CVA"),
    (17, "Superficial Incisional Surgical Site Infection"),
    (18, "Unplanned Admission to the ICU"),
    (19, "Unplanned Intubation"),
    (20, "Unplanned Visit to the Operating Room"),
    (21, "Ventilator-Associated Pneumonia (VAP)"),
]

CANON_2026: List[Tuple[int, str]] = [
    (1, "Acute Kidney Injury (AKI)"),
    (2, "Acute Respiratory Distress Syndrome (ARDS)"),
    (3, "Alcohol Withdrawal Syndrome"),
    (4, "Cardiac Arrest With CPR"),
    (5, "Catheter-Associated Urinary Tract Infection (CAUTI)"),
    (6, "Central Line-Associated Bloodstream Infection (CLABSI)"),
    (7, "Deep Surgical Site Infection (Deep SSI)"),
    (8, "Deep Vein Thrombosis (DVT)"),
    (9, "Delirium"),
    (10, "Myocardial Infarction (MI)"),
    (11, "Organ/Space Surgical Site Infection"),
    (12, "Osteomyelitis"),
    (13, "Pressure Ulcer"),
    (14, "Pulmonary Embolism (PE)"),
    (15, "Severe Sepsis"),
    (16, "Stroke/CVA"),
    (17, "Superficial Incisional Surgical Site Infection"),
    (18, "Unplanned Admission to the ICU"),
    (19, "Unplanned Intubation"),
    (20, "Unplanned Return to the Operating Room"),
    (21, "Ventilator-Associated Pneumonia (VAP)"),
]


# -------------------------
# Section parsing
# -------------------------

SECTION_ORDER: List[str] = [
    "DESCRIPTION",
    "ADDITIONAL INFORMATION",
    "ELEMENT INTENT",
    "ELEMENT VALUES",
    "DATA SOURCE HIERARCHY GUIDE",
    "ASSOCIATED EDIT CHECKS",
    "EXCLUDE",  # some PDFs place EXCLUDE at end; include it last to be safe
]

SECTION_ALIASES: Dict[str, List[str]] = {
    "DESCRIPTION": ["DESCRIPTION"],
    "ADDITIONAL INFORMATION": ["ADDITIONAL INFORMATION", "ADDITIONAL INFO"],
    "ELEMENT INTENT": ["ELEMENT INTENT"],
    "ELEMENT VALUES": ["ELEMENT VALUES"],
    "DATA SOURCE HIERARCHY GUIDE": ["DATA SOURCE HIERARCHY GUIDE", "DATA SOURCE HIERARCHY"],
    "ASSOCIATED EDIT CHECKS": ["ASSOCIATED EDIT CHECKS", "EDIT CHECKS"],
    "EXCLUDE": ["EXCLUDE", "EXCLUSION", "EXCLUSIONS"],
}


def normalize_ws(s: str) -> str:
    s = (s or "").replace("\u00a0", " ")
    s = s.replace("\r", "\n")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def sha256_text(s: str) -> str:
    h = hashlib.sha256()
    h.update((s or "").encode("utf-8", errors="replace"))
    return h.hexdigest()


def build_section_regex(section_name: str) -> re.Pattern:
    """
    Build a robust heading matcher that catches exact NTDS headings.
    Headings are usually standalone lines.
    """
    alts = SECTION_ALIASES.get(section_name, [section_name])
    # Match start-of-line heading, possibly surrounded by spaces, with optional trailing colon.
    alt_pat = "|".join(re.escape(a) for a in alts)
    return re.compile(rf"(?im)^(?:\s*)({alt_pat})(?:\s*:?\s*)$", re.MULTILINE)


def find_heading_positions(raw: str) -> List[Tuple[int, str]]:
    """
    Returns list of (start_index, SECTION_NAME) for headings found in raw text.
    We search for canonical headings using aliases.
    """
    hits: List[Tuple[int, str]] = []
    for sec in SECTION_ORDER:
        pat = build_section_regex(sec)
        for m in pat.finditer(raw):
            hits.append((m.start(), sec))
    hits.sort(key=lambda x: x[0])

    # Deduplicate adjacent duplicates (same section repeated)
    dedup: List[Tuple[int, str]] = []
    last_sec = None
    for pos, sec in hits:
        if sec == last_sec:
            continue
        dedup.append((pos, sec))
        last_sec = sec

    return dedup


def slice_sections(raw_text: str) -> Tuple[Dict[str, str], List[str]]:
    """
    Split raw_text into section bodies based on headings.
    Returns (sections_dict, warnings)
    """
    raw = normalize_ws(raw_text)
    warnings: List[str] = []
    sections: Dict[str, str] = {}

    if not raw:
        warnings.append("EMPTY_RAW_TEXT")
        return sections, warnings

    heads = find_heading_positions(raw)
    if not heads:
        # Can't section-split; keep whole text in 'unparsed'
        sections["UNPARSED"] = raw
        warnings.append("NO_SECTION_HEADINGS_FOUND")
        return sections, warnings

    # Build ranges
    for i, (pos, sec) in enumerate(heads):
        start = pos
        end = heads[i + 1][0] if i + 1 < len(heads) else len(raw)
        chunk = raw[start:end].strip()

        # Remove the heading line itself from chunk:
        # take first line, drop it if it matches the heading
        lines = chunk.splitlines()
        if lines:
            first = lines[0].strip().upper().rstrip(":")
            # if first line looks like this section (or alias), drop it
            alias_upper = [a.upper() for a in SECTION_ALIASES.get(sec, [sec])]
            if first in alias_upper:
                chunk = "\n".join(lines[1:]).strip()

        if chunk:
            # Keep first occurrence; if repeats, append deterministically
            if sec in sections:
                sections[sec] = (sections[sec] + "\n\n" + chunk).strip()
                warnings.append(f"DUPLICATE_SECTION_MERGED:{sec}")
            else:
                sections[sec] = chunk
        else:
            warnings.append(f"EMPTY_SECTION_BODY:{sec}")

    # Minimal sanity checks
    if "DESCRIPTION" not in sections:
        warnings.append("MISSING_DESCRIPTION_SECTION")
    if "ELEMENT VALUES" not in sections:
        warnings.append("MISSING_ELEMENT_VALUES_SECTION")

    return sections, warnings


# -------------------------
# RAW loading helpers
# -------------------------

RAW_FILE_RE = re.compile(r"^ntds_events_raw_(?P<year>\d{4})_v(?P<v>\d+)\.json$")


def find_latest_raw(year: int) -> Path:
    folder = REPO_ROOT / "rules" / "ntds" / str(year)
    if not folder.exists():
        raise SystemExit(f"Missing folder: {folder}")

    candidates: List[Tuple[int, Path]] = []
    for p in folder.iterdir():
        m = RAW_FILE_RE.match(p.name)
        if m and int(m.group("year")) == year:
            candidates.append((int(m.group("v")), p))

    if not candidates:
        raise SystemExit(f"No RAW files found for year {year} in {folder} (expected ntds_events_raw_{year}_v*.json)")

    candidates.sort(key=lambda x: x[0])
    return candidates[-1][1]


def load_raw_events(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def stable_lookup_by_name(raw_events: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Build lookup by exact event_name (from extractor output).
    """
    out: Dict[str, Dict[str, Any]] = {}
    for e in raw_events:
        name = (e.get("event_name") or "").strip()
        if name and name not in out:
            out[name] = e
    return out


def now_iso() -> str:
    # Keep ISO seconds only for determinism in diffs
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


# -------------------------
# Conversion
# -------------------------

def convert_year(year: int) -> int:
    raw_path = find_latest_raw(year)
    raw_obj = load_raw_events(raw_path)

    raw_events: List[Dict[str, Any]] = raw_obj.get("events", [])
    raw_meta: Dict[str, Any] = raw_obj.get("meta", {})

    canon = CANON_2025 if year == 2025 else CANON_2026

    by_name = stable_lookup_by_name(raw_events)

    structured_events: List[Dict[str, Any]] = []
    index: List[Dict[str, Any]] = []

    for event_id, canon_name in canon:
        src = by_name.get(canon_name)

        warnings: List[str] = []
        if not src:
            warnings.append("RAW_EVENT_NOT_FOUND_BY_NAME")
            raw_text = ""
            pages: Dict[str, Any] = {}
            raw_event_id = None
            raw_warnings = []
        else:
            raw_text = src.get("raw_text") or ""
            raw_event_id = src.get("event_id")
            raw_warnings = src.get("extraction_warnings") or []
            # carry forward any page receipts the extractor provided
            pages = {
                "pdf_start_page": src.get("pdf_start_page", src.get("start_page", 0)),
                "pdf_end_page": src.get("pdf_end_page", src.get("end_page", 0)),
                "doc_start_page": src.get("doc_start_page", 0),
                "doc_end_page": src.get("doc_end_page", 0),
            }

        sections, sec_warnings = slice_sections(raw_text)
        warnings.extend([f"RAW_WARN:{w}" for w in (raw_warnings or [])])
        warnings.extend([f"PARSE_WARN:{w}" for w in sec_warnings])

        # Year-specific notes
        year_notes: List[str] = []
        if year == 2026 and event_id == 7:
            year_notes.append("NOTE_2026_DEEP_SSI_ADDITIONAL_INFO_CHANGED")
        if year == 2026 and event_id == 20:
            year_notes.append("NOTE_2026_EVENT20_RENAMED_TO_UNPLANNED_RETURN_TO_OR")
        if year == 2025 and event_id == 20:
            year_notes.append("NOTE_2025_EVENT20_IS_UNPLANNED_VISIT_TO_OR")

        raw_hash = sha256_text(raw_text)

        structured = {
            "event_id": event_id,
            "canonical_name": canon_name,
            "ntds_year": year,
            "sections": sections,
            "year_notes": year_notes,
            "provenance": {
                "source_pdf": raw_meta.get("source_pdf") or raw_meta.get("source_file"),
                "raw_file": str(raw_path),
                "raw_event_id": raw_event_id,
                "raw_text_sha256": raw_hash,
                "extractor_meta": raw_meta,
                "converter_version": "1.0.0",
                "converted_at_utc": now_iso(),
            },
            "page_receipts": pages,
            "warnings": warnings,
        }

        structured_events.append(structured)

        index.append(
            {
                "event_id": event_id,
                "canonical_name": canon_name,
                "warnings_count": len(warnings),
                "has_description": "DESCRIPTION" in sections,
                "has_element_values": "ELEMENT VALUES" in sections,
                "pdf_pages": {
                    "start": pages.get("pdf_start_page", 0),
                    "end": pages.get("pdf_end_page", 0),
                },
            }
        )

    out_folder = REPO_ROOT / "rules" / "ntds" / str(year)
    out_struct = out_folder / f"ntds_events_structured_{year}_v1.json"
    out_index = out_folder / f"ntds_index_structured_{year}_v1.json"

    payload = {
        "meta": {
            "system": "Netrion Systems",
            "product": "CerebralOS",
            "ruleset": "NTDS Hospital Events (STRUCTURED)",
            "year": year,
            "version": "1.0.0",
            "source_raw": str(raw_path),
            "event_count": len(structured_events),
        },
        "events": structured_events,
    }

    out_struct.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    out_index.write_text(json.dumps({"meta": payload["meta"], "events": index}, indent=2), encoding="utf-8")

    print(f"\nCerebralOS — NTDS Convert RAW → STRUCTURED — {year}")
    print("Reading RAW:", raw_path)
    print("Wrote STRUCTURED:", out_struct)
    print("Wrote INDEX:", out_index)
    print("Structured events:", len(structured_events))

    warned = [x for x in index if x["warnings_count"] > 0]
    if warned:
        print(f"⚠️  Events with warnings: {len(warned)} (expected early; validator will enforce hard gates)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True, choices=[2025, 2026])
    args = ap.parse_args()
    return convert_year(args.year)


if __name__ == "__main__":
    raise SystemExit(main())
