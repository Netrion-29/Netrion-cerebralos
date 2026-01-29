#!/usr/bin/env python3
"""
CerebralOS — NTDS Hospital Events Extractor (RAW v6)

Key behavior:
- 2025: TOC-driven extraction (uses document page numbers like 142, 144, 151...)
        then maps to PDF pages by detecting footer "PAGE <n>" on each PDF page.
        This handles headings that are not text-extractable on event pages.
- 2026: title/token-match extraction (works for your 2026 PDF).

Writes:
  rules/ntds/<YEAR>/ntds_events_raw_<YEAR>_v6.json
  rules/ntds/<YEAR>/ntds_index_<YEAR>_v6.json
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pypdf import PdfReader

REPO_ROOT = Path(__file__).resolve().parents[2]


# -------------------------
# Canonical events (friendly names)
# -------------------------

CANON_2025: List[str] = [
    "Acute Kidney Injury (AKI)",
    "Acute Respiratory Distress Syndrome (ARDS)",
    "Alcohol Withdrawal Syndrome",
    "Cardiac Arrest With CPR",
    "Catheter-Associated Urinary Tract Infection (CAUTI)",
    "Central Line-Associated Bloodstream Infection (CLABSI)",
    "Deep Surgical Site Infection (Deep SSI)",
    "Deep Vein Thrombosis (DVT)",
    "Delirium",
    "Myocardial Infarction (MI)",
    "Organ/Space Surgical Site Infection",
    "Osteomyelitis",
    "Pressure Ulcer",
    "Pulmonary Embolism (PE)",
    "Severe Sepsis",
    "Stroke/CVA",
    "Superficial Incisional Surgical Site Infection",
    "Unplanned Admission to the ICU",
    "Unplanned Intubation",
    "Unplanned Visit to the Operating Room",
    "Ventilator-Associated Pneumonia (VAP)",
]

CANON_2026: List[str] = [
    "Acute Kidney Injury (AKI)",
    "Acute Respiratory Distress Syndrome (ARDS)",
    "Alcohol Withdrawal Syndrome",
    "Cardiac Arrest With CPR",
    "Catheter-Associated Urinary Tract Infection (CAUTI)",
    "Central Line-Associated Bloodstream Infection (CLABSI)",
    "Deep Surgical Site Infection (Deep SSI)",
    "Deep Vein Thrombosis (DVT)",
    "Delirium",
    "Myocardial Infarction (MI)",
    "Organ/Space Surgical Site Infection",
    "Osteomyelitis",
    "Pressure Ulcer",
    "Pulmonary Embolism (PE)",
    "Severe Sepsis",
    "Stroke/CVA",
    "Superficial Incisional Surgical Site Infection",
    "Unplanned Admission to the ICU",
    "Unplanned Intubation",
    "Unplanned Return to the Operating Room",  # NEW in 2026
    "Ventilator-Associated Pneumonia (VAP)",
]


# -------------------------
# Extraction helpers
# -------------------------

def clean(text: str) -> str:
    text = (text or "").replace("\u00a0", " ")
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_pages(pdf_path: Path) -> List[Dict[str, Any]]:
    # Prefer PyMuPDF
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(str(pdf_path))
        pages: List[Dict[str, Any]] = []
        print("✅ Using PyMuPDF (fitz) for extraction")
        for i in range(doc.page_count):
            page = doc.load_page(i)
            raw = page.get_text("text") or ""
            pages.append({"pdf_page": i + 1, "text": clean(raw)})
        return pages
    except Exception as e:
        print(f"⚠️  PyMuPDF extraction failed ({e}); falling back to pypdf...")

    # Fallback: pypdf
    reader = PdfReader(str(pdf_path))
    pages = []
    for i, page in enumerate(reader.pages):
        raw = page.extract_text() or ""
        pages.append({"pdf_page": i + 1, "text": clean(raw)})
    return pages


def build_concat(pages: List[Dict[str, Any]]) -> Tuple[str, List[Tuple[int, int, int]]]:
    """
    Concatenate PDF pages with explicit markers. spans: (pdf_page, start_char, end_char)
    """
    parts: List[str] = []
    spans: List[Tuple[int, int, int]] = []
    cursor = 0
    for p in pages:
        pdf_page = int(p["pdf_page"])
        txt = p["text"] or ""
        marker = f"\n\n=== PDF_PAGE {pdf_page} ===\n\n"
        chunk = marker + txt
        start = cursor
        parts.append(chunk)
        cursor += len(chunk)
        end = cursor
        spans.append((pdf_page, start, end))
    return "".join(parts), spans


def char_to_pdf_page(spans: List[Tuple[int, int, int]], char_idx: int) -> int:
    for pdf_page, start, end in spans:
        if start <= char_idx < end:
            return pdf_page
    return spans[-1][0] if spans else 0


def stable_event_id(title: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", title.upper()).strip("_")


# -------------------------
# 2025 TOC-driven extraction
# -------------------------

TOC_LINE_RE = re.compile(r"^(?P<title>[A-Z0-9/()\- ,]+?)\s+\.{3,}\s+(?P<pageno>\d{1,4})\s*$")
DOC_PAGE_FOOTER_RE = re.compile(r"\bPAGE\s+(?P<n>\d{1,4})\b", re.IGNORECASE)


def canon_to_toc_title(canon: str) -> str:
    """
    Convert friendly title to expected TOC uppercase title.
    Examples:
      "Deep Surgical Site Infection (Deep SSI)" -> "DEEP SURGICAL SITE INFECTION"
      "Pressure Ulcer" -> "PRESSURE ULCER"
      Keeps abbreviations in parens for most items.
    """
    # Special case: Deep SSI in TOC is without "(Deep SSI)"
    if canon == "Deep Surgical Site Infection (Deep SSI)":
        return "DEEP SURGICAL SITE INFECTION"
    return canon.upper()


def parse_toc_doc_pages(pages: List[Dict[str, Any]]) -> Dict[str, int]:
    """
    Scan early pages for TOC entries under HOSPITAL EVENTS and parse doc page numbers.
    Returns map: TOC_TITLE -> doc_page_number
    """
    toc_map: Dict[str, int] = {}

    # Look across first 20 PDF pages (safe, deterministic)
    search_text = "\n".join((p["text"] or "") for p in pages[:20])
    lines = [ln.strip() for ln in search_text.splitlines() if ln.strip()]

    in_hospital_events = False
    for ln in lines:
        if ln.strip().upper() == "HOSPITAL EVENTS":
            in_hospital_events = True
            continue
        if in_hospital_events:
            m = TOC_LINE_RE.match(ln)
            if m:
                title = m.group("title").strip().upper()
                doc_p = int(m.group("pageno"))
                toc_map[title] = doc_p
            # stop if we leave section (heuristic)
            if in_hospital_events and ln.strip().upper().startswith("HOSPITAL DISCHARGE"):
                break

    return toc_map


def map_doc_page_to_pdf_page(pages: List[Dict[str, Any]]) -> Dict[int, int]:
    """
    Build map from doc page number (footer 'PAGE N') -> pdf_page.
    """
    m: Dict[int, int] = {}
    for p in pages:
        pdf_page = int(p["pdf_page"])
        txt = p["text"] or ""
        # use last occurrence on page if multiple
        hits = list(DOC_PAGE_FOOTER_RE.finditer(txt))
        if hits:
            doc_n = int(hits[-1].group("n"))
            # first mapping wins (deterministic)
            if doc_n not in m:
                m[doc_n] = pdf_page
    return m


def extract_2025_by_toc(
    pages: List[Dict[str, Any]],
    full_text: str,
    spans: List[Tuple[int, int, int]],
) -> List[Dict[str, Any]]:
    toc = parse_toc_doc_pages(pages)
    doc_to_pdf = map_doc_page_to_pdf_page(pages)

    # Build ordered start doc pages for canonical events
    starts: List[Tuple[int, str]] = []
    missing_toc: List[str] = []

    for canon in CANON_2025:
        toc_title = canon_to_toc_title(canon)
        doc_start = toc.get(toc_title)
        if doc_start is None:
            missing_toc.append(canon)
            continue
        starts.append((doc_start, canon))

    starts.sort(key=lambda x: x[0])

    events: List[Dict[str, Any]] = []
    for i, (doc_start, canon) in enumerate(starts):
        doc_end = starts[i + 1][0] - 1 if i + 1 < len(starts) else doc_start + 10  # safe cap

        pdf_start = doc_to_pdf.get(doc_start, 0)
        pdf_end = doc_to_pdf.get(doc_end, 0)

        warnings: List[str] = []
        if pdf_start == 0:
            warnings.append("DOC_PAGE_TO_PDF_PAGE_MAP_MISSING_START")
        if pdf_end == 0:
            # If end not found, use start only; we still capture something.
            pdf_end = pdf_start
            warnings.append("DOC_PAGE_TO_PDF_PAGE_MAP_MISSING_END")

        # Slice by PDF page markers in concatenated full_text
        # We locate the marker strings and cut between them
        start_marker = f"=== PDF_PAGE {pdf_start} ==="
        end_marker = f"=== PDF_PAGE {pdf_end + 1} ==="  # end is exclusive

        start_off = full_text.find(start_marker)
        if start_off < 0:
            warnings.append("PDF_START_MARKER_NOT_FOUND")
            start_off = 0

        end_off = full_text.find(end_marker)
        if end_off < 0:
            end_off = len(full_text)

        raw = full_text[start_off:end_off].strip()

        # anchor sanity
        anchors = ["DESCRIPTION", "EXCLUDE", "ELEMENT VALUES", "DATA SOURCE HIERARCHY GUIDE", "ASSOCIATED EDIT CHECKS"]
        anchor_hits = sum(1 for a in anchors if a.lower() in raw.lower())
        if anchor_hits < 2:
            warnings.append(f"LOW_ANCHOR_HITS({anchor_hits})")

        events.append(
            {
                "event_id": stable_event_id(canon),
                "event_name": canon,
                "matched_title": canon_to_toc_title(canon),
                "doc_start_page": doc_start,
                "doc_end_page": doc_end,
                "pdf_start_page": pdf_start,
                "pdf_end_page": pdf_end,
                "raw_text": raw,
                "extraction_warnings": warnings,
            }
        )

    # Any canon missing from TOC parse
    if missing_toc:
        for canon in missing_toc:
            events.append(
                {
                    "event_id": stable_event_id(canon),
                    "event_name": canon,
                    "matched_title": None,
                    "doc_start_page": 0,
                    "doc_end_page": 0,
                    "pdf_start_page": 0,
                    "pdf_end_page": 0,
                    "raw_text": "",
                    "extraction_warnings": ["TITLE_NOT_FOUND_IN_TOC"],
                }
            )

    return events


# -------------------------
# 2026 title/token extraction (works for your 2026)
# -------------------------

def _token_pattern(variant: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9]+", variant)
    if not tokens:
        return ""
    return r"(?i)\b" + r"[\W_]+".join(map(re.escape, tokens)) + r"\b"


def find_first_offset(full_text: str, variants: List[str]) -> Optional[Tuple[int, str]]:
    best: Optional[Tuple[int, str]] = None
    for v in variants:
        pat_str = _token_pattern(v)
        if not pat_str:
            continue
        m = re.search(pat_str, full_text)
        if not m:
            continue
        cand = (m.start(), v)
        if best is None or cand[0] < best[0]:
            best = cand
    return best


def extract_2026_by_title(
    full_text: str,
    spans: List[Tuple[int, int, int]],
) -> List[Dict[str, Any]]:
    # Minimal aliases; 2026 works for you
    alias: Dict[str, List[str]] = {}

    # Find starts
    starts: List[Tuple[int, str, str]] = []
    for canon in CANON_2026:
        variants = [canon] + alias.get(canon, [])
        hit = find_first_offset(full_text, variants)
        if hit:
            starts.append((hit[0], canon, hit[1]))

    starts.sort(key=lambda x: x[0])
    start_by_title: Dict[str, Tuple[int, str]] = {t: (off, mv) for off, t, mv in starts}

    out: List[Dict[str, Any]] = []
    for canon in CANON_2026:
        if canon not in start_by_title:
            out.append(
                {
                    "event_id": stable_event_id(canon),
                    "event_name": canon,
                    "matched_title": None,
                    "pdf_start_page": 0,
                    "pdf_end_page": 0,
                    "raw_text": "",
                    "extraction_warnings": ["TITLE_NOT_FOUND_IN_PDF"],
                }
            )
            continue

        start_off, matched = start_by_title[canon]

        end_off = len(full_text)
        for j in range(len(starts)):
            if starts[j][1] == canon and starts[j][0] == start_off:
                if j + 1 < len(starts):
                    end_off = starts[j + 1][0]
                break

        raw = full_text[start_off:end_off].strip()
        pdf_start = char_to_pdf_page(spans, start_off)
        pdf_end = char_to_pdf_page(spans, max(start_off, end_off - 1))

        warnings: List[str] = []
        anchors = ["DESCRIPTION", "EXCLUDE", "ELEMENT VALUES", "DATA SOURCE HIERARCHY GUIDE", "ASSOCIATED EDIT CHECKS"]
        anchor_hits = sum(1 for a in anchors if a.lower() in raw.lower())
        if anchor_hits < 2:
            warnings.append(f"LOW_ANCHOR_HITS({anchor_hits})")

        out.append(
            {
                "event_id": stable_event_id(canon),
                "event_name": canon,
                "matched_title": matched,
                "pdf_start_page": pdf_start,
                "pdf_end_page": pdf_end,
                "raw_text": raw,
                "extraction_warnings": warnings,
            }
        )

    return out


# -------------------------
# Runner
# -------------------------

def run(year: int) -> int:
    pdf_path = REPO_ROOT / "rules" / "ntds" / str(year) / f"Hospital Events {year}.pdf"
    out_raw = REPO_ROOT / "rules" / "ntds" / str(year) / f"ntds_events_raw_{year}_v6.json"
    out_index = REPO_ROOT / "rules" / "ntds" / str(year) / f"ntds_index_{year}_v6.json"

    print(f"\nCerebralOS — NTDS Extract (RAW v6) — {year}")
    print("Reading:", pdf_path)

    if not pdf_path.exists():
        raise SystemExit(f"Missing PDF: {pdf_path}")

    pages = extract_pages(pdf_path)
    print("PDF pages extracted:", len(pages))
    nonempty = sum(1 for p in pages if (p.get("text") or "").strip())
    print("PDF pages with non-empty text:", nonempty)

    full_text, spans = build_concat(pages)

    if year == 2025:
        events = extract_2025_by_toc(pages, full_text, spans)
        expected = len(CANON_2025)
    else:
        events = extract_2026_by_title(full_text, spans)
        expected = len(CANON_2026)

    missing = [e["event_name"] for e in events if "TITLE_NOT_FOUND_IN_PDF" in (e.get("extraction_warnings") or []) or "TITLE_NOT_FOUND_IN_TOC" in (e.get("extraction_warnings") or [])]
    warned = sum(1 for e in events if (e.get("extraction_warnings") or []))

    flags: List[str] = []
    if year == 2026:
        flags.extend(
            [
                "CHANGELOG_2026_UNPLANNED_VISIT_OR_RETIRED",
                "CHANGELOG_2026_UNPLANNED_RETURN_OR_NEW",
                "CHANGELOG_2026_DEEP_SSI_ADDITIONAL_INFO_CHANGED",
            ]
        )

    payload = {
        "meta": {
            "system": "Netrion Systems",
            "product": "CerebralOS",
            "ruleset": "NTDS Hospital Events (RAW v6)",
            "year": year,
            "version": "6.0.0",
            "source_pdf": str(pdf_path),
            "expected_event_count": expected,
            "extracted_event_count": len(events),
            "missing_titles": len(missing),
            "flags": flags,
        },
        "events": events,
    }

    idx = []
    for e in events:
        idx.append(
            {
                "event_id": e["event_id"],
                "event_name": e["event_name"],
                "matched_title": e.get("matched_title"),
                "pdf_start_page": e.get("pdf_start_page", 0),
                "pdf_end_page": e.get("pdf_end_page", 0),
                "doc_start_page": e.get("doc_start_page", 0),
                "doc_end_page": e.get("doc_end_page", 0),
                "warnings_count": len(e.get("extraction_warnings") or []),
            }
        )

    out_raw.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    out_index.write_text(json.dumps({"meta": payload["meta"], "events": idx}, indent=2), encoding="utf-8")

    print("OK ✅ Wrote RAW:  ", out_raw)
    print("OK ✅ Wrote INDEX:", out_index)
    print("Expected events:", expected)
    print("Extracted events:", len(events))
    print("Missing titles:", len(missing))
    print("Events with warnings:", warned)

    if missing:
        print("Missing titles list:")
        for t in missing:
            print(" -", t)
        raise SystemExit("FAIL ❌ Missing one or more events. For 2025 this indicates TOC or footer mapping not found.")

    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True, choices=[2025, 2026])
    args = ap.parse_args()
    return run(args.year)


if __name__ == "__main__":
    raise SystemExit(main())

