#!/usr/bin/env python3
"""
Evidence text cleaning and extraction utilities.

Removes Epic UI garbage and extracts actual clinical content.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple


# Epic UI noise patterns to skip (line-level: entire line is noise)
_EPIC_NOISE_PATTERNS = [
    r"^Signed\s*$",
    r"^Expand All Collapse All\s*$",
    r"^Revision History\s*$",
    r"^Routing History\s*$",
    r"^Pended\s*$",
    r"^Addendum\s*$",
    r"^Date of Service:",
    r"^Encounter Date:",
    r"^\s*\d{1,2}/\d{1,2}/\d{2,4}\s+\d{3,4}\s*$",  # Timestamp lines
    r"^Result\s+Date\s*$",
    r"^Component\s*$",
    r"^Electronically\s+signed\b",
    r"^Cosigned\s+by\b",
    r"^Pended\s+by\b",
    r"^Authenticated\s+by\b",
    r"^Status:\s*(?:Signed|Auth|Final)\s*$",
    r"^\*{3,}",  # Separator lines (****)
    r"^-{5,}",  # Separator lines (-----)
    r"^={5,}",  # Separator lines (=====)
]

# Inline noise patterns: substrings within lines that should be stripped
_EPIC_INLINE_NOISE = [
    re.compile(r"Signed\s+Expand\s+All\s+Collapse\s+All\s*", re.IGNORECASE),
    re.compile(r"Expand\s+All\s+Collapse\s+All\s*", re.IGNORECASE),
    re.compile(r"Electronically\s+signed\s+by\s+[A-Za-z,.\-\s]+(?:MD|DO|PA-C|PA|NP|RN|FNP|APRN|CRNA)[\s,]*(?:on\s+\d{1,2}/\d{1,2}/\d{2,4}\s*(?:\d{3,4})?)?\s*", re.IGNORECASE),
    re.compile(r"Cosigned\s+by\s+[A-Za-z,.\-\s]+(?:MD|DO|PA-C|PA|NP|RN|FNP|APRN|CRNA)[\s,]*(?:on\s+\d{1,2}/\d{1,2}/\d{2,4}\s*(?:\d{3,4})?)?\s*", re.IGNORECASE),
    re.compile(r"Pended\s+by\s+[A-Za-z,.\-\s]+(?:MD|DO|PA-C|PA|NP|RN|FNP|APRN|CRNA)\s*", re.IGNORECASE),
    re.compile(r"Routing\s+History\s*", re.IGNORECASE),
    re.compile(r"Revision\s+History\s*", re.IGNORECASE),
]

# Provider header patterns (name + credentials)
_PROVIDER_HEADER_RE = re.compile(
    r"^[A-Z][a-zA-Z'\-]+,\s+[A-Z][a-zA-Z'\-]+.*(?:MD|DO|PA-C|PA|NP|RN|FNP|APRN|CRNA)",
    re.IGNORECASE
)

# Known roles that appear after provider headers
_ROLE_LINES = {
    "Physician", "Registered Nurse", "Nurse Practitioner",
    "Social Worker", "Case Manager", "Dietitian",
    "Physical Therapy", "Occupational Therapy",
    "Pharmacist", "Chaplain", "Respiratory Therapist",
    "Surgeon", "General Surgeon", "Attending Physician",
    "Resident", "Fellow", "Medical Student",
    "Physician Assistant", "Nurse Anesthetist",
}

# Section headers we want to preserve
_SECTION_HEADERS = {
    "Chief Complaint:", "History of Present Illness:", "HPI:",
    "Past Medical History:", "PMH:", "Past Surgical History:", "PSH:",
    "Medications:", "Allergies:", "Social History:",
    "Review of Systems:", "ROS:",
    "Physical Exam:", "Exam:", "PE:",
    "Assessment:", "A/P:", "Assessment and Plan:",
    "Plan:", "Impression:", "IMPRESSION:",
    "FINDINGS:", "TECHNIQUE:", "COMPARISON:",
    "INDICATION:", "HISTORY:",
}


def _is_noise_line(line: str) -> bool:
    """Check if a line is Epic UI noise that should be skipped."""
    stripped = line.strip()
    if not stripped:
        return False

    # Check noise patterns
    for pattern in _EPIC_NOISE_PATTERNS:
        if re.match(pattern, stripped, re.IGNORECASE):
            return True

    # Check provider headers
    if _PROVIDER_HEADER_RE.match(stripped):
        return True

    # Check role lines
    if stripped in _ROLE_LINES:
        return True

    return False


def _extract_clinical_sections(text: str) -> Dict[str, str]:
    """
    Extract clinical sections from note text.

    Returns dict mapping section name to content.
    """
    lines = text.split("\n")
    sections: Dict[str, str] = {}
    current_section: Optional[str] = None
    current_content: List[str] = []

    for line in lines:
        stripped = line.strip()

        # Skip noise
        if _is_noise_line(line):
            continue

        # Check if this is a section header
        is_header = False
        for header in _SECTION_HEADERS:
            if stripped.startswith(header):
                # Save previous section
                if current_section and current_content:
                    sections[current_section] = "\n".join(current_content).strip()

                # Start new section
                current_section = header
                current_content = []
                # Include text after header on same line
                after_header = stripped[len(header):].strip()
                if after_header:
                    current_content.append(after_header)
                is_header = True
                break

        if not is_header and current_section:
            # Add to current section
            if stripped:
                current_content.append(stripped)

    # Save last section
    if current_section and current_content:
        sections[current_section] = "\n".join(current_content).strip()

    return sections


def _strip_inline_noise(text: str) -> str:
    """Strip Epic UI noise that appears inline within text (not on separate lines)."""
    result = text
    for pattern in _EPIC_INLINE_NOISE:
        result = pattern.sub("", result)
    # Collapse multiple spaces left by stripping
    result = re.sub(r"  +", " ", result)
    return result.strip()


def clean_evidence_text(text: str, max_length: int = 500) -> str:
    """
    Clean Epic evidence text by removing UI noise and extracting clinical content.

    Two-pass cleaning:
    1. Line-level: skip entire lines that are pure noise (headers, timestamps, roles)
    2. Inline: strip noise substrings embedded within clinical lines

    Args:
        text: Raw evidence text from Epic export
        max_length: Maximum length of returned text

    Returns:
        Cleaned clinical text
    """
    if not text:
        return ""

    lines = text.split("\n")
    clean_lines: List[str] = []

    for line in lines:
        stripped = line.strip()

        # Skip full noise lines
        if _is_noise_line(line):
            continue

        # Skip blank lines at start
        if not clean_lines and not stripped:
            continue

        # Strip inline noise from within the line
        if stripped:
            cleaned = _strip_inline_noise(stripped)
            if cleaned:
                clean_lines.append(cleaned)

    # Join and truncate
    result = " ".join(clean_lines)
    if len(result) > max_length:
        result = result[:max_length].rstrip() + "..."

    return result


def extract_clinical_content(text: str) -> str:
    """
    Extract meaningful clinical content from raw evidence text.

    Unlike clean_evidence_text (which truncates), this function:
    - Strips all Epic UI noise (line-level and inline)
    - Preserves section structure
    - Returns full cleaned text without truncation

    Use this when you need the complete clinical text for analysis,
    not just a display snippet.

    Args:
        text: Raw evidence text from Epic export

    Returns:
        Full cleaned clinical text with section structure preserved
    """
    if not text:
        return ""

    lines = text.split("\n")
    clean_lines: List[str] = []

    for line in lines:
        stripped = line.strip()

        # Skip full noise lines
        if _is_noise_line(line):
            continue

        # Strip inline noise
        cleaned = _strip_inline_noise(stripped) if stripped else ""

        # Preserve blank lines within content for paragraph separation
        if clean_lines and not cleaned and clean_lines[-1]:
            clean_lines.append("")
        elif cleaned:
            clean_lines.append(cleaned)

    # Remove trailing blank lines
    while clean_lines and not clean_lines[-1]:
        clean_lines.pop()

    return "\n".join(clean_lines)


def extract_mechanism_of_injury(trauma_hp_text: str) -> Optional[str]:
    """
    Extract mechanism of injury from Trauma H&P.

    Looks for key phrases like "fall", "MVC", "GSW", etc.
    """
    if not trauma_hp_text:
        return None

    # Common mechanism patterns
    mech_patterns = [
        r"(?:mechanical )?fall(?:\s+from\s+(?:standing|height|ladder|stairs|vehicle))?",
        r"motor vehicle (?:collision|crash|accident)",
        r"MVC",
        r"motorcycle (?:collision|crash)",
        r"pedestrian struck",
        r"gunshot wound",
        r"GSW",
        r"stab wound",
        r"assault",
        r"bicycle crash",
    ]

    text_lower = trauma_hp_text.lower()
    for pattern in mech_patterns:
        match = re.search(pattern, text_lower, re.IGNORECASE)
        if match:
            # Extract surrounding sentence for context
            # Find sentence boundaries around the match
            match_pos = match.start()

            # Find start of sentence (period, question mark, or beginning of text)
            sentence_start = 0
            for i in range(match_pos - 1, max(0, match_pos - 250), -1):
                if trauma_hp_text[i] in '.!?':
                    sentence_start = i + 1
                    break

            # Find end of sentence (period, question mark, or newline)
            sentence_end = len(trauma_hp_text)
            for i in range(match.end(), min(len(trauma_hp_text), match.end() + 250)):
                if trauma_hp_text[i] in '.!?\n':
                    sentence_end = i + 1
                    break

            mechanism = trauma_hp_text[sentence_start:sentence_end].strip()

            # If too long, limit to 250 chars
            if len(mechanism) > 250:
                mechanism = mechanism[:250] + "..."

            return mechanism

    # Fallback: If HPI starts with age/demographics, extract first meaningful sentence after demographics
    if re.match(r"^\d+\s+(?:yo|y\.o\.|year old)", trauma_hp_text.strip(), re.IGNORECASE):
        # Skip past age and PMH, find "presents" or similar verb
        presents_match = re.search(r"(?:presents|admitted)\s+(?:as\s+)?(?:transfer\s+)?(?:from\s+\w+\s+)?(?:after|following|with)\s+.+?[.!?]",
                                  trauma_hp_text, re.IGNORECASE)
        if presents_match:
            return presents_match.group(0).strip()

    # Last fallback: return first sentence
    sentences = re.split(r'[.!?]\s+', trauma_hp_text)
    if sentences:
        first = sentences[0].strip()
        if len(first) > 250:
            first = first[:250] + "..."
        return first

    return None


def extract_injuries_from_imaging(imaging_text: str) -> List[str]:
    """
    Extract injury findings from imaging/radiology text.

    Returns list of injury descriptions.
    """
    if not imaging_text:
        return []

    injuries: List[str] = []

    # Look for IMPRESSION or FINDINGS section
    sections = _extract_clinical_sections(imaging_text)
    relevant_text = sections.get("IMPRESSION:", "") or sections.get("FINDINGS:", "") or imaging_text

    # Injury keywords
    injury_keywords = [
        "fracture", "hemorrhage", "hematoma", "contusion", "laceration",
        "pneumothorax", "hemothorax", "injury", "dissection", "rupture",
        "perforation", "bleed", "bleeding"
    ]

    lines = relevant_text.split("\n")
    for line in lines:
        line_lower = line.lower()
        if any(keyword in line_lower for keyword in injury_keywords):
            injuries.append(line.strip())

    return injuries


def extract_procedure_name(procedure_text: str) -> Optional[str]:
    """
    Extract procedure name from operative/procedure note.

    Returns the procedure title or first meaningful line.
    """
    if not procedure_text:
        return None

    lines = [line.strip() for line in procedure_text.split("\n") if line.strip()]

    # Skip noise lines at start
    clean_start = 0
    for i, line in enumerate(lines):
        if not _is_noise_line(line):
            clean_start = i
            break

    if clean_start < len(lines):
        first_line = lines[clean_start]
        # Limit length
        if len(first_line) > 150:
            first_line = first_line[:150] + "..."
        return first_line

    return None


def is_historical_reference(text: str) -> bool:
    """
    Check if text refers to historical/past events rather than current admission.

    Returns True if this appears to be historical data.
    """
    if not text:
        return False

    text_lower = text.lower()

    # Historical time references
    historical_patterns = [
        r"history of",
        r"past (?:medical|surgical) history",
        r"pmh",
        r"psh",
        r"previous(?:ly)?",
        r"prior to (?:admission|this)",
        r"\d+\s+(?:months?|years?|weeks?)\s+ago",
        r"remote history",
        r"old fracture",
        r"healed fracture",
        r"status post.*\d+\s+(?:months?|years?)",
    ]

    for pattern in historical_patterns:
        if re.search(pattern, text_lower):
            return True

    return False


def get_clean_snippet(
    evidence_obj,
    max_length: int = 300,
    skip_if_historical: bool = False
) -> Tuple[str, bool]:
    """
    Get clean evidence snippet from an Evidence object.

    Args:
        evidence_obj: Evidence object with .text attribute
        max_length: Maximum length of snippet
        skip_if_historical: If True, return empty string for historical references

    Returns:
        Tuple of (cleaned_text, is_historical)
    """
    if not hasattr(evidence_obj, 'text') or not evidence_obj.text:
        return ("", False)

    text = evidence_obj.text
    is_historical = is_historical_reference(text)

    if skip_if_historical and is_historical:
        return ("", True)

    cleaned = clean_evidence_text(text, max_length)
    return (cleaned, is_historical)


# ---------------------------------------------------------------------------
# H&P Section-Aware Parsing
# ---------------------------------------------------------------------------

# H&P section headers (Epic-specific format)
_HP_SECTION_HEADERS = {
    "Alert History": r"^Alert\s+History\s*:?",
    "Primary Survey": r"^Primary\s+Survey\s*:?",
    "HPI": r"^(?:History\s+of\s+Present\s+Illness|HPI)\s*:?",
    "Impression": r"^Impression\s*:?",
    "Plan": r"^Plan\s*:?",
    "ROS": r"^(?:Review\s+of\s+Systems|ROS)\s*:?",
    "Secondary Survey": r"^Secondary\s+Survey\s*:?",
    "Past Medical History": r"^(?:Past\s+Medical\s+History|PMH)\s*:?",
    "Past Surgical History": r"^(?:Past\s+Surgical\s+History|PSH)\s*:?",
    "Medications": r"^Medications\s*:?",
    "Allergies": r"^Allergies\s*:?",
    "Social History": r"^Social\s+History\s*:?",
    "Physical Exam": r"^(?:Physical\s+Exam|PE)\s*:?",
    "Assessment": r"^Assessment\s*:?",
    "Assessment and Plan": r"^Assessment\s+and\s+Plan\s*:?",
}


def extract_hp_sections(trauma_hp_text: str) -> Dict[str, str]:
    """
    Extract structured sections from Trauma H&P text.

    Args:
        trauma_hp_text: Raw Trauma H&P text from Epic export

    Returns:
        Dict mapping section name to content text
    """
    if not trauma_hp_text:
        return {}

    lines = trauma_hp_text.split("\n")
    sections: Dict[str, str] = {}
    current_section: Optional[str] = None
    current_content: List[str] = []

    for line in lines:
        stripped = line.strip()

        # Skip noise
        if _is_noise_line(line):
            continue

        # Check if this line is a section header
        matched_header = None
        for section_name, pattern in _HP_SECTION_HEADERS.items():
            if re.match(pattern, stripped, re.IGNORECASE):
                # Save previous section
                if current_section and current_content:
                    sections[current_section] = "\n".join(current_content).strip()

                # Start new section
                matched_header = section_name
                current_section = section_name
                current_content = []

                # Include text after header on same line
                after_header = re.sub(pattern, "", stripped, flags=re.IGNORECASE).strip()
                if after_header and after_header != ":":
                    current_content.append(after_header)
                break

        # If not a header, add to current section
        if not matched_header and current_section and stripped:
            current_content.append(stripped)

    # Save last section
    if current_section and current_content:
        sections[current_section] = "\n".join(current_content).strip()

    return sections


def extract_trauma_category(alert_history_text: str) -> Optional[str]:
    """
    Extract Trauma Category activation from Alert History section.

    Args:
        alert_history_text: Alert History section text

    Returns:
        Trauma category string (e.g., "Category 2") or None
    """
    if not alert_history_text:
        return None

    # Pattern: "Category X alert at HHMM"
    match = re.search(
        r"Category\s+(\d)\s+(?:alert|trauma|activation)",
        alert_history_text,
        re.IGNORECASE
    )
    if match:
        return f"Category {match.group(1)}"

    return None


def extract_gcs(primary_survey_text: str) -> Optional[int]:
    """
    Extract GCS (Glasgow Coma Scale) score from Primary Survey or Secondary Survey.

    Args:
        primary_survey_text: Primary Survey OR Secondary Survey section text

    Returns:
        GCS score as integer, or None if not found
    """
    if not primary_survey_text:
        return None

    # Pattern: "GCS: 15" or "GCS 15" or "Glasgow Coma Scale: 15"
    patterns = [
        r"GCS\s*:?\s*(\d+)",
        r"Glasgow\s+Coma\s+Scale\s*:?\s*(\d+)",
        r"Coma\s+Scale\s*:?\s*(\d+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, primary_survey_text, re.IGNORECASE)
        if match:
            gcs = int(match.group(1))
            # Validate GCS range (3-15)
            if 3 <= gcs <= 15:
                return gcs

    return None


def extract_fast_exam(primary_survey_text: str) -> Optional[str]:
    """
    Extract FAST exam result from Primary Survey.

    Args:
        primary_survey_text: Primary Survey section text

    Returns:
        FAST result string (e.g., "negative", "positive") or None
    """
    if not primary_survey_text:
        return None

    # Pattern: "FAST: negative" or "FAST exam negative"
    text_lower = primary_survey_text.lower()

    if "fast" in text_lower:
        # Extract context around "fast"
        match = re.search(
            r"fast(?:\s+exam)?[:\s]*([a-z\s]+?)(?:\.|$|\n)",
            text_lower,
            re.IGNORECASE
        )
        if match:
            result = match.group(1).strip()
            # Normalize result
            if "negative" in result or "neg" in result:
                return "negative"
            elif "positive" in result or "pos" in result:
                return "positive"
            elif "not performed" in result or "deferred" in result:
                return "not performed"
            else:
                return result[:50]  # Return raw if unknown format

    return None


def extract_consults_from_plan(plan_text: str) -> List[Dict[str, str]]:
    """
    Extract consult services and call times from Plan section.

    Args:
        plan_text: Plan section text

    Returns:
        List of dicts with keys: service, call_time, details
    """
    if not plan_text:
        return []

    consults = []
    lines = plan_text.split("\n")

    # Common consult service patterns
    service_patterns = [
        "Neurosurgery", "NSGY", "Orthopedics", "Ortho", "General Surgery",
        "Trauma Surgery", "Vascular Surgery", "Cardiothoracic", "CT Surgery",
        "Plastics", "Plastic Surgery", "ENT", "Ophthalmology", "Urology",
        "Gynecology", "GYN", "Anesthesia", "ICU", "SICU",
    ]

    for line in lines:
        stripped = line.strip()

        # Check if line mentions a consult service
        for service in service_patterns:
            if service.lower() in stripped.lower():
                # Try to extract call time (e.g., "at 1822", "called at 1830")
                time_match = re.search(
                    r"(?:at|called\s+at|@)\s*(\d{4}|\d{1,2}:\d{2})",
                    stripped,
                    re.IGNORECASE
                )
                call_time = time_match.group(1) if time_match else ""

                consults.append({
                    "service": service,
                    "call_time": call_time,
                    "details": stripped[:200],
                })
                break  # Only match first service per line

    return consults


def extract_injuries_from_impression(impression_text: str) -> List[str]:
    """
    Extract injury list from Impression section.

    Filters out historical references (PMH items mixed into impression).

    Args:
        impression_text: Impression section text

    Returns:
        List of current injury descriptions
    """
    if not impression_text:
        return []

    injuries = []
    lines = impression_text.split("\n")

    # Injury keywords (including abbreviations)
    injury_keywords = [
        "fracture", "fx", "hemorrhage", "hematoma", "contusion", "laceration",
        "pneumothorax", "pto", "hemothorax", "injury", "dissection", "rupture",
        "perforation", "bleed", "bleeding", "rib", "spinal cord",
        "sah", "sdh", "edh",  # subarachnoid/subdural/epidural hemorrhage
        "ich",  # intracranial hemorrhage
        "traumatic", "trauma",
    ]

    for line in lines:
        stripped = line.strip()

        # Skip if this looks like a historical reference
        if is_historical_reference(line):
            continue

        # Skip lines that are just demographic info
        if re.match(r"^\d+\s+(?:yo|y\.o\.|year old)", stripped, re.IGNORECASE):
            continue

        # Check if line mentions an injury keyword
        line_lower = stripped.lower()
        if any(keyword in line_lower for keyword in injury_keywords):
            # Clean up bullet points and dashes
            clean = re.sub(r"^[-•\-\*\d]+\.?\s*", "", stripped)
            if len(clean) > 2:  # Minimum meaningful length
                injuries.append(clean)

    return injuries
