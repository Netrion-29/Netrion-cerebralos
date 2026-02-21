#!/usr/bin/env python3
"""
CerebralOS Opportunity Flags Domain — Section 28.

Advisory-only domain that surfaces observable documentation gaps and
structural inconsistencies for operator awareness. Strictly non-evaluative,
non-gating, non-determinative.

Governance boundaries (Section 28):
- Disabled by default — renders only when explicitly enabled
- Must never auto-run, be implied, or persist across commands
- Assembly position: after Orders Presence Checklist, before Findings
- Must not reference any other domain's output
- Must not assert compliance, deficiency, quality, or safety
- Language: neutral, factual, source-anchored, non-judgmental
- Standardized expression: "Opportunity identified: [factual condition]"

Prohibited (Section 28.6):
- Declaring compliance or non-compliance
- Implying care adequacy or inadequacy
- Suggesting corrective action
- Predicting Findings
- Using evaluative verbs or normative language
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class OpportunityFlag:
    """A single opportunity flag item."""
    flag_id: str
    description: str  # Standardized: "Opportunity identified: [factual condition]"


@dataclass
class OpportunityFlagsResult:
    """Result of opportunity flags evaluation."""
    enabled: bool
    items: List[OpportunityFlag] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Flag definitions — observable documentation patterns
# ---------------------------------------------------------------------------
# Each definition: (flag_id, condition_description, detection_function_name)
# Detection functions check for observable gaps — never evaluate quality.

def _check_dvt_prophylaxis_gap(evaluation: Dict[str, Any]) -> Optional[str]:
    """Check if DVT prophylaxis documentation is absent for multi-day stay."""
    snippets = evaluation.get("all_evidence_snippets", [])
    combined = "\n".join(s.get("text") or s.get("text_raw") or "" for s in snippets)

    # Only flag for multi-day stays (discharge present implies > same-day)
    if not evaluation.get("has_discharge", False):
        return None

    dvt_patterns = [
        r"\bheparin\b", r"\benoxaparin\b", r"\blovenox\b",
        r"\bSCD\b", r"\bsequential\s+compression\b",
        r"\bDVT\s+(?:ppx|prophylaxis)\b", r"\bVTE\s+(?:ppx|prophylaxis)\b",
    ]
    for pat in dvt_patterns:
        if re.search(pat, combined, re.IGNORECASE):
            return None  # Found — no flag

    return "DVT/VTE prophylaxis not documented in available records"


def _check_tetanus_gap(evaluation: Dict[str, Any]) -> Optional[str]:
    """Check if tetanus status is absent when open wounds are documented."""
    snippets = evaluation.get("all_evidence_snippets", [])
    combined = "\n".join(s.get("text") or s.get("text_raw") or "" for s in snippets)

    # Only relevant if open wounds present
    wound_patterns = [
        r"\blaceration\b", r"\bopen\s+(?:wound|fracture)\b",
        r"\bpenetrating\b", r"\bstab\b", r"\bGSW\b", r"\babrasion\b",
    ]
    has_wound = any(re.search(p, combined, re.IGNORECASE) for p in wound_patterns)
    if not has_wound:
        return None

    tetanus_patterns = [
        r"\btetanus\b", r"\bTdap\b", r"\bTd\s+(?:vaccine|immunization|shot)\b",
    ]
    for pat in tetanus_patterns:
        if re.search(pat, combined, re.IGNORECASE):
            return None  # Found — no flag

    return "Tetanus prophylaxis status not documented with open wound present"


def _check_anticoagulation_status(evaluation: Dict[str, Any]) -> Optional[str]:
    """Check if home anticoagulation status is documented."""
    snippets = evaluation.get("all_evidence_snippets", [])
    combined = "\n".join(s.get("text") or s.get("text_raw") or "" for s in snippets)

    anticoag_patterns = [
        r"\banticoagul\b", r"\bblood\s+thinner\b",
        r"\bwarfarin\b", r"\bcoumadin\b", r"\beliquis\b", r"\bapixaban\b",
        r"\bxarelto\b", r"\brivaroxaban\b", r"\bpradaxa\b", r"\bdabigatran\b",
        r"\bnot\s+on\s+(?:any\s+)?(?:blood\s+thinner|anticoagul)\b",
        r"\bno\s+(?:blood\s+thinner|anticoagul)\b",
        r"\bdenies\s+(?:blood\s+thinner|anticoagul)\b",
    ]
    for pat in anticoag_patterns:
        if re.search(pat, combined, re.IGNORECASE):
            return None  # Found — no flag

    return "Home anticoagulation status not documented in available records"


def _check_allergy_documentation(evaluation: Dict[str, Any]) -> Optional[str]:
    """Check if allergy documentation is present."""
    snippets = evaluation.get("all_evidence_snippets", [])
    combined = "\n".join(s.get("text") or s.get("text_raw") or "" for s in snippets)

    allergy_patterns = [
        r"\ballergi\b", r"\bNKDA\b", r"\bno\s+known\s+(?:drug\s+)?allergi\b",
        r"\ballergy\s*:", r"\ballergi\b",
    ]
    for pat in allergy_patterns:
        if re.search(pat, combined, re.IGNORECASE):
            return None  # Found — no flag

    return "Allergy documentation not found in available records"


def _check_pain_reassessment(evaluation: Dict[str, Any]) -> Optional[str]:
    """Check if pain reassessment is documented after pain management."""
    snippets = evaluation.get("all_evidence_snippets", [])
    combined = "\n".join(s.get("text") or s.get("text_raw") or "" for s in snippets)

    # Only relevant if pain was treated
    pain_med_patterns = [
        r"\bmorphine\b", r"\bfentanyl\b", r"\bhydromorphone\b",
        r"\bdilaudid\b", r"\boxycodone\b",
    ]
    had_pain_med = any(re.search(p, combined, re.IGNORECASE) for p in pain_med_patterns)
    if not had_pain_med:
        return None

    reassess_patterns = [
        r"\bpain\s+reassess\b", r"\bpain\s+re-?assess\b",
        r"\bpain\s+score\s+(?:after|post|follow)\b",
        r"\bpain\s+(?:improved|better|worse|unchanged)\s+(?:after|post|following)\b",
    ]
    for pat in reassess_patterns:
        if re.search(pat, combined, re.IGNORECASE):
            return None  # Found — no flag

    return "Pain reassessment documentation not found after opioid administration"


def _check_discharge_instructions(evaluation: Dict[str, Any]) -> Optional[str]:
    """Check if discharge instructions are documented for discharged patients."""
    if not evaluation.get("has_discharge", False):
        return None

    snippets = evaluation.get("all_evidence_snippets", [])
    combined = "\n".join(s.get("text") or s.get("text_raw") or "" for s in snippets)

    instruction_patterns = [
        r"\bdischarge\s+instruction\b", r"\breturn\s+precaution\b",
        r"\bfollow[\s-]up\b", r"\breturn\s+to\s+(?:ED|ER|emergency)\b",
        r"\bfollow\s+up\s+(?:with|appointment)\b",
    ]
    for pat in instruction_patterns:
        if re.search(pat, combined, re.IGNORECASE):
            return None  # Found — no flag

    return "Discharge instructions not documented in available records"


def _check_fall_risk_assessment(evaluation: Dict[str, Any]) -> Optional[str]:
    """Check if fall risk assessment is documented for elderly trauma patients."""
    snippets = evaluation.get("all_evidence_snippets", [])
    combined = "\n".join(s.get("text") or s.get("text_raw") or "" for s in snippets)

    # Only relevant for geriatric patients (age >= 65)
    age_match = re.search(r"\b(\d+)\s*[-\s]?(?:year|y/?o|yr)", combined, re.IGNORECASE)
    if not age_match:
        return None
    try:
        age = int(age_match.group(1))
    except ValueError:
        return None
    if age < 65:
        return None

    fall_patterns = [
        r"\bfall\s+risk\b", r"\bMorse\s+fall\b", r"\bfall\s+(?:assess|screen)\b",
        r"\bfall\s+precaution\b",
    ]
    for pat in fall_patterns:
        if re.search(pat, combined, re.IGNORECASE):
            return None  # Found — no flag

    return "Fall risk assessment not documented for patient aged 65+"


# All flag detectors
_FLAG_DETECTORS = [
    ("dvt_prophylaxis_gap", _check_dvt_prophylaxis_gap),
    ("tetanus_gap", _check_tetanus_gap),
    ("anticoagulation_status", _check_anticoagulation_status),
    ("allergy_documentation", _check_allergy_documentation),
    ("pain_reassessment", _check_pain_reassessment),
    ("discharge_instructions", _check_discharge_instructions),
    ("fall_risk_assessment", _check_fall_risk_assessment),
]


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def evaluate_opportunity_flags(
    evaluation: Dict[str, Any],
    enabled: bool = False,
) -> OpportunityFlagsResult:
    """
    Evaluate opportunity flags for a patient.

    Per Section 28.3: flags are only generated when explicitly enabled.
    When disabled, returns an empty result — their absence must not be
    noted, explained, or implied.

    Args:
        evaluation: Patient evaluation dict from batch_eval.evaluate_patient()
        enabled: Must be True to generate flags. Defaults to False (disabled).

    Returns:
        OpportunityFlagsResult with flags (empty if not enabled).
    """
    result = OpportunityFlagsResult(enabled=enabled)

    if not enabled:
        return result

    for flag_id, detector in _FLAG_DETECTORS:
        try:
            description = detector(evaluation)
            if description:
                result.items.append(OpportunityFlag(
                    flag_id=flag_id,
                    # Per Section 28.7A: standardized expression
                    description=f"Opportunity identified: {description}",
                ))
        except Exception:
            pass  # Flag detection failures are silent per Section 28.9

    return result


def format_opportunity_flags_text(flags: OpportunityFlagsResult) -> str:
    """Format opportunity flags as text for the PI report."""
    if not flags.enabled or not flags.items:
        return ""

    lines: List[str] = []
    lines.append("=" * 70)
    lines.append("OPPORTUNITY FLAGS (advisory only)")
    lines.append("=" * 70)

    for item in flags.items:
        lines.append(f"  {item.description}")

    lines.append("")
    return "\n".join(lines)
