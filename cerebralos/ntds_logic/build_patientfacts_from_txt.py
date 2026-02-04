#!/usr/bin/env python3
"""
CerebralOS — Build PatientFacts from Epic TXT Export (v1)

Parses raw Epic .txt exports into PatientFacts for NTDS evaluation.

Design:
- Deterministic line-by-line parsing
- Fail-closed: missing data → empty or None (never guessed)
- Preserves original text for evidence receipts
- PHI handling: caller is responsible for ensuring PHI is not committed

Supported Epic export format:
- Section headers (e.g., "PHYSICIAN NOTES:", "IMAGING:")
- Timestamped entries (e.g., "01/15/26 0830")
- Free-text clinical notes
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from cerebralos.ntds_logic.model import (
    Evidence,
    EvidencePointer,
    PatientFacts,
    SourceType,
)


# Section header patterns map to SourceType
_SECTION_PATTERNS: Dict[str, SourceType] = {
    r"PHYSICIAN\s+NOTE": SourceType.PHYSICIAN_NOTE,
    r"CONSULT\s+NOTE": SourceType.CONSULT_NOTE,
    r"NURSING\s+NOTE": SourceType.NURSING_NOTE,
    r"IMAGING": SourceType.IMAGING,
    r"RADIOLOGY": SourceType.IMAGING,
    r"LAB": SourceType.LAB,
    r"MAR": SourceType.MAR,
    r"MEDICATION\s+ADMIN": SourceType.MAR,
    r"PROCEDURE": SourceType.PROCEDURE,
    r"OPERATIVE\s+NOTE": SourceType.OPERATIVE_NOTE,
    r"OP\s+NOTE": SourceType.OPERATIVE_NOTE,
    r"DISCHARGE": SourceType.DISCHARGE,
    r"ED\s+NOTE": SourceType.ED_NOTE,
    r"EMERGENCY": SourceType.ED_NOTE,
    r"PROGRESS\s+NOTE": SourceType.PROGRESS_NOTE,
}

# Timestamp patterns (various Epic formats)
_TIMESTAMP_PATTERNS = [
    # mm/dd/yy HHmm
    (r"(\d{1,2}/\d{1,2}/\d{2,4})\s+(\d{4})", "%m/%d/%y %H%M"),
    # mm/dd/yy HH:mm
    (r"(\d{1,2}/\d{1,2}/\d{2,4})\s+(\d{2}:\d{2})", "%m/%d/%y %H:%M"),
    # yyyy-mm-dd HH:mm:ss
    (r"(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2})", "%Y-%m-%d %H:%M:%S"),
    # yyyy-mm-dd HH:mm
    (r"(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})", "%Y-%m-%d %H:%M"),
    # ISO format
    (r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", "%Y-%m-%dT%H:%M:%S"),
]


def _detect_source_type(line: str, current_source: SourceType) -> SourceType:
    """Detect if line is a section header, return appropriate SourceType."""
    upper = line.upper().strip()
    for pattern, source_type in _SECTION_PATTERNS.items():
        if re.search(pattern, upper):
            return source_type
    return current_source


def _extract_timestamp(line: str) -> Optional[str]:
    """Extract timestamp from line if present, return ISO format or None."""
    for pattern, fmt in _TIMESTAMP_PATTERNS:
        match = re.search(pattern, line)
        if match:
            try:
                ts_str = match.group(0)
                # Handle mm/dd/yy HHmm format specially
                if " " in ts_str and len(ts_str.split()[-1]) == 4 and ":" not in ts_str.split()[-1]:
                    parts = ts_str.split()
                    date_part = parts[0]
                    time_part = parts[1]
                    # Parse with 2-digit year or 4-digit year
                    if len(date_part.split("/")[-1]) == 2:
                        dt = datetime.strptime(f"{date_part} {time_part}", "%m/%d/%y %H%M")
                    else:
                        dt = datetime.strptime(f"{date_part} {time_part}", "%m/%d/%Y %H%M")
                    return dt.strftime("%Y-%m-%dT%H:%M:%S")
                # Handle mm/dd/yy HH:mm format
                elif " " in ts_str and ":" in ts_str.split()[-1] and len(ts_str.split()[-1]) == 5:
                    parts = ts_str.split()
                    date_part = parts[0]
                    time_part = parts[1]
                    if len(date_part.split("/")[-1]) == 2:
                        dt = datetime.strptime(f"{date_part} {time_part}", "%m/%d/%y %H:%M")
                    else:
                        dt = datetime.strptime(f"{date_part} {time_part}", "%m/%d/%Y %H:%M")
                    return dt.strftime("%Y-%m-%dT%H:%M:%S")
                else:
                    dt = datetime.strptime(ts_str, fmt)
                    return dt.strftime("%Y-%m-%dT%H:%M:%S")
            except ValueError:
                continue
    return None


def _is_section_header(line: str) -> bool:
    """Check if line is a section header."""
    upper = line.upper().strip()
    for pattern in _SECTION_PATTERNS:
        if re.search(pattern, upper):
            return True
    return False


def build_patientfacts(
    txt_path: Path,
    query_patterns: Dict[str, Any],
    arrival_time: Optional[str] = None,
    patient_id: Optional[str] = None,
) -> PatientFacts:
    """Parse Epic TXT export into PatientFacts.
    
    Args:
        txt_path: Path to the Epic .txt export file
        query_patterns: Dictionary of query pattern keys to regex patterns
        arrival_time: Optional override for arrival time (ISO format preferred)
        patient_id: Optional de-identified patient identifier
        
    Returns:
        PatientFacts containing parsed evidence and facts
        
    Note:
        - Fails closed: if file is missing or unreadable, returns empty PatientFacts
        - PHI in txt_path is the caller's responsibility to handle
    """
    facts: Dict[str, Any] = {
        "query_patterns": query_patterns,
        "arrival_time": arrival_time,
    }
    evidence_list: List[Evidence] = []
    
    if not txt_path.exists():
        return PatientFacts(patient_id=patient_id, facts=facts, evidence=[])
    
    try:
        content = txt_path.read_text(encoding="utf-8")
    except (IOError, UnicodeDecodeError):
        return PatientFacts(patient_id=patient_id, facts=facts, evidence=[])
    
    lines = content.splitlines()
    current_source = SourceType.UNKNOWN
    current_timestamp: Optional[str] = None
    
    for line_num, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        
        # Check for section header
        new_source = _detect_source_type(stripped, current_source)
        if new_source != current_source:
            current_source = new_source
            # Section headers often contain timestamps too
            ts = _extract_timestamp(stripped)
            if ts:
                current_timestamp = ts
            continue
        
        # Check for timestamp in line
        ts = _extract_timestamp(stripped)
        if ts:
            current_timestamp = ts
        
        # Create evidence for this line
        pointer = EvidencePointer(ref={
            "file": txt_path.name,
            "line": line_num,
        })
        
        ev = Evidence(
            source_type=current_source,
            timestamp=current_timestamp,
            text=stripped,
            pointer=pointer,
        )
        evidence_list.append(ev)
    
    return PatientFacts(
        patient_id=patient_id,
        facts=facts,
        evidence=evidence_list,
    )
