#!/usr/bin/env python3
"""
Consultant Plan Items v1 — Structured Consultant Plan/Recommendation Extraction.

Deterministic extraction of explicit consultant plan/recommendation items
from consultant note text within the patient timeline.

This feature builds on ``consultant_events_v1`` (which identifies *which*
consultant services were involved) by extracting *what* those consultants
actually recommended.

Strategy:
  1. Uses ``consultant_events_v1`` from the assembled features dict to
     identify which services are consultant services and their timestamps.
  2. Finds the corresponding CONSULT_NOTE and consultant PHYSICIAN_NOTE
     items in the timeline (``days_data``).
  3. Extracts plan/recommendation sections from each matching note's text.
  4. Parses individual plan items from those sections.

Matching timeline items to consultant services:
  - ``note_index_events_v1`` entries have (date_raw, time_raw, service).
  - Timeline items have (dt, type, payload.text).
  - Match by: timeline ``type`` in {CONSULT_NOTE, PHYSICIAN_NOTE} AND
    ``dt`` aligns with note_index (date_raw + time_raw) within same minute.
  - Service attribution comes from the note_index entry that shares the
    timestamp, not from text guessing.

Plan section detection — explicit section headers only:
  - ``Assessment and Plan`` / ``Assessment & Plan`` / ``Assessment/Plan``
  - ``A/P:``
  - ``Plan:``
  - ``Assessment:`` (when followed by ``Plan:`` subsection)
  - ``Recommendations`` (for PT/OT/wound notes)

Plan section termination:
  - Next major section header (Subjective, Objective, Physical Exam, etc.)
  - Underscore/dash separator lines (3+ chars)
  - Electronic signature / attestation markers
  - End of text

Filtered out (not plan items):
  - Physician signatures / credential lines
  - Date/time-only lines
  - Attestation / MDM blocks
  - MyChart disclaimers
  - Co-signature lines
  - Pager/office contact info
  - Courtesy/thanks lines
  - Revision/routing history
  - ``untitled image`` markers
  - ``Reason for Admission`` / ``Reason for continued hospitalization``

Deduplication:
  - Identical (service, item_text_normalized) pairs across co-signed /
    duplicate note copies are deduplicated.

Output key: ``consultant_plan_items_v1``

Output schema::

    {
      "items": [
        {
          "service": "Otolaryngology",
          "ts": "2026-01-01T10:20:00",
          "author_name": "Chacko, Chris E",
          "item_text": "Nonoperative management of nasal fracture",
          "item_type": "recommendation",
          "evidence": [
            {
              "role": "consultant_plan_item",
              "snippet": "...",
              "raw_line_id": "<sha256>"
            }
          ]
        }, ...
      ],
      "item_count": <int>,
      "services_with_plan_items": ["Otolaryngology", ...],
      "source_rule_id": "consultant_plan_from_note_text"
                       | "no_consultant_events"
                       | "no_plan_sections_found",
      "warnings": [...],
      "notes": [...]
    }

Fail-closed behaviour:
  - No ``consultant_events_v1`` or consultant_present != "yes"
    → item_count=0, source_rule_id="no_consultant_events"
  - Consultant events present but no plan sections found in any note
    → item_count=0, source_rule_id="no_plan_sections_found"
  - Plan sections found and parsed
    → source_rule_id="consultant_plan_from_note_text"

Design:
- Deterministic, fail-closed.
- No LLM, no ML, no clinical inference.
- raw_line_id preserved from note_index_events entries.
- Explicit-only: only extracts from recognized plan/recommendation
  section headers.  Does not infer recommendations from narrative text.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional, Set, Tuple

_DNA = "DATA NOT AVAILABLE"

# ── Plan/Recommendation section header patterns ───────────────────
# Order matters: more specific patterns first.
_PLAN_HEADER_RE = re.compile(
    r"^\s*"
    r"(?:"
    r"Assessment\s+and\s+Plan"
    r"|Assessment\s*&\s*Plan"
    r"|Assessment/Plan"
    r"|A/P"
    r"|Plan"
    r"|Recommendations?"
    r")"
    r"\s*[:.]?\s*",
    re.IGNORECASE,
)

# ── Section headers that TERMINATE a plan section ─────────────────
_NEXT_SECTION_RE = re.compile(
    r"^\s*(?:"
    r"Subjective"
    r"|Objective"
    r"|Physical\s+Exam"
    r"|Review\s+of\s+Systems"
    r"|ROS"
    r"|History\s+of\s+Present\s+Illness"
    r"|HPI"
    r"|Chief\s+Complaint"
    r"|Past\s+Medical\s+History"
    r"|PMH"
    r"|Medications"
    r"|Current\s+Medications"
    r"|Allergies"
    r"|Social\s+History"
    r"|Family\s+History"
    r"|Vital\s+Signs"
    r"|Vitals"
    r"|Labs"
    r"|Laboratory"
    r"|Imaging"
    r"|Radiology"
    r"|Follow\s+up\s+as\s+an\s+outpatient"
    r"|Disposition"
    r"|Revision\s+History"
    r"|Routing\s+History"
    r"|Cosigned\s+by"
    r"|Physician\s+Attestation"
    r"|Reason\s+for\s+Admission"
    r"|Reason\s+for\s+continued\s+hospitalization"
    r")\s*[:.]?\s*",
    re.IGNORECASE,
)

# ── Separator lines (underscore or dash runs) ─────────────────────
_SEPARATOR_RE = re.compile(r"^[\s]*[_\-=]{3,}\s*$")

# ── Electronic signature / attestation markers ────────────────────
_SIGNATURE_RE = re.compile(
    r"(?:"
    r"Electronically\s+signed"
    r"|This\s+has\s+been\s+electronically\s+signed"
    r"|Signed\s+by"
    r"|Authenticated\s+by"
    r"|Addendum\b"
    r")",
    re.IGNORECASE,
)

# ── Lines to FILTER OUT from plan items ───────────────────────────

# Attestation block
_ATTESTATION_RE = re.compile(
    r"I have (seen|reviewed|personally).*patient",
    re.IGNORECASE,
)

# Credential/signature line: "Name, Credentials" pattern
_CRED_LINE_RE = re.compile(
    r"^[A-Z][a-z]+\s+(?:[A-Z]\.?\s+)?[A-Z][a-z]+,?\s+"
    r"(?:MD|DO|NP|PA-C|PA|AGACNP|OTR|PT|DPT|RN|BSN|CWOCN|"
    r"OTR/L|C/NDT|MS|FACS|FACP|OTA|COTA|PTA|LCSW|LISW)\b",
)

# Date-only lines: "1/1/2026", "01/02/2026"
_DATE_ONLY_RE = re.compile(r"^\s*\d{1,2}/\d{1,2}/\d{2,4}\s*$")

# Time-only lines: "6:00 PM", "10:15 AM"
_TIME_ONLY_RE = re.compile(r"^\s*\d{1,2}:\d{2}\s*(?:AM|PM)\s*$", re.IGNORECASE)

# Seen-at pattern: "Seen at 0540"
_SEEN_AT_RE = re.compile(r"^\s*Seen\s+at\s+\d{4}\s*$", re.IGNORECASE)

# MyChart / disclaimer
_DISCLAIMER_RE = re.compile(r"MyChart|Disclaimer", re.IGNORECASE)

# MDM grid line
_MDM_RE = re.compile(
    r"(?:complexity|Overall\s+Highest\s+Level|Amount.*Data|"
    r"Diagnoses\s+and\s+Treatment\s+Options)",
    re.IGNORECASE,
)

# "untitled image"
_UNTITLED_IMAGE_RE = re.compile(r"^\s*untitled\s+image\s*$", re.IGNORECASE)

# Courtesy / thanks lines
_COURTESY_RE = re.compile(
    r"^\s*(?:Thank\s+you\s+for|Please\s+feel\s+free|"
    r"Please\s+contact\b|We\s+will\s+follow\s+along)\b",
    re.IGNORECASE,
)

# Pager / office phone
_PHONE_RE = re.compile(
    r"(?:Pager|Office|Fax)\s*:\s*\d{3}[\s\-]",
    re.IGNORECASE,
)

# Order reference
_ORDER_RE = re.compile(r"^\s*Order:\s*\d+", re.IGNORECASE)

# Service/title standalone lines (e.g., "Deaconess Clinic", "Available on Haiku")
_SERVICE_TITLE_RE = re.compile(
    r"^\s*(?:Deaconess\s+(?:Clinic|Care\s+Group|Health\s+System)\b.*"
    r"|Available\s+on\s+Haiku"
    r"|Ear\s+Nose\s+and\s+Throat\s+Surgery"
    r"|Wound\s+Ostomy\s+and\s+Continence\b.*"
    r"|Hospitalist"
    r"|NEUROSURGERY\s+FRACTURE\s+INSTRUCTIONS\s*:?"
    r")\s*$",
    re.IGNORECASE,
)

# "Code, full" / "Full code status" standalone — not a plan item
_CODE_STATUS_RE = re.compile(
    r"^\s*(?:Code,?\s+full|Full\s+code\s+status)\b",
    re.IGNORECASE,
)

# ── v2 noise filters ──────────────────────────────────────────────

# PT/OT functional-assessment form fields: "Label: Level" where
# Level is a standard functional assessment value.
_FUNC_ASSESS_RE = re.compile(
    r":\s*(?:Independent|Supervision|Partial/moderate|Substantial/Maximal"
    r"|Not applicable|Needed\s+some\s+help|Dependent"
    r"|Setup\s+or\s+clean-?up)"
    r"(?:\s+(?:assistance|Assistance))?",
    re.IGNORECASE,
)

# PT/OT assessment score lines: "Raw Score: 23", "T-Scale Score: 50.88"
_ASSESS_SCORE_RE = re.compile(
    r"(?:Raw\s+Score|T-Scale\s+Score|T\s+Scale\s+Score)\s*:\s*[\d.]+",
    re.IGNORECASE,
)

# PT/OT form headings and field labels — section labels with no clinical action.
_THERAPY_FORM_FIELD_RE = re.compile(
    r"^\s*(?:"
    r"Outcome\s+Measures?"
    r"|Prior\s+Level\s+of\s+Function"
    r"|ADL\s+Assist(?:ance)?"
    r"|Functional\s+Transfers?"
    r"|Home\s+Equipment\s+Available"
    r"|Prior\s+Device\s+Use"
    r"|Home\s+Layout\s*:"
    r"|Permanent\s+Residence\s*:"
    r"|Who\s+do\s+you\s+live\s+with\b"
    r"|(?:PT|OT)\s+Frequency\s*:"
    r"|Distance\s+Ambulated\b"
    r"|Assistive\s+Device\s*:"
    r"|Pattern\s*:\s*Within\s+functional"
    r"|Progress\s*:\s*Progressing\s+toward"
    r"|Home\s+Layout\b"
    r"|Treatment(?:/| )Interventions\s*:"
    r"|Treatment\s+Interventions\s*:"
    r")",
    re.IGNORECASE,
)

# PT/OT bare section-heading words (must match ENTIRE line)
_THERAPY_HEADING_RE = re.compile(
    r"^\s*(?:"
    r"Transfers"
    r"|Mobility"
    r"|Balance"
    r"|Stairs"
    r"|Assessment"
    r"|Skin\s+Integrity"
    r"|Patient\s+[Ii]nstructions"
    r")\.?\s*$",
    re.IGNORECASE,
)

# Orthopedic / hospitalist problem-list template lines
_PROBLEM_LIST_RE = re.compile(
    r"^\s*(?:"
    r"Problems\s*:\s*\(highlighted\s+problems"
    r"|Active\s+Hospital\s+Problems"
    r"|Resolved\s+Hospital\s+Problems"
    r"|No\s+resolved\s+problems\s+to\s+display"
    r"|Diagnosis\s+Date\s+Noted"
    r")",
    re.IGNORECASE,
)

# Lines ending with "(HCC)" — diagnosis heading with billing marker
_HCC_DIAG_RE = re.compile(r"\(HCC\)\s*$")

# ICD-style diagnosis lines ending with "initial encounter" / "subsequent encounter"
_ICD_ENCOUNTER_RE = re.compile(
    r",\s*(?:initial|subsequent)\s+encounter\b",
    re.IGNORECASE,
)

# PT/OT activity assessment labels (specific transfer/mobility form fields)
# followed by a colon — these are form data, not clinical recommendations.
_THERAPY_ACTIVITY_LABEL_RE = re.compile(
    r"^\s*(?:"
    r"Sitting\s+to\s+lying"
    r"|Lying\s+to\s+sitting"
    r"|Sit\s+to\s+Stand"
    r"|Chair/bed\s+to\s+chair"
    r"|Eating\s+Assist"
    r"|Oral\s+Hygiene"
    r"|Shower/Bathe"
    r"|[UL]E\s+Dressing"
    r"|Toilet\s+Hygiene"
    r"|Putting\s+on/Taking\s+off"
    r"|Ambulation\s+Assist"
    r"|Sitting\s+-\s+(?:Static|Dynamic)"
    r"|Standing\s+-\s+(?:Static|Dynamic)"
    r")\s*:",
    re.IGNORECASE,
)

# Patient acknowledgment / understanding boilerplate
_PATIENT_ACK_RE = re.compile(
    r"(?:"
    r"(?:patient|guardian).*(?:understanding|agrees\s+with\s+the\s+plan)"
    r"|(?:questions?\s+(?:were\s+)?answered)"
    r"|(?:patient\s+is\s+given\s+an\s+After\s+Visit\s+Summary)"
    r"|(?:indicates?\s+understanding\s+of\s+these\s+issues)"
    r")",
    re.IGNORECASE,
)

# Bare "Signed:" line
_SIGNED_BARE_RE = re.compile(r"^\s*Signed\s*:\s*$", re.IGNORECASE)

# Generic instruction boilerplate (After Visit, medication instructions)
_GENERIC_INSTRUCTION_RE = re.compile(
    r"^\s*(?:"
    r"If\s+medications\s+are\s+provided\b"
    r"|Take\s+all\s+medications\s+as\s+(?:directed|prescribed)"
    r")",
    re.IGNORECASE,
)

# Standalone lab order names (all-caps short tokens)
_LAB_ORDER_RE = re.compile(
    r"^\s*(?:CBC\s+W\s+AUTO\s+DIFF|CBC|BMP|CMP|BNP|CHEM|ABG|VBG|PT/INR|PT\s+INR"
    r"|COMPREHENSIVE\s+METABOLIC|BASIC\s+METABOLIC|LIPID\s+PANEL"
    r"|COMPLETE\s+BLOOD\s+COUNT)\s*$",
    re.IGNORECASE,
)

# ── Item type classification ──────────────────────────────────────

_ITEM_TYPE_PATTERNS: List[Tuple[str, re.Pattern]] = [
    # Order matters: more specific patterns first to avoid broad matches.
    ("imaging", re.compile(
        r"\b(?:CT\s|MRI\s|X-?ray|XR\s|repeat\s+(?:CT|MRI|X-?ray|imaging)|"
        r"CTA|ultrasound|ECHO|TTE|TEE|angiogram|fluoroscopy)\b",
        re.IGNORECASE,
    )),
    ("procedure", re.compile(
        r"\b(?:surgery|operative|OR\s|ORIF|I&D|debridement|reduction|"
        r"intubat|extubat|tracheostomy|chest\s+tube|drain|line\s+placement|"
        r"bronchoscopy|endoscopy|biopsy|repair)\b",
        re.IGNORECASE,
    )),
    ("follow-up", re.compile(
        r"\b(?:follow[\s-]?up|f/u|return\s+to\s+clinic|"
        r"outpatient\s+follow|recheck|repeat\s+in|"
        r"schedule\s+(?:a\s+)?follow|see\s+in\s+\d)\b",
        re.IGNORECASE,
    )),
    ("activity", re.compile(
        r"\b(?:weight[\s-]?bearing|NWB|WBAT|TDWB|PWB|FWB|"
        r"mobiliz|ambul|PT\s+eval|OT\s+eval|"
        r"activity\s+as\s+tolerated|bed\s+rest|OOB|"
        r"ROM\s+exercises|incentive\s+spirometry|"
        r"bronchopulmonary\s+hygiene|splint|brace|sling|"
        r"collar|immobiliz)\b",
        re.IGNORECASE,
    )),
    ("discharge", re.compile(
        r"\b(?:discharg|d/c\s+(?:from|when|to\s+home|planning)|"
        r"disposition|home\s+with|SNF|rehab\s+facility|"
        r"safe\s+for\s+discharge|ok\s+to\s+d/c)\b",
        re.IGNORECASE,
    )),
    ("medication", re.compile(
        r"\b(?:start|continue|resume|discontinue|hold|titrate|"
        r"wean|increase|decrease|taper|prescribe|administer|"
        r"Nimodipine|Heparin|Rocephin|Lovenox|enoxaparin|heparin|"
        r"hydralazine|Wellbutrin|acetaminophen|ibuprofen|IV\s+antibiotics|"
        r"vancomycin|Ancef|cefazolin|morphine|dilaudid|gabapentin|"
        r"famotidine|pantoprazole|melatonin)\b",
        re.IGNORECASE,
    )),
]


# ── Helpers ────────────────────────────────────────────────────────

def _sha256(text: str) -> str:
    """Return SHA-256 hex digest of text (for raw_line_id)."""
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _normalize_item_text(text: str) -> str:
    """Normalize plan item text: strip leading bullets/numbers, trim."""
    # Remove leading bullet chars: -, •, *, numbered lists (1., 1), etc.
    s = text.strip()
    s = re.sub(r"^[\-\*•]\s*", "", s)
    s = re.sub(r"^\d+[.)]\s*", "", s)
    s = re.sub(r"^\d+\.\s+", "", s)
    # Collapse internal whitespace
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _classify_item_type(text: str) -> str:
    """Classify a plan item into a type tag, or 'recommendation'."""
    for type_tag, pattern in _ITEM_TYPE_PATTERNS:
        if pattern.search(text):
            return type_tag
    return "recommendation"


def _is_noise_line(line: str) -> bool:
    """Return True if line should be filtered out of plan items."""
    stripped = line.strip()
    if not stripped:
        return True
    if _ATTESTATION_RE.search(stripped):
        return True
    if _CRED_LINE_RE.match(stripped):
        return True
    if _DATE_ONLY_RE.match(stripped):
        return True
    if _TIME_ONLY_RE.match(stripped):
        return True
    if _SEEN_AT_RE.match(stripped):
        return True
    if _DISCLAIMER_RE.search(stripped):
        return True
    if _MDM_RE.search(stripped):
        return True
    if _UNTITLED_IMAGE_RE.match(stripped):
        return True
    if _COURTESY_RE.match(stripped):
        return True
    if _PHONE_RE.search(stripped):
        return True
    if _ORDER_RE.match(stripped):
        return True
    if _SERVICE_TITLE_RE.match(stripped):
        return True
    if _SIGNATURE_RE.search(stripped):
        return True
    if _CODE_STATUS_RE.match(stripped):
        return True
    if _LAB_ORDER_RE.match(stripped):
        return True
    # ── v2 noise filters ──
    if _FUNC_ASSESS_RE.search(stripped):
        return True
    if _ASSESS_SCORE_RE.search(stripped):
        return True
    if _THERAPY_FORM_FIELD_RE.match(stripped):
        return True
    if _THERAPY_HEADING_RE.match(stripped):
        return True
    if _PROBLEM_LIST_RE.match(stripped):
        return True
    if _HCC_DIAG_RE.search(stripped):
        return True
    if _ICD_ENCOUNTER_RE.search(stripped):
        return True
    if _THERAPY_ACTIVITY_LABEL_RE.match(stripped):
        return True
    if _PATIENT_ACK_RE.search(stripped):
        return True
    if _SIGNED_BARE_RE.match(stripped):
        return True
    if _GENERIC_INSTRUCTION_RE.match(stripped):
        return True
    # Very short lines (≤2 chars) are noise
    if len(stripped) <= 2:
        return True
    return False


def _extract_plan_sections(text: str) -> List[Tuple[int, str, str]]:
    """
    Extract plan/recommendation sections from note text.

    Returns list of (line_offset, header_text, section_body) tuples.
    line_offset is the 0-based line index of the header in the text.
    """
    lines = text.split("\n")
    sections: List[Tuple[int, str, str]] = []

    i = 0
    while i < len(lines):
        line = lines[i]
        m = _PLAN_HEADER_RE.match(line)
        if m:
            header_text = line.strip()
            # Capture inline content on the header line itself
            inline_content = line[m.end():].strip()
            body_lines: List[str] = []
            if inline_content:
                body_lines.append(inline_content)

            # Collect subsequent lines until termination signal
            j = i + 1
            while j < len(lines):
                next_line = lines[j]

                # Check termination conditions
                if _SEPARATOR_RE.match(next_line):
                    break
                if _SIGNATURE_RE.search(next_line):
                    break
                # Another plan header → stop (new section)
                if _PLAN_HEADER_RE.match(next_line) and j > i + 1:
                    break
                if _NEXT_SECTION_RE.match(next_line):
                    break
                body_lines.append(next_line)
                j += 1

            section_body = "\n".join(body_lines)
            if section_body.strip():
                sections.append((i, header_text, section_body))
            i = j
        else:
            i += 1

    return sections


def _parse_plan_items(
    section_body: str,
    service: str,
    ts: str,
    author_name: str,
    base_raw_line_id: str,
    header_text: str,
) -> List[Dict[str, Any]]:
    """
    Parse individual plan items from a plan section body.

    Returns a list of item dicts.
    """
    items: List[Dict[str, Any]] = []
    lines = section_body.split("\n")

    # Accumulate multi-line items (continuation lines that are indented
    # under a bullet or belong to the same paragraph)
    current_item_lines: List[str] = []
    current_item_start_idx: int = 0

    def _flush_item():
        nonlocal current_item_lines
        if not current_item_lines:
            return
        raw_text = "\n".join(current_item_lines)
        combined = " ".join(l.strip() for l in current_item_lines)
        normalized = _normalize_item_text(combined)
        if normalized and len(normalized) >= 5 and not _is_noise_line(normalized):
            # Generate raw_line_id from the item text
            item_raw_line_id = _sha256(
                f"{base_raw_line_id}::{normalized}"
            )
            item_type = _classify_item_type(normalized)
            snippet = f"[{service}] {header_text}: {normalized}"[:150]
            items.append({
                "service": service,
                "ts": ts,
                "author_name": author_name if author_name else None,
                "item_text": normalized,
                "item_type": item_type,
                "evidence": [{
                    "role": "consultant_plan_item",
                    "snippet": snippet,
                    "raw_line_id": item_raw_line_id,
                }],
            })
        current_item_lines = []

    for idx, line in enumerate(lines):
        stripped = line.strip()

        # Skip empty lines (but flush current item)
        if not stripped:
            _flush_item()
            continue

        # Skip noise lines
        if _is_noise_line(line):
            _flush_item()
            continue

        # Check if this starts a new bullet/item
        is_bullet = bool(re.match(r"^\s*[\-\*•]\s", line))
        is_numbered = bool(re.match(r"^\s*\d+[.)]\s", line))
        is_continuation = (
            current_item_lines
            and not is_bullet
            and not is_numbered
            # Continuation: must be indented (4+ spaces) relative to start
            and len(line) - len(line.lstrip()) >= 4
        )

        if is_bullet or is_numbered:
            _flush_item()
            current_item_lines = [stripped]
            current_item_start_idx = idx
        elif is_continuation:
            current_item_lines.append(stripped)
        else:
            # New plain-text item
            _flush_item()
            current_item_lines = [stripped]
            current_item_start_idx = idx

    _flush_item()
    return items


def _match_timeline_items_to_services(
    days_data: Dict[str, Any],
    consultant_services: List[Dict[str, Any]],
    note_index_entries: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Match timeline items to consultant services by timestamp alignment.

    For each consultant service in consultant_events_v1, find timeline
    items (CONSULT_NOTE or PHYSICIAN_NOTE) whose dt matches any of the
    service's note_index entry timestamps.

    Returns list of matched items with: service, ts, author_name,
    text, raw_line_id (from note_index entry).
    """
    # Build a lookup of note_index entries by (date_raw, time_raw)
    # Each entry has: date_raw, time_raw, author_name, service, raw_line_id
    ni_by_ts: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for entry in note_index_entries:
        date_raw = (entry.get("date_raw") or "").strip()
        time_raw = (entry.get("time_raw") or "").strip()
        if date_raw and time_raw:
            ni_by_ts[(date_raw, time_raw)] = entry

    # Build set of (service_name) → list of (date_raw, time_raw) from
    # consultant_events_v1 evidence
    svc_timestamps: Dict[str, List[Tuple[str, str]]] = {}
    for svc_info in consultant_services:
        svc_name = svc_info.get("service", "")
        # Extract timestamps from evidence snippets or derive from
        # first_ts / last_ts
        svc_evidence = svc_info.get("evidence", [])
        for ev in svc_evidence:
            snippet = ev.get("snippet", "")
            # Evidence snippet format: "Consults 01/01 1020 Author [Service]"
            # or "Progress Notes 01/01 1514 Author [Service]"
            parts = snippet.split()
            if len(parts) >= 3:
                # Try to extract date_raw and time_raw from snippet
                # Format varies but date is always MM/DD and time is HHMM
                date_raw = None
                time_raw = None
                for p_idx, p in enumerate(parts):
                    if re.match(r"\d{2}/\d{2}", p) and p_idx + 1 < len(parts):
                        if re.match(r"\d{4}$", parts[p_idx + 1]):
                            date_raw = p
                            time_raw = parts[p_idx + 1]
                            break
                if date_raw and time_raw:
                    if svc_name not in svc_timestamps:
                        svc_timestamps[svc_name] = []
                    svc_timestamps[svc_name].append((date_raw, time_raw))

    # Collect all timeline items across all days
    days = days_data.get("days", {})
    timeline_by_dt: Dict[str, Dict[str, Any]] = {}
    for date_key, day_data in days.items():
        items = day_data.get("items", [])
        for item in items:
            item_type = item.get("type", "")
            if item_type in ("CONSULT_NOTE", "PHYSICIAN_NOTE"):
                dt = item.get("dt", "")
                if dt:
                    timeline_by_dt[dt] = item

    # Match: for each service → for each timestamp → find timeline item
    matched: List[Dict[str, Any]] = []
    matched_keys: Set[Tuple[str, str]] = set()  # (service, dt) dedup

    for svc_name, ts_list in svc_timestamps.items():
        for date_raw, time_raw in ts_list:
            # Convert date_raw (MM/DD) + time_raw (HHMM) to possible dt
            # Try to find timeline item whose dt matches
            ni_entry = ni_by_ts.get((date_raw, time_raw), {})
            ni_service = (ni_entry.get("service") or "").strip()
            ni_author = (ni_entry.get("author_name") or "").strip()
            ni_raw_line_id = ni_entry.get("raw_line_id", "")

            # Find matching timeline item by dt
            for dt, item in timeline_by_dt.items():
                # Parse dt: "2026-01-01T10:20:00" → check if it matches
                # date_raw="01/01" time_raw="1020"
                if _dt_matches(dt, date_raw, time_raw):
                    key = (svc_name, dt)
                    if key not in matched_keys:
                        matched_keys.add(key)
                        text = (item.get("payload") or {}).get("text", "")
                        matched.append({
                            "service": svc_name,
                            "ts": dt,
                            "author_name": ni_author,
                            "text": text,
                            "raw_line_id": ni_raw_line_id,
                            "source_id": item.get("source_id", ""),
                        })

    return matched


def _dt_matches(dt_iso: str, date_raw: str, time_raw: str) -> bool:
    """
    Check if ISO datetime matches MM/DD + HHMM from note_index.

    dt_iso: "2026-01-01T10:20:00"
    date_raw: "01/01"
    time_raw: "1020"
    """
    # Parse ISO dt
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})", dt_iso)
    if not m:
        return False
    _, month, day, hour, minute = m.groups()

    # Parse date_raw: "01/01" → month, day
    dm = re.match(r"(\d{2})/(\d{2})", date_raw)
    if not dm:
        return False
    dr_month, dr_day = dm.groups()

    # Parse time_raw: "1020" → hour, minute
    if len(time_raw) != 4 or not time_raw.isdigit():
        return False
    tr_hour = time_raw[:2]
    tr_minute = time_raw[2:]

    return (month == dr_month and day == dr_day
            and hour == tr_hour and minute == tr_minute)


def _match_timeline_items_direct(
    days_data: Dict[str, Any],
    consultant_services: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Direct matching: find CONSULT_NOTE timeline items that correspond
    to consultant services discovered via the timeline-scan fallback.

    Unlike ``_match_timeline_items_to_services`` (which uses note_index
    timestamps for matching), this function matches CONSULT_NOTE items
    by dt from the evidence entries in consultant_services.

    Returns list of matched items with: service, ts, author_name,
    text, raw_line_id.
    """
    # Collect all (dt, service) pairs from consultant events evidence
    svc_dts: Dict[str, Set[str]] = {}
    for svc_info in consultant_services:
        svc_name = svc_info.get("service", "")
        for ev in svc_info.get("evidence", []):
            snippet = ev.get("snippet", "")
            # Evidence snippet format from fallback:
            # "Consults MM/DD HHMM  [Service]"
            # Derive dt from date_raw/time_raw in the snippet
            pass
        # Also use first_ts/last_ts but these are "MM/DD HHMM" —
        # not enough for direct matching.
    # Better approach: scan timeline directly for CONSULT_NOTE items
    # and match against known services
    days = days_data.get("days", {})
    consult_items: Dict[str, Dict[str, Any]] = {}
    for date_key in sorted(days.keys()):
        day_data = days[date_key]
        for item in day_data.get("items", []):
            if item.get("type") != "CONSULT_NOTE":
                continue
            dt = item.get("dt", "")
            if dt and dt not in consult_items:
                consult_items[dt] = item

    # Build set of consultant service names (lowered for matching)
    known_services: Dict[str, str] = {}
    for svc_info in consultant_services:
        svc_name = svc_info.get("service", "")
        known_services[svc_name.lower()] = svc_name

    # Match each CONSULT_NOTE against known services
    import re as _re
    _CONSULT_TO_RE_LOCAL = _re.compile(
        r"[Cc]onsult\s+[Tt]o\s+([A-Z][A-Za-z/& ]+?)(?:\s*[\[(\n]|\s+ordered\s+by)",
    )
    _CONSULT_HEADING_RE_LOCAL = _re.compile(
        r"^([A-Z][A-Za-z ]+?)\s+Consult(?:\s+Note)?\s*$",
        _re.MULTILINE,
    )

    matched: List[Dict[str, Any]] = []
    matched_keys: Set[Tuple[str, str]] = set()

    for dt, item in sorted(consult_items.items()):
        text = (item.get("payload") or {}).get("text", "")
        if not text:
            continue

        # Extract service from text
        service = None
        for m in _CONSULT_TO_RE_LOCAL.finditer(text[:2000]):
            candidate = m.group(1).strip()
            if candidate.lower() in known_services:
                service = known_services[candidate.lower()]
                break
            # Try partial match (service name starts with candidate)
            for ks_lower, ks_name in known_services.items():
                if ks_lower.startswith(candidate.lower()):
                    service = ks_name
                    break
            if service:
                break

        if not service:
            for m in _CONSULT_HEADING_RE_LOCAL.finditer(text[:2000]):
                candidate = m.group(1).strip()
                if candidate.lower() in known_services:
                    service = known_services[candidate.lower()]
                    break

        if not service:
            continue

        key = (service, dt)
        if key in matched_keys:
            continue
        matched_keys.add(key)

        raw_line_id = hashlib.sha256(
            f"{item.get('source_id', '')}|{dt}|CONSULT_NOTE|{service}".encode(
                "utf-8", errors="replace"
            )
        ).hexdigest()[:16]

        matched.append({
            "service": service,
            "ts": dt,
            "author_name": "",
            "text": text,
            "raw_line_id": raw_line_id,
            "source_id": item.get("source_id", ""),
        })

    return matched


# ── Public API ──────────────────────────────────────────────────────

def extract_consultant_plan_items(
    pat_features: Dict[str, Any],
    days_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Extract consultant plan/recommendation items from consultant note text.

    Parameters
    ----------
    pat_features : dict
        Assembled features dict. Must contain ``consultant_events_v1``
        and ``note_index_events_v1``.
    days_data : dict
        Full patient_days_v1.json dict — for timeline item text access.

    Returns
    -------
    dict with keys: items, item_count, services_with_plan_items,
                    source_rule_id, warnings, notes
    """
    warnings: List[str] = []
    notes: List[str] = []

    # ── Check consultant_events_v1 ──
    ce = pat_features.get("consultant_events_v1")
    if ce is None or ce.get("consultant_present") != "yes":
        reason = "no_consultant_events"
        if ce is not None:
            notes.append(
                f"consultant_present={ce.get('consultant_present', '?')}"
            )
        else:
            notes.append("consultant_events_v1 not available in features")
        return {
            "items": [],
            "item_count": 0,
            "services_with_plan_items": [],
            "source_rule_id": reason,
            "warnings": warnings,
            "notes": notes,
        }

    consultant_services = ce.get("consultant_services", [])
    if not consultant_services:
        return {
            "items": [],
            "item_count": 0,
            "services_with_plan_items": [],
            "source_rule_id": "no_consultant_events",
            "warnings": warnings,
            "notes": ["consultant_services list is empty"],
        }

    # ── Get note_index_events_v1 for timestamp-to-service mapping ──
    ni = pat_features.get("note_index_events_v1", {})
    ni_entries = ni.get("entries", [])
    if not isinstance(ni_entries, list):
        ni_entries = []

    ce_source_rule = ce.get("source_rule_id", "")

    # ── Match timeline items to consultant services ──
    if ce_source_rule == "consultant_events_from_timeline_items":
        # Fallback path: events came from direct timeline scan.
        # Match CONSULT_NOTE items directly by dt + service.
        matched_items = _match_timeline_items_direct(
            days_data, consultant_services,
        )
    else:
        # Primary path: events came from note_index.
        matched_items = _match_timeline_items_to_services(
            days_data, consultant_services, ni_entries,
        )

    if not matched_items:
        notes.append(
            f"consultant_events found {len(consultant_services)} services "
            f"but no timeline items matched"
        )
        return {
            "items": [],
            "item_count": 0,
            "services_with_plan_items": [],
            "source_rule_id": "no_plan_sections_found",
            "warnings": warnings,
            "notes": notes,
        }

    # ── Extract plan sections from each matched note ──
    all_items: List[Dict[str, Any]] = []
    notes_with_plan = 0

    for mi in matched_items:
        text = mi.get("text", "")
        if not text:
            continue

        sections = _extract_plan_sections(text)
        if not sections:
            continue

        notes_with_plan += 1
        for line_offset, header_text, section_body in sections:
            parsed = _parse_plan_items(
                section_body=section_body,
                service=mi["service"],
                ts=mi["ts"],
                author_name=mi.get("author_name", ""),
                base_raw_line_id=mi.get("raw_line_id", ""),
                header_text=header_text,
            )
            all_items.extend(parsed)

    # ── Deduplicate identical (service, item_text) pairs ──
    seen: Set[Tuple[str, str]] = set()
    deduped_items: List[Dict[str, Any]] = []
    for item in all_items:
        key = (item["service"], item["item_text"].lower())
        if key not in seen:
            seen.add(key)
            deduped_items.append(item)
        else:
            warnings.append(
                f"Duplicate plan item removed: [{item['service']}] "
                f"{item['item_text'][:60]}"
            )

    # ── Build services_with_plan_items ──
    services_with_items: List[str] = sorted(set(
        item["service"] for item in deduped_items
    ))

    # ── Determine source_rule_id ──
    if deduped_items:
        source_rule_id = "consultant_plan_from_note_text"
    else:
        source_rule_id = "no_plan_sections_found"
        notes.append(
            f"Scanned {notes_with_plan} notes with plan sections "
            f"but no valid plan items extracted"
        )

    notes.append(
        f"matched {len(matched_items)} timeline items, "
        f"{notes_with_plan} had plan sections, "
        f"{len(deduped_items)} items extracted "
        f"(from {len(all_items)} pre-dedup)"
    )

    return {
        "items": deduped_items,
        "item_count": len(deduped_items),
        "services_with_plan_items": services_with_items,
        "source_rule_id": source_rule_id,
        "warnings": warnings,
        "notes": notes,
    }
