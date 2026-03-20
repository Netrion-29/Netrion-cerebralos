#!/usr/bin/env python3
"""
Procedure / Operative Events Extraction v1 for CerebralOS.

Deterministic extraction of structured procedure, operative, and
anesthesia events from timeline items whose ``type`` (kind) explicitly
maps to a procedural category.

Recognised item kinds (emitted by parse_patient_txt):

  PROCEDURE, OP_NOTE, PRE_PROCEDURE,
  ANESTHESIA_PREPROCEDURE, ANESTHESIA_PROCEDURE,
  ANESTHESIA_POSTPROCEDURE, ANESTHESIA_FOLLOWUP,
  ANESTHESIA_CONSULT,
  SIGNIFICANT_EVENT

For each qualifying item the extractor captures:
  ts, source_kind, category, label, status (if explicit), evidence[].

For anesthesia-record-style content, explicit event-timeline milestones
are captured when present:
  Anesthesia Start/Stop, Induction, Intubation/Extubation,
  Incision, Tourniquet Inflated/Deflated, Emergence.

**This module does NOT extract:**
  - Inferred procedures from narrative text.
  - Anesthesia physiologic metrics (temp, EBL, med doses) — deferred
    to ``anesthesia-case-metrics-v1``.
  - Green-card procedure list or spine/tourniquet fields (those live
    in a separate layer with a different shape).

Fail-closed: returns empty events[] when no qualifying items exist.
Every event carries evidence traceability via raw_line_id / item_ref.

Output key: ``procedure_operatives_v1``
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

_DNA = "DATA NOT AVAILABLE"

# ── Kind → category mapping ────────────────────────────────────────

_KIND_CATEGORY: Dict[str, str] = {
    "PROCEDURE":                "operative",
    "OP_NOTE":                  "operative",
    "PRE_PROCEDURE":            "pre-op",
    "ANESTHESIA_PREPROCEDURE":  "anesthesia",
    "ANESTHESIA_PROCEDURE":     "anesthesia",
    "ANESTHESIA_POSTPROCEDURE": "anesthesia",
    "ANESTHESIA_FOLLOWUP":      "anesthesia",
    "ANESTHESIA_CONSULT":       "anesthesia",
    "SIGNIFICANT_EVENT":        "significant_event",
}

# Set of all kinds we consume (for fast membership test)
_PROC_KINDS = frozenset(_KIND_CATEGORY.keys())


# ── Label extraction regex ─────────────────────────────────────────
# Matches explicit procedure/operation headings in note text.
# Goal: capture the first explicit label from structured headings.

# "Procedure: <label>" or "Operation: <label>" (colon-delimited)
_RE_PROCEDURE_LABEL = re.compile(
    r"(?:^|\|)\s*(?:Procedure|Operation|Operative Procedure|"
    r"Block type)\s*[:]\s*(.+?)(?:\||$)",
    re.IGNORECASE,
)

# Title-like headings at start of text body:
#   "EMERGENT ENDOTRACHEAL INTUBATION"
#   "Bronchoscopy Procedure Note"
#   "Operative Notation"
#   "Chest Ultrasound"
_RE_HEADING_LABEL = re.compile(
    r"(?:^|\|)\s*(?:Signed|Attested|Addendum)\s*\|*\s*\|+"
    r"\s*(.+?)(?:\||$)",
    re.IGNORECASE,
)

# "Pre-op Dx" / "PreOp Dx" line → use as secondary label context
_RE_PREOP_DX = re.compile(
    r"(?:^|\|)\s*Pre[- ]?[Oo]p(?:erative)?\s+D(?:iagnos[ie]s|x)\s*[:]\s*(.+?)(?:\||$)",
    re.IGNORECASE,
)

# Date of Procedure / Date of Operation → not a label but confirms
# the item is a procedure note.
_RE_DATE_OF_PROCEDURE = re.compile(
    r"(?:^|\|)\s*Date\s+of\s+(?:Procedure|Operation|Patient Encounter)\s*[:]\s*(.+?)(?:\||$)",
    re.IGNORECASE,
)

# Status patterns: Completed, Cancelled, etc.
_RE_STATUS = re.compile(
    r"(?:^|\|)\s*(?:Status|Case Status|Procedure Status)\s*[:]\s*(Completed|Cancelled|Canceled|Aborted|In Progress)",
    re.IGNORECASE,
)

# ── Anesthesia milestone patterns ──────────────────────────────────
# Each pattern → (milestone_label, regex)
# These capture explicit timestamped milestones from anesthesia records.

_ANESTHESIA_MILESTONES: List[Tuple[str, re.Pattern]] = [
    ("anesthesia_start", re.compile(
        r"(?:^|\|)\s*Anesthesia\s+Start\s*[:]\s*(\d{1,2}[:/]\d{2}(?:\s*[AP]M)?|\d{4})",
        re.IGNORECASE)),
    ("anesthesia_stop", re.compile(
        r"(?:^|\|)\s*Anesthesia\s+(?:Stop|End)\s*[:]\s*(\d{1,2}[:/]\d{2}(?:\s*[AP]M)?|\d{4})",
        re.IGNORECASE)),
    ("induction", re.compile(
        r"(?:^|\|)\s*Induction\s*[:]\s*(\d{1,2}[:/]\d{2}(?:\s*[AP]M)?|\d{4})",
        re.IGNORECASE)),
    ("intubation", re.compile(
        r"(?:^|\|)\s*(?:Intubation|ETT Placement)\s*[:]\s*(\d{1,2}[:/]\d{2}(?:\s*[AP]M)?|\d{4})",
        re.IGNORECASE)),
    ("extubation", re.compile(
        r"(?:^|\|)\s*Extubation\s*[:]\s*(\d{1,2}[:/]\d{2}(?:\s*[AP]M)?|\d{4})",
        re.IGNORECASE)),
    ("incision", re.compile(
        r"(?:^|\|)\s*(?:Incision|Surgical Start)\s*[:]\s*(\d{1,2}[:/]\d{2}(?:\s*[AP]M)?|\d{4})",
        re.IGNORECASE)),
    ("tourniquet_inflated", re.compile(
        r"(?:^|\|)\s*Tourniquet\s+Inflat(?:ed|ion)\s*[:]\s*(\d{1,2}[:/]\d{2}(?:\s*[AP]M)?|\d{4})",
        re.IGNORECASE)),
    ("tourniquet_deflated", re.compile(
        r"(?:^|\|)\s*Tourniquet\s+Deflat(?:ed|ion)\s*[:]\s*(\d{1,2}[:/]\d{2}(?:\s*[AP]M)?|\d{4})",
        re.IGNORECASE)),
    ("emergence", re.compile(
        r"(?:^|\|)\s*Emergence\s*[:]\s*(\d{1,2}[:/]\d{2}(?:\s*[AP]M)?|\d{4})",
        re.IGNORECASE)),
]


# ── CPT code extraction ────────────────────────────────────────────
# Matches explicit "CPT <5-digit>" when the token "CPT" is preceded by
# a word boundary (not part of a longer word like "VEST CPT" which is
# chest physiotherapy).  Requires exactly 5 digits (standard CPT-4).
_RE_CPT_CODE = re.compile(
    r"(?<![A-Za-z])CPT\s*#?\s*:?\s*(\d{5})\b",
    re.IGNORECASE,
)


# ── Anesthesia detail extraction ───────────────────────────────────
# Simple key:value extraction for anesthesia type, ASA status, airway

_RE_ANESTHESIA_TYPE = re.compile(
    r"(?:^|\|)\s*Anesthesia\s+(?:Type|Plan)\s*[:]\s*(.+?)(?:\||$)",
    re.IGNORECASE,
)
_RE_ASA_STATUS = re.compile(
    r"(?:^|\|)\s*ASA\s+(?:Status|Class|Classification)\s*[:]\s*(\d+\w*)",
    re.IGNORECASE,
)


# ── Helpers ────────────────────────────────────────────────────────

def _clean_label(raw: str) -> str:
    """Trim and normalise a procedure label."""
    label = raw.strip()
    # Remove trailing pipe / whitespace
    label = label.rstrip("|").strip()
    # Collapse multiple spaces
    label = re.sub(r"\s{2,}", " ", label)
    # Cap length for sanity
    if len(label) > 200:
        label = label[:200] + "…"
    return label


def _extract_cpt_codes(text: str) -> List[str]:
    """Extract explicit CPT codes from procedure text.

    Returns a deduplicated list of 5-digit CPT code strings in
    encounter order.  Only codes preceded by the literal token
    "CPT" are captured — never inferred from procedure names.
    Fail-closed: returns [] when no explicit CPT is present.
    """
    seen: set[str] = set()
    codes: List[str] = []
    for m in _RE_CPT_CODE.finditer(text):
        # Guard: reject "VEST CPT" (chest physiotherapy)
        start = m.start()
        prefix = text[max(0, start - 5):start].strip().upper()
        if prefix.endswith("VEST"):
            continue
        code = m.group(1)
        if code not in seen:
            seen.add(code)
            codes.append(code)
    return codes


def _extract_label(text: str) -> Optional[str]:
    """
    Extract the best explicit procedure label from item text.

    Priority:
      1. "Procedure:" / "Operation:" / "Block type:" line
      2. Heading after "Signed|Attested|Addendum" marker
      3. None (fail-closed)
    """
    # Try Procedure/Operation label lines
    m = _RE_PROCEDURE_LABEL.search(text)
    if m:
        candidate = _clean_label(m.group(1))
        if candidate and len(candidate) > 2:
            return candidate

    # Try heading label
    m = _RE_HEADING_LABEL.search(text)
    if m:
        candidate = _clean_label(m.group(1))
        # Filter out noise headings
        if candidate and len(candidate) > 2 and not re.match(
            r"^(?:Patient|Expand|Collapse|Note|Alert)", candidate, re.IGNORECASE
        ):
            return candidate

    return None


def _extract_preop_dx(text: str) -> Optional[str]:
    """Extract Pre-op Diagnosis if explicitly documented."""
    m = _RE_PREOP_DX.search(text)
    if m:
        dx = _clean_label(m.group(1))
        if dx and len(dx) > 2:
            return dx
    return None


def _extract_status(text: str) -> Optional[str]:
    """Extract explicit procedure status (completed/cancelled/etc.)."""
    m = _RE_STATUS.search(text)
    if m:
        return m.group(1).strip().lower()
    return None


def _extract_milestones(text: str) -> List[Dict[str, str]]:
    """
    Extract anesthesia milestone events with explicit timestamps.

    Returns list of {"milestone": label, "time_raw": raw_time_str}.
    Only explicit structured milestones are captured (not narrative).
    """
    milestones: List[Dict[str, str]] = []
    for label, pat in _ANESTHESIA_MILESTONES:
        m = pat.search(text)
        if m:
            milestones.append({
                "milestone": label,
                "time_raw": m.group(1).strip(),
            })
    return milestones


def _extract_anesthesia_details(text: str) -> Dict[str, Optional[str]]:
    """Extract anesthesia type and ASA status."""
    details: Dict[str, Optional[str]] = {
        "anesthesia_type": None,
        "asa_status": None,
    }
    m = _RE_ANESTHESIA_TYPE.search(text)
    if m:
        details["anesthesia_type"] = _clean_label(m.group(1))
    m = _RE_ASA_STATUS.search(text)
    if m:
        details["asa_status"] = m.group(1).strip()
    return details


def _make_item_ref(day_iso: str, item_idx: int) -> str:
    """Create an item reference string for evidence traceability."""
    return f"item:{day_iso}:{item_idx}"


# ── Core extraction ───────────────────────────────────────────────

def extract_procedure_operatives(
    pat_features: Dict[str, Any],
    days_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Extract structured procedure/operative events from patient timeline.

    Parameters
    ----------
    pat_features : dict
        ``{"days": feature_days}`` — standard pattern (currently unused
        but follows convention).
    days_data : dict
        Full ``patient_days_v1.json`` dict.

    Returns
    -------
    dict
        Output under key ``procedure_operatives_v1`` with:
        events[], procedure_event_count, operative_event_count,
        anesthesia_event_count, categories_present[], evidence[],
        warnings[], notes[], source_rule_id.
    """
    days_map = days_data.get("days") or {}
    warnings: List[str] = []
    notes: List[str] = []
    events: List[Dict[str, Any]] = []
    evidence: List[Dict[str, Any]] = []

    for day_iso in sorted(days_map.keys()):
        day_info = days_map[day_iso]
        items = day_info.get("items") or []

        for item_idx, item in enumerate(items):
            kind = item.get("type", "")
            if kind not in _PROC_KINDS:
                continue

            ts_raw = item.get("dt") or None
            payload = item.get("payload") or {}
            text = payload.get("text", "")
            raw_line_id = item.get("raw_line_id")

            # Use pipe-delimited text for regex (pipe = newline in some
            # timeline items); also try original newlines
            text_for_regex = text.replace("\n", "|")

            category = _KIND_CATEGORY[kind]
            label = _extract_label(text_for_regex)
            status = _extract_status(text_for_regex)
            preop_dx = _extract_preop_dx(text_for_regex)
            cpt_codes = _extract_cpt_codes(text_for_regex)

            # Build item reference for evidence
            item_ref = _make_item_ref(day_iso, item_idx)
            if raw_line_id is None:
                raw_line_id = item_ref

            # Anesthesia milestones (only for anesthesia kinds)
            milestones: List[Dict[str, str]] = []
            anesthesia_details: Dict[str, Optional[str]] = {}
            if category == "anesthesia":
                milestones = _extract_milestones(text_for_regex)
                anesthesia_details = _extract_anesthesia_details(text_for_regex)

            event: Dict[str, Any] = {
                "ts": ts_raw,
                "source_kind": kind,
                "category": category,
                "label": label,
                "raw_line_id": raw_line_id,
                "evidence": [{
                    "role": "procedure_event",
                    "snippet": text[:120].replace("\n", " ").strip(),
                    "raw_line_id": raw_line_id,
                }],
            }

            # Optional fields — only include when present
            if status:
                event["status"] = status
            if preop_dx:
                event["preop_dx"] = preop_dx
            if milestones:
                event["milestones"] = milestones
            if anesthesia_details.get("anesthesia_type"):
                event["anesthesia_type"] = anesthesia_details["anesthesia_type"]
            if anesthesia_details.get("asa_status"):
                event["asa_status"] = anesthesia_details["asa_status"]
            if cpt_codes:
                event["cpt_codes"] = cpt_codes

            events.append(event)

            # Top-level evidence for contract validation
            evidence.append({
                "role": "procedure_event",
                "snippet": (
                    f"{ts_raw or '?'} {kind} "
                    f"{label or '(no label)'}"
                )[:120],
                "raw_line_id": raw_line_id,
            })

    # ── Summary counts ─────────────────────────────────────────
    procedure_count = sum(
        1 for e in events if e["source_kind"] == "PROCEDURE"
    )
    operative_count = sum(
        1 for e in events if e["source_kind"] == "OP_NOTE"
    )
    anesthesia_count = sum(
        1 for e in events if e["category"] == "anesthesia"
    )
    categories = sorted(set(e["category"] for e in events))

    if not events:
        notes.append("no_procedure_operative_events_found")

    return {
        "events": events,
        "procedure_event_count": procedure_count,
        "operative_event_count": operative_count,
        "anesthesia_event_count": anesthesia_count,
        "categories_present": categories,
        "evidence": evidence,
        "warnings": warnings,
        "notes": notes,
        "source_rule_id": "procedure_operatives_v1",
    }
