#!/usr/bin/env python3
"""
CerebralOS Findings Domain — Section 9.5 / 10.10.

Output-on-request observational overlays. Never auto-runs, never appears
in run all, must always render last in assembly order.

Governance boundaries (Section 9.5):
- Registry-safe, evidence-anchored, and neutral
- No judgment language
- Use "Unable to determine" when evidence is insufficient
- Must not reinterpret protocol triggers
- Must not modify NTDS values
- Must not retroactively justify or critique narrative domains

Assembly position (Section 10.10):
- Must always render last
- Must never be embedded within other outputs
- Must never appear unless explicitly requested

Invocation (Section 10.11):
- findings
- findings [topic]
- are there any findings
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Finding:
    """A single finding — observational, evidence-anchored, neutral."""
    finding_id: str
    category: str       # e.g., "documentation_gap", "cross_domain", "registry"
    description: str    # Factual, neutral description
    evidence_basis: str  # What evidence supports this observation
    status: str         # "Observed" | "Unable to determine"


@dataclass
class FindingsResult:
    """Result of findings generation."""
    items: List[Finding] = field(default_factory=list)
    topic_filter: Optional[str] = None


# ---------------------------------------------------------------------------
# Finding generators — each produces observational overlays
# ---------------------------------------------------------------------------

def _finding_protocol_noncompliance(evaluation: Dict[str, Any]) -> List[Finding]:
    """Generate findings for non-compliant protocols."""
    findings: List[Finding] = []
    for r in evaluation.get("results", []):
        if r.get("outcome") != "NON_COMPLIANT":
            continue
        protocol_name = r.get("protocol_name", "Unknown")
        steps = r.get("step_trace", [])
        failed_steps = [s for s in steps if not s.get("passed")]
        reasons = "; ".join(s.get("reason", "")[:80] for s in failed_steps[:2])

        findings.append(Finding(
            finding_id=f"protocol_nc_{r.get('protocol_id', 'unknown')}",
            category="protocol",
            description=f"Protocol '{protocol_name}' evaluated as NON_COMPLIANT",
            evidence_basis=reasons or "See protocol step trace",
            status="Observed",
        ))
    return findings


def _finding_protocol_indeterminate(evaluation: Dict[str, Any]) -> List[Finding]:
    """Generate findings for indeterminate protocols (documentation gaps)."""
    findings: List[Finding] = []
    for r in evaluation.get("results", []):
        if r.get("outcome") != "INDETERMINATE":
            continue
        protocol_name = r.get("protocol_name", "Unknown")
        steps = r.get("step_trace", [])
        missing = []
        for s in steps:
            missing.extend(s.get("missing_data", []))

        findings.append(Finding(
            finding_id=f"protocol_ind_{r.get('protocol_id', 'unknown')}",
            category="documentation_gap",
            description=f"Protocol '{protocol_name}' evaluated as INDETERMINATE due to missing documentation",
            evidence_basis=f"Missing elements: {', '.join(missing[:5])}" if missing else "Required documentation not found",
            status="Unable to determine",
        ))
    return findings


def _finding_ntds_events(evaluation: Dict[str, Any]) -> List[Finding]:
    """Generate findings for NTDS hospital events detected (YES)."""
    findings: List[Finding] = []
    for r in evaluation.get("ntds_results", []):
        if r.get("outcome") != "YES":
            continue
        eid = r.get("event_id", 0)
        name = r.get("canonical_name", "Unknown")
        gates = r.get("gate_trace", [])
        passed_gates = [g.get("gate", "") for g in gates if g.get("passed")]

        findings.append(Finding(
            finding_id=f"ntds_yes_{eid:02d}",
            category="registry",
            description=f"NTDS hospital event #{eid:02d} ({name}) detected",
            evidence_basis=f"Passed gates: {', '.join(passed_gates)}" if passed_gates else "See gate trace",
            status="Observed",
        ))
    return findings


def _finding_ntds_unable(evaluation: Dict[str, Any]) -> List[Finding]:
    """Generate findings for NTDS events that could not be determined."""
    findings: List[Finding] = []
    for r in evaluation.get("ntds_results", []):
        if r.get("outcome") != "UNABLE_TO_DETERMINE":
            continue
        eid = r.get("event_id", 0)
        name = r.get("canonical_name", "Unknown")
        gates = r.get("gate_trace", [])
        failed_gates = [g.get("gate", "") for g in gates if not g.get("passed")]

        findings.append(Finding(
            finding_id=f"ntds_unable_{eid:02d}",
            category="documentation_gap",
            description=f"NTDS hospital event #{eid:02d} ({name}) could not be determined",
            evidence_basis=f"Failed gates: {', '.join(failed_gates)}" if failed_gates else "Insufficient documentation",
            status="Unable to determine",
        ))
    return findings


def _finding_evidence_volume(evaluation: Dict[str, Any]) -> List[Finding]:
    """Generate finding about evidence block count for context."""
    block_count = evaluation.get("evidence_blocks", 0)
    if block_count < 3:
        return [Finding(
            finding_id="evidence_low_volume",
            category="documentation_gap",
            description=f"Patient evaluation based on {block_count} evidence block(s)",
            evidence_basis="Low evidence volume may affect determination completeness",
            status="Observed",
        )]
    return []


# All finding generators
_GENERATORS = [
    ("protocol", _finding_protocol_noncompliance),
    ("protocol", _finding_protocol_indeterminate),
    ("ntds", _finding_ntds_events),
    ("ntds", _finding_ntds_unable),
    ("evidence", _finding_evidence_volume),
]


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def generate_findings(
    evaluation: Dict[str, Any],
    topic: Optional[str] = None,
) -> FindingsResult:
    """
    Generate findings from a patient evaluation.

    Per Section 9.5: output-on-request only, registry-safe,
    evidence-anchored, neutral.

    Args:
        evaluation: Patient evaluation dict from batch_eval.evaluate_patient()
        topic: Optional topic filter (e.g., "protocol", "ntds", "documentation")

    Returns:
        FindingsResult with observational findings.
    """
    result = FindingsResult(topic_filter=topic)

    for category, generator in _GENERATORS:
        # Topic filtering
        if topic:
            topic_lower = topic.lower()
            if topic_lower not in category and topic_lower not in "all":
                continue
        try:
            items = generator(evaluation)
            result.items.extend(items)
        except Exception:
            pass  # Finding generation failures are silent

    return result


def format_findings_text(findings: FindingsResult) -> str:
    """Format findings as text for the PI report."""
    if not findings.items:
        return ""

    lines: List[str] = []
    lines.append("=" * 70)
    topic_suffix = f" ({findings.topic_filter})" if findings.topic_filter else ""
    lines.append(f"FINDINGS{topic_suffix}")
    lines.append("=" * 70)
    lines.append("")

    observed = [f for f in findings.items if f.status == "Observed"]
    unable = [f for f in findings.items if f.status == "Unable to determine"]

    if observed:
        lines.append("Observed:")
        for f in observed:
            lines.append(f"  [{f.category}] {f.description}")
            lines.append(f"    Basis: {f.evidence_basis}")
        lines.append("")

    if unable:
        lines.append("Unable to determine:")
        for f in unable:
            lines.append(f"  [{f.category}] {f.description}")
            lines.append(f"    Basis: {f.evidence_basis}")
        lines.append("")

    lines.append("=" * 70)
    return "\n".join(lines)
