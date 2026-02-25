#!/usr/bin/env python3
"""
LDA Events v1 — Lines / Drains / Airways Lifecycle Extraction.

Deterministic extraction of device lifecycle events from the **LDAs**
section of Epic-format encounter exports.  Captures each device's type,
placement timestamp, removal timestamp, duration, category, and
lightweight assessment rows when present.

Two source formats are handled:

  **Format A — Summary LDA** (newer event-log exports):
  Starts with ``LDAs`` header followed by device category line, device
  label, Placed/Removed/Duration fields, and optional timestamped
  assessment rows.

  **Format B — Event-log Active LDA** (daily-note–embedded):
  Starts with ``Patient Lines/Drains/Airways Status`` → ``Active LDAs``
  → tabular Name/Placement date/Placement time/Site/Days rows.

Source priority:
  1. Raw data file (``meta.source_file`` injected by the builder from
     the evidence JSON).
  2. Fail-closed when no raw file path or no LDAs section found.

Output key: ``lda_events_v1``

Output schema::

    {
      "devices": [
        {
          "device_type": "<string>",
          "device_label": "<string>",
          "category": "<string>",
          "placed_ts": "<MM/DD/YY HHMM> | null",
          "removed_ts": "<MM/DD/YY HHMM> | null",
          "duration_text": "<string> | null",
          "site": "<string> | null",
          "source_format": "summary | event_log",
          "assessment_count": <int>,
          "event_rows": [
            {
              "ts_raw": "MM/DD HHMM",
              "fields": {"<key>": "<value>", ...}
            }, ...
          ],
          "evidence": [
            {
              "role": "lda_device_entry",
              "snippet": "<first 120 chars>",
              "raw_line_id": "<sha256>"
            }
          ]
        }, ...
      ],
      "lda_device_count": <int>,
      "active_devices_count": <int>,
      "categories_present": ["PIV Line", "Urethral Catheter", ...],
      "devices_with_placement": ["<device_label>", ...],
      "devices_with_removal": ["<device_label>", ...],
      "source_file": "<path> | null",
      "source_rule_id": "lda_events_raw_file | no_lda_section",
      "warnings": [],
      "notes": []
    }

Fail-closed behaviour:
  - No raw file path → devices=[], source_rule_id="no_lda_section"
  - Raw file exists but no LDAs section → same
  - Section found, 0 devices extracted → lda_device_count=0

Boundary note:
  - Urine-output-specific extraction (aggregation, trending, normalization)
    is intentionally deferred to a separate ``urine_output_events_v1``
    feature.  This module captures raw assessment rows including any
    ``Output (ml)`` fields but does NOT perform urine-specific analysis.

Design:
- Deterministic, fail-closed.
- No LLM, no ML, no clinical inference.
- raw_line_id required on every evidence entry.
"""

from __future__ import annotations

import hashlib
import os
import re
from typing import Any, Dict, List, Optional, Tuple

_DNA = "DATA NOT AVAILABLE"

# ── LDA section markers ───────────────────────────────────────────

# Format A: "LDAs" alone on a line (with optional trailing whitespace/tabs)
RE_LDA_SUMMARY_HEADER = re.compile(r"^LDAs\s*$")

# Format B: "Patient Lines/Drains/Airways Status" or "Active LDAs"
RE_LDA_EVENTLOG_HEADER = re.compile(
    r"^(?:Patient\s+Lines/Drains/Airways\s+Status|Active\s+LDAs)\s*$"
)

# Combined: "Lines / Drains / Airways" or "Lines" can precede the event-log block
RE_LDA_LINES_HEADER = re.compile(
    r"^(?:\s*Lines\s*/\s*Drains\s*/\s*Airways\s*|Lines\s*)$"
)

# ── Section boundary headers (end of LDA section) ──────────────
RE_SECTION_BOUNDARY = re.compile(
    r"^(?:Notes|Flowsheets|Meds|Labs|Scheduled|Patient Movement|"
    r"Imaging(?:,\s*EKG,?\s*and\s*Radiology)?|"
    r"Vent\s*Settings|Nutritional\s*Status|Chief\s*Complaint|"
    r"Subjective|Objective|Exam|"
    r" Exam)\s*$",
    re.IGNORECASE,
)

# ── Device category/type line (Format A) ──────────────────────
# Examples: "PIV Line, Line", "Drain, Urethral Catheter, NHSN Urethral Catheter"
#           "Wound"
# These lines appear on their own, contain comma-separated categories, no digits
RE_CATEGORY_LINE = re.compile(
    r"^(?:PIV Line|Drain|Wound|Peripheral Nerve Catheter|"
    r"Urethral Catheter|NHSN Urethral Catheter|"
    r"External Urinary Catheter|"
    r"Line|Airway|Central Line|Arterial Line|"
    r"PICC|Triple Lumen|Chest Tube|"
    r"JP Drain|Surgical Drain|"
    r"G-tube|J-tube|Feeding Tube|PEG|"
    r"Surgical Airway|Trach)"
)

# ── Device label line (Format A): "Peripheral IV 12/31/25 Left Antecubital\t\t\tN assessments"
RE_DEVICE_LABEL_A = re.compile(
    r"^(?P<label>.+?)\s+(?P<assess_count>\d+)\s+assessments?\s*$"
)

# ── Device label line (Format A variant): no assessment count
# e.g. "Urethral Catheter 16 fr Anchored\t\t\tPlaced"
RE_DEVICE_LABEL_A_NO_ASSESS = re.compile(
    r"^(?P<label>(?:Peripheral IV|Urethral Catheter|External Urinary Catheter|"
    r"PICC|Arterial Line|Central Line|Chest Tube|"
    r"Surgical Airway|Continuous Nerve Block|G-tube|J-tube|Feeding Tube|"
    r"Wound|JP Drain|Surgical Drain).+?)\s+(?:Placed|$)",
)

# ── Device label line (Format B): "Peripheral IV 12/24/25 Right Forearm"
# or "PICC Triple Lumen" or "Urethral Catheter 16 fr Anchored"
RE_DEVICE_LABEL_B = re.compile(
    r"^(?P<label>(?:Peripheral IV|Urethral Catheter|External Urinary Catheter|"
    r"PICC|Arterial Line|Central Line|Chest Tube|"
    r"Surgical Airway|G-tube|Continuous Nerve Block|J-tube|Feeding Tube|"
    r"G-tube.*PEG|Wound|JP Drain|Surgical Drain).+?)\s*$",
)

# ── Placed/Removed/Duration field patterns ─────────────────────
RE_PLACED = re.compile(r"^Placed\s*$", re.IGNORECASE)
RE_REMOVED = re.compile(r"^Removed\s*$", re.IGNORECASE)
RE_DURATION = re.compile(r"^Duration\s*$", re.IGNORECASE)

# ── Date/time pattern: MM/DD/YY HHMM ─────────────────────────
RE_DATE_TIME = re.compile(r"(\d{2}/\d{2}/\d{2})\s+(\d{4})")
RE_DATE_ONLY = re.compile(r"^(\d{2}/\d{2}/\d{2})\s*$")

# ── Assessment timestamp: "\tMM/DD\tHHMM\t..." ───────────────
RE_ASSESS_TS = re.compile(r"^\t(\d{2}/\d{2})\t(\d{4})\t")

# ── Event-log tabular header ──────────────────────────────────
RE_EVENTLOG_TABLE_HEADER = re.compile(r"^Name\s*$")

# ── Duration value line ──────────────────────────────────────
RE_DURATION_VAL = re.compile(
    r"^(?:less than )?\d+\s+days?$|^<\d+\s+days?$",
    re.IGNORECASE,
)

# ── Present on Discharge pattern ─────────────────────────────
RE_PRESENT_ON_DISCHARGE = re.compile(r"^Present on Discharge$", re.IGNORECASE)

# ── Category mapping ──────────────────────────────────────────
_CATEGORY_MAP = {
    "peripheral iv": "PIV",
    "picc": "PICC",
    "arterial line": "Arterial Line",
    "central line": "Central Line",
    "urethral catheter": "Urethral Catheter",
    "external urinary catheter": "External Urinary Catheter",
    "chest tube": "Chest Tube",
    "surgical airway": "Surgical Airway/Trach",
    "surgical airway/trach": "Surgical Airway/Trach",
    "g-tube": "Feeding Tube",
    "j-tube": "Feeding Tube",
    "feeding tube": "Feeding Tube",
    "peg": "Feeding Tube",
    "wound": "Wound",
    "jp drain": "Drain",
    "surgical drain": "Drain",
    "drain": "Drain",
    "continuous nerve block": "Peripheral Nerve Catheter",
    "peripheral nerve catheter": "Peripheral Nerve Catheter",
}

_MAX_ASSESSMENT_ROWS = 50  # cap per device to keep output deterministic


# ─────────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────────

def _make_raw_line_id(text: str) -> str:
    """Deterministic SHA-256 hash of the raw line text."""
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _classify_device(label: str) -> str:
    """Map a device label to a canonical category."""
    lower = label.lower()
    for prefix, cat in _CATEGORY_MAP.items():
        if lower.startswith(prefix):
            return cat
    return "Other"


def _classify_device_type(label: str) -> str:
    """Extract device type from a device label string."""
    # Take the first few words before date/number info
    # e.g. "Peripheral IV 12/31/25 Left Antecubital" → "Peripheral IV"
    # e.g. "Urethral Catheter 16 fr Anchored" → "Urethral Catheter"
    # e.g. "PICC Triple Lumen" → "PICC Triple Lumen"
    # e.g. "Surgical Airway/Trach Shiley 8 mm Distal;Long" → "Surgical Airway/Trach"
    for prefix in sorted(_CATEGORY_MAP.keys(), key=len, reverse=True):
        if label.lower().startswith(prefix):
            return label[:len(prefix)].strip()
    # Fallback: first two words
    parts = label.split()
    return " ".join(parts[:2]) if len(parts) >= 2 else label


# ─────────────────────────────────────────────────────────────────
# Section extraction from raw file
# ─────────────────────────────────────────────────────────────────

def _extract_lda_sections(filepath: str) -> Optional[List[List[Tuple[int, str]]]]:
    """
    Read the raw data file and extract all LDA sections.

    Returns a list of sections, each section being a list of
    (line_number, line_text) tuples, or None if no LDA section found.

    Handles both Format A (``LDAs``) and Format B
    (``Patient Lines/Drains/Airways Status`` / ``Active LDAs``).
    """
    if not filepath or not os.path.isfile(filepath):
        return None

    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
    except OSError:
        return None

    sections: List[List[Tuple[int, str]]] = []
    i = 0
    n = len(all_lines)

    while i < n:
        line = all_lines[i].rstrip("\n\r")
        stripped = line.strip()

        # Check for Format A header: "LDAs"
        if RE_LDA_SUMMARY_HEADER.match(stripped):
            section_lines: List[Tuple[int, str]] = []
            section_lines.append((i + 1, line))
            i += 1
            # Collect lines until next section boundary
            while i < n:
                inner = all_lines[i].rstrip("\n\r")
                inner_stripped = inner.strip()
                if RE_SECTION_BOUNDARY.match(inner_stripped):
                    break
                # Another LDAs header means a new section
                if RE_LDA_SUMMARY_HEADER.match(inner_stripped) and len(section_lines) > 3:
                    break
                section_lines.append((i + 1, inner))
                i += 1
            if len(section_lines) > 1:
                sections.append(section_lines)
            continue

        # Check for Format B header chain: "Lines / Drains / Airways" or
        # "Patient Lines/Drains/Airways Status" or "Active LDAs"
        if RE_LDA_EVENTLOG_HEADER.match(stripped) or RE_LDA_LINES_HEADER.match(stripped):
            # Look forward for "Active LDAs" to confirm
            section_lines = []
            section_lines.append((i + 1, line))
            i += 1
            found_active = False
            while i < n:
                inner = all_lines[i].rstrip("\n\r")
                inner_stripped = inner.strip()
                if RE_SECTION_BOUNDARY.match(inner_stripped):
                    break
                if inner_stripped == "Active LDAs":
                    found_active = True
                section_lines.append((i + 1, inner))
                i += 1
                # End on next major section or next LDA block
                if found_active and RE_LDA_LINES_HEADER.match(inner_stripped):
                    break
                if found_active and RE_LDA_EVENTLOG_HEADER.match(inner_stripped) and len(section_lines) > 10:
                    break
            if found_active and len(section_lines) > 1:
                sections.append(section_lines)
            continue

        i += 1

    return sections if sections else None


# ─────────────────────────────────────────────────────────────────
# Format A parser (Summary LDA)
# ─────────────────────────────────────────────────────────────────

def _parse_summary_lda(section_lines: List[Tuple[int, str]]) -> Tuple[List[Dict], List[str]]:
    """
    Parse a Format A LDA section into device dicts.

    Format A layout:
      LDAs
      <category_line>  (e.g. "PIV Line, Line")
      <device_label>\t\t\t<N> assessments
      Placed
      <MM/DD/YY HHMM>
      [blank]
      Removed
      <MM/DD/YY HHMM>
      [blank]
      Duration
      <text>
      [blank]
      \t<MM/DD>\t<HHMM>\t<field-value rows>  (assessment rows)
      ...
      <next category_line or end of section>
    """
    devices: List[Dict] = []
    warnings: List[str] = []

    i = 0
    n = len(section_lines)
    current_category = ""

    while i < n:
        line_num, line = section_lines[i]
        stripped = line.strip()

        # Skip header, blank, or "LDAs" itself
        if not stripped or RE_LDA_SUMMARY_HEADER.match(stripped):
            i += 1
            continue

        # ── Device label checks BEFORE category check ──
        # Device labels can start with category prefixes (e.g. "Urethral
        # Catheter 16 fr Anchored\t\t\tPlaced") so they must be matched
        # first to avoid being consumed as a category line.

        # Check for device label with assessment count
        m_label = RE_DEVICE_LABEL_A.match(stripped)
        if m_label:
            label = m_label.group("label").strip()
            assess_count = int(m_label.group("assess_count"))
            raw_id = _make_raw_line_id(line)

            device = _parse_device_block_a(
                section_lines, i + 1, label, current_category,
                assess_count, raw_id, line_num,
            )
            devices.append(device)
            # Advance past this device's block
            i = device.pop("_end_idx", i + 1)
            continue

        # Check for device label without assessment count (Format A variant)
        # These have "Placed" on the same line or on the next
        m_label_no = RE_DEVICE_LABEL_A_NO_ASSESS.match(stripped)
        if m_label_no:
            label = m_label_no.group("label").strip()
            raw_id = _make_raw_line_id(line)

            # When "Placed" appears on the label line itself, the next
            # line is the placed timestamp — start in "placed" state.
            init_st = "placed" if "Placed" in stripped[len(label):] else "seek"

            device = _parse_device_block_a(
                section_lines, i + 1, label, current_category,
                0, raw_id, line_num,
                initial_state=init_st,
            )
            devices.append(device)
            i = device.pop("_end_idx", i + 1)
            continue

        # ── Category line check (after device labels) ──
        if RE_CATEGORY_LINE.match(stripped) and not RE_DATE_TIME.search(stripped):
            # Category lines don't contain dates or end with "assessments"
            if "assessment" not in stripped.lower() and not RE_DATE_ONLY.match(stripped):
                if not re.search(r"\d{2}/\d{2}/\d{2}", stripped):
                    current_category = stripped
                    i += 1
                    continue

        # Check for device label (Format B style appearing in Format A context)
        m_label_b = RE_DEVICE_LABEL_B.match(stripped)
        if m_label_b:
            label = m_label_b.group("label").strip()
            raw_id = _make_raw_line_id(line)

            # Look ahead for Placed/Removed/Duration
            device = _parse_device_block_a(
                section_lines, i + 1, label, current_category,
                0, raw_id, line_num,
            )
            devices.append(device)
            i = device.pop("_end_idx", i + 1)
            continue

        i += 1

    return devices, warnings


def _parse_device_block_a(
    section_lines: List[Tuple[int, str]],
    start_idx: int,
    label: str,
    category_line: str,
    assess_count: int,
    raw_line_id: str,
    source_line_num: int,
    initial_state: str = "seek",
) -> Dict[str, Any]:
    """Parse the Placed/Removed/Duration/assessment block for a Format A device."""
    placed_ts: Optional[str] = None
    removed_ts: Optional[str] = None
    duration_text: Optional[str] = None
    event_rows: List[Dict[str, Any]] = []
    site: Optional[str] = None

    i = start_idx
    n = len(section_lines)

    state = initial_state  # seek | placed | removed | duration | assessments

    while i < n:
        line_num, line = section_lines[i]
        stripped = line.strip()

        # Check if we hit a new device (category or label line)
        if RE_CATEGORY_LINE.match(stripped) and not RE_DATE_TIME.search(stripped):
            if "assessment" not in stripped.lower():
                if not re.search(r"\d{2}/\d{2}/\d{2}", stripped):
                    break

        if RE_DEVICE_LABEL_A.match(stripped):
            break
        if RE_DEVICE_LABEL_A_NO_ASSESS.match(stripped) and stripped != label:
            break
        m_next = RE_DEVICE_LABEL_B.match(stripped)
        if m_next and stripped != label and i > start_idx + 1:
            break

        # Placed
        if RE_PLACED.match(stripped):
            state = "placed"
            i += 1
            continue

        # Removed
        if RE_REMOVED.match(stripped):
            state = "removed"
            i += 1
            continue

        # Duration
        if RE_DURATION.match(stripped):
            state = "duration"
            i += 1
            continue

        # Present on Discharge — skip
        if RE_PRESENT_ON_DISCHARGE.match(stripped):
            i += 1
            # skip value on next line
            if i < n:
                i += 1
            continue

        if state == "placed" and stripped:
            m_dt = RE_DATE_TIME.search(stripped)
            if m_dt:
                placed_ts = f"{m_dt.group(1)} {m_dt.group(2)}"
            elif RE_DATE_ONLY.match(stripped):
                # Date only, time on next line
                date_str = stripped
                i += 1
                if i < n:
                    _, next_line = section_lines[i]
                    time_str = next_line.strip()
                    if re.match(r"^\d{4}\s*$", time_str):
                        placed_ts = f"{date_str} {time_str.strip()}"
                        i += 1
                        continue
                    else:
                        placed_ts = date_str
                continue
            state = "seek"
            i += 1
            continue

        if state == "removed" and stripped:
            m_dt = RE_DATE_TIME.search(stripped)
            if m_dt:
                removed_ts = f"{m_dt.group(1)} {m_dt.group(2)}"
            elif RE_DATE_ONLY.match(stripped):
                date_str = stripped
                i += 1
                if i < n:
                    _, next_line = section_lines[i]
                    time_str = next_line.strip()
                    if re.match(r"^\d{4}\s*$", time_str):
                        removed_ts = f"{date_str} {time_str.strip()}"
                        i += 1
                        continue
                    else:
                        removed_ts = date_str
                continue
            state = "seek"
            i += 1
            continue

        if state == "duration" and stripped:
            duration_text = stripped
            state = "seek"
            i += 1
            continue

        # Assessment row: starts with tab + date MM/DD + tab + time HHMM
        m_assess = RE_ASSESS_TS.match(line)
        if m_assess and len(event_rows) < _MAX_ASSESSMENT_ROWS:
            ts_raw = f"{m_assess.group(1)} {m_assess.group(2)}"
            # Parse key-value fields from subsequent lines
            fields: Dict[str, str] = {}
            remainder = line[m_assess.end():].strip()
            if remainder:
                # First field might be on the timestamp line
                fields["_first"] = remainder
            i += 1
            while i < n:
                _, fline = section_lines[i]
                fstripped = fline.strip()
                # Stop at next assessment timestamp, next device, or section end
                if RE_ASSESS_TS.match(fline):
                    break
                if RE_CATEGORY_LINE.match(fstripped) and not RE_DATE_TIME.search(fstripped) and "assessment" not in fstripped.lower():
                    if not re.search(r"\d{2}/\d{2}/\d{2}", fstripped):
                        break
                if RE_DEVICE_LABEL_A.match(fstripped):
                    break
                if RE_DEVICE_LABEL_A_NO_ASSESS.match(fstripped):
                    break
                m_b = RE_DEVICE_LABEL_B.match(fstripped)
                if m_b and fstripped != label:
                    break
                if RE_PLACED.match(fstripped) or RE_REMOVED.match(fstripped) or RE_DURATION.match(fstripped):
                    break
                if RE_PRESENT_ON_DISCHARGE.match(fstripped):
                    break

                if not fstripped:
                    i += 1
                    continue

                # Key-value pair: the key is alone on a line, value on next line
                # But some are just value lines after a key on the same line
                fields[fstripped] = ""
                # peek: if next non-empty line looks like a value (no key pattern)
                i += 1
                if i < n:
                    _, vline = section_lines[i]
                    vstripped = vline.strip()
                    if vstripped and not RE_ASSESS_TS.match(vline) and not RE_PLACED.match(vstripped) and not RE_REMOVED.match(vstripped) and not RE_DURATION.match(vstripped):
                        # Check if it's a value (not another key pattern)
                        # Heuristic: values tend to be shorter or contain units/numbers
                        fields[fstripped] = vstripped
                        i += 1
                continue

            # Clean up _first field
            first_val = fields.pop("_first", None)
            if first_val:
                fields["note"] = first_val

            event_rows.append({
                "ts_raw": ts_raw,
                "fields": fields,
            })
            continue

        # Skip blanks and unrecognized lines
        i += 1

    device_type = _classify_device_type(label)
    category = _classify_device(label)

    return {
        "device_type": device_type,
        "device_label": label,
        "category": category,
        "placed_ts": placed_ts,
        "removed_ts": removed_ts,
        "duration_text": duration_text,
        "site": site,
        "source_format": "summary",
        "assessment_count": assess_count or len(event_rows),
        "event_rows": event_rows,
        "evidence": [
            {
                "role": "lda_device_entry",
                "snippet": label[:120],
                "raw_line_id": raw_line_id,
            }
        ],
        "_end_idx": i,
    }


# ─────────────────────────────────────────────────────────────────
# Format B parser (Event-log Active LDA)
# ─────────────────────────────────────────────────────────────────

def _parse_eventlog_lda(section_lines: List[Tuple[int, str]]) -> Tuple[List[Dict], List[str]]:
    """
    Parse a Format B (event-log) LDA section.

    Format B layout:
      [Lines / Drains / Airways]
      Patient Lines/Drains/Airways Status
      [blank]
      Active LDAs
      [blank]
      Name
      Placement date
      Placement time
      Site
      Days
      [blank]
      <device_label>
      <MM/DD/YY>             ← placement date
      <HHMM>                 ← placement time
      <site>                 ← site/location
      <days_count>           ← "less than 1" or N
      [blank]
      <next device_label or section end>
    """
    devices: List[Dict] = []
    warnings: List[str] = []

    # Skip header lines until after "Days" (the last column header)
    i = 0
    n = len(section_lines)
    found_days_header = False
    while i < n:
        _, line = section_lines[i]
        stripped = line.strip()
        if stripped == "Days":
            found_days_header = True
            i += 1
            break
        i += 1

    if not found_days_header:
        # Try to find device labels directly
        i = 0

    while i < n:
        line_num, line = section_lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # Check for section boundary
        if RE_SECTION_BOUNDARY.match(stripped):
            break

        # Check for device label
        m_dev = RE_DEVICE_LABEL_B.match(stripped)
        if m_dev:
            label = m_dev.group("label").strip()
            raw_id = _make_raw_line_id(line)

            placed_date = None
            placed_time = None
            site = None
            duration_text = None

            # Read next lines: date, time, site, days
            j = i + 1
            # Skip blanks
            while j < n and not section_lines[j][1].strip():
                j += 1

            # Placement date
            if j < n:
                _, dline = section_lines[j]
                d_stripped = dline.strip()
                if RE_DATE_ONLY.match(d_stripped) or re.match(r"^\d{2}/\d{2}/\d{2}\s*$", d_stripped):
                    placed_date = d_stripped
                    j += 1

            # Skip blanks
            while j < n and not section_lines[j][1].strip():
                j += 1

            # Placement time
            if j < n:
                _, tline = section_lines[j]
                t_stripped = tline.strip()
                if re.match(r"^\d{3,4}\s*$", t_stripped):
                    placed_time = t_stripped
                    j += 1

            # Skip blanks
            while j < n and not section_lines[j][1].strip():
                j += 1

            # Site
            if j < n:
                _, sline = section_lines[j]
                s_stripped = sline.strip()
                # Site is usually a word/phrase, not a date/time/number/section-header
                if s_stripped and not re.match(r"^\d+$", s_stripped) and not RE_SECTION_BOUNDARY.match(s_stripped):
                    if not RE_DEVICE_LABEL_B.match(s_stripped):
                        site = s_stripped
                        j += 1

            # Skip blanks
            while j < n and not section_lines[j][1].strip():
                j += 1

            # Days
            if j < n:
                _, dayline = section_lines[j]
                day_stripped = dayline.strip()
                if re.match(r"^(?:less than )?\d+\s*$", day_stripped, re.IGNORECASE):
                    duration_text = f"{day_stripped} day(s)"
                    j += 1

            placed_ts = None
            if placed_date:
                placed_ts = f"{placed_date} {placed_time}" if placed_time else placed_date

            device_type = _classify_device_type(label)
            category = _classify_device(label)

            devices.append({
                "device_type": device_type,
                "device_label": label,
                "category": category,
                "placed_ts": placed_ts,
                "removed_ts": None,  # Event-log format doesn't include removal
                "duration_text": duration_text,
                "site": site if site != "—" else None,
                "source_format": "event_log",
                "assessment_count": 0,
                "event_rows": [],
                "evidence": [
                    {
                        "role": "lda_device_entry",
                        "snippet": label[:120],
                        "raw_line_id": raw_id,
                    }
                ],
            })

            i = j
            continue

        # Also handle "compact" device lines that contain date in the label itself
        # e.g. "Peripheral IV 12/24/25 Right Forearm"
        # These should be caught by RE_DEVICE_LABEL_B above, but if not:
        i += 1

    return devices, warnings


# ─────────────────────────────────────────────────────────────────
# Section classifier
# ─────────────────────────────────────────────────────────────────

def _classify_section_format(section_lines: List[Tuple[int, str]]) -> str:
    """Determine whether a section is Format A (summary) or Format B (event-log)."""
    for _, line in section_lines[:10]:
        stripped = line.strip()
        if "Active LDAs" in stripped or "Patient Lines/Drains/Airways Status" in stripped:
            return "event_log"
        if RE_LDA_SUMMARY_HEADER.match(stripped):
            # Format A starts with "LDAs" alone
            return "summary"
    return "summary"  # default


# ─────────────────────────────────────────────────────────────────
# Deduplication
# ─────────────────────────────────────────────────────────────────

def _deduplicate_devices(devices: List[Dict]) -> List[Dict]:
    """
    Merge duplicate device entries (same label) keeping the richest data.
    Event-log snapshots from different days may produce duplicates.
    """
    seen: Dict[str, Dict] = {}  # label → best device dict
    for dev in devices:
        label = dev["device_label"]
        if label not in seen:
            seen[label] = dev
        else:
            existing = seen[label]
            # Prefer the entry with more data
            if dev.get("placed_ts") and not existing.get("placed_ts"):
                existing["placed_ts"] = dev["placed_ts"]
            if dev.get("removed_ts") and not existing.get("removed_ts"):
                existing["removed_ts"] = dev["removed_ts"]
            if dev.get("duration_text") and not existing.get("duration_text"):
                existing["duration_text"] = dev["duration_text"]
            if dev.get("site") and not existing.get("site"):
                existing["site"] = dev["site"]
            # Merge assessment rows (dedup by ts_raw)
            existing_ts = {r["ts_raw"] for r in existing.get("event_rows", [])}
            for row in dev.get("event_rows", []):
                if row["ts_raw"] not in existing_ts and len(existing.get("event_rows", [])) < _MAX_ASSESSMENT_ROWS:
                    existing.setdefault("event_rows", []).append(row)
                    existing_ts.add(row["ts_raw"])
            # Update assessment count
            existing["assessment_count"] = max(
                existing.get("assessment_count", 0),
                dev.get("assessment_count", 0),
                len(existing.get("event_rows", [])),
            )
            # Merge evidence
            existing_ids = {e["raw_line_id"] for e in existing.get("evidence", [])}
            for e in dev.get("evidence", []):
                if e["raw_line_id"] not in existing_ids:
                    existing.setdefault("evidence", []).append(e)
    return list(seen.values())


# ─────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────

def extract_lda_events(
    pat_features: Dict[str, Any],
    days_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Extract LDA lifecycle events from the raw data file.

    Args:
        pat_features: {"days": feature_days} — per-day extracted features
        days_data: full patient_days_v1.json dict (contains meta.source_file)

    Returns:
        dict with keys: devices, lda_device_count, active_devices_count,
        categories_present, devices_with_placement, devices_with_removal,
        source_file, source_rule_id, warnings, notes
    """
    meta = days_data.get("meta") or {}
    source_file = meta.get("source_file")

    empty_result: Dict[str, Any] = {
        "devices": [],
        "lda_device_count": 0,
        "active_devices_count": 0,
        "categories_present": [],
        "devices_with_placement": [],
        "devices_with_removal": [],
        "source_file": source_file,
        "source_rule_id": "no_lda_section",
        "warnings": [],
        "notes": [],
    }

    if not source_file:
        empty_result["notes"].append("No meta.source_file — raw file not available")
        return empty_result

    sections = _extract_lda_sections(source_file)
    if not sections:
        empty_result["notes"].append("No LDAs section found in raw file")
        return empty_result

    all_devices: List[Dict] = []
    all_warnings: List[str] = []

    for section in sections:
        fmt = _classify_section_format(section)
        if fmt == "event_log":
            devs, warns = _parse_eventlog_lda(section)
        else:
            devs, warns = _parse_summary_lda(section)
        all_devices.extend(devs)
        all_warnings.extend(warns)

    # Deduplicate across sections (event-log may repeat devices)
    all_devices = _deduplicate_devices(all_devices)

    # Build summary fields
    categories = sorted(set(d["category"] for d in all_devices))
    with_placement = sorted(set(
        d["device_label"] for d in all_devices if d.get("placed_ts")
    ))
    with_removal = sorted(set(
        d["device_label"] for d in all_devices if d.get("removed_ts")
    ))

    # Active devices: those with placement but no removal
    active_count = sum(
        1 for d in all_devices
        if d.get("placed_ts") and not d.get("removed_ts")
    )

    # Build notes
    notes: List[str] = []
    format_types = sorted(set(d["source_format"] for d in all_devices))
    if format_types:
        notes.append(f"source_formats: {', '.join(format_types)}")
    notes.append(
        "Urine-output-specific analysis deferred to urine_output_events_v1"
    )

    return {
        "devices": all_devices,
        "lda_device_count": len(all_devices),
        "active_devices_count": active_count,
        "categories_present": categories,
        "devices_with_placement": with_placement,
        "devices_with_removal": with_removal,
        "source_file": source_file,
        "source_rule_id": "lda_events_raw_file",
        "warnings": all_warnings,
        "notes": notes,
    }
