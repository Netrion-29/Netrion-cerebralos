#!/usr/bin/env python3
"""
audit_new_patients.py — Heuristic new-patient audit matrix generator.

Scans one or more data_raw/*.txt files and prints a markdown table with
rough richness estimates per clinical domain.  Output is labelled as
**estimated / heuristic only** — verified ratings require running the
full pipeline (``./run_patient.sh``) and the QA reporter.

Usage
-----
  # Scan specific files
  python3 scripts/audit_new_patients.py data_raw/Michael_Dougan.txt \\
      "data_raw/Roscella Weatherly.txt"

  # Scan all txt files in a directory (optional --limit)
  python3 scripts/audit_new_patients.py --dir data_raw --limit 5

  # Check whether pipeline outputs already exist
  python3 scripts/audit_new_patients.py --check-outputs data_raw/Michael_Dougan.txt

  # TSV output instead of markdown
  python3 scripts/audit_new_patients.py --format tsv data_raw/Michael_Dougan.txt

Self-check example
------------------
  $ python3 scripts/audit_new_patients.py data_raw/Michael_Dougan.txt
  # Should print a markdown table with one row for Michael_Dougan
  # showing ADT=strong, Notes-rich=strong, Labs/MAR=strong, etc.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ── Keyword → domain mapping ───────────────────────────────────────
# Each entry:  (pattern_string, domain_key, case_insensitive)
# Counts are summed per domain; thresholds below convert to ratings.

_INDICATORS: List[Tuple[str, str, bool]] = [
    # ADT
    ("ADT Events",     "adt",       True),
    ("Transfer In",    "adt",       True),
    ("Transfer Out",   "adt",       True),
    ("Admission",      "adt",       False),  # case-sensitive to avoid noise
    ("Discharge",      "adt",       False),
    # SBIRT
    ("SBIRT",          "sbirt",     True),
    ("AUDIT-C",        "sbirt",     True),
    ("DAST-10",        "sbirt",     True),
    ("CAGE",           "sbirt",     False),
    # Procedure / Anesthesia
    ("Anesthesia",     "procedure", True),
    ("Operative",      "procedure", True),
    ("Procedure Note", "procedure", True),
    ("Surgical",       "procedure", True),
    # Neuro / TBI
    ("GCS",            "neuro",     False),
    ("Glasgow",        "neuro",     True),
    ("TBI",            "neuro",     False),
    ("Intracranial",   "neuro",     True),
    ("Subdural",       "neuro",     True),
    ("Craniotomy",     "neuro",     True),
    # Rib / Respiratory
    ("Incentive Spirometry", "respiratory", True),
    ("Chest Tube",     "respiratory", True),
    ("Rib Fracture",   "respiratory", True),
    ("rib fx",         "respiratory", True),
    ("Pneumothorax",   "respiratory", True),
    ("Hemothorax",     "respiratory", True),
    # Med / Allergy / Social
    ("Past Medical History",               "med_social", True),
    ("Allergies",                          "med_social", True),
    ("Social Hx",                          "med_social", True),
    ("Current Outpatient Medications",     "med_social", True),
    # Labs / MAR
    ("Component",      "labs_mar",  False),
    ("Hemoglobin",     "labs_mar",  True),
    ("INR",            "labs_mar",  False),
    ("Base Deficit",   "labs_mar",  True),
    ("Lactate",        "labs_mar",  True),
    ("MAR Admin",      "labs_mar",  True),
    ("ADS Dispense",   "labs_mar",  True),
    ("OMNICELL",       "labs_mar",  True),
    # Note sections
    ("Impression",     "notes",     False),
    ("Assessment",     "notes",     False),
    ("H&P",            "notes",     False),
    ("Trauma H & P",   "notes",     True),
    ("Progress Note",  "notes",     True),
    ("Case Management","notes",     True),
]

# Domain display labels (in column order)
_DOMAIN_COLS: List[Tuple[str, str]] = [
    ("adt",         "ADT"),
    ("notes",       "Notes-rich"),
    ("sbirt",       "SBIRT"),
    ("procedure",   "Proc/Anesth"),
    ("neuro",       "Neuro/TBI"),
    ("respiratory", "Rib/Resp"),
    ("med_social",  "Med/Allg/Soc"),
    ("labs_mar",    "Labs/MAR"),
]

# Thresholds: (min_count, rating)  — first match wins (descending)
_THRESHOLDS: List[Tuple[int, str]] = [
    (15, "strong"),
    (3,  "possible"),
    (0,  "none"),
]


# ── Format family detection ────────────────────────────────────────

_RE_NAME_AGE_DOB = re.compile(
    r"^\s*.+\n\s*\d+\s+year\s+old\s+(male|female)",
    re.IGNORECASE | re.MULTILINE,
)
_RE_LEGACY_KEYED = re.compile(
    r"^PATIENT_ID:\s*\d+",
    re.MULTILINE,
)


def _detect_format(header: str) -> str:
    if _RE_LEGACY_KEYED.search(header):
        return "legacy-keyed"
    if _RE_NAME_AGE_DOB.search(header):
        return "name-age-dob"
    return "unknown"


# ── Quirk detection ────────────────────────────────────────────────

def _detect_quirks(path: Path, header: str, text: str) -> List[str]:
    quirks: List[str] = []
    if " " in path.stem:
        quirks.append("space-in-filename")
    if header.startswith("\n") or header.startswith("\r"):
        quirks.append("leading-blank-line")
    if '"' in header.split("\n")[0]:
        quirks.append("nickname-in-header")
    line_count = text.count("\n") + 1
    if line_count > 30000:
        quirks.append(f"large-file({line_count // 1000}K-lines)")
    # ADT rows without "ADT Events" header
    if "ADT Events" not in text and re.search(
        r"\d{1,2}/\d{1,2}/\d{2,4}\s+\d{4}\t.*\t.*\t.*\tAdmission", text
    ):
        quirks.append("inline-ADT-no-header")
    return quirks


# ── Output artifact check ─────────────────────────────────────────

def _check_outputs(slug: str, base_dir: Path) -> str:
    """Return 'yes', 'no', or 'not_run'."""
    evidence = base_dir / "outputs" / "evidence" / slug / "patient_evidence_v1.json"
    timeline = base_dir / "outputs" / "timeline" / slug / "patient_days_v1.json"
    features = base_dir / "outputs" / "features" / slug / "patient_features_v1.json"

    if features.is_file() and timeline.is_file() and evidence.is_file():
        # Minimal size check — empty JSON would be < 10 bytes
        if features.stat().st_size > 50:
            return "yes"
        return "no"
    if evidence.is_file() or timeline.is_file() or features.is_file():
        return "no"  # partial outputs suggest a failed run
    return "not_run"


# ── Core scan ──────────────────────────────────────────────────────

def scan_patient(path: Path, check_outputs: bool, base_dir: Path) -> Dict[str, Any]:
    """Scan a single raw patient file and return a row dict."""
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()

    header = text[:500]
    slug = path.stem.replace(" ", "_")

    # Count domain hits
    domain_counts: Dict[str, int] = {}
    for keyword, domain, ci in _INDICATORS:
        if ci:
            c = text.lower().count(keyword.lower())
        else:
            c = text.count(keyword)
        domain_counts[domain] = domain_counts.get(domain, 0) + c

    # Convert counts to ratings
    ratings: Dict[str, str] = {}
    for domain, _ in _DOMAIN_COLS:
        count = domain_counts.get(domain, 0)
        for threshold, rating in _THRESHOLDS:
            if count >= threshold:
                ratings[domain] = rating
                break

    fmt = _detect_format(header)
    quirks = _detect_quirks(path, header, text)
    ingest = _check_outputs(slug, base_dir) if check_outputs else "not_run"

    return {
        "patient": path.stem,
        "raw_file": path.name,
        "format": fmt,
        "row_status": "estimated",
        "ingest_ok": ingest,
        "ratings": ratings,
        "quirks": "; ".join(quirks) if quirks else "",
    }


# ── Rendering ──────────────────────────────────────────────────────

def _render_markdown(rows: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    lines.append(
        "<!-- HEURISTIC / ESTIMATED ONLY — verified ratings require "
        "./run_patient.sh + report_features_qa.py -->"
    )
    lines.append("")

    # Header
    cols = ["Patient", "Raw file", "Format", "Row status", "Ingest OK?"]
    cols += [label for _, label in _DOMAIN_COLS]
    cols += ["Notes / quirks"]
    lines.append("| " + " | ".join(cols) + " |")
    lines.append("| " + " | ".join(["---"] * len(cols)) + " |")

    for r in rows:
        vals = [
            r["patient"],
            f'`{r["raw_file"]}`',
            r["format"],
            r["row_status"],
            r["ingest_ok"],
        ]
        vals += [r["ratings"].get(d, "none") for d, _ in _DOMAIN_COLS]
        vals += [r["quirks"]]
        lines.append("| " + " | ".join(vals) + " |")

    lines.append("")
    lines.append(
        "> **Note**: All richness ratings above are heuristic estimates from "
        "keyword pattern counts.  \n"
        "> Run `./run_patient.sh <patient>` and then "
        "`report_features_qa.py --pat <slug>` to verify ingest and feature coverage."
    )
    return "\n".join(lines)


def _render_tsv(rows: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    cols = ["Patient", "Raw file", "Format", "Row status", "Ingest OK?"]
    cols += [label for _, label in _DOMAIN_COLS]
    cols += ["Notes / quirks"]
    lines.append("\t".join(cols))

    for r in rows:
        vals = [
            r["patient"],
            r["raw_file"],
            r["format"],
            r["row_status"],
            r["ingest_ok"],
        ]
        vals += [r["ratings"].get(d, "none") for d, _ in _DOMAIN_COLS]
        vals += [r["quirks"]]
        lines.append("\t".join(vals))
    return "\n".join(lines)


# ── CLI ────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Heuristic new-patient audit matrix generator.\n"
            "Scans data_raw/*.txt files and prints a rough richness "
            "matrix.  Output is ESTIMATED — run ./run_patient.sh + "
            "report_features_qa.py to verify."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "files", nargs="*",
        help="One or more raw .txt file paths to scan.",
    )
    ap.add_argument(
        "--dir", dest="scan_dir", default=None,
        help="Scan all .txt files in this directory.",
    )
    ap.add_argument(
        "--limit", type=int, default=None,
        help="Max files to scan when using --dir.",
    )
    ap.add_argument(
        "--check-outputs", action="store_true", default=False,
        help=(
            "Check for existing pipeline output artifacts and set "
            "Ingest OK? to yes/no/not_run (conservative)."
        ),
    )
    ap.add_argument(
        "--format", dest="fmt", choices=["markdown", "tsv"],
        default="markdown",
        help="Output format (default: markdown).",
    )

    args = ap.parse_args()

    paths: List[Path] = []
    if args.scan_dir:
        scan_dir = Path(args.scan_dir)
        if not scan_dir.is_dir():
            print(f"ERROR: --dir path not found: {scan_dir}", file=sys.stderr)
            return 1
        txt_files = sorted(scan_dir.glob("*.txt"))
        if args.limit:
            txt_files = txt_files[: args.limit]
        paths.extend(txt_files)

    for f in args.files or []:
        p = Path(f)
        if not p.is_file():
            print(f"WARNING: file not found, skipping: {p}", file=sys.stderr)
            continue
        paths.append(p)

    if not paths:
        ap.print_help()
        return 1

    # Deduplicate preserving order
    seen: set = set()
    unique: List[Path] = []
    for p in paths:
        rp = p.resolve()
        if rp not in seen:
            seen.add(rp)
            unique.append(p)
    paths = unique

    # Determine repo base dir (for --check-outputs)
    base_dir = Path(__file__).resolve().parent.parent

    rows = [scan_patient(p, args.check_outputs, base_dir) for p in paths]

    if args.fmt == "tsv":
        print(_render_tsv(rows))
    else:
        print(_render_markdown(rows))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
