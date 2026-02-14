#!/usr/bin/env python3
"""
ACS VRC Medical Record Injury Category Classifier.

Evaluates each patient against the American College of Surgeons
Verification Review Consultation Medical Record Injury Categories.
Uses available clinical documentation to determine if the patient
qualifies for each category.

Status values:
  YES     — evidence clearly supports this category
  NO      — evidence clearly rules it out
  POSSIBLE — some supporting evidence but missing a key data point
  UNABLE  — not enough data to evaluate
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Category definitions
# ---------------------------------------------------------------------------

_VRC_CATEGORIES = [
    # Neurosurgical Injuries
    {
        "id": "NEURO_EPIDURAL_SUBDURAL_TO_OR",
        "group": "Neurosurgical Injuries",
        "description": "Epidural/subdural hematoma taken to operating room",
        "detect_fn": "_check_neuro_hematoma_or",
    },
    {
        "id": "NEURO_SEVERE_TBI_ICU",
        "group": "Neurosurgical Injuries",
        "description": "Severe TBI (GCS <= 8) admitted to ICU",
        "detect_fn": "_check_severe_tbi_icu",
    },
    {
        "id": "NEURO_SPINAL_CORD_DEFICIT",
        "group": "Neurosurgical Injuries",
        "description": "Spinal cord injury with neurologic deficit",
        "detect_fn": "_check_spinal_cord",
    },
    # Orthopaedic Injuries
    {
        "id": "ORTHO_AMPUTATION",
        "group": "Orthopaedic Injuries",
        "description": "Any amputations excluding digits",
        "detect_fn": "_check_amputation",
    },
    {
        "id": "ORTHO_ACETABULAR_PELVIC",
        "group": "Orthopaedic Injuries",
        "description": "Acetabular/pelvic fractures requiring embolization, transfusion, or surgery/ORIF",
        "detect_fn": "_check_acetabular_pelvic",
    },
    {
        "id": "ORTHO_OPEN_FEMUR_TIBIA",
        "group": "Orthopaedic Injuries",
        "description": "Open femur or tibia fractures",
        "detect_fn": "_check_open_femur_tibia",
    },
    # Abdominal & Thoracic Injuries
    {
        "id": "ABDTHOR_THORACIC_CARDIAC",
        "group": "Abdominal & Thoracic Injuries",
        "description": "Thoracic/cardiac injuries (incl. aortic), AIS >= 3 or requiring intervention",
        "detect_fn": "_check_thoracic_cardiac",
    },
    {
        "id": "ABDTHOR_SOLID_ORGAN",
        "group": "Abdominal & Thoracic Injuries",
        "description": "Solid organ injuries (spleen/liver/kidney/pancreas) >= Grade III or requiring intervention",
        "detect_fn": "_check_solid_organ",
    },
    {
        "id": "ABDTHOR_PENETRATING",
        "group": "Abdominal & Thoracic Injuries",
        "description": "Penetrating neck/torso/proximal extremity trauma, ISS >= 9 or requiring intervention",
        "detect_fn": "_check_penetrating",
    },
    # Non-Surgical Admissions & Transfers
    {
        "id": "NONSURG_ISS9",
        "group": "Non-Surgical Admissions & Transfers",
        "description": "Patients admitted to non-surgical services with ISS >= 9",
        "detect_fn": "_check_nonsurg_iss9",
    },
    {
        "id": "NONSURG_GERIATRIC_HIP",
        "group": "Non-Surgical Admissions & Transfers",
        "description": "Non-surgical geriatric hip fractures with ISS >= 9",
        "detect_fn": "_check_geriatric_hip",
    },
    {
        "id": "NONSURG_TRANSFER_OUT",
        "group": "Non-Surgical Admissions & Transfers",
        "description": "Transfer out for management of acute injury",
        "detect_fn": "_check_transfer_out",
    },
    # Adverse Events
    {
        "id": "ADVERSE_RETURN_SICU_OR",
        "group": "Adverse Events",
        "description": "Unexpected return to SICU/PICU or operating room",
        "detect_fn": "_check_return_sicu_or",
    },
    {
        "id": "ADVERSE_ISS25_SURVIVAL",
        "group": "Adverse Events",
        "description": "ISS > 25 with survival, without severe TBI (Head AIS < 3)",
        "detect_fn": "_check_iss25_survival",
    },
    # Massive Transfusion Protocol
    {
        "id": "MTP_ACTIVATED",
        "group": "Massive Transfusion Protocol",
        "description": "MTP activation criteria, timing of hemorrhage control",
        "detect_fn": "_check_mtp",
    },
    # Hospice
    {
        "id": "HOSPICE",
        "group": "Hospice",
        "description": "Care provided up to time of transfer for hospice",
        "detect_fn": "_check_hospice",
    },
    # Deaths
    {
        "id": "DEATH",
        "group": "Deaths",
        "description": "Mortality (with or without opportunity for improvement)",
        "detect_fn": "_check_death",
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _all_text(snippets: List[Dict]) -> str:
    """Combine all evidence text into one searchable string, lowered."""
    parts = []
    for s in snippets:
        t = s.get("text") or ""
        if t:
            parts.append(t)
    return "\n".join(parts).lower()


def _snippets_matching(snippets: List[Dict], pattern: re.Pattern) -> List[Dict]:
    """Return snippets whose text matches the pattern."""
    matches = []
    for s in snippets:
        t = (s.get("text") or "").lower()
        if pattern.search(t):
            matches.append(s)
    return matches


def _extract_gcs(snippets: List[Dict]) -> Optional[int]:
    """Extract the lowest GCS value from evidence blocks."""
    gcs_pattern = re.compile(r'\bgcs\s*(?:of|:|\s)?\s*(\d{1,2})\b', re.IGNORECASE)
    values = []
    for s in snippets:
        t = s.get("text") or ""
        for m in gcs_pattern.finditer(t):
            val = int(m.group(1))
            if 3 <= val <= 15:
                values.append(val)
    return min(values) if values else None


def _extract_age(evaluation: Dict) -> Optional[int]:
    """Try to extract patient age from DOB or evidence."""
    dob = evaluation.get("dob", "")
    if dob:
        # Try to parse DOB and compute age
        import re as _re
        m = _re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})', dob)
        if m:
            from datetime import datetime
            try:
                birth = datetime(int(m.group(3)), int(m.group(1)), int(m.group(2)))
                age = (datetime.now() - birth).days // 365
                return age
            except (ValueError, OverflowError):
                pass
    return None


def _has_or_evidence(snippets: List[Dict]) -> bool:
    """Check for operating room evidence."""
    or_pat = re.compile(r'\b(?:operating room|taken to or\b|brought to or\b|operative|surgery performed|surgical intervention)', re.IGNORECASE)
    return bool(_snippets_matching(snippets, or_pat))


def _has_icu_evidence(snippets: List[Dict]) -> bool:
    """Check for ICU admission evidence."""
    icu_pat = re.compile(r'\b(?:admitted to icu|icu admission|sicu|micu|picu|transferred to icu|intensive care unit)', re.IGNORECASE)
    return bool(_snippets_matching(snippets, icu_pat))


def _has_surgical_evidence(snippets: List[Dict]) -> bool:
    """Check for any surgical procedure performed."""
    surg_pat = re.compile(r'\b(?:surgery|surgical|operative|orif|arthroplasty|fixation|reduction|laparotomy|thoracotomy|craniotomy)', re.IGNORECASE)
    return bool(_snippets_matching(snippets, surg_pat))


# ---------------------------------------------------------------------------
# Detection functions
# ---------------------------------------------------------------------------

def _check_neuro_hematoma_or(snippets: List[Dict], evaluation: Dict) -> Dict:
    hematoma_pat = re.compile(r'\b(?:epidural|subdural)\s*(?:hematoma|hemorrhage|bleed)', re.IGNORECASE)
    craniotomy_pat = re.compile(r'\b(?:craniotomy|craniectomy|hematoma evacuation|burr hole)', re.IGNORECASE)
    hematoma_ev = _snippets_matching(snippets, hematoma_pat)
    craniotomy_ev = _snippets_matching(snippets, craniotomy_pat)
    if hematoma_ev and (craniotomy_ev or _has_or_evidence(snippets)):
        return {"status": "YES", "reason": "Epidural/subdural hematoma with OR intervention documented",
                "evidence_snippets": (hematoma_ev + craniotomy_ev)[:3]}
    if hematoma_ev:
        return {"status": "POSSIBLE", "reason": "Epidural/subdural hematoma documented, OR intervention unclear",
                "evidence_snippets": hematoma_ev[:2]}
    return {"status": "NO", "reason": "No epidural/subdural hematoma documented", "evidence_snippets": []}


def _check_severe_tbi_icu(snippets: List[Dict], evaluation: Dict) -> Dict:
    gcs = _extract_gcs(snippets)
    has_icu = _has_icu_evidence(snippets)
    if gcs is not None and gcs <= 8 and has_icu:
        return {"status": "YES", "reason": f"GCS {gcs} with ICU admission", "evidence_snippets": []}
    if gcs is not None and gcs <= 8:
        return {"status": "POSSIBLE", "reason": f"GCS {gcs} documented, ICU admission unclear",
                "evidence_snippets": []}
    if gcs is not None and gcs > 8:
        return {"status": "NO", "reason": f"GCS {gcs} (> 8)", "evidence_snippets": []}
    # Check for TBI language without GCS
    tbi_pat = re.compile(r'\b(?:traumatic brain injury|tbi|severe head injury|intracranial hemorrhage)', re.IGNORECASE)
    if _snippets_matching(snippets, tbi_pat) and has_icu:
        return {"status": "POSSIBLE", "reason": "TBI + ICU documented but GCS value not found",
                "evidence_snippets": _snippets_matching(snippets, tbi_pat)[:2]}
    return {"status": "NO", "reason": "No severe TBI indicators", "evidence_snippets": []}


def _check_spinal_cord(snippets: List[Dict], evaluation: Dict) -> Dict:
    sci_pat = re.compile(r'\b(?:spinal cord injury|paraplegia|quadriplegia|tetraplegia|neurologic deficit|cord compression|myelopathy)', re.IGNORECASE)
    matches = _snippets_matching(snippets, sci_pat)
    if matches:
        return {"status": "YES", "reason": "Spinal cord injury with neurologic deficit documented",
                "evidence_snippets": matches[:3]}
    return {"status": "NO", "reason": "No spinal cord injury documented", "evidence_snippets": []}


def _check_amputation(snippets: List[Dict], evaluation: Dict) -> Dict:
    amp_pat = re.compile(r'\b(?:amputation|amputated)\b', re.IGNORECASE)
    digit_pat = re.compile(r'\b(?:digit|finger|toe|fingertip)\b', re.IGNORECASE)
    matches = _snippets_matching(snippets, amp_pat)
    if matches:
        # Exclude digit-only amputations
        non_digit = [s for s in matches if not digit_pat.search((s.get("text") or "").lower())]
        if non_digit:
            return {"status": "YES", "reason": "Amputation (non-digit) documented",
                    "evidence_snippets": non_digit[:2]}
        return {"status": "NO", "reason": "Only digit amputation documented", "evidence_snippets": []}
    return {"status": "NO", "reason": "No amputation documented", "evidence_snippets": []}


def _check_acetabular_pelvic(snippets: List[Dict], evaluation: Dict) -> Dict:
    frac_pat = re.compile(r'\b(?:acetabul(?:ar|um)|pelvic|pelvis)\s*(?:fracture|fx)', re.IGNORECASE)
    interv_pat = re.compile(r'\b(?:embolization|transfusion|orif|open reduction|internal fixation|surgery)', re.IGNORECASE)
    frac_ev = _snippets_matching(snippets, frac_pat)
    interv_ev = _snippets_matching(snippets, interv_pat)
    if frac_ev and interv_ev:
        return {"status": "YES", "reason": "Acetabular/pelvic fracture with intervention",
                "evidence_snippets": (frac_ev + interv_ev)[:3]}
    if frac_ev:
        return {"status": "POSSIBLE", "reason": "Acetabular/pelvic fracture documented, intervention unclear",
                "evidence_snippets": frac_ev[:2]}
    return {"status": "NO", "reason": "No acetabular/pelvic fracture documented", "evidence_snippets": []}


def _check_open_femur_tibia(snippets: List[Dict], evaluation: Dict) -> Dict:
    open_frac_pat = re.compile(r'\bopen\s*(?:fracture|fx)\b.*\b(?:femur|femoral|tibia|tibial)\b', re.IGNORECASE)
    alt_pat = re.compile(r'\b(?:femur|femoral|tibia|tibial)\b.*\bopen\s*(?:fracture|fx)\b', re.IGNORECASE)
    matches = _snippets_matching(snippets, open_frac_pat) + _snippets_matching(snippets, alt_pat)
    if matches:
        return {"status": "YES", "reason": "Open femur/tibia fracture documented",
                "evidence_snippets": matches[:2]}
    # Check for femur/tibia fracture without "open" qualifier
    frac_pat = re.compile(r'\b(?:femur|femoral|tibia|tibial)\s*(?:fracture|fx)', re.IGNORECASE)
    frac_ev = _snippets_matching(snippets, frac_pat)
    if frac_ev:
        return {"status": "POSSIBLE", "reason": "Femur/tibia fracture documented, open/closed not specified",
                "evidence_snippets": frac_ev[:2]}
    return {"status": "NO", "reason": "No femur/tibia fracture documented", "evidence_snippets": []}


def _check_thoracic_cardiac(snippets: List[Dict], evaluation: Dict) -> Dict:
    thoracic_pat = re.compile(r'\b(?:aortic\s*(?:injury|dissection|transection|tear|rupture)|cardiac\s*injury|thoracotomy|thoracic\s*(?:injury|trauma)|hemothorax|pneumothorax|chest tube|cardiac tamponade|pericardial)', re.IGNORECASE)
    matches = _snippets_matching(snippets, thoracic_pat)
    if matches:
        # Check for intervention
        interv_pat = re.compile(r'\b(?:intubat|thoracotomy|surgery|chest tube|intervention|embolization|repair)', re.IGNORECASE)
        interv_ev = _snippets_matching(snippets, interv_pat)
        if interv_ev:
            return {"status": "YES", "reason": "Thoracic/cardiac injury with intervention documented",
                    "evidence_snippets": (matches + interv_ev)[:3]}
        return {"status": "POSSIBLE", "reason": "Thoracic/cardiac injury documented, AIS/intervention unclear",
                "evidence_snippets": matches[:3]}
    return {"status": "NO", "reason": "No thoracic/cardiac injury documented", "evidence_snippets": []}


def _check_solid_organ(snippets: List[Dict], evaluation: Dict) -> Dict:
    organ_pat = re.compile(r'\b(?:spleen|splenic|liver|hepatic|kidney|renal|pancrea(?:s|tic))\s*(?:injury|laceration|rupture|contusion|hemorrhage|bleed)', re.IGNORECASE)
    grade_pat = re.compile(r'\bgrade\s*(?:III|IV|V|3|4|5)\b', re.IGNORECASE)
    interv_pat = re.compile(r'\b(?:splenectomy|embolization|transfusion|nephrectomy|laparotomy|surgery|operative)', re.IGNORECASE)
    organ_ev = _snippets_matching(snippets, organ_pat)
    if organ_ev:
        grade_ev = _snippets_matching(snippets, grade_pat)
        interv_ev = _snippets_matching(snippets, interv_pat)
        if grade_ev or interv_ev:
            return {"status": "YES", "reason": "Solid organ injury with high grade or intervention",
                    "evidence_snippets": (organ_ev + grade_ev + interv_ev)[:3]}
        return {"status": "POSSIBLE", "reason": "Solid organ injury documented, grade/intervention unclear",
                "evidence_snippets": organ_ev[:2]}
    return {"status": "NO", "reason": "No solid organ injury documented", "evidence_snippets": []}


def _check_penetrating(snippets: List[Dict], evaluation: Dict) -> Dict:
    pen_pat = re.compile(r'\b(?:penetrating|gunshot|gsw|stab|stab wound|ballistic)\b', re.IGNORECASE)
    location_pat = re.compile(r'\b(?:neck|torso|chest|abdom|trunk|proximal extremity|axilla|groin)\b', re.IGNORECASE)
    pen_ev = _snippets_matching(snippets, pen_pat)
    if pen_ev:
        loc_ev = _snippets_matching(snippets, location_pat)
        if loc_ev:
            return {"status": "YES", "reason": "Penetrating trauma to neck/torso documented",
                    "evidence_snippets": (pen_ev + loc_ev)[:3]}
        return {"status": "POSSIBLE", "reason": "Penetrating trauma documented, location unclear",
                "evidence_snippets": pen_ev[:2]}
    return {"status": "NO", "reason": "No penetrating trauma documented", "evidence_snippets": []}


def _check_nonsurg_iss9(snippets: List[Dict], evaluation: Dict) -> Dict:
    has_surg = _has_surgical_evidence(snippets)
    iss_pat = re.compile(r'\biss\s*(?:of|:|\s|=)?\s*(\d+)\b', re.IGNORECASE)
    iss_val = None
    for s in snippets:
        t = s.get("text") or ""
        m = iss_pat.search(t)
        if m:
            iss_val = int(m.group(1))
            break
    if has_surg:
        return {"status": "NO", "reason": "Surgical intervention documented (not non-surgical admission)",
                "evidence_snippets": []}
    if iss_val is not None and iss_val >= 9:
        return {"status": "YES", "reason": f"Non-surgical admission with ISS {iss_val}",
                "evidence_snippets": []}
    if iss_val is not None and iss_val < 9:
        return {"status": "NO", "reason": f"ISS {iss_val} (< 9)", "evidence_snippets": []}
    if not has_surg:
        return {"status": "POSSIBLE", "reason": "No surgical intervention found, ISS not documented",
                "evidence_snippets": []}
    return {"status": "UNABLE", "reason": "Cannot determine surgical status or ISS", "evidence_snippets": []}


def _check_geriatric_hip(snippets: List[Dict], evaluation: Dict) -> Dict:
    age = _extract_age(evaluation)
    hip_pat = re.compile(r'\b(?:hip\s*fracture|femoral\s*neck\s*fracture|intertrochanteric|subtrochanteric)', re.IGNORECASE)
    hip_ev = _snippets_matching(snippets, hip_pat)
    has_surg = _has_surgical_evidence(snippets)
    if age is not None and age >= 65 and hip_ev and not has_surg:
        return {"status": "POSSIBLE", "reason": f"Age {age}, hip fracture, no surgery documented, ISS not verified",
                "evidence_snippets": hip_ev[:2]}
    if hip_ev and not has_surg:
        return {"status": "POSSIBLE", "reason": "Hip fracture, no surgery documented, age/ISS unclear",
                "evidence_snippets": hip_ev[:2]}
    if not hip_ev:
        return {"status": "NO", "reason": "No hip fracture documented", "evidence_snippets": []}
    return {"status": "NO", "reason": "Hip fracture with surgical intervention", "evidence_snippets": []}


def _check_transfer_out(snippets: List[Dict], evaluation: Dict) -> Dict:
    transfer_pat = re.compile(r'\b(?:transfer(?:red)?\s*(?:to|out)|transported to\s*\w+\s*hospital|accept(?:ed)?\s*(?:by|at))', re.IGNORECASE)
    matches = _snippets_matching(snippets, transfer_pat)
    # Check discharge blocks specifically
    discharge_transfer = [s for s in matches if s.get("source_type") == "DISCHARGE"]
    if discharge_transfer:
        return {"status": "YES", "reason": "Transfer out documented in discharge",
                "evidence_snippets": discharge_transfer[:2]}
    if matches:
        return {"status": "POSSIBLE", "reason": "Transfer language found, not in discharge block",
                "evidence_snippets": matches[:2]}
    return {"status": "NO", "reason": "No transfer out documented", "evidence_snippets": []}


def _check_return_sicu_or(snippets: List[Dict], evaluation: Dict) -> Dict:
    return_pat = re.compile(r'\b(?:return(?:ed)?\s*to\s*(?:or|operating room|sicu|icu)|unplanned\s*return|readmit(?:ted)?\s*to\s*(?:icu|sicu)|unexpected\s*return|re-?exploration)', re.IGNORECASE)
    matches = _snippets_matching(snippets, return_pat)
    if matches:
        return {"status": "YES", "reason": "Unexpected return to SICU/OR documented",
                "evidence_snippets": matches[:3]}
    # Check for multiple OR blocks (possible return)
    or_blocks = [s for s in snippets if s.get("source_type") in ("OPERATIVE_NOTE", "PROCEDURE")]
    if len(or_blocks) >= 2:
        return {"status": "POSSIBLE", "reason": f"Multiple operative blocks ({len(or_blocks)}) — possible return to OR",
                "evidence_snippets": or_blocks[:2]}
    return {"status": "NO", "reason": "No return to SICU/OR documented", "evidence_snippets": []}


def _check_iss25_survival(snippets: List[Dict], evaluation: Dict) -> Dict:
    iss_pat = re.compile(r'\biss\s*(?:of|:|\s|=)?\s*(\d+)\b', re.IGNORECASE)
    iss_val = None
    for s in snippets:
        m = iss_pat.search(s.get("text") or "")
        if m:
            iss_val = int(m.group(1))
            break
    has_discharge = evaluation.get("has_discharge", False)
    gcs = _extract_gcs(snippets)
    if iss_val is not None and iss_val > 25 and has_discharge:
        if gcs is not None and gcs <= 8:
            return {"status": "NO", "reason": f"ISS {iss_val} but severe TBI (GCS {gcs})",
                    "evidence_snippets": []}
        return {"status": "YES", "reason": f"ISS {iss_val} with survival, no severe TBI",
                "evidence_snippets": []}
    if iss_val is not None and iss_val <= 25:
        return {"status": "NO", "reason": f"ISS {iss_val} (<= 25)", "evidence_snippets": []}
    return {"status": "UNABLE", "reason": "ISS not documented", "evidence_snippets": []}


def _check_mtp(snippets: List[Dict], evaluation: Dict) -> Dict:
    mtp_pat = re.compile(r'\b(?:massive\s*transfusion|mtp|code\s*crimson|massive\s*hemorrhage\s*protocol)', re.IGNORECASE)
    matches = _snippets_matching(snippets, mtp_pat)
    if matches:
        return {"status": "YES", "reason": "Massive Transfusion Protocol activation documented",
                "evidence_snippets": matches[:3]}
    # Check for high volume transfusion
    transfusion_pat = re.compile(r'\b(?:prbc|packed red blood cells|ffp|plt|cryoprecipitate|blood products)\b', re.IGNORECASE)
    transfusion_ev = _snippets_matching(snippets, transfusion_pat)
    if len(transfusion_ev) >= 3:
        return {"status": "POSSIBLE", "reason": f"Multiple blood product references ({len(transfusion_ev)}) — possible MTP",
                "evidence_snippets": transfusion_ev[:3]}
    return {"status": "NO", "reason": "No MTP activation documented", "evidence_snippets": []}


def _check_hospice(snippets: List[Dict], evaluation: Dict) -> Dict:
    hospice_pat = re.compile(r'\b(?:hospice|comfort\s*care|comfort\s*measures|palliative|withdrawal\s*of\s*care|withdraw\s*care)', re.IGNORECASE)
    matches = _snippets_matching(snippets, hospice_pat)
    if matches:
        return {"status": "YES", "reason": "Hospice/comfort care documented",
                "evidence_snippets": matches[:2]}
    return {"status": "NO", "reason": "No hospice/comfort care documented", "evidence_snippets": []}


def _check_death(snippets: List[Dict], evaluation: Dict) -> Dict:
    death_pat = re.compile(r'\b(?:expired|time of death|pronounced dead|deceased|death|died|tod\s*:|mortality)\b', re.IGNORECASE)
    matches = _snippets_matching(snippets, death_pat)
    if matches:
        return {"status": "YES", "reason": "Mortality documented",
                "evidence_snippets": matches[:3]}
    return {"status": "NO", "reason": "No mortality documented", "evidence_snippets": []}


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_DETECT_FNS = {
    "_check_neuro_hematoma_or": _check_neuro_hematoma_or,
    "_check_severe_tbi_icu": _check_severe_tbi_icu,
    "_check_spinal_cord": _check_spinal_cord,
    "_check_amputation": _check_amputation,
    "_check_acetabular_pelvic": _check_acetabular_pelvic,
    "_check_open_femur_tibia": _check_open_femur_tibia,
    "_check_thoracic_cardiac": _check_thoracic_cardiac,
    "_check_solid_organ": _check_solid_organ,
    "_check_penetrating": _check_penetrating,
    "_check_nonsurg_iss9": _check_nonsurg_iss9,
    "_check_geriatric_hip": _check_geriatric_hip,
    "_check_transfer_out": _check_transfer_out,
    "_check_return_sicu_or": _check_return_sicu_or,
    "_check_iss25_survival": _check_iss25_survival,
    "_check_mtp": _check_mtp,
    "_check_hospice": _check_hospice,
    "_check_death": _check_death,
}


def classify_vrc_categories(
    evaluation: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Classify a patient against all ACS VRC Medical Record Injury Categories.

    Args:
        evaluation: Patient evaluation dict from batch_eval.evaluate_patient()

    Returns:
        List of category result dicts with keys:
            category_id, category_group, description, status, reason, evidence_snippets
    """
    snippets = evaluation.get("all_evidence_snippets", [])
    results = []

    for cat in _VRC_CATEGORIES:
        fn = _DETECT_FNS.get(cat["detect_fn"])
        if fn is None:
            results.append({
                "category_id": cat["id"],
                "category_group": cat["group"],
                "description": cat["description"],
                "status": "UNABLE",
                "reason": "Detection function not found",
                "evidence_snippets": [],
            })
            continue

        result = fn(snippets, evaluation)
        results.append({
            "category_id": cat["id"],
            "category_group": cat["group"],
            "description": cat["description"],
            "status": result["status"],
            "reason": result["reason"],
            "evidence_snippets": result.get("evidence_snippets", []),
        })

    return results
