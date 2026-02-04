#!/usr/bin/env python3
"""
CerebralOS — NTDS Logic Data Models (v1)

Defines the core data structures for the NTDS engine:
- PatientFacts: container for patient data and evidence
- Evidence: a single piece of clinical documentation
- EvidencePointer: reference to source location
- GateResult: evaluation result for a single gate
- EventResult: final evaluation result for an NTDS event
- HardStop: exclusion or early termination record
- Outcome: possible evaluation outcomes
- SourceType: clinical documentation source types

Design:
- Deterministic
- Fail-closed: missing required data → UNABLE_TO_DETERMINE / NOT_EVALUATED
- No invented data
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class Outcome(Enum):
    """Possible outcomes for NTDS event evaluation."""
    YES = "YES"
    NO = "NO"
    EXCLUDED = "EXCLUDED"
    UNABLE_TO_DETERMINE = "UNABLE_TO_DETERMINE"
    NOT_EVALUATED = "NOT_EVALUATED"


class SourceType(Enum):
    """Clinical documentation source types from Epic exports."""
    PHYSICIAN_NOTE = "PHYSICIAN_NOTE"
    CONSULT_NOTE = "CONSULT_NOTE"
    NURSING_NOTE = "NURSING_NOTE"
    IMAGING = "IMAGING"
    LAB = "LAB"
    MAR = "MAR"  # Medication Administration Record
    PROCEDURE = "PROCEDURE"
    DISCHARGE = "DISCHARGE"
    ED_NOTE = "ED_NOTE"
    PROGRESS_NOTE = "PROGRESS_NOTE"
    OPERATIVE_NOTE = "OPERATIVE_NOTE"
    UNKNOWN = "UNKNOWN"


@dataclass
class EvidencePointer:
    """Reference to source location in clinical documentation.
    
    Attributes:
        ref: Dictionary containing source reference (file, line, offset, etc.)
    """
    ref: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Evidence:
    """A single piece of clinical documentation evidence.
    
    Attributes:
        source_type: Type of clinical documentation source
        timestamp: Optional ISO timestamp of the evidence
        text: The text content of the evidence
        pointer: Reference to source location
    """
    source_type: SourceType
    timestamp: Optional[str] = None
    text: Optional[str] = None
    pointer: EvidencePointer = field(default_factory=EvidencePointer)


@dataclass
class HardStop:
    """Represents an exclusion or early termination condition.
    
    Attributes:
        rule_id: Identifier of the rule that triggered the hard stop
        reason: Human-readable explanation
        evidence: Supporting evidence for the hard stop
    """
    rule_id: str
    reason: str
    evidence: List[Evidence] = field(default_factory=list)


@dataclass
class GateResult:
    """Result of evaluating a single gate.
    
    Attributes:
        gate: Identifier of the gate
        passed: Whether the gate passed
        reason: Explanation of the result
        evidence: Supporting evidence
    """
    gate: str
    passed: bool
    reason: str
    evidence: List[Evidence] = field(default_factory=list)


@dataclass
class EventResult:
    """Final result of NTDS event evaluation.
    
    Attributes:
        event_id: NTDS event identifier
        canonical_name: Human-readable event name
        ntds_year: NTDS year (e.g., 2025, 2026)
        outcome: Final outcome of evaluation
        hard_stop: Optional hard stop that terminated evaluation
        gate_trace: List of gate evaluation results
        warnings: Any warnings generated during evaluation
    """
    event_id: int
    canonical_name: str
    ntds_year: int
    outcome: Outcome = Outcome.UNABLE_TO_DETERMINE
    hard_stop: Optional[HardStop] = None
    gate_trace: List[GateResult] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class PatientFacts:
    """Container for patient data and clinical evidence.
    
    Attributes:
        patient_id: De-identified patient identifier (optional)
        facts: Dictionary of extracted facts (arrival_time, query_patterns, etc.)
        evidence: List of clinical documentation evidence
    """
    patient_id: Optional[str] = None
    facts: Optional[Dict[str, Any]] = field(default_factory=dict)
    evidence: List[Evidence] = field(default_factory=list)
