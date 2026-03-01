#!/usr/bin/env python3
"""
CerebralOS — Non-Trauma Team Day Plans v1

Extracts per-day brief plan/update entries from non-trauma-team services
(hospitalist, critical care, neurosurgery, therapy, case management, etc.)
and organises them by calendar day and service.

Strategy:
  1. Iterate timeline items chronologically across all days.
  2. Select items that are NOT claimed by the trauma daily plan allowlist
     and NOT consult-notes (which are handled by consultant_day_plans).
  3. Classify each qualifying note to a service using header-text
     heuristics.
  4. Extract a brief clinical update (Assessment/Plan snippet or first
     meaningful clinical line) — no admin boilerplate.
  5. Organise results by day → service → notes.

Qualifying item types:
  - PHYSICIAN_NOTE  (when NOT matching trauma allowlist)
  - CASE_MGMT       (Plan of Care — case management, discharge planning)

Excluded (handled elsewhere or not in scope):
  - Trauma-team progress notes (→ trauma_daily_plan_by_day_v1)
  - Consultant initial notes (→ consultant_day_plans_by_day_v1)
  - Radiology reads, labs, MAR, etc. (not clinical plan notes)
  - CONSULT_NOTE items (→ consultant day plans pipeline)
  - ED_NOTE, TRIAGE, NURSING_NOTE (not plan-level content)

Output key: ``non_trauma_team_day_plans_v1``

Output schema::

    {
        "days": {
            "<ISO-date>": {
                "services": {
                    "<service-name>": {
                        "notes": [
                            {
                                "dt": "<ISO datetime>",
                                "source_id": "<item source_id>",
                                "author": "<name, credential>",
                                "service": "<service-name>",
                                "note_header": "<first meaningful header line>",
                                "brief_lines": ["line1", ...],
                                "brief_line_count": <int>,
                                "raw_line_id": "<sha256 hash>",
                            },
                            ...
                        ],
                        "note_count": <int>,
                    },
                    ...
                },
                "service_count": <int>,
                "note_count": <int>,
            },
            ...
        },
        "total_days": <int>,
        "total_notes": <int>,
        "total_services": <int>,
        "services_seen": ["<service>", ...],
        "source_rule_id": "non_trauma_day_plans_extracted"
                        | "no_qualifying_notes",
        "warnings": [],
        "notes": [],
    }

Fail-closed:
  - If no qualifying notes found → source_rule_id = "no_qualifying_notes",
    days = {}, total_notes = 0.
  - Deterministic: same input → same output, always.

Design:
  - Deterministic, fail-closed.
  - No LLM, no ML, no clinical inference.
  - Evidence preserved via raw_line_id (SHA-256 hash).
  - Brief updates only — no full note text, no admin boilerplate.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

# ── Constants ──────────────────────────────────────────────────────
_DNA = "DATA NOT AVAILABLE"

# ── Trauma note allowlist (inverse match = non-trauma) ─────────────
# Mirrors the allowlist in trauma_daily_plan_by_day_v1.py.
# Any PHYSICIAN_NOTE matching these headers belongs to trauma-team
# and is NOT processed here.
_RE_TRAUMA_HEADER = re.compile(
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
    r"|ESA\s+Short\s+Progress\s+Note"
    r")\s*:?\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# ── Radiology read heuristic ──────────────────────────────────────
_RE_RADIOLOGY_HEURISTIC = re.compile(
    r"Narrative\s*&\s*Impression|\bINDICATION\b.*\bFINDINGS\b",
    re.IGNORECASE | re.DOTALL,
)

# Additional radiology patterns: notes starting with a radiology
# IMPRESSION line or containing Result Date + imaging study names.
_RE_RADIOLOGY_CONTENT = re.compile(
    r"^IMPRESSION:\s"
    r"|\bResult\s+Date:\s"
    r"|^(?:CT|CTA|XR|MRI|MRA)\s+(?:HEAD|CHEST|CERVICAL|MAXILLOFACIAL|ABDOMEN|PELVIS|SPINE)",
    re.IGNORECASE | re.MULTILINE,
)

# ── Medication order / MAR heuristic ──────────────────────────────
_RE_MEDICATION_ORDER = re.compile(
    r"^\[(?:DISCONTINUED|COMPLETED|ACTIVE)\]"
    r"|^\s*\d+\.?\d*\s+(?:mcg|mg|mL|units?)\b"
    r"|New\s+Bag\(Override\)"
    r"|Order\s+Audit\s+Trail"
    r"|^\s*(?:Intravenous|Oral|Subcutaneous|Intramuscular)\s*$"
    r"|^\s*Q\d+\s*(?:Min|H|HR)\s",
    re.IGNORECASE | re.MULTILINE,
)

# ── Service detection patterns ─────────────────────────────────────
# Applied to the first ~500 chars of the note text (header area).
# Order matters: first match wins.  More specific patterns first.
_SERVICE_HEADER_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("Hospitalist", re.compile(
        r"Deaconess\s+Care\s+Group|Hospital\s+Progress\s+Note|Hospitalist",
        re.IGNORECASE)),
    ("Critical Care", re.compile(
        r"Pulmonary\s*/?\s*(?:&\s*)?Critical\s+Care"
        r"|Critical\s+Care\s+(?:on-call|coverage|progress|Medicine)"
        r"|PCCM\b"
        r"|Intensivist\s+Progress"
        r"|Brain\s+Death",
        re.IGNORECASE)),
    ("Neurosurgery", re.compile(
        r"Neurosurgery\s*[-–—]"
        r"|Neurosurgical\s+(?:Progress|Consult)"
        r"|^\s*N/S\s*$",
        re.IGNORECASE | re.MULTILINE)),
    ("Nutrition/Dietitian", re.compile(
        r"Nutrition\s+(?:assessment|Follow\s*-?\s*Up)"
        r"|Registered\s+Dietitian"
        r"|,\s*RD\s*$"
        r"|tube\s+feedings?\b",
        re.IGNORECASE | re.MULTILINE)),
    ("Neurology", re.compile(
        r"(?:General\s+)?Neurology\s+(?:Inpatient|Progress|Consult)",
        re.IGNORECASE)),
    ("Physical Therapy", re.compile(
        r"PHYSICAL\s+THERAPY|PT\s+(?:Eval|Treatment|Progress|Assessment)"
        r"|EARLY\s+MOBILITY(?!\s*-\s*(?:OT|ASSESSMENT))",
        re.IGNORECASE)),
    ("Occupational Therapy", re.compile(
        r"OCCUPATIONAL\s+THERAPY|OT\s+(?:Eval|Treatment|Progress|Assessment)"
        r"|EARLY\s+MOBILITY\s*-\s*(?:OT|ASSESSMENT)",
        re.IGNORECASE)),
    ("Speech Language Pathology", re.compile(
        r"Speech\s+Language\s+Pathology|SLP\s+(?:Eval|Assessment|Progress)"
        r"|Clinical\s+Swallow\s+Evaluation|Dementia\s+Screening",
        re.IGNORECASE)),
    ("Wound/Ostomy", re.compile(
        r"Wound\s+(?:Care|Ostomy)|WOCN\b",
        re.IGNORECASE)),
    ("Palliative Care", re.compile(
        r"Palliative\s+(?:Care|Medicine)",
        re.IGNORECASE)),
    ("Case Management", re.compile(
        r"Case\s+Manag(?:er|ement)|Discharge\s+Planning|Social\s+Work",
        re.IGNORECASE)),
    ("Respiratory Therapy", re.compile(
        r"Respiratory\s+Therapy|RT\s+(?:Progress|Assessment)",
        re.IGNORECASE)),
    ("Cardiology", re.compile(
        r"Cardiology\s+(?:Progress|Consult|Note)",
        re.IGNORECASE)),
    ("Infectious Disease", re.compile(
        r"Infectious\s+Disease|ID\s+(?:Progress|Consult)",
        re.IGNORECASE)),
    ("Pastoral Care", re.compile(
        r"Pastoral\s+Care|Chaplain",
        re.IGNORECASE)),
]

# ── Brief update extraction ────────────────────────────────────────
# Assessment / Plan section start
_RE_ASSESSMENT_PLAN = re.compile(
    r"^\s*(?:Assessment|Impression|A/P|Plan|Assessment\s*/?\s*Plan)\s*:",
    re.IGNORECASE | re.MULTILINE,
)

# Terminators — stop extracting brief lines at these
_RE_BRIEF_TERMINATORS = re.compile(
    r"(?:"
    r"I have seen and examined patient"
    r"|MyChart now allows"
    r"|Revision History"
    r"|Expand All Collapse All"
    r"|Electronically\s+signed"
    r"|Toggle\s+Section"
    r"|Cosigned\s+by"
    r"|This\s+encounter\s+was"
    r"|Patient\s+Active\s+Problem"
    r")",
    re.IGNORECASE,
)

# Noise lines to skip (admin/boilerplate)
_RE_NOISE_LINE = re.compile(
    r"^\s*$"
    r"|^\s*Revision\s*History"
    r"|^\s*Toggle\s+Section"
    r"|^\s*Expand\s+All"
    r"|^\s*Collapse\s+All"
    r"|^\s*[-_=]{5,}\s*$"
    r"|^\s*Electronically\s+signed"
    r"|^\s*Cosigned\s+by"
    r"|^\s*MyChart\s+now\s+allows"
    r"|^\s*DEA\s*#\s*:"
    r"|^\s*Ordering\s+User\s*:",
    re.IGNORECASE,
)

# Author/signature line pattern
_RE_SIGNATURE_LINE = re.compile(
    r"^\s*[A-Z][a-z]+(?:\s+[A-Z]\.?)?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?"
    r",\s*(?:PA-C|NP|MD|DO|PA|RN|APRN|ARNP|FNP|CNP)\s*$",
    re.MULTILINE,
)

# Maximum brief lines per note
_MAX_BRIEF_LINES = 12

# Item types to process
_QUALIFYING_ITEM_TYPES = frozenset({"PHYSICIAN_NOTE", "CASE_MGMT"})

# Notes to skip entirely (pharmacy, brief event notations, etc.)
_RE_SKIP_NOTE = re.compile(
    r"^\s*DEA\s*#\s*:"
    r"|^\s*Ordering\s+User\s*:"
    r"|^\s*On-call\s+NP\s+notified\s+by\s+RN",
    re.IGNORECASE | re.MULTILINE,
)

# Minimum meaningful content threshold: notes with fewer than this
# many non-blank, non-noise lines are skipped as too brief or noise.
_MIN_MEANINGFUL_LINES = 2


# ── Helpers ────────────────────────────────────────────────────────

def _make_raw_line_id(source_id: str, dt: str, preview: str) -> str:
    """Deterministic SHA-256 hash for evidence tracing."""
    payload = f"{source_id}|{dt}|{preview}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _is_trauma_note(text: str) -> bool:
    """Return True if text matches the trauma daily plan allowlist."""
    if _RE_TRAUMA_HEADER.search(text):
        # Also gate "Daily Progress Note" by ESA affiliation
        m = _RE_TRAUMA_HEADER.search(text)
        matched = m.group(0).strip().rstrip(":").lower()  # type: ignore[union-attr]
        if matched == "daily progress note":
            return bool(re.search(
                r"Evansville\s+Surgical\s+Assoc",
                text[:600],
                re.IGNORECASE,
            ))
        return True
    return False


def _is_radiology_read(text: str) -> bool:
    """Heuristic: if the note looks like a radiology read, return True."""
    if "Narrative & Impression" in text:
        return True
    has_indication = bool(re.search(r"\bINDICATION\b", text[:500]))
    has_findings = bool(re.search(r"\bFINDINGS\b", text))
    if has_indication and has_findings:
        return True
    # Catch notes that contain IMPRESSION: + imaging study names anywhere
    if _RE_RADIOLOGY_CONTENT.search(text):
        return True
    # If IMPRESSION: appears in the first 300 chars, treat as radiology
    if re.search(r"^IMPRESSION\s*:", text[:300], re.IGNORECASE | re.MULTILINE):
        return True
    return False


def _is_medication_order(text: str) -> bool:
    """Heuristic: if the note is a medication order / MAR entry, return True."""
    return bool(_RE_MEDICATION_ORDER.search(text[:500]))


def _detect_service(text: str, item_type: str) -> Optional[str]:
    """Detect the originating service from note header text.

    Returns the service name or None if the note should be skipped.
    """
    # CASE_MGMT items are always Case Management
    if item_type == "CASE_MGMT":
        return "Case Management"

    header_area = text[:500]

    # Skip pharmacy/prescription records misclassified as progress notes
    if _RE_SKIP_NOTE.search(header_area):
        return None

    for service_name, pattern in _SERVICE_HEADER_PATTERNS:
        if pattern.search(header_area):
            return service_name

    # Fallback: if we can't identify the service, label it generically
    # but still include it (fail-open for non-trauma classification,
    # fail-closed for data quality)
    return "Other Physician"


def _extract_author(text: str) -> str:
    """Extract author name from the header area of a note."""
    header_area = text[:400]
    m = _RE_SIGNATURE_LINE.search(header_area)
    if m:
        return m.group(0).strip()
    return _DNA


def _extract_note_header(text: str) -> str:
    """Extract a short identifying header from the first meaningful line."""
    lines = text.split("\n")
    for ln in lines[:8]:
        stripped = ln.strip()
        if not stripped:
            continue
        if len(stripped) < 3:
            continue
        if _RE_NOISE_LINE.match(stripped):
            continue
        # Return first meaningful line, truncated
        return stripped[:100]
    return "Unknown"


def _extract_brief_lines(text: str) -> List[str]:
    """Extract a brief clinical update from the note.

    Prefers Assessment/Plan section content.  Falls back to the first
    meaningful clinical lines after the header area.
    """
    # Try to find Assessment/Plan section
    m = _RE_ASSESSMENT_PLAN.search(text)
    if m:
        section_start = m.start()
        # Extract lines after the header
        section_text = text[section_start:]
        lines = section_text.split("\n")
        result: List[str] = []
        for raw_line in lines:
            stripped = raw_line.rstrip()
            if _RE_BRIEF_TERMINATORS.search(stripped):
                break
            if _RE_SIGNATURE_LINE.match(stripped):
                break
            if not stripped.strip():
                continue
            if _RE_NOISE_LINE.match(stripped):
                continue
            result.append(stripped)
            if len(result) >= _MAX_BRIEF_LINES:
                break
        if result:
            return result

    # Fallback: extract first meaningful lines after the header area
    lines = text.split("\n")
    result = []
    # Skip the first few lines (header), start extracting from line 3+
    for ln in lines[3:]:
        stripped = ln.rstrip()
        if _RE_BRIEF_TERMINATORS.search(stripped):
            break
        if _RE_SIGNATURE_LINE.match(stripped):
            break
        if not stripped.strip():
            continue
        if _RE_NOISE_LINE.match(stripped):
            continue
        result.append(stripped)
        if len(result) >= _MAX_BRIEF_LINES:
            break

    return result


# ── Main Extractor ─────────────────────────────────────────────────

def extract_non_trauma_team_day_plans(
    pat_features: Dict[str, Any],
    days_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Extract per-day non-trauma-team plan/update entries.

    Parameters
    ----------
    pat_features : dict with {"days": feature_days}
    days_data    : full patient_days_v1.json

    Returns
    -------
    Dict with per-day, per-service note entries, total counts,
    and source_rule_id.
    """
    warnings: List[str] = []
    notes_meta: List[str] = []
    total_notes = 0
    all_services: Set[str] = set()

    # day_iso → service → list of note dicts
    day_service_notes: Dict[str, Dict[str, List[Dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )

    days_map = days_data.get("days") or {}

    for day_iso in sorted(days_map.keys()):
        if day_iso == "__UNDATED__":
            continue

        day_data = days_map[day_iso]

        for item in day_data.get("items") or []:
            item_type = item.get("type", "")

            # Only process qualifying item types
            if item_type not in _QUALIFYING_ITEM_TYPES:
                continue

            text = (item.get("payload") or {}).get("text", "")
            if not text.strip():
                continue

            # For PHYSICIAN_NOTE: skip if it matches trauma allowlist
            if item_type == "PHYSICIAN_NOTE":
                if _is_trauma_note(text):
                    continue
                if _is_radiology_read(text):
                    continue
                if _is_medication_order(text):
                    continue

            # Detect service from header
            service = _detect_service(text, item_type)
            if service is None:
                continue  # skip unclassifiable (pharmacy, etc.)

            # Extract brief update
            brief_lines = _extract_brief_lines(text)
            if not brief_lines:
                # No meaningful clinical content extracted
                continue
            if len(brief_lines) < _MIN_MEANINGFUL_LINES:
                # Too brief to be a useful clinical update
                continue

            # Extract author and header
            author = _extract_author(text)
            note_header = _extract_note_header(text)

            # Build evidence hash
            dt_str = item.get("dt", "")
            source_id = str(item.get("source_id", ""))
            preview = (brief_lines[0] if brief_lines else "")[:80]
            raw_line_id = _make_raw_line_id(source_id, dt_str, preview)

            note_entry: Dict[str, Any] = {
                "dt": dt_str,
                "source_id": source_id,
                "author": author,
                "service": service,
                "note_header": note_header,
                "brief_lines": brief_lines,
                "brief_line_count": len(brief_lines),
                "raw_line_id": raw_line_id,
            }

            day_service_notes[day_iso][service].append(note_entry)
            all_services.add(service)
            total_notes += 1

    # ── Build output structure ──────────────────────────────────
    days_result: Dict[str, Dict[str, Any]] = {}

    for day_iso in sorted(day_service_notes.keys()):
        service_map = day_service_notes[day_iso]
        services_out: Dict[str, Dict[str, Any]] = {}
        day_note_count = 0

        for svc_name in sorted(service_map.keys()):
            svc_notes = service_map[svc_name]
            # Sort by dt for determinism
            svc_notes.sort(key=lambda n: n.get("dt", ""))

            services_out[svc_name] = {
                "notes": svc_notes,
                "note_count": len(svc_notes),
            }
            day_note_count += len(svc_notes)

        days_result[day_iso] = {
            "services": services_out,
            "service_count": len(services_out),
            "note_count": day_note_count,
        }

    # ── Determine source_rule_id ────────────────────────────────
    if total_notes > 0:
        source_rule_id = "non_trauma_day_plans_extracted"
    else:
        source_rule_id = "no_qualifying_notes"
        notes_meta.append(
            "No qualifying non-trauma-team notes found in timeline. "
            "This patient may only have trauma-team progress notes."
        )

    return {
        "days": days_result,
        "total_days": len(days_result),
        "total_notes": total_notes,
        "total_services": len(all_services),
        "services_seen": sorted(all_services),
        "source_rule_id": source_rule_id,
        "warnings": warnings,
        "notes": notes_meta,
    }
