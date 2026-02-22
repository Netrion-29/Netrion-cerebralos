#!/usr/bin/env python3
"""
FAST Exam Extraction v1 for CerebralOS.

Extracts FAST (Focused Assessment with Sonography for Trauma) exam
status from TRAUMA_HP Primary Survey section.

Output (patient-level, under features.fast_exam_v1)::

    {
      "fast_performed": "yes" | "no" | "DATA NOT AVAILABLE",
      "fast_result": "positive" | "negative" | "indeterminate" | null,
      "fast_ts": "<ISO datetime from TRAUMA_HP item>" | null,
      "fast_source": "TRAUMA_HP:Primary_Survey:FAST" | null,
      "fast_source_rule_id": "trauma_hp_primary_survey"
                           | "trauma_hp_primary_survey_no_fast_line"
                           | "no_trauma_hp_primary_survey"
                           | null,
      "fast_raw_text": "<exact FAST line text>" | null,
      "raw_line_id": "<sha256 evidence coordinate>" | null,
      "evidence": [ { ... } ] | [],
      "notes": [ ... ],
      "warnings": [ ... ]
    }

Source precedence (deterministic):
  1. TRAUMA_HP item → Primary Survey section → "FAST:" line.
     This is the ONLY supported source.  We do NOT fall back to
     narrative mentions ("Fast exam is negative") in ED notes or
     other note types.  Narrative FAST mentions are not structured
     enough for deterministic extraction without clinical inference.

Recognised FAST line patterns (all within Primary Survey):
  - "FAST: No"                           → performed=no, result=null
  - "FAST: Not indicated"                → performed=no, result=null
  - "FAST: No not indicated"             → performed=no, result=null
  - "FAST: Yes" (bare)                   → performed=yes, result=indeterminate
  - "FAST: Yes - negative"               → performed=yes, result=negative
  - "FAST: Yes - positive"               → performed=yes, result=positive
  - "FAST: Yes (per <name>) - negative"  → performed=yes, result=negative
  - "FAST: Yes (per <name>) - positive"  → performed=yes, result=positive

If TRAUMA_HP exists but no Primary Survey or no FAST line → fail-closed
with fast_performed = "DATA NOT AVAILABLE".

If no TRAUMA_HP at all → fail-closed with fast_performed = "DATA NOT AVAILABLE".

Design:
- Deterministic, fail-closed.
- No LLM, no ML, no clinical inference.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional, Tuple

_DNA = "DATA NOT AVAILABLE"

# ── Regex patterns ──────────────────────────────────────────────────

# Primary Survey section boundaries
RE_PRIMARY_SURVEY_START = re.compile(
    r"Primary\s+Survey\s*:", re.IGNORECASE,
)
RE_PRIMARY_SURVEY_END = re.compile(
    r"(Secondary\s+Survey|PMH|Past\s+Medical|ROS|HPI|Allergies)\s*:",
    re.IGNORECASE,
)

# FAST line within Primary Survey.
# Captures the full value after "FAST:" (trimmed).
RE_FAST_LINE = re.compile(
    r"^\s*FAST\s*:\s*(.+)$", re.IGNORECASE,
)

# Sub-patterns for classifying the FAST value text
# "Yes" optionally followed by physician attribution and result
RE_FAST_YES = re.compile(
    r"^Yes\b", re.IGNORECASE,
)
RE_FAST_RESULT = re.compile(
    r"[-\u2013]\s*(positive|negative|indeterminate)\b", re.IGNORECASE,
)
# "No" / "Not indicated" / "No not indicated"
RE_FAST_NO = re.compile(
    r"^No\b|^Not\s+indicated\b", re.IGNORECASE,
)


# ── Evidence helpers ────────────────────────────────────────────────

def _make_raw_line_id(
    source_type: str,
    source_id: Optional[str],
    line_text: str,
) -> str:
    """
    Build a deterministic raw_line_id from evidence coordinates.

    Format: sha256 of "source_type|source_id|line_text_stripped".
    """
    payload = f"{source_type}|{source_id or ''}|{line_text.strip()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ── Internal extraction ─────────────────────────────────────────────

def _extract_fast_from_text(
    text: str,
    dt: Optional[str],
    source_type: str,
    source_id: Optional[str],
) -> Optional[Dict[str, Any]]:
    """
    Parse a single text block for a FAST line within Primary Survey.

    Returns a result dict if a FAST line is found, else None.
    Only processes TRAUMA_HP items.
    """
    if source_type != "TRAUMA_HP":
        return None

    lines = text.split("\n")
    in_primary_survey = False

    for line in lines:
        stripped = line.strip()

        # Detect Primary Survey start
        if RE_PRIMARY_SURVEY_START.match(stripped):
            in_primary_survey = True
            continue

        # Detect section end
        if in_primary_survey and RE_PRIMARY_SURVEY_END.match(stripped):
            in_primary_survey = False
            continue

        if not in_primary_survey:
            continue

        # Look for FAST line
        m = RE_FAST_LINE.match(stripped)
        if not m:
            continue

        fast_value_text = m.group(1).strip()
        raw_line_id = _make_raw_line_id(source_type, source_id, stripped)

        # Classify
        fast_performed: str
        fast_result: Optional[str] = None

        if RE_FAST_YES.match(fast_value_text):
            fast_performed = "yes"
            # Check for result qualifier
            rm = RE_FAST_RESULT.search(fast_value_text)
            if rm:
                fast_result = rm.group(1).lower()
            else:
                fast_result = "indeterminate"
        elif RE_FAST_NO.match(fast_value_text):
            fast_performed = "no"
            fast_result = None
        else:
            # Unrecognised value → fail-closed as indeterminate
            fast_performed = "yes"
            fast_result = "indeterminate"

        return {
            "fast_performed": fast_performed,
            "fast_result": fast_result,
            "fast_ts": dt,
            "fast_source": "TRAUMA_HP:Primary_Survey:FAST",
            "fast_source_rule_id": "trauma_hp_primary_survey",
            "fast_raw_text": fast_value_text,
            "raw_line_id": raw_line_id,
        }

    return None


# ── Empty result ────────────────────────────────────────────────────

def _empty_result(
    rule_id: Optional[str] = None,
    notes: Optional[List[str]] = None,
    warnings: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Return a fail-closed empty result."""
    return {
        "fast_performed": _DNA,
        "fast_result": None,
        "fast_ts": None,
        "fast_source": None,
        "fast_source_rule_id": rule_id,
        "fast_raw_text": None,
        "raw_line_id": None,
        "evidence": [],
        "notes": notes or [],
        "warnings": warnings or [],
    }


# ── Public API ──────────────────────────────────────────────────────

def extract_fast_exam(
    pat_features: Dict[str, Any],
    days_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Extract FAST exam status from timeline items.

    Parameters
    ----------
    pat_features : dict
        ``{"days": {day_iso: {feature_key: ...}}}`` — the per-day
        features assembled so far.  Not used for FAST extraction
        but accepted for API consistency with other cross-day modules.
    days_data : dict
        Full ``patient_days_v1.json`` content (raw timeline).

    Returns
    -------
    dict
        FAST exam result dict (see module docstring for schema).
    """
    days_map = days_data.get("days") or {}

    has_trauma_hp = False
    has_primary_survey = False
    result: Optional[Dict[str, Any]] = None

    # Scan all days for TRAUMA_HP items with Primary Survey + FAST line.
    # Use the FIRST match found (chronologically earliest day).
    for day_iso in sorted(days_map.keys()):
        items = days_map[day_iso].get("items") or []
        for item in items:
            if item.get("type") != "TRAUMA_HP":
                continue

            has_trauma_hp = True
            text = (item.get("payload") or {}).get("text", "")
            if not text:
                continue

            # Check if this TRAUMA_HP has a Primary Survey section
            if RE_PRIMARY_SURVEY_START.search(text):
                has_primary_survey = True

            dt = item.get("dt")
            source_id = item.get("source_id")

            extracted = _extract_fast_from_text(
                text, dt, "TRAUMA_HP", source_id,
            )
            if extracted is not None and result is None:
                result = extracted

    # Build final output
    if result is not None:
        evidence_entry = {
            "raw_line_id": result["raw_line_id"],
            "source": result["fast_source"],
            "ts": result["fast_ts"],
            "snippet": f"FAST: {result['fast_raw_text']}",
        }
        return {
            "fast_performed": result["fast_performed"],
            "fast_result": result["fast_result"],
            "fast_ts": result["fast_ts"],
            "fast_source": result["fast_source"],
            "fast_source_rule_id": result["fast_source_rule_id"],
            "fast_raw_text": result["fast_raw_text"],
            "raw_line_id": result["raw_line_id"],
            "evidence": [evidence_entry],
            "notes": [],
            "warnings": [],
        }

    # No FAST found — determine why and fail-closed
    if not has_trauma_hp:
        return _empty_result(
            rule_id="no_trauma_hp",
            notes=["No TRAUMA_HP item found in timeline"],
        )

    if not has_primary_survey:
        return _empty_result(
            rule_id="no_trauma_hp_primary_survey",
            notes=["TRAUMA_HP exists but no Primary Survey section found"],
        )

    # Primary Survey exists but no FAST line
    return _empty_result(
        rule_id="trauma_hp_primary_survey_no_fast_line",
        notes=["Primary Survey exists but no FAST line found"],
        warnings=["fast_missing_in_primary_survey"],
    )
