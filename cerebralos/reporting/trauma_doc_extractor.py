#!/usr/bin/env python3
"""
Trauma Doc Extraction — Level II Contract Implementation.

Deterministic extraction of structured trauma documentation fields from
CerebralOS evaluation data. Follows the Trauma Doc Output contract:

    === TRAUMA SUMMARY ===
    === TRAUMA DAILY NOTES ===
    === GREEN CARD ===

Rules:
- Use ONLY information explicitly present in source text.
- NO inference, NO assumptions, NO "likely", NO filling gaps.
- Missing data → "NOT DOCUMENTED IN SOURCE"
- Military time (HHMM). Dates in MM/DD/YYYY.
- Concise clinical language. No narrative. No reasoning.
"""
from __future__ import annotations

import re
from collections import OrderedDict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

_NOT_DOCUMENTED = "NOT DOCUMENTED IN SOURCE"
_NONE_DOCUMENTED = "NONE DOCUMENTED"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _first_snippet(ev: Dict, source_type: str) -> Optional[Dict]:
    """Return first evidence snippet of given source type."""
    for s in ev.get("all_evidence_snippets", []):
        if s.get("source_type") == source_type:
            return s
    return None


def _snippets_by_type(ev: Dict, source_type: str) -> List[Dict]:
    """Return all evidence snippets of given source type."""
    return [s for s in ev.get("all_evidence_snippets", [])
            if s.get("source_type") == source_type]


def _snippets_for_date(ev: Dict, date_str: str) -> List[Dict]:
    """Return all evidence snippets for a given date (YYYY-MM-DD)."""
    results = []
    for s in ev.get("all_evidence_snippets", []):
        ts = s.get("timestamp") or ""
        if len(ts) >= 10 and ts[:10] == date_str:
            results.append(s)
    return results


def _to_military(time_str: str) -> str:
    """Convert time string to military time HHMM. Returns original if can't parse."""
    if not time_str:
        return ""
    # Already military time
    m = re.match(r"^(\d{4})$", time_str.strip())
    if m:
        return m.group(1)
    # HH:MM format
    m = re.match(r"(\d{1,2}):(\d{2})", time_str.strip())
    if m:
        return f"{int(m.group(1)):02d}{m.group(2)}"
    return time_str.strip()


def _to_mmddyyyy(date_str: str) -> str:
    """Convert YYYY-MM-DD date to MM/DD/YYYY format."""
    if not date_str:
        return ""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", date_str)
    if m:
        return f"{m.group(2)}/{m.group(3)}/{m.group(1)}"
    return date_str


def _format_arrival(arrival_time: str) -> str:
    """Format arrival_time (YYYY-MM-DD HH:MM:SS) to MM/DD/YYYY HHMM."""
    if not arrival_time:
        return _NOT_DOCUMENTED
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2})", arrival_time)
    if m:
        return f"{m.group(2)}/{m.group(3)}/{m.group(1)} {m.group(4)}{m.group(5)}"
    return arrival_time


def _clean_study_name(name: str) -> str:
    """Strip trailing underscores, dashes, and whitespace from study names."""
    return re.sub(r"[\s_\-]+$", "", name).strip()


def _is_radiology_note(text: str) -> bool:
    """Detect if a PHYSICIAN_NOTE is actually a radiology report.

    Epic sometimes classifies radiology reads as PHYSICIAN_NOTE.
    These contain TECHNIQUE/FINDINGS/IMPRESSION sections typical of rad reports.
    """
    text_lower = text[:500].lower()
    # Must have at least 2 of these radiology-report markers
    markers = ["technique:", "findings:", "impression:", "indication:",
               "narrative & impression", "comparison:", "history:"]
    return sum(1 for m in markers if m in text_lower) >= 2


def _is_pharmacy_note(text: str) -> bool:
    """Detect if a PHYSICIAN_NOTE is actually a pharmacy/order note."""
    text_lower = text[:300].lower()
    return any(k in text_lower for k in ["dea #:", "pharmacy", "quantity remaining"])


def _is_nonclinical_note(text: str) -> bool:
    """Detect if a PHYSICIAN_NOTE is non-clinical (order audit, rate/dose, medication list, etc.)."""
    text_start = text[:200].lower()
    if any(skip in text_start for skip in [
        "warnings override", "rate/dose verify", "order audit trail",
        "current outpatient medications", "narrative & impression",
    ]):
        return True
    # Single bullet entry (PMH/order line from Epic)
    if text.strip().startswith("\u2022") and len(text.strip()) < 200:
        return True
    return False


def _clean_epic_artifacts(text: str) -> str:
    """Strip Epic UI artifacts from extracted context snippets."""
    # Remove "important suggestion  View ..." artifacts (may be truncated mid-word)
    text = re.sub(r"\s*important\s+suggest(?:ion)?.*$", "", text, flags=re.IGNORECASE)
    # Remove bare trailing "important" (truncated before "suggestion")
    text = re.sub(r"\s+important\s*$", "", text, flags=re.IGNORECASE)
    # Remove "View Full Report" / "View Detailed Reports" etc.
    text = re.sub(r"\s*View\s+(?:Full|Detailed|Condensed)\s+\w+.*", "", text, flags=re.IGNORECASE)
    return text.strip()


def _clean_plan_text(plan: str, max_len: int = 300) -> str:
    """Clean plan text: strip provider attestation, Epic artifacts, trailing noise."""
    # Remove provider attestation lines at end
    plan = re.sub(
        r"(?:I have seen|Electronically Signed|I have reviewed|I personally).*$",
        "", plan, flags=re.IGNORECASE | re.DOTALL
    ).strip()
    # Remove "Based upon..." trailing commentary
    plan = re.sub(r"\n\s*Based upon.*$", "", plan, flags=re.IGNORECASE | re.DOTALL).strip()
    # Remove "Discussed with..." trailing commentary
    plan = re.sub(r"\n\s*Discussed with.*$", "", plan, flags=re.IGNORECASE | re.DOTALL).strip()
    # Remove MyChart and other Epic UI artifacts BEFORE provider name cleanup
    plan = re.sub(r"\s*MyChart\s*(?:no|yes)?\s*$", "", plan, flags=re.IGNORECASE).strip()
    # Remove provider name + credentials at end (e.g., "Joshua C Barajas, PA-C")
    # Handles: "FirstName [Middle] LastName, CREDENTIAL" with 2-4 name parts
    # Works whether preceded by newline or space (inline plan text)
    plan = re.sub(
        r"[\n\s]+[A-Z][a-z]+(?:\s+[A-Z][a-z]*\.?)*\s+[A-Z][a-z]+,?\s+"
        r"(?:PA-C|NP|MD|DO|AGACNP|APP|RN|MSN|APRN|FNP|CNS|DNP|CRNA)\s*$",
        "", plan
    ).strip()
    # Clean general Epic artifacts
    plan = _clean_epic_artifacts(plan)
    return plan[:max_len]


def _snap_context(text: str, match_start: int, match_end: int,
                  before: int = 20, after: int = 60, max_len: int = 200) -> str:
    """Extract context around a match, snapping to word boundaries and cleaning artifacts."""
    start = max(0, match_start - before)
    end = min(len(text), match_end + after)

    # Snap start forward to next word boundary (after space/newline)
    if start > 0:
        space = text.find(" ", start)
        newline = text.find("\n", start)
        if space != -1 and space < match_start:
            start = space + 1
        elif newline != -1 and newline < match_start:
            start = newline + 1

    # Snap end backward to last word boundary
    if end < len(text):
        last_space = text.rfind(" ", match_end, end)
        if last_space > match_end:
            end = last_space

    result = text[start:end].strip()
    return _clean_epic_artifacts(result)[:max_len]


def _is_trauma_progress_note(text: str) -> bool:
    """Detect if a PHYSICIAN_NOTE is an ESA / Trauma Service progress note.

    These are the primary trauma notes — captain of the ship.
    They contain 'Trauma Progress Note' or 'Progress Note' from trauma attendings/APPs.
    """
    return "Trauma Progress Note" in text[:200] or "Progress Note" in text[:50]


def _parse_progress_note_sections(text: str) -> Dict[str, str]:
    """Parse an ESA Trauma Progress Note into sections.

    Typical structure:
      Trauma Progress Note <Provider>
      HPI: ...
      CC: ...
      SUBJECTIVE: ...
      PE: General: ... Vitals: ... GCS: ... Lungs: ... Neurologic: ...
      Radiographs: ...
      Labs: ...
      Prophylaxis: ...
      Impression: ...
      Plan: ...
    """
    sections: Dict[str, str] = {}
    # These are the major section markers in ESA progress notes
    section_markers = [
        "HPI:", "CC:", "SUBJECTIVE:", "PE:", "Radiographs:", "Labs:",
        "Prophylaxis:", "Impression:", "Plan:",
    ]

    text_lower = text.lower()
    positions = []
    for marker in section_markers:
        idx = text_lower.find(marker.lower())
        if idx != -1:
            positions.append((idx, marker.rstrip(":")))

    positions.sort(key=lambda x: x[0])

    for i, (pos, name) in enumerate(positions):
        start = pos + len(name) + 1  # skip past "Name:"
        end = positions[i + 1][0] if i + 1 < len(positions) else len(text)
        section_text = text[start:end].strip()
        sections[name.lower()] = section_text

    return sections


# ---------------------------------------------------------------------------
# TRAUMA_HP section parser
# ---------------------------------------------------------------------------

def _parse_hp_sections(hp_text: str) -> Dict[str, str]:
    """
    Parse TRAUMA_HP into named sections.

    Returns dict mapping section name (lowercase) to section text.
    """
    sections: Dict[str, str] = {}
    # Known section headers in Epic Trauma H&P
    section_headers = [
        "HPI", "Alert History", "Primary Survey", "Secondary Survey",
        "PMH", "PAST MEDICAL HISTORY", "Past Medical History",
        "Meds", "Medications", "Current Outpatient Medications",
        "Allergies", "Social History", "Family History",
        "Review of Systems", "ROS",
        "Physical Exam", "PHYSICAL EXAM", "Exam",
        "Assessment", "Plan", "Assessment/Plan", "Assessment and Plan",
        "Imaging", "Radiographs", "Labs",
        "Disposition", "Admit",
    ]

    current_section = "header"
    current_text: List[str] = []

    for line in hp_text.split("\n"):
        stripped = line.strip()
        # Check if this line is a section header
        matched = False
        for hdr in section_headers:
            if stripped.startswith(hdr + ":") or stripped == hdr:
                # Save previous section
                if current_text:
                    sections[current_section.lower()] = "\n".join(current_text).strip()
                current_section = hdr
                current_text = [stripped]
                matched = True
                break
        if not matched:
            current_text.append(line)

    # Save last section
    if current_text:
        sections[current_section.lower()] = "\n".join(current_text).strip()

    return sections


def _extract_gcs(hp_text: str) -> str:
    """Extract GCS from TRAUMA_HP text."""
    # Look for explicit GCS score patterns
    patterns = [
        r"GCS\s*[:=]?\s*(\d{1,2})\b",
        r"Glasgow\s+Coma\s+Scale\s*[:=]?\s*(\d{1,2})",
        r"GCS\s+(?:of\s+)?(\d{1,2})",
        r"GCS\s+(\d{1,2})\s*[/\(]",
    ]
    for pat in patterns:
        m = re.search(pat, hp_text, re.IGNORECASE)
        if m:
            return m.group(1)

    # Check for "GCS PERRLA" or similar descriptive
    if re.search(r"GCS\s+PERRLA", hp_text, re.IGNORECASE):
        return "15 (GCS PERRLA noted)"

    return _NOT_DOCUMENTED


def _extract_initial_vitals(hp_text: str) -> str:
    """Extract initial vitals from TRAUMA_HP Secondary Survey / Vitals section."""
    # Try to extract from Secondary Survey / Vitals section first for accuracy
    sections = _parse_hp_sections(hp_text)
    search_text = sections.get("secondary survey", "")
    if not search_text:
        # Fall back to full text but this may have false positives
        search_text = hp_text

    vitals = []

    # Blood pressure — handle "(!) " or other chars between keyword and value
    bp = re.search(r"(?:BP|[Bb]lood\s+[Pp]ressure)\s*[^0-9]{0,10}(\d{2,3}/\d{2,3})", search_text)
    if bp:
        vitals.append(f"BP {bp.group(1)}")

    # Heart rate / Pulse
    hr = re.search(r"(?:HR|[Hh]eart\s+[Rr]ate|[Pp]ulse)\s*[:=]?\s*(\d{2,3})", search_text)
    if hr:
        vitals.append(f"HR {hr.group(1)}")

    # Temperature — NO bare "T" to avoid matching times like "at 1822"
    temp = re.search(r"(?:[Tt]emp(?:erature)?)\s*[:=]?\s*([\d.]+)\s*(?:°?\s*[FC])?", search_text)
    if temp:
        val = temp.group(1)
        # Sanity check: temperature should be 90-110 F or 30-43 C
        try:
            fval = float(val)
            if 85.0 <= fval <= 115.0 or 30.0 <= fval <= 45.0:
                vitals.append(f"Temp {val}")
        except ValueError:
            pass

    # Respiratory rate — handle "resp. rate" with period
    rr = re.search(r"(?:RR|[Rr]esp\.?\s*(?:[Rr]ate)?)\s*[:=]?\s*(\d{1,2})", search_text)
    if rr:
        vitals.append(f"RR {rr.group(1)}")

    # SpO2
    spo2 = re.search(r"(?:SpO2|O2\s*[Ss]at)\s*[:=]?\s*(\d{2,3})%?", search_text)
    if spo2:
        vitals.append(f"SpO2 {spo2.group(1)}%")

    # Hemodynamics from Primary Survey as fallback
    if not vitals:
        hd = re.search(r"(?:Circulation|HD)\s*[:=]?\s*(.+?)(?:\n|$)", hp_text, re.IGNORECASE)
        if hd:
            vitals.append(hd.group(1).strip())

    return ", ".join(vitals) if vitals else _NOT_DOCUMENTED


def _extract_mechanism(hp_text: str) -> str:
    """Extract mechanism of injury from TRAUMA_HP HPI."""
    sections = _parse_hp_sections(hp_text)

    # Try HPI section first
    hpi = sections.get("hpi", "")
    if hpi:
        # Strip the "HPI:" prefix
        hpi = re.sub(r"^HPI\s*:\s*", "", hpi).strip()
        # Take mechanism sentence (usually first 1-2 sentences up to "presents" or "denies")
        # Find the core mechanism
        mech_match = re.search(
            r"(?:presents?\s+(?:as|with|after|from)|"
            r"(?:status\s+post|s/p)|"
            r"(?:involved\s+in|was\s+in)|"
            r"(?:fell|fall|struck|hit|ejected|rollover|collision|MVC|MVA|GSW|stab))",
            hpi, re.IGNORECASE
        )
        if mech_match:
            # Take from start of HPI to end of the mechanism description
            # Find end (period, "Denies", or 200 chars)
            text = hpi[:300]
            end_match = re.search(r"\.\s+(?:Denies|Patient\s+denies|He\s+denies|She\s+denies)", text)
            if end_match:
                text = text[:end_match.start() + 1]
            return text.strip()

        # Fallback: first 200 chars of HPI
        text = hpi[:200]
        if len(hpi) > 200:
            text += "..."
        return text.strip()

    # Try Alert History
    alert = sections.get("alert history", "")
    if alert:
        return re.sub(r"^Alert\s+History\s*:\s*", "", alert).strip()[:200]

    return _NOT_DOCUMENTED


def _extract_impression(text: str) -> str:
    """Extract IMPRESSION section from a radiology report text.

    Tries IMPRESSION first (preferred — concise summary), then FINDINGS.
    Returns the extracted text or empty string.
    """
    # Try IMPRESSION first (more specific, concise)
    imp_match = re.search(
        r"IMPRESSION\s*:\s*(.+?)(?:$|\n\n|\b(?:FINDINGS|TECHNIQUE|HISTORY|COMPARISON)\b)",
        text, re.IGNORECASE | re.DOTALL
    )
    if imp_match:
        result = imp_match.group(1).strip()
        if result:  # Not empty (handles truncated "IMPRESSION:" with nothing after)
            return result

    # Fall back to FINDINGS
    findings_match = re.search(
        r"FINDINGS\s*:\s*(.+?)(?:$|\n\n|\bIMPRESSION\b)",
        text, re.IGNORECASE | re.DOTALL
    )
    if findings_match:
        return findings_match.group(1).strip()

    return ""


def _split_impression_sentences(imp_text: str) -> List[str]:
    """Split impression text into individual findings (sentences or numbered items)."""
    # Try numbered items first: "1. ...", "2. ..."
    numbered = re.findall(r"\d+\.\s*([^0-9].+?)(?=\d+\.\s|$)", imp_text, re.DOTALL)
    if numbered and len(numbered) > 1:
        return [n.strip() for n in numbered if n.strip()]

    # Fall back to sentence splitting (period + space or period + end)
    sentences = re.split(r"\.\s+", imp_text)
    return [s.strip().rstrip(".") for s in sentences if s.strip()]


def _extract_primary_injuries(ev: Dict) -> str:
    """Extract primary injury diagnoses from imaging IMPRESSION sections."""
    injuries = []
    seen_studies = set()

    for s in _snippets_by_type(ev, "RADIOLOGY"):
        text = s.get("text", "")

        # Deduplicate: skip if we've already seen this exact study text
        text_key = text[:100]
        if text_key in seen_studies:
            continue
        seen_studies.add(text_key)

        impression = _extract_impression(text)
        if not impression:
            continue

        # Split into individual findings/sentences
        sentences = _split_impression_sentences(impression)
        for sentence in sentences:
            if not sentence or len(sentence) < 5:
                continue
            sl = sentence.lower()
            # Acute injury keyword check (used for exception logic below)
            has_acute_keyword = any(acute in sl for acute in [
                "fracture", "hemorrhage", "hematoma", "laceration",
                "contusion", "dislocation", "pneumothorax", "hemothorax",
            ])
            # Skip negative findings
            if any(neg in sl for neg in [
                "no acute", "no evidence", "unremarkable", "no significant",
                "negative", "no fracture", "no pneumothorax", "no radiographic",
                "no osseous", "no abnormality", "impression not captured",
                "no dvt", "no deep vein", "within normal limits",
                "no pulmonary embol", "no stenosis", "normal radiograph",
                "normal study", "normal exam",
            ]):
                continue
            # Skip non-injury clinical findings (incidental, pre-existing, minor)
            if not has_acute_keyword and any(noninj in sl for noninj in [
                "atelectasis", "pleural effusion", "cardiomegaly",
                "spondylosis", "spondylolisthesis",
                "correlation with tenderness", "further evaluated by mri",
                "can be further evaluated",
                "central line", "tube in place", "catheter",
                "stenosis", "occlusion",
                "otherwise stable", "stable cardiopulmonary",
                "result date:", "xr ", "ct ",
                "pulmonary nodule", "endotracheal tube", "et tube",
                "ng tube", "og tube", "foley",
                "recommend", "suggest", "correlate for",
                "tip projects", "appropriately positioned",
            ]):
                continue
            # Skip "unchanged" only if it's the primary descriptor (not "unchanged SAH")
            if sl.startswith("unchanged") and "hemorrhage" not in sl and "hematoma" not in sl:
                continue
            # Skip chronic/degenerative/incidental findings (not acute injuries)
            # But DON'T skip if the sentence contains an acute injury keyword
            if not has_acute_keyword and any(chronic in sl for chronic in [
                "degenerative", "osteoarthr", "osteopeni", "osteoporosi",
                "calcification", "atrophic", "volume loss", "encephalomalacia",
                "chronic deformity", "chronic nondisplaced",
                "joint spaces are maintained", "joint spaces maintained",
                "soft tissue swelling about",
            ]):
                continue
            # Skip findings that start with "chronic" (chronic findings, not acute injuries)
            if sl.startswith("chronic") and not has_acute_keyword:
                continue
            # Skip vague references and formatting artifacts
            if any(skip in sl for skip in [
                "chronic changes as above", "as above", "____",
                "findings discussed with", "preliminary report",
            ]):
                continue
            # Skip lines that are just delimiters or very short
            if re.match(r"^[_\-=\s]+$", sentence):
                continue
            # Clean numbering
            clean = re.sub(r"^\d+\.\s*", "", sentence).strip()
            if clean and len(clean) > 5:
                injuries.append(clean[:200])

    if not injuries:
        return _NOT_DOCUMENTED

    # Deduplicate by normalized prefix
    seen = set()
    unique = []
    for inj in injuries:
        key = inj.lower()[:50]
        if key not in seen:
            seen.add(key)
            unique.append(inj)

    return "; ".join(unique[:8])


def _extract_imaging_results(ev: Dict) -> str:
    """Extract imaging results (positive and negative) from RADIOLOGY blocks."""
    results = []
    seen_studies = set()

    for s in _snippets_by_type(ev, "RADIOLOGY"):
        text = s.get("text", "")
        ts = s.get("timestamp", "")
        date = _to_mmddyyyy(ts[:10]) if ts else ""

        # Extract study name
        study_match = re.match(r"(?:Radiographs:\s+)?(.+?)(?:\s+Result Date|\s+INDICATION|\s+HISTORY)", text)
        study_name = _clean_study_name(study_match.group(1)) if study_match else "Imaging study"

        # Deduplicate by study name
        study_key = study_name.lower()[:40]
        if study_key in seen_studies:
            continue
        seen_studies.add(study_key)

        # Extract impression using shared helper
        impression = _extract_impression(text)
        if impression:
            # Condense to first 150 chars
            if len(impression) > 150:
                impression = impression[:150] + "..."
            results.append(f"{study_name} ({date}): {impression}")
        else:
            results.append(f"{study_name} ({date}): impression not captured")

    if not results:
        return _NOT_DOCUMENTED

    return "; ".join(results[:6])


def _extract_interventions(ev: Dict) -> str:
    """Extract ED and OR interventions."""
    interventions = []

    # From TRAUMA_HP — search only relevant sections (not PMH/surgical history)
    hp = _first_snippet(ev, "TRAUMA_HP")
    if hp:
        hp_text = hp.get("text", "")
        sections = _parse_hp_sections(hp_text)
        # Only search in clinical sections, NOT in PMH/Surgical Hx/Meds
        search_sections = []
        for key in ["primary survey", "secondary survey", "assessment", "plan",
                     "assessment/plan", "assessment and plan", "impression", "header"]:
            if key in sections:
                search_sections.append(sections[key])
        combined = "\n".join(search_sections)

        for pattern in [
            r"(?:intubat|chest\s+tube|central\s+line|arterial\s+line|"
            r"foley|splint|reduction|pelvic\s+binder|tourniquet|"
            r"massive\s+transfusion|blood\s+products|"
            r"(?<![Nn]euro)surgery(?!\s+consult)|OR\s+for|"
            r"taken\s+to\s+(?:the\s+)?OR)",
        ]:
            for m in re.finditer(pattern, combined, re.IGNORECASE):
                context = _snap_context(combined, m.start(), m.end(), before=20, after=40, max_len=150)
                interventions.append(context)

    # From ED_NOTE
    for s in _snippets_by_type(ev, "ED_NOTE"):
        text = s.get("text", "")
        for keyword in ["intubat", "chest tube", "line placed", "transfusion", "splint"]:
            if keyword in text.lower():
                for sent in re.split(r'[.!?]+', text):
                    if keyword in sent.lower():
                        interventions.append(sent.strip()[:150])
                        break

    # From DISCHARGE — look for "Surgical Treatment and Procedures" section
    discharge = _first_snippet(ev, "DISCHARGE")
    if discharge:
        text = discharge.get("text", "")
        surg_match = re.search(
            r"(?:Surgical\s+Treatment|Procedures?)\s*(?:and\s+Procedures?)?\s*:\s*(.+?)(?:\n\d+\.|\s+\d+\.\s|\Z)",
            text, re.IGNORECASE | re.DOTALL
        )
        if surg_match:
            result = surg_match.group(1).strip()
            if result.lower() not in ("none", "n/a", ""):
                interventions.append(result[:150])

    if not interventions:
        return _NOT_DOCUMENTED

    # Deduplicate
    seen = set()
    unique = []
    for item in interventions:
        key = item.lower()[:30]
        if key not in seen:
            seen.add(key)
            unique.append(item)

    return "; ".join(unique[:5])


def _extract_disposition(ev: Dict) -> str:
    """Extract disposition from DISCHARGE or status."""
    discharge = _first_snippet(ev, "DISCHARGE")
    if discharge:
        text = discharge.get("text", "")

        # Look for discharge disposition patterns (most specific first)
        disp_patterns = [
            r"(?:Discharge\s+(?:Disposition|Status))\s*:?\s*(.+?)(?:\n|$)",
            # Handle numbered format: "9. Disposition: ..." (before "Discharged to")
            r"\d+\.\s*Disposition\s*:\s*(.+?)(?:\n|$)",
            # Standalone "Disposition:" anywhere in the text
            r"Disposition\s*:\s*(.+?)(?:\n|$)",
            # "Discharged to" (less specific — captures after "to")
            r"(?:Discharged?\s+to)\s*:?\s*(.+?)(?:\n|$)",
            # "Discharge condition" section
            r"Discharge\s+[Cc]ondition\s*:\s*(.+?)(?:\n|$)",
        ]
        for pat in disp_patterns:
            disp_match = re.search(pat, text, re.IGNORECASE)
            if disp_match:
                result = disp_match.group(1).strip()
                if result and len(result) > 2:
                    # Truncate at next numbered section (e.g., "10. Instructions...")
                    result = re.split(r"\s+\d+\.\s", result)[0].strip()
                    # Truncate at next section marker
                    result = re.split(r"\n\s*(?:Instructions|Follow|Medications|Diet|Activity|Wound|Seek)", result)[0].strip()
                    # Truncate at electronic signature
                    result = re.split(r"\s*Electronically signed", result, flags=re.IGNORECASE)[0].strip()
                    # Truncate at "Instructions for" (same line)
                    result = re.split(r"\s+Instructions for", result, flags=re.IGNORECASE)[0].strip()
                    return result[:80]

        # Look for admit/discharge dates as fallback
        discharge_date = re.search(r"Discharge\s+Date\s*:?[^0-9]*(\d{1,2}/\d{1,2}/\d{2,4})", text, re.IGNORECASE)
        if discharge_date:
            return f"Discharged {discharge_date.group(1)}"

    if ev.get("is_live"):
        return "In hospital"

    return _NOT_DOCUMENTED


def _extract_pmh(hp_text: str) -> str:
    """Extract past medical history from TRAUMA_HP."""
    sections = _parse_hp_sections(hp_text)

    # Check "past medical history" FIRST (contains actual diagnoses),
    # then "pmh" (may only contain the header "PMH: PAST MEDICAL HISTORY")
    for key in ["past medical history", "pmh"]:
        pmh = sections.get(key, "")
        if not pmh:
            continue

        # Extract diagnosis lines (bullets followed by tab: "•\t<diagnosis>\t<date>")
        diagnoses = []
        for line in pmh.split("\n"):
            line = line.strip()
            if not line:
                continue
            # Match Epic bullet format: "•" followed by tab-separated fields
            if line.startswith("•"):
                line = line.lstrip("•").strip()
                # Remove tab + date column at end (MM/DD/YYYY format)
                line = re.sub(r"\t\d{1,2}/\d{1,2}/\d{2,4}$", "", line).strip()
                # Remove tab-separated trailing content (date, status columns)
                # Keep only the first tab-delimited field (diagnosis name)
                if "\t" in line:
                    line = line.split("\t")[0].strip()
                if line and len(line) > 2:
                    # Skip sub-descriptions (indented lines that start with lowercase)
                    diagnoses.append(line)
            elif line.startswith("\t") or line.startswith(" \t"):
                # Indented sub-description — skip (these are dates, notes, etc.)
                continue

        if diagnoses:
            return "; ".join(diagnoses[:10])

        # Fallback: raw section text with header stripped
        cleaned = re.sub(
            r"^(?:PMH|PAST MEDICAL HISTORY|Past Medical History)\s*:?\s*",
            "", pmh, flags=re.IGNORECASE
        ).strip()
        # Also strip the "Diagnosis\tDate" column header
        cleaned = re.sub(r"^Diagnosis\s+Date\s*\n?", "", cleaned).strip()
        if cleaned and cleaned.upper() != "PAST MEDICAL HISTORY":
            return cleaned[:300]

    return _NOT_DOCUMENTED


def _extract_home_blood_thinners(hp_text: str) -> str:
    """Extract whether patient was on blood thinners at home from TRAUMA_HP medications."""
    blood_thinner_names = [
        "warfarin", "coumadin", "eliquis", "apixaban", "xarelto", "rivaroxaban",
        "pradaxa", "dabigatran", "lovenox", "enoxaparin", "heparin", "plavix",
        "clopidogrel", "aspirin", "brilinta", "ticagrelor", "effient", "prasugrel",
    ]

    found = []
    text_lower = hp_text.lower()

    for med in blood_thinner_names:
        if med in text_lower:
            # Check if it's in the medications section or HPI
            # Look for context
            idx = text_lower.find(med)
            context = hp_text[max(0, idx - 50):idx + 80]
            # Check if discontinued
            if "discontinued" in context.lower() or "[discontinued]" in context.lower():
                found.append(f"{med} (DISCONTINUED)")
            else:
                found.append(med)

    if found:
        return "YES — " + ", ".join(found)

    return "NO (no blood thinners documented in home medications)"


def _extract_dvt_prophylaxis(ev: Dict) -> str:
    """Extract first DVT prophylaxis dose date/time from MAR."""
    mar = _first_snippet(ev, "MAR")
    if not mar:
        return _NOT_DOCUMENTED

    text = mar.get("text", "")
    text_lower = text.lower()

    # DVT prophylaxis medications
    dvt_meds = ["enoxaparin", "lovenox", "heparin prophyl", "heparin 5000",
                 "heparin 5,000", "fondaparinux", "arixtra"]

    for med in dvt_meds:
        if med in text_lower:
            # Find the section for this medication
            idx = text_lower.find(med)
            section = text[max(0, idx - 200):idx + 500]

            # Look for administration date/time
            admin_match = re.search(
                r"(?:Admin(?:istration)?\s+Date/?Time|Scheduled\s+Start\s+Date/?Time|Given)\s*:?\s*"
                r"(\d{1,2}/\d{1,2}/\d{2,4})\s+(\d{4})",
                section, re.IGNORECASE
            )
            if admin_match:
                date = admin_match.group(1)
                time = admin_match.group(2)
                return f"{date} {time} ({med})"

            # Try alternate format
            admin_match2 = re.search(
                r"(\w{3}\s+\w{3}\s+\d{1,2},\s+\d{4})\s+(\d{4})",
                section
            )
            if admin_match2:
                return f"{admin_match2.group(1)} {admin_match2.group(2)} ({med})"

    return _NOT_DOCUMENTED


def _extract_consults(ev: Dict) -> str:
    """Extract consults from CONSULT_NOTE blocks and DISCHARGE consultations section."""
    consults = []
    seen = set()

    # From DISCHARGE "Consultations" section (cleanest source — lists all consults)
    discharge = _first_snippet(ev, "DISCHARGE")
    if discharge:
        text = discharge.get("text", "")
        consult_match = re.search(
            r"(?:Consultation|Consult)s?\s*:\s*(.+?)(?:\n\d+\.|\s+\d+\.\s|\n\n|\Z)",
            text, re.IGNORECASE | re.DOTALL
        )
        if consult_match:
            raw = consult_match.group(1).strip()
            # Truncate at signatures, HPI markers, or long text (consult lists are short)
            raw = re.split(r"(?:HPI|History of Present|Reason for|Chief Complaint)", raw, flags=re.IGNORECASE)[0].strip()
            raw = raw[:200]  # Consult list should never be this long
            # Split on comma or semicolon
            for part in re.split(r"[,;\n]", raw):
                name = part.strip()
                if name and name.lower() not in ("none", "n/a", "") and len(name) > 1:
                    # Skip if name is clearly not a specialty (too long, or contains HPI-like text)
                    if len(name) > 60 or any(skip in name.lower() for skip in [
                        "yo ", "year old", "presents", "pmh of", "with a pmh",
                    ]):
                        continue
                    key = name.lower()[:20]
                    if key not in seen:
                        seen.add(key)
                        consults.append(name)

    # From CONSULT_NOTE blocks (has dates and details)
    for s in _snippets_by_type(ev, "CONSULT_NOTE"):
        text = s.get("text", "")
        ts = s.get("timestamp") or ""
        date = _to_mmddyyyy(ts[:10]) if ts and re.match(r"\d{4}-\d{2}-\d{2}", ts) else ""
        # Parse "Inpatient consult to <SPECIALTY> [order#]" format
        specialty_match = re.search(r"consult\s+to\s+(.+?)\s*\[", text, re.IGNORECASE)
        if specialty_match:
            name = specialty_match.group(1).strip()
        else:
            # Try "Consultation Note <Provider Name>" — skip these
            consult_note_match = re.search(
                r"(?:Consult(?:ation)?\s+Note)\s+.+?(?:\n|$)", text[:200], re.IGNORECASE
            )
            if consult_note_match:
                continue  # Just a note header with provider name, not useful as specialty
            name = text.split("\n")[0].strip()[:60] if text else ""
        if name:
            # Truncate name at common noise markers
            name = re.split(r"(?:^|\s+)(?:Reason for|Pt Name|Patient:|MRN|HPI:|Narrative)", name, flags=re.IGNORECASE)[0].strip()
            if not name or len(name) < 2:
                continue
            # Skip if the entire name looks like clinical text (starts with HPI, contains age references)
            name_lower = name.lower()
            if any(skip in name_lower for skip in [
                "hpi:", "yo ", "year old", "presents", "pmh of",
                "chief complaint", "reason for",
            ]):
                continue
            key = name.lower()[:20]
            if key not in seen:
                seen.add(key)
                consults.append(f"{name} ({date})" if date else name)

    if not consults:
        return _NOT_DOCUMENTED

    # Normalize specialty names for deduplication, preferring fuller names
    _SPECIALTY_ALIASES = {
        "ortho": "orthopedic surgery",
        "orthopedics": "orthopedic surgery",
        "neuro": "neurosurgery",
        "neurosurg": "neurosurgery",
        "cards": "cardiology",
        "pulm": "pulmonology",
        "gi": "gastroenterology",
        "ent": "otolaryngology",
        "ir": "interventional radiology",
        "ct surg": "cardiothoracic surgery",
        "vasc surg": "vascular surgery",
    }

    def _normalize_specialty(name: str) -> str:
        key = name.lower().strip().rstrip(".")
        # Strip date suffix like " (12/17/2025)"
        key = re.sub(r"\s*\(\d{1,2}/\d{1,2}/\d{2,4}\)\s*$", "", key)
        return _SPECIALTY_ALIASES.get(key, key)

    seen_normalized: Dict[str, int] = {}  # normalized -> index in unique list
    unique = []
    for c in consults:
        norm = _normalize_specialty(c)
        if norm not in seen_normalized:
            seen_normalized[norm] = len(unique)
            unique.append(c)
        else:
            # Prefer longer/fuller name (replace abbreviation with full name)
            existing_idx = seen_normalized[norm]
            existing_name = re.sub(r"\s*\([\d/]+\)\s*$", "", unique[existing_idx])
            new_name = re.sub(r"\s*\([\d/]+\)\s*$", "", c)
            if len(new_name) > len(existing_name):
                unique[existing_idx] = c

    return "; ".join(unique)


def _extract_admission_imaging(ev: Dict) -> str:
    """Extract imaging completed on admission day."""
    arrival = ev.get("arrival_time", "")
    if not arrival:
        return _NOT_DOCUMENTED

    arrival_date = arrival[:10]  # YYYY-MM-DD
    studies = []
    seen = set()

    for s in _snippets_by_type(ev, "RADIOLOGY"):
        ts = s.get("timestamp", "")
        if ts[:10] == arrival_date:
            text = s.get("text", "")
            study_match = re.match(r"(?:Radiographs:\s+)?(.+?)(?:\s+Result Date|\s+INDICATION|\s+HISTORY)", text)
            if study_match:
                name = _clean_study_name(study_match.group(1))
                key = name.lower()[:40]
                if key not in seen:
                    seen.add(key)
                    studies.append(name)

    if not studies:
        return _NOT_DOCUMENTED

    return "; ".join(studies)


def _extract_followup(ev: Dict) -> str:
    """Extract follow-up appointments from DISCHARGE."""
    discharge = _first_snippet(ev, "DISCHARGE")
    if not discharge:
        return _NOT_DOCUMENTED

    text = discharge.get("text", "")
    # Look for follow-up section
    fu_match = re.search(
        r"(?:Follow[- ]?up|Return|Appointments?)\s*:?\s*(.+?)(?:\n\n|\Z)",
        text, re.IGNORECASE | re.DOTALL
    )
    if fu_match:
        return fu_match.group(1).strip()[:300]

    return _NOT_DOCUMENTED


def _calc_hospital_los(ev: Dict) -> str:
    """Calculate hospital LOS from arrival_time and discharge date."""
    arrival = ev.get("arrival_time", "")
    discharge = _first_snippet(ev, "DISCHARGE")

    if not arrival:
        return _NOT_DOCUMENTED

    discharge_date = None
    if discharge:
        text = discharge.get("text", "")
        # Allow non-digit characters between "Date:" and the actual date
        # (handles special chars like [EOT] that appear in some Epic exports)
        dm = re.search(r"Discharge\s+Date\s*:?[^0-9]*(\d{1,2}/\d{1,2}/\d{2,4})", text, re.IGNORECASE)
        if dm:
            date_str = dm.group(1)
            # Handle 2-digit year (e.g., "12/20/25" -> "12/20/2025")
            parts = date_str.split("/")
            if len(parts) == 3 and len(parts[2]) == 2:
                year = int(parts[2])
                parts[2] = str(2000 + year if year < 50 else 1900 + year)
                date_str = "/".join(parts)
            try:
                discharge_date = datetime.strptime(date_str, "%m/%d/%Y")
            except ValueError:
                pass

    if not discharge_date:
        if ev.get("is_live"):
            return "In hospital (ongoing)"
        return _NOT_DOCUMENTED

    try:
        arrival_date = datetime.strptime(arrival[:10], "%Y-%m-%d")
        los = (discharge_date - arrival_date).days
        return f"{los} days"
    except ValueError:
        return _NOT_DOCUMENTED


def _extract_mortality(ev: Dict) -> str:
    """Check for mortality indicators."""
    # Strong indicators — these specific phrases almost always mean actual patient death
    strong_keywords = [
        "patient expired", "pt expired", "pronounced dead", "time of death",
        "declared dead", "pronounced deceased", "comfort measures only",
        "withdrawal of care", "withdraw care", "comfort care only",
    ]
    # Weaker indicators that need more context checking
    weak_keywords = ["expired", "deceased", "death"]
    # Family history / non-patient context markers
    fhx_markers = [
        "neg hx", "family history", "family hx", "fhx", "social history",
        "before 55", "before 65", "sudden death before",
        "hx •", "risk of death", "risk for death", "mortality risk",
        "cause of death", "death risk", "brain death protocol",
    ]

    for s in ev.get("all_evidence_snippets", []):
        text_raw = s.get("text") or ""
        text = text_raw.lower()
        # Check strong keywords first (no extra context needed)
        for keyword in strong_keywords:
            if keyword in text:
                return "YES"
        # Check weaker keywords with stricter context
        for keyword in weak_keywords:
            if keyword not in text:
                continue
            idx = text.find(keyword)
            context = text[max(0, idx - 100):idx + len(keyword) + 100]
            # Skip if in family history / risk assessment context
            if any(fhx in context for fhx in fhx_markers):
                continue
            # Skip if clearly about a relative
            if any(rel in context for rel in ["mother", "father", "brother", "sister",
                                               "family member", "spouse"]):
                continue
            return "YES"

    return "NO"


# ---------------------------------------------------------------------------
# Daily notes field extractors
# ---------------------------------------------------------------------------

def _extract_daily_field(snippets: List[Dict], field: str) -> str:
    """
    Extract a specific clinical field from a day's evidence snippets.

    Returns extracted text or NOT DOCUMENTED.
    """
    if field == "hemodynamic_status":
        return _daily_hemodynamic(snippets)
    elif field == "respiratory_status":
        return _daily_respiratory(snippets)
    elif field == "neuro_status":
        return _daily_neuro(snippets)
    elif field == "procedures":
        return _daily_procedures(snippets)
    elif field == "imaging":
        return _daily_imaging(snippets)
    elif field == "labs":
        return _daily_labs(snippets)
    elif field == "consults":
        return _daily_consults(snippets)
    elif field == "complications":
        return _daily_complications(snippets)
    elif field == "plan":
        return _daily_plan(snippets)
    return _NOT_DOCUMENTED


def _daily_hemodynamic(snippets: List[Dict]) -> str:
    """Extract hemodynamic status from day's snippets.

    Priority: ESA Trauma Progress Note PE section > other physician notes > TRAUMA_HP.
    """
    # Priority 1: ESA Trauma Progress Note — structured vitals in PE section
    for s in snippets:
        if s.get("source_type") == "PHYSICIAN_NOTE":
            text = s.get("text", "")
            if _is_trauma_progress_note(text):
                sections = _parse_progress_note_sections(text)
                pe = sections.get("pe", "")
                if pe:
                    parts = []
                    bp = re.search(r"(?:BP|[Bb]lood\s+[Pp]ressure)\s*[^0-9]{0,10}(\d{2,3}/\d{2,3})", pe)
                    hr = re.search(r"(?:HR|[Pp]ulse)\s*[:=]?\s*(\d{2,3})", pe)
                    if bp:
                        parts.append(f"BP {bp.group(1)}")
                    if hr:
                        parts.append(f"HR {hr.group(1)}")
                    if parts:
                        return ", ".join(parts)

    # Priority 2: Other physician/nursing/ED notes with vital patterns
    for s in snippets:
        src = s.get("source_type", "")
        if src in ("PHYSICIAN_NOTE", "NURSING_NOTE", "ED_NOTE"):
            text = s.get("text", "")
            if src == "PHYSICIAN_NOTE" and (_is_radiology_note(text) or _is_pharmacy_note(text) or _is_nonclinical_note(text)):
                continue
            if src == "PHYSICIAN_NOTE" and _is_trauma_progress_note(text):
                continue  # Already checked above
            for pattern in [
                r"(?:BP|[Bb]lood\s+[Pp]ressure)\s*[^0-9]{0,10}(\d{2,3}/\d{2,3})",
                r"(?:HR|[Hh]eart\s+[Rr]ate|[Pp]ulse)\s*[:=]?\s*\d{2,3}",
                r"[Hh]emodynamic(?:ally)?\s+(?:stable|unstable|labile)",
                r"(?:vasopressor|norepinephrine|phenylephrine|dopamine|levophed)\s",
            ]:
                m = re.search(pattern, text, re.IGNORECASE)
                if m:
                    return _snap_context(text, m.start(), m.end(), before=30, after=60)

    # Check TRAUMA_HP secondary survey for vitals (admission day)
    for s in snippets:
        if s.get("source_type") == "TRAUMA_HP":
            hp_text = s.get("text", "")
            sections = _parse_hp_sections(hp_text)
            ss = sections.get("secondary survey", "")
            if ss:
                bp = re.search(r"(?:BP|[Bb]lood\s+[Pp]ressure)\s*[^0-9]{0,10}(\d{2,3}/\d{2,3})", ss)
                hr = re.search(r"(?:HR|[Pp]ulse)\s*[:=]?\s*(\d{2,3})", ss)
                parts = []
                if bp:
                    parts.append(f"BP {bp.group(1)}")
                if hr:
                    parts.append(f"HR {hr.group(1)}")
                if parts:
                    return ", ".join(parts)
            # Check Primary Survey for HD status
            ps = sections.get("primary survey", "")
            if ps:
                hd = re.search(r"(?:Circulation|HD)\s*[:=]?\s*(.+?)(?:\n|$)", ps)
                if hd:
                    return hd.group(1).strip()[:200]

    # Check DISCHARGE for vitals on discharge day
    for s in snippets:
        if s.get("source_type") == "DISCHARGE":
            text = s.get("text", "")
            # Look for "Vital signs on discharge:" section
            vs = re.search(r"[Vv]ital\s+signs?\s+on\s+discharge\s*:\s*(.+?)(?:\n\n|\n\d+\.)", text, re.DOTALL)
            if vs:
                return vs.group(1).strip()[:200]

    return _NOT_DOCUMENTED


def _daily_respiratory(snippets: List[Dict]) -> str:
    """Extract respiratory status from day's snippets.

    Priority: ESA Trauma Progress Note PE section > other notes > TRAUMA_HP.
    """
    # Priority 1: ESA Trauma Progress Note — structured Lungs, SpO2 in PE section
    for s in snippets:
        if s.get("source_type") == "PHYSICIAN_NOTE":
            text = s.get("text", "")
            if _is_trauma_progress_note(text):
                sections = _parse_progress_note_sections(text)
                pe = sections.get("pe", "")
                if pe:
                    parts = []
                    lungs = re.search(r"Lungs?\s*:\s*(.+?)(?:\s+Cardiac|\s+Chest\s+wall|\n|$)", pe)
                    if lungs:
                        parts.append(lungs.group(1).strip())
                    spo2 = re.search(r"SpO2\s*(\d+%?)", pe)
                    if spo2:
                        parts.append(f"SpO2 {spo2.group(1)}")
                    rr = re.search(r"resp\.?\s*rate\s*(\d+)", pe, re.IGNORECASE)
                    if rr:
                        parts.append(f"RR {rr.group(1)}")
                    if parts:
                        return "; ".join(parts)

    # Priority 2: Other notes — respiratory patterns
    for s in snippets:
        src = s.get("source_type", "")
        if src in ("PHYSICIAN_NOTE", "NURSING_NOTE", "ED_NOTE"):
            text = s.get("text", "")
            if src == "PHYSICIAN_NOTE" and (_is_radiology_note(text) or _is_pharmacy_note(text) or _is_nonclinical_note(text)):
                continue
            if src == "PHYSICIAN_NOTE" and _is_trauma_progress_note(text):
                continue  # Already checked
            for pattern in [
                r"(?:respiratory|resp\.?)\s+(?:status|rate|therapy|treatment)",
                r"(?:on\s+)?(?:room\s+air|\bRA\b|nasal\s+cannula|\bNC\b|high\s+flow|BiPAP|CPAP|ventilat|intubat|extubat)",
                r"(?:SpO2|O2\s+sat|oxygen\s+sat)\s*[:=]?\s*\d+",
                r"(?:lung\s+sounds|breath\s+sounds|clear\s+to\s+auscultation|\bCTA\b\s+bilat)",
                r"incentive\s+spirometr",
                r"\bIS\b\s+(?:use|x\d|performed|teaching|instructed|encouraged)",
                r"secretion\s+clearance",
                r"\bSC\b\s+(?:perform|instruct|teach)",
                r"(?:cough\s+(?:and\s+deep\s+breath|assist)|deep\s+breath(?:ing)?|pulmonary\s+toilet|chest\s+(?:PT|physio))",
                r"(?:nebulizer|albuterol|bronchodilator|suction(?:ing)?)",
                r"(?:trach(?:eostomy)?|wean(?:ing)?|FiO2|PEEP|tidal\s+volume)",
            ]:
                m = re.search(pattern, text, re.IGNORECASE)
                if m:
                    return _snap_context(text, m.start(), m.end(), before=20, after=60)

    # Check TRAUMA_HP secondary survey for respiratory findings (admission day)
    for s in snippets:
        if s.get("source_type") == "TRAUMA_HP":
            hp_text = s.get("text", "")
            sections = _parse_hp_sections(hp_text)
            ss = sections.get("secondary survey", "")
            if ss:
                # Look for Lungs section within secondary survey
                lungs = re.search(r"Lungs?\s*:\s*(.+?)(?:\n|$)", ss)
                if lungs:
                    return lungs.group(1).strip()[:200]
                # Look for SpO2
                spo2 = re.search(r"SpO2\s*(\d+%?)", ss)
                if spo2:
                    return f"SpO2 {spo2.group(1)}"

    return _NOT_DOCUMENTED


def _daily_neuro(snippets: List[Dict]) -> str:
    """Extract neurological status from day's snippets.

    Priority: ESA Trauma Progress Note PE section > other notes > TRAUMA_HP.
    """
    # Priority 1: ESA Trauma Progress Note — structured GCS and Neurologic in PE
    for s in snippets:
        if s.get("source_type") == "PHYSICIAN_NOTE":
            text = s.get("text", "")
            if _is_trauma_progress_note(text):
                sections = _parse_progress_note_sections(text)
                pe = sections.get("pe", "")
                if pe:
                    parts = []
                    gcs = re.search(r"GCS\s*:\s*(\d+)", pe)
                    if gcs:
                        parts.append(f"GCS {gcs.group(1)}")
                    neuro = re.search(r"Neurologic\s*:\s*(.+?)(?:\s+Radiographs|\s+Labs|\n\n|$)", pe, re.DOTALL)
                    if neuro:
                        neuro_text = neuro.group(1).strip()
                        # Take first 150 chars of neuro findings
                        parts.append(neuro_text[:150])
                    if parts:
                        return "; ".join(parts)

    # Priority 2: Other notes
    for s in snippets:
        src = s.get("source_type", "")
        if src in ("PHYSICIAN_NOTE", "NURSING_NOTE", "ED_NOTE"):
            text = s.get("text", "")
            if src == "PHYSICIAN_NOTE" and (_is_radiology_note(text) or _is_pharmacy_note(text) or _is_nonclinical_note(text)):
                continue
            if src == "PHYSICIAN_NOTE" and _is_trauma_progress_note(text):
                continue
            for pattern in [
                r"GCS\s*[:=]?\s*\d+",
                r"(?:alert|oriented|confused|obtund|comatose|lethargic|somnolent)",
                r"(?:neuro(?:logic(?:al)?)?)\s+(?:exam|status|intact|deficit)",
                r"(?:pupils|PERRLA|pupil(?:s)?\s+(?:equal|reactive|fixed))",
                r"(?:sensation|motor)\s+(?:intact|diminished|absent)",
            ]:
                m = re.search(pattern, text, re.IGNORECASE)
                if m:
                    return _snap_context(text, m.start(), m.end(), before=20, after=60)

    # Check TRAUMA_HP for GCS and neuro findings (admission day only)
    for s in snippets:
        if s.get("source_type") == "TRAUMA_HP":
            hp_text = s.get("text", "")
            sections = _parse_hp_sections(hp_text)
            # Check Secondary Survey for GCS and Neurologic sections
            ss = sections.get("secondary survey", "")
            if ss:
                gcs = re.search(r"GCS\s*:\s*(.+?)(?:\n|$)", ss)
                if gcs:
                    neuro_parts = [f"GCS {gcs.group(1).strip()}"]
                    neuro = re.search(r"Neurologic\s*:\s*(.+?)(?:\n|$)", ss)
                    if neuro:
                        neuro_parts.append(neuro.group(1).strip())
                    return "; ".join(neuro_parts)[:200]
            # Check Primary Survey for disability
            ps = sections.get("primary survey", "")
            if ps:
                disability = re.search(r"Disability\s*:\s*(.+?)(?:\n|$)", ps)
                if disability:
                    return disability.group(1).strip()[:200]

    return _NOT_DOCUMENTED


def _daily_procedures(snippets: List[Dict]) -> str:
    """Extract procedures from day's snippets."""
    procs = []
    for s in snippets:
        if s.get("source_type") in ("PROCEDURE", "OPERATIVE_NOTE"):
            text = s.get("text", "")
            first_line = text.split("\n")[0].strip()
            if first_line and len(first_line) > 5:
                procs.append(first_line[:150])
    return "; ".join(procs) if procs else "None"


def _daily_imaging(snippets: List[Dict]) -> str:
    """Extract imaging studies done on this specific day.

    Only includes studies whose Result Date matches the day of the snippets.
    Does NOT carry forward imaging from previous days.
    """
    studies = []
    seen = set()

    # Determine current day from snippet timestamps
    current_day = None
    for s in snippets:
        ts = s.get("timestamp") or ""
        if len(ts) >= 10 and re.match(r"\d{4}-\d{2}-\d{2}", ts):
            current_day = ts[:10]
            break

    for s in snippets:
        if s.get("source_type") == "RADIOLOGY":
            text = s.get("text", "")

            # Extract Result Date from the study text
            result_date_match = re.search(r"Result Date:\s*(\d{1,2}/\d{1,2}/\d{2,4})", text)
            if result_date_match and current_day:
                rd = result_date_match.group(1)
                # Normalize to YYYY-MM-DD for comparison
                rd_parts = rd.split("/")
                if len(rd_parts) == 3:
                    m, d, y = rd_parts
                    if len(y) == 2:
                        y = "20" + y
                    rd_normalized = f"{y}-{int(m):02d}-{int(d):02d}"
                    if rd_normalized != current_day:
                        continue  # Study done on a different day — skip

            study_match = re.match(r"(?:Radiographs:\s+)?(.+?)(?:\s+Result Date|\s+INDICATION|\s+HISTORY)", text)
            if study_match:
                name = _clean_study_name(study_match.group(1))
                key = name.lower()[:40]
                if key not in seen:
                    seen.add(key)
                    studies.append(name)
    return "; ".join(studies) if studies else "None"


def _daily_labs(snippets: List[Dict]) -> str:
    """Extract significant labs from day's snippets.

    Shows WBC, HGB, PLT always. Other labs only if flagged abnormal.

    Handles two Epic lab formats:
    1. Admission detail: bullet lines with Component, Date, Value, Ref Range, Status
    2. Recent Labs trend table: rows like 'WBC\\t7.1\\t -- \\t10.0' with * marking abnormals
    """
    # Labs that are ALWAYS shown (core trauma labs)
    _ALWAYS_SHOW = {
        "wbc", "hgb", "plt",
        "white blood cell count", "hemoglobin", "platelet count",
    }

    def _is_always_show(name: str) -> bool:
        return name.lower().strip() in _ALWAYS_SHOW
    # Known lab abbreviations for validating trend table row names
    _LAB_NAMES = {
        "wbc", "hgb", "hct", "plt", "na", "k", "cl", "co2", "bun",
        "creatinine", "inr", "ast", "alt", "alkphos", "labbili", "bili",
        "glucose", "calcium", "magnesium", "phosphorus", "albumin",
        "troponin", "troponin t", "lactate", "lipase", "ammonia",
        "fibrinogen", "pt", "ptt", "aptt", "rdwcv", "rdwsd",
        "est gfr", "mcv", "mch", "mchc", "mpv", "esr", "crp",
        "red blood cell count", "white blood cell count", "hemoglobin",
        "hematocrit", "platelet count", "mean corpuscular volume",
    }

    for s in snippets:
        if s.get("source_type") == "LAB":
            text = s.get("text", "")
            results = []

            # Detect Format 1: has "Component\tDate\tValue" header
            is_detail_format = "Component\t" in text or "Component " in text[:200]

            if not is_detail_format and ("Recent Labs" in text or "\t" in text):
                # Format 2: "Recent Labs" trend table
                for line in text.split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    parts = re.split(r"\t+", line)
                    if len(parts) < 2:
                        continue
                    lab_name = parts[0].strip()
                    # Skip empty, header, date, and time rows
                    if not lab_name or re.match(r"^\s*$", lab_name):
                        continue
                    if lab_name.lower() in ("labs", "recent labs", "component", "date", " "):
                        continue
                    if re.match(r"^\d{3,4}$", lab_name):  # Time like "1439", "0405"
                        continue
                    if "/" in lab_name:  # Date like "12/17/25"
                        continue
                    if "Imaging" in lab_name:  # "Imaging Studies:" section break
                        break
                    # Find the most recent non-empty value (rightmost)
                    latest_val = ""
                    for val in reversed(parts[1:]):
                        val = val.strip()
                        if val and val != "--" and val != " -- ":
                            latest_val = val
                            break
                    if latest_val:
                        is_abnormal = "*" in latest_val
                        flag = " *" if is_abnormal else ""
                        clean_val = latest_val.replace("*", "").strip()
                        if clean_val and not re.match(r"^\d{1,2}/\d{1,2}/\d{2,4}$", clean_val):
                            # Only show: always-show labs (WBC/HGB/PLT) + abnormal others
                            if _is_always_show(lab_name) or is_abnormal:
                                results.append(f"{lab_name} {clean_val}{flag}")
                if results:
                    return "; ".join(results[:10])

            else:
                # Format 1: Admission detail with bullet lines
                for line in text.split("\n"):
                    line = line.strip()
                    if not line.startswith("\u2022") and not line.startswith("•"):
                        continue
                    parts = re.split(r"\t+", line)
                    if len(parts) >= 4:
                        comp = parts[1].strip() if len(parts) > 1 else ""
                        val = parts[3].strip() if len(parts) > 3 else ""
                        ref = parts[4].strip() if len(parts) > 4 else ""
                        if comp and val:
                            flag = ""
                            is_abnormal = False
                            if ref and " - " in ref:
                                try:
                                    ref_parts = ref.split(" - ")
                                    lo = float(ref_parts[0].strip())
                                    hi_str = ref_parts[1].strip().split()[0]
                                    hi = float(hi_str)
                                    fval = float(val)
                                    if fval < lo:
                                        flag = " (L)"
                                        is_abnormal = True
                                    elif fval > hi:
                                        flag = " (H)"
                                        is_abnormal = True
                                except (ValueError, IndexError):
                                    pass
                            # Only show: always-show labs (WBC/HGB/PLT) + abnormal others
                            if _is_always_show(comp) or is_abnormal:
                                results.append(f"{comp} {val}{flag}")
                if results:
                    return "; ".join(results[:10])

            return _NOT_DOCUMENTED

    # Also check PHYSICIAN_NOTE (ESA notes embed "Recent Labs" tables)
    for s in snippets:
        if s.get("source_type") == "PHYSICIAN_NOTE":
            text = s.get("text", "")
            labs_idx = text.find("Labs:")
            if labs_idx == -1:
                labs_idx = text.find("Recent Labs")
            if labs_idx == -1:
                continue
            labs_section = text[labs_idx:labs_idx + 800]
            results = []
            for line in labs_section.split("\n"):
                line = line.strip()
                if not line:
                    continue
                parts = re.split(r"\t+", line)
                if len(parts) < 2:
                    continue
                lab_name = parts[0].strip()
                if not lab_name or "/" in lab_name:
                    continue
                if lab_name.lower() in ("labs", "recent labs", "component", " "):
                    continue
                if re.match(r"^\d{3,4}$", lab_name):
                    continue
                if "Prophylaxis" in lab_name or "Impression" in lab_name:
                    break  # Past the labs section
                latest_val = ""
                for val in reversed(parts[1:]):
                    val = val.strip()
                    if val and val != "--" and val != " -- ":
                        latest_val = val
                        break
                if latest_val:
                    is_abnormal = "*" in latest_val
                    flag = " *" if is_abnormal else ""
                    clean_val = latest_val.replace("*", "").strip()
                    if clean_val and not re.match(r"^\d{1,2}/\d{1,2}/\d{2,4}$", clean_val):
                        if _is_always_show(lab_name) or is_abnormal:
                            results.append(f"{lab_name} {clean_val}{flag}")
            if results:
                return "; ".join(results[:10])

    return _NOT_DOCUMENTED


def _daily_consults(snippets: List[Dict]) -> str:
    """Extract consults from day's snippets. Clean up Epic order formatting."""
    consults = []
    seen = set()
    for s in snippets:
        if s.get("source_type") == "CONSULT_NOTE":
            text = s.get("text", "")
            # Parse "Inpatient consult to <SPECIALTY> [order#]" format
            specialty_match = re.search(
                r"consult\s+to\s+(.+?)\s*\[",
                text, re.IGNORECASE
            )
            if specialty_match:
                name = specialty_match.group(1).strip()
            else:
                # Fallback: use first meaningful line
                first_line = text.split("\n")[0].strip()
                name = first_line[:80] if first_line else ""
            if name:
                key = name.lower()[:30]
                if key not in seen:
                    seen.add(key)
                    consults.append(name)
    return "; ".join(consults) if consults else "None"


def _daily_complications(snippets: List[Dict]) -> str:
    """Extract complications from day's snippets.

    Excludes TRAUMA_HP and LAB source types to avoid matching PMH/historical conditions.
    Also skips radiology-formatted physician notes and pharmacy notes.
    Uses regex with word boundaries for short abbreviations.
    """
    complications = []
    # Regex patterns with word boundaries for short keywords
    complication_patterns = [
        r"\bpneumonia\b",
        r"\bsepsis\b",
        # DVT only when NOT followed by "prophylaxis/ppx/prevention" (prophylaxis is treatment, not complication)
        r"\bdvt\b(?!\s+(?:prophylaxis|ppx|prevention|precaution))",
        r"\bpulmonary\s+embolism\b",
        r"\bwound\s+infection\b",
        r"\bssi\b",
        r"\bdelirium\b",
        r"\bards\b",
        r"\baki\b",
        r"\brenal\s+failure\b",
        r"\bcardiac\s+arrest\b",
        # Exclude traumatic types: subarachnoid, subdural, epidural, intracranial
        r"(?<!subarachnoid\s)(?<!subdural\s)(?<!epidural\s)(?<!intracranial\s)\bhemorrhage\b",
        r"\btransfusion\b",
        # "Unplanned" only when followed by relevant context (return, readmission actual event),
        # NOT "Unplanned Readmission Risk Score" which is just an assessment tool
        r"\bunplanned\b\s+(?:return|intubation|reoperation)(?!\s+risk)",
        r"\breturn\s+to\s+or\b",
    ]
    # Only check clinical notes (not TRAUMA_HP which contains PMH, not LAB/RAD)
    for s in snippets:
        src = s.get("source_type", "")
        if src in ("TRAUMA_HP", "LAB", "RADIOLOGY", "MAR"):
            continue  # Skip sources that contain historical/reference data
        text_raw = s.get("text") or ""
        # Skip radiology/pharmacy notes misclassified as physician notes
        if src == "PHYSICIAN_NOTE" and (_is_radiology_note(text_raw) or _is_pharmacy_note(text_raw)):
            continue
        text = text_raw.lower()
        for pat in complication_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                idx = m.start()
                context_before = text[max(0, idx - 120):idx]
                # Skip if preceded by PMH/historical references
                if any(hist in context_before for hist in [
                    "history of", "pmh", "past medical", "h/o",
                    "prior to admission", "pre-existing",
                    "prior", "previous", "old", "baseline", "chronic",
                ]):
                    continue
                # Skip if negated: "no hemorrhage", "without hemorrhage", "negative for"
                near_before = text[max(0, idx - 30):idx].strip()
                if any(neg in near_before for neg in [
                    "no ", "no new ", "without ", "negative for ",
                    "absent", "denies ", "ruled out",
                ]):
                    continue
                # Skip if within a bullet-list PMH format (• or · before keyword)
                if "\u2022" in context_before[-30:] or "\xb7" in context_before[-30:]:
                    continue
                # Skip if keyword is followed by dated entry from years before encounter
                context_after = text[idx:idx + 80]
                old_date = re.search(r"\d{1,2}/\d{1,2}/(?:19|20[01])", context_after)
                if old_date:
                    continue  # Date from years before encounter — historical
                context = text_raw[max(0, idx - 20):idx + 60].strip()
                complications.append(_clean_epic_artifacts(context)[:100])
                break

    return "; ".join(complications) if complications else "None"


def _daily_plan(snippets: List[Dict]) -> str:
    """Extract plan from day's notes.

    Priority: ESA Trauma Progress Note > other physician notes > TRAUMA_HP > DISCHARGE.
    ESA is captain of the ship — their plan is always primary.
    """
    # Priority 1: ESA Trauma Progress Notes (trauma service)
    for s in snippets:
        if s.get("source_type") == "PHYSICIAN_NOTE":
            text = s.get("text", "")
            if _is_trauma_progress_note(text):
                sections = _parse_progress_note_sections(text)
                plan = sections.get("plan", "")
                if plan:
                    return _clean_plan_text(plan)

    # Priority 2: Other physician notes (skip radiology/pharmacy/therapy/non-clinical notes)
    for s in snippets:
        if s.get("source_type") == "PHYSICIAN_NOTE":
            text = s.get("text", "")
            if _is_radiology_note(text) or _is_pharmacy_note(text) or _is_nonclinical_note(text):
                continue
            if _is_trauma_progress_note(text):
                continue  # Already checked above
            plan_match = re.search(r"(?:\bPlan\b|Assessment\s*/?\s*Plan)\s*:?\s*(.+?)(?:$|\n\n)",
                                    text, re.IGNORECASE | re.DOTALL)
            if plan_match:
                return _clean_plan_text(plan_match.group(1).strip(), max_len=200)

    # Priority 3: TRAUMA_HP plan section (admission day)
    for s in snippets:
        if s.get("source_type") == "TRAUMA_HP":
            hp_text = s.get("text", "")
            sections = _parse_hp_sections(hp_text)
            plan = sections.get("plan", "")
            if plan:
                plan = re.sub(r"^Plan\s*:\s*", "", plan, flags=re.IGNORECASE).strip()
                if plan:
                    return _clean_plan_text(plan)

    # Priority 4: DISCHARGE hospital course
    for s in snippets:
        if s.get("source_type") == "DISCHARGE":
            text = s.get("text", "")
            course = re.search(r"Hospital\s+Course\s*:\s*(.+?)(?:\n\d+\.|\s+\d+\.\s|\n\n|\Z)",
                              text, re.IGNORECASE | re.DOTALL)
            if course:
                return course.group(1).strip()[:200]

    return _NOT_DOCUMENTED


# ---------------------------------------------------------------------------
# Public API — Contract Section Extractors
# ---------------------------------------------------------------------------

def extract_trauma_summary(ev: Dict) -> Dict[str, str]:
    """
    Extract === TRAUMA SUMMARY === fields per contract.

    Returns OrderedDict with fields in contract order.
    """
    hp = _first_snippet(ev, "TRAUMA_HP")
    hp_text = hp.get("text", "") if hp else ""

    # NTDS complications
    ntds_yes = [r for r in ev.get("ntds_results", []) if r.get("outcome") == "YES"]
    if ntds_yes:
        ntds_complications = "; ".join(
            f"#{r['event_id']:02d} {r['canonical_name']}" for r in ntds_yes
        )
        ntds_present = "YES"
    else:
        ntds_complications = _NONE_DOCUMENTED
        ntds_present = "NO"

    return OrderedDict([
        ("Mechanism", _extract_mechanism(hp_text)),
        ("Arrival date/time", _format_arrival(ev.get("arrival_time", ""))),
        ("Initial vitals", _extract_initial_vitals(hp_text)),
        ("GCS", _extract_gcs(hp_text)),
        ("Primary injuries (explicit diagnoses only)", _extract_primary_injuries(ev)),
        ("Imaging results (positive and negative)", _extract_imaging_results(ev)),
        ("Interventions (ED and OR)", _extract_interventions(ev)),
        ("Disposition", _extract_disposition(ev)),
        ("NTDS-relevant complications", ntds_complications),
        ("NTDS complications present?", ntds_present),
    ])


def extract_daily_notes(ev: Dict) -> List[Dict[str, Any]]:
    """
    Extract === TRAUMA DAILY NOTES === per contract.

    Returns list of dicts, one per calendar day, in chronological order.
    Each dict has 'date' (MM/DD/YYYY) and the contract fields.
    """
    # Collect all dates
    dates = set()
    for s in ev.get("all_evidence_snippets", []):
        ts = s.get("timestamp") or ""
        if len(ts) >= 10 and re.match(r"\d{4}-\d{2}-\d{2}", ts):
            dates.add(ts[:10])

    if not dates:
        return []

    daily_notes = []
    for date_str in sorted(dates):
        snippets = _snippets_for_date(ev, date_str)
        if not snippets:
            continue

        fields = [
            ("Hemodynamic status", _extract_daily_field(snippets, "hemodynamic_status")),
            ("Respiratory status", _extract_daily_field(snippets, "respiratory_status")),
            ("Neuro status", _extract_daily_field(snippets, "neuro_status")),
            ("Procedures performed", _extract_daily_field(snippets, "procedures")),
            ("Imaging", _extract_daily_field(snippets, "imaging")),
            ("Labs (significant only)", _extract_daily_field(snippets, "labs")),
            ("Consults", _extract_daily_field(snippets, "consults")),
            ("Complications", _extract_daily_field(snippets, "complications")),
            ("Plan", _extract_daily_field(snippets, "plan")),
        ]

        daily_notes.append({
            "date": _to_mmddyyyy(date_str),
            "fields": OrderedDict(fields),
        })

    return daily_notes


def extract_green_card(ev: Dict) -> Dict[str, str]:
    """
    Extract === GREEN CARD === fields per contract.

    Returns OrderedDict with fields in contract order.
    """
    hp = _first_snippet(ev, "TRAUMA_HP")
    hp_text = hp.get("text", "") if hp else ""

    # NTDS complications
    ntds_yes = [r for r in ev.get("ntds_results", []) if r.get("outcome") == "YES"]
    complications = (
        "; ".join(f"#{r['event_id']:02d} {r['canonical_name']}" for r in ntds_yes)
        if ntds_yes else _NONE_DOCUMENTED
    )

    # Operative procedures
    procedures = []
    for s in ev.get("all_evidence_snippets", []):
        if s.get("source_type") in ("PROCEDURE", "OPERATIVE_NOTE"):
            text = s.get("text", "")
            first_line = text.split("\n")[0].strip()
            if first_line and len(first_line) > 5:
                procedures.append(first_line[:150])

    return OrderedDict([
        ("Mechanism", _extract_mechanism(hp_text)),
        ("Injury list", _extract_primary_injuries(ev)),
        ("Past medical history", _extract_pmh(hp_text)),
        ("Operative procedures", "; ".join(procedures) if procedures else "None"),
        ("ICU LOS", _NOT_DOCUMENTED),  # Requires ADT data not in current evidence
        ("Hospital LOS", _calc_hospital_los(ev)),
        ("Complications (NTDS specific)", complications),
        ("Mortality (YES/NO)", _extract_mortality(ev)),
        ("Discharge disposition", _extract_disposition(ev)),
        ("On blood thinners at home?", _extract_home_blood_thinners(hp_text)),
        ("Imaging completed at Deaconess Midtown on admission", _extract_admission_imaging(ev)),
        ("Consults", _extract_consults(ev)),
        ("First DVT prophylaxis dose date and time", _extract_dvt_prophylaxis(ev)),
        ("Follow-up appointments", _extract_followup(ev)),
    ])
