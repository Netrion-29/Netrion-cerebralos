#!/usr/bin/env python3
"""
CerebralOS — Trauma Daily Plan By Day v1

Extracts per-day plan text from trauma-team progress notes and organises
it by calendar day.

Strategy:
  1. Iterate timeline items chronologically across all days.
  2. Select items of type PHYSICIAN_NOTE whose text matches the
     qualifying note-type header allowlist.
  3. Within each qualifying note, locate the "Impression:" (or
     "Assessment:") and "Plan:" sections using deterministic regex
     anchors.
  4. Extract the Impression/Assessment + Plan text as structured data.
  5. Organise results by day, with per-note entries preserving the
     author, timestamp, and raw plan lines.

Qualifying note types (allowlist):
  - "Trauma Progress Note"
  - "Trauma Tertiary Survey Note"
  - "Trauma Tertiary Note"
  - "Trauma Tertiary Progress Note"
  - "Trauma Overnight Progress Note"
  - "Daily Progress Note" (only when from Evansville Surgical Associates)
  - "ESA Brief Progress Note" (brief — may lack Impression/Plan)
  - "ESA Brief Update" (brief — may lack Impression/Plan)
  - "ESA Quick Update Note" (brief — may lack Impression/Plan)
  - "ESA TRAUMA BRIEF NOTE" (brief — may lack Impression/Plan)

Excluded (not in scope):
  - Consultant notes (separate feature: consultant_plan_items_v1)
  - Hospitalist progress notes (different plan format, not trauma-team)
  - Radiology reads (PHYSICIAN_NOTE but not trauma progress notes)
  - ED notes, nursing notes, discharge summaries

Output schema:
  {
      "days": {
          "<ISO-date>": {
              "notes": [
                  {
                      "note_type": "<qualifying header>",
                      "author": "<name, credential>",
                      "dt": "<ISO datetime>",
                      "source_id": "<item source_id>",
                      "impression_lines": ["line1", ...],
                      "plan_lines": ["line1", ...],
                      "raw_line_id": "<sha256 hash>",
                  },
                  ...
              ]
          },
          ...
      },
      "total_notes": <int>,
      "total_days": <int>,
      "qualifying_note_types_found": ["Trauma Progress Note", ...],
      "source_rule_id": "trauma_daily_plan_from_progress_notes" | "no_qualifying_notes",
      "warnings": [],
      "notes": [],
  }

Fail-closed:
  - If no qualifying notes found → source_rule_id = "no_qualifying_notes",
    days = {}, total_notes = 0
  - If a qualifying note has no Plan: section → warning emitted, note skipped
  - Deterministic: same input → same output, always
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional, Tuple

# ── Constants ──────────────────────────────────────────────────────
_DNA = "DATA NOT AVAILABLE"

# Note-type allowlist: only these header patterns qualify.
# Matched case-insensitively against lines at the top of the note.
_QUALIFYING_NOTE_HEADERS = (
    "Trauma Progress Note",
    "Trauma Tertiary Survey Note",
    "Trauma Tertiary Note",
    "Trauma Tertiary Progress Note",
    "Trauma Overnight Progress Note",
    "Daily Progress Note",           # Only when ESA-gated (see _detect_note_type)
    "ESA Brief Progress Note",
    "ESA Brief Update",
    "ESA Quick Update Note",
    "ESA TRAUMA BRIEF NOTE",
)

# Regex to match a qualifying trauma note header in the note text.
# Anchored to line start (after optional whitespace).  The trailing
# colon is optional ("Trauma Overnight Progress Note:" has one).
_RE_QUALIFYING_HEADER = re.compile(
    r"^\s*(?:"
    r"Trauma\s+Progress\s+Note"
    r"|Trauma\s+Tertiary\s+Survey\s+Note"
    r"|Trauma\s+Tertiary\s+Note"
    r"|Trauma\s+Tertiary\s+Progress\s+Note"
    r"|Trauma\s+Overnight\s+Progress\s+Note"
    r"|Daily\s+Progress\s+Note"
    r"|ESA\s+Brief\s+Progress\s+Note"
    r"|ESA\s+Brief\s+Update"
    r"|ESA\s+Quick\s+Update\s+Note"
    r"|ESA\s+TRAUMA\s+BRIEF\s+NOTE"
    r")\s*:?\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# Match the author line: "Name Credential, Credential" immediately after header.
# Examples: "Allison Kimmel, PA-C", "Rachel N Bertram, NP", "Roberto C Iglesias, MD"
_RE_AUTHOR_LINE = re.compile(
    r"^\s*([A-Z][a-z]+(?:\s+[A-Z]\.?)?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?,\s*(?:PA-C|NP|MD|DO|PA|RN|APRN|ARNP|FNP|CNP))\s*$",
    re.MULTILINE,
)

# Impression section start: " Impression:" (may have leading space) or "Impression:"
_RE_IMPRESSION_START = re.compile(
    r"^\s*Impression\s*:\s*$|^\s*Impression\s*:\s*\S",
    re.IGNORECASE | re.MULTILINE,
)

# Assessment section start: used by ESA "Daily Progress Note" format
# which uses "Assessment:" instead of "Impression:"
_RE_ASSESSMENT_START = re.compile(
    r"^\s*Assessment\s*:\s*$|^\s*Assessment\s*:\s*\S",
    re.IGNORECASE | re.MULTILINE,
)

# Plan section start — matches "Plan:" at line start, with or without
# inline content (some ESA notes have "Plan:  Admit to 45/46" on same line)
_RE_PLAN_START = re.compile(
    r"^\s*Plan\s*:",
    re.IGNORECASE | re.MULTILINE,
)

# Plan section terminators (attestation, footer, author signature, MyChart)
_PLAN_TERMINATORS = re.compile(
    r"(?:"
    r"I have seen and examined patient"
    r"|MyChart now allows"
    r"|Revision History"
    r"|Medically\s+stable\s+for\s+discharge"
    r"|Expand All Collapse All"
    r")",
    re.IGNORECASE,
)

# Author/signature line pattern — used as a plan terminator too
_RE_SIGNATURE_LINE = re.compile(
    r"^\s*[A-Z][a-z]+(?:\s+[A-Z]\.?)?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?,\s*(?:PA-C|NP|MD|DO|PA|RN|APRN|ARNP|FNP|CNP)\s*$",
    re.MULTILINE,
)

# Noise lines to skip within plan/impression sections
_NOISE_LINE_RE = re.compile(
    r"^\s*$"  # blank lines (handled separately)
    r"|^\s*Revision\s*History"
    r"|^\s*Toggle\s+Section"
    r"|^\s*Expand\s+All"
    r"|^\s*Collapse\s+All",
    re.IGNORECASE,
)

# Maximum plan lines per note (safety cap)
_MAX_PLAN_LINES = 60
# Maximum impression lines per note (safety cap)
_MAX_IMPRESSION_LINES = 30


# ── Helpers ────────────────────────────────────────────────────────

def _make_raw_line_id(source_id: str, dt: str, preview: str) -> str:
    """Deterministic SHA-256 hash for evidence tracing."""
    payload = f"{source_id}|{dt}|{preview}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _detect_note_type(text: str) -> Optional[str]:
    """Return the qualifying note type header if found, else None.

    For "Daily Progress Note", requires ESA (Evansville Surgical Associates)
    body text to avoid false-matching hospitalist notes.
    """
    m = _RE_QUALIFYING_HEADER.search(text)
    if not m:
        return None
    matched = m.group(0).strip().rstrip(":")
    lower = matched.lower()

    # ── ESA brief note patterns ──
    if lower.startswith("esa "):
        # Normalise to canonical form
        if "brief progress" in lower:
            return "ESA Brief Progress Note"
        if "brief update" in lower:
            return "ESA Brief Update"
        if "quick update" in lower:
            return "ESA Quick Update Note"
        if "trauma brief" in lower:
            return "ESA TRAUMA BRIEF NOTE"
        return matched  # fallback (shouldn't happen)

    # ── Daily Progress Note: must be from ESA ──
    if lower == "daily progress note":
        # Gate: only match if the note body mentions ESA affiliation
        if not re.search(
            r"Evansville\s+Surgical\s+Assoc",
            text[:600],
            re.IGNORECASE,
        ):
            return None
        return "Daily Progress Note"

    # ── Trauma-prefixed headers ──
    if "overnight" in lower:
        return "Trauma Overnight Progress Note"
    if "tertiary" in lower and "survey" in lower:
        return "Trauma Tertiary Survey Note"
    if "tertiary" in lower and "progress" in lower:
        return "Trauma Tertiary Progress Note"
    if "tertiary" in lower:
        return "Trauma Tertiary Note"
    return "Trauma Progress Note"


def _extract_author(text: str) -> str:
    """Extract the author name from the note header area."""
    # Search only the first 300 chars (header area)
    header_area = text[:300]
    m = _RE_AUTHOR_LINE.search(header_area)
    if m:
        return m.group(1).strip()
    return _DNA


def _extract_section_text(
    text: str,
    start_pos: int,
    end_pos: int,
    terminators: re.Pattern,
    max_lines: int,
) -> List[str]:
    """
    Extract lines from a section bounded by start_pos and end_pos.
    Applies terminators within the section. Returns cleaned, non-blank lines.
    """
    section_text = text[start_pos:end_pos]
    lines = section_text.split("\n")

    result: List[str] = []
    for raw_line in lines:
        stripped = raw_line.rstrip()
        # Stop at terminators
        if terminators.search(stripped):
            break
        # Stop at signature lines (author name at end of plan)
        if _RE_SIGNATURE_LINE.match(stripped):
            break
        # Skip completely blank lines
        if not stripped.strip():
            continue
        result.append(stripped)
        if len(result) >= max_lines:
            break

    return result


def _find_clinical_impression_and_plan(text: str) -> Tuple[int, int, int]:
    """
    Find the clinical Impression and Plan section boundaries.

    Strategy: find the Plan: section first, then search backwards for the
    nearest Impression: that appears AFTER the Prophylaxis or Labs section
    (to skip radiology read IMPRESSION: lines embedded earlier in the note).

    Returns (impression_start, plan_start, plan_end) character positions.
    If impression not found, impression_start == plan_start.
    If plan not found, all values are -1.
    """
    # Find Plan: section
    plan_match = None
    for m in _RE_PLAN_START.finditer(text):
        plan_match = m  # Take the last Plan: match

    if not plan_match:
        return -1, -1, -1

    plan_header_end = plan_match.end()
    plan_start = plan_match.start()

    # Find end of Plan: (attestation, footer, etc.)
    plan_end = len(text)
    # Search after plan header for terminators
    for line_start_idx in range(plan_header_end, len(text)):
        if text[line_start_idx] == '\n' or line_start_idx == plan_header_end:
            line_end_idx = text.find('\n', line_start_idx + 1)
            if line_end_idx == -1:
                line_end_idx = len(text)
            line = text[line_start_idx:line_end_idx]
            if _PLAN_TERMINATORS.search(line):
                plan_end = line_start_idx
                break
            if _RE_SIGNATURE_LINE.match(line.strip()):
                plan_end = line_start_idx
                break

    # Find the LAST Impression: before Plan:
    # Fall back to Assessment: if no Impression: is found (ESA format)
    impression_start = plan_start  # default: no impression found
    last_impression_match = None
    for m in _RE_IMPRESSION_START.finditer(text[:plan_start]):
        last_impression_match = m

    if not last_impression_match:
        # Try Assessment: as fallback (ESA "Daily Progress Note" format)
        for m in _RE_ASSESSMENT_START.finditer(text[:plan_start]):
            last_impression_match = m

    if last_impression_match:
        # Get the start of the line containing "Impression:"
        line_start = text.rfind("\n", 0, last_impression_match.start())
        impression_start = line_start + 1 if line_start >= 0 else 0

    return impression_start, plan_start, plan_end


def _extract_impression(text: str) -> List[str]:
    """Extract impression section lines from a trauma note."""
    imp_start, plan_start, _ = _find_clinical_impression_and_plan(text)
    if imp_start < 0 or imp_start == plan_start:
        return []

    # Get the text between impression header and plan header
    impression_text = text[imp_start:plan_start]

    # Remove the "Impression:" (or "Assessment:") header itself and extract content
    m = _RE_IMPRESSION_START.search(impression_text)
    if not m:
        m = _RE_ASSESSMENT_START.search(impression_text)
    if not m:
        return []

    # Get inline content on the header line
    header_line_end = impression_text.find("\n", m.start())
    if header_line_end == -1:
        header_line_end = len(impression_text)
    header_line = impression_text[m.start():header_line_end]

    result: List[str] = []

    # Check for inline content after "Impression:"
    colon_idx = header_line.find(":")
    if colon_idx >= 0:
        after_colon = header_line[colon_idx + 1:].strip()
        if after_colon and len(after_colon) > 2:
            result.append(after_colon)

    # Extract remaining lines after the header line
    remaining = impression_text[header_line_end:]
    for raw_line in remaining.split("\n"):
        stripped = raw_line.rstrip()
        if not stripped.strip():
            continue
        if _PLAN_TERMINATORS.search(stripped):
            break
        result.append(stripped)
        if len(result) >= _MAX_IMPRESSION_LINES:
            break

    return result


def _extract_plan(text: str) -> List[str]:
    """Extract plan section lines from a trauma note."""
    _, plan_start, plan_end = _find_clinical_impression_and_plan(text)
    if plan_start < 0:
        return []

    # Skip past the "Plan:" header line
    plan_text = text[plan_start:plan_end]
    m = _RE_PLAN_START.search(plan_text)
    if not m:
        return []

    content_start = plan_start + m.end()
    return _extract_section_text(
        text, content_start, plan_end,
        _PLAN_TERMINATORS, _MAX_PLAN_LINES,
    )


def _is_radiology_read(text: str) -> bool:
    """
    Heuristic: if the note text looks like a radiology read rather than
    a clinical progress note, return True. Radiology reads have
    INDICATION/FINDINGS/IMPRESSION structure with "Narrative & Impression"
    but lack the trauma progress note header.
    """
    if "Narrative & Impression" in text:
        return True
    # Check for radiology-specific pattern (INDICATION + FINDINGS + IMPRESSION)
    has_indication = bool(re.search(r"\bINDICATION\b", text[:500]))
    has_findings = bool(re.search(r"\bFINDINGS\b", text))
    if has_indication and has_findings and not _RE_QUALIFYING_HEADER.search(text):
        return True
    return False


# ── Main Extractor ─────────────────────────────────────────────────

def extract_trauma_daily_plan_by_day(
    pat_features: Dict[str, Any],
    days_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Extract per-day trauma plan from qualifying trauma team progress notes.

    Parameters
    ----------
    pat_features : dict with {"days": feature_days}
    days_data    : full patient_days_v1.json

    Returns
    -------
    Dict with per-day plan entries, total counts, and source_rule_id.
    """
    warnings: List[str] = []
    notes_meta: List[str] = []
    days_result: Dict[str, Dict[str, Any]] = {}
    total_notes = 0
    note_types_found: set = set()

    days_map = days_data.get("days") or {}

    for day_iso in sorted(days_map.keys()):
        if day_iso == "__UNDATED__":
            continue

        day_data = days_map[day_iso]
        day_notes: List[Dict[str, Any]] = []

        for item in day_data.get("items") or []:
            item_type = item.get("type", "")

            # Only PHYSICIAN_NOTE items can be trauma progress notes
            if item_type != "PHYSICIAN_NOTE":
                continue

            text = (item.get("payload") or {}).get("text", "")
            if not text:
                continue

            # Skip radiology reads
            if _is_radiology_read(text):
                continue

            # Check for qualifying note header
            note_type = _detect_note_type(text)
            if not note_type:
                continue

            # Extract author
            author = _extract_author(text)

            # Extract impression + plan
            impression_lines = _extract_impression(text)
            plan_lines = _extract_plan(text)

            if not plan_lines:
                warnings.append(
                    f"Qualifying {note_type} on {day_iso} by {author} "
                    f"has no extractable Plan section"
                )
                continue

            # Build evidence hash
            dt_str = item.get("dt", "")
            source_id = str(item.get("source_id", ""))
            preview = (plan_lines[0] if plan_lines else "")[:80]
            raw_line_id = _make_raw_line_id(source_id, dt_str, preview)

            note_entry: Dict[str, Any] = {
                "note_type": note_type,
                "author": author,
                "dt": dt_str,
                "source_id": source_id,
                "impression_lines": impression_lines,
                "plan_lines": plan_lines,
                "impression_line_count": len(impression_lines),
                "plan_line_count": len(plan_lines),
                "raw_line_id": raw_line_id,
            }

            day_notes.append(note_entry)
            note_types_found.add(note_type)
            total_notes += 1

        if day_notes:
            # Sort by dt within the day for determinism
            day_notes.sort(key=lambda n: n.get("dt", ""))
            days_result[day_iso] = {"notes": day_notes}

    # Determine source_rule_id
    if total_notes > 0:
        source_rule_id = "trauma_daily_plan_from_progress_notes"
    else:
        source_rule_id = "no_qualifying_notes"
        notes_meta.append(
            "No qualifying trauma progress notes found in timeline. "
            "This patient may not have trauma-team daily progress notes."
        )

    return {
        "days": days_result,
        "total_notes": total_notes,
        "total_days": len(days_result),
        "qualifying_note_types_found": sorted(note_types_found),
        "source_rule_id": source_rule_id,
        "warnings": warnings,
        "notes": notes_meta,
    }
