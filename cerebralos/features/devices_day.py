#!/usr/bin/env python3
"""
Per-day device tri-state tracking for CerebralOS.

For each tracked device (foley, central_line, ett_vent, chest_tube, drain),
evaluates all text for the day and assigns:
  PRESENT     – if any "present" pattern matches
  NOT_PRESENT – else if any "absent" pattern matches
  UNKNOWN     – else (no explicit mention)

Design:
- Deterministic, fail-closed.
- Config-driven patterns from devices_patterns_v1.json.
- No inference beyond explicit text.
- No LLM, no ML.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

# Item types preferred for device scanning (if available);
# falls back to scanning all items for determinism.
_PREFERRED_TYPES = {"NURSING_NOTE", "PHYSICIAN_NOTE", "LAB", "MAR", "DEVICE"}


def _compile_patterns(
    config: Dict[str, Any],
) -> Dict[str, Dict[str, List["re.Pattern[str]"]]]:
    """
    Compile regex patterns from the devices config.

    Returns {device_key: {"present": [compiled...], "absent": [compiled...]}}
    Skips keys starting with '_' (comments).
    """
    compiled: Dict[str, Dict[str, List[re.Pattern[str]]]] = {}
    for device_key, spec in config.items():
        if device_key.startswith("_"):
            continue
        if not isinstance(spec, dict):
            continue
        compiled[device_key] = {
            "present": [re.compile(p, re.IGNORECASE) for p in spec.get("present", [])],
            "absent": [re.compile(p, re.IGNORECASE) for p in spec.get("absent", [])],
        }
    return compiled


def evaluate_devices_for_day(
    items: List[Dict[str, Any]],
    day_iso: str,
    config: Dict[str, Any],
) -> Tuple[Dict[str, Any], List[str]]:
    """
    Evaluate device tri-state for a single day.

    Parameters
    ----------
    items   : timeline items for the day
    day_iso : 'YYYY-MM-DD'
    config  : loaded devices_patterns_v1 config dict

    Returns
    -------
    (result_dict, warnings)
        result_dict = {
            "tri_state": {device: "PRESENT"|"NOT_PRESENT"|"UNKNOWN", ...},
            "evidence": {device: [{line_id, text_preview}, ...], ...}
        }
    """
    warnings: List[str] = []
    compiled = _compile_patterns(config)

    # Collect text blocks with metadata
    text_blocks: List[Dict[str, Any]] = []
    for item in items:
        text = (item.get("payload") or {}).get("text", "")
        if not text:
            continue
        text_blocks.append({
            "text": text,
            "source_id": item.get("source_id"),
            "dt": item.get("dt"),
            "type": item.get("type"),
        })

    tri_state: Dict[str, str] = {}
    evidence: Dict[str, List[Dict[str, Any]]] = {}

    for device_key in sorted(compiled.keys()):
        pats = compiled[device_key]
        present_matches: List[Dict[str, Any]] = []
        absent_matches: List[Dict[str, Any]] = []

        for block in text_blocks:
            text = block["text"]
            # Check present patterns
            for pat in pats["present"]:
                m = pat.search(text)
                if m:
                    present_matches.append({
                        "line_id": block.get("source_id"),
                        "text_preview": text[max(0, m.start() - 30):m.end() + 50].strip()[:120],
                    })
                    break  # one match per block per direction is enough

            # Check absent patterns
            for pat in pats["absent"]:
                m = pat.search(text)
                if m:
                    absent_matches.append({
                        "line_id": block.get("source_id"),
                        "text_preview": text[max(0, m.start() - 30):m.end() + 50].strip()[:120],
                    })
                    break

        # Tri-state logic: PRESENT wins over NOT_PRESENT wins over UNKNOWN
        if present_matches:
            tri_state[device_key] = "PRESENT"
            evidence[device_key] = present_matches
        elif absent_matches:
            tri_state[device_key] = "NOT_PRESENT"
            evidence[device_key] = absent_matches
        else:
            tri_state[device_key] = "UNKNOWN"
            evidence[device_key] = []

    return {
        "tri_state": tri_state,
        "evidence": evidence,
    }, warnings
