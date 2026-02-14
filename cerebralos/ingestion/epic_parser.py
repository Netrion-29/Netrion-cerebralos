#!/usr/bin/env python3
"""
Epic EHR export parser for CerebralOS.

Converts raw Epic text exports (copied from Citrix/Epic) into the structured
[SOURCE_TYPE] block format that the CerebralOS protocol evaluation engine expects.

Usage:
    python -m cerebralos.ingestion.epic_parser --input patient.txt --output parsed.txt
    python -m cerebralos.ingestion.epic_parser --input-dir /path/to/patients/ --output-dir data_raw/

Design:
    - Fail-closed: unknown sections → PHYSICIAN_NOTE (never discarded)
    - Non-destructive: all original text preserved in output blocks
    - Auditable: line numbers tracked for provenance
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Known medical credentials (used to detect provider header lines)
# ---------------------------------------------------------------------------
_CREDENTIALS = {
    "MD", "DO", "PA-C", "PA", "NP", "FNP-C", "FNP", "AGACNP", "AGACNP-BC",
    "APRN", "CNP", "ANP", "CRNA",
    "RN", "BSN", "MSN", "RN,BSN",
    "MSW", "LCSW", "BSW",
    "OTR", "OT", "PT", "DPT", "PTA", "COTA",
    "RD", "PharmD", "CWOCN", "BCC",
    "FAAN", "FACS", "FACP",
}

# Build regex that matches credentials at end of line
_CRED_ALTS = "|".join(re.escape(c) for c in sorted(_CREDENTIALS, key=len, reverse=True))
_PROVIDER_RE = re.compile(
    r"^([A-Z][a-zA-Z'\-]+),\s+"          # Last name
    r"([A-Z][a-zA-Z'\-]+(?:\s+[A-Z][a-zA-Z'\-]*)*)"  # First + optional middle
    r"(?:,\s*|\s+)"                        # separator
    r"(" + _CRED_ALTS + r"(?:[,\s]+(?:" + _CRED_ALTS + r"))*)\s*$"  # credentials
)

# ---------------------------------------------------------------------------
# Known roles (line after provider header)
# ---------------------------------------------------------------------------
_KNOWN_ROLES = {
    "Physician", "Registered Nurse", "Nurse Practitioner",
    "Social Worker", "Case Manager", "Dietitian",
    "Physical Therapy", "Physical Therapy Assistant",
    "Occupational Therapy", "Occupational Therapist",
    "Pharmacist", "Chaplain", "Respiratory Therapist",
    "General Surgeon", "Surgeon",
}

# ---------------------------------------------------------------------------
# Note type → SourceType mapping
# ---------------------------------------------------------------------------
# Order matters: first match wins (check longest/most specific first)
_NOTE_TYPE_PATTERNS: List[Tuple[str, str]] = [
    # H&P (highest priority - the cornerstone document)
    ("Trauma H & P", "TRAUMA_HP"),
    ("Trauma H&P", "TRAUMA_HP"),
    ("H&P", "TRAUMA_HP"),
    ("History and Physical", "TRAUMA_HP"),

    # ED
    ("ED Provider Notes", "ED_NOTE"),
    ("Triage Assessment", "ED_NOTE"),
    ("Emergency Department", "ED_NOTE"),

    # Discharge
    ("Discharge Summary", "DISCHARGE"),
    ("Patient Discharge Summary", "DISCHARGE"),

    # Consults
    ("CONSULT", "CONSULT_NOTE"),
    ("Consult", "CONSULT_NOTE"),

    # Nursing
    ("Plan of Care", "NURSING_NOTE"),
    ("Nurse to Nurse", "NURSING_NOTE"),
    ("Nursing Assessment", "NURSING_NOTE"),

    # Case Management → NURSING_NOTE
    ("CASE MANAGEMENT", "NURSING_NOTE"),
    ("Case Management", "NURSING_NOTE"),

    # Physical/Occupational Therapy → PHYSICIAN_NOTE
    ("PHYSICAL THERAPY", "PHYSICIAN_NOTE"),
    ("OCCUPATIONAL THERAPY", "PHYSICIAN_NOTE"),

    # Procedures
    ("PROCEDURES", "PROCEDURE"),
    ("Procedure Note", "PROCEDURE"),

    # Progress Notes (physician/NP/PA)
    ("Trauma Progress Note", "PHYSICIAN_NOTE"),
    ("Progress Note", "PHYSICIAN_NOTE"),
    ("Hospital Progress Note", "PHYSICIAN_NOTE"),
    ("Progress Notes", "PHYSICIAN_NOTE"),

    # Spiritual/Chaplain
    ("SPIRITUAL CARE", "NURSING_NOTE"),
    ("PASTORAL CARE", "NURSING_NOTE"),
]

# ---------------------------------------------------------------------------
# Date of Service patterns
# ---------------------------------------------------------------------------
_DOS_RE = re.compile(
    r"(?:Date of Service|Encounter Date):\s*(\d{1,2}/\d{1,2}/\d{2,4}\s+\d{3,4})"
)
_DOS_FULL_RE = re.compile(
    r"(?:Date of Service|Encounter Date):\s*(\d{1,2}/\d{1,2}/\d{2,4}\s+\d{1,2}:\d{2}\s*(?:AM|PM)?)"
)

# ---------------------------------------------------------------------------
# ADT (Admission/Discharge/Transfer) event table pattern
# ---------------------------------------------------------------------------
_ADT_EVENT_RE = re.compile(
    r"^(\d{1,2}/\d{1,2}/\d{2,4})\s+(\d{4})\s+"  # date + time
    r"(.+?)(?:\s{2,}|\t)"                           # unit (tab or multi-space separated)
    r"(.+?)(?:\s{2,}|\t)"                           # room
    r"(.+?)(?:\s{2,}|\t)"                           # bed
    r"(.+?)(?:\s{2,}|\t)"                           # service
    r"(Admission|Transfer In|Transfer Out|Discharge|Patient Update)"  # event
)

# ---------------------------------------------------------------------------
# Standalone radiology report header
# ---------------------------------------------------------------------------
_RAD_HEADER_RE = re.compile(
    r"^(CT|XR|MR[AI]?|US|CTA|ECHO|EKG|EEG|PORTABLE|TRANSTHORACIC)\s",
    re.IGNORECASE,
)

# Patient metadata patterns
_PATIENT_NAME_RE = re.compile(r"Patient(?:\s+Name)?:\s*(.+?)(?:\s+DOB:|$)")
_DOB_RE = re.compile(r"DOB:\s*(\d{1,2}/\d{1,2}/\d{4})")
_MRN_RE = re.compile(r"MRN:\s*(\d+)")
_ADMIT_DATE_RE = re.compile(r"Admit(?:\s+Date)?:\s*(\d{1,2}/\d{1,2}/\d{4})")
_CATEGORY_RE = re.compile(r"Category\s+(\d)\s+(?:alert|trauma|activation)", re.IGNORECASE)
_ALERT_TIME_RE = re.compile(
    r"Category\s+\d\s+alert\s+at\s+(\d{4})",
    re.IGNORECASE,
)

# Noise lines to skip in header detection
_NOISE_LINES = {
    "Expand All Collapse All",
    "Revision History",
    "Routing History",
    "Signed",
    "Addendum",
    "Pended",
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class NoteSection:
    """A single clinical note section parsed from an Epic export."""
    source_type: str  # SourceType string value
    note_type_raw: str  # Original note type string from Epic
    provider: str
    provider_role: str
    timestamp: str  # ISO format or best-effort
    content: str
    line_start: int
    line_end: int


@dataclass
class PatientMetadata:
    """Patient identifying information extracted from Epic export."""
    patient_name: str = ""
    dob: str = ""
    mrn: str = ""
    admit_date: str = ""
    arrival_time: str = ""  # ISO format for engine
    trauma_category: str = ""


@dataclass
class ParsedExport:
    """Complete parsed result from an Epic export."""
    metadata: PatientMetadata = field(default_factory=PatientMetadata)
    sections: List[NoteSection] = field(default_factory=list)
    adt_events: List[Dict[str, str]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    source_file: str = ""


# ---------------------------------------------------------------------------
# Timestamp parsing
# ---------------------------------------------------------------------------
_TS_FORMATS = [
    "%m/%d/%y %H%M",
    "%m/%d/%Y %H%M",
    "%m/%d/%y %H:%M",
    "%m/%d/%Y %H:%M",
    "%m/%d/%Y %I:%M %p",
    "%m/%d/%y %I:%M %p",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y",
    "%m/%d/%y",
]


def _parse_timestamp(ts_str: str) -> str:
    """Parse Epic timestamp to ISO format. Returns original if unparseable."""
    if not ts_str:
        return ""
    s = ts_str.strip()
    for fmt in _TS_FORMATS:
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    # Try partial: just date
    return s


def _parse_dos_line(line: str) -> str:
    """Extract and parse Date of Service from a line."""
    m = _DOS_FULL_RE.search(line)
    if m:
        return _parse_timestamp(m.group(1))
    m = _DOS_RE.search(line)
    if m:
        return _parse_timestamp(m.group(1))
    return ""


# ---------------------------------------------------------------------------
# Core parser
# ---------------------------------------------------------------------------
def _is_provider_header(line: str) -> bool:
    """Check if a line is a provider name + credentials header."""
    stripped = line.strip()
    if not stripped or len(stripped) < 5:
        return False
    return bool(_PROVIDER_RE.match(stripped))


def _classify_note_type(text: str) -> Tuple[str, str]:
    """
    Classify a note type string into a source type.

    Returns: (source_type_str, matched_note_type)
    """
    for pattern, source_type in _NOTE_TYPE_PATTERNS:
        if pattern.lower() in text.lower():
            return (source_type, pattern)
    return ("PHYSICIAN_NOTE", text)


def _extract_metadata(lines: List[str]) -> PatientMetadata:
    """Extract patient metadata by scanning the file."""
    meta = PatientMetadata()
    # Scan first 2000 lines for most metadata
    full_text = "\n".join(lines[:2000])

    # Patient name
    m = _PATIENT_NAME_RE.search(full_text)
    if m:
        meta.patient_name = m.group(1).strip().rstrip(",")

    # DOB
    m = _DOB_RE.search(full_text)
    if m:
        meta.dob = m.group(1)

    # MRN - search first 2000 lines, then do targeted scan of full file if not found
    m = _MRN_RE.search(full_text)
    if m:
        meta.mrn = m.group(1)
    else:
        # MRN often appears in MAR section much later in the file
        for line in lines:
            m = _MRN_RE.search(line)
            if m:
                meta.mrn = m.group(1)
                break

    # Admit date
    m = _ADMIT_DATE_RE.search(full_text)
    if m:
        meta.admit_date = m.group(1)
        meta.arrival_time = _parse_timestamp(m.group(1))

    # Trauma category
    m = _CATEGORY_RE.search(full_text)
    if m:
        meta.trauma_category = m.group(1)

    return meta


def _extract_adt_events(lines: List[str]) -> Tuple[List[Dict[str, str]], int, str]:
    """
    Extract ADT events table from the beginning of the file.
    Epic ADT tables are tab-delimited.

    Returns: (events_list, last_adt_line_index, admission_time_iso)
    """
    events = []
    last_adt_line = 0
    _ADT_EVENT_TYPES = {"Admission", "Transfer In", "Transfer Out", "Discharge", "Patient Update"}

    for i, line in enumerate(lines[:50]):  # ADT table is always at the top
        stripped = line.strip()

        # Header line: starts with tab or "Unit"
        if stripped.startswith("Unit") and "\t" in line:
            last_adt_line = i
            continue

        # Data line: starts with date pattern and is tab-delimited
        if re.match(r"^\d{1,2}/\d{1,2}/\d{2,4}\s+\d{4}\t", stripped):
            # Split datetime from rest
            dt_match = re.match(r"^(\d{1,2}/\d{1,2}/\d{2,4})\s+(\d{4})\t(.+)$", stripped)
            if dt_match:
                date_str = dt_match.group(1)
                time_str = dt_match.group(2)
                rest = dt_match.group(3)
                fields = rest.split("\t")
                # fields: [unit, room, bed, service, event]
                if len(fields) >= 5:
                    event_type = fields[-1].strip()
                    if event_type in _ADT_EVENT_TYPES:
                        events.append({
                            "date": date_str,
                            "time": time_str,
                            "unit": fields[0].strip(),
                            "room": fields[1].strip() if len(fields) > 1 else "",
                            "bed": fields[2].strip() if len(fields) > 2 else "",
                            "service": fields[3].strip() if len(fields) > 3 else "",
                            "event": event_type,
                        })
                        last_adt_line = i
        elif events and not stripped:
            # Blank line after ADT events = end of table
            break

    # Extract admission time from first Admission event
    admission_time = ""
    for evt in events:
        if evt["event"] == "Admission":
            admission_time = _parse_timestamp(f"{evt['date']} {evt['time']}")
            break

    return events, last_adt_line, admission_time


def _find_note_boundaries(lines: List[str], start_from: int = 0) -> List[Dict[str, Any]]:
    """
    Find note section boundaries in the Epic export.

    Strategy:
    1. Scan for provider header lines (Name, Credentials)
    2. Look ahead for role, note type, and Date of Service
    3. Each confirmed boundary becomes a note section start

    Returns: List of boundary dicts with keys:
        line_idx, provider, role, note_type, source_type, timestamp
    """
    boundaries = []
    i = start_from

    while i < len(lines):
        line = lines[i].strip()

        # Check if this is a provider header
        if _is_provider_header(line):
            provider = line
            role = ""
            note_type = ""
            source_type = "PHYSICIAN_NOTE"
            timestamp = ""
            note_type_line = -1

            # Look ahead (up to 15 lines) for role, note type, Date of Service
            scan_end = min(i + 15, len(lines))
            for j in range(i + 1, scan_end):
                scan_line = lines[j].strip()

                if not scan_line:
                    continue

                # Check for role
                if not role:
                    for known_role in _KNOWN_ROLES:
                        if scan_line.startswith(known_role) or scan_line == known_role:
                            role = scan_line
                            break
                    # Also handle: "Specialty: X" or single-word role
                    if scan_line.startswith("Specialty:"):
                        role = role or scan_line

                # Check for note type
                if scan_line in _NOISE_LINES:
                    continue
                if "Date of Service:" in scan_line or "Encounter Date:" in scan_line:
                    timestamp = _parse_dos_line(scan_line)
                    break

                # Check note type patterns
                for pattern, st in _NOTE_TYPE_PATTERNS:
                    if pattern.lower() in scan_line.lower():
                        note_type = scan_line
                        source_type = st
                        note_type_line = j
                        break

            if not note_type and role:
                # Infer from role
                if "Nurse" in role or "RN" in role:
                    source_type = "NURSING_NOTE"
                    note_type = "Nursing Note"

            boundaries.append({
                "line_idx": i,
                "provider": provider,
                "role": role,
                "note_type": note_type or "Clinical Note",
                "source_type": source_type,
                "timestamp": timestamp,
            })

        i += 1

    return boundaries


def _extract_sections(
    lines: List[str],
    boundaries: List[Dict[str, Any]],
    adt_end: int = 0,
) -> List[NoteSection]:
    """
    Extract note sections based on detected boundaries.

    Each section spans from its boundary to the next boundary (or end of file).
    Content starts after the Date of Service line (or provider header if no DoS).
    """
    sections = []

    for idx, boundary in enumerate(boundaries):
        start = boundary["line_idx"]

        # End is the next boundary's start (or end of file)
        if idx + 1 < len(boundaries):
            end = boundaries[idx + 1]["line_idx"]
        else:
            end = len(lines)

        # Find where content actually starts (after Date of Service or a few lines
        # past the provider header)
        content_start = start
        for j in range(start, min(start + 20, end)):
            jline = lines[j].strip()
            if "Date of Service:" in jline or "Encounter Date:" in jline:
                content_start = j + 1
                break
            if jline == "Signed" or jline == "Addendum":
                content_start = j + 1

        # If we didn't find Date of Service, start a few lines after provider header
        if content_start == start:
            content_start = min(start + 3, end)

        # Extract content, skip noise lines
        content_lines = []
        for j in range(content_start, end):
            cline = lines[j]
            stripped = cline.strip()
            # Skip revision/routing history markers at the end of a section
            if stripped in ("Revision History", "Routing History"):
                break
            content_lines.append(cline)

        content = "\n".join(content_lines).strip()

        if content and len(content) > 20:  # Skip trivially short sections
            sections.append(NoteSection(
                source_type=boundary["source_type"],
                note_type_raw=boundary["note_type"],
                provider=boundary["provider"],
                provider_role=boundary["role"],
                timestamp=boundary["timestamp"],
                content=content,
                line_start=start + 1,  # 1-indexed
                line_end=end,
            ))

    return sections


def _detect_inline_sections(sections: List[NoteSection]) -> List[NoteSection]:
    """
    Post-process sections to detect inline labs and radiology within larger notes.

    Some H&P and progress notes contain inline "Labs:" and "Radiographs:" sections.
    These are valuable to also make available as standalone LAB/RADIOLOGY blocks
    for source-restricted pattern matching.

    We keep the original section intact AND add extracted sub-sections.
    """
    extra_sections = []

    for section in sections:
        text = section.content
        lines_local = text.split("\n")

        # Detect Labs: section
        lab_start = None
        for k, ln in enumerate(lines_local):
            if re.match(r"^Labs?\s*:", ln.strip(), re.IGNORECASE):
                lab_start = k
            elif lab_start is not None:
                # Labs end at the next major section header or blank-line-heavy gap
                if (ln.strip() and not ln.strip().startswith("•") and
                        not re.match(r"^[\s•\t]", ln) and
                        not re.match(r"^\w+\s+\d{1,2}/\d{1,2}/\d{2,4}", ln.strip()) and
                        re.match(r"^[A-Z][a-z]+:", ln.strip())):
                    # Found next section header
                    lab_text = "\n".join(lines_local[lab_start:k]).strip()
                    if len(lab_text) > 50:
                        extra_sections.append(NoteSection(
                            source_type="LAB",
                            note_type_raw="Labs (extracted)",
                            provider=section.provider,
                            provider_role=section.provider_role,
                            timestamp=section.timestamp,
                            content=lab_text,
                            line_start=section.line_start,
                            line_end=section.line_end,
                        ))
                    lab_start = None

        # If lab section runs to end of note
        if lab_start is not None:
            lab_text = "\n".join(lines_local[lab_start:]).strip()
            if len(lab_text) > 50:
                extra_sections.append(NoteSection(
                    source_type="LAB",
                    note_type_raw="Labs (extracted)",
                    provider=section.provider,
                    provider_role=section.provider_role,
                    timestamp=section.timestamp,
                    content=lab_text,
                    line_start=section.line_start,
                    line_end=section.line_end,
                ))

        # Detect radiology results within notes
        rad_start = None
        for k, ln in enumerate(lines_local):
            stripped = ln.strip()
            if re.match(r"^Radiographs?\s*:", stripped, re.IGNORECASE):
                rad_start = k
            elif re.match(r"^(CT|XR|MRI|CTA|US|ECHO|EKG|EEG)\s+", stripped, re.IGNORECASE):
                rad_start = k
            elif stripped.startswith("IMPRESSION:") and rad_start is not None:
                # Found end of a radiology block
                rad_text = "\n".join(lines_local[rad_start:k + 1]).strip()
                if len(rad_text) > 50:
                    extra_sections.append(NoteSection(
                        source_type="RADIOLOGY",
                        note_type_raw="Radiology (extracted)",
                        provider=section.provider,
                        provider_role=section.provider_role,
                        timestamp=section.timestamp,
                        content=rad_text,
                        line_start=section.line_start,
                        line_end=section.line_end,
                    ))
                rad_start = None

    return extra_sections


def _detect_standalone_radiology(lines: List[str], boundaries: List[Dict]) -> List[NoteSection]:
    """
    Detect standalone radiology report sections that don't have provider headers.

    These appear as blocks like:
        CT HEAD WO CONTRAST
        Result Date: 12/17/2025
        INDICATION: ...
        FINDINGS: ...
        IMPRESSION: ...
    """
    # Get all boundary line indices for gap detection
    boundary_lines = {b["line_idx"] for b in boundaries}
    rad_sections = []

    i = 0
    while i < len(lines):
        stripped = lines[i].strip()

        # Check for radiology order headers (often have "Order" or study type)
        if (re.match(r"^(CT|XR|MR[AI]?|CTA|US)\s+", stripped, re.IGNORECASE) and
                "Result Date:" in "\n".join(lines[i:min(i+5, len(lines))])):

            # Found a potential standalone radiology report
            rad_start = i
            rad_end = i
            has_impression = False

            for j in range(i, min(i + 100, len(lines))):
                jline = lines[j].strip()
                if jline.startswith("IMPRESSION:"):
                    has_impression = True
                # End on double blank line or next provider header or next study
                if j > i + 5 and (
                    (not lines[j].strip() and j + 1 < len(lines) and not lines[j + 1].strip()) or
                    _is_provider_header(lines[j].strip()) or
                    j in boundary_lines
                ):
                    rad_end = j
                    break
                rad_end = j

            if has_impression:
                content = "\n".join(lines[rad_start:rad_end + 1]).strip()
                if len(content) > 50:
                    # Extract timestamp from "Result Date:" if present
                    ts = ""
                    for rline in lines[rad_start:rad_start + 5]:
                        rm = re.search(r"Result Date:\s*(\d{1,2}/\d{1,2}/\d{4})", rline)
                        if rm:
                            ts = _parse_timestamp(rm.group(1))
                            break

                    rad_sections.append(NoteSection(
                        source_type="RADIOLOGY",
                        note_type_raw=stripped[:60],
                        provider="",
                        provider_role="",
                        timestamp=ts,
                        content=content,
                        line_start=rad_start + 1,
                        line_end=rad_end + 1,
                    ))
                i = rad_end + 1
                continue

        i += 1

    return rad_sections


def _detect_mar_section(lines: List[str]) -> List[NoteSection]:
    """
    Detect Medication Administration Record (MAR) / Rx Med Report sections.

    These typically appear as:
        Rx Med Report
        <patient name>
        <medication details...>
    """
    mar_sections = []

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "Rx Med Report" or stripped.startswith("Rx Med Report"):
            # Find the end of the MAR section
            mar_start = i
            mar_end = len(lines) - 1  # MAR is usually at the end

            # Look for next non-MAR section
            for j in range(i + 5, len(lines)):
                if _is_provider_header(lines[j].strip()):
                    mar_end = j - 1
                    break

            content = "\n".join(lines[mar_start:mar_end + 1]).strip()
            if len(content) > 100:
                mar_sections.append(NoteSection(
                    source_type="MAR",
                    note_type_raw="Medication Administration Record",
                    provider="",
                    provider_role="",
                    timestamp="",
                    content=content,
                    line_start=mar_start + 1,
                    line_end=mar_end + 1,
                ))
            break  # Usually only one MAR section

    return mar_sections


# ---------------------------------------------------------------------------
# Main parse function
# ---------------------------------------------------------------------------
def parse_epic_export(filepath: Path) -> ParsedExport:
    """
    Parse a raw Epic text export into structured note sections.

    Args:
        filepath: Path to the raw Epic .txt export file

    Returns:
        ParsedExport with metadata, sections, ADT events, and warnings
    """
    content = filepath.read_text(encoding="utf-8", errors="replace")
    # Normalize line endings
    content = content.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    lines = content.split("\n")

    result = ParsedExport(source_file=str(filepath))

    # Phase 1: Extract ADT events (top of file)
    adt_events, adt_end, adt_admission_time = _extract_adt_events(lines)
    result.adt_events = adt_events

    # Phase 2: Extract patient metadata
    result.metadata = _extract_metadata(lines)

    # ADT admission time is most precise (has hour:minute); prefer it over Admit Date
    if adt_admission_time:
        result.metadata.arrival_time = adt_admission_time
    # If no ADT, metadata.arrival_time from Admit Date is already set

    # Phase 3: Find note boundaries
    boundaries = _find_note_boundaries(lines, start_from=adt_end)

    if not boundaries:
        result.warnings.append("No note boundaries detected. File may not be a standard Epic export.")
        # Fall back: treat entire file as a single PHYSICIAN_NOTE
        result.sections.append(NoteSection(
            source_type="PHYSICIAN_NOTE",
            note_type_raw="Full Document (unparsed)",
            provider="Unknown",
            provider_role="",
            timestamp=result.metadata.arrival_time,
            content=content,
            line_start=1,
            line_end=len(lines),
        ))
        return result

    # Phase 4: Extract sections from boundaries
    sections = _extract_sections(lines, boundaries, adt_end)

    # Phase 5: Detect inline labs and radiology within notes
    inline_extras = _detect_inline_sections(sections)

    # Phase 6: Detect standalone radiology reports
    standalone_rad = _detect_standalone_radiology(lines, boundaries)

    # Phase 7: Detect MAR sections
    mar_sections = _detect_mar_section(lines)

    # Combine all sections
    all_sections = sections + inline_extras + standalone_rad + mar_sections

    # Sort by line_start for chronological ordering
    all_sections.sort(key=lambda s: s.line_start)

    result.sections = all_sections

    # Validation warnings
    source_types_found = {s.source_type for s in all_sections}
    if "TRAUMA_HP" not in source_types_found:
        result.warnings.append("No Trauma H&P section detected.")
    if not result.metadata.arrival_time:
        result.warnings.append("No arrival/admission time found.")
    if not result.metadata.patient_name:
        result.warnings.append("No patient name detected.")

    return result


# ---------------------------------------------------------------------------
# Output in CerebralOS engine format
# ---------------------------------------------------------------------------
def write_cerebralos_format(parsed: ParsedExport, output_path: Path) -> None:
    """
    Write parsed Epic export in CerebralOS engine-compatible format.

    Output format:
        PATIENT_ID: <name or MRN>
        ARRIVAL_TIME: <ISO timestamp>

        [SOURCE_TYPE] timestamp
        content...

        [SOURCE_TYPE] timestamp
        content...
    """
    patient_id = parsed.metadata.mrn or parsed.metadata.patient_name or "UNKNOWN"

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"PATIENT_ID: {patient_id}\n")
        f.write(f"ARRIVAL_TIME: {parsed.metadata.arrival_time}\n")
        if parsed.metadata.patient_name:
            f.write(f"PATIENT_NAME: {parsed.metadata.patient_name}\n")
        if parsed.metadata.dob:
            f.write(f"DOB: {parsed.metadata.dob}\n")
        if parsed.metadata.trauma_category:
            f.write(f"TRAUMA_CATEGORY: {parsed.metadata.trauma_category}\n")
        f.write("\n")

        for section in parsed.sections:
            ts = section.timestamp or parsed.metadata.arrival_time or ""
            f.write(f"[{section.source_type}] {ts}\n")
            f.write(section.content)
            f.write("\n\n")


# ---------------------------------------------------------------------------
# Batch processing
# ---------------------------------------------------------------------------
def process_patient_file(input_path: Path, output_dir: Path) -> ParsedExport:
    """Process a single patient file."""
    parsed = parse_epic_export(input_path)

    # Generate output filename
    safe_name = re.sub(r"[^\w\-.]", "_", input_path.stem)
    output_path = output_dir / f"{safe_name}.txt"

    write_cerebralos_format(parsed, output_path)
    return parsed


def process_directory(input_dir: Path, output_dir: Path) -> List[ParsedExport]:
    """Process all .txt patient files in a directory."""
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []

    for txt_file in sorted(input_dir.glob("*.txt")):
        # Skip non-patient files
        if txt_file.name.startswith(".") or "Protocol" in txt_file.name:
            continue
        print(f"  Parsing: {txt_file.name}")
        try:
            parsed = process_patient_file(txt_file, output_dir)
            results.append(parsed)
            n_sections = len(parsed.sections)
            source_counts = {}
            for s in parsed.sections:
                source_counts[s.source_type] = source_counts.get(s.source_type, 0) + 1
            print(f"    → {n_sections} sections: {source_counts}")
            if parsed.warnings:
                for w in parsed.warnings:
                    print(f"    ⚠ {w}")
        except Exception as e:
            print(f"    ERROR: {e}")
            results.append(ParsedExport(
                source_file=str(txt_file),
                warnings=[f"Parse error: {e}"],
            ))

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    import argparse

    ap = argparse.ArgumentParser(
        description="Parse Epic EHR exports for CerebralOS protocol evaluation"
    )
    ap.add_argument("--input", "-i", help="Single patient .txt file")
    ap.add_argument("--input-dir", help="Directory of patient .txt files")
    ap.add_argument("--output", "-o", help="Output file (single file mode)")
    ap.add_argument("--output-dir", default="data_raw",
                    help="Output directory (default: data_raw)")
    ap.add_argument("--summary", action="store_true",
                    help="Print parse summary only (no output files)")

    args = ap.parse_args()

    if args.input:
        input_path = Path(args.input)
        if not input_path.exists():
            print(f"ERROR: File not found: {input_path}")
            sys.exit(1)

        parsed = parse_epic_export(input_path)

        if args.summary:
            _print_summary(parsed)
        else:
            output_path = Path(args.output) if args.output else Path(args.output_dir) / f"{input_path.stem}.txt"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            write_cerebralos_format(parsed, output_path)
            print(f"Written: {output_path}")
            _print_summary(parsed)

    elif args.input_dir:
        input_dir = Path(args.input_dir)
        if not input_dir.is_dir():
            print(f"ERROR: Directory not found: {input_dir}")
            sys.exit(1)

        output_dir = Path(args.output_dir)
        print(f"Processing patient files from: {input_dir}")
        print(f"Output directory: {output_dir}")
        print()

        results = process_directory(input_dir, output_dir)

        print(f"\n{'='*60}")
        print(f"PROCESSED: {len(results)} files")
        print(f"{'='*60}")
    else:
        ap.print_help()
        sys.exit(1)


def _print_summary(parsed: ParsedExport):
    """Print a summary of the parsed export."""
    print(f"\n{'='*50}")
    print(f"Patient: {parsed.metadata.patient_name}")
    print(f"DOB: {parsed.metadata.dob}")
    print(f"MRN: {parsed.metadata.mrn}")
    print(f"Admission: {parsed.metadata.admit_date}")
    print(f"Arrival Time: {parsed.metadata.arrival_time}")
    print(f"Trauma Category: {parsed.metadata.trauma_category}")
    print(f"ADT Events: {len(parsed.adt_events)}")
    print(f"Note Sections: {len(parsed.sections)}")
    print()

    source_counts: Dict[str, int] = {}
    for s in parsed.sections:
        source_counts[s.source_type] = source_counts.get(s.source_type, 0) + 1

    print("Sections by type:")
    for st, count in sorted(source_counts.items()):
        print(f"  {st}: {count}")

    if parsed.warnings:
        print(f"\nWarnings ({len(parsed.warnings)}):")
        for w in parsed.warnings:
            print(f"  - {w}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
