#!/usr/bin/env python3
"""
CerebralOS — Patient TXT Parser (Stage-1 Ingest)

Purpose:
- Deterministically parse a raw Epic-export .txt patient file
- Preserve ALL lines with line numbers (evidence_lines)
- Produce a stable, audit-friendly JSON artifact that downstream
  NTDS + protocol logic can use.

Reads:
  <input .txt file path>

Writes:
  outputs/patient_parse/<Last_First_or_filename>/patient_parse_v1.json

Guarantees:
- Deterministic output
- No inference beyond text
- Includes provenance.sha256 + line receipts
- Includes lightweight "note block" detection (optional scaffolding)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_OUT_DIR = REPO_ROOT / "outputs" / "patient_parse"

# Conservative note-title detection scaffolding (tweak later)
NOTE_TITLE_RE = re.compile(
    r"\b("
    r"TRAUMA\s+H\s*&\s*P|"
    r"TRAUMA\s+HISTORY\s+AND\s+PHYSICAL|"
    r"ED\s+PROVIDER\s+NOTE|"
    r"PROGRESS\s+NOTE|"
    r"DISCHARGE\s+SUMMARY|"
    r"OPERATIVE\s+NOTE|"
    r"CONSULT\s+NOTE|"
    r"RADIOLOGY\s+REPORT|"
    r"ANESTHESIA\s+POST\s+EVALUATION|"
    r"INTUBATION\s+NOTE"
    r")\b",
    re.IGNORECASE,
)

# “Section” headers that sometimes appear in exported definitions / copied content
SECTION_HEADERS = [
    "DESCRIPTION",
    "DEFINITION",
    "ELEMENT INTENT",
    "ELEMENT VALUES",
    "ELEMENT VALUE",
    "ADDITIONAL INFORMATION",
    "DATA SOURCE HIERARCHY GUIDE",
    "ASSOCIATED EDIT CHECKS",
    "EXCLUDE",
]


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_text(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()


def normalize_newlines(s: str) -> str:
    return (s or "").replace("\r\n", "\n").replace("\r", "\n")


def safe_slug(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[^A-Za-z0-9 _\-()]", "", s)
    s = s.strip().replace(" ", "_")
    return s or "UNKNOWN"


def read_text(path: Path) -> str:
    # Epic exports can be weird; try utf-8 then fallback
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1")


def build_evidence_lines(raw_text: str) -> List[Dict[str, Any]]:
    """
    Store every line with:
      - line_no (1-based)
      - text (verbatim line)
      - text_sha256 (line-level hash for anchored references)
    """
    lines = raw_text.splitlines()
    out: List[Dict[str, Any]] = []
    for i, ln in enumerate(lines, start=1):
        out.append(
            {
                "line_no": i,
                "text": ln,
                "text_sha256": sha256_text(ln),
            }
        )
    return out


def detect_note_blocks(lines: List[str]) -> List[Dict[str, Any]]:
    """
    Lightweight pass:
    - find lines matching NOTE_TITLE_RE
    - treat as starts; end at next note title or EOF
    This is scaffolding only; we’ll refine per Epic format later.
    """
    starts: List[int] = []
    for idx, ln in enumerate(lines):
        if NOTE_TITLE_RE.search(ln or ""):
            starts.append(idx)

    blocks: List[Dict[str, Any]] = []
    if not starts:
        return blocks

    for k, s_idx in enumerate(starts):
        e_idx = starts[k + 1] if (k + 1) < len(starts) else len(lines)
        title = lines[s_idx].strip()
        blocks.append(
            {
                "note_title": title,
                "start_line": s_idx + 1,
                "end_line": e_idx,
                "line_count": (e_idx - s_idx),
            }
        )
    return blocks


def split_sections(text: str) -> Dict[str, str]:
    """
    Deterministic section splitting within a text blob.
    Only used if those headers appear.
    """
    sections: Dict[str, List[str]] = {}
    current: Optional[str] = None

    for ln in (text or "").splitlines():
        up = (ln or "").strip().upper()
        if up in SECTION_HEADERS:
            current = up
            sections[current] = []
            continue
        if current is not None:
            sections[current].append(ln)

    return {k: "\n".join(v).strip() for k, v in sections.items() if "\n".join(v).strip()}


def guess_patient_label(input_path: Path) -> str:
    # Use filename stem (common: "Last First.txt" or similar)
    return safe_slug(input_path.stem)


def run(input_path: Path, out_dir: Path) -> Path:
    if not input_path.exists():
        raise SystemExit(f"Missing input file: {input_path}")

    raw_text = normalize_newlines(read_text(input_path))
    raw_sha = sha256_text(raw_text)

    lines = raw_text.splitlines()
    patient_label = guess_patient_label(input_path)

    # Build full evidence_lines (ALL lines)
    evidence_lines = build_evidence_lines(raw_text)

    # Optional scaffolding: note blocks
    note_blocks = detect_note_blocks(lines)

    payload: Dict[str, Any] = {
        "meta": {
            "system": "CerebralOS",
            "artifact": "patient_txt_parse",
            "version": "1.0.0",
            "created_at_utc": now_utc_iso(),
            "source_file": str(input_path),
            "source_file_size_bytes": input_path.stat().st_size,
            "raw_text_sha256": raw_sha,
            "line_count": len(lines),
        },
        "patient": {
            "label": patient_label,
        },
        "evidence_lines": evidence_lines,
        "note_blocks": note_blocks,
        # If section headers exist somewhere in file, keep them available for later tooling
        "detected_section_headers": list(split_sections(raw_text).keys()),
    }

    out_patient_dir = out_dir / patient_label
    out_patient_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_patient_dir / "patient_parse_v1.json"

    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return out_path


def main() -> int:
    ap = argparse.ArgumentParser(description="CerebralOS patient .txt parser (all lines)")
    ap.add_argument("--in", dest="inp", required=True, help="Path to patient .txt file")
    ap.add_argument(
        "--out-dir",
        dest="out_dir",
        default=str(DEFAULT_OUT_DIR),
        help="Base output directory (default: outputs/patient_parse)",
    )
    args = ap.parse_args()

    input_path = Path(args.inp).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()

    out_path = run(input_path, out_dir)

    print("OK ✅ Wrote:", out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
