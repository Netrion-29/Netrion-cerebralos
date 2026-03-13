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

# ── Supplemental: RT/IS order and flowsheet detection ──────

# IS order detail page header:
#   "INCENTIVE SPIROMETER Q2H While awake [RT16] (Order 466185479)"
RE_IS_ORDER_PAGE = re.compile(
    r"^INCENTIVE\s+SPIROMETER\b.*\[RT\d+\]\s*\(Order\s+\d+\)",
    re.IGNORECASE,
)

# IS flowsheet header: standalone "Incentive Spirometry"
RE_IS_FLOWSHEET_HDR = re.compile(
    r"^Incentive\s+Spirometry\s*$",
    re.IGNORECASE,
)

# IS flowsheet data row prefix: "MM/DD HHMM"
RE_IS_FLOWSHEET_ROW = re.compile(r"^\d{2}/\d{2}\s+\d{4}\b")

# Order page date field: "Date: M/D/YYYY"
RE_ORDER_PAGE_DATE = re.compile(r"Date:\s*(\d{1,2}/\d{1,2}/\d{4})")

# Supplemental: Spine Clearance order detail inline line
# "Spine Clearance Cervical Spine Clearance: Yes; Thoracic/Spine Lumbar Clearance: No [NUR1015] (Order 466671395)"
RE_SPINE_CLEARANCE_INLINE = re.compile(
    r"^Spine Clearance\s+Cervical Spine Clearance:\s*(?:Yes|No)",
    re.IGNORECASE,
)

# "Ordered On" timestamp in order detail pages: "M/D/YYYY HHMM" (military, no colon)
RE_ORDERED_ON_HHMM = re.compile(
    r"^\s*(\d{1,2}/\d{1,2}/\d{2,4})\s+(\d{4})\s",
)


# ============================================================
# New-format (Date of Service) -- regex and mapping
# ============================================================

# Date of Service boundary: "Date of Service: MM/DD/YY HHMM"
# NOTE: must NOT match "Date of Service:  M/D/YYYY" (embedded in note bodies,
#       extra space, 4-digit year, no military time).
RE_DOS_BOUNDARY = re.compile(
    r"^Date of Service:\s+(\d{1,2}/\d{1,2}/\d{2})\s+(\d{4})\s*$"
)

# Note-category label (3 lines above DoS boundary) → evidence KIND
_NOTE_CATEGORY_MAP: Dict[str, str] = {
    "H&P":                                  "TRAUMA_HP",
    "Progress Notes":                       "PHYSICIAN_NOTE",
    "Consults":                             "CONSULT_NOTE",
    "ED Provider Notes":                    "ED_NOTE",
    "ED Notes":                             "ED_NURSING",
    "Plan of Care":                         "CASE_MGMT",
    "Op Note":                              "OP_NOTE",
    "Triage Assessment":                    "TRIAGE",
    "Discharge Summary":                    "DISCHARGE_SUMMARY",
    "Procedures":                           "PROCEDURE",
    "Pre-Procedure Note":                   "PRE_PROCEDURE",
    "Significant Event":                    "SIGNIFICANT_EVENT",
    "Anesthesia Follow Up Evaluation":      "ANESTHESIA_FOLLOWUP",
    "Anesthesia Postprocedure Evaluation":  "ANESTHESIA_POSTPROCEDURE",
    "Anesthesia Procedure Notes":           "ANESTHESIA_PROCEDURE",
    "Anesthesia Preprocedure Evaluation":   "ANESTHESIA_PREPROCEDURE",
    "Anesthesia Consult":                   "ANESTHESIA_CONSULT",
}

# Radiology study name prefixes for backward scan
_RAD_STUDY_PREFIXES = (
    "CT ", "XR ", "US ", "MR ", "MRI ", "PET ", "DEXA ",
    "FL ", "NM ", "FLUORO ", "DSA ", "IR ",
)

# Chronological results-summary timestamp: "MM/DD/YY HH:MM" (colon, standalone)
RE_RESULTS_TS = re.compile(r"^(\d{2}/\d{2}/\d{2})\s+(\d{2}:\d{2})$")

# History-section markers that precede duplicate note blocks in Epic exports.
# If such a marker appears between two consecutive DoS boundaries, the second
# boundary is a Routing/Revision History copy and should be skipped.
RE_HISTORY_MARKER = re.compile(
    r"^(?:Routing History|Revision History)", re.IGNORECASE,
)


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


def _resolve_flowsheet_year(mm_dd, arrival_dt_str):
    """Resolve year for a MM/DD flowsheet date using arrival context.

    Flowsheet rows have MM/DD without year.  If the flowsheet month is
    earlier than the arrival month the data must be in the next calendar
    year (e.g. admission 12/29/2025 → flowsheet 01/07 → 2026).
    """
    if not arrival_dt_str:
        return None
    try:
        arr = datetime.strptime(arrival_dt_str[:10], "%Y-%m-%d")
    except ValueError:
        return None
    try:
        month = int(mm_dd[:2])
    except (ValueError, IndexError):
        return None
    if month < arr.month:
        return arr.year + 1
    return arr.year


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
# Format detection
# ============================================================

def _detect_format(lines, scan_limit=500):
    """Return 'bracket' (old) or 'dos' (new Date-of-Service) or 'unknown'."""
    for line in lines[:scan_limit]:
        if RE_BLOCK_STANDARD.match(line):
            return "bracket"
    for line in lines[:scan_limit]:
        if RE_DOS_BOUNDARY.match(line.strip()):
            return "dos"
    return "unknown"


# ============================================================
# New-format header extraction
# ============================================================

def _extract_header_dos(lines):
    """
    Extract metadata from new-format (Date of Service) files.
    Line 1: patient name, Line 2: "NN year old male/female", Line 3: DOB.
    ADT Events table: first 'Admission' row → ARRIVAL_TIME,
                      last 'Discharge' row  → DISCHARGE_DATETIME.
    """
    header: Dict[str, str] = {}
    # Line 1: patient name
    if len(lines) >= 1 and lines[0].strip():
        header["PATIENT_NAME"] = lines[0].strip()
    # Line 2: age/sex  ("67 year old male")
    if len(lines) >= 2:
        m = re.match(r"(\d+)\s+year\s+old\s+(\w+)", lines[1].strip(), re.IGNORECASE)
        if m:
            header["AGE"] = m.group(1)
            header["SEX"] = m.group(2).capitalize()
    # Line 3: DOB
    if len(lines) >= 3 and re.match(r"\d{1,2}/\d{1,2}/\d{4}", lines[2].strip()):
        header["DOB"] = lines[2].strip()
    # ADT Events: first "Admission" row → ARRIVAL_TIME,
    #             last  "Discharge" row  → DISCHARGE_DATETIME
    adt_re = re.compile(r"^(\d{1,2}/\d{1,2}/\d{2})\s+(\d{4})\s+")
    for line in lines[:60]:
        if "Admission" in line:
            m = adt_re.match(line.strip())
            if m:
                ts = _parse_dt_slash_hhmm(m.group(1), m.group(2))
                if ts:
                    header["ARRIVAL_TIME"] = ts
            break
    # Scan for last Discharge row (there may be multiple; last wins).
    # Only rows with event column exactly "Discharge" qualify —
    # "Transfer Out", "Transfer In" etc. are excluded by the keyword check.
    discharge_ts: Optional[str] = None
    for line in lines[:60]:
        if "Discharge" in line and "Transfer" not in line:
            m = adt_re.match(line.strip())
            if m:
                ts = _parse_dt_slash_hhmm(m.group(1), m.group(2))
                if ts:
                    discharge_ts = ts  # last wins
    if discharge_ts:
        header["DISCHARGE_DATETIME"] = discharge_ts
    return header


# ============================================================
# Sex/gender HPI fallback extraction
# ============================================================

# Matches: "65 y.o. female", "72 yo male", "55-year-old female",
#          "60 year old male", "86 year old male patient who..."
_RE_HPI_SEX = re.compile(
    r"\b(\d+)[\s\-]*(?:y\.?o\.?|year[\s\-]*old)\s+(male|female)\b",
    re.IGNORECASE,
)

# Lines that mention sex-related words but are NOT patient sex.
_RE_SEX_NOISE = re.compile(
    r"Partners:\s*(?:Male|Female)|Sexual\s+activity|Sexually\s+Abused",
    re.IGNORECASE,
)


def _extract_sex_hpi_fallback(lines, scan_limit=60):
    """
    Scan the first *scan_limit* lines for an HPI-style age/sex phrase.

    Returns (sex, line_number) or (None, None).
    *line_number* is a 0-based index into the provided *lines* list.
    Guardrails: skips lines matching _RE_SEX_NOISE.
    """
    for idx, raw in enumerate(lines[:scan_limit]):
        stripped = raw.strip()
        if not stripped:
            continue
        if _RE_SEX_NOISE.search(stripped):
            continue
        m = _RE_HPI_SEX.search(stripped)
        if m:
            return m.group(2).capitalize(), idx
    return None, None


# ============================================================
# New-format item parsing (DoS boundaries + supplemental)
# ============================================================

def _parse_items_dos(lines, arrival_dt_str=None):
    """
    Parse new-format files:
    1. Date-of-Service boundaries → clinical note items
    2. Supplemental sections → RADIOLOGY / LAB / MAR items

    The last clinical note's body is trimmed to exclude supplemental data
    so that vitals/labs are not duplicated from note bodies.

    Dedup:
    - Phase 1b: skip DoS boundaries preceded by "Routing History" or
      "Revision History" markers (Epic export duplicates).
    - Phase 2b: content-hash dedup on (kind, datetime, text_hash) as
      defense-in-depth for any remaining duplicates.
    """
    items: List[EvidenceItem] = []

    # ── Phase 1: locate all DoS boundaries ──────────────────
    boundaries: List[Tuple[int, Optional[str], str]] = []
    for i, line in enumerate(lines):
        m = RE_DOS_BOUNDARY.match(line.strip())
        if m:
            dos_dt = _parse_dt_slash_hhmm(m.group(1), m.group(2))
            if dos_dt:
                _ts_count("MM/DD/YY HHMM (DoS header)")
            cat_line = lines[i - 3].strip() if i >= 3 else ""
            cat_clean = re.sub(
                r"\s+(This note has been|The patient can).*$", "", cat_line,
            ).strip()
            kind = _NOTE_CATEGORY_MAP.get(cat_clean, "NOTE")
            boundaries.append((i, dos_dt, kind))

    if not boundaries:
        return items

    # ── Phase 1b: filter out history-section duplicates ─────
    # If "Routing History" or "Revision History" appears between two
    # consecutive DoS boundaries, the later one is a duplicate.
    filtered: List[Tuple[int, Optional[str], str]] = [boundaries[0]]
    for b_idx in range(1, len(boundaries)):
        prev_dos_idx = boundaries[b_idx - 1][0]
        curr_dos_idx = boundaries[b_idx][0]
        # Scan lines between the previous DoS line and this one
        is_history_copy = False
        for scan_i in range(prev_dos_idx + 1, curr_dos_idx):
            if RE_HISTORY_MARKER.match(lines[scan_i].strip()):
                is_history_copy = True
                break
        if not is_history_copy:
            filtered.append(boundaries[b_idx])
    boundaries = filtered

    # ── Phase 2: create clinical-note items ─────────────────
    seen_hashes: set = set()   # (kind, datetime, text_hash) for content dedup
    for b_idx, (dos_idx, dos_dt, kind) in enumerate(boundaries):
        body_start = dos_idx + 1
        if b_idx + 1 < len(boundaries):
            # End 7 lines before next DoS (skip provider header block)
            body_end = max(body_start, boundaries[b_idx + 1][0] - 7)
        else:
            # Last note: extend to EOF initially; Phase 4 may trim.
            body_end = len(lines)

        text = "\n".join(lines[body_start:body_end]).strip("\n")

        # Phase 2b: content-hash dedup (defense-in-depth)
        text_hash = _sha256_text(text)
        dedup_key = (kind, dos_dt, text_hash)
        if dedup_key in seen_hashes:
            continue
        seen_hashes.add(dedup_key)

        warns: List[str] = []
        if dos_dt is None:
            warns.append("ts_missing")

        items.append(
            EvidenceItem(
                idx=len(items),
                kind=kind,
                datetime=dos_dt,
                line_start=dos_idx + 1,   # 1-based
                line_end=body_end,
                text=text,
                warnings=tuple(warns),
                header_dt=dos_dt,
            )
        )

    # ── Phase 3: supplemental items (RADIOLOGY / LAB / MAR) ─
    last_dos_idx = boundaries[-1][0]
    supp_items = _parse_supplemental_dos(
        lines, last_dos_idx, arrival_dt_str, start_idx=len(items),
    )

    # ── Phase 4: trim last note body if supplemental overlaps ─
    if supp_items and items:
        first_supp_line = min(it.line_start for it in supp_items)
        last_note = items[-1]
        if first_supp_line <= last_note.line_end:
            trim_end = first_supp_line - 1   # 1-based line before supp
            trimmed_text = "\n".join(
                lines[last_note.line_start - 1 : max(0, trim_end - 1)]
            ).strip("\n")
            items[-1] = EvidenceItem(
                idx=last_note.idx,
                kind=last_note.kind,
                datetime=last_note.datetime,
                line_start=last_note.line_start,
                line_end=max(last_note.line_start, trim_end),
                text=trimmed_text,
                warnings=last_note.warnings,
                header_dt=last_note.header_dt,
            )

    items.extend(supp_items)
    return items


def _parse_supplemental_dos(lines, last_dos_idx, arrival_dt_str, start_idx=0):
    """
    Parse supplemental sections after the last clinical note for:
      - RADIOLOGY reports ("Narrative & Impression" blocks)
      - LAB results ("Specimen Collected:" pages + chronological summary)
      - MAR records ("All Administrations of" sections)
      - RT_ORDER: IS order detail pages ("INCENTIVE SPIROMETER ... [RTnn]")
      - IS_FLOWSHEET: Incentive Spirometry flowsheet data (tabular)
    """
    items: List[EvidenceItem] = []
    idx = start_idx
    n = len(lines)
    scan_start = last_dos_idx + 1
    claimed: set = set()  # line indices already assigned to an item

    # ── RADIOLOGY: "Narrative & Impression" blocks ──────────
    for i in range(scan_start, n):
        if lines[i].strip() != "Narrative & Impression":
            continue
        if i in claimed:
            continue

        # Backwards scan for study name (CT / XR / US / MR …)
        study_name = ""
        study_line = i
        for j in range(i - 1, max(scan_start, i - 30), -1):
            sl = lines[j].strip()
            if any(sl.upper().startswith(p) for p in _RAD_STUDY_PREFIXES):
                study_name = sl.split("Order:")[0].strip()
                study_line = j
                break

        # Forward scan: collect until end-of-report markers
        report_end = i + 1
        for j in range(i + 1, min(n, i + 500)):
            rl = lines[j].strip()
            if rl in (
                "Reading Physician Information",
                "Signing Physician Information",
                "Imaging Information",
            ):
                report_end = j
                break
            if rl.startswith("Exam Ended:"):
                report_end = j + 1
                break
            report_end = j + 1

        report_text = (
            (study_name + "\n" if study_name else "")
            + "\n".join(lines[i + 1 : report_end]).strip()
        )

        # Timestamp: prefer Exam Ended, then Final result date
        rad_dt: Optional[str] = None
        for j in range(i, report_end):
            m = RE_EXAM_ENDED.search(lines[j])
            if m:
                rad_dt = _parse_dt_slash_colon(m.group(1), m.group(2))
                if rad_dt:
                    _ts_count("MM/DD/YY HH:MM (Exam Ended)")
                    break
        if rad_dt is None:
            for j in range(max(scan_start, study_line - 10), report_end):
                m = RE_FINAL_RESULT_DATE.search(lines[j])
                if m:
                    rad_dt = _date_only_iso(m.group("date"))
                    if rad_dt:
                        _ts_count("Final result date (RADIOLOGY)")
                        break

        warns: List[str] = []
        if rad_dt is None:
            _ts_fail()
            warns.append("ts_missing")
        elif "00:00:00" in rad_dt:
            warns.append("time_defaulted_0000")

        items.append(
            EvidenceItem(
                idx=idx, kind="RADIOLOGY", datetime=rad_dt,
                line_start=study_line + 1, line_end=report_end,
                text=report_text, warnings=tuple(warns), header_dt=rad_dt,
            )
        )
        idx += 1
        for j in range(study_line, report_end):
            claimed.add(j)

    # ── LAB: "Specimen Collected:" pages ────────────────────
    for i in range(scan_start, n):
        stripped = lines[i].strip()
        if "Specimen Collected:" not in stripped:
            continue
        if i in claimed:
            continue

        # Backward: find start of this lab result block
        lab_start = i
        for j in range(i - 1, max(scan_start, i - 100), -1):
            sl = lines[j].strip()
            if j in claimed:
                lab_start = j + 1
                break
            if sl.startswith("Contains abnormal") or "(Order" in sl or sl == "Component":
                lab_start = j
                break

        lab_end = i + 1  # include Specimen Collected line
        lab_text = "\n".join(lines[lab_start:lab_end]).strip()

        # Timestamp from "Specimen Collected: MM/DD/YY HH:MM CST"
        lab_dt: Optional[str] = None
        m = re.search(
            r"Specimen Collected:\s*(\d{1,2}/\d{1,2}/\d{2,4})\s+(\d{1,2}:\d{2})",
            stripped,
        )
        if m:
            lab_dt = _parse_dt_slash_colon(m.group(1), m.group(2))
            if lab_dt:
                _ts_count("MM/DD/YY HH:MM (Specimen Collected)")

        warns = []
        if lab_dt is None:
            _ts_fail()
            warns.append("ts_missing")

        items.append(
            EvidenceItem(
                idx=idx, kind="LAB", datetime=lab_dt,
                line_start=lab_start + 1, line_end=lab_end,
                text=lab_text, warnings=tuple(warns), header_dt=lab_dt,
            )
        )
        idx += 1
        for j in range(lab_start, lab_end):
            claimed.add(j)

    # ── LAB: chronological results-summary groups ───────────
    # Standalone "MM/DD/YY HH:MM" lines followed by lab values.
    # These may repeat 2-3 times (different views); deduplicate.
    seen_lab_ts: set = set()
    for i in range(scan_start, n):
        if i in claimed:
            continue
        stripped = lines[i].strip()
        m = RE_RESULTS_TS.match(stripped)
        if not m:
            continue

        ts = _parse_dt_slash_colon(m.group(1), m.group(2))
        if ts is None or ts in seen_lab_ts:
            continue

        # Collect subsequent non-blank lines until next timestamp or blank gap
        has_lab_value = False
        group_end = i + 1
        for j in range(i + 1, min(n, i + 50)):
            jl = lines[j].strip()
            if jl == "":
                group_end = j
                break
            if RE_RESULTS_TS.match(jl):
                group_end = j
                break
            # Distinguish lab values from radiology refs (": Rpt")
            if ": Rpt" not in jl and ":" in jl:
                has_lab_value = True
            group_end = j + 1

        if not has_lab_value:
            continue  # skip radiology-reference-only groups

        seen_lab_ts.add(ts)
        lab_text = "\n".join(lines[i:group_end]).strip()

        items.append(
            EvidenceItem(
                idx=idx, kind="LAB", datetime=ts,
                line_start=i + 1, line_end=group_end,
                text=lab_text, warnings=(), header_dt=ts,
            )
        )
        _ts_count("MM/DD/YY HH:MM (results summary)")
        idx += 1
        for j in range(i, group_end):
            claimed.add(j)

    # ── MAR: "All Administrations of" blocks ────────────────
    admin_indices = []
    for i in range(scan_start, n):
        if lines[i].strip().startswith("All Administrations of") and i not in claimed:
            admin_indices.append(i)

    for ai, mar_start in enumerate(admin_indices):
        mar_end = min(n, mar_start + 200)
        for j in range(mar_start + 1, min(n, mar_start + 200)):
            sl = lines[j].strip()
            if sl.startswith("All Administrations of") or sl.startswith("Warnings Override"):
                mar_end = j
                break

        mar_text = "\n".join(lines[mar_start:mar_end]).strip()

        # Timestamp from admin record lines
        mar_dt: Optional[str] = None
        for j in range(mar_start, mar_end):
            m = RE_ADMIN_ROW_ACTION_TIME.search(lines[j])
            if m:
                ts_str = m.group(1).strip()
                parts = ts_str.split()
                if len(parts) >= 2:
                    mar_dt = _parse_dt_slash_hhmm(parts[0], parts[1][:4])
                    if mar_dt:
                        _ts_count("MM/DD/YY HHMM (MAR admin)")
                        break

        warns = []
        if mar_dt is None:
            _ts_fail()
            warns.append("ts_missing")

        items.append(
            EvidenceItem(
                idx=idx, kind="MAR", datetime=mar_dt,
                line_start=mar_start + 1, line_end=mar_end,
                text=mar_text, warnings=tuple(warns), header_dt=mar_dt,
            )
        )
        idx += 1

    # ── RT_ORDER: IS order detail pages ───────────────────────
    for i in range(scan_start, n):
        stripped = lines[i].strip()
        if i in claimed:
            continue
        if not RE_IS_ORDER_PAGE.match(stripped):
            continue

        block_start = i
        block_end = min(n, i + 120)
        for j in range(i + 1, min(n, i + 120)):
            jl = lines[j].strip()
            if jl == "Link to Procedure Log":
                block_end = j
                break
            # Safety: stop at next IS order header
            if j > i + 5 and RE_IS_ORDER_PAGE.match(jl):
                block_end = j
                break

        block_text = "\n".join(lines[block_start:block_end]).strip()

        # Timestamp from "Date: MM/DD/YYYY" in the block header area
        rt_dt: Optional[str] = None
        for j in range(block_start, min(block_end, block_start + 20)):
            dm = RE_ORDER_PAGE_DATE.search(lines[j])
            if dm:
                rt_dt = _date_only_iso(dm.group(1))
                if rt_dt:
                    _ts_count("M/D/YYYY (RT_ORDER Date)")
                    break

        warns: List[str] = []
        if rt_dt is None:
            _ts_fail()
            warns.append("ts_missing")
        elif "00:00:00" in rt_dt:
            warns.append("time_defaulted_0000")

        items.append(
            EvidenceItem(
                idx=idx, kind="RT_ORDER", datetime=rt_dt,
                line_start=block_start + 1, line_end=block_end,
                text=block_text, warnings=tuple(warns), header_dt=rt_dt,
            )
        )
        idx += 1
        for j in range(block_start, block_end):
            claimed.add(j)

    # ── IS_FLOWSHEET: Incentive Spirometry flowsheet data ─────
    for i in range(scan_start, n):
        stripped = lines[i].strip()
        if i in claimed:
            continue
        if not RE_IS_FLOWSHEET_HDR.match(stripped):
            continue

        block_start = i
        block_end = i + 1
        found_col_header = False

        for j in range(i + 1, min(n, i + 500)):
            jl = lines[j].strip()
            # Section boundary: next flowsheet group
            if re.match(r"^(?:Intake|Output)\b", jl, re.IGNORECASE):
                break
            if jl.startswith(("Height and Weight", "Emesis Documentation")):
                break
            if "**" in jl:
                found_col_header = True
            block_end = j + 1

        if not found_col_header:
            continue  # Not real flowsheet data

        block_text = "\n".join(lines[block_start:block_end]).strip()

        # Timestamp: first data row (most recent), resolve year
        fs_dt: Optional[str] = None
        for j in range(block_start, block_end):
            dm = RE_IS_FLOWSHEET_ROW.match(lines[j].strip())
            if dm:
                row_str = lines[j].strip()
                mm_dd = row_str[:5]   # "01/07"
                hhmm = row_str[6:10]  # "1401"
                year = _resolve_flowsheet_year(mm_dd, arrival_dt_str)
                if year:
                    date_str = "{}/{:02d}".format(mm_dd, year % 100)
                    fs_dt = _parse_dt_slash_hhmm(date_str, hhmm)
                    if fs_dt:
                        _ts_count("MM/DD HHMM (IS_FLOWSHEET row)")
                        break

        warns = []
        if fs_dt is None:
            _ts_fail()
            warns.append("ts_missing")

        items.append(
            EvidenceItem(
                idx=idx, kind="IS_FLOWSHEET", datetime=fs_dt,
                line_start=block_start + 1, line_end=block_end,
                text=block_text, warnings=tuple(warns), header_dt=fs_dt,
            )
        )
        idx += 1
        for j in range(block_start, block_end):
            claimed.add(j)

    # ── SBIRT_FLOWSHEET: Flowsheet History with SBIRT questions ──
    # "Flowsheet History" sections that contain SBIRT screening
    # questions (e.g. "Does the patient have an injury?",
    # "Have you used drugs…", "Audit-C Score").  Emitted as
    # NURSING_NOTE so the feature-layer SBIRT scanner picks them up.
    _SBIRT_Q_SIGNATURES = (
        "Does the patient have an injury",
        "Have you used drugs other than",
        "Do you drink alcohol",
        "Audit-C Score",
        "Audit C Score",
    )
    for i in range(scan_start, n):
        if i in claimed:
            continue
        stripped = lines[i].strip()
        if stripped != "Flowsheet History":
            continue

        # Find a tab-delimited header row containing SBIRT questions
        hdr_idx: Optional[int] = None
        for j in range(i + 1, min(n, i + 15)):
            if j in claimed:
                continue
            jl = lines[j]
            if "\t" not in jl:
                continue
            if any(sig in jl for sig in _SBIRT_Q_SIGNATURES):
                hdr_idx = j
                break

        if hdr_idx is None:
            continue  # not an SBIRT-containing flowsheet section

        # Collect data rows immediately after the header until blank
        # or non-data line (e.g. "User Key").
        block_start = hdr_idx
        block_end = hdr_idx + 1
        sbirt_dt: Optional[str] = None
        for j in range(hdr_idx + 1, min(n, hdr_idx + 30)):
            jl = lines[j].strip()
            if not jl:
                block_end = j
                break
            # Data rows start with MM/DD/YY
            if re.match(r"\d{1,2}/\d{1,2}/\d{2,4}", jl):
                block_end = j + 1
                if sbirt_dt is None:
                    parts = jl.split("\t")[0].strip().split()
                    if len(parts) >= 2:
                        sbirt_dt = _parse_dt_slash_hhmm(parts[0], parts[1][:4])
                        if sbirt_dt:
                            _ts_count("MM/DD/YY HHMM (SBIRT flowsheet)")
                continue
            # Stop at non-data lines like "User Key"
            block_end = j
            break

        block_text = "\n".join(lines[block_start:block_end]).strip()

        warns: List[str] = []
        if sbirt_dt is None:
            _ts_fail()
            warns.append("ts_missing")

        items.append(
            EvidenceItem(
                idx=idx, kind="NURSING_NOTE", datetime=sbirt_dt,
                line_start=block_start + 1, line_end=block_end,
                text=block_text, warnings=tuple(warns), header_dt=sbirt_dt,
            )
        )
        idx += 1
        for j in range(i, block_end):
            claimed.add(j)

    # ── NURSING_ORDER: Spine Clearance order detail pages ─────
    # In DoS-format files, Epic "Spine Clearance" order detail pages
    # appear in the supplemental region.  The inline summary line
    # ("Spine Clearance Cervical Spine Clearance: Yes; ...") is
    # followed by metadata and an "Order Questions" block with the
    # same answers.  Capture from the inline line through the next
    # "Print Order Requisition" marker so the downstream spine-
    # clearance feature extractor can parse both inline and
    # structured formats, plus the "Ordered On" timestamp.
    for i in range(scan_start, n):
        if i in claimed:
            continue
        stripped = lines[i].strip()
        if not RE_SPINE_CLEARANCE_INLINE.match(stripped):
            continue

        block_start = i
        block_end = i + 1

        # Scan forward through the order detail block.
        # Stop at the second "Print Order Requisition" (first ends
        # the inline summary block; second ends the OQ block) or
        # at another spine-clearance inline line.
        pror_count = 0
        for j in range(i + 1, min(n, i + 100)):
            jl = lines[j].strip()
            # Another spine clearance order starts → stop
            if j > i + 3 and RE_SPINE_CLEARANCE_INLINE.match(jl):
                block_end = j
                break
            if jl == "Print Order Requisition":
                pror_count += 1
                if pror_count >= 2:
                    block_end = j + 1
                    break
            block_end = j + 1

        block_text = "\n".join(lines[block_start:block_end]).strip()

        # Timestamp: prefer "Ordered On" line (military HHMM),
        # fall back to "Date:" field.
        sc_dt: Optional[str] = None
        ordered_on_next = False
        for j in range(block_start, block_end):
            jl = lines[j].strip()
            if jl.startswith("Ordered On"):
                ordered_on_next = True
                continue
            if ordered_on_next:
                m = RE_ORDERED_ON_HHMM.match(jl)
                if m:
                    sc_dt = _parse_dt_slash_hhmm(m.group(1), m.group(2))
                    if sc_dt:
                        _ts_count("MM/DD/YY HHMM (Spine Clearance order)")
                        break
                ordered_on_next = False

        if sc_dt is None:
            for j in range(block_start, min(block_end, block_start + 15)):
                dm = RE_ORDER_PAGE_DATE.search(lines[j])
                if dm:
                    sc_dt = _date_only_iso(dm.group(1))
                    if sc_dt:
                        _ts_count("M/D/YYYY (Spine Clearance Date)")
                        break

        warns: List[str] = []
        if sc_dt is None:
            _ts_fail()
            warns.append("ts_missing")

        items.append(
            EvidenceItem(
                idx=idx, kind="NURSING_ORDER", datetime=sc_dt,
                line_start=block_start + 1, line_end=block_end,
                text=block_text, warnings=tuple(warns), header_dt=sc_dt,
            )
        )
        idx += 1
        for j in range(block_start, block_end):
            claimed.add(j)

    return items


# ============================================================
# Core parser (bracket format)
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


def _item_with_raw_line_id(item: EvidenceItem) -> dict:
    """Serialize an EvidenceItem and stamp raw_line_id (AGENTS §5)."""
    d = asdict(item)
    d["raw_line_id"] = f"L{item.line_start}-L{item.line_end}"
    return d


def _build_evidence_object(src_path, patient_slug):
    _reset_ts_counts()  # fresh counters per patient
    lines = _read_lines(src_path)
    raw_text = "\n".join(lines)

    fmt = _detect_format(lines)

    if fmt == "dos":
        header = _extract_header_dos(lines)
        arrival_dt = header.get("ARRIVAL_TIME")
        items = _parse_items_dos(lines, arrival_dt_str=arrival_dt)
    else:
        header = _extract_header(lines)
        arrival_dt = header.get("ARRIVAL_TIME")
        items = _parse_items(lines, arrival_dt_str=arrival_dt)

    # ── Sex fallback: if header extraction didn't capture SEX, try HPI ──
    if "SEX" not in header:
        sex_val, _sex_line = _extract_sex_hpi_fallback(lines)
        if sex_val:
            header["SEX"] = sex_val

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
            "discharge_datetime": header.get("DISCHARGE_DATETIME"),
            "trauma_category": trauma_category or "DATA_NOT_AVAILABLE",
            "timezone": "America/Chicago",
        },
        "header": header,  # full header KV (auditable)
        "items": [_item_with_raw_line_id(it) for it in items],
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
    print("   discharge_datetime: {}".format(evidence["meta"].get("discharge_datetime")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
