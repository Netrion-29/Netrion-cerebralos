#!/usr/bin/env python3
"""
Narrative trauma report generator matching user's preferred format.

Generates clinical narrative summaries with emoji headers and structured sections.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from pathlib import Path
from cerebralos.reporting.evidence_utils import (
    extract_mechanism_of_injury,
    extract_injuries_from_imaging,
    extract_procedure_name,
    clean_evidence_text,
    extract_hp_sections,
    extract_trauma_category,
    extract_gcs,
    extract_fast_exam,
    extract_consults_from_plan,
    extract_injuries_from_impression,
)
from cerebralos.reporting.vitals import extract_vitals, format_vitals_summary
from cerebralos.reporting.devices import (
    extract_device_events,
    build_device_timelines,
    get_devices_on_date,
    format_device_report,
)


def _extract_patient_demographics(evaluation: Dict) -> Dict[str, str]:
    """Extract patient demographic information."""
    name = evaluation.get("patient_name", "Unknown")
    dob = evaluation.get("dob", "Unknown")
    arrival = evaluation.get("arrival_time", "Unknown")
    trauma_cat = evaluation.get("trauma_category", "N/A")
    status = "Completed admission (discharged)" if not evaluation.get("is_live") else "In hospital"

    # Calculate age from DOB if available
    age_text = ""
    if dob and dob != "Unknown":
        try:
            from datetime import datetime
            dob_dt = datetime.strptime(dob, "%m/%d/%Y")
            today = datetime.now()
            age = today.year - dob_dt.year - ((today.month, today.day) < (dob_dt.month, dob_dt.day))
            age_text = f"{age}-year-old"
        except:
            age_text = ""

    return {
        "name": name,
        "age_text": age_text,
        "dob": dob,
        "arrival": arrival,
        "trauma_cat": trauma_cat,
        "status": status,
    }


def _get_trauma_hp_text(evaluation: Dict) -> Optional[str]:
    """Extract Trauma H&P text from evidence."""
    for snippet in evaluation.get("all_evidence_snippets", []):
        if snippet.get("source_type") == "TRAUMA_HP":
            return snippet.get("text", "")
    return None


def _extract_mechanism(evaluation: Dict) -> Dict[str, Any]:
    """Extract mechanism of injury and alert history from H&P."""
    trauma_hp = _get_trauma_hp_text(evaluation)
    if not trauma_hp:
        return {"mechanism_text": [], "trauma_category": None}

    # Parse H&P sections
    sections = extract_hp_sections(trauma_hp)

    # Extract trauma category from Alert History
    trauma_category = None
    if "Alert History" in sections:
        trauma_category = extract_trauma_category(sections["Alert History"])

    # Extract mechanism from HPI
    mechanism_text = []
    if "HPI" in sections:
        mech = extract_mechanism_of_injury(sections["HPI"])
        if mech:
            mechanism_text.append(mech)
    elif trauma_hp:
        # Fallback to full text extraction
        mech = extract_mechanism_of_injury(trauma_hp)
        if mech:
            mechanism_text.append(mech)

    return {
        "mechanism_text": mechanism_text,
        "trauma_category": trauma_category,
    }


def _extract_clinical_findings(evaluation: Dict) -> Dict[str, Any]:
    """Extract GCS, FAST, and other critical clinical findings from Primary Survey."""
    trauma_hp = _get_trauma_hp_text(evaluation)
    if not trauma_hp:
        return {}

    sections = extract_hp_sections(trauma_hp)

    findings = {}

    # Extract from Primary Survey first
    if "Primary Survey" in sections:
        primary = sections["Primary Survey"]

        gcs = extract_gcs(primary)
        if gcs is not None:
            findings["gcs"] = gcs

        fast = extract_fast_exam(primary)
        if fast:
            findings["fast"] = fast

    # If GCS not found in Primary, check Secondary Survey
    if "gcs" not in findings and "Secondary Survey" in sections:
        gcs = extract_gcs(sections["Secondary Survey"])
        if gcs is not None:
            findings["gcs"] = gcs

    return findings


def _extract_injuries(evaluation: Dict) -> Dict[str, List[str]]:
    """
    Extract documented injuries from Impression and imaging.

    Returns dict with:
    - 'initial_impression': Injuries from H&P Impression (what trauma team knows at presentation)
    - 'imaging_findings': Injuries from imaging/radiology (confirmation/additional findings)
    """
    initial_impression = []
    imaging_findings = []

    trauma_hp = _get_trauma_hp_text(evaluation)

    # First: Extract from Impression section of H&P (initial trauma team assessment)
    if trauma_hp:
        sections = extract_hp_sections(trauma_hp)
        if "Impression" in sections:
            impression_injuries = extract_injuries_from_impression(sections["Impression"])
            initial_impression.extend(impression_injuries)

    # Then: Extract from imaging/radiology (cross-check and additional findings)
    for snippet in evaluation.get("all_evidence_snippets", []):
        src = snippet.get("source_type", "")
        if src in ("IMAGING", "RADIOLOGY"):
            text = snippet.get("text", "")
            found = extract_injuries_from_imaging(text)
            imaging_findings.extend(found)

    # Deduplicate each list while preserving order
    def dedupe(items):
        seen = set()
        unique = []
        for item in items:
            if item.lower() not in seen:
                seen.add(item.lower())
                unique.append(item)
        return unique

    return {
        "initial_impression": dedupe(initial_impression)[:5],
        "imaging_findings": dedupe(imaging_findings)[:10],
    }


def _extract_consults(evaluation: Dict) -> List[Dict[str, str]]:
    """Extract consult services and call times from Plan."""
    trauma_hp = _get_trauma_hp_text(evaluation)
    if not trauma_hp:
        return []

    sections = extract_hp_sections(trauma_hp)

    if "Plan" in sections:
        return extract_consults_from_plan(sections["Plan"])

    return []


def _extract_procedures(evaluation: Dict) -> List[Dict[str, str]]:
    """Extract operative/procedural interventions."""
    procedures = []

    for snippet in evaluation.get("all_evidence_snippets", []):
        src = snippet.get("source_type", "")
        if src in ("PROCEDURE", "OPERATIVE_NOTE"):
            text = snippet.get("text", "")
            ts = snippet.get("timestamp", "")
            proc_name = extract_procedure_name(text)
            if proc_name:
                procedures.append({
                    "name": proc_name,
                    "date": ts[:10] if ts and len(ts) >= 10 else "",
                })

    return procedures[:5]  # Limit to 5


def _extract_vital_summary(evaluation: Dict) -> Dict[str, str]:
    """Extract vital signs summary from evidence (if documented)."""
    # TODO: Parse vital signs from nursing notes or flow sheets
    # For now, return empty - this requires parsing structured data
    return {}


def _extract_disposition(evaluation: Dict) -> str:
    """Extract disposition from discharge note or status."""
    if evaluation.get("is_live"):
        return "Patient currently in hospital"

    for snippet in evaluation.get("all_evidence_snippets", []):
        if snippet.get("source_type") == "DISCHARGE":
            text = snippet.get("text", "")
            # Extract first meaningful sentence
            clean = clean_evidence_text(text, max_length=300)
            if clean:
                return clean

    return "Discharged"


def generate_narrative_trauma_summary(evaluation: Dict) -> str:
    """
    Generate narrative trauma summary matching user's preferred format.

    Returns formatted text with emoji headers and clinical narrative.
    """
    demo = _extract_patient_demographics(evaluation)
    name = demo["name"]
    age_text = demo["age_text"]

    lines = []
    lines.append(f"🧾 TRAUMA SUMMARY — {name}")
    lines.append(f"Patient: {name}")
    if age_text:
        lines.append(f"Age: {age_text}")
    lines.append(f"DOB: {demo['dob']}")
    lines.append(f"Status: {demo['status']}")

    # Mechanism of Injury + Trauma Category
    mech_data = _extract_mechanism(evaluation)
    if mech_data.get("trauma_category"):
        lines.append(f"Trauma Category: {mech_data['trauma_category']}")
    else:
        lines.append(f"Trauma Category: {demo['trauma_cat']}")
    lines.append("")

    # Clinical Findings (GCS, FAST)
    findings = _extract_clinical_findings(evaluation)
    if findings:
        lines.append("📊 Initial Clinical Findings")
        if "gcs" in findings:
            lines.append(f"• GCS: {findings['gcs']}")
        if "fast" in findings:
            lines.append(f"• FAST exam: {findings['fast']}")
        lines.append("")

    # Mechanism of Injury
    mechanism = mech_data.get("mechanism_text", [])
    if mechanism:
        lines.append("📍 Mechanism of Injury")
        for m in mechanism:
            lines.append(f"• {m}")
        lines.append("")

    # Injuries - distinguish initial impression from imaging findings
    injuries_data = _extract_injuries(evaluation)

    if injuries_data.get("initial_impression"):
        lines.append("🩺 Initial Assessment (H&P Impression)")
        for inj in injuries_data["initial_impression"]:
            lines.append(f"• {inj}")
        lines.append("")

    if injuries_data.get("imaging_findings"):
        lines.append("🔬 Imaging Findings (Cross-Check)")
        for inj in injuries_data["imaging_findings"]:
            lines.append(f"• {inj}")
        lines.append("")

    # Consults
    consults = _extract_consults(evaluation)
    if consults:
        lines.append("📞 Consults")
        for consult in consults:
            if consult.get("call_time"):
                lines.append(f"• {consult['service']} (called at {consult['call_time']})")
            else:
                lines.append(f"• {consult['service']}")
        lines.append("")

    # Operative Management
    procedures = _extract_procedures(evaluation)
    if procedures:
        lines.append("🛠️ Operative Management")
        for proc in procedures:
            if proc.get("date"):
                lines.append(f"Date: {proc['date']}")
            lines.append(f"Procedure: {proc['name']}")
            lines.append("")

    # Hospital Course (High-Level)
    lines.append("🏥 Hospital Course (High-Level)")
    if evaluation.get("is_live"):
        lines.append("• Patient currently admitted")
    else:
        lines.append("• Completed admission")
    # TODO: Extract more detailed course from progress notes
    lines.append("")

    # Disposition
    disposition = _extract_disposition(evaluation)
    lines.append("🚪 Disposition")
    lines.append(f"• {disposition}")
    lines.append("")

    # NTDS Relevance
    ntds_yes = [r for r in evaluation.get("ntds_results", []) if r["outcome"] == "YES"]
    if ntds_yes:
        lines.append("🧾 Trauma Registry Relevance (NTDS)")
        for event in ntds_yes:
            lines.append(f"• {event['canonical_name']}: YES")
        lines.append("")

    return "\n".join(lines)


def generate_daily_notes(evaluation: Dict) -> str:
    """
    Generate daily hospital notes grouped by calendar day.

    Per-day structure includes:
    - Hemodynamics (vitals)
    - Labs
    - Devices (placement/removal/days in place)
    - Imaging (verbatim impressions)
    - Clinical Notes (physician, consult, nursing, therapy)
    - Procedures
    - Medications

    Missing elements are explicitly stated, never silently omitted.

    Returns formatted text with hospital day headers.
    """
    # Group all evidence by date
    snippets = evaluation.get("all_evidence_snippets", [])

    days: Dict[str, List[Dict]] = {}
    for s in snippets:
        ts = s.get("timestamp", "")
        date_key = ts[:10] if len(ts) >= 10 else "Unknown Date"
        if date_key not in days:
            days[date_key] = []
        days[date_key].append(s)

    if not days:
        return ""

    sorted_days = sorted([d for d in days.keys() if d != "Unknown Date"])

    # Build device timelines from all evidence (need evidence-like objects)
    # Create lightweight evidence proxies for device extraction
    device_evidence = _build_evidence_proxies(snippets)
    device_events = extract_device_events(device_evidence)
    device_timelines = build_device_timelines(device_events)

    lines = []
    lines.append("DAILY NOTES")
    lines.append("")

    for i, date_key in enumerate(sorted_days, 1):
        day_snippets = days[date_key]

        # Categorize by source type
        sources: Dict[str, List[Dict]] = {}
        for s in day_snippets:
            src = s.get("source_type", "UNKNOWN")
            if src not in sources:
                sources[src] = []
            sources[src].append(s)

        lines.append(f"Hospital Day {i} -- {date_key}")
        lines.append("-" * 40)

        # --- Hemodynamics ---
        vitals_evidence = _build_evidence_proxies(day_snippets)
        day_vitals = extract_vitals(vitals_evidence, target_date=date_key)
        vitals_summary = format_vitals_summary(day_vitals)
        lines.append(f"  Hemodynamics: {vitals_summary}")
        lines.append("")

        # --- Labs ---
        if "LAB" in sources:
            lines.append("  Labs:")
            for lab in sources["LAB"][:3]:
                text = clean_evidence_text(lab.get("text", ""), max_length=200)
                if text:
                    lines.append(f"    {text}")
        else:
            lines.append("  Labs: No labs documented this day.")
        lines.append("")

        # --- Devices ---
        active_devices = get_devices_on_date(device_timelines, date_key)
        if active_devices:
            lines.append("  Devices:")
            for tl in active_devices:
                name = tl.device_type
                if tl.device_subtype:
                    name = f"{name} ({tl.device_subtype})"
                if tl.location:
                    name = f"{name} -- {tl.location}"
                # Calculate day of device
                if tl.placed:
                    try:
                        from datetime import datetime
                        placed_dt = datetime.fromisoformat(tl.placed.replace("Z", "+00:00"))
                        current_dt = datetime.fromisoformat(date_key + "T00:00:00+00:00")
                        device_day = max(1, (current_dt - placed_dt).days + 1)
                        lines.append(f"    - {name} -- Day {device_day}")
                    except (ValueError, TypeError):
                        lines.append(f"    - {name}")
                else:
                    lines.append(f"    - {name}")
                # Check if removed on this day
                if tl.removed and tl.removed[:10] == date_key:
                    lines.append(f"      ** Removed this day **")
        else:
            lines.append("  Devices: No devices documented.")
        lines.append("")

        # --- Imaging ---
        if "IMAGING" in sources or "RADIOLOGY" in sources:
            lines.append("  Imaging:")
            for src in ["IMAGING", "RADIOLOGY"]:
                if src in sources:
                    for img in sources[src][:3]:
                        text = img.get("text", "")
                        injuries = extract_injuries_from_imaging(text)
                        if injuries:
                            for inj in injuries[:3]:
                                lines.append(f"    \"{inj}\"")
                        else:
                            snippet = clean_evidence_text(text, max_length=150)
                            if snippet:
                                lines.append(f"    {snippet}")
        else:
            lines.append("  Imaging: No imaging this day.")
        lines.append("")

        # --- Clinical Notes ---
        has_clinical = False

        # Physician Notes & Consults
        if "PHYSICIAN_NOTE" in sources or "CONSULT_NOTE" in sources:
            lines.append("  Clinical Notes:")
            has_clinical = True
            for src in ["PHYSICIAN_NOTE", "CONSULT_NOTE"]:
                if src in sources:
                    for note in sources[src][:2]:
                        text = clean_evidence_text(note.get("text", ""), max_length=200)
                        if text:
                            src_label = "Consult" if src == "CONSULT_NOTE" else "Physician"
                            lines.append(f"    [{src_label}] {text}")

        # Nursing Assessments
        if "NURSING_NOTE" in sources:
            if not has_clinical:
                lines.append("  Clinical Notes:")
                has_clinical = True
            for note in sources["NURSING_NOTE"][:2]:
                text = clean_evidence_text(note.get("text", ""), max_length=150)
                if text:
                    lines.append(f"    [Nursing] {text}")

        # Therapy Notes (PT/OT)
        therapy_notes = []
        if "PHYSICIAN_NOTE" in sources:
            for note in sources["PHYSICIAN_NOTE"]:
                text = note.get("text", "")
                if any(keyword in text.upper() for keyword in ["PHYSICAL THERAPY", "OCCUPATIONAL THERAPY", "PT ", "OT "]):
                    therapy_notes.append(note)
        if therapy_notes:
            if not has_clinical:
                lines.append("  Clinical Notes:")
                has_clinical = True
            for note in therapy_notes[:2]:
                text = clean_evidence_text(note.get("text", ""), max_length=150)
                if text:
                    lines.append(f"    [Therapy] {text}")

        if not has_clinical:
            lines.append("  Clinical Notes: None documented this day.")
        lines.append("")

        # --- Procedures ---
        if "PROCEDURE" in sources or "OPERATIVE_NOTE" in sources:
            lines.append("  Procedures:")
            for src in ["OPERATIVE_NOTE", "PROCEDURE"]:
                if src in sources:
                    for proc in sources[src]:
                        proc_name = extract_procedure_name(proc.get("text", ""))
                        if proc_name:
                            lines.append(f"    - {proc_name}")
            lines.append("")

        # --- Medications ---
        if "MAR" in sources:
            lines.append("  Medications:")
            for mar in sources["MAR"][:2]:
                text = clean_evidence_text(mar.get("text", ""), max_length=150)
                if text:
                    lines.append(f"    {text}")
            lines.append("")

        lines.append("")

    return "\n".join(lines)


class _EvidenceProxy:
    """Lightweight proxy to make snippet dicts look like evidence objects for extraction functions."""
    def __init__(self, snippet: Dict):
        self.source_type = type('ST', (), {'value': snippet.get('source_type', 'UNKNOWN'), 'name': snippet.get('source_type', 'UNKNOWN')})()
        self.timestamp = snippet.get('timestamp', '')
        self.text = snippet.get('text', '') or snippet.get('text_raw', '')


def _build_evidence_proxies(snippets: List[Dict]) -> List[_EvidenceProxy]:
    """Convert snippet dicts to evidence-like objects for extraction functions."""
    return [_EvidenceProxy(s) for s in snippets]


def generate_protocol_trigger_summary(evaluation: Dict) -> str:
    """
    Generate protocol trigger summary with ✅/❌/⚠️ status indicators.

    Returns formatted text showing which protocols triggered and why.
    """
    results = evaluation.get("results", [])

    triggered = [r for r in results if r["outcome"] != "NOT_TRIGGERED"]

    if not triggered:
        return "No protocols triggered for this patient."

    lines = []
    lines.append("📋 PROTOCOL TRIGGER SUMMARY")
    lines.append("")

    for r in triggered:
        name = r.get("protocol_name", "Unknown")
        outcome = r.get("outcome", "")

        # Status indicator
        if outcome == "COMPLIANT":
            indicator = "✅"
            status = "Documented as active/implemented"
        elif outcome == "NON_COMPLIANT":
            indicator = "❌"
            status = "Not evidenced as compliant"
        elif outcome == "INDETERMINATE":
            indicator = "⚠️"
            status = "Not confirmed / needs supporting data"
        else:
            indicator = "?"
            status = outcome

        lines.append(f"{indicator} {name}")
        lines.append(f"   Protocol status: {status}")

        # Show trigger criteria
        for step in r.get("step_trace", []):
            req_id = step.get("requirement_id", "")
            if "TRIGGER" in req_id:
                passed = step.get("passed", False)
                if passed:
                    lines.append("   Trigger criteria: ✅ Met")
                else:
                    lines.append("   Trigger criteria: ❌ Not met")
                    missing = step.get("missing_data", [])
                    if missing:
                        lines.append(f"   Missing: {', '.join(missing)}")

        lines.append("")

    return "\n".join(lines)


def generate_full_narrative_report(evaluation: Dict, output_path: Optional[Path] = None) -> str:
    """
    Generate complete narrative trauma report.

    Combines trauma summary, daily notes, and protocol summary.
    """
    sections = []

    # Trauma Summary
    sections.append(generate_narrative_trauma_summary(evaluation))
    sections.append("=" * 70)
    sections.append("")

    # Daily Notes
    sections.append(generate_daily_notes(evaluation))
    sections.append("=" * 70)
    sections.append("")

    # Protocol Summary
    sections.append(generate_protocol_trigger_summary(evaluation))

    report = "\n".join(sections)

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report, encoding="utf-8")

    return report
