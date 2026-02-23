#!/usr/bin/env python3
"""
Patient Age Extraction v1 — Deterministic Feature Module

Extracts patient age (integer years) from existing parsed patient data
in the timeline layer.

Extraction hierarchy (deterministic, fail-closed):

  1. **Primary: DOB from note text** — Parse ``DOB: M/D/YYYY`` or
     ``Date of Birth: M/D/YYYY`` patterns from timeline item payload
     text.  Compute age_years = floor((arrival_date – DOB) / 365.25).
     Priority: check TRAUMA_HP items first, then any note type.

  2. **Fallback: HPI narrative age** — Parse ``XX y.o.``, ``XX yo``,
     ``XX year-old`` patterns from TRAUMA_HP or CONSULT_NOTE items on
     arrival day.  Source rule: ``hpi_narrative_age``.

Fail-closed behavior:
  - If no DOB and no narrative age found → ``age_available = "DATA NOT AVAILABLE"``
  - If DOB yields nonsensical age (< 0 or > 120) → ``DATA NOT AVAILABLE``
  - If narrative age is nonsensical (< 0 or > 120) → skip that match

Evidence traceability:
  - DOB from note header: raw_line_id synthesised via SHA-256[:16]
    of evidence coordinates (item_type + ts + text line).
  - HPI narrative age: raw_line_id synthesised similarly.
  - Metadata-source exception: DOB is typically from note header
    metadata lines, not clinical evidence rows.  Contract documents
    this as a known metadata-source provenance pattern.

Output key: ``age_extraction_v1`` (under top-level ``features`` dict)

Output schema::

    {
      "age_years": <int | null>,
      "age_available": "yes" | "DATA NOT AVAILABLE",
      "age_source_rule_id": "dob_note_header" | "hpi_narrative_age" | null,
      "age_source_text": "<matched text>" | null,
      "dob_iso": "YYYY-MM-DD" | null,
      "evidence": [...],
      "notes": [...],
      "warnings": []
    }

Design:
- Deterministic, fail-closed.
- No LLM, no ML, no clinical inference.
- raw_line_id required on every stored evidence entry.
- Consumes only timeline data (patient_days_v1.json).
"""

from __future__ import annotations

import hashlib
import math
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

_DNA = "DATA NOT AVAILABLE"

# ── Regex patterns ──────────────────────────────────────────────────

# DOB from note headers: "DOB: M/D/YYYY", "DOB:  M/D/YYYY",
# "Date of Birth: M/D/YYYY"
_DOB_RE = re.compile(
    r"(?:DOB|Date\s+of\s+Birth)\s*:\s*(\d{1,2}/\d{1,2}/\d{4})",
    re.IGNORECASE,
)

# Narrative age in HPI: "65 y.o.", "60 yo", "65 year-old",
# "65 year old", "65-year-old", "65 yr old"
_NARRATIVE_AGE_RE = re.compile(
    r"\b(\d{1,3})\s*[-\s]?(?:y\.?o\.?|year[-\s]?old|yr)\b",
    re.IGNORECASE,
)

# Item types in priority order for DOB extraction
_DOB_PRIORITY_TYPES = ("TRAUMA_HP", "CONSULT_NOTE", "ED_NOTE", "PHYSICIAN_NOTE",
                        "NURSING_NOTE", "DISCHARGE")

# Item types for HPI narrative age (Trauma H&P has clinical authority)
_HPI_PRIORITY_TYPES = ("TRAUMA_HP", "CONSULT_NOTE", "ED_NOTE")

# Sanity bounds for age
_AGE_MIN = 0
_AGE_MAX = 120


# ── Helpers ─────────────────────────────────────────────────────────

def _make_raw_line_id(source: str, dt: Optional[str], text: str) -> str:
    """Build a deterministic raw_line_id from evidence coordinates."""
    payload = f"{source}|{dt or ''}|{text.strip()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _parse_dob(dob_str: str) -> Optional[date]:
    """Parse M/D/YYYY → date, or None on failure."""
    try:
        parts = dob_str.strip().split("/")
        if len(parts) != 3:
            return None
        month, day, year = int(parts[0]), int(parts[1]), int(parts[2])
        return date(year, month, day)
    except (ValueError, IndexError):
        return None


def _compute_age_years(dob: date, ref_date: date) -> Optional[int]:
    """Compute integer age in years at ref_date."""
    # Standard birthday math
    age = ref_date.year - dob.year
    if (ref_date.month, ref_date.day) < (dob.month, dob.day):
        age -= 1
    if _AGE_MIN <= age <= _AGE_MAX:
        return age
    return None  # nonsensical


def _make_dna_result(reason: str) -> Dict[str, Any]:
    """Build DATA NOT AVAILABLE stub."""
    return {
        "age_years": None,
        "age_available": _DNA,
        "age_source_rule_id": None,
        "age_source_text": None,
        "dob_iso": None,
        "evidence": [],
        "notes": [reason],
        "warnings": [],
    }


def _get_arrival_date(meta: Dict[str, Any]) -> Optional[date]:
    """Extract arrival date from meta.arrival_datetime."""
    arrival_str = meta.get("arrival_datetime")
    if not arrival_str or not isinstance(arrival_str, str):
        return None
    try:
        # Handles "YYYY-MM-DD HH:MM:SS" and "YYYY-MM-DDTHH:MM:SS"
        return datetime.fromisoformat(arrival_str.replace(" ", "T")).date()
    except (ValueError, TypeError):
        return None


# ── DOB extraction from note text ──────────────────────────────────

def _extract_dob_from_items(
    all_items: List[Tuple[str, str, Dict[str, Any]]],
) -> Optional[Tuple[str, str, str, str]]:
    """
    Search items for DOB pattern in priority order.

    Parameters
    ----------
    all_items : list of (day_iso, item_type, item_dict)
        Flattened items across all days.

    Returns
    -------
    (dob_str, matched_line, item_type, item_ts) or None
    """
    # Group by item type priority
    for target_type in _DOB_PRIORITY_TYPES:
        for day_iso, item_type, item in all_items:
            if item_type != target_type:
                continue
            text = (item.get("payload") or {}).get("text", "")
            for line in text.split("\n"):
                m = _DOB_RE.search(line)
                if m:
                    return (
                        m.group(1),           # dob_str e.g. "3/20/1960"
                        line.strip(),         # matched line
                        item_type,            # source type
                        item.get("dt") or "", # item timestamp
                    )
    return None


# ── HPI narrative age extraction ────────────────────────────────────

def _extract_narrative_age_from_items(
    arrival_items: List[Tuple[str, str, Dict[str, Any]]],
) -> Optional[Tuple[int, str, str, str]]:
    """
    Search arrival-day items for HPI narrative age pattern.

    Parameters
    ----------
    arrival_items : list of (day_iso, item_type, item_dict)
        Items on arrival day only.

    Returns
    -------
    (age_int, matched_text, item_type, item_ts) or None
    """
    for target_type in _HPI_PRIORITY_TYPES:
        for day_iso, item_type, item in arrival_items:
            if item_type != target_type:
                continue
            text = (item.get("payload") or {}).get("text", "")
            m = _NARRATIVE_AGE_RE.search(text)
            if m:
                age_val = int(m.group(1))
                if _AGE_MIN < age_val <= _AGE_MAX:
                    # Grab context around the match
                    start = max(0, m.start() - 10)
                    end = min(len(text), m.end() + 10)
                    snippet = text[start:end].strip()
                    return (
                        age_val,
                        snippet,
                        item_type,
                        item.get("dt") or "",
                    )
    return None


# ── Core extraction ─────────────────────────────────────────────────

def extract_patient_age(
    days_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Deterministic patient age extraction from timeline data.

    Consumes:
      - days_data["meta"]["arrival_datetime"] — arrival reference date
      - days_data["days"][*]["items"][*] — note text for DOB / HPI age

    Parameters
    ----------
    days_data : dict
        The full patient_days_v1.json dict.

    Returns
    -------
    dict
        age_extraction_v1 contract output.
    """
    meta = days_data.get("meta") or {}
    days_map = days_data.get("days") or {}
    evidence: List[Dict[str, Any]] = []
    notes: List[str] = []
    warnings: List[str] = []

    arrival_date = _get_arrival_date(meta)
    if arrival_date is None:
        return _make_dna_result("arrival_datetime not available; cannot compute age")

    arrival_day_iso = arrival_date.isoformat()

    # ── Flatten items with type info ────────────────────────────
    all_items: List[Tuple[str, str, Dict[str, Any]]] = []
    arrival_items: List[Tuple[str, str, Dict[str, Any]]] = []
    for day_iso in sorted(days_map.keys()):
        day_info = days_map[day_iso]
        for item in day_info.get("items") or []:
            item_type = item.get("type", "")
            entry = (day_iso, item_type, item)
            all_items.append(entry)
            if day_iso == arrival_day_iso:
                arrival_items.append(entry)

    if not all_items:
        return _make_dna_result("no timeline items available")

    # ── Strategy 1: DOB from note text ──────────────────────────
    dob_result = _extract_dob_from_items(all_items)
    if dob_result is not None:
        dob_str, matched_line, item_type, item_ts = dob_result
        dob_date = _parse_dob(dob_str)
        if dob_date is not None:
            age_years = _compute_age_years(dob_date, arrival_date)
            if age_years is not None:
                raw_line_id = _make_raw_line_id(
                    item_type, item_ts, matched_line,
                )
                evidence.append({
                    "raw_line_id": raw_line_id,
                    "source": item_type,
                    "ts": item_ts or None,
                    "snippet": f"DOB: {dob_str} → age {age_years} at arrival",
                    "role": "primary",
                })

                return {
                    "age_years": age_years,
                    "age_available": "yes",
                    "age_source_rule_id": "dob_note_header",
                    "age_source_text": f"DOB: {dob_str}",
                    "dob_iso": dob_date.isoformat(),
                    "evidence": evidence,
                    "notes": notes,
                    "warnings": warnings,
                }
            else:
                warnings.append(
                    f"DOB parsed ({dob_str}) but computed age out of "
                    f"bounds [0–120]; falling back to narrative"
                )
        else:
            warnings.append(
                f"DOB pattern matched ({dob_str}) but could not parse date; "
                "falling back to narrative"
            )

    # ── Strategy 2: HPI narrative age ───────────────────────────
    hpi_result = _extract_narrative_age_from_items(arrival_items)
    if hpi_result is not None:
        age_val, snippet, item_type, item_ts = hpi_result
        raw_line_id = _make_raw_line_id(item_type, item_ts, snippet)
        evidence.append({
            "raw_line_id": raw_line_id,
            "source": item_type,
            "ts": item_ts or None,
            "snippet": snippet,
            "role": "primary",
        })
        notes.append(
            "age extracted from HPI narrative text (no DOB header found); "
            "age is approximate"
        )

        return {
            "age_years": age_val,
            "age_available": "yes",
            "age_source_rule_id": "hpi_narrative_age",
            "age_source_text": snippet,
            "dob_iso": None,
            "evidence": evidence,
            "notes": notes,
            "warnings": warnings,
        }

    # ── Neither source found ────────────────────────────────────
    return _make_dna_result(
        "no DOB or narrative age found in timeline items"
    )
