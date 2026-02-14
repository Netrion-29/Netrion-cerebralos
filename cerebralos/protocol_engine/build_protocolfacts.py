#!/usr/bin/env python3
"""
Parser for Epic TXT exports to ProtocolFacts objects.

This module converts raw Epic clinical text exports into structured ProtocolFacts
objects suitable for protocol compliance evaluation. It emphasizes actions, orders,
and interventions rather than just diagnoses.

Adapted from NTDS build_patientfacts_from_txt.py with protocol-specific focus.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from cerebralos.protocol_engine.model import (
    ProtocolEvidence,
    EvidencePointer,
    ProtocolFacts,
    SourceType,
)


# Timestamp patterns (reused from NTDS for consistency)
_TS_PATTERNS = [
    ("%Y-%m-%dT%H:%M:%SZ", True),
    ("%Y-%m-%dT%H:%M:%S", False),
    ("%Y-%m-%d %H:%M:%S", False),
    ("%Y-%m-%d %H:%M", False),
    ("%m/%d/%y %H%M", False),
    ("%m/%d/%Y %H%M", False),
    ("%m/%d/%Y %H:%M", False),
    ("%m/%d/%y %H:%M", False),
]


def _parse_ts(ts: Optional[str]) -> Optional[str]:
    """
    Parse timestamp string to ISO format (or return original if valid).

    Attempts multiple common timestamp formats. Returns None if unparseable.
    Preserves timezone info when present.
    """
    if not ts:
        return None
    s = ts.strip()
    if not s:
        return None

    for fmt, is_utc_z in _TS_PATTERNS:
        try:
            dt = datetime.strptime(s, fmt)
            if is_utc_z:
                dt = dt.replace(tzinfo=timezone.utc)
            # Return in ISO format for consistency
            if dt.tzinfo:
                return dt.isoformat()
            # Naive datetime - return without timezone
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            continue

    # If no pattern matched, return original string (engine will handle it)
    return s


def _parse_source_type(source_str: str) -> SourceType:
    """
    Parse source type string from [SOURCE_TYPE] header.

    Handles case-insensitive matching and fallback to PHYSICIAN_NOTE for
    unrecognized types (fail-closed design).
    """
    s = source_str.strip().upper().replace(" ", "_")

    # Try exact match first
    for st in SourceType:
        if st.name == s:
            return st

    # Fallback for common aliases or typos
    aliases = {
        "PHYSICIAN": SourceType.PHYSICIAN_NOTE,
        "CONSULT": SourceType.CONSULT_NOTE,
        "NURSE": SourceType.NURSING_NOTE,
        "NURSING": SourceType.NURSING_NOTE,
        "IMAGE": SourceType.IMAGING,
        "RAD": SourceType.RADIOLOGY,
        "MEDICATION": SourceType.MAR,
        "PROC": SourceType.PROCEDURE,
        "DC": SourceType.DISCHARGE,
        "TRAUMA": SourceType.TRAUMA_HP,
        "ED": SourceType.ED_NOTE,
        "OPERATIVE": SourceType.OPERATIVE_NOTE,
    }

    for prefix, st in aliases.items():
        if s.startswith(prefix):
            return st

    # Default fallback (fail-closed: assign a generic type rather than error)
    return SourceType.PHYSICIAN_NOTE


def build_protocolfacts(
    txt_path: Path,
    action_patterns: Dict[str, Any],
    arrival_time: Optional[str] = None,
) -> ProtocolFacts:
    """
    Parse Epic TXT export into ProtocolFacts object.

    Input format:
        PATIENT_ID: <id>
        ARRIVAL_TIME: <timestamp>

        [SOURCE_TYPE] timestamp
        Clinical text content (actions, orders, assessments)...

        [SOURCE_TYPE] timestamp
        More content...

    Args:
        txt_path: Path to Epic TXT export file
        action_patterns: Pattern mappings dict (from mapper or shared buckets)
        arrival_time: Optional arrival time override (if not in file)

    Returns:
        ProtocolFacts object with evidence blocks and metadata
    """
    if not txt_path.exists():
        raise FileNotFoundError(f"Patient file not found: {txt_path}")

    content = txt_path.read_text(encoding="utf-8")
    lines = content.splitlines()

    # Parse header for PATIENT_ID and ARRIVAL_TIME
    patient_id: Optional[str] = None
    file_arrival_time: Optional[str] = None

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("PATIENT_ID:"):
            patient_id = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("ARRIVAL_TIME:"):
            file_arrival_time = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("[") or (i > 5):
            # Stop parsing header once we hit first evidence block or after 5 lines
            break

    # Use override if provided, otherwise use file value
    final_arrival_time = arrival_time if arrival_time else file_arrival_time

    # Parse evidence blocks: [SOURCE_TYPE] timestamp
    evidence_blocks: List[ProtocolEvidence] = []
    block_id = 0

    # Pattern to match evidence block headers: [SOURCE_TYPE] optional_timestamp
    header_pattern = re.compile(r"^\[([^\]]+)\](.*)$")

    current_source: Optional[SourceType] = None
    current_timestamp: Optional[str] = None
    current_text_lines: List[str] = []
    current_line_start: Optional[int] = None

    def _finalize_block(line_end: int) -> None:
        """Helper to finalize current evidence block."""
        nonlocal block_id, current_source, current_timestamp, current_text_lines, current_line_start

        if current_source is None or current_line_start is None:
            return

        # Join text lines, preserving internal whitespace
        text = "\n".join(current_text_lines).strip()

        # Only create evidence block if there's actual content
        if text:
            pointer = EvidencePointer(
                ref={
                    "file": str(txt_path.absolute()),
                    "line_start": current_line_start,
                    "line_end": line_end,
                    "block_id": block_id,
                }
            )

            evidence_blocks.append(
                ProtocolEvidence(
                    source_type=current_source,
                    timestamp=current_timestamp,
                    text=text,
                    pointer=pointer,
                )
            )
            block_id += 1

        # Reset current block
        current_source = None
        current_timestamp = None
        current_text_lines = []
        current_line_start = None

    for i, line in enumerate(lines, start=1):
        match = header_pattern.match(line)

        if match:
            # Finalize previous block if any
            _finalize_block(i - 1)

            # Start new block
            source_str = match.group(1).strip()
            timestamp_str = match.group(2).strip()

            current_source = _parse_source_type(source_str)
            current_timestamp = _parse_ts(timestamp_str) if timestamp_str else None
            current_line_start = i
            current_text_lines = []

        elif current_source is not None:
            # Accumulate text for current block (preserve whitespace)
            current_text_lines.append(line.rstrip())

    # Finalize last block
    _finalize_block(len(lines))

    # Assemble ProtocolFacts
    facts: Dict[str, Any] = {
        "action_patterns": action_patterns,
        "arrival_time": final_arrival_time,
        "patient_id": patient_id,
    }

    return ProtocolFacts(evidence=evidence_blocks, facts=facts)
