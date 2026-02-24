#!/usr/bin/env python3
"""
Anticoagulation Context Extraction v1 for CerebralOS.

Deterministic extraction of home/outpatient anticoagulant and
antiplatelet medications from trauma-relevant note content.

Scans TRAUMA_HP, PHYSICIAN_NOTE, ED_NOTE, CONSULT_NOTE, and NURSING_NOTE
items for explicit outpatient medication table entries referencing
anticoagulants or antiplatelets.

Extracts:
  - home_anticoagulants[]:  apixaban/Eliquis, rivaroxaban/Xarelto,
    dabigatran/Pradaxa, warfarin/Coumadin, edoxaban/Savaysa
  - home_antiplatelets[]:   aspirin, clopidogrel/Plavix,
    ticagrelor/Brilinta, prasugrel/Effient
  - anticoag_present:       yes / no / DATA NOT AVAILABLE
  - antiplatelet_present:   yes / no / DATA NOT AVAILABLE

Fail-closed behaviour:
  - Only medication lines that explicitly name a known drug are captured.
  - Diagnosis mentions alone ("Hx afib") do NOT trigger extraction.
  - [DISCONTINUED] entries are captured but flagged as discontinued.
  - No dose/frequency normalization beyond trivially explicit values.
  - No LLM, no ML, no clinical inference.

Sources (scanned in timeline order):
  TRAUMA_HP, PHYSICIAN_NOTE, ED_NOTE, CONSULT_NOTE, NURSING_NOTE

Output key: ``anticoag_context_v1`` (under top-level ``features`` dict)
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

# ── Known anticoagulant drugs ──────────────────────────────────────
# Each entry: (regex pattern, normalized_name, class)
_ANTICOAGULANT_DRUGS: List[Tuple[re.Pattern, str, str]] = [
    (re.compile(r"\bapixaban\b", re.IGNORECASE), "apixaban", "DOAC"),
    (re.compile(r"\bELIQUIS\b", re.IGNORECASE), "apixaban", "DOAC"),
    (re.compile(r"\brivaroxaban\b", re.IGNORECASE), "rivaroxaban", "DOAC"),
    (re.compile(r"\bXarelto\b", re.IGNORECASE), "rivaroxaban", "DOAC"),
    (re.compile(r"\bdabigatran\b", re.IGNORECASE), "dabigatran", "DOAC"),
    (re.compile(r"\bPradaxa\b", re.IGNORECASE), "dabigatran", "DOAC"),
    (re.compile(r"\bedoxaban\b", re.IGNORECASE), "edoxaban", "DOAC"),
    (re.compile(r"\bSavaysa\b", re.IGNORECASE), "edoxaban", "DOAC"),
    (re.compile(r"\bwarfarin\b", re.IGNORECASE), "warfarin", "VKA"),
    (re.compile(r"\bCoumadin\b", re.IGNORECASE), "warfarin", "VKA"),
]

# ── Known antiplatelet drugs ──────────────────────────────────────
_ANTIPLATELET_DRUGS: List[Tuple[re.Pattern, str, str]] = [
    (re.compile(r"\baspirin\b", re.IGNORECASE), "aspirin", "antiplatelet"),
    (re.compile(r"\bHALFPRIN\b", re.IGNORECASE), "aspirin", "antiplatelet"),
    (re.compile(r"\bASPIR(?:IN)?\s+(?:LOW\s+DOSE|EC)\b", re.IGNORECASE), "aspirin", "antiplatelet"),
    (re.compile(r"\bclopidogrel\b", re.IGNORECASE), "clopidogrel", "antiplatelet"),
    (re.compile(r"\bPlavix\b", re.IGNORECASE), "clopidogrel", "antiplatelet"),
    (re.compile(r"\bticagrelor\b", re.IGNORECASE), "ticagrelor", "antiplatelet"),
    (re.compile(r"\bBrilinta\b", re.IGNORECASE), "ticagrelor", "antiplatelet"),
    (re.compile(r"\bprasugrel\b", re.IGNORECASE), "prasugrel", "antiplatelet"),
    (re.compile(r"\bEffient\b", re.IGNORECASE), "prasugrel", "antiplatelet"),
]

# ── Section header patterns ────────────────────────────────────────
# Match "Current Outpatient Medications on File Prior to Encounter"
# or similar outpatient medication headers
RE_OUTPATIENT_HEADER = re.compile(
    r"Current\s+Outpatient\s+Medications\s+on\s+File",
    re.IGNORECASE,
)

# Match the end of the outpatient med section
RE_MED_SECTION_END = re.compile(
    r"^\s*(?:Allergies|Social\s+Hx|Surgical\s+Hx|Past\s+Surgical|"
    r"ROS:|Secondary\s+Survey|Physical\s+Exam|"
    r"Medications\s+Ordered|Assessment|Plan:|Labs:)\b",
    re.IGNORECASE | re.MULTILINE,
)

# ── Bullet line pattern (outpatient med entry) ─────────────────────
RE_BULLET_LINE = re.compile(r"^[•\-\*]\s+", re.MULTILINE)

# ── Discontinued marker ───────────────────────────────────────────
RE_DISCONTINUED = re.compile(
    r"\[DISCONTINUED\]|\bDiscontinued\b|\bdiscontinued\b",
    re.IGNORECASE,
)


# ── Helpers ─────────────────────────────────────────────────────────

def _make_raw_line_id(
    source_type: str,
    source_id: Optional[str],
    line_text: str,
) -> str:
    """Build a deterministic raw_line_id from evidence coordinates."""
    payload = f"{source_type}|{source_id or ''}|{line_text.strip()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _snippet(text: str, max_len: int = 120) -> str:
    """Trim text to a short deterministic snippet."""
    text = str(text).strip()
    if len(text) <= max_len:
        return text
    return text[:max_len] + "\u2026"


def _extract_dose(line: str) -> Optional[str]:
    """Extract dose if trivially explicit (e.g. '5 MG', '81 MG')."""
    m = re.search(
        r"(\d+(?:\.\d+)?)\s*(?:MG|mg|MCG|mcg)\s*(?:tablet|capsule|EC)?\b",
        line,
    )
    if m:
        return m.group(0).strip()
    return None


def _extract_indication(line: str) -> Optional[str]:
    """Extract indication if explicitly stated (e.g. 'Indications: ...')."""
    m = re.search(r"Indications?:\s*(.+?)(?:\t|$)", line, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return None


# ── Outpatient section parser ──────────────────────────────────────

def _find_outpatient_med_sections(text: str) -> List[str]:
    """
    Find all outpatient medication sections in the text.

    Returns list of section text blocks (from header to next section).
    """
    sections: List[str] = []
    for m in RE_OUTPATIENT_HEADER.finditer(text):
        start = m.start()
        # Find the end of this section
        end_m = RE_MED_SECTION_END.search(text, m.end() + 1)
        end = end_m.start() if end_m else len(text)
        sections.append(text[start:end])
    return sections


def _scan_outpatient_section(
    section_text: str,
    source_type: str,
    source_id: Optional[str],
    source_ts: Optional[str],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Scan an outpatient medication section for anticoagulants and antiplatelets.

    Returns (anticoagulants, antiplatelets, evidence, notes_list_unused).
    """
    anticoagulants: List[Dict[str, Any]] = []
    antiplatelets: List[Dict[str, Any]] = []
    evidence: List[Dict[str, Any]] = []

    lines = section_text.split("\n")
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Check for anticoagulant drugs
        for pat, normalized, drug_class in _ANTICOAGULANT_DRUGS:
            if pat.search(stripped):
                rid = _make_raw_line_id(source_type, source_id, stripped)
                is_discontinued = bool(RE_DISCONTINUED.search(stripped))

                entry = {
                    "name": _extract_med_name(stripped),
                    "normalized_name": normalized,
                    "class": drug_class,
                    "context": "home_outpatient",
                    "discontinued": is_discontinued,
                    "raw_line_id": rid,
                    "source_type": source_type,
                    "ts": source_ts,
                }
                dose = _extract_dose(stripped)
                if dose:
                    entry["dose"] = dose
                indication = _extract_indication(stripped)
                if indication:
                    entry["indication"] = indication

                # Deduplicate by normalized_name within this section
                if not any(
                    a["normalized_name"] == normalized
                    and a["discontinued"] == is_discontinued
                    for a in anticoagulants
                ):
                    anticoagulants.append(entry)
                    evidence.append({
                        "role": "home_anticoagulant",
                        "label": f"home_{normalized}",
                        "source_type": source_type,
                        "source_id": source_id,
                        "ts": source_ts,
                        "raw_line_id": rid,
                        "snippet": _snippet(stripped),
                    })
                break  # Only match first drug pattern per line

        # Check for antiplatelet drugs
        for pat, normalized, drug_class in _ANTIPLATELET_DRUGS:
            if pat.search(stripped):
                rid = _make_raw_line_id(source_type, source_id, stripped)
                is_discontinued = bool(RE_DISCONTINUED.search(stripped))

                entry = {
                    "name": _extract_med_name(stripped),
                    "normalized_name": normalized,
                    "class": drug_class,
                    "context": "home_outpatient",
                    "discontinued": is_discontinued,
                    "raw_line_id": rid,
                    "source_type": source_type,
                    "ts": source_ts,
                }
                dose = _extract_dose(stripped)
                if dose:
                    entry["dose"] = dose
                indication = _extract_indication(stripped)
                if indication:
                    entry["indication"] = indication

                if not any(
                    a["normalized_name"] == normalized
                    and a["discontinued"] == is_discontinued
                    for a in antiplatelets
                ):
                    antiplatelets.append(entry)
                    evidence.append({
                        "role": "home_antiplatelet",
                        "label": f"home_{normalized}",
                        "source_type": source_type,
                        "source_id": source_id,
                        "ts": source_ts,
                        "raw_line_id": rid,
                        "snippet": _snippet(stripped),
                    })
                break  # Only match first drug pattern per line

    return anticoagulants, antiplatelets, evidence, []


def _extract_med_name(line: str) -> str:
    """Extract the medication name from a bullet line.

    Typical formats:
      • apixaban (ELIQUIS) 5 MG tablet  Take ...
      • aspirin EC (HALFPRIN) 81 MG tablet  Take ...
      • warfarin (COUMADIN) 5 MG tablet  Take ...
    """
    # Remove bullet prefix
    cleaned = re.sub(r"^[•\-\*\s]+", "", line)
    # Remove [DISCONTINUED] prefix
    cleaned = re.sub(r"\[DISCONTINUED\]\s*", "", cleaned, flags=re.IGNORECASE)
    # Take everything up to the tab (sig info) or Take/Inject
    m = re.match(r"^(.+?)(?:\t|$)", cleaned)
    if m:
        name_part = m.group(1).strip()
        # Further trim at "Take " or "Inject " if present
        t = re.split(r"\s+Take\s+|\s+Inject\s+", name_part, maxsplit=1)
        name_part = t[0].strip()
        return name_part
    return cleaned.strip()


# ── Item scanner ────────────────────────────────────────────────────

def _scan_item(
    text: str,
    source_type: str,
    source_id: Optional[str],
    source_ts: Optional[str],
) -> Dict[str, Any]:
    """
    Scan a single timeline item text for home anticoag/antiplatelet content.

    Returns dict with anticoagulants, antiplatelets, evidence, notes, warnings.
    """
    all_anticoag: List[Dict[str, Any]] = []
    all_antiplatelet: List[Dict[str, Any]] = []
    all_evidence: List[Dict[str, Any]] = []
    all_notes: List[str] = []
    all_warnings: List[str] = []

    # Find outpatient medication sections
    sections = _find_outpatient_med_sections(text)

    if not sections:
        return {
            "anticoagulants": [],
            "antiplatelets": [],
            "evidence": [],
            "notes": [],
            "warnings": [],
        }

    for section in sections:
        ac, ap, ev, _ = _scan_outpatient_section(
            section, source_type, source_id, source_ts,
        )
        all_anticoag.extend(ac)
        all_antiplatelet.extend(ap)
        all_evidence.extend(ev)

    if all_anticoag:
        all_notes.append(
            f"home_anticoagulants_found: {len(all_anticoag)} drug(s)"
        )
    if all_antiplatelet:
        all_notes.append(
            f"home_antiplatelets_found: {len(all_antiplatelet)} drug(s)"
        )

    return {
        "anticoagulants": all_anticoag,
        "antiplatelets": all_antiplatelet,
        "evidence": all_evidence,
        "notes": all_notes,
        "warnings": all_warnings,
    }


# ── Main extractor ──────────────────────────────────────────────────

def extract_anticoag_context(
    pat_features: Dict[str, Any],
    days_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Extract anticoagulation context from patient timeline.

    Args:
        pat_features: partial patient features dict (unused, API compat).
        days_data: full patient_days_v1.json dict.

    Returns:
        Structured dict with home anticoagulant/antiplatelet presence,
        drug lists, evidence, notes, warnings.
    """
    all_anticoag: List[Dict[str, Any]] = []
    all_antiplatelet: List[Dict[str, Any]] = []
    all_evidence: List[Dict[str, Any]] = []
    all_notes: List[str] = []
    all_warnings: List[str] = []

    days = days_data.get("days", {})
    if not days:
        return _build_result(
            anticoagulants=[], antiplatelets=[],
            evidence=[], notes=["no_days_data"], warnings=[],
        )

    # Deduplicate across timeline items by normalized_name
    seen_anticoag: set = set()
    seen_antiplatelet: set = set()

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

            scan = _scan_item(text, item_type, item_id, item_ts)

            for ac in scan["anticoagulants"]:
                key = (ac["normalized_name"], ac["discontinued"])
                if key not in seen_anticoag:
                    seen_anticoag.add(key)
                    all_anticoag.append(ac)
                    # Add evidence for this entry
                    for ev in scan["evidence"]:
                        if ev["label"] == f"home_{ac['normalized_name']}":
                            all_evidence.append(ev)
                            break

            for ap in scan["antiplatelets"]:
                key = (ap["normalized_name"], ap["discontinued"])
                if key not in seen_antiplatelet:
                    seen_antiplatelet.add(key)
                    all_antiplatelet.append(ap)
                    for ev in scan["evidence"]:
                        if ev["label"] == f"home_{ap['normalized_name']}":
                            all_evidence.append(ev)
                            break

            all_notes.extend(scan["notes"])
            all_warnings.extend(scan["warnings"])

    return _build_result(
        anticoagulants=all_anticoag,
        antiplatelets=all_antiplatelet,
        evidence=all_evidence,
        notes=all_notes,
        warnings=all_warnings,
    )


def _build_result(
    anticoagulants: List[Dict[str, Any]],
    antiplatelets: List[Dict[str, Any]],
    evidence: List[Dict[str, Any]],
    notes: List[str],
    warnings: List[str],
) -> Dict[str, Any]:
    """Assemble the final output dict."""

    # Active (non-discontinued) drugs determine presence flags
    active_anticoag = [a for a in anticoagulants if not a.get("discontinued")]
    active_antiplatelet = [a for a in antiplatelets if not a.get("discontinued")]

    if active_anticoag:
        anticoag_present = "yes"
    elif anticoagulants:
        # Only discontinued entries found
        anticoag_present = "no"
        notes.append(
            "anticoag_all_discontinued: home anticoagulant(s) found "
            "but all marked [DISCONTINUED]"
        )
    else:
        anticoag_present = _DNA

    if active_antiplatelet:
        antiplatelet_present = "yes"
    elif antiplatelets:
        antiplatelet_present = "no"
        notes.append(
            "antiplatelet_all_discontinued: home antiplatelet(s) found "
            "but all marked [DISCONTINUED]"
        )
    else:
        antiplatelet_present = _DNA

    return {
        "anticoag_present": anticoag_present,
        "antiplatelet_present": antiplatelet_present,
        "home_anticoagulants": anticoagulants,
        "home_antiplatelets": antiplatelets,
        "anticoag_count": len(anticoagulants),
        "antiplatelet_count": len(antiplatelets),
        "source_rule_id": "anticoag_context_v1",
        "evidence": evidence,
        "notes": notes,
        "warnings": warnings,
    }
