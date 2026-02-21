#!/usr/bin/env python3
"""
Deterministic clinical-service tagger for CerebralOS.

Given a day's worth of timeline items, assigns service tags (e.g. "trauma",
"orthopedics", "vascular_surgery") based on keyword/regex matching against
note text, author names, and item types.

Design:
- Fail-closed: unknown services are ignored; no clinical inference.
- Keyword-based regex matching against payload text.
- No LLM, no ML.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

# ── service keyword table ───────────────────────────────────────────
# (canonical_tag, compiled regex)
_SERVICE_PATTERNS: List[Tuple[str, "re.Pattern[str]"]] = [
    ("trauma",              re.compile(r"\btrauma\b", re.I)),
    ("orthopedics",         re.compile(r"\b(ortho(?:pedic)?s?|orthopaedic)\b", re.I)),
    ("vascular_surgery",    re.compile(r"\b(vascular\s+surg(?:ery|ical|eon))\b", re.I)),
    ("general_surgery",     re.compile(r"\b(general\s+surg(?:ery|ical|eon))\b", re.I)),
    ("neurosurgery",        re.compile(r"\b(neuro\s*surg(?:ery|ical|eon))\b", re.I)),
    ("cardiology",          re.compile(r"\b(cardiology|cardiologist)\b", re.I)),
    ("pulmonology",         re.compile(r"\b(pulmonology|pulmonologist|pulmonary\s+medicine)\b", re.I)),
    ("critical_care",       re.compile(r"\b(critical\s+care|ICU|intensive\s+care)\b", re.I)),
    ("emergency",           re.compile(r"\b(emergency\s+(department|medicine|room)|ER\b|ED\b)", re.I)),
    ("anesthesia",          re.compile(r"\b(anesthesi(?:a|ology|ologist))\b", re.I)),
    ("radiology",           re.compile(r"\b(radiology|radiologist|imaging)\b", re.I)),
    ("infectious_disease",  re.compile(r"\b(infectious\s+disease|ID\s+clinic|ID\s+consult)\b", re.I)),
    ("endocrinology",       re.compile(r"\b(endocrinology|endocrinologist)\b", re.I)),
    ("nephrology",          re.compile(r"\b(nephrology|nephrologist)\b", re.I)),
    ("gastroenterology",    re.compile(r"\b(gastroenterology|GI\s+consult|gastroenterologist)\b", re.I)),
    ("physical_therapy",    re.compile(r"\b(physical\s+therap(?:y|ist)|PT\s+eval|PT\s+note)\b", re.I)),
    ("occupational_therapy", re.compile(r"\b(occupational\s+therap(?:y|ist)|OT\s+eval|OT\s+note)\b", re.I)),
    ("respiratory_therapy", re.compile(r"\b(respiratory\s+therap(?:y|ist)|RT\s+note)\b", re.I)),
    ("social_work",         re.compile(r"\b(social\s+work(?:er)?|case\s+manag(?:er|ement))\b", re.I)),
    ("pharmacy",            re.compile(r"\b(pharmacy|pharmacist|clinical\s+pharmacist)\b", re.I)),
    ("nursing",             re.compile(r"\b(nursing\s+note|RN\s+note|nurse\s+note)\b", re.I)),
    ("wound_care",          re.compile(r"\b(wound\s+care|wound\s+nurse|wound\s+consult)\b", re.I)),
    ("nutrition",           re.compile(r"\b(nutrition|dietitian|dietary)\b", re.I)),
    ("pain_management",     re.compile(r"\b(pain\s+manage(?:ment)?|pain\s+service|pain\s+consult)\b", re.I)),
    ("plastic_surgery",     re.compile(r"\b(plastic\s+surg(?:ery|ical|eon))\b", re.I)),
]

# ── note-kind tags (from item type / header) ────────────────────────
_NOTE_KIND_MAP: Dict[str, str] = {
    "TRAUMA_HP":        "trauma_hp",
    "PHYSICIAN_NOTE":   "physician_note",
    "NURSING_NOTE":     "nursing_note",
    "RADIOLOGY":        "radiology",
    "LAB":              "lab",
    "MAR":              "mar",
    "ORDER":            "order",
    "CONSULT":          "consult",
    "PROCEDURE_NOTE":   "procedure_note",
    "OPERATIVE_NOTE":   "operative_note",
    "DISCHARGE":        "discharge",
    "PROGRESS_NOTE":    "progress_note",
}


def _tag_services(text: str) -> List[str]:
    """Return sorted list of service tags found in *text*."""
    found: set[str] = set()
    for tag, pat in _SERVICE_PATTERNS:
        if pat.search(text):
            found.add(tag)
    return sorted(found)


def tag_services_for_day(
    items: List[Dict[str, Any]],
    day_iso: str,
) -> Tuple[Dict[str, Any], List[str]]:
    """
    Given all timeline items for a single day, extract service involvement.

    Parameters
    ----------
    items : list of timeline item dicts (each has type, dt, payload)
    day_iso : YYYY-MM-DD

    Returns
    -------
    (result_dict, warnings)
        result_dict = {
            "tags": ["orthopedics", "trauma", ...],    # sorted unique
            "notes": [
                {
                    "ts": "...",
                    "type": "PHYSICIAN_NOTE",
                    "service_tags": [...],
                    "note_kinds": [...],
                    "text_preview": "...",
                },
                ...
            ]
        }
    """
    warnings: List[str] = []
    notes: List[Dict[str, Any]] = []
    all_tags: set[str] = set()

    for item in items:
        text = (item.get("payload") or {}).get("text", "")
        if not text:
            continue
        svc_tags = _tag_services(text)
        item_type = item.get("type", "")
        note_kind = _NOTE_KIND_MAP.get(item_type, item_type.lower() if item_type else "unknown")

        if svc_tags:
            all_tags.update(svc_tags)

        notes.append({
            "ts": item.get("dt"),
            "type": item_type,
            "source_id": item.get("source_id"),
            "service_tags": svc_tags,
            "note_kinds": [note_kind],
            "text_preview": text[:200],
        })

    return {
        "tags": sorted(all_tags),
        "notes": notes,
    }, warnings
