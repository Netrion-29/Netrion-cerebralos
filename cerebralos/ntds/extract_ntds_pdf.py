#!/usr/bin/env python3
"""
CerebralOS — NTDS Hospital Events Extractor (RAW v9)

Fixes:
- Eliminates false-positive start-page matches (e.g., Delirium matching on page 6)
- Requires:
    1) "HOSPITAL EVENTS" in the top block
    2) event title appears as a standalone header line in the top lines (token-normalized)
- Writes explicit pdf_start_page/pdf_end_page + pages list
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Dict, List, Any, Optional

import fitz  # PyMuPDF

REPO_ROOT = Path(__file__).resolve().parents[2]

NTDS_EVENTS_2025 = [
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

NTDS_EVENTS_2026 = [
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


def clean(text: str) -> str:
    text = (text or "").replace("\u00a0", " ").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_pages(pdf_path: Path) -> List[Dict[str, Any]]:
    doc = fitz.open(str(pdf_path))
    pages = []
    for i in range(doc.page_count):
        txt = clean(doc.load_page(i).get_text("text") or "")
        pages.append({"page": i + 1, "text": txt})
    return pages


def first_nonempty_lines(text: str, n: int = 30) -> List[str]:
    out = []
    for ln in (text or "").splitlines():
        ln = ln.strip()
        if ln:
            out.append(ln)
        if len(out) >= n:
            break
    return out


def normalize_tokens(s: str) -> str:
    t = (s or "").upper()
    t = re.sub(r"[^A-Z0-9]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def header_aliases(event_name: str) -> List[str]:
    base = event_name.strip()
    aliases = [base]
    no_paren = re.sub(r"\s*\([^)]*\)\s*", " ", base).strip()
    if no_paren and no_paren not in aliases:
        aliases.append(no_paren)
    return aliases


def is_true_title_page(page_text: str, hdr_aliases: List[str]) -> bool:
    """
    True title page must have:
      - "HOSPITAL EVENTS" in the top block
      - the event title present as a standalone top line (token-normalized match)
    """
    lines = first_nonempty_lines(page_text, n=30)
    if not lines:
        return False

    top_block = "\n".join(lines)
    top_norm = normalize_tokens(top_block)

    # Must be within hospital-events section
    if "HOSPITAL EVENTS" not in top_norm:
        return False

    # Build set of normalized lines for exact match
    norm_lines = {normalize_tokens(ln) for ln in lines}

    for alias in hdr_aliases:
        h = normalize_tokens(alias)
        if not h:
            continue
        # Require header as a standalone line near top
        if h in norm_lines:
            return True

    return False


def run(year: int) -> int:
    pdf_path = REPO_ROOT / "rules" / "ntds" / str(year) / f"Hospital Events {year}.pdf"
    out_raw = REPO_ROOT / "rules" / "ntds" / str(year) / f"ntds_events_raw_{year}_v9.json"
    out_index = REPO_ROOT / "rules" / "ntds" / str(year) / f"ntds_index_{year}_v9.json"

    print(f"\nCerebralOS — NTDS Extract (RAW v9) — {year}")
    print("Reading:", pdf_path)

    if not pdf_path.exists():
        raise SystemExit(f"Missing PDF: {pdf_path}")

    pages = extract_pages(pdf_path)
    print("Pages extracted:", len(pages))
    nonempty = sum(1 for p in pages if (p["text"] or "").strip())
    print("Pages with non-empty text:", nonempty)

    canon = NTDS_EVENTS_2025 if year == 2025 else NTDS_EVENTS_2026
    wanted = {eid: header_aliases(name) for eid, name in canon}

    start_pages: Dict[int, int] = {}

    for p in pages:
        txt = p["text"]
        for eid, aliases in wanted.items():
            if eid in start_pages:
                continue
            if is_true_title_page(txt, aliases):
                start_pages[eid] = p["page"]

    print("Expected events:", len(canon))
    print("Found start pages:", len(start_pages))

    missing = [name for eid, name in canon if eid not in start_pages]
    if missing:
        print("⚠️  Missing start pages for:", len(missing))
        for m in missing:
            print(" -", m)

    # Build ordered list using canonical IDs, but slice by page numbers
    ordered = [(eid, name, start_pages.get(eid, 0)) for eid, name in canon]

    # Sort by start page (non-zero first), tie-break by event_id
    ordered_sorted = sorted([x for x in ordered if x[2] > 0], key=lambda t: (t[2], t[0]))

    # Build start->end ranges based on next start in page order
    ranges: Dict[int, tuple[int, int]] = {}
    for i, (eid, name, sp) in enumerate(ordered_sorted):
        if i + 1 < len(ordered_sorted):
            ep = ordered_sorted[i + 1][2] - 1
        else:
            ep = pages[-1]["page"]
        if ep < sp:
            ep = sp
        ranges[eid] = (sp, ep)

    events = []
    index = []
    warned_count = 0

    for eid, name, _ in ordered:
        warnings: List[str] = []
        sp, ep = ranges.get(eid, (0, 0))
        pages_used: List[int] = []
        raw_text = ""

        if sp == 0:
            warnings.append("START_PAGE_NOT_FOUND")
        else:
            pages_used = list(range(sp, ep + 1))
            raw_text = clean("\n\n".join(p["text"] for p in pages if p["page"] in pages_used))
            if not raw_text.strip():
                warnings.append("EMPTY_RAW_TEXT")

        if warnings:
            warned_count += 1

        events.append(
            {
                "event_id": eid,
                "event_name": name,
                "pdf_start_page": sp,
                "pdf_end_page": ep,
                "pages": pages_used,
                "raw_text": raw_text,
                "extraction_warnings": warnings,
            }
        )
        index.append(
            {
                "event_id": eid,
                "event_name": name,
                "pdf_start_page": sp,
                "pdf_end_page": ep,
                "pages_count": len(pages_used),
                "warnings_count": len(warnings),
            }
        )

    payload = {
        "meta": {
            "system": "Netrion Systems",
            "product": "CerebralOS",
            "ruleset": "NTDS Hospital Events (RAW)",
            "year": year,
            "version": "9.0.0",
            "source_pdf": str(pdf_path),
            "event_count": len(events),
        },
        "events": events,
    }

    out_raw.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    out_index.write_text(json.dumps({"meta": payload["meta"], "events": index}, indent=2), encoding="utf-8")

    print("OK ✅ Wrote RAW:  ", out_raw)
    print("OK ✅ Wrote INDEX:", out_index)
    print("Events extracted:", len(events))
    if warned_count:
        print(f"⚠️  Events with warnings: {warned_count} (review; extraction still succeeded)")

    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True, choices=[2025, 2026])
    args = ap.parse_args()
    return run(args.year)


if __name__ == "__main__":
    raise SystemExit(main())
