#!/usr/bin/env python3
"""
Device tracking and timeline extraction for CerebralOS.

Extracts invasive device events (placement, removal, documented-in-situ)
from clinical documentation and builds per-device timelines.

Tracked devices:
- CVC (Central Venous Catheter) / Triple Lumen / Cordis
- PICC (Peripherally Inserted Central Catheter)
- Arterial Line (A-Line)
- Foley / Urinary Catheter
- Chest Tube / Thoracostomy
- NG Tube (Nasogastric) / OG Tube (Orogastric) / Dobhoff
- ET Tube (Endotracheal) / ETT

Design:
- Deterministic: Same input → same output
- Fail-closed: No inference of placement/removal dates
- Evidence-based: Every event traces to source text
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Data Model
# ---------------------------------------------------------------------------

@dataclass
class DeviceEvent:
    """A single device-related event extracted from documentation."""
    device_type: str          # Canonical: CVC, PICC, A-LINE, FOLEY, CHEST_TUBE, NG, OG, ET_TUBE
    device_subtype: str       # e.g., "Triple Lumen", "Pigtail", "Dobhoff"
    action: str               # PLACED, REMOVED, IN_SITU, MENTIONED
    timestamp: Optional[str]  # ISO timestamp if documented
    source_type: str          # NURSING_NOTE, PHYSICIAN_NOTE, PROCEDURE, etc.
    source_text: str          # Verbatim text where device was found
    location: Optional[str]   # e.g., "Right IJ", "Left SC", "Right Radial"


@dataclass
class DeviceTimeline:
    """Aggregated timeline for a single device instance."""
    device_type: str
    device_subtype: str
    placed: Optional[str]         # Earliest PLACED timestamp
    removed: Optional[str]        # Earliest REMOVED timestamp
    days_in_place: Optional[int]  # Calculated if both placed and removed are known
    location: Optional[str]       # Placement location if documented
    events: List[DeviceEvent] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Device Detection Patterns
# ---------------------------------------------------------------------------

# Each entry: (device_type, device_subtype, compiled_regex)
_DEVICE_PATTERNS: List[tuple[str, str, re.Pattern]] = []


def _build_device_patterns():
    """Build and cache compiled device detection patterns."""
    if _DEVICE_PATTERNS:
        return

    raw = [
        # CVC / Central Lines
        ("CVC", "Triple Lumen", r"\btriple\s*lumen\b"),
        ("CVC", "Triple Lumen", r"\bTLC\b"),
        ("CVC", "", r"\bcentral\s*(?:venous)?\s*(?:catheter|line)\b"),
        ("CVC", "", r"\bCVC\b(?!\s*(?:strip|rhythm))"),   # Avoid "CVC strip" (EKG term)
        ("CVC", "Cordis", r"\bcordis\b"),
        ("CVC", "Introducer", r"\bintroducer\s*(?:sheath|catheter)?\b"),
        ("CVC", "Multi-Lumen", r"\b(?:multi|dual|quad)\s*lumen\b"),

        # PICC
        ("PICC", "", r"\bPICC\s*(?:line)?\b"),
        ("PICC", "", r"\bperipherally\s+inserted\b"),

        # Arterial Line
        ("A-LINE", "", r"\barterial\s*(?:line|catheter)\b"),
        ("A-LINE", "", r"\ba[\-\s]?line\b"),
        ("A-LINE", "", r"\bart\s*line\b"),

        # Foley / Urinary Catheter
        ("FOLEY", "", r"\bfoley\s*(?:catheter)?\b"),
        ("FOLEY", "", r"\burinary\s*catheter\b"),
        ("FOLEY", "", r"\bindwelling\s*(?:urinary\s*)?catheter\b"),

        # Chest Tube
        ("CHEST_TUBE", "", r"\bchest\s*tube\b"),
        ("CHEST_TUBE", "", r"\bthoracostomy\s*(?:tube)?\b"),
        ("CHEST_TUBE", "Pigtail", r"\bpigtail\s*(?:catheter|drain)?\b"),
        ("CHEST_TUBE", "", r"\bpleural\s*(?:drain|tube)\b"),

        # NG / OG Tubes
        ("NG", "", r"\bNG\s*tube\b"),
        ("NG", "", r"\bnasogastric\b"),
        ("OG", "", r"\bOG\s*tube\b"),
        ("OG", "", r"\borogastric\b"),
        ("NG", "Dobhoff", r"\bdobhoff\b"),
        ("NG", "Dobhoff", r"\bDHT\b"),

        # Endotracheal Tube
        ("ET_TUBE", "", r"\bendotracheal\s*tube\b"),
        ("ET_TUBE", "", r"\bET\s*tube\b"),
        ("ET_TUBE", "", r"\bETT\b"),
    ]

    for dtype, subtype, pattern in raw:
        _DEVICE_PATTERNS.append(
            (dtype, subtype, re.compile(pattern, re.IGNORECASE))
        )


# Action detection patterns
_ACTION_PLACED = re.compile(
    r"\b(?:placed|inserted|started|initiated|established|obtained|"
    r"new\b.*\b(?:line|catheter|tube)|put\s+in|sutured\s+in)\b",
    re.IGNORECASE
)

_ACTION_REMOVED = re.compile(
    r"\b(?:removed|discontinued|d/?c['\u2019]?d|pulled|taken\s+out|"
    r"dc['\u2019]?d|explanted|extracted)\b"
    r"|\[REMOVED\]",
    re.IGNORECASE
)

_ACTION_IN_SITU = re.compile(
    r"\b(?:in\s+place|intact|patent|flushed|site\s+clean|"
    r"dressing\s+(?:clean|dry|intact)|"
    r"no\s+(?:redness|swelling|drainage)|"
    r"functioning\s+(?:well|properly))\b",
    re.IGNORECASE
)

# Location patterns
_LOCATION_PATTERNS = re.compile(
    r"\b(?:(?:right|left|R|L)\s+)?(?:"
    r"(?:internal\s+jugular|IJ)|"
    r"(?:subclavian|SC)|"
    r"(?:femoral)|"
    r"(?:radial)|"
    r"(?:brachial)|"
    r"(?:antecubital|AC)|"
    r"(?:groin)|"
    r"(?:neck)|"
    r"(?:upper\s+arm)"
    r")\b",
    re.IGNORECASE
)


# ---------------------------------------------------------------------------
# Extraction Functions
# ---------------------------------------------------------------------------

def extract_device_events(evidence_blocks: List[Any]) -> List[DeviceEvent]:
    """
    Extract device events from evidence blocks.

    Args:
        evidence_blocks: List of evidence objects (must have .source_type, .timestamp, .text)

    Returns:
        List of DeviceEvent objects found in the evidence
    """
    _build_device_patterns()
    events: List[DeviceEvent] = []

    for ev in evidence_blocks:
        src_type = ev.source_type.value if hasattr(ev.source_type, "value") else str(ev.source_type)
        text = ev.text or ""
        timestamp = ev.timestamp

        if not text:
            continue

        # Scan for device mentions
        for dtype, subtype, pattern in _DEVICE_PATTERNS:
            for match in pattern.finditer(text):
                # Get context window around the match (200 chars each side)
                ctx_start = max(0, match.start() - 200)
                ctx_end = min(len(text), match.end() + 200)
                context = text[ctx_start:ctx_end]

                # Determine action from context
                action = _determine_action(context)

                # Extract location from context
                location = _extract_location(context)

                events.append(DeviceEvent(
                    device_type=dtype,
                    device_subtype=subtype,
                    action=action,
                    timestamp=timestamp,
                    source_type=src_type,
                    source_text=context.strip()[:300],
                    location=location,
                ))
                break  # One event per device type per evidence block

    return events


def _determine_action(context: str) -> str:
    """Determine device action (PLACED/REMOVED/IN_SITU/MENTIONED) from context."""
    if _ACTION_REMOVED.search(context):
        return "REMOVED"
    if _ACTION_PLACED.search(context):
        return "PLACED"
    if _ACTION_IN_SITU.search(context):
        return "IN_SITU"
    return "MENTIONED"


def _extract_location(context: str) -> Optional[str]:
    """Extract anatomical location from context around a device mention."""
    match = _LOCATION_PATTERNS.search(context)
    if match:
        return match.group(0).strip()
    return None


def build_device_timelines(events: List[DeviceEvent]) -> List[DeviceTimeline]:
    """
    Build device timelines from a list of device events.

    Groups events by device_type (and subtype if present), finds earliest
    placement and removal timestamps, calculates days in place.

    Args:
        events: List of DeviceEvent objects

    Returns:
        List of DeviceTimeline objects, one per unique device
    """
    # Group events by (device_type, device_subtype)
    groups: Dict[tuple[str, str], List[DeviceEvent]] = {}
    for ev in events:
        key = (ev.device_type, ev.device_subtype)
        groups.setdefault(key, []).append(ev)

    timelines: List[DeviceTimeline] = []
    for (dtype, subtype), group_events in groups.items():
        # Sort events by timestamp (None timestamps sort last)
        sorted_events = sorted(
            group_events,
            key=lambda e: e.timestamp or "9999-99-99"
        )

        # Find first PLACED and first REMOVED timestamps
        placed_ts = None
        removed_ts = None
        location = None

        for ev in sorted_events:
            if ev.action == "PLACED" and placed_ts is None:
                placed_ts = ev.timestamp
                if ev.location:
                    location = ev.location
            elif ev.action == "REMOVED" and removed_ts is None:
                removed_ts = ev.timestamp

            # Capture location from any event if not yet found
            if location is None and ev.location:
                location = ev.location

        # Calculate days in place
        days = None
        if placed_ts and removed_ts:
            try:
                placed_dt = datetime.fromisoformat(placed_ts.replace("Z", "+00:00"))
                removed_dt = datetime.fromisoformat(removed_ts.replace("Z", "+00:00"))
                delta = removed_dt - placed_dt
                days = max(0, delta.days)
            except (ValueError, TypeError):
                pass

        timelines.append(DeviceTimeline(
            device_type=dtype,
            device_subtype=subtype,
            placed=placed_ts,
            removed=removed_ts,
            days_in_place=days,
            location=location,
            events=sorted_events,
        ))

    # Sort timelines by device type for consistent output
    timelines.sort(key=lambda t: t.device_type)
    return timelines


def format_device_report(timelines: List[DeviceTimeline]) -> str:
    """
    Format device timelines into a human-readable report.

    Args:
        timelines: List of DeviceTimeline objects

    Returns:
        Formatted multi-line string
    """
    if not timelines:
        return "No devices documented."

    lines: List[str] = []
    for tl in timelines:
        name = tl.device_type
        if tl.device_subtype:
            name = f"{name} ({tl.device_subtype})"
        if tl.location:
            name = f"{name} — {tl.location}"

        placed_str = _format_ts(tl.placed) if tl.placed else "Not documented"
        removed_str = _format_ts(tl.removed) if tl.removed else "Still in place / not documented"

        line = f"- {name}: Placed {placed_str}"
        if tl.removed:
            line += f", Removed {removed_str}"
        if tl.days_in_place is not None:
            line += f" ({tl.days_in_place} days)"
        elif not tl.removed:
            line += f" — {removed_str}"

        lines.append(line)

    return "\n".join(lines)


def get_devices_on_date(
    timelines: List[DeviceTimeline],
    target_date: str,
) -> List[DeviceTimeline]:
    """
    Get devices that were in place on a specific date.

    A device is considered in place if:
    - It was placed on or before target_date AND
    - It was removed on or after target_date (or not yet removed)

    Args:
        timelines: List of DeviceTimeline objects
        target_date: Date string (YYYY-MM-DD format)

    Returns:
        List of DeviceTimeline objects in place on that date
    """
    active: List[DeviceTimeline] = []
    target = target_date[:10]  # Use date part only

    for tl in timelines:
        placed_date = (tl.placed or "")[:10]
        removed_date = (tl.removed or "")[:10]

        # If no placement date, check if any event exists on target date
        if not placed_date:
            has_event_on_date = any(
                (ev.timestamp or "")[:10] == target for ev in tl.events
            )
            if has_event_on_date:
                active.append(tl)
            continue

        # Device placed on or before target AND not yet removed or removed after target
        if placed_date <= target:
            if not removed_date or removed_date >= target:
                active.append(tl)

    return active


def device_in_place_at_time(
    timelines: List[DeviceTimeline],
    device_type: str,
    timestamp: str,
) -> bool:
    """
    Check if a specific device type was in place at a given timestamp.

    Used by NTDS gates (CLABSI, CAUTI, VAP) to confirm device presence.

    Args:
        timelines: List of DeviceTimeline objects
        device_type: Device type to check (e.g., "CVC", "FOLEY", "ET_TUBE")
        timestamp: ISO timestamp to check

    Returns:
        True if device was documented as in place at that time
    """
    check_date = timestamp[:10]
    for tl in timelines:
        if tl.device_type != device_type:
            continue

        placed_date = (tl.placed or "")[:10]
        removed_date = (tl.removed or "")[:10]

        if placed_date and placed_date <= check_date:
            if not removed_date or removed_date >= check_date:
                return True

    return False


def _format_ts(ts: Optional[str]) -> str:
    """Format a timestamp for display (date + time if available)."""
    if not ts:
        return ""
    # Try to parse and reformat
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            dt = datetime.strptime(ts, fmt)
            return dt.strftime("%m/%d/%Y %H:%M")
        except ValueError:
            continue
    return ts[:16]  # Fallback: first 16 chars
