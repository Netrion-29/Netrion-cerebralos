#!/usr/bin/env python3
"""
Note Sections v1 — Structured Trauma Note Section Extraction.

Deterministic extraction of the canonical note sections from trauma notes:
  - HPI (History of Present Illness)
  - Primary Survey (Airway, Breathing, Circulation, Disability, Exposure, FAST)
  - Secondary Survey
  - Impression
  - Plan

This is Phase A1 of the Daily Notes v5 plan.  It produces structured
section text and boundaries that downstream renderers / protocol engines
can consume without re-parsing the raw note.

Source selection (priority order — earliest note preferred):
  1. TRAUMA_HP
  2. ED_NOTE
  3. PHYSICIAN_NOTE
  4. CONSULT_NOTE

Output key: ``note_sections_v1`` (under top-level ``features`` dict)

Output schema::

    {
      "sections_present": true | false | "DATA NOT AVAILABLE",
      "source_type": "TRAUMA_HP" | "ED_NOTE" | ... | null,
      "source_ts": "<ISO datetime>" | null,
      "source_rule_id": "trauma_hp_sections"
                       | "ed_note_sections"
                       | "physician_note_sections"
                       | "consult_note_sections"
                       | "no_qualifying_source"
                       | null,
      "hpi": {
        "present": true | false,
        "text": "<full extracted text>" | null,
        "line_count": <int>
      },
      "primary_survey": {
        "present": true | false,
        "text": "<full extracted text>" | null,
        "line_count": <int>,
        "fields": {
          "airway": "<text>" | null,
          "breathing": "<text>" | null,
          "circulation": "<text>" | null,
          "disability": "<text>" | null,
          "exposure": "<text>" | null,
          "fast": "<text>" | null
        }
      },
      "secondary_survey": {
        "present": true | false,
        "text": "<full extracted text>" | null,
        "line_count": <int>
      },
      "impression": {
        "present": true | false,
        "text": "<full extracted text>" | null,
        "line_count": <int>
      },
      "plan": {
        "present": true | false,
        "text": "<full extracted text>" | null,
        "line_count": <int>
      },
      "evidence": [
        {
          "raw_line_id": "<sha256 hex>",
          "source_type": "TRAUMA_HP" | ...,
          "ts": "<ISO datetime>" | null,
          "section": "hpi" | "primary_survey" | "secondary_survey"
                     | "impression" | "plan",
          "snippet": "<first 120 chars>"
        }, ...
      ],
      "notes": [ ... ],
      "warnings": [ ... ]
    }

Fail-closed behavior:
  - If no qualifying source → sections_present = "DATA NOT AVAILABLE"
  - If source exists but a section is absent → that section.present = false
  - Radiological ``IMPRESSION:`` (ALL CAPS inside Radiographs block) is
    excluded; only clinical ``Impression:`` (title case) at section level
    is captured.
  - Anna_Dennis outlier "History of Present Illness" is handled as HPI alias.

Design:
- Deterministic, fail-closed.
- No LLM, no ML, no clinical inference.
- raw_line_id required on every evidence entry.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional, Tuple

_DNA = "DATA NOT AVAILABLE"

# ── Source precedence ───────────────────────────────────────────────

_SOURCE_PRIORITY = ["TRAUMA_HP", "ED_NOTE", "PHYSICIAN_NOTE", "CONSULT_NOTE"]

_SOURCE_RULE_MAP = {
    "TRAUMA_HP": "trauma_hp_sections",
    "ED_NOTE": "ed_note_sections",
    "PHYSICIAN_NOTE": "physician_note_sections",
    "CONSULT_NOTE": "consult_note_sections",
}

# ── Section boundary regex patterns ────────────────────────────────

# HPI start — matches "HPI:" or "History of Present Illness:" (Anna Dennis outlier)
RE_HPI_START = re.compile(
    r"^(?:HPI|History\s+of\s+Present\s+Illness)\s*:",
    re.IGNORECASE | re.MULTILINE,
)
RE_HPI_END = re.compile(
    r"^(?:Primary\s+Survey|Secondary\s+Survey|PMH|Past\s+Medical|"
    r"ROS|Review\s+of\s+Systems|Allergies|Medications|Social\s+Hx|"
    r"History\s+of\s+Present|Family\s+Hx)\s*:",
    re.IGNORECASE | re.MULTILINE,
)

# Primary Survey
RE_PRIMARY_SURVEY_START = re.compile(
    r"^(?:\s*)Primary\s+Survey\s*:", re.IGNORECASE | re.MULTILINE,
)
RE_PRIMARY_SURVEY_END = re.compile(
    r"^(?:\s*)(?:Secondary\s+Survey|PMH|Past\s+Medical|ROS|"
    r"Allergies|Medications|Social\s+Hx|HPI)\s*:",
    re.IGNORECASE | re.MULTILINE,
)

# Primary Survey sub-fields (typically 12-space indented)
RE_PS_AIRWAY = re.compile(r"^\s*Airway\s*:\s*(.*)", re.IGNORECASE | re.MULTILINE)
RE_PS_BREATHING = re.compile(r"^\s*Breathing\s*:\s*(.*)", re.IGNORECASE | re.MULTILINE)
RE_PS_CIRCULATION = re.compile(r"^\s*Circulation\s*:\s*(.*)", re.IGNORECASE | re.MULTILINE)
RE_PS_DISABILITY = re.compile(r"^\s*Disability\s*:\s*(.*)", re.IGNORECASE | re.MULTILINE)
RE_PS_EXPOSURE = re.compile(r"^\s*Exposure\s*:\s*(.*)", re.IGNORECASE | re.MULTILINE)
RE_PS_FAST = re.compile(r"^\s*FAST\s*:\s*(.*)", re.IGNORECASE | re.MULTILINE)

# Secondary Survey
RE_SECONDARY_SURVEY_START = re.compile(
    r"^(?:\s*)Secondary\s+Survey\s*:", re.IGNORECASE | re.MULTILINE,
)
RE_SECONDARY_SURVEY_END = re.compile(
    r"^(?:\s*)(?:Radiographs|Labs|Impression|Assessment|Plan|"
    r"Disposition|PMH|Past\s+Medical|Medications|Allergies)\s*:",
    re.IGNORECASE | re.MULTILINE,
)

# Impression — clinical only (Title Case).  Must NOT be inside a
# Radiographs section (that uses ALL-CAPS "IMPRESSION:").
RE_IMPRESSION_START = re.compile(
    r"^(?:\s*)Impression\s*:", re.MULTILINE,
)
RE_IMPRESSION_END = re.compile(
    r"^(?:\s*)(?:Plan|Disposition|Electronically\s+signed|"
    r"Assessment\s*/?\s*Plan|A\s*/\s*P)\s*:",
    re.IGNORECASE | re.MULTILINE,
)

# Plan
RE_PLAN_START = re.compile(
    r"^(?:\s*)Plan\s*:", re.MULTILINE,
)
RE_PLAN_END = re.compile(
    r"^(?:\s*)(?:Disposition|Electronically\s+signed|"
    r"Attestation|______|Exam\s+Ended|Order\s+Details)\s*",
    re.IGNORECASE | re.MULTILINE,
)

# Assessment/Plan (fallback for non-TRAUMA_HP notes)
RE_ASSESSMENT_PLAN_START = re.compile(
    r"^(?:\s*)Assessment\s*/?\s*Plan\s*:", re.IGNORECASE | re.MULTILINE,
)

# Radiographs section — used to detect if IMPRESSION: is radiological
RE_RADIOGRAPHS_START = re.compile(
    r"^(?:\s*)Radiographs\s*:", re.IGNORECASE | re.MULTILINE,
)


# ── Helpers ─────────────────────────────────────────────────────────

def _make_raw_line_id(
    source_type: str,
    source_id: Optional[str],
    line_text: str,
) -> str:
    """Build a deterministic raw_line_id from evidence coordinates."""
    payload = f"{source_type}|{source_id or ''}|{line_text.strip()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _snippet(text: str, max_len: int = 120) -> str:
    """Trim text to a short deterministic snippet."""
    text = str(text).strip()
    if len(text) <= max_len:
        return text
    return text[:max_len] + "\u2026"


def _extract_section(
    text: str,
    start_re: re.Pattern,
    end_re: re.Pattern,
) -> Optional[str]:
    """
    Extract text between start and end patterns.

    Returns the text between the end of the start match and the
    beginning of the end match, or from start to end-of-text if
    no end pattern is found.  Returns None if start is not found.
    """
    m_start = start_re.search(text)
    if not m_start:
        return None
    rest = text[m_start.end():]
    m_end = end_re.search(rest)
    if m_end:
        return rest[: m_end.start()]
    return rest


def _is_inside_radiographs(text: str, impression_match_start: int) -> bool:
    """
    Check whether an Impression match is inside a Radiographs section.

    The radiological IMPRESSION: header appears within the Radiographs
    block (often in ALL CAPS).  We exclude it to capture only the
    clinical Impression section.
    """
    # Find the last Radiographs: header before this Impression match
    last_rad = None
    for m in RE_RADIOGRAPHS_START.finditer(text):
        if m.start() < impression_match_start:
            last_rad = m
    if last_rad is None:
        return False
    # Check whether there's a section-level header (Secondary Survey, Impression,
    # Plan, Labs) between Radiographs and this match, which would close the
    # Radiographs block.
    between = text[last_rad.end(): impression_match_start]
    # Only look for section headers that are genuinely *different* from
    # Impression itself.  Radiological sub-impressions (IMPRESSION: or
    # Impression:) that appear inside a multi-study Radiographs block
    # must NOT be treated as closing headers.
    closing = re.search(
        r"^(?:\s*)(?:Secondary\s+Survey|Plan|Labs|Assessment|Disposition)\s*:",
        between,
        re.IGNORECASE | re.MULTILINE,
    )
    return closing is None


def _extract_impression(text: str) -> Optional[str]:
    """
    Extract the clinical Impression section, skipping radiological IMPRESSION.

    Walks all Impression: matches and returns the first one that is
    NOT inside a Radiographs block.
    """
    for m in RE_IMPRESSION_START.finditer(text):
        if _is_inside_radiographs(text, m.start()):
            continue
        rest = text[m.end():]
        m_end = RE_IMPRESSION_END.search(rest)
        if m_end:
            return rest[: m_end.start()]
        return rest
    return None


def _extract_plan(text: str) -> Optional[str]:
    """
    Extract the Plan section.

    Also handles Assessment/Plan as a fallback — if no standalone Plan:
    header exists but Assessment/Plan: does, extract from there.
    """
    # Try standalone Plan: first
    plan_text = _extract_section(text, RE_PLAN_START, RE_PLAN_END)
    if plan_text is not None:
        return plan_text
    # Fallback: Assessment/Plan:
    return _extract_section(text, RE_ASSESSMENT_PLAN_START, RE_PLAN_END)


def _extract_primary_survey_fields(ps_text: str) -> Dict[str, Optional[str]]:
    """
    Extract structured sub-fields from Primary Survey text.

    Returns a dict with keys: airway, breathing, circulation,
    disability, exposure, fast.  Each value is the text after the
    sub-label, or None if not found.
    """
    fields: Dict[str, Optional[str]] = {
        "airway": None,
        "breathing": None,
        "circulation": None,
        "disability": None,
        "exposure": None,
        "fast": None,
    }
    for name, pattern in (
        ("airway", RE_PS_AIRWAY),
        ("breathing", RE_PS_BREATHING),
        ("circulation", RE_PS_CIRCULATION),
        ("disability", RE_PS_DISABILITY),
        ("exposure", RE_PS_EXPOSURE),
        ("fast", RE_PS_FAST),
    ):
        m = pattern.search(ps_text)
        if m:
            fields[name] = m.group(1).strip() or None
    return fields


def _section_line_count(text: Optional[str]) -> int:
    """Count non-blank lines in section text."""
    if not text:
        return 0
    return sum(1 for line in text.split("\n") if line.strip())


def _make_section_dict(
    text: Optional[str],
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a standardised section sub-dict."""
    present = text is not None and bool(text.strip())
    d: Dict[str, Any] = {
        "present": present,
        "text": text.strip() if present else None,
        "line_count": _section_line_count(text),
    }
    if extra:
        d.update(extra)
    return d


def _make_dna_result(reason: str) -> Dict[str, Any]:
    """Fail-closed result when no qualifying source exists."""
    empty_section: Dict[str, Any] = {
        "present": False,
        "text": None,
        "line_count": 0,
    }
    return {
        "sections_present": _DNA,
        "source_type": None,
        "source_ts": None,
        "source_rule_id": "no_qualifying_source",
        "hpi": dict(empty_section),
        "primary_survey": {
            **empty_section,
            "fields": {
                "airway": None,
                "breathing": None,
                "circulation": None,
                "disability": None,
                "exposure": None,
                "fast": None,
            },
        },
        "secondary_survey": dict(empty_section),
        "impression": dict(empty_section),
        "plan": dict(empty_section),
        "evidence": [],
        "notes": [reason],
        "warnings": ["no_qualifying_source"],
    }


# ── Main extractor ──────────────────────────────────────────────────

def extract_note_sections(
    pat_features: Dict[str, Any],
    days_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Deterministic note section extraction from timeline items.

    Parameters
    ----------
    pat_features : dict
        The in-progress patient features dict (with "days" key).
    days_data : dict
        The full patient_days_v1.json structure for raw text access.

    Returns
    -------
    dict
        note_sections_v1 contract output.
    """
    evidence: List[Dict[str, Any]] = []
    notes: List[str] = []
    warnings: List[str] = []

    days_map = days_data.get("days") or {}

    # ── Collect qualifying items, sorted by source priority + timestamp ──
    qualifying_items: List[Tuple[int, str, Dict[str, Any]]] = []
    for day_iso in sorted(days_map.keys()):
        for item in days_map[day_iso].get("items") or []:
            item_type = item.get("type", "")
            if item_type in _SOURCE_PRIORITY:
                priority = _SOURCE_PRIORITY.index(item_type)
                dt = item.get("dt", "")
                qualifying_items.append((priority, dt, item))

    # Sort: highest priority source first, then earliest timestamp
    qualifying_items.sort(key=lambda x: (x[0], x[1]))

    if not qualifying_items:
        return _make_dna_result(
            "no TRAUMA_HP, ED_NOTE, PHYSICIAN_NOTE, or CONSULT_NOTE items found"
        )

    # ── Extract sections from the best available source ──
    # Use the first qualifying item that contains at least one section.
    best_item: Optional[Dict[str, Any]] = None
    best_text: str = ""
    best_type: str = ""
    best_ts: Optional[str] = None

    for _priority, _dt, item in qualifying_items:
        item_type = item.get("type", "")
        text = (item.get("payload") or {}).get("text", "")
        if not text.strip():
            continue

        # Quick check: does this note have any recognisable section header?
        has_section = bool(
            RE_HPI_START.search(text)
            or RE_PRIMARY_SURVEY_START.search(text)
            or RE_SECONDARY_SURVEY_START.search(text)
            or RE_IMPRESSION_START.search(text)
            or RE_PLAN_START.search(text)
            or RE_ASSESSMENT_PLAN_START.search(text)
        )
        if has_section:
            best_item = item
            best_text = text
            best_type = item_type
            best_ts = item.get("dt")
            break

    if best_item is None:
        return _make_dna_result(
            "qualifying note items exist but none contain recognisable section headers"
        )

    source_id = best_item.get("source_id")
    source_rule_id = _SOURCE_RULE_MAP.get(best_type, "unknown_source")

    # ── Extract each section ─────────────────────────────────────
    hpi_text = _extract_section(best_text, RE_HPI_START, RE_HPI_END)
    ps_text = _extract_section(best_text, RE_PRIMARY_SURVEY_START, RE_PRIMARY_SURVEY_END)
    ss_text = _extract_section(best_text, RE_SECONDARY_SURVEY_START, RE_SECONDARY_SURVEY_END)
    imp_text = _extract_impression(best_text)
    plan_text = _extract_plan(best_text)

    # ── Primary Survey sub-fields ────────────────────────────────
    ps_fields = _extract_primary_survey_fields(ps_text) if ps_text else {
        "airway": None,
        "breathing": None,
        "circulation": None,
        "disability": None,
        "exposure": None,
        "fast": None,
    }

    # ── Build section dicts ──────────────────────────────────────
    hpi_dict = _make_section_dict(hpi_text)
    ps_dict = _make_section_dict(ps_text, extra={"fields": ps_fields})
    ss_dict = _make_section_dict(ss_text)
    imp_dict = _make_section_dict(imp_text)
    plan_dict = _make_section_dict(plan_text)

    sections_found = any(
        d["present"]
        for d in (hpi_dict, ps_dict, ss_dict, imp_dict, plan_dict)
    )

    # ── Evidence entries (one per section found) ─────────────────
    for sec_name, sec_text in (
        ("hpi", hpi_text),
        ("primary_survey", ps_text),
        ("secondary_survey", ss_text),
        ("impression", imp_text),
        ("plan", plan_text),
    ):
        if sec_text and sec_text.strip():
            first_line = sec_text.strip().split("\n")[0]
            evidence.append({
                "raw_line_id": _make_raw_line_id(best_type, source_id, first_line),
                "source_type": best_type,
                "ts": best_ts,
                "section": sec_name,
                "snippet": _snippet(first_line),
            })

    # ── Notes & warnings ─────────────────────────────────────────
    notes.append(f"source: {best_type} (rule: {source_rule_id})")
    if best_type != "TRAUMA_HP":
        notes.append(f"fallback source used: {best_type} (no TRAUMA_HP found)")
        warnings.append("non_trauma_hp_source")

    missing_sections = []
    for sec_name, sec_dict in (
        ("hpi", hpi_dict),
        ("primary_survey", ps_dict),
        ("secondary_survey", ss_dict),
        ("impression", imp_dict),
        ("plan", plan_dict),
    ):
        if not sec_dict["present"]:
            missing_sections.append(sec_name)
    if missing_sections:
        notes.append(f"missing sections: {', '.join(missing_sections)}")
        if len(missing_sections) >= 4:
            warnings.append("most_sections_missing")

    return {
        "sections_present": sections_found,
        "source_type": best_type,
        "source_ts": best_ts,
        "source_rule_id": source_rule_id,
        "hpi": hpi_dict,
        "primary_survey": ps_dict,
        "secondary_survey": ss_dict,
        "impression": imp_dict,
        "plan": plan_dict,
        "evidence": evidence,
        "notes": notes,
        "warnings": warnings,
    }
