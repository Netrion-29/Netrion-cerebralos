#!/usr/bin/env python3
"""
CerebralOS -- Patient TXT -> Evidence JSON (v1.1)

Goal:
- Deterministically parse a raw Epic-export .txt into a single "evidence" artifact
  that downstream timeline + daily-notes can consume.

Writes (default):
  outputs/evidence/<PATIENT_SLUG>/patient_evidence_v1.json

Design:
- Fail-closed: never crash on weird formatting; keep raw text.
- No inference: only extract explicit header fields and timestamped blocks.
- Timeline-friendly: emits `items: []` where each item has a datetime + type + text.
- Block-level timestamp extraction: when block header timestamps match arrival
  (or are missing), scan block body for deterministic inline timestamps.
- Items with no deterministic timestamp get datetime=null + "ts_missing" warning.

Expected header patterns (commonly present near top of file):
  PATIENT_ID: 2849731
  ARRIVAL_TIME: 2025-12-31 14:59:00
  PATIENT_NAME: Anna Dennis
  DOB: 3/20/1960
  TRAUMA_CATEGORY: 2

Expected block marker patterns:
  [CONSULT_NOTE] 2025-12-31 15:44:00
  [NURSING_NOTE] 2026-01-02 10:25:00
  [TRAUMA_HP]   2025-12-26 11:54:00
  [REMOVED] CVC Triple Lumen 12/18/25 Right Internal jugular
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ============================================================
# Regex -- block detection
# ============================================================

RE_HEADER_KV = re.compile(r"^\s*([A-Z_]+)\s*:\s*(.*?)\s*$")

# Standard block: [KIND] YYYY-MM-DD HH:MM:SS
RE_BLOCK_STANDARD = re.compile(
    r"^\s*\[(?P<kind>[A-Z_]+)\]\s+(?P<dt>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s*$"
)

# REMOVED block: [REMOVED] <description text>
RE_BLOCK_REMOVED = re.compile(
    r"^\s*\[REMOVED\]\s+(?P<desc>.+)$"
)


# ============================================================
# Timestamp format counter (global, reset per build_evidence call)
# ============================================================

_TS_FORMAT_COUNTS: Dict[str, int] = {}
_TS_FORMAT_FAILURES: int = 0

def _ts_count(format_label: str) -> None:
    """Increment the counter for a successfully parsed timestamp format."""
    _TS_FORMAT_COUNTS[format_label] = _TS_FORMAT_COUNTS.get(format_label, 0) + 1

def _ts_fail() -> None:
    """Increment the failure counter."""
    global _TS_FORMAT_FAILURES
    _TS_FORMAT_FAILURES += 1

def _reset_ts_counts() -> None:
    """Reset format counts for a new patient run."""
    global _TS_FORMAT_FAILURES
    _TS_FORMAT_COUNTS.clear()
    _TS_FORMAT_FAILURES = 0

def get_timestamp_format_counts() -> Dict[str, Any]:
    """Return a snapshot of timestamp format counts for QA."""
    return {
        "format_counts": dict(_TS_FORMAT_COUNTS),
        "total_parsed": sum(_TS_FORMAT_COUNTS.values()),
        "total_failed": _TS_FORMAT_FAILURES,
    }


# ============================================================
# Regex -- in-block timestamp patterns (deterministic)
# ============================================================

# "Exam Ended: 12/18/25 16:21 CST"
RE_EXAM_ENDED = re.compile(
    r"Exam Ended:\s*(\d{1,2}/\d{1,2}/\d{2,4})\s+(\d{2}:\d{2})")

# "Last Resulted: 12/18/25 16:23 CST"
RE_LAST_RESULTED = re.compile(
    r"Last Resulted:\s*(\d{1,2}/\d{1,2}/\d{2,4})\s+(\d{2}:\d{2})")

# "(Exam End: 12/18/2025 16:38)"
RE_EXAM_END_PAREN = re.compile(
    r"\(Exam End:\s*(\d{1,2}/\d{1,2}/\d{2,4})\s+(\d{2}:\d{2})\)")

# "Ordering Date/Time: Sat Jan 3, 2026 1735"
RE_ORDERING_DT = re.compile(
    r"Ordering Date/Time:\s*\w+\s+(\w+\s+\d{1,2},\s+\d{4})\s+(\d{4})")

# "D/C Date/Time: Sat Jan 3, 2026 1735"
RE_DC_DT = re.compile(
    r"D/C Date/Time:\s*\w+\s+(\w+\s+\d{1,2},\s+\d{4})\s+(\d{4})")

# "Ordered On\t1/15/2026  2:38 PM"
RE_ORDERED_ON = re.compile(
    r"Ordered On\s+(\d{1,2}/\d{1,2}/\d{4})\s+(\d{1,2}:\d{2}\s*[AP]M)")

# "Result Date: 12/18/2025" (date only)
RE_RESULT_DATE = re.compile(
    r"Result Date:\s*(\d{1,2}/\d{1,2}/\d{4})")

# "Admission on 12/18/2025" (date only)
RE_ADMISSION_ON = re.compile(
    r"Admission on\s+(\d{1,2}/\d{1,2}/\d{4})")

# "Placement date\t12/18/25" (for REMOVED/device blocks)
RE_PLACEMENT_DATE = re.compile(
    r"Placement date\s+(\d{1,2}/\d{1,2}/\d{2,4})")

# "Removal date\t12/19/25"
RE_REMOVAL_DATE = re.compile(
    r"Removal date\s+(\d{1,2}/\d{1,2}/\d{2,4})")

# Order-history line: "01/15/26 1438\tRelease ..."
RE_ORDER_HIST_LINE = re.compile(
    r"^(\d{2}/\d{2}/\d{2})\s+(\d{4})\s+")

# Generic inline "MM/DD/YY HHMM" like "at 12/18/25 1535"
RE_INLINE_MMDDYY_HHMM = re.compile(
    r"\b(\d{1,2}/\d{1,2}/\d{2})\s+(\d{4})\b")

# RADIOLOGY-only: "Final result\t12/19/2025" or "<study> Final result  12/19/2025"
RE_FINAL_RESULT_DATE = re.compile(
    r"\bFinal result\b[^\d]{0,10}(?P<date>\d{1,2}/\d{1,2}/\d{4})\b")

# RADIOLOGY-only: standalone date near "Reading Physician / Reading Date" header
RE_READING_DATE_HEADER = re.compile(
    r"Reading (Physician|Date)", re.IGNORECASE)
RE_STANDALONE_DATE = re.compile(
    r"\b(?P<date>\d{1,2}/\d{1,2}/\d{4})\b")

# --- New multi-format patterns (build-forward) ---

# "M/D/YYYY H:MM AM/PM" human display timestamps (e.g. "2/6/2026 1:57 PM")
RE_HUMAN_DISPLAY_DT = re.compile(
    r"\b(\d{1,2}/\d{1,2}/\d{4})\s+(\d{1,2}:\d{2}\s*[AP]M)\b", re.IGNORECASE)

# "Wed Dec 17, 2025 1634" day-of-week style (pharmacy/orders)
RE_DOW_NAMED_HHMM = re.compile(
    r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(\w+\s+\d{1,2},\s+\d{4})\s+(\d{4})\b")

# "Wed Dec 17, 2025 5:00 PM" or "Wed Dec 17, 2025 10:34 AM CST" (imaging/scheduling)
RE_DOW_NAMED_AMPM = re.compile(
    r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(\w+\s+\d{1,2},\s+\d{4})\s+(\d{1,2}:\d{2}\s*[AP]M)", re.IGNORECASE)

# "Collection Time: 12/18/25  9:12 AM" — lab collection hybrid (date MM/DD/YY, time AM/PM)
RE_COLLECTION_TIME = re.compile(
    r"Collection Time:\s*(\d{1,2}/\d{1,2}/\d{2,4})\s+(\d{1,2}:\d{2}\s*[AP]M)", re.IGNORECASE)

# "Date: M/D/YYYY   Time: H:MM AM/PM" — split date/time fields
RE_DATE_TIME_FIELDS = re.compile(
    r"Date:\s*(\d{1,2}/\d{1,2}/\d{4})\s+Time:\s*(\d{1,2}:\d{2}\s*[AP]M)", re.IGNORECASE)

# "Service date: H:MM AM/PM M/D/YYYY" — time-first display format
RE_SERVICE_DATE_TIME_FIRST = re.compile(
    r"Service date:\s*(\d{1,2}:\d{2}\s*[AP]M)\s+(\d{1,2}/\d{1,2}/\d{4})", re.IGNORECASE)

# "Electronically signed by ... on MM/DD/YY at HHMM CST" — military e-sig
RE_ESIG_MILITARY = re.compile(
    r"on\s+(\d{1,2}/\d{1,2}/\d{2,4})\s+at\s+(\d{4})\s+(?:CST|CDT|EST|EDT|PST|PDT)?", re.IGNORECASE)

# "MM/DD/YY HH:MM" admin table with colon variant (e.g. "12/18/25 14:00")
RE_SLASH_COLON_INLINE = re.compile(
    r"\b(\d{1,2}/\d{1,2}/\d{2})\s+(\d{2}:\d{2})\b")

# All Administrations table header
RE_ALL_ADMIN_HEADER = re.compile(
    r"^All Administrations of (.+?)$", re.MULTILINE)

# Administration row: "Given : ... <action_time_mmddyy_hhmm>  <recorded_time>  ..."
RE_ADMIN_ROW_ACTION_TIME = re.compile(
    r"(?:Given|Not Given|New Bag|Rate Change|Bolus)\s*:\s*[^\t]*\t?"
    r".*?(\d{1,2}/\d{1,2}/\d{2,4}\s+\d{4})",
    re.IGNORECASE)


# ============================================================
# Timestamp parsing helpers
# ============================================================

def _parse_date_flex(date_str):
    """Parse a date string in M/DD/YY or M/DD/YYYY format."""
    date_str = date_str.strip()
    for fmt in ("%m/%d/%y", "%m/%d/%Y"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None


def _parse_dt_slash_colon(date_str, time_str):
    """Parse 'MM/DD/YY' + 'HH:MM' -> 'YYYY-MM-DD HH:MM:SS'."""
    d = _parse_date_flex(date_str)
    if d is None:
        return None
    try:
        t = datetime.strptime(time_str.strip(), "%H:%M")
        dt = d.replace(hour=t.hour, minute=t.minute, second=0)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _parse_dt_slash_hhmm(date_str, time_str):
    """Parse 'MM/DD/YY' + 'HHMM' -> 'YYYY-MM-DD HH:MM:SS'."""
    d = _parse_date_flex(date_str)
    if d is None:
        return None
    time_str = time_str.strip()
    if len(time_str) != 4 or not time_str.isdigit():
        return None
    try:
        t = datetime.strptime(time_str, "%H%M")
        dt = d.replace(hour=t.hour, minute=t.minute, second=0)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _parse_named_month_hhmm(date_str, time_str):
    """Parse 'Jan 3, 2026' + '1735' -> 'YYYY-MM-DD HH:MM:SS'."""
    try:
        d = datetime.strptime(date_str.strip(), "%b %d, %Y")
    except ValueError:
        return None
    time_str = time_str.strip()
    if len(time_str) != 4 or not time_str.isdigit():
        return None
    try:
        t = datetime.strptime(time_str, "%H%M")
        dt = d.replace(hour=t.hour, minute=t.minute, second=0)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _parse_ampm_dt(date_str, time_str):
    """Parse 'M/DD/YYYY' + 'H:MM AM' -> 'YYYY-MM-DD HH:MM:SS'."""
    d = _parse_date_flex(date_str)
    if d is None:
        return None
    try:
        t = datetime.strptime(time_str.strip(), "%I:%M %p")
        dt = d.replace(hour=t.hour, minute=t.minute, second=0)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _date_only_iso(date_str):
    """Parse a date string to 'YYYY-MM-DD 00:00:00' (time defaulted)."""
    d = _parse_date_flex(date_str)
    if d is None:
        return None
    return d.strftime("%Y-%m-%d 00:00:00")


def _parse_named_month_ampm(date_str, time_str):
    """Parse 'Jan 3, 2026' + '5:00 PM' -> 'YYYY-MM-DD HH:MM:SS'."""
    try:
        d = datetime.strptime(date_str.strip(), "%b %d, %Y")
    except ValueError:
        return None
    try:
        t = datetime.strptime(time_str.strip(), "%I:%M %p")
        dt = d.replace(hour=t.hour, minute=t.minute, second=0)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _parse_date_ampm_hybrid(date_str, time_str):
    """Parse 'MM/DD/YY' + 'H:MM AM' -> 'YYYY-MM-DD HH:MM:SS' (lab collection hybrid)."""
    d = _parse_date_flex(date_str)
    if d is None:
        return None
    try:
        t = datetime.strptime(time_str.strip(), "%I:%M %p")
        dt = d.replace(hour=t.hour, minute=t.minute, second=0)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


# ============================================================
# Block-level timestamp extraction
# ============================================================

def _is_suspicious_header_dt(header_dt, arrival_dt_str):
    """
    Return True if the block header timestamp should NOT be trusted
    and we should scan the block body for a better one.
    Suspicious = matches arrival exactly, or is midnight on arrival date,
    or is absent.
    """
    if header_dt is None:
        return True
    if arrival_dt_str is None:
        return False
    hd = header_dt.strip()
    ad = arrival_dt_str.strip()
    if hd == ad:
        return True
    # Midnight on arrival date is also suspicious (date-only placeholder)
    arrival_date_prefix = ad[:10]
    if hd == "{} 00:00:00".format(arrival_date_prefix):
        return True
    return False


def _extract_block_ts(body_lines, arrival_dt_str, block_kind=None):
    """
    Scan block body lines for deterministic timestamp patterns.
    Returns (iso_datetime_str_or_None, list_of_warnings).

    Priority (high -> low, full datetime first, then date-only):
      1.  Exam Ended            (radiology - date + time)
      2.  Ordering Date/Time    (MAR/orders - date + time)
      3.  D/C Date/Time         (discontinued meds - date + time)
      4.  Ordered On            (orders - date + time AM/PM)
      5.  Exam End in parens    (radiology - date + time)
      6.  Last Resulted         (radiology - date + time)
      6b. Collection Time       (labs - date + AM/PM time)
      6c. Date/Time split field (date + AM/PM time)
      6d. Service date time-first (AM/PM time + date)
      6e. E-sig military        (MM/DD/YY at HHMM CST)
      7.  Order-history line    (MM/DD/YY HHMM - first occurrence)
      7b. MM/DD/YY HH:MM inline (admin - colon variant)
      7c. M/D/YYYY H:MM AM/PM  (human display)
      7d. Ddd Mon DD, YYYY HHMM (day-of-week military)
      7e. Ddd Mon DD, YYYY H:MM AM/PM (day-of-week display)
      8.  Result Date           (labs - date only)
      9.  Placement date        (devices - date only)
     10.  Removal date          (devices - date only)
     11.  Admission on          (labs - date only)
     12.  Final result date     (RADIOLOGY-only - date only)
     13.  Reading Date fallback (RADIOLOGY-only - date only)
    """
    warnings = []

    # --- Pass 1: high-priority date+time patterns ---
    for line in body_lines:
        m = RE_EXAM_ENDED.search(line)
        if m:
            ts = _parse_dt_slash_colon(m.group(1), m.group(2))
            if ts and ts != arrival_dt_str:
                _ts_count("MM/DD/YY HH:MM (Exam Ended)")
                return ts, warnings

        m = RE_ORDERING_DT.search(line)
        if m:
            ts = _parse_named_month_hhmm(m.group(1), m.group(2))
            if ts and ts != arrival_dt_str:
                _ts_count("Ddd Mon DD, YYYY HHMM (Ordering)")
                return ts, warnings

        m = RE_DC_DT.search(line)
        if m:
            ts = _parse_named_month_hhmm(m.group(1), m.group(2))
            if ts and ts != arrival_dt_str:
                _ts_count("Ddd Mon DD, YYYY HHMM (D/C)")
                return ts, warnings

    # --- Pass 2: medium-priority date+time ---
    for line in body_lines:
        m = RE_ORDERED_ON.search(line)
        if m:
            ts = _parse_ampm_dt(m.group(1), m.group(2))
            if ts and ts != arrival_dt_str:
                _ts_count("M/D/YYYY H:MM AM/PM (Ordered On)")
                return ts, warnings

        m = RE_EXAM_END_PAREN.search(line)
        if m:
            ts = _parse_dt_slash_colon(m.group(1), m.group(2))
            if ts and ts != arrival_dt_str:
                _ts_count("MM/DD/YY HH:MM (Exam End paren)")
                return ts, warnings

        m = RE_LAST_RESULTED.search(line)
        if m:
            ts = _parse_dt_slash_colon(m.group(1), m.group(2))
            if ts and ts != arrival_dt_str:
                _ts_count("MM/DD/YY HH:MM (Last Resulted)")
                return ts, warnings

    # --- Pass 2b: new medium-priority date+time patterns ---
    for line in body_lines:
        # Collection Time: MM/DD/YY H:MM AM/PM (labs)
        m = RE_COLLECTION_TIME.search(line)
        if m:
            ts = _parse_date_ampm_hybrid(m.group(1), m.group(2))
            if ts and ts != arrival_dt_str:
                _ts_count("MM/DD/YY H:MM AM/PM (Collection Time)")
                return ts, warnings

        # Date: M/D/YYYY  Time: H:MM AM/PM (split fields)
        m = RE_DATE_TIME_FIELDS.search(line)
        if m:
            ts = _parse_ampm_dt(m.group(1), m.group(2))
            if ts and ts != arrival_dt_str:
                _ts_count("Date/Time split fields")
                return ts, warnings

        # Service date: H:MM AM/PM M/D/YYYY (time-first)
        m = RE_SERVICE_DATE_TIME_FIRST.search(line)
        if m:
            ts = _parse_ampm_dt(m.group(2), m.group(1))  # note: date=group(2), time=group(1)
            if ts and ts != arrival_dt_str:
                _ts_count("Service date H:MM AM/PM M/D/YYYY (time-first)")
                return ts, warnings

        # E-sig military: "on MM/DD/YY at HHMM CST"
        m = RE_ESIG_MILITARY.search(line)
        if m:
            ts = _parse_dt_slash_hhmm(m.group(1), m.group(2))
            if ts and ts != arrival_dt_str:
                _ts_count("MM/DD/YY at HHMM CST (e-sig military)")
                return ts, warnings

    # --- Pass 3: order-history table lines ---
    for line in body_lines:
        m = RE_ORDER_HIST_LINE.match(line.strip())
        if m:
            ts = _parse_dt_slash_hhmm(m.group(1), m.group(2))
            if ts and ts != arrival_dt_str:
                _ts_count("MM/DD/YY HHMM (order history)")
                return ts, warnings

    # --- Pass 3b: new date+time inline patterns ---
    for line in body_lines:
        # MM/DD/YY HH:MM colon inline
        m = RE_SLASH_COLON_INLINE.search(line)
        if m:
            ts = _parse_dt_slash_colon(m.group(1), m.group(2))
            if ts and ts != arrival_dt_str:
                _ts_count("MM/DD/YY HH:MM (inline colon)")
                return ts, warnings

        # M/D/YYYY H:MM AM/PM human display
        m = RE_HUMAN_DISPLAY_DT.search(line)
        if m:
            ts = _parse_ampm_dt(m.group(1), m.group(2))
            if ts and ts != arrival_dt_str:
                _ts_count("M/D/YYYY H:MM AM/PM (human display)")
                return ts, warnings

        # Ddd Mon DD, YYYY HHMM (day-of-week military)
        m = RE_DOW_NAMED_HHMM.search(line)
        if m:
            ts = _parse_named_month_hhmm(m.group(1), m.group(2))
            if ts and ts != arrival_dt_str:
                _ts_count("Ddd Mon DD, YYYY HHMM (dow military)")
                return ts, warnings

        # Ddd Mon DD, YYYY H:MM AM/PM (day-of-week AM/PM)
        m = RE_DOW_NAMED_AMPM.search(line)
        if m:
            ts = _parse_named_month_ampm(m.group(1), m.group(2))
            if ts and ts != arrival_dt_str:
                _ts_count("Ddd Mon DD, YYYY H:MM AM/PM (dow display)")
                return ts, warnings

        # Generic inline MM/DD/YY HHMM
        m = RE_INLINE_MMDDYY_HHMM.search(line)
        if m:
            ts = _parse_dt_slash_hhmm(m.group(1), m.group(2))
            if ts and ts != arrival_dt_str:
                _ts_count("MM/DD/YY HHMM (generic inline)")
                return ts, warnings

    # --- Pass 4: date-only patterns (time defaults to 00:00) ---
    for line in body_lines:
        m = RE_RESULT_DATE.search(line)
        if m:
            ts = _date_only_iso(m.group(1))
            if ts and ts != arrival_dt_str:
                warnings.append("time_defaulted_0000")
                _ts_count("Result Date (date only)")
                return ts, warnings

        m = RE_PLACEMENT_DATE.search(line)
        if m:
            ts = _date_only_iso(m.group(1))
            if ts and ts != arrival_dt_str:
                warnings.append("time_defaulted_0000")
                _ts_count("Placement date (date only)")
                return ts, warnings

        m = RE_REMOVAL_DATE.search(line)
        if m:
            ts = _date_only_iso(m.group(1))
            if ts and ts != arrival_dt_str:
                warnings.append("time_defaulted_0000")
                _ts_count("Removal date (date only)")
                return ts, warnings

        m = RE_ADMISSION_ON.search(line)
        if m:
            ts = _date_only_iso(m.group(1))
            if ts and ts != arrival_dt_str:
                warnings.append("time_defaulted_0000")
                _ts_count("Admission on (date only)")
                return ts, warnings

    # --- Pass 5: RADIOLOGY-only date fallbacks (time -> 0000) ---
    if block_kind == "RADIOLOGY":
        # 5a: "Final result" followed by date
        for line in body_lines:
            m = RE_FINAL_RESULT_DATE.search(line)
            if m:
                ts = _date_only_iso(m.group("date"))
                if ts and ts != arrival_dt_str:
                    warnings.append("time_defaulted_0000")
                    _ts_count("Final result date (RADIOLOGY)")
                    return ts, warnings

        # 5b: Standalone date within ~40 lines after a "Reading Physician/Date" header
        reading_header_idx = None
        for i, line in enumerate(body_lines):
            if RE_READING_DATE_HEADER.search(line):
                reading_header_idx = i
            elif reading_header_idx is not None and (i - reading_header_idx) <= 40:
                m = RE_STANDALONE_DATE.search(line)
                if m:
                    ts = _date_only_iso(m.group("date"))
                    if ts and ts != arrival_dt_str:
                        warnings.append("time_defaulted_0000")
                        _ts_count("Reading Date (RADIOLOGY)")
                        return ts, warnings

    # Nothing found
    _ts_fail()
    warnings.append("ts_missing")
    return None, warnings


# ============================================================
# Data models
# ============================================================

@dataclass(frozen=True)
class EvidenceItem:
    idx: int
    kind: str
    datetime: Optional[str]   # ISO-like or None if no deterministic timestamp
    line_start: int           # 1-based
    line_end: int             # 1-based, inclusive
    text: str
    warnings: Tuple[str, ...] = ()  # e.g. ("ts_missing",) or ("time_defaulted_0000",)
    header_dt: Optional[str] = None  # block header datetime (preserved even if suspicious)


def _sha256_text(s):
    h = hashlib.sha256()
    h.update(s.encode("utf-8", errors="replace"))
    return h.hexdigest()


def _slugify(name):
    # Deterministic and filesystem-friendly.
    s = name.strip().replace(" ", "_")
    s = re.sub(r"[^A-Za-z0-9_]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "UNKNOWN_PATIENT"


def _read_lines(path):
    # Epic exports can have odd characters; keep it resilient.
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def _extract_header(lines, scan_limit=400):
    """
    Extract simple KEY: VALUE headers from the first N lines.
    """
    header = {}
    for raw in lines[:scan_limit]:
        m = RE_HEADER_KV.match(raw)
        if not m:
            continue
        k, v = m.group(1).strip(), m.group(2).strip()
        # Keep first occurrence (deterministic).
        if k not in header and v != "":
            header[k] = v
    return header


# ============================================================
# Core parser
# ============================================================

def _parse_items(lines, arrival_dt_str=None):
    """
    Split the file into blocks delimited by bracket tags.
    For blocks whose header timestamp is suspicious (equals arrival or is
    absent), scan the body for deterministic inline timestamps.
    If no deterministic timestamp is found, datetime is set to None.
    """
    items = []
    current_kind = None
    current_header_dt = None
    current_start = None
    buf = []

    def flush(end_line_1based):
        nonlocal current_kind, current_header_dt, current_start, buf
        if current_kind is None or current_start is None:
            buf = []
            return

        text = "\n".join(buf).strip("\n")
        warnings = []
        chosen_dt = current_header_dt

        if _is_suspicious_header_dt(current_header_dt, arrival_dt_str):
            # Block header ts is arrival or absent -> scan body for real ts
            internal_dt, scan_warnings = _extract_block_ts(buf, arrival_dt_str, block_kind=current_kind)
            warnings.extend(scan_warnings)
            if internal_dt is not None:
                chosen_dt = internal_dt
            else:
                # No deterministic internal ts found -> leave null
                chosen_dt = None
                if "ts_missing" not in warnings:
                    warnings.append("ts_missing")

        items.append(
            EvidenceItem(
                idx=len(items),
                kind=current_kind,
                datetime=chosen_dt,
                line_start=current_start,
                line_end=end_line_1based,
                text=text,
                warnings=tuple(warnings),
                header_dt=current_header_dt,
            )
        )
        # reset
        current_kind = None
        current_header_dt = None
        current_start = None
        buf = []

    for i0, raw in enumerate(lines):
        line_no = i0 + 1  # 1-based

        # Check for standard block start: [KIND] YYYY-MM-DD HH:MM:SS
        m = RE_BLOCK_STANDARD.match(raw)
        if m:
            if current_kind is not None:
                flush(end_line_1based=line_no - 1)
            current_kind = m.group("kind")
            current_header_dt = m.group("dt")
            _ts_count("YYYY-MM-DD HH:MM:SS (block header)")
            current_start = line_no
            buf = [raw]  # keep the header line inside the block text (auditable)
            continue

        # Check for REMOVED block start: [REMOVED] <description>
        m = RE_BLOCK_REMOVED.match(raw)
        if m:
            if current_kind is not None:
                flush(end_line_1based=line_no - 1)
            current_kind = "REMOVED"
            current_header_dt = None  # No ISO timestamp in REMOVED headers
            current_start = line_no
            buf = [raw]
            continue

        if current_kind is not None:
            buf.append(raw)

    # flush trailing block
    if current_kind is not None:
        flush(end_line_1based=len(lines))

    return items


def _build_evidence_object(src_path, patient_slug):
    _reset_ts_counts()  # fresh counters per patient
    lines = _read_lines(src_path)
    raw_text = "\n".join(lines)

    header = _extract_header(lines)

    # Arrival datetime needed for suspicious-header detection
    arrival_dt = header.get("ARRIVAL_TIME")
    items = _parse_items(lines, arrival_dt_str=arrival_dt)

    # Strictly "no inference": only set these meta fields if explicit header exists
    patient_id = header.get("PATIENT_ID")
    patient_name = header.get("PATIENT_NAME")
    trauma_category = header.get("TRAUMA_CATEGORY")
    dob = header.get("DOB")

    obj = {
        "meta": {
            "artifact": "patient_evidence_v1",
            "version": "1.1.0",
            "created_at_utc": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            "source_file": str(src_path),
            "source_file_sha256": _sha256_text(raw_text),
            "line_count": len(lines),
            "patient_slug": patient_slug,
            "patient_id": patient_id or "DATA_NOT_AVAILABLE",
            "patient_name": patient_name or "DATA_NOT_AVAILABLE",
            "dob": dob or "DATA_NOT_AVAILABLE",
            "arrival_datetime": arrival_dt or "DATA_NOT_AVAILABLE",
            "trauma_category": trauma_category or "DATA_NOT_AVAILABLE",
            "timezone": "America/Chicago",
        },
        "header": header,  # full header KV (auditable)
        "items": [asdict(it) for it in items],
        # Keep raw lines available for debugging without rereading file.
        "raw": {
            "first_50_lines": lines[:50],
        },
        "timestamp_format_counts": get_timestamp_format_counts(),
    }
    return obj


def main():
    ap = argparse.ArgumentParser(
        description="CerebralOS patient .txt -> evidence JSON (timeline-ready)")
    ap.add_argument("--in", dest="inp", required=True,
                    help="Path to patient .txt file")
    ap.add_argument(
        "--out-dir",
        dest="out_dir",
        default="outputs/evidence",
        help="Base output directory (default: outputs/evidence)",
    )
    ap.add_argument(
        "--patient",
        dest="patient",
        default=None,
        help="Optional patient slug override (default: derived from filename)",
    )
    ap.add_argument(
        "--out",
        dest="out",
        default=None,
        help="Optional explicit output file path (overrides --out-dir)",
    )

    args = ap.parse_args()
    src_path = Path(args.inp).expanduser().resolve()
    if not src_path.exists():
        raise SystemExit("Input file not found: {}".format(src_path))

    # Determine patient slug deterministically
    if args.patient:
        patient_slug = _slugify(args.patient)
    else:
        patient_slug = _slugify(src_path.stem)

    evidence = _build_evidence_object(src_path, patient_slug)

    if args.out:
        out_path = Path(args.out).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        base = Path(args.out_dir).expanduser().resolve()
        out_path = base / patient_slug / "patient_evidence_v1.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)

    out_path.write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")

    # ---- Sanity-check output ----
    all_items = evidence.get("items") or []
    n_total = len(all_items)
    n_with_ts = sum(1 for it in all_items if it.get("datetime") is not None)
    n_missing_ts = n_total - n_with_ts
    unique_dates = set()
    for it in all_items:
        dt = it.get("datetime")
        if dt:
            unique_dates.add(dt[:10])  # YYYY-MM-DD portion

    print("OK  Wrote evidence: {}".format(out_path))
    print("   items total:       {}".format(n_total))
    print("   items with ts:     {}".format(n_with_ts))
    print("   items missing ts:  {}".format(n_missing_ts))
    print("   unique dates:      {}  {}".format(len(unique_dates), sorted(unique_dates)))
    print("   patient_id:        {}".format(evidence["meta"].get("patient_id")))
    print("   arrival_datetime:  {}".format(evidence["meta"].get("arrival_datetime")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
