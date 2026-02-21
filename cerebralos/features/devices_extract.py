#!/usr/bin/env python3
"""
Deterministic device-presence extraction for CerebralOS.

Scans timeline items for mentions of medical devices (lines, drains, tubes, etc.)
and returns a per-day summary of which devices were present plus raw episodes.

Design:
- Fail-closed: unrecognised mentions are ignored; no clinical inference.
- Keyword-based regex matching against payload text.
- No LLM, no ML.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

# ── device keyword table ────────────────────────────────────────────
# Each entry: (canonical_name, compiled regex)
_DEVICE_PATTERNS: List[Tuple[str, "re.Pattern[str]"]] = [
    ("foley",               re.compile(r"\bfoley\b", re.I)),
    ("chest_tube",          re.compile(r"\bchest\s*tube\b", re.I)),
    ("central_line",        re.compile(r"\b(central\s+(line|venous\s+catheter)|CVC)\b", re.I)),
    ("arterial_line",       re.compile(r"\b(arterial\s+line|a[\-\s]?line|art\s+line)\b", re.I)),
    ("picc",                re.compile(r"\bPICC\b", re.I)),
    ("midline",             re.compile(r"\bmidline\b", re.I)),
    ("peripheral_iv",       re.compile(r"\b(peripheral\s+IV|PIV)\b", re.I)),
    ("ng_tube",             re.compile(r"\b(NG\s*tube|nasogastric\s*tube|naso[\-]?gastric)\b", re.I)),
    ("og_tube",             re.compile(r"\b(OG\s*tube|orogastric\s*tube)\b", re.I)),
    ("ett",                 re.compile(r"\b(ETT|endotracheal\s+tube)\b", re.I)),
    ("trach",               re.compile(r"\b(trach(?:eostomy)?)\b", re.I)),
    ("ventilator",          re.compile(r"\b(ventilator|mechanical\s+ventilation|vent\s+settings?)\b", re.I)),
    ("jp_drain",            re.compile(r"\b(JP\s*drain|Jackson[\-\s]?Pratt)\b", re.I)),
    ("chest_drain",         re.compile(r"\bchest\s*drain\b", re.I)),
    ("wound_vac",           re.compile(r"\b(wound\s*vac|negative\s*pressure\s*wound|NPWT|VAC\s+dressing)\b", re.I)),
    ("external_fixator",    re.compile(r"\b(external\s*fix(ator|ation)|ex[\-\s]?fix)\b", re.I)),
    ("traction",            re.compile(r"\btraction\b", re.I)),
    ("c_collar",            re.compile(r"\b(C[\-\s]?collar|cervical\s+collar)\b", re.I)),
    ("spine_board",         re.compile(r"\b(spine\s+board|long\s+board|back\s*board)\b", re.I)),
    ("icp_monitor",         re.compile(r"\b(ICP\s+monitor|intracranial\s+pressure\s+monitor)\b", re.I)),
    ("evd",                 re.compile(r"\b(EVD|external\s+ventricular\s+drain)\b", re.I)),
    ("pelvic_binder",       re.compile(r"\b(pelvic\s+binder|T[\-\s]?POD)\b", re.I)),
    ("splint",              re.compile(r"\bsplint\b", re.I)),
    ("tourniquet",          re.compile(r"\btourniquet\b", re.I)),
]


def _scan_text_for_devices(text: str) -> List[str]:
    """Return sorted list of canonical device names found in *text*."""
    found: set[str] = set()
    for canon, pat in _DEVICE_PATTERNS:
        if pat.search(text):
            found.add(canon)
    return sorted(found)


def extract_devices_for_day(
    items: List[Dict[str, Any]],
    day_iso: str,
) -> Tuple[Dict[str, Any], List[str]]:
    """
    Given all timeline items for a single day, extract device presence.

    Parameters
    ----------
    items : list of timeline item dicts (each has type, dt, payload)
    day_iso : YYYY-MM-DD

    Returns
    -------
    (result_dict, warnings)
        result_dict = {
            "present": ["c_collar", "foley", ...],   # sorted unique
            "episodes": [ {device, source_id, dt, text_preview}, ... ]
        }
    """
    warnings: List[str] = []
    episodes: List[Dict[str, Any]] = []
    all_devices: set[str] = set()

    for item in items:
        text = (item.get("payload") or {}).get("text", "")
        if not text:
            continue
        devs = _scan_text_for_devices(text)
        if devs:
            all_devices.update(devs)
            episodes.append({
                "devices": devs,
                "source_id": item.get("source_id"),
                "dt": item.get("dt"),
                "type": item.get("type"),
                "text_preview": text[:200],
            })

    return {
        "present": sorted(all_devices),
        "episodes": episodes,
    }, warnings
