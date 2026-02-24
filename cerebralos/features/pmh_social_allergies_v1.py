#!/usr/bin/env python3
"""
PMH / Social History / Allergies Extraction v1 for CerebralOS.

Deterministic extraction of structured patient context from
trauma-relevant note sections:

  - **PMH items**: problem list from "Past Medical History:" sections
  - **Allergies**: allergen + reaction from "Allergies:" sections
  - **Social history**: smoking status, alcohol use, drug use,
    marital status (when trivially explicit)

Scans TRAUMA_HP, PHYSICIAN_NOTE, ED_NOTE, CONSULT_NOTE, NURSING_NOTE
items. Extracts only explicit, structured table entries — no inference,
no NLP, no LLM.

Fail-closed behaviour:
  - Only values from recognized section structures are captured.
  - Unknown/Not on file values are captured as-is (downstream can filter).
  - Entries are deduplicated across repeated notes.
  - Every evidence item carries raw_line_id.

Output key: ``pmh_social_allergies_v1``
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional, Tuple

_DNA = "DATA NOT AVAILABLE"

# ── Source types to scan ────────────────────────────────────────────
_SOURCE_TYPES = frozenset({
    "TRAUMA_HP",
    "PHYSICIAN_NOTE",
    "ED_NOTE",
    "CONSULT_NOTE",
    "NURSING_NOTE",
})

# ── Section header patterns ────────────────────────────────────────

# PMH section start: "PMH: PAST MEDICAL HISTORY", "PAST MEDICAL HISTORY:",
# "Past Medical History:", "PMH:", etc. + "Past Medical History:" sub-header
RE_PMH_HEADER = re.compile(
    r"(?:PMH\s*:\s*(?:PAST\s+MEDICAL\s+HISTORY)?|"
    r"PAST\s+MEDICAL\s+HISTORY\s*:?\s*|"
    r"Past\s+Medical\s+History\s*:?\s*)",
    re.IGNORECASE,
)

# Allergies section start
RE_ALLERGIES_HEADER = re.compile(
    r"^\s*(?:ALLERGIES|Allergies)\s*:?\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# Social Hx section start
RE_SOCIAL_HEADER = re.compile(
    r"^\s*(?:Social\s+Hx|SOCIAL\s+HISTORY|Social\s+History)\s*:?\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# Generic section boundary (ends current section)
RE_SECTION_BOUNDARY = re.compile(
    r"^\s*(?:Meds\s*:|Medications|Current\s+(?:Outpatient|Medications)|Scheduled\s+meds|"
    r"No\s+current\s+(?:facility|outpatient)|"
    r"Allergies\s*:?\s*$|ALLERGIES|"
    r"Social\s+Hx|SOCIAL\s+HISTORY|Social\s+History|"
    r"Surgical\s+Hx|Past\s+Surgical|"
    r"ROS\s*:|Review\s+of\s+Systems|"
    r"Secondary\s+Survey|Primary\s+Survey|"
    r"Physical\s+Exam|"
    r"Assessment|Plan\s*:|Labs\s*:|"
    r"PMH\s*:|PAST\s+MEDICAL\s+HISTORY|Past\s+Medical\s+History|"
    r"HPI\s*:|History\s+of\s+Present|"
    r"Chief\s+Complaint|"
    r"Impression|"
    r"Disposition)",
    re.IGNORECASE | re.MULTILINE,
)

# Allergen/Reactions column header
RE_ALLERGEN_HEADER = re.compile(
    r"Allergen\s+Reactions",
    re.IGNORECASE,
)

# Bullet line
RE_BULLET = re.compile(r"^[•\-\*]\s+", re.MULTILINE)

# PMH "Diagnosis\tDate" header line
RE_PMH_TABLE_HEADER = re.compile(
    r"^\s*Diagnosis\s+Date\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# ── Social history field patterns ──────────────────────────────────
RE_SMOKING = re.compile(r"Smoking\s+status\s*:\s*(.+)", re.IGNORECASE)
RE_SMOKELESS = re.compile(r"Smokeless\s+tobacco\s*:\s*(.+)", re.IGNORECASE)
RE_VAPING = re.compile(r"Vaping\s+status\s*:\s*(.+)", re.IGNORECASE)
RE_ALCOHOL = re.compile(r"Alcohol\s+use\s*:\s*(.+)", re.IGNORECASE)
RE_DRUG_USE = re.compile(r"Drug\s+use\s*:\s*(.+)", re.IGNORECASE)
RE_DRUG_TYPES = re.compile(r"Types\s*:\s*(.+)", re.IGNORECASE)
RE_DRUG_COMMENT = re.compile(r"Comment\s*:\s*(.+)", re.IGNORECASE)
RE_MARITAL = re.compile(r"Marital\s+status\s*:\s*(.+)", re.IGNORECASE)


# ── Helpers ─────────────────────────────────────────────────────────

def _make_raw_line_id(
    source_type: str,
    source_id: Optional[str],
    line_text: str,
) -> str:
    payload = f"{source_type}|{source_id or ''}|{line_text.strip()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _snippet(text: str, max_len: int = 120) -> str:
    text = str(text).strip()
    if len(text) <= max_len:
        return text
    return text[:max_len] + "\u2026"


def _normalize_pmh_label(raw: str) -> str:
    """Normalize a PMH item label for deduplication.

    Strips parenthetical annotations like (HCC), trailing dates,
    whitespace, and lowercases.
    """
    text = raw.strip()
    # Remove (HCC) etc.
    text = re.sub(r"\s*\(HCC\)\s*", " ", text, flags=re.IGNORECASE)
    # Remove trailing date patterns
    text = re.sub(r"\s*\d{1,2}/\d{1,2}/\d{2,4}\s*$", "", text)
    text = text.strip().rstrip(",").strip()
    return text.lower()


# ── Section extraction ─────────────────────────────────────────────

def _extract_section_text(
    full_text: str,
    header_match_start: int,
    header_match_end: int,
) -> str:
    """Extract text from header end to next section boundary."""
    # Search for next section boundary after the header
    rest = full_text[header_match_end:]
    # Skip blank lines / sub-headers that are part of this section
    boundary = RE_SECTION_BOUNDARY.search(rest)
    if boundary:
        return rest[:boundary.start()]
    return rest


def _find_all_sections(
    text: str,
    header_re: re.Pattern,
) -> List[Tuple[int, int, str]]:
    """Find all occurrences of a section. Returns (start, end, section_text)."""
    results = []
    for m in header_re.finditer(text):
        section_text = _extract_section_text(text, m.start(), m.end())
        results.append((m.start(), m.end(), section_text))
    return results


# ── PMH extraction ─────────────────────────────────────────────────

def _extract_pmh_from_section(
    section_text: str,
    source_type: str,
    source_id: Optional[str],
    source_ts: Optional[str],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Extract PMH items from a Past Medical History section.

    Returns (pmh_items, evidence).
    Handles both tabbed single-line format and un-tabbed multi-line format.
    """
    items: List[Dict[str, Any]] = []
    evidence: List[Dict[str, Any]] = []

    lines = section_text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Skip header lines, blank lines, "Diagnosis Date" header
        if not stripped or RE_PMH_TABLE_HEADER.match(stripped):
            i += 1
            continue

        # Skip "Past Medical History:" sub-header
        if re.match(r"^\s*Past\s+Medical\s+History\s*:?\s*$", stripped, re.IGNORECASE):
            i += 1
            continue

        # Skip "Diagnosis" alone on a line (un-tabbed format header)
        if stripped.lower() in ("diagnosis", "date", "diagnosis date"):
            i += 1
            continue

        # Bullet line = PMH entry (Epic uses '•' — avoid '-' which
        # is common in clinical text like "--Start Peptamen...")
        if stripped.startswith("•"):
            # Extract the diagnosis text (remove bullet + tab)
            raw_text = re.sub(r"^•\s*", "", stripped)

            # In tabbed format, the diagnosis and date are tab-separated
            parts = raw_text.split("\t")
            diagnosis = parts[0].strip() if parts else raw_text.strip()

            # Check for date in second tab field
            date_str = None
            if len(parts) > 1 and parts[1].strip():
                date_str = parts[1].strip()

            # Look ahead for sub-comment (indented line without bullet)
            sub_comment = None
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                if next_line and not next_line.startswith("•") and not RE_SECTION_BOUNDARY.match(next_line):
                    # Skip if it looks like another header
                    if not re.match(r"^\s*(Diagnosis|Date|Past Medical)", next_line, re.IGNORECASE):
                        sub_comment = next_line
                        i += 1  # consume the sub-comment line

            # Skip trivial/empty labels (stray bullets, dashes, etc.)
            if diagnosis and not re.match(r"^[\-–—\s]+$", diagnosis):
                rid = _make_raw_line_id(source_type, source_id, stripped)
                entry: Dict[str, Any] = {
                    "label": diagnosis,
                    "raw_label": raw_text.strip(),
                    "raw_line_id": rid,
                    "source_type": source_type,
                    "ts": source_ts,
                }
                if date_str:
                    entry["date"] = date_str
                if sub_comment:
                    entry["sub_comment"] = sub_comment

                items.append(entry)
                evidence.append({
                    "role": "pmh_item",
                    "label": diagnosis,
                    "source_type": source_type,
                    "source_id": source_id,
                    "ts": source_ts,
                    "raw_line_id": rid,
                    "snippet": _snippet(stripped),
                })

        elif stripped and not stripped.startswith("•"):
            # Un-tabbed format: diagnosis name on its own line (no bullet)
            # Only capture if it looks like a diagnosis (not a header/date)
            # In un-tabbed format, pattern is: bullet -> diagnosis -> date
            # But we only capture bullet-prefixed entries to be fail-closed
            pass

        i += 1

    return items, evidence


# ── Allergies extraction ───────────────────────────────────────────

def _extract_allergies_from_section(
    section_text: str,
    source_type: str,
    source_id: Optional[str],
    source_ts: Optional[str],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
    """Extract allergies from an Allergies section.

    Returns (allergy_items, evidence, allergy_status).
    allergy_status: "NKA" | "present" | None
    """
    items: List[Dict[str, Any]] = []
    evidence: List[Dict[str, Any]] = []
    allergy_status: Optional[str] = None

    lines = section_text.split("\n")

    # Check for NKA
    full = " ".join(l.strip() for l in lines)
    if re.search(r"No\s+Known\s+Allergies|NKDA|NKA", full, re.IGNORECASE):
        allergy_status = "NKA"
        # Build evidence for the NKA line
        for line in lines:
            stripped = line.strip()
            if re.search(r"No\s+Known\s+Allergies|NKDA|NKA", stripped, re.IGNORECASE):
                rid = _make_raw_line_id(source_type, source_id, stripped)
                evidence.append({
                    "role": "allergy_nka",
                    "label": "No Known Allergies",
                    "source_type": source_type,
                    "source_id": source_id,
                    "ts": source_ts,
                    "raw_line_id": rid,
                    "snippet": _snippet(stripped),
                })
                break
        return items, evidence, allergy_status

    # Look for allergen entries
    in_allergen_table = False
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Skip blank/header lines
        if not stripped:
            i += 1
            continue

        # Skip "Allergies" sub-headers
        if re.match(r"^\s*Allergies?\s*$", stripped, re.IGNORECASE):
            i += 1
            continue

        # Detect allergen table header
        if RE_ALLERGEN_HEADER.search(stripped):
            in_allergen_table = True
            i += 1
            continue

        # Bullet line = allergen entry (Epic uses '•')
        if stripped.startswith("•"):
            raw_text = re.sub(r"^•\s*", "", stripped)
            allergy_status = "present"

            # Parse allergen name and inline reaction (tab-separated)
            parts = raw_text.split("\t")
            allergen = parts[0].strip() if parts else raw_text.strip()
            inline_reaction = parts[1].strip() if len(parts) > 1 and parts[1].strip() else None

            # Look ahead for indented reaction line
            reaction = inline_reaction
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                if next_line and not next_line.startswith("•"):
                    # Skip if it looks like a section boundary or another header
                    if not RE_SECTION_BOUNDARY.match(next_line) and not re.match(r"^\s*Allergies?\s*$", next_line, re.IGNORECASE):
                        if not reaction:
                            reaction = next_line
                        else:
                            reaction = next_line  # indented reaction overrides
                        i += 1

            if allergen:
                rid = _make_raw_line_id(source_type, source_id, stripped)
                entry: Dict[str, Any] = {
                    "allergen": allergen,
                    "raw_line_id": rid,
                    "source_type": source_type,
                    "ts": source_ts,
                }
                if reaction:
                    entry["reaction"] = reaction

                items.append(entry)
                evidence.append({
                    "role": "allergy",
                    "label": allergen,
                    "source_type": source_type,
                    "source_id": source_id,
                    "ts": source_ts,
                    "raw_line_id": rid,
                    "snippet": _snippet(stripped),
                })

        i += 1

    return items, evidence, allergy_status


# ── Social History extraction ──────────────────────────────────────

def _extract_social_from_section(
    section_text: str,
    source_type: str,
    source_id: Optional[str],
    source_ts: Optional[str],
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Extract social history fields from a Social Hx section.

    Returns (social_dict, evidence).
    """
    social: Dict[str, Any] = {}
    evidence: List[Dict[str, Any]] = []

    lines = section_text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Smoking status
        m = RE_SMOKING.search(stripped)
        if m and "smoking_status" not in social:
            val = m.group(1).strip()
            rid = _make_raw_line_id(source_type, source_id, stripped)
            social["smoking_status"] = val
            evidence.append({
                "role": "social_smoking",
                "label": f"smoking_status={val}",
                "source_type": source_type,
                "source_id": source_id,
                "ts": source_ts,
                "raw_line_id": rid,
                "snippet": _snippet(stripped),
            })

        # Smokeless tobacco
        m = RE_SMOKELESS.search(stripped)
        if m and "smokeless_tobacco" not in social:
            val = m.group(1).strip()
            rid = _make_raw_line_id(source_type, source_id, stripped)
            social["smokeless_tobacco"] = val
            evidence.append({
                "role": "social_smokeless",
                "label": f"smokeless_tobacco={val}",
                "source_type": source_type,
                "source_id": source_id,
                "ts": source_ts,
                "raw_line_id": rid,
                "snippet": _snippet(stripped),
            })

        # Vaping status
        m = RE_VAPING.search(stripped)
        if m and "vaping_status" not in social:
            val = m.group(1).strip()
            rid = _make_raw_line_id(source_type, source_id, stripped)
            social["vaping_status"] = val
            evidence.append({
                "role": "social_vaping",
                "label": f"vaping_status={val}",
                "source_type": source_type,
                "source_id": source_id,
                "ts": source_ts,
                "raw_line_id": rid,
                "snippet": _snippet(stripped),
            })

        # Alcohol use
        m = RE_ALCOHOL.search(stripped)
        if m and "alcohol_use" not in social:
            val = m.group(1).strip()
            rid = _make_raw_line_id(source_type, source_id, stripped)
            social["alcohol_use"] = val
            evidence.append({
                "role": "social_alcohol",
                "label": f"alcohol_use={val}",
                "source_type": source_type,
                "source_id": source_id,
                "ts": source_ts,
                "raw_line_id": rid,
                "snippet": _snippet(stripped),
            })

        # Drug use
        m = RE_DRUG_USE.search(stripped)
        if m and "drug_use" not in social:
            val = m.group(1).strip()
            rid = _make_raw_line_id(source_type, source_id, stripped)
            drug_info: Dict[str, Any] = {"status": val}

            # Look ahead for Types: and Comment: on indented lines
            j = i + 1
            while j < len(lines):
                next_stripped = lines[j].strip()
                tm = RE_DRUG_TYPES.search(next_stripped)
                if tm:
                    drug_info["types"] = tm.group(1).strip()
                    j += 1
                    continue
                cm = RE_DRUG_COMMENT.search(next_stripped)
                if cm:
                    drug_info["comment"] = cm.group(1).strip()
                    j += 1
                    continue
                # Stop if we hit a new field or blank line in structure
                if next_stripped and not next_stripped.startswith(("\t", " ")):
                    break
                if not next_stripped:
                    j += 1
                    continue
                j += 1
                break
            i = j - 1  # will be incremented at end of loop

            social["drug_use"] = drug_info
            evidence.append({
                "role": "social_drug_use",
                "label": f"drug_use={val}",
                "source_type": source_type,
                "source_id": source_id,
                "ts": source_ts,
                "raw_line_id": rid,
                "snippet": _snippet(stripped),
            })

        # Marital status
        m = RE_MARITAL.search(stripped)
        if m and "marital_status" not in social:
            val = m.group(1).strip()
            rid = _make_raw_line_id(source_type, source_id, stripped)
            social["marital_status"] = val
            evidence.append({
                "role": "social_marital",
                "label": f"marital_status={val}",
                "source_type": source_type,
                "source_id": source_id,
                "ts": source_ts,
                "raw_line_id": rid,
                "snippet": _snippet(stripped),
            })

        i += 1

    return social, evidence


# ── Item scanner ────────────────────────────────────────────────────

def _scan_item(
    text: str,
    source_type: str,
    source_id: Optional[str],
    source_ts: Optional[str],
) -> Dict[str, Any]:
    """Scan a single timeline item for PMH, allergies, and social hx."""

    all_pmh: List[Dict[str, Any]] = []
    all_pmh_evidence: List[Dict[str, Any]] = []
    all_allergies: List[Dict[str, Any]] = []
    all_allergy_evidence: List[Dict[str, Any]] = []
    allergy_status: Optional[str] = None
    social: Dict[str, Any] = {}
    social_evidence: List[Dict[str, Any]] = []

    # ── PMH sections ──
    for m in RE_PMH_HEADER.finditer(text):
        # Only process if this looks like a section start (near line boundary)
        start = m.start()
        # Check this is near a line start
        line_start = text.rfind("\n", 0, start)
        prefix = text[line_start + 1:start].strip() if line_start >= 0 else text[:start].strip()
        if prefix and not prefix.endswith(":"):
            continue  # Skip matches embedded in other text

        section_text = _extract_section_text(text, start, m.end())
        items, ev = _extract_pmh_from_section(
            section_text, source_type, source_id, source_ts,
        )
        all_pmh.extend(items)
        all_pmh_evidence.extend(ev)

    # ── Allergies sections ──
    for m in RE_ALLERGIES_HEADER.finditer(text):
        # Find section boundary for allergies
        # Allergies sections end at Social Hx, Surgical Hx, Meds, ROS, etc.
        rest = text[m.end():]
        allergy_end_re = re.compile(
            r"^\s*(?:Social\s+Hx|SOCIAL\s+HISTORY|Social\s+History|"
            r"Surgical\s+Hx|Past\s+Surgical|"
            r"Meds\s*:|Medications|Current\s+(?:Outpatient|Medications)|Scheduled\s+meds|"
            r"No\s+current\s+(?:facility|outpatient)|"
            r"ROS\s*:|Review\s+of\s+Systems|"
            r"Secondary\s+Survey|Primary\s+Survey|"
            r"PMH|PAST\s+MEDICAL|Past\s+Medical|"
            r"HPI|History\s+of\s+Present|"
            r"Physical\s+Exam|Assessment|Plan\s*:|Labs\s*:)",
            re.IGNORECASE | re.MULTILINE,
        )
        end_m = allergy_end_re.search(rest)
        section_text = rest[:end_m.start()] if end_m else rest

        items, ev, status = _extract_allergies_from_section(
            section_text, source_type, source_id, source_ts,
        )
        all_allergies.extend(items)
        all_allergy_evidence.extend(ev)
        if status and allergy_status is None:
            allergy_status = status

    # ── Social Hx sections ──
    for m in RE_SOCIAL_HEADER.finditer(text):
        # Social sections end at Surgical Hx, ROS, Meds, PMH, etc.
        rest = text[m.end():]
        social_end_re = re.compile(
            r"^\s*(?:Surgical\s+Hx|Past\s+Surgical|"
            r"ROS\s*:|Review\s+of\s+Systems|"
            r"Meds\s*:|Medications|Current\s+Outpatient|"
            r"PMH|PAST\s+MEDICAL|Past\s+Medical|"
            r"Allergies|ALLERGIES|"
            r"Secondary\s+Survey|Primary\s+Survey|"
            r"Physical\s+Exam|Assessment|Plan\s*:|Labs\s*:|"
            r"HPI|History\s+of\s+Present|"
            r"Chief\s+Complaint)",
            re.IGNORECASE | re.MULTILINE,
        )
        end_m = social_end_re.search(rest)
        section_text = rest[:end_m.start()] if end_m else rest

        s, ev = _extract_social_from_section(
            section_text, source_type, source_id, source_ts,
        )
        # Merge social — first-seen wins (already guarded in extractor)
        for k, v in s.items():
            if k not in social:
                social[k] = v
        social_evidence.extend(ev)

    return {
        "pmh_items": all_pmh,
        "pmh_evidence": all_pmh_evidence,
        "allergies": all_allergies,
        "allergy_evidence": all_allergy_evidence,
        "allergy_status": allergy_status,
        "social": social,
        "social_evidence": social_evidence,
    }


# ── Deduplication ───────────────────────────────────────────────────

def _dedup_pmh(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicate PMH items by normalized label."""
    seen: set = set()
    result: List[Dict[str, Any]] = []
    for item in items:
        key = _normalize_pmh_label(item["label"])
        if key and key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _dedup_allergies(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicate allergies by allergen name (case-insensitive)."""
    seen: set = set()
    result: List[Dict[str, Any]] = []
    for item in items:
        key = item["allergen"].strip().lower()
        if key and key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _dedup_evidence(
    evidence: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Deduplicate evidence by raw_line_id."""
    seen: set = set()
    result: List[Dict[str, Any]] = []
    for ev in evidence:
        rid = ev.get("raw_line_id", "")
        if rid not in seen:
            seen.add(rid)
            result.append(ev)
    return result


# ── Main extractor ──────────────────────────────────────────────────

def extract_pmh_social_allergies(
    pat_features: Dict[str, Any],
    days_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Extract PMH, social history, and allergies from patient timeline.

    Args:
        pat_features: partial patient features dict (unused, API compat).
        days_data: full patient_days_v1.json dict.

    Returns:
        Structured dict with PMH items, allergies, social history,
        evidence, notes, warnings.
    """
    all_pmh: List[Dict[str, Any]] = []
    all_pmh_evidence: List[Dict[str, Any]] = []
    all_allergies: List[Dict[str, Any]] = []
    all_allergy_evidence: List[Dict[str, Any]] = []
    allergy_status: Optional[str] = None
    social: Dict[str, Any] = {}
    social_evidence: List[Dict[str, Any]] = []
    notes: List[str] = []
    warnings: List[str] = []

    days = days_data.get("days", {})
    if not days:
        return _build_result(
            pmh_items=[], pmh_evidence=[],
            allergies=[], allergy_evidence=[], allergy_status=None,
            social={}, social_evidence=[],
            notes=["no_days_data"], warnings=[],
        )

    scanned_items = 0
    for day_key in sorted(days.keys()):
        day_val = days[day_key]
        items = day_val.get("items", [])

        for item in items:
            item_type = item.get("type", "")
            if item_type not in _SOURCE_TYPES:
                continue

            text = (item.get("payload") or {}).get("text", "")
            if not text.strip():
                continue

            item_ts = item.get("dt")
            item_id = item.get("id")
            scanned_items += 1

            scan = _scan_item(text, item_type, item_id, item_ts)

            all_pmh.extend(scan["pmh_items"])
            all_pmh_evidence.extend(scan["pmh_evidence"])
            all_allergies.extend(scan["allergies"])
            all_allergy_evidence.extend(scan["allergy_evidence"])
            if scan["allergy_status"] and allergy_status is None:
                allergy_status = scan["allergy_status"]

            for k, v in scan["social"].items():
                if k not in social:
                    social[k] = v
            social_evidence.extend(scan["social_evidence"])

    # Deduplicate
    all_pmh = _dedup_pmh(all_pmh)
    all_pmh_evidence = _dedup_evidence(all_pmh_evidence)
    all_allergies = _dedup_allergies(all_allergies)
    all_allergy_evidence = _dedup_evidence(all_allergy_evidence)
    social_evidence = _dedup_evidence(social_evidence)

    if all_pmh:
        notes.append(f"pmh_items_found: {len(all_pmh)}")
    if all_allergies:
        notes.append(f"allergies_found: {len(all_allergies)}")
    if social:
        notes.append(f"social_fields_found: {sorted(social.keys())}")

    return _build_result(
        pmh_items=all_pmh, pmh_evidence=all_pmh_evidence,
        allergies=all_allergies, allergy_evidence=all_allergy_evidence,
        allergy_status=allergy_status,
        social=social, social_evidence=social_evidence,
        notes=notes, warnings=warnings,
    )


def _build_result(
    pmh_items: List[Dict[str, Any]],
    pmh_evidence: List[Dict[str, Any]],
    allergies: List[Dict[str, Any]],
    allergy_evidence: List[Dict[str, Any]],
    allergy_status: Optional[str],
    social: Dict[str, Any],
    social_evidence: List[Dict[str, Any]],
    notes: List[str],
    warnings: List[str],
) -> Dict[str, Any]:
    """Assemble the final output dict."""

    # Combine all evidence
    all_evidence = pmh_evidence + allergy_evidence + social_evidence

    return {
        "pmh_items": pmh_items,
        "pmh_count": len(pmh_items),
        "allergies": allergies,
        "allergy_count": len(allergies),
        "allergy_status": allergy_status or _DNA,
        "social_history": social,
        "source_rule_id": "pmh_social_allergies_v1",
        "evidence": all_evidence,
        "notes": notes,
        "warnings": warnings,
    }
