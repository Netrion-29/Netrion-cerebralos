#!/usr/bin/env python3
"""
Consultant Events v1 — Structured Consultant-Service Involvement Extraction.

Deterministic extraction of consultant-service involvement from the
``note_index_events_v1`` feature output.  Identifies which specialist
consultant services were involved during the encounter, with timing,
note counts, and author details.

This is an event-index-based feature — it does NOT parse note bodies
or extract consultant recommendations (that is ``consultant_plan_items_v1``).

Source:
  ``note_index_events_v1`` entries (already extracted from raw data).
  No raw-file rereads needed.

Consultant detection rules:
  1. **note_type == "Consults"** with a service NOT in the exclusion set
     → always a consultant entry.
  2. **note_type == "Progress Notes"** with an explicit service NOT in
     the exclusion set → consultant follow-up entry.
  3. All other note types are excluded (ED Notes, ED Provider Notes,
     Triage Assessment, H&P, Discharge Summary, Plan of Care).

Non-consultant service exclusion set:
  - General Surgeon (primary trauma service)
  - Hospitalist (co-management, not specialist consultant)
  - Physician to Physician (handoff note)
  - Nurse to Nurse (nursing handoff)
  - Case Manager (case management)
  - Emergency (ED staff)
  - Surgery (alias for primary surgical service)

Output key: ``consultant_events_v1``

Output schema::

    {
      "consultant_present": "yes" | "no" | "DATA NOT AVAILABLE",
      "consultant_services_count": <int>,
      "consultant_services": [
        {
          "service": "Otolaryngology",
          "first_ts": "01/01 1020",
          "last_ts": "01/01 1020",
          "note_count": 1,
          "authors": ["Chacko, Chris E"],
          "note_types": ["Consults"],
          "evidence": [
            {
              "role": "consultant_event",
              "snippet": "...",
              "raw_line_id": "<sha256>"
            }
          ]
        }, ...
      ],
      "source_rule_id": "consultant_events_from_note_index"
                       | "no_note_index_available"
                       | "no_consultant_entries",
      "warnings": [...],
      "notes": [...]
    }

Fail-closed behaviour:
  - No ``note_index_events_v1`` feature → consultant_present="DATA NOT AVAILABLE",
    source_rule_id="no_note_index_available"
  - Note index present but 0 consultant entries → consultant_present="no",
    source_rule_id="no_consultant_entries"
  - Note index present with consultant entries → consultant_present="yes",
    source_rule_id="consultant_events_from_note_index"

Design:
- Deterministic, fail-closed.
- No LLM, no ML, no clinical inference.
- raw_line_id preserved from note_index_events entries.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional, Set

_DNA = "DATA NOT AVAILABLE"

# ── Note types that can indicate consultant involvement ────────────
_CONSULTANT_NOTE_TYPES: Set[str] = {
    "Consults",
    "Progress Notes",
}

# ── Services excluded from consultant classification ───────────────
# These represent primary trauma/hospitalist/nursing/case management
# roles, not specialist consultant services.
_NON_CONSULTANT_SERVICES: Set[str] = {
    "general surgeon",
    "hospitalist",
    "physician to physician",
    "nurse to nurse",
    "case manager",
    "emergency",
    "surgery",
}

# ── Note types that are NEVER consultant regardless of service ─────
# Only "Consults" and "Progress Notes" are eligible.
# Everything else (ED Notes, H&P, Triage, Discharge Summary,
# Plan of Care, ED Provider Notes) is excluded.

# ── Service extraction from CONSULT_NOTE text (fallback path) ─────
# Pattern: "consult to <SERVICE> [order_id]" or "Consult To <SERVICE>"
_CONSULT_TO_RE = re.compile(
    r"[Cc]onsult\s+[Tt]o\s+([A-Z][A-Za-z/& ]+?)(?:\s*[\[(\n]|\s+ordered\s+by)",
)
# Pattern: "<SERVICE> Consult Note" or "<SERVICE> Consult" as a heading
_CONSULT_HEADING_RE = re.compile(
    r"^([A-Z][A-Za-z ]+?)\s+Consult(?:\s+Note)?\s*$",
    re.MULTILINE,
)

# ── Service name normalization for fallback path ───────────────────
_SERVICE_ALIASES: Dict[str, str] = {
    "orthopedic surgery": "Orthopedic Surgery",
    "ortho": "Orthopedic Surgery",
    "orthopedics": "Orthopedic Surgery",
    "vascular surgery": "Vascular Surgery",
    "vascular": "Vascular Surgery",
    "neurosurgery": "Neurosurgery",
    "pulmonology": "Pulmonology",
    "ent": "ENT",
    "infection control": "Infection Control",
    "infectious disease": "Infectious Disease",
    "palliative care": "Palliative Care",
    "case management/social work": "Case Management",
    "case management": "Case Management",
}

# Headings that are primary-service notes, NOT consultant notes
_PRIMARY_NOTE_HEADINGS: Set[str] = {
    "trauma h & p",
    "trauma h&p",
    "trauma hp",
}


def _extract_service_from_consult_note(text: str) -> Optional[str]:
    """
    Extract consultant service name from CONSULT_NOTE body text.

    Tries (in order):
      1. "consult to <SERVICE> [order_id]" / "Consult To <SERVICE>"
      2. "<SERVICE> Consult Note" heading

    Returns normalized service name or None if not extractable.
    """
    # Strategy: collect all "consult to" matches and pick the most
    # specific one (longest service name, which helps with
    # "Orthopedic Surgery" vs "Case Management/Social Work").
    candidates: List[str] = []
    for m in _CONSULT_TO_RE.finditer(text[:2000]):
        raw = m.group(1).strip()
        candidates.append(raw)

    if not candidates:
        # Try heading pattern
        for m in _CONSULT_HEADING_RE.finditer(text[:2000]):
            raw = m.group(1).strip()
            if raw.lower() not in _PRIMARY_NOTE_HEADINGS:
                candidates.append(raw)

    if not candidates:
        return None

    # Pick longest candidate (most specific)
    best = max(candidates, key=len)

    # Normalize via alias map
    key = best.lower().strip()
    if key in _SERVICE_ALIASES:
        return _SERVICE_ALIASES[key]

    # Clean up trailing "Eval and" artifacts
    best = re.sub(r"\s+Eval\s+and\s*$", "", best, flags=re.IGNORECASE)
    return best.strip() or None


def _is_primary_service_note(text: str) -> bool:
    """
    Detect CONSULT_NOTE items that are actually primary-service notes
    (Trauma H&P) mislabeled as consult notes.
    """
    # Check first 500 chars for primary note heading
    head = text[:500].lower()
    for heading in _PRIMARY_NOTE_HEADINGS:
        if heading in head:
            return True
    return False


def _sha256_hex(text: str) -> str:
    """Return SHA-256[:16] of text for raw_line_id."""
    return hashlib.sha256(
        text.encode("utf-8", errors="replace")
    ).hexdigest()[:16]


def _scan_timeline_for_consult_notes(
    days_data: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Fallback: scan timeline items for CONSULT_NOTE entries and extract
    service names from their text.

    Returns list of synthetic note_index-compatible entries with:
    - service, date_raw, time_raw, note_type, author_name, author_raw,
      raw_line_id, dt (ISO), source_id
    """
    entries: List[Dict[str, Any]] = []
    days = days_data.get("days", {})
    for date_key in sorted(days.keys()):
        day_data = days[date_key]
        for item in day_data.get("items", []):
            if item.get("type") != "CONSULT_NOTE":
                continue
            text = (item.get("payload") or {}).get("text", "")
            if not text:
                continue

            # Skip primary-service notes mislabeled as CONSULT_NOTE
            if _is_primary_service_note(text):
                continue

            service = _extract_service_from_consult_note(text)
            if not service:
                continue

            # Check exclusion
            if service.lower() in _NON_CONSULTANT_SERVICES:
                continue

            dt = item.get("dt", "")
            source_id = item.get("source_id", "")

            # Derive date_raw / time_raw from ISO dt
            dm = re.match(r"\d{4}-(\d{2})-(\d{2})T(\d{2}):(\d{2})", dt)
            if dm:
                date_raw = f"{dm.group(1)}/{dm.group(2)}"
                time_raw = f"{dm.group(3)}{dm.group(4)}"
            else:
                date_raw = "??/??"
                time_raw = "????"

            raw_line_id = _sha256_hex(
                f"{source_id}|{dt}|CONSULT_NOTE|{service}"
            )

            entries.append({
                "note_type": "Consults",
                "date_raw": date_raw,
                "time_raw": time_raw,
                "author_raw": "",
                "author_name": "",
                "service": service,
                "raw_line_id": raw_line_id,
                "dt": dt,
                "source_id": source_id,
            })

    return entries


def _is_consultant_entry(entry: Dict[str, Any]) -> bool:
    """
    Determine if a note_index entry represents consultant involvement.

    Rules:
      1. note_type must be in _CONSULTANT_NOTE_TYPES
      2. service must be present and explicit (not empty/null)
      3. service must NOT be in _NON_CONSULTANT_SERVICES
    """
    note_type = (entry.get("note_type") or "").strip()
    service = (entry.get("service") or "").strip()

    # Must be an eligible note type
    if note_type not in _CONSULTANT_NOTE_TYPES:
        return False

    # Must have an explicit service tag
    if not service:
        return False

    # Service must not be in exclusion set
    if service.lower() in _NON_CONSULTANT_SERVICES:
        return False

    return True


def _normalize_service(service: str) -> str:
    """
    Normalize service name for consistent grouping.

    Currently returns the service as-is (preserving original casing).
    Can be extended with mapping rules if needed.
    """
    return service.strip()


def _build_consultant_services(
    consultant_entries: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Group consultant entries by service and build per-service summaries.

    Returns a list of service dicts sorted alphabetically by service name.
    """
    # Group by normalized service
    by_service: Dict[str, List[Dict[str, Any]]] = {}
    for entry in consultant_entries:
        svc = _normalize_service(entry.get("service") or "")
        if svc not in by_service:
            by_service[svc] = []
        by_service[svc].append(entry)

    result: List[Dict[str, Any]] = []
    for svc_name in sorted(by_service.keys()):
        entries = by_service[svc_name]

        # Collect timestamps for ordering
        timestamps: List[str] = []
        authors: List[str] = []
        note_types: List[str] = []
        evidence: List[Dict[str, Any]] = []

        for e in entries:
            ts = f"{e.get('date_raw', '??/??')} {e.get('time_raw', '????')}"
            timestamps.append(ts)

            author = (e.get("author_name") or "").strip()
            if author and author not in authors:
                authors.append(author)

            nt = (e.get("note_type") or "").strip()
            if nt and nt not in note_types:
                note_types.append(nt)

            raw_line_id = e.get("raw_line_id", "")
            snippet = (
                f"{nt} {e.get('date_raw', '')} {e.get('time_raw', '')} "
                f"{e.get('author_raw', '')} [{svc_name}]"
            )[:120]
            evidence.append({
                "role": "consultant_event",
                "snippet": snippet,
                "raw_line_id": raw_line_id,
            })

        # Sort timestamps to find first/last
        # Format is "MM/DD HHMM" — sortable within same year context
        sorted_ts = sorted(timestamps)
        first_ts = sorted_ts[0] if sorted_ts else None
        last_ts = sorted_ts[-1] if sorted_ts else None

        result.append({
            "service": svc_name,
            "first_ts": first_ts,
            "last_ts": last_ts,
            "note_count": len(entries),
            "authors": sorted(authors),
            "note_types": sorted(note_types),
            "evidence": evidence,
        })

    return result


# ── Public API ──────────────────────────────────────────────────────

def extract_consultant_events(
    pat_features: Dict[str, Any],
    days_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Extract consultant-service involvement from note_index_events_v1.

    Parameters
    ----------
    pat_features : dict
        Must contain ``note_index_events_v1`` under the features dict.
        The builder passes the assembled features dict (or a subset).
    days_data : dict
        Full patient_days_v1.json dict — unused by this extractor but
        follows the standard signature.

    Returns
    -------
    dict with keys: consultant_present, consultant_services_count,
                    consultant_services, source_rule_id, warnings, notes
    """
    warnings: List[str] = []
    notes: List[str] = []

    # ── Get note_index_events_v1 from already-computed features ──
    ni = pat_features.get("note_index_events_v1")
    if ni is None:
        notes.append("note_index_events_v1 not available in features")
        return {
            "consultant_present": _DNA,
            "consultant_services_count": 0,
            "consultant_services": [],
            "source_rule_id": "no_note_index_available",
            "warnings": warnings,
            "notes": notes,
        }

    ni_entries = ni.get("entries", [])
    ni_rule = ni.get("source_rule_id", "")

    if not ni_entries and ni_rule == "no_notes_section":
        # ── Fallback: scan timeline CONSULT_NOTE items directly ──
        notes.append(
            "note_index has no entries (no Notes section in raw file), "
            "trying timeline CONSULT_NOTE fallback"
        )
        fallback_entries = _scan_timeline_for_consult_notes(days_data)
        if not fallback_entries:
            notes.append("timeline CONSULT_NOTE fallback: 0 items found")
            return {
                "consultant_present": _DNA,
                "consultant_services_count": 0,
                "consultant_services": [],
                "source_rule_id": "no_note_index_available",
                "warnings": warnings,
                "notes": notes,
            }

        notes.append(
            f"timeline CONSULT_NOTE fallback: "
            f"{len(fallback_entries)} consultant items found"
        )
        consultant_services = _build_consultant_services(fallback_entries)
        return {
            "consultant_present": "yes",
            "consultant_services_count": len(consultant_services),
            "consultant_services": consultant_services,
            "source_rule_id": "consultant_events_from_timeline_items",
            "warnings": warnings,
            "notes": notes,
        }

    # ── Filter to consultant entries ────────────────────────────
    consultant_entries = [e for e in ni_entries if _is_consultant_entry(e)]

    notes.append(
        f"note_index_entries={len(ni_entries)}, "
        f"consultant_entries={len(consultant_entries)}"
    )

    if not consultant_entries:
        return {
            "consultant_present": "no",
            "consultant_services_count": 0,
            "consultant_services": [],
            "source_rule_id": "no_consultant_entries",
            "warnings": warnings,
            "notes": notes,
        }

    # ── Build per-service summaries ─────────────────────────────
    consultant_services = _build_consultant_services(consultant_entries)

    return {
        "consultant_present": "yes",
        "consultant_services_count": len(consultant_services),
        "consultant_services": consultant_services,
        "source_rule_id": "consultant_events_from_note_index",
        "warnings": warnings,
        "notes": notes,
    }
