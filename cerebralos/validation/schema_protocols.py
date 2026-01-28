"""
CerebralOS Protocol Schema
--------------------------
This file defines the authoritative structure for ALL trauma protocols.

Rules:
- Protocols are DATA, not code.
- No clinical inference lives here.
- No defaults. Missing = invalid.
- Validators fail-closed.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Literal


ProtocolLevel = Literal["HOSPITAL", "TRAUMA", "ICU", "SERVICE"]
RequirementType = Literal["MANDATORY", "CONDITIONAL", "CONTRAINDICATED"]
EvidenceSource = Literal[
    "TRAUMA_H&P",
    "ED_NOTE",
    "ICU_NOTE",
    "OPERATIVE_NOTE",
    "CONSULT_NOTE",
    "NURSING_NOTE",
    "IMAGING",
    "LAB",
    "MAR"
]


@dataclass(frozen=True)
class ProtocolRequirement:
    """
    A single enforceable requirement within a protocol.
    """
    id: str
    description: str
    requirement_type: RequirementType

    trigger_conditions: List[str]
    acceptable_evidence: List[EvidenceSource]

    failure_consequence: str
    notes: Optional[str] = None


@dataclass(frozen=True)
class TraumaProtocol:
    """
    One complete trauma protocol definition.
    """
    protocol_id: str
    name: str
    version: str

    level: ProtocolLevel
    owning_service: str

    inclusion_criteria: List[str]
    exclusion_criteria: List[str]

    requirements: List[ProtocolRequirement]

    references: List[str]

    last_reviewed: str
    status: Literal["ACTIVE", "RETIRED"]
