#!/usr/bin/env python3
"""
Per-day Pupil Reactivity Extraction v1 for CerebralOS.

Deterministic extraction of bilateral pupil size and reactivity from
structured nursing flowsheet rows and common prose patterns.

Sources (per-item scan):
  - Structured flowsheet: "Size R Pupil (mm): 3", "Reaction R Pupil: Brisk"
  - Prose patterns: PERRL, "pupils equal and reactive", "fixed and dilated",
    "pinpoint pupils", "pupils sluggish", "pupils X mm and fixed"

Output per day::

    pupil_reactivity_v1: {
      assessments: [
        {
          right_size_mm: float | null,
          left_size_mm:  float | null,
          right_reaction: "Brisk" | "Sluggish" | "Fixed" | "Nonreactive" | null,
          left_reaction:  "Brisk" | "Sluggish" | "Fixed" | "Nonreactive" | null,
          source_type: "FLOWSHEET" | "PROSE",
          dt: "<ISO datetime>" | null,
          raw_line_id: "...",
          line_preview: "...",
          abnormal: true | false,
        }, ...
      ],
      summary: {
        total_assessments: int,
        any_abnormal: bool,
        any_fixed: bool,
        any_asymmetric: bool,
      },
      warnings: [...]
    }

Abnormal criteria (fail-closed):
  - Fixed or Nonreactive reaction (either eye)
  - Dilated >= 6 mm (either eye)
  - Pinpoint <= 2 mm (either eye)
  - Asymmetric size difference >= 1 mm

Design:
  - Deterministic, fail-closed.
  - No LLM, no ML, no clinical inference.
  - Every assessment carries raw_line_id for audit traceability.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional, Tuple

# ── Canonical reaction values ───────────────────────────────────────
_REACTIONS = frozenset({"Brisk", "Sluggish", "Fixed", "Nonreactive"})

# ── Abnormal thresholds ─────────────────────────────────────────────
_DILATED_THRESHOLD = 6.0   # mm, >= is dilated
_PINPOINT_THRESHOLD = 2.0  # mm, <= is pinpoint
_ASYMMETRY_THRESHOLD = 1.0 # mm difference between L and R

# ── Source types to scan ────────────────────────────────────────────
_SOURCE_TYPES = frozenset({
    "FLOWSHEET",
    "TRAUMA_HP",
    "PHYSICIAN_NOTE",
    "ED_NOTE",
    "CONSULT_NOTE",
    "NURSING_NOTE",
    "PROGRESS_NOTE",
})

# ── Structured flowsheet patterns ───────────────────────────────────
# "Size R Pupil (mm): 3" or "Size L Pupil (mm): 4"
_RE_SIZE = re.compile(
    r"Size\s+([RL])\s+Pupil\s*\(mm\)\s*:\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)

# "Reaction R Pupil: Brisk" or "Reaction L Pupil: Sluggish"
_RE_REACTION = re.compile(
    r"Reaction\s+([RL])\s+Pupil\s*:\s*(\w+)",
    re.IGNORECASE,
)

# ── Prose patterns ──────────────────────────────────────────────────
# PERRL — "Pupils Equal, Round, Reactive to Light"
_RE_PERRL = re.compile(r"\bPERRL[A-Z]?\b", re.IGNORECASE)

# "Pupils equal in size, round, and reactive to light bilaterally"
# "pupils are symmetric and briskly reactive"
_RE_NORMAL_PROSE = re.compile(
    r"\bpupils?\s+(?:\w+\s+)*(?:equal|symmetric)\b[^.;]{0,60}"
    r"(?:round|reactive|brisk)",
    re.IGNORECASE,
)

# "pinpoint pupils" or "bilateral pinpoint pupils"
_RE_PINPOINT = re.compile(
    r"\b(?:bilateral\s+)?pinpoint\s+pupils?\b",
    re.IGNORECASE,
)

# "fixed and dilated pupils" or "pupils fixed and dilated"
_RE_FIXED_DILATED = re.compile(
    r"\b(?:fixed\s+and\s+dilated\s+pupils?|pupils?\s+fixed\s+and\s+dilated)\b",
    re.IGNORECASE,
)

# "Pupils 6mm and fixed" or "pupils now 4 mm and fixed"
_RE_SIZE_AND_FIXED = re.compile(
    r"\bpupils?\s+(?:now\s+)?(\d+)\s*mm\s+and\s+fixed\b",
    re.IGNORECASE,
)

# "pupils sluggish" or "pupils sluggish bilaterally/pinpoint"
_RE_SLUGGISH = re.compile(
    r"\bpupils?\s+sluggish\b",
    re.IGNORECASE,
)

# "pupils / nonreactive" or "pupils nonreactive"
_RE_NONREACTIVE = re.compile(
    r"\bpupils?\s*(?:/\s*)?non\s*-?\s*reactive\b",
    re.IGNORECASE,
)


# ── Helpers ─────────────────────────────────────────────────────────

def _make_raw_line_id(source_id: Any, dt: Optional[str], preview: str) -> str:
    """Deterministic raw_line_id from evidence coordinates."""
    key = f"{source_id}|{dt}|{preview}"
    return hashlib.sha256(key.encode("utf-8", errors="replace")).hexdigest()[:16]


def _normalize_reaction(raw: str) -> Optional[str]:
    """Normalize a reaction string to canonical form."""
    r = raw.strip().capitalize()
    if r in _REACTIONS:
        return r
    lower = raw.strip().lower()
    if lower.startswith("brisk"):
        return "Brisk"
    if lower.startswith("sluggish"):
        return "Sluggish"
    if lower in ("fixed", "no response", "none"):
        return "Fixed"
    if lower in ("nonreactive", "non-reactive", "non reactive", "unreactive"):
        return "Nonreactive"
    return None


def _is_abnormal(
    right_size: Optional[float],
    left_size: Optional[float],
    right_reaction: Optional[str],
    left_reaction: Optional[str],
) -> bool:
    """Determine if a pupil assessment is abnormal."""
    # Fixed or Nonreactive
    for rxn in (right_reaction, left_reaction):
        if rxn in ("Fixed", "Nonreactive"):
            return True
    # Dilated
    for sz in (right_size, left_size):
        if sz is not None and sz >= _DILATED_THRESHOLD:
            return True
    # Pinpoint
    for sz in (right_size, left_size):
        if sz is not None and sz <= _PINPOINT_THRESHOLD:
            return True
    # Asymmetric
    if right_size is not None and left_size is not None:
        if abs(right_size - left_size) >= _ASYMMETRY_THRESHOLD:
            return True
    return False


def _is_asymmetric(
    right_size: Optional[float],
    left_size: Optional[float],
) -> bool:
    """Check for pupil size asymmetry."""
    if right_size is not None and left_size is not None:
        return abs(right_size - left_size) >= _ASYMMETRY_THRESHOLD
    return False


# ── Main extraction ─────────────────────────────────────────────────

def extract_pupil_reactivity_for_day(
    items: List[Dict[str, Any]],
    day_iso: str,
) -> Tuple[Dict[str, Any], List[str]]:
    """Extract pupil reactivity assessments from timeline items for one day.

    Args:
        items: Timeline items for this calendar day.
        day_iso: Calendar day in ISO format (YYYY-MM-DD).

    Returns:
        (result_dict, warnings_list)
    """
    assessments: List[Dict[str, Any]] = []
    warnings: List[str] = []

    for item in items:
        item_type = item.get("type")
        if item_type not in _SOURCE_TYPES:
            continue

        text = (item.get("payload") or {}).get("text", "")
        if not text:
            continue

        dt = item.get("dt")
        source_id = item.get("source_id", "")

        lines = text.split("\n")
        # Accumulate flowsheet fields across consecutive lines
        fs_right_size: Optional[float] = None
        fs_left_size: Optional[float] = None
        fs_right_rxn: Optional[str] = None
        fs_left_rxn: Optional[str] = None
        fs_lines: List[str] = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                # Flush any accumulated flowsheet data on blank line
                if fs_lines:
                    preview = "; ".join(fs_lines)[:120]
                    rid = _make_raw_line_id(source_id, dt, preview)
                    assessments.append({
                        "right_size_mm": fs_right_size,
                        "left_size_mm": fs_left_size,
                        "right_reaction": fs_right_rxn,
                        "left_reaction": fs_left_rxn,
                        "source_type": "FLOWSHEET",
                        "dt": dt,
                        "raw_line_id": rid,
                        "line_preview": preview,
                        "abnormal": _is_abnormal(
                            fs_right_size, fs_left_size,
                            fs_right_rxn, fs_left_rxn,
                        ),
                    })
                    fs_right_size = fs_left_size = None
                    fs_right_rxn = fs_left_rxn = None
                    fs_lines = []
                continue

            # ── Structured flowsheet: Size ──
            m_size = _RE_SIZE.search(stripped)
            if m_size:
                side = m_size.group(1).upper()
                val = float(m_size.group(2))
                if side == "R":
                    fs_right_size = val
                else:
                    fs_left_size = val
                fs_lines.append(stripped)
                continue

            # ── Structured flowsheet: Reaction ──
            m_rxn = _RE_REACTION.search(stripped)
            if m_rxn:
                side = m_rxn.group(1).upper()
                rxn = _normalize_reaction(m_rxn.group(2))
                if rxn:
                    if side == "R":
                        fs_right_rxn = rxn
                    else:
                        fs_left_rxn = rxn
                    fs_lines.append(stripped)
                    continue

            # If we have accumulated flowsheet fields but hit a non-matching
            # line, flush what we have
            if fs_lines:
                preview = "; ".join(fs_lines)[:120]
                rid = _make_raw_line_id(source_id, dt, preview)
                assessments.append({
                    "right_size_mm": fs_right_size,
                    "left_size_mm": fs_left_size,
                    "right_reaction": fs_right_rxn,
                    "left_reaction": fs_left_rxn,
                    "source_type": "FLOWSHEET",
                    "dt": dt,
                    "raw_line_id": rid,
                    "line_preview": preview,
                    "abnormal": _is_abnormal(
                        fs_right_size, fs_left_size,
                        fs_right_rxn, fs_left_rxn,
                    ),
                })
                fs_right_size = fs_left_size = None
                fs_right_rxn = fs_left_rxn = None
                fs_lines = []

            # ── Prose patterns (only on lines containing "pupil" or "PERRL") ──
            if not re.search(r"pupil|PERRL", stripped, re.IGNORECASE):
                continue

            preview = stripped[:120]
            rid = _make_raw_line_id(source_id, dt, preview)

            # PERRL
            if _RE_PERRL.search(stripped):
                assessments.append({
                    "right_size_mm": None,
                    "left_size_mm": None,
                    "right_reaction": "Brisk",
                    "left_reaction": "Brisk",
                    "source_type": "PROSE",
                    "dt": dt,
                    "raw_line_id": rid,
                    "line_preview": preview,
                    "abnormal": False,
                })
                continue

            # Normal prose (equal/symmetric + reactive)
            if _RE_NORMAL_PROSE.search(stripped):
                assessments.append({
                    "right_size_mm": None,
                    "left_size_mm": None,
                    "right_reaction": "Brisk",
                    "left_reaction": "Brisk",
                    "source_type": "PROSE",
                    "dt": dt,
                    "raw_line_id": rid,
                    "line_preview": preview,
                    "abnormal": False,
                })
                continue

            # Fixed and dilated
            if _RE_FIXED_DILATED.search(stripped):
                assessments.append({
                    "right_size_mm": None,
                    "left_size_mm": None,
                    "right_reaction": "Fixed",
                    "left_reaction": "Fixed",
                    "source_type": "PROSE",
                    "dt": dt,
                    "raw_line_id": rid,
                    "line_preview": preview,
                    "abnormal": True,
                })
                continue

            # Pupils Xmm and fixed
            m_sf = _RE_SIZE_AND_FIXED.search(stripped)
            if m_sf:
                sz = float(m_sf.group(1))
                assessments.append({
                    "right_size_mm": sz,
                    "left_size_mm": sz,
                    "right_reaction": "Fixed",
                    "left_reaction": "Fixed",
                    "source_type": "PROSE",
                    "dt": dt,
                    "raw_line_id": rid,
                    "line_preview": preview,
                    "abnormal": True,
                })
                continue

            # Pinpoint pupils
            if _RE_PINPOINT.search(stripped):
                assessments.append({
                    "right_size_mm": 1.0,
                    "left_size_mm": 1.0,
                    "right_reaction": None,
                    "left_reaction": None,
                    "source_type": "PROSE",
                    "dt": dt,
                    "raw_line_id": rid,
                    "line_preview": preview,
                    "abnormal": True,
                })
                continue

            # Sluggish
            if _RE_SLUGGISH.search(stripped):
                assessments.append({
                    "right_size_mm": None,
                    "left_size_mm": None,
                    "right_reaction": "Sluggish",
                    "left_reaction": "Sluggish",
                    "source_type": "PROSE",
                    "dt": dt,
                    "raw_line_id": rid,
                    "line_preview": preview,
                    "abnormal": False,
                })
                continue

            # Nonreactive
            if _RE_NONREACTIVE.search(stripped):
                assessments.append({
                    "right_size_mm": None,
                    "left_size_mm": None,
                    "right_reaction": "Nonreactive",
                    "left_reaction": "Nonreactive",
                    "source_type": "PROSE",
                    "dt": dt,
                    "raw_line_id": rid,
                    "line_preview": preview,
                    "abnormal": True,
                })
                continue

        # Flush any remaining flowsheet accumulation at end of text
        if fs_lines:
            preview = "; ".join(fs_lines)[:120]
            rid = _make_raw_line_id(source_id, dt, preview)
            assessments.append({
                "right_size_mm": fs_right_size,
                "left_size_mm": fs_left_size,
                "right_reaction": fs_right_rxn,
                "left_reaction": fs_left_rxn,
                "source_type": "FLOWSHEET",
                "dt": dt,
                "raw_line_id": rid,
                "line_preview": preview,
                "abnormal": _is_abnormal(
                    fs_right_size, fs_left_size,
                    fs_right_rxn, fs_left_rxn,
                ),
            })

    # Build summary
    any_fixed = any(
        a.get("right_reaction") == "Fixed" or a.get("left_reaction") == "Fixed"
        for a in assessments
    )
    any_asymmetric = any(
        _is_asymmetric(a.get("right_size_mm"), a.get("left_size_mm"))
        for a in assessments
    )
    any_abnormal = any(a.get("abnormal") for a in assessments)

    result = {
        "assessments": assessments,
        "summary": {
            "total_assessments": len(assessments),
            "any_abnormal": any_abnormal,
            "any_fixed": any_fixed,
            "any_asymmetric": any_asymmetric,
        },
        "warnings": warnings,
    }

    return result, warnings
