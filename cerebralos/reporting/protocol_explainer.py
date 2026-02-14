#!/usr/bin/env python3
"""
Protocol trigger explainer - plain language descriptions.

Converts technical pattern keys (e.g., protocol_tbi_gcs_documented@TRAUMA_HP)
into human-readable clinical explanations.
"""
from __future__ import annotations

from typing import Optional


# Pattern key to plain language mapping
_PATTERN_DESCRIPTIONS = {
    # TBI - Traumatic Brain Injury
    "protocol_tbi_gcs_documented": "GCS (Glasgow Coma Scale) documented",
    "protocol_tbi_gcs_8_or_less": "Severe TBI with GCS ≤ 8",
    "protocol_tbi_intubation": "Intubation for TBI documented",
    "protocol_tbi_ct_findings": "CT scan findings documented",
    "protocol_tbi_neuro_exam": "Neurological exam documented",
    "protocol_tbi_repeat_imaging": "Repeat imaging performed",

    # BCVI - Blunt Cerebrovascular Injury
    "protocol_bcvi_neuro_exam": "Neurological exam findings documented",
    "protocol_bcvi_clinical_signs": "Clinical signs of BCVI documented (e.g., neck pain, neurologic deficit)",
    "protocol_bcvi_cta": "CTA (CT angiography) of neck performed",
    "protocol_bcvi_screening_criteria": "BCVI screening criteria met",
    "protocol_bcvi_treatment": "BCVI treatment plan documented",

    # Geriatric
    "protocol_geriatric_age_65_plus": "Patient age ≥ 65 years",
    "protocol_geriatric_medical_vulnerability": "Medical vulnerability factors documented (anticoagulation, comorbidities)",
    "protocol_geriatric_frailty_assessment": "Frailty assessment performed",
    "protocol_geriatric_functional_status": "Pre-injury functional status documented",
    "protocol_geriatric_cognitive_assessment": "Cognitive assessment performed",
    "protocol_geriatric_goals_discussion": "Goals of care discussion documented",

    # Geriatric Hip Fracture
    "protocol_geriatric_hip_surgery": "Hip fracture surgery performed",
    "protocol_geriatric_hip_timing": "Surgery timing documented",
    "protocol_geriatric_hip_dvt_ppx": "DVT prophylaxis initiated",
    "protocol_geriatric_hip_pain_management": "Pain management plan documented",

    # Neurosurgical Emergencies
    "protocol_neurosurg_gcs": "GCS documented",
    "protocol_neurosurg_neuro_exam": "Neurological exam documented",
    "protocol_neurosurg_imaging": "Neuroimaging performed",
    "protocol_neurosurg_consult": "Neurosurgery consultation documented",
    "protocol_neurosurg_intervention": "Neurosurgical intervention performed",

    # Vascular
    "protocol_vascular_bp": "Blood pressure documented",
    "protocol_vascular_angioembolization": "Angiography/embolization performed",
    "protocol_vascular_injury_grade": "Vascular injury grade documented",
    "protocol_vascular_intervention_timing": "Timing of vascular intervention documented",

    # Hypothermia
    "protocol_hypothermia_initial_temp": "Initial temperature documented",
    "protocol_hypothermia_serial_temps": "Serial temperature monitoring documented",
    "protocol_hypothermia_warming": "Active warming measures documented",
    "protocol_hypothermia_prevention": "Hypothermia prevention measures implemented",

    # DVT Prophylaxis
    "protocol_dvt_adult_prophylaxis_ordered": "DVT prophylaxis ordered",
    "protocol_dvt_adult_timing": "Timing of DVT prophylaxis initiation documented",
    "protocol_dvt_adult_contraindications": "Contraindications to DVT prophylaxis assessed",
    "protocol_dvt_adult_type": "Type of DVT prophylaxis documented (pharmacologic/mechanical)",

    # Rib Fractures
    "protocol_rib_pain_assessment": "Pain assessment documented",
    "protocol_rib_analgesia": "Analgesia plan documented",
    "protocol_rib_epidural": "Epidural analgesia considered/documented",
    "protocol_rib_incentive_spirometry": "Incentive spirometry ordered",
    "protocol_rib_pulmonary_hygiene": "Pulmonary hygiene measures documented",

    # Solid Organ Injuries
    "protocol_solid_organ_imaging": "Imaging of solid organ injury",
    "protocol_solid_organ_grade": "Injury grade documented",
    "protocol_solid_organ_hemodynamics": "Hemodynamic status documented",
    "protocol_solid_organ_intervention": "Intervention (operative/angioembolization) documented",
    "protocol_solid_organ_serial_exams": "Serial abdominal exams documented",

    # Spinal
    "protocol_spinal_clearance_imaging": "Spinal imaging performed",
    "protocol_spinal_clearance_exam": "Spinal exam documented",
    "protocol_spinal_clearance_criteria": "Spinal clearance criteria applied",
    "protocol_spinal_injury_neuro_exam": "Neurological exam for spinal injury",
    "protocol_spinal_injury_mri": "MRI for spinal injury",

    # Pelvic Fractures
    "protocol_pelvic_imaging": "Pelvic imaging performed",
    "protocol_pelvic_hemodynamics": "Hemodynamic status documented",
    "protocol_pelvic_stabilization": "Pelvic stabilization performed",
    "protocol_pelvic_angioembolization": "Angioembolization considered/performed",

    # Blood Products
    "protocol_blood_massive_transfusion": "Massive transfusion protocol activation",
    "protocol_blood_products_ratio": "Blood product ratio documented (PRBC:FFP:PLT)",
    "protocol_blood_lactate": "Serial lactate measurements",
    "protocol_blood_coagulation": "Coagulation studies documented",

    # Base Deficit
    "protocol_base_deficit_initial": "Initial base deficit documented",
    "protocol_base_deficit_serial": "Serial base deficit measurements",
    "protocol_base_deficit_trend": "Base deficit trend tracked",

    # Penetrating Trauma
    "protocol_penetrating_mechanism": "Mechanism of injury documented",
    "protocol_penetrating_wound_location": "Wound location documented",
    "protocol_penetrating_hemodynamics": "Hemodynamic status documented",
    "protocol_penetrating_imaging": "Imaging performed",
    "protocol_penetrating_operative": "Operative intervention documented",

    # Mental Health & SBIRT
    "protocol_sbirt_screening": "Alcohol/drug screening performed",
    "protocol_sbirt_intervention": "Brief intervention documented",
    "protocol_sbirt_referral": "Referral to treatment documented",
    "protocol_mental_health_screening": "Mental health screening performed",
    "protocol_mental_health_referral": "Mental health referral documented",

    # Obstetric Trauma
    "protocol_obstetric_gestational_age": "Gestational age documented",
    "protocol_obstetric_fetal_monitoring": "Fetal monitoring performed",
    "protocol_obstetric_ob_consult": "OB/GYN consultation documented",

    # Pediatric
    "protocol_nat_assessment": "Non-accidental trauma assessment performed",
    "protocol_nat_social_work": "Social work consultation documented",
    "protocol_nat_reporting": "Mandatory reporting completed",
}


def explain_pattern_key(pattern_key: str) -> str:
    """
    Convert technical pattern key to plain language description.

    Args:
        pattern_key: Technical key like "protocol_tbi_gcs_documented@TRAUMA_HP"

    Returns:
        Human-readable description
    """
    # Strip source type suffix if present (e.g., @TRAUMA_HP, @LAB)
    base_key = pattern_key.split("@")[0]

    # Look up in mapping
    if base_key in _PATTERN_DESCRIPTIONS:
        description = _PATTERN_DESCRIPTIONS[base_key]

        # If there was a source type, append it
        if "@" in pattern_key:
            source_type = pattern_key.split("@")[1]
            source_display = _format_source_type(source_type)
            return f"{description} (in {source_display})"

        return description

    # Fallback: make a reasonable guess from the key name
    return _guess_description_from_key(base_key)


def _format_source_type(source_type: str) -> str:
    """Format source type for display."""
    source_map = {
        "TRAUMA_HP": "Trauma H&P",
        "PHYSICIAN_NOTE": "physician notes",
        "NURSING_NOTE": "nursing notes",
        "OPERATIVE_NOTE": "operative notes",
        "PROCEDURE": "procedure notes",
        "LAB": "lab results",
        "IMAGING": "imaging reports",
        "MAR": "medication records",
        "VITAL_SIGNS": "vital signs",
        "DISCHARGE": "discharge summary",
    }
    return source_map.get(source_type, source_type.replace("_", " ").lower())


def _guess_description_from_key(key: str) -> str:
    """
    Make a reasonable guess at description from pattern key structure.

    Handles keys like: protocol_<protocol>_<concept>
    """
    # Remove protocol_ prefix
    if key.startswith("protocol_"):
        key = key[9:]

    # Split by underscores and capitalize
    parts = key.split("_")

    # Common abbreviations to uppercase
    uppercase_terms = {"gcs", "cta", "mri", "ct", "dvt", "nat", "sbirt", "ob"}
    formatted_parts = []
    for part in parts:
        if part in uppercase_terms:
            formatted_parts.append(part.upper())
        else:
            formatted_parts.append(part.capitalize())

    description = " ".join(formatted_parts)

    # Add "documented" if it doesn't end with a verb
    if not any(description.endswith(suffix) for suffix in [
        "documented", "performed", "ordered", "assessed", "initiated",
        "considered", "completed", "applied", "tracked", "met"
    ]):
        description += " documented"

    return description


def explain_requirement(requirement_id: str) -> str:
    """
    Explain what a protocol requirement means.

    Args:
        requirement_id: Like "REQ_TRIGGER_CRITERIA", "REQ_REQUIRED_DATA_ELEMENTS"

    Returns:
        Plain language explanation
    """
    req_map = {
        "REQ_TRIGGER_CRITERIA": "Protocol Trigger",
        "REQ_REQUIRED_DATA_ELEMENTS": "Required Documentation",
        "REQ_TIMELY_INTERVENTION": "Timely Intervention",
        "REQ_APPROPRIATE_CARE": "Appropriate Care",
        "REQ_CONSULTATION": "Consultation Required",
        "REQ_IMAGING": "Imaging Required",
        "REQ_MONITORING": "Monitoring Required",
        "REQ_PREVENTION": "Prevention Measures",
        "REQ_FOLLOW_UP": "Follow-up Required",
    }

    return req_map.get(requirement_id, requirement_id.replace("REQ_", "").replace("_", " ").title())
