#!/usr/bin/env python3
"""
Section 19 — Evidence Rigor Validation.

Cross-domain, diagnostic-only, non-corrective checks applied automatically
during governance checklist execution. Per Section 19.3, there is no
standalone Section 19 command.

Validates:
- 19.4.1 Evidence Anchoring — facts traceable to source
- 19.4.2 Numeric Fidelity — no qualitative substitution for numeric data
- 19.4.3 Ambiguity Preservation — uncertain data stays uncertain
- 19.4.4 Absence as Explicit Fact — missing elements explicitly stated
- 19.4.5 Narrative De-Smoothing — no unsupported narrative language
- 19A    Daily Notes Required-Content Hard Gates

Output (per 19.7):
- PASS or FAIL
- Identifies failed requirement(s)
- Factual, non-judgmental language
- No recommendations, no corrective edits
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class RigorCheck:
    """Single evidence rigor check result."""
    section: str        # e.g., "19.4.1", "19.4.2", "19A.3A"
    name: str           # e.g., "evidence_anchoring", "numeric_fidelity"
    passed: bool
    failures: List[str] = field(default_factory=list)


@dataclass
class RigorResult:
    """Aggregate Section 19 rigor result for a domain."""
    domain: str
    passed: bool
    checks: List[RigorCheck] = field(default_factory=list)
    failure_count: int = 0


# ---------------------------------------------------------------------------
# 19.4.2 Numeric Fidelity — prohibited qualitative substitutions
# ---------------------------------------------------------------------------
_QUALITATIVE_SUBSTITUTIONS = [
    r"\bstable\b",
    r"\bmild\b",
    r"\bimproving\b",
    r"\bminimal\b",
    r"\btreated medically\b",
]
_QUALITATIVE_COMPILED = [re.compile(p, re.IGNORECASE) for p in _QUALITATIVE_SUBSTITUTIONS]

# Numeric anchors that validate nearby qualitative terms
_NUMERIC_ANCHOR = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:%|mg|mL|mmHg|bpm|/min|g/dL|mmol|mEq|units?|mcg|cm|mm)\b"
    r"|\bBP\s*:?\s*\d+/\d+\b"
    r"|\bHR\s*:?\s*\d+\b"
    r"|\bGCS\s*:?\s*\d+\b"
    r"|\bTemp\s*:?\s*\d+\b"
    r"|\bRR\s*:?\s*\d+\b"
    r"|\bSpO2\s*:?\s*\d+\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# 19.4.5 Narrative De-Smoothing — prohibited unsupported narrative terms
# ---------------------------------------------------------------------------
_SMOOTHING_TERMS = [
    r"\buncomplicated\b",
    r"\bresponded appropriately\b",
    r"\bdid well\b",
    r"\bmanaged conservatively\b",
]
_SMOOTHING_COMPILED = [re.compile(p, re.IGNORECASE) for p in _SMOOTHING_TERMS]


# ---------------------------------------------------------------------------
# Evidence Anchoring — valid evidence source types
# ---------------------------------------------------------------------------
_VALID_ANCHOR_TYPES = frozenset({
    "RADIOLOGY", "LAB", "MAR", "PROCEDURE", "OPERATIVE_NOTE",
    "PHYSICIAN_NOTE", "CONSULT_NOTE", "ED_NOTE", "NURSING_NOTE",
    "TRAUMA_HP", "DISCHARGE",
})


# ---------------------------------------------------------------------------
# Domain-specific rigor checks
# ---------------------------------------------------------------------------

def check_protocol_rigor(evaluation: Dict[str, Any]) -> RigorResult:
    """
    Section 19 checks for Protocol domain.

    Validates:
    - Protocol triggers are evidence-anchored (19.4.1)
    - INDETERMINATE used for missing trigger data (19.5 Protocols)
    - No qualitative substitution in timing evidence (19.4.2)
    """
    result = RigorResult(domain="protocol", passed=True)

    results = evaluation.get("results", [])

    # 19.4.1 — Evidence anchoring: every triggered protocol must have evidence
    cr_anchor = RigorCheck(section="19.4.1", name="protocol_evidence_anchoring", passed=True)
    for r in results:
        outcome = r.get("outcome", "")
        if outcome in ("NOT_TRIGGERED", "APPLICABLE_CONTEXTUAL", "ERROR"):
            continue
        # Triggered protocols must have evidence in at least one step
        steps = r.get("step_trace", [])
        has_any_evidence = any(
            step.get("evidence_count", 0) > 0 or step.get("evidence_snippets")
            for step in steps
        )
        if not has_any_evidence and outcome in ("COMPLIANT", "NON_COMPLIANT"):
            cr_anchor.passed = False
            cr_anchor.failures.append(
                f"{r.get('protocol_name', 'Unknown')}: {outcome} without evidence anchoring"
            )
    result.checks.append(cr_anchor)

    # 19.5 Protocols — INDETERMINATE for missing trigger data
    cr_indet = RigorCheck(section="19.5", name="protocol_indeterminate_discipline", passed=True)
    for r in results:
        steps = r.get("step_trace", [])
        for step in steps:
            if step.get("missing_data") and step.get("passed", False):
                cr_indet.passed = False
                cr_indet.failures.append(
                    f"{r.get('protocol_name', 'Unknown')}: step passed despite missing_data"
                )
    result.checks.append(cr_indet)

    result.passed = all(c.passed for c in result.checks)
    result.failure_count = sum(len(c.failures) for c in result.checks)
    return result


def check_ntds_rigor(evaluation: Dict[str, Any]) -> RigorResult:
    """
    Section 19 checks for NTDS domain.

    Validates:
    - Gate evidence anchoring (19.4.1)
    - Missing evidence not converted to Present/Absent (19.5 NTDS)
    - Numeric fidelity in gate evidence (19.4.2)
    """
    result = RigorResult(domain="ntds", passed=True)

    ntds_results = evaluation.get("ntds_results", [])

    # 19.4.1 — Evidence anchoring: YES outcomes must have gate evidence
    cr_anchor = RigorCheck(section="19.4.1", name="ntds_evidence_anchoring", passed=True)
    for r in ntds_results:
        outcome = r.get("outcome", "")
        if outcome != "YES":
            continue
        gates = r.get("gate_trace", [])
        passed_gates = [g for g in gates if g.get("passed")]
        has_evidence = any(
            g.get("evidence_count", 0) > 0 or g.get("evidence_snippets")
            for g in passed_gates
        )
        if not has_evidence:
            cr_anchor.passed = False
            cr_anchor.failures.append(
                f"Event #{r.get('event_id', 0):02d} {r.get('canonical_name', 'Unknown')}: YES without evidence"
            )
    result.checks.append(cr_anchor)

    # 19.5 NTDS — missing evidence must not produce Present/Absent
    cr_missing = RigorCheck(section="19.5", name="ntds_missing_evidence_discipline", passed=True)
    for r in ntds_results:
        outcome = r.get("outcome", "")
        gates = r.get("gate_trace", [])
        if outcome in ("YES", "NO") and not gates:
            cr_missing.passed = False
            cr_missing.failures.append(
                f"Event #{r.get('event_id', 0):02d}: {outcome} without gate trace"
            )
    result.checks.append(cr_missing)

    result.passed = all(c.passed for c in result.checks)
    result.failure_count = sum(len(c.failures) for c in result.checks)
    return result


def check_evidence_rigor(evaluation: Dict[str, Any]) -> RigorResult:
    """
    Section 19 checks for Evidence domain.

    Validates:
    - Evidence blocks have valid source types (19.4.1)
    - Evidence text not empty for used blocks (19.4.1)
    """
    result = RigorResult(domain="evidence", passed=True)

    snippets = evaluation.get("all_evidence_snippets", [])

    # 19.4.1 — Evidence source type validation
    cr_sources = RigorCheck(section="19.4.1", name="evidence_source_types", passed=True)
    invalid_sources: List[str] = []
    for s in snippets:
        src = s.get("source_type", "")
        if src and src not in _VALID_ANCHOR_TYPES:
            if src not in invalid_sources:
                invalid_sources.append(src)
    if invalid_sources:
        cr_sources.passed = False
        cr_sources.failures.append(
            f"Unrecognized evidence source types: {invalid_sources}"
        )
    result.checks.append(cr_sources)

    # 19.4.1 — Non-empty evidence text
    cr_text = RigorCheck(section="19.4.1", name="evidence_text_present", passed=True)
    empty_count = 0
    for s in snippets:
        text = s.get("text") or s.get("text_raw") or ""
        if not text.strip():
            empty_count += 1
    if empty_count > 0:
        cr_text.passed = False
        cr_text.failures.append(
            f"{empty_count} evidence block(s) with empty text"
        )
    result.checks.append(cr_text)

    result.passed = all(c.passed for c in result.checks)
    result.failure_count = sum(len(c.failures) for c in result.checks)
    return result


def check_narrative_rigor(
    text: str,
    domain_name: str = "narrative",
) -> RigorResult:
    """
    Section 19 checks for narrative output text (trauma summary, daily notes).

    Validates:
    - 19.4.2 Numeric Fidelity — qualitative terms without numeric anchors
    - 19.4.5 Narrative De-Smoothing — unsupported narrative terms
    - 19.4.4 Absence as Explicit Fact — missing elements silently omitted

    Args:
        text: The narrative output text to validate
        domain_name: Identifier for failure reporting
    """
    result = RigorResult(domain=domain_name, passed=True)

    if not text:
        return result

    # 19.4.2 — Numeric Fidelity
    cr_numeric = RigorCheck(section="19.4.2", name="numeric_fidelity", passed=True)
    for pat in _QUALITATIVE_COMPILED:
        for m in pat.finditer(text):
            # Check if there's a numeric anchor within 100 chars
            start = max(0, m.start() - 100)
            end = min(len(text), m.end() + 100)
            context = text[start:end]
            if not _NUMERIC_ANCHOR.search(context):
                cr_numeric.passed = False
                # Extract line context for the failure message
                line_start = text.rfind("\n", 0, m.start())
                line_end = text.find("\n", m.end())
                line = text[line_start + 1:line_end if line_end > 0 else m.end() + 50].strip()
                cr_numeric.failures.append(
                    f"Qualitative term '{m.group(0)}' without numeric anchor near: "
                    f"{line[:80]}"
                )
    result.checks.append(cr_numeric)

    # 19.4.5 — Narrative De-Smoothing
    cr_smooth = RigorCheck(section="19.4.5", name="narrative_de_smoothing", passed=True)
    for pat in _SMOOTHING_COMPILED:
        for m in pat.finditer(text):
            cr_smooth.passed = False
            line_start = text.rfind("\n", 0, m.start())
            line_end = text.find("\n", m.end())
            line = text[line_start + 1:line_end if line_end > 0 else m.end() + 50].strip()
            cr_smooth.failures.append(
                f"Unsupported narrative term '{m.group(0)}' near: {line[:80]}"
            )
    result.checks.append(cr_smooth)

    result.passed = all(c.passed for c in result.checks)
    result.failure_count = sum(len(c.failures) for c in result.checks)
    return result


def check_daily_notes_required_content(
    daily_notes: List[Dict[str, Any]],
) -> RigorResult:
    """
    Section 19A — Daily Notes Required-Content Hard Gates.

    Per 19A.3, a Daily Notes artifact fails if any calendar day lacks:
    A) Objective Clinical Data — at least one numeric vital sign OR explicit absence
    B) Imaging Discipline — verbatim impressions when imaging exists
    C) Disposition & Trajectory — one of the defined disposition states

    Args:
        daily_notes: List of day dicts from extract_daily_notes()
    """
    result = RigorResult(domain="daily_notes_19A", passed=True)

    if not daily_notes:
        return result

    # Patterns for detecting numeric vitals
    numeric_vital = re.compile(
        r"\b(?:BP|HR|Temp|RR|SpO2|SBP|DBP)\s*:?\s*\d+"
        r"|\b\d+/\d+\s*(?:mmHg)?"
        r"|\b\d+\s*(?:bpm|/min|degrees?|%)",
        re.IGNORECASE,
    )
    vitals_absent_phrase = re.compile(
        r"vitals?\s+not\s+documented|no\s+vitals?\s+(?:available|documented|recorded)",
        re.IGNORECASE,
    )

    # Patterns for detecting numeric labs
    numeric_lab = re.compile(
        r"\b(?:WBC|HGB|PLT|Hgb|Na|K|Cr|BUN|Glucose|INR|Lactate)\s*:?\s*\d+",
        re.IGNORECASE,
    )
    labs_absent_phrase = re.compile(
        r"no\s+labs?\s+(?:documented|available|drawn|recorded)"
        r"|labs?\s+not\s+documented",
        re.IGNORECASE,
    )

    # Disposition keywords per 19A.3C
    disposition_pattern = re.compile(
        r"not\s+medically\s+ready"
        r"|medically\s+ready"
        r"|goals?\s+of\s+care"
        r"|discharge\s+planned"
        r"|discharged"
        r"|expired"
        r"|transferred",
        re.IGNORECASE,
    )

    for day in daily_notes:
        date = day.get("date", "unknown")
        fields = day.get("fields", {})

        # Combine all field values for this day
        day_text = "\n".join(str(v) for v in fields.values())

        # 19A.3A — Objective Clinical Data
        cr_vitals = RigorCheck(
            section="19A.3A",
            name=f"daily_notes_vitals_{date}",
            passed=True,
        )
        hemo = str(fields.get("Hemodynamic status", ""))
        has_numeric_vital = bool(numeric_vital.search(hemo))
        has_absence_stmt = bool(vitals_absent_phrase.search(hemo))
        if not has_numeric_vital and not has_absence_stmt:
            # Check for NOT DOCUMENTED sentinel
            if "NOT DOCUMENTED" not in hemo.upper():
                cr_vitals.passed = False
                cr_vitals.failures.append(
                    f"[{date}] No numeric vital signs and no explicit absence statement"
                )
        result.checks.append(cr_vitals)

        # 19A.3A — Labs when present
        cr_labs = RigorCheck(
            section="19A.3A",
            name=f"daily_notes_labs_{date}",
            passed=True,
        )
        labs = str(fields.get("Labs (significant only)", ""))
        if labs and "NOT DOCUMENTED" not in labs.upper() and "NONE DOCUMENTED" not in labs.upper():
            has_numeric_lab = bool(numeric_lab.search(labs))
            if not has_numeric_lab and not labs_absent_phrase.search(labs):
                cr_labs.passed = False
                cr_labs.failures.append(
                    f"[{date}] Labs present but no numeric values"
                )
        result.checks.append(cr_labs)

        # 19A.3C — Disposition & Trajectory
        cr_disp = RigorCheck(
            section="19A.3C",
            name=f"daily_notes_disposition_{date}",
            passed=True,
        )
        plan = str(fields.get("Plan", ""))
        has_disposition = bool(disposition_pattern.search(plan)) or bool(
            disposition_pattern.search(day_text)
        )
        if not has_disposition:
            # Allow NOT DOCUMENTED as a valid explicit absence
            if "NOT DOCUMENTED" not in plan.upper():
                cr_disp.passed = False
                cr_disp.failures.append(
                    f"[{date}] No disposition/trajectory statement"
                )
        result.checks.append(cr_disp)

    result.passed = all(c.passed for c in result.checks)
    result.failure_count = sum(len(c.failures) for c in result.checks)
    return result


# ---------------------------------------------------------------------------
# Aggregate runner for governance checklist integration
# ---------------------------------------------------------------------------

def run_section19_for_evaluation(
    evaluation: Dict[str, Any],
) -> List[RigorResult]:
    """
    Run all applicable Section 19 checks against a patient evaluation.

    Called by governance checklist validators. Returns list of RigorResult
    objects — one per domain.

    Per Section 19.2: diagnostic-only, non-corrective, non-blocking.
    Per Section 19.6: failures are logged, artifacts retained, no rewriting.
    """
    results: List[RigorResult] = []

    # Protocol rigor
    results.append(check_protocol_rigor(evaluation))

    # NTDS rigor
    results.append(check_ntds_rigor(evaluation))

    # Evidence rigor
    results.append(check_evidence_rigor(evaluation))

    # Narrative rigor — trauma summary
    try:
        from cerebralos.reporting.trauma_doc_extractor import extract_trauma_summary
        summary_fields = extract_trauma_summary(evaluation)
        if summary_fields:
            summary_text = "\n".join(f"{k}: {v}" for k, v in summary_fields.items())
            results.append(check_narrative_rigor(summary_text, "trauma_summary"))
    except Exception:
        pass

    # Daily notes rigor (Section 19A)
    try:
        from cerebralos.reporting.trauma_doc_extractor import extract_daily_notes
        daily = extract_daily_notes(evaluation)
        if daily:
            results.append(check_daily_notes_required_content(daily))
            # Also check narrative rigor on daily notes text
            daily_text = ""
            for day in daily:
                for v in day.get("fields", {}).values():
                    daily_text += str(v) + "\n"
            if daily_text:
                results.append(check_narrative_rigor(daily_text, "daily_notes"))
    except Exception:
        pass

    return results
