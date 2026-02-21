#!/usr/bin/env python3
"""
Per-day service tagging with note-kind classification.

Tags services and note kinds deterministically using config-driven
regex patterns, then groups notes by service per day.

Design:
- Deterministic, fail-closed.
- Config-driven patterns from services_patterns_v1.json.
- note_kind: first match wins by priority order in config.
- Scans note header/title + first ~400 chars of text.
- No LLM, no ML, no clinical inference.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple


def _compile_pattern_map(
    mapping: Dict[str, List[str]],
) -> List[Tuple[str, "re.Pattern[str]"]]:
    """
    Compile a {key: [pattern_str, ...]} map into an ordered list of
    (key, compiled_regex) tuples.  Order is preserved from the dict
    (Python 3.7+ insertion order).
    """
    result: List[Tuple[str, re.Pattern[str]]] = []
    for key, patterns in mapping.items():
        if key.startswith("_"):
            continue
        for pat_str in patterns:
            result.append((key, re.compile(pat_str, re.IGNORECASE)))
    return result


def tag_services_daily(
    items: List[Dict[str, Any]],
    day_iso: str,
    config: Dict[str, Any],
) -> Tuple[Dict[str, Any], List[str]]:
    """
    Tag services and note kinds per day, group notes by service.

    Parameters
    ----------
    items   : timeline items for the day
    day_iso : 'YYYY-MM-DD'
    config  : loaded services_patterns_v1 config dict

    Returns
    -------
    (result_dict, warnings)
        result_dict = {
            "notes_by_service": {
                service_tag: [
                    {"ts": ..., "type": ..., "note_kind": ..., "preview": ...},
                    ...
                ],
                ...
            }
        }
    """
    warnings: List[str] = []
    service_patterns = _compile_pattern_map(config.get("services", {}))
    note_kind_patterns = _compile_pattern_map(config.get("note_kinds", {}))

    # notes_by_service: {service_tag: [note_record, ...]}
    notes_by_service: Dict[str, List[Dict[str, Any]]] = {}

    for item in items:
        text = (item.get("payload") or {}).get("text", "")
        if not text:
            continue

        item_type = item.get("type", "")
        ts = item.get("dt")

        # Scan header/title + first ~400 chars
        scan_text = text[:400]

        # Tag services: collect all matching service tags
        matched_services: List[str] = []
        seen_svc: set = set()
        for svc_tag, pat in service_patterns:
            if svc_tag not in seen_svc and pat.search(scan_text):
                matched_services.append(svc_tag)
                seen_svc.add(svc_tag)

        # Tag note_kind: first match wins (priority order)
        note_kind = "other"
        for kind_tag, pat in note_kind_patterns:
            if pat.search(scan_text):
                note_kind = kind_tag
                break

        # Also check item type for note_kind fallback
        if note_kind == "other" and item_type:
            type_lower = item_type.lower()
            if "consult" in type_lower:
                note_kind = "consult"
            elif "progress" in type_lower:
                note_kind = "progress"
            elif "operative" in type_lower or "op_note" in type_lower:
                note_kind = "op_note"
            elif "discharge" in type_lower:
                note_kind = "discharge"

        # Build preview
        preview = text[:200].replace("\n", " ").strip()

        note_record = {
            "ts": ts,
            "type": item_type,
            "note_kind": note_kind,
            "preview": preview,
        }

        # Group by service
        if matched_services:
            for svc in matched_services:
                notes_by_service.setdefault(svc, []).append(note_record)
        # Also keep an "_untagged" group for notes with no service match
        # so nothing is silently lost
        if not matched_services:
            notes_by_service.setdefault("_untagged", []).append(note_record)

    return {
        "notes_by_service": {k: v for k, v in sorted(notes_by_service.items())},
    }, warnings
