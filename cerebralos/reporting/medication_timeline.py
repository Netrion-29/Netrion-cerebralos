#!/usr/bin/env python3
"""
Medication timeline tracker for DVT prophylaxis and anticoagulation.

Extracts blood thinner administration with exact timing per user requirement:
"I want every single blood thinners first dose listed, day and time"
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from datetime import datetime


# Blood thinner medications (generic and brand names)
_BLOOD_THINNERS = {
    # Low molecular weight heparins
    "enoxaparin": "Enoxaparin (Lovenox)",
    "lovenox": "Enoxaparin (Lovenox)",
    "dalteparin": "Dalteparin (Fragmin)",
    "fragmin": "Dalteparin (Fragmin)",

    # Unfractionated heparin
    "heparin": "Heparin",

    # DOACs (Direct Oral Anticoagulants)
    "apixaban": "Apixaban (Eliquis)",
    "eliquis": "Apixaban (Eliquis)",
    "rivaroxaban": "Rivaroxaban (Xarelto)",
    "xarelto": "Rivaroxaban (Xarelto)",
    "dabigatran": "Dabigatran (Pradaxa)",
    "pradaxa": "Dabigatran (Pradaxa)",
    "edoxaban": "Edoxaban (Savaysa)",
    "savaysa": "Edoxaban (Savaysa)",

    # Warfarin
    "warfarin": "Warfarin (Coumadin)",
    "coumadin": "Warfarin (Coumadin)",

    # Antiplatelet agents
    "aspirin": "Aspirin (ASA)",
    "asa": "Aspirin (ASA)",
    "clopidogrel": "Clopidogrel (Plavix)",
    "plavix": "Clopidogrel (Plavix)",
    "prasugrel": "Prasugrel (Effient)",
    "effient": "Prasugrel (Effient)",
    "ticagrelor": "Ticagrelor (Brilinta)",
    "brilinta": "Ticagrelor (Brilinta)",
}


def _parse_administration_table(mar_text: str) -> List[Dict[str, str]]:
    """
    Parse administration table from MAR text.

    Returns list of administrations with action_time, recorded_time, nurse, site.
    """
    administrations = []

    # Parse administration table rows directly from the section
    # Format: "Given : 30 mg :   : Subcutaneous	12/18/25 1118	12/18/25 1118	L, Craddock Sarah, RN	Left Lower Quadrant Abdominal"
    admin_pattern = re.compile(
        r"Given\s*:\s*([^\t]+)\s*:\s*:\s*([^\t]+)\t"  # Dose and route
        r"(\d{1,2}/\d{1,2}/\d{2,4}\s+\d{4})\t"  # Action time
        r"(\d{1,2}/\d{1,2}/\d{2,4}\s+\d{4})\t"  # Recorded time
        r"([^\t]+)\t"  # Nurse name
        r"([^\t\n]*)",  # Site
        re.IGNORECASE
    )

    for match in admin_pattern.finditer(mar_text):
        dose = match.group(1).strip()
        route = match.group(2).strip()
        action_time = match.group(3).strip()
        recorded_time = match.group(4).strip()
        nurse = match.group(5).strip()
        site = match.group(6).strip()

        administrations.append({
            "dose": dose,
            "route": route,
            "action_time": action_time,
            "recorded_time": recorded_time,
            "nurse": nurse,
            "site": site,
        })

    return administrations


def _parse_order_details(mar_text: str) -> Dict[str, Any]:
    """
    Extract order details from MAR text.

    Returns dict with ordered_dose, route, frequency, start_time, end_time.
    """
    details = {}

    # Ordered dose
    dose_match = re.search(r"Ordered Dose:\s*([^\t\n]+)", mar_text)
    if dose_match:
        details["ordered_dose"] = dose_match.group(1).strip()

    # Route
    route_match = re.search(r"Route:\s*([^\t\n]+)", mar_text, re.IGNORECASE)
    if route_match:
        details["route"] = route_match.group(1).strip()

    # Frequency
    freq_match = re.search(r"Frequency:\s*([^\t\n]+)", mar_text)
    if freq_match:
        details["frequency"] = freq_match.group(1).strip()

    # Scheduled start date/time
    start_match = re.search(
        r"Scheduled Start Date/Time:\s*(\d{1,2}/\d{1,2}/\d{2,4}\s+\d{4})",
        mar_text
    )
    if start_match:
        details["scheduled_start"] = start_match.group(1).strip()

    # End date/time
    end_match = re.search(
        r"End Date/Time:\s*(\d{1,2}/\d{1,2}/\d{2,4}\s+\d{4})",
        mar_text
    )
    if end_match:
        details["scheduled_end"] = end_match.group(1).strip()

    # Order time (when ordered, not when scheduled to start)
    order_match = re.search(
        r"Ordering Date/Time:\s*\w+\s+(\w+\s+\d{1,2},\s+\d{4}\s+\d{4})",
        mar_text
    )
    if order_match:
        details["order_time"] = order_match.group(1).strip()

    return details


def _identify_blood_thinner(medication_name: str) -> Optional[str]:
    """
    Identify if medication is a blood thinner and return standardized name.

    Returns canonical name (e.g., "Enoxaparin (Lovenox)") or None.
    """
    lower_name = medication_name.lower()

    for key, canonical in _BLOOD_THINNERS.items():
        if key in lower_name:
            return canonical

    return None


def extract_blood_thinner_timeline(evaluation: Dict) -> List[Dict[str, Any]]:
    """
    Extract blood thinner medications with first dose timing.

    Returns list of medication records sorted by first administration time.
    Each record contains:
    - medication_name: Canonical name (e.g., "Enoxaparin (Lovenox)")
    - order_details: Dict with dose, route, frequency, scheduled start/end, order time
    - first_dose: Dict with action_time, nurse, site
    - all_doses: List of all administrations
    - clinical_notes: Relevant notes about holds, contraindications, clearance
    """
    blood_thinners = []

    # Extract from MAR evidence blocks
    for snippet in evaluation.get("all_evidence_snippets", []):
        if snippet.get("source_type") != "MAR":
            continue

        text = snippet.get("text", "")

        # Split by medication headers (lines with medication name + bracket number)
        # Pattern: medication name followed by [number]
        # This keeps Order Details and All Administrations together
        med_sections = re.split(r"(?=^[A-Za-z].+?\[\d+\]$)", text, flags=re.MULTILINE)

        for section in med_sections:
            if not section.strip() or len(section) < 100:
                continue

            # Look for "All Administrations of" to identify the medication name
            admin_match = re.search(
                r"All Administrations of (.+?)$",
                section,
                re.MULTILINE
            )

            if not admin_match:
                continue

            medication_name = admin_match.group(1).strip()
            canonical_name = _identify_blood_thinner(medication_name)

            if not canonical_name:
                continue  # Not a blood thinner

            # Parse order details from this section
            order_details = _parse_order_details(section)

            # Parse administrations from this section
            administrations = _parse_administration_table(section)

            if not administrations:
                # No administrations yet (ordered but not given)
                blood_thinners.append({
                    "medication_name": canonical_name,
                    "order_details": order_details,
                    "first_dose": None,
                    "all_doses": [],
                    "status": "Ordered but not yet administered",
                })
                continue

            # Sort administrations by action time (earliest first)
            # Convert to datetime for proper sorting
            def parse_time(time_str):
                try:
                    return datetime.strptime(time_str, "%m/%d/%y %H%M")
                except:
                    return datetime.min

            administrations.sort(key=lambda a: parse_time(a["action_time"]))

            first_dose = administrations[0]

            blood_thinners.append({
                "medication_name": canonical_name,
                "order_details": order_details,
                "first_dose": first_dose,
                "all_doses": administrations,
                "total_doses": len(administrations),
                "status": "Administered",
            })

    # Extract clinical notes about holds, contraindications, clearance
    clinical_notes = _extract_clinical_notes_about_anticoagulation(evaluation)

    # Attach relevant clinical notes to each medication
    for med in blood_thinners:
        med["clinical_notes"] = [
            note for note in clinical_notes
            if any(keyword in note.lower() for keyword in [
                med["medication_name"].lower().split()[0],  # e.g., "enoxaparin"
                "dvt", "anticoagulation", "blood thinner", "hold", "lovenox",
                "heparin", "aspirin", "warfarin", "coumadin"
            ])
        ]

    # Sort by first dose time (earliest first)
    def get_first_dose_time(med):
        if not med.get("first_dose"):
            return datetime.max
        return parse_time(med["first_dose"]["action_time"])

    blood_thinners.sort(key=get_first_dose_time)

    return blood_thinners


def _extract_clinical_notes_about_anticoagulation(evaluation: Dict) -> List[str]:
    """
    Extract clinical notes mentioning anticoagulation decisions.

    Returns list of note snippets (150 chars each) mentioning DVT prophylaxis,
    holds, contraindications, or clearance for anticoagulation.
    """
    notes = []

    keywords = [
        "dvt prophylaxis", "dvt ppx", "anticoagulation", "blood thinner",
        "hold aspirin", "hold lovenox", "hold heparin", "hold anticoagulation",
        "okay for lovenox", "cleared for anticoagulation", "okay for heparin",
        "contraindication", "sah", "intracranial hemorrhage",
    ]

    for snippet in evaluation.get("all_evidence_snippets", []):
        src = snippet.get("source_type", "")
        if src not in ("PHYSICIAN_NOTE", "TRAUMA_HP", "CONSULT_NOTE", "DISCHARGE"):
            continue

        text = snippet.get("text", "")
        text_lower = text.lower()

        # Check if any keyword appears
        for keyword in keywords:
            if keyword in text_lower:
                # Extract sentence containing keyword
                sentences = re.split(r'[.!?\n]+', text)
                for sentence in sentences:
                    if keyword in sentence.lower():
                        clean_sentence = sentence.strip()
                        if len(clean_sentence) > 10:
                            notes.append(clean_sentence[:200])
                        break
                break

    return list(set(notes))  # Deduplicate


def format_blood_thinner_report(timeline: List[Dict[str, Any]]) -> str:
    """
    Format blood thinner timeline as human-readable text.

    Returns formatted report text.
    """
    if not timeline:
        return "No blood thinner medications administered during this admission."

    lines = []
    lines.append("💊 BLOOD THINNER / DVT PROPHYLAXIS TIMELINE")
    lines.append("")

    for med in timeline:
        name = med["medication_name"]
        order = med.get("order_details", {})
        first = med.get("first_dose")
        total = med.get("total_doses", 0)

        lines.append(f"• {name}")

        if order.get("ordered_dose"):
            lines.append(f"  Dose: {order['ordered_dose']}")
        if order.get("route"):
            lines.append(f"  Route: {order['route']}")
        if order.get("frequency"):
            lines.append(f"  Frequency: {order['frequency']}")

        if first:
            action_time = first["action_time"]
            nurse = first.get("nurse", "")
            lines.append(f"  ⭐ FIRST DOSE: {action_time} (by {nurse})")
            lines.append(f"  Total doses given: {total}")
        elif med.get("status") == "Ordered but not yet administered":
            lines.append(f"  Status: {med['status']}")
            if order.get("scheduled_start"):
                lines.append(f"  Scheduled start: {order['scheduled_start']}")

        # Clinical notes
        clinical_notes = med.get("clinical_notes", [])
        if clinical_notes:
            lines.append("  Clinical context:")
            for note in clinical_notes[:3]:  # Show first 3 notes
                lines.append(f"    → {note}")

        lines.append("")

    return "\n".join(lines)
