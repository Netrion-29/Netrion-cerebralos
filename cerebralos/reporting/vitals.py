#!/usr/bin/env python3
"""
Vital sign extraction and formatting for CerebralOS.

Extracts numeric vital signs from clinical documentation evidence blocks
and formats them for daily notes output.

Tracked vitals:
- HR (Heart Rate / Pulse)
- BP (Blood Pressure — systolic/diastolic)
- RR (Respiratory Rate)
- SpO2 (Oxygen Saturation)
- Temp (Temperature)
- MAP (Mean Arterial Pressure)
- GCS (Glasgow Coma Scale)

Design:
- Deterministic: Same input → same output
- Fail-closed: No inference of values
- Evidence-based: Every value traces to source text
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class VitalSign:
    """A single vital sign reading extracted from documentation."""
    name: str           # Canonical: HR, BP, RR, SpO2, Temp, MAP, GCS
    value: str          # Display value: "120/80", "98", "36.7"
    numeric: float      # Primary numeric (for BP, this is systolic)
    timestamp: str      # ISO timestamp from evidence block
    source_type: str    # NURSING_NOTE, PHYSICIAN_NOTE, etc.


# ---------------------------------------------------------------------------
# Vital Sign Detection Patterns
# ---------------------------------------------------------------------------
# Each entry: (vital_name, compiled_regex, group_index_for_display, group_index_for_numeric)

_VITAL_PATTERNS: List[tuple[str, re.Pattern, int, int]] = []


def _build_vital_patterns():
    """Build and cache compiled vital sign patterns."""
    if _VITAL_PATTERNS:
        return

    raw = [
        # Heart Rate
        ("HR", r"\b(?:HR|heart\s*rate|pulse)\s*[:=]?\s*(\d{2,3})\b", 1, 1),
        ("HR", r"\bP(?:ulse)?\s*[:=]\s*(\d{2,3})\b", 1, 1),

        # Blood Pressure (capture full "120/80" for display, systolic for numeric)
        ("BP", r"\b(?:BP|blood\s*pressure)\s*[:=]?\s*(\d{2,3})/(\d{2,3})\b", 0, 1),
        ("BP", r"\b(?:SBP|systolic)\s*[:=]?\s*(\d{2,3})\b", 1, 1),

        # Respiratory Rate
        ("RR", r"\b(?:RR|resp(?:iratory)?\s*rate)\s*[:=]?\s*(\d{1,2})\b", 1, 1),

        # Oxygen Saturation
        ("SpO2", r"\b(?:SpO2|O2\s*sat|sat(?:uration)?|SaO2)\s*[:=]?\s*(\d{2,3})\s*%?\b", 1, 1),

        # Temperature
        ("Temp", r"\b(?:Temp|temperature|T)\s*[:=]\s*(\d{2,3}\.?\d?)\s*(?:°?[CF])?\b", 1, 1),

        # Mean Arterial Pressure
        ("MAP", r"\b(?:MAP|mean\s*arterial\s*pressure?)\s*[:=]?\s*(\d{2,3})\b", 1, 1),

        # Glasgow Coma Scale
        ("GCS", r"\b(?:GCS|Glasgow(?:\s*Coma\s*Scale)?)\s*[:=]?\s*(\d{1,2})\b", 1, 1),
    ]

    for name, pattern, display_group, numeric_group in raw:
        _VITAL_PATTERNS.append(
            (name, re.compile(pattern, re.IGNORECASE), display_group, numeric_group)
        )


def extract_vitals(
    evidence_blocks: List[Any],
    target_date: Optional[str] = None,
) -> List[VitalSign]:
    """
    Extract vital signs from evidence blocks.

    Args:
        evidence_blocks: List of evidence objects (must have .source_type, .timestamp, .text)
        target_date: Optional YYYY-MM-DD to filter by date. If None, extracts from all.

    Returns:
        List of VitalSign objects found in the evidence, sorted by timestamp.
    """
    _build_vital_patterns()
    vitals: List[VitalSign] = []
    seen: set = set()  # Deduplicate by (name, value, timestamp)

    for ev in evidence_blocks:
        src_type = ev.source_type.value if hasattr(ev.source_type, "value") else str(ev.source_type)
        text = ev.text or ""
        timestamp = ev.timestamp or ""

        if not text:
            continue

        # Filter by date if specified
        if target_date and timestamp:
            ev_date = timestamp[:10]
            if ev_date != target_date:
                continue

        for name, pattern, display_group, numeric_group in _VITAL_PATTERNS:
            for match in pattern.finditer(text):
                # Extract display value
                if name == "BP" and display_group == 0:
                    # For BP pattern with full match, reconstruct "systolic/diastolic"
                    try:
                        systolic = match.group(1)
                        diastolic = match.group(2)
                        display_val = f"{systolic}/{diastolic}"
                        numeric_val = float(systolic)
                    except (IndexError, ValueError):
                        continue
                else:
                    try:
                        display_val = match.group(display_group)
                        numeric_val = float(match.group(numeric_group))
                    except (IndexError, ValueError):
                        continue

                # Validate reasonable ranges
                if not _is_reasonable_vital(name, numeric_val):
                    continue

                # Deduplicate
                dedup_key = (name, display_val, timestamp)
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)

                vitals.append(VitalSign(
                    name=name,
                    value=display_val,
                    numeric=numeric_val,
                    timestamp=timestamp,
                    source_type=src_type,
                ))

    # Sort by timestamp then by vital name
    vitals.sort(key=lambda v: (v.timestamp or "9999-99-99", v.name))
    return vitals


def _is_reasonable_vital(name: str, value: float) -> bool:
    """Validate vital sign is within physiologically reasonable range."""
    ranges = {
        "HR": (20, 250),
        "BP": (40, 300),       # Systolic
        "RR": (4, 60),
        "SpO2": (50, 100),
        "Temp": (30, 42),      # Celsius
        "MAP": (30, 200),
        "GCS": (3, 15),
    }
    lo, hi = ranges.get(name, (0, 9999))
    return lo <= value <= hi


def format_vitals_summary(vitals: List[VitalSign]) -> str:
    """
    Format vitals into a concise summary line.

    Groups by vital name, takes most recent value for each.

    Example output: "HR 88, BP 132/78, RR 16, SpO2 97%, Temp 37.1, MAP 96, GCS 15"
    """
    if not vitals:
        return "Vitals not documented for this day."

    # Take most recent value per vital name
    latest: Dict[str, VitalSign] = {}
    for v in vitals:
        if v.name not in latest or (v.timestamp or "") > (latest[v.name].timestamp or ""):
            latest[v.name] = v

    # Format in standard order
    order = ["HR", "BP", "RR", "SpO2", "Temp", "MAP", "GCS"]
    parts: List[str] = []
    for name in order:
        if name in latest:
            v = latest[name]
            if name == "SpO2":
                parts.append(f"SpO2 {v.value}%")
            elif name == "Temp":
                parts.append(f"Temp {v.value}")
            else:
                parts.append(f"{name} {v.value}")

    if not parts:
        return "Vitals not documented for this day."

    return ", ".join(parts)


def get_vitals_for_date(
    evidence_blocks: List[Any],
    target_date: str,
) -> Dict[str, VitalSign]:
    """
    Get latest vitals for a specific date.

    Args:
        evidence_blocks: Evidence list
        target_date: YYYY-MM-DD date string

    Returns:
        Dict mapping vital name to most recent VitalSign for that date
    """
    vitals = extract_vitals(evidence_blocks, target_date=target_date)
    latest: Dict[str, VitalSign] = {}
    for v in vitals:
        if v.name not in latest or (v.timestamp or "") > (latest[v.name].timestamp or ""):
            latest[v.name] = v
    return latest
