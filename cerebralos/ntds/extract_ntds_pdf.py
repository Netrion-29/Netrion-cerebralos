#!/usr/bin/env python3
"""
CerebralOS — NTDS Hospital Events Extractor (RAW v8)

Fixes vs v7:
- If the title page extracts little/no text, include the next page in the slice
  (bounded, deterministic "title_page+1" rule).
- Emits explicit warnings:
  - START_PAGE_NOT_FOUND
  - EMPTY_RAW_TEXT
  - USED_TITLE_PLUS_ONE_PAGE
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Dict, List, Any

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
    text = (text or "").replace("\u00a0", " ")
    text = text.replace("\r", "\n")
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


def first_nonempty_lines(text: str, n: int = 25) -> List[str]:
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


def page_has_header(page_text: str, headers: List[str]) -> bool:
    lines = first_nonempty_lines(page_text, n=25)
    if not lines:
        return False
    top = "\n".join(lines)
    top_norm = normalize_tokens(top)

    for hdr in headers:
        hdr_norm = normalize_tokens(hdr)
        if not hdr_norm:
            continue
        if hdr_norm in top_norm:
            return True

        toks = hdr_norm.split()
        if len(toks) >= 3:
            if all(tok in top_norm for tok in toks[:3]) and toks[-1] in top_norm:
                return True

    return False


def run(year: int) -> int:
    pdf_path = REPO_ROOT / "rules" / "ntds" / str(year) / f"Hospital Events {year}.pdf"
    out_raw = REPO_ROOT / "rules" / "ntds" / str(year) / f"ntds_events_raw_{year}_v8.json"
    out_index = REPO_ROOT / "rules" / "ntds" / str(year) / f"ntds_index_{year}_v8.json"

    print(f"\nCerebralOS — NTDS Extract (RAW v8) — {year}")
    print("Reading:", pdf_path)

    if not pdf_path.exists():
        raise SystemExit(f"Missing PDF: {pdf_path}")

    pages = extract_pages(pdf_path)
    print("Pages extracted:", len(pages))
    nonempty = [p for p in pages if p["text"]]
    print("Pages with non-empty text:", len(nonempty))

    canon = NTDS_EVENTS_2025 if year == 2025 else NTDS_EVENTS_2026
    wanted = {eid: header_aliases(name) for eid, name in canon}

    start_pages: Dict[int, int] = {}
    for p in pages:
        txt = p["text"]
        for eid, hdrs in wanted.items():
            if eid in start_pages:
                continue
            if page_has_header(txt, hdrs):
                start_pages[eid] = p["page"]

    print("Expected events:", len(canon))
    print("Found start pages:", len(start_pages))

    missing = [name for eid, name in canon if eid not in start_pages]
    if missing:
        print("⚠️  Missing start pages for:", len(missing))
        for m in missing:
            print(" -", m)

    ordered = [(eid, name, start_pages.get(eid)) for eid, name in canon]

    events = []
    index = []

    for i, (eid, name, start) in enumerate(ordered):
        warnings: List[str] = []
        pages_used: List[int] = []
        raw_text = ""

        if start is None:
            warnings.append("START_PAGE_NOT_FOUND")
        else:
            end = None
            for _, _, nxt in ordered[i + 1 :]:
                if nxt is not None:
                    end = nxt - 1
                    break
            if end is None:
                end = pages[-1]["page"]

            # Default slice
            pages_used = list(range(start, end + 1))
            raw_text = clean("\n\n".join(p["text"] for p in pages if p["page"] in pages_used))

            # If empty, deterministically include start+1 (title bar page often extracts poorly)
            if not raw_text.strip():
                if start + 1 <= pages[-1]["page"]:
                    pages_used = list(range(start, min(end, start + 1) + 1))
                    raw_text = clean("\n\n".join(p["text"] for p in pages if p["page"] in pages_used))
                    warnings.append("USED_TITLE_PLUS_ONE_PAGE")

            if not raw_text.strip():
                warnings.append("EMPTY_RAW_TEXT")

        events.append(
            {
                "event_id": eid,
                "event_name": name,
                "pages": pages_used,
                "raw_text": raw_text,
                "extraction_warnings": warnings,
            }
        )

        index.append(
            {
                "event_id": eid,
                "event_name": name,
                "pages": pages_used,
                "warnings_count": len(warnings),
            }
        )

    payload = {
        "meta": {
            "system": "Netrion Systems",
            "product": "CerebralOS",
            "ruleset": "NTDS Hospital Events (RAW)",
            "year": year,
            "version": "8.0.0",
            "source_pdf": str(pdf_path),
            "event_count": len(events),
        },
        "events": events,
    }

    out_raw.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    out_index.write_text(json.dumps({"meta": payload["meta"], "events": index}, indent=2), encoding="utf-8")

    warned = [e for e in index if e["warnings_count"] > 0]
    print("OK ✅ Wrote RAW:  ", out_raw)
    print("OK ✅ Wrote INDEX:", out_index)
    print("Events extracted:", len(events))
    if warned:
        print(f"⚠️  Events with warnings: {len(warned)} (review; extraction still succeeded)")

    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True, choices=[2025, 2026])
    args = ap.parse_args()
    return run(args.year)


if __name__ == "__main__":
    raise SystemExit(main())
