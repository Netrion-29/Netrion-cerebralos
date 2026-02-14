#!/usr/bin/env python3
"""
Data model classes for the Protocol evaluation pipeline.

This module defines all data structures used in the protocol evaluation engine,
including protocol evidence, step results, and protocol facts.

Mirrors the NTDS model architecture but adapted for protocol compliance evaluation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

# Reuse evidence pointer and hard stop from NTDS model
from cerebralos.ntds_logic.model import EvidencePointer, HardStop


class SourceType(Enum):
    """
    Clinical evidence source types from Epic EHR exports.

    Reuses NTDS source types with protocol-relevant additions.
    """
    TRAUMA_HP = "TRAUMA_HP"
    ED_NOTE = "ED_NOTE"
    PHYSICIAN_NOTE = "PHYSICIAN_NOTE"
    CONSULT_NOTE = "CONSULT_NOTE"
    NURSING_NOTE = "NURSING_NOTE"
    IMAGING = "IMAGING"
    LAB = "LAB"
    MAR = "MAR"  # Medication Administration Record
    OPERATIVE_NOTE = "OPERATIVE_NOTE"
    PROCEDURE = "PROCEDURE"
    DISCHARGE = "DISCHARGE"
    RADIOLOGY = "RADIOLOGY"


class ProtocolOutcome(Enum):
    """
    Protocol compliance evaluation outcomes.

    - COMPLIANT: All requirements met, full protocol adherence
    - NON_COMPLIANT: Protocol applies but requirements failed
    - NOT_TRIGGERED: Protocol doesn't apply to this patient
    - INDETERMINATE: Missing data, cannot determine compliance
    """
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"
    NOT_TRIGGERED = "NOT_TRIGGERED"
    INDETERMINATE = "INDETERMINATE"


class RequirementType(Enum):
    """
    Protocol requirement evaluation modes.

    - MANDATORY: Must be met if protocol applies (e.g., trigger criteria, required data)
    - CONDITIONAL: Only applies in certain scenarios (e.g., timing requirements)
    - CONTRAINDICATED: Safety exclusion (hard-stop if present)
    """
    MANDATORY = "MANDATORY"
    CONDITIONAL = "CONDITIONAL"
    CONTRAINDICATED = "CONTRAINDICATED"


@dataclass
class ProtocolEvidence:
    """
    A single clinical evidence block for protocol evaluation.

    Similar to NTDS Evidence but emphasizes actions/interventions rather than diagnoses.

    Attributes:
        source_type: Clinical documentation source category
        timestamp: Optional timestamp of the clinical action/documentation
        text: Clinical text content (may contain PHI, never committed to Git)
        pointer: Provenance tracking for audit trail
    """
    source_type: SourceType
    timestamp: Optional[str]
    text: Optional[str]
    pointer: EvidencePointer


@dataclass
class MatchDetail:
    """
    Details about a specific pattern match within evidence.

    Tracks which pattern matched, what text was matched, and surrounding context.
    Used to explain WHY a piece of evidence was selected.
    """
    pattern_key: str    # e.g., "protocol_tbi_gate", "geriatric_age_80plus"
    matched_text: str   # The exact text that matched the pattern
    context: str        # Surrounding 200 chars for readability


@dataclass
class StepResult:
    """
    Evaluation result for a single protocol requirement/step.

    Analogous to NTDS GateResult but for protocol requirements (trigger criteria,
    data elements, timing, etc.).

    Attributes:
        requirement_id: Requirement identifier (e.g., REQ_TRIGGER_CRITERIA)
        requirement_type: MANDATORY, CONDITIONAL, or CONTRAINDICATED
        passed: Whether the requirement was satisfied
        reason: Human-readable explanation of the result
        evidence: Supporting clinical evidence (max items per contract)
        missing_data: Specific data elements that were missing (for INDETERMINATE outcomes)
    """
    requirement_id: str
    requirement_type: RequirementType
    passed: bool
    reason: str
    evidence: List[ProtocolEvidence]
    missing_data: List[str] = field(default_factory=list)
    match_details: List[MatchDetail] = field(default_factory=list)


@dataclass
class ProtocolResult:
    """
    Final evaluation result for a protocol.

    Analogous to NTDS EventResult but for protocol compliance evaluation.

    Attributes:
        protocol_id: Unique protocol identifier (e.g., TRAUMATIC_BRAIN_INJURY_MANAGEMENT)
        protocol_name: Human-readable protocol name
        protocol_version: Protocol version string
        outcome: Compliance determination (COMPLIANT/NON_COMPLIANT/NOT_TRIGGERED/INDETERMINATE)
        step_trace: Sequential evaluation trace for all requirements
        hard_stop: Optional contraindication evidence (safety exclusion)
        warnings: Non-fatal issues encountered during evaluation
    """
    protocol_id: str
    protocol_name: str
    protocol_version: str
    outcome: ProtocolOutcome
    step_trace: List[StepResult] = field(default_factory=list)
    hard_stop: Optional[HardStop] = None
    warnings: List[str] = field(default_factory=list)


@dataclass
class ProtocolFacts:
    """
    Patient clinical evidence and metadata for protocol evaluation.

    Analogous to NTDS PatientFacts but emphasizes protocol-relevant actions/orders.

    Attributes:
        evidence: All clinical evidence blocks (actions, orders, vitals, etc.)
        facts: Metadata dictionary containing:
            - action_patterns: Pattern mappings for evidence matching
            - arrival_time: Patient arrival timestamp (for timing validation)
            - patient_id: Patient identifier (never committed to Git)
    """
    evidence: List[ProtocolEvidence]
    facts: Dict[str, Any]
