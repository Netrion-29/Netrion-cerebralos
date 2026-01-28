#!/usr/bin/env python3
"""
CerebralOS — Convert Deaconess Protocols RAW -> STRUCTURED v1

Input:
  rules/deaconess/protocols_deaconess_raw_v1.json

Output:
  rules/deaconess/protocols_deaconess_structured_v1.json

Notes:
- Deterministic conversion.
- No clinical inference.
- Uses section headings when present; falls back to raw_block parsing if needed.
- Context-only protocols are preserved as STRUCTURED with evaluation_mode=CONTEXT_ONLY.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple


REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_PATH = REPO_ROOT / "rules" / "deaconess" / "protocols_deaconess_raw_v1.json"
OUT_PATH = REPO_ROOT / "rules" / "deaconess" / "protocols_deaconess_structured_v1.json"


def _norm_lines(lines: List[str]) -> List[str]:
    out = []
    for ln in lines or []:
        ln = ln.strip()
        if not ln:
            continue
        out.append(ln)
    return out


def _section(sections: Dict[str, List[str]], key: str) -> List[str]:
    return _norm_lines(sections.get(key, []))


def _split_bullets(lines: List[str]) -> List[str]:
    """
    Converts lines like:
      - item
      • item
      1. item
    into clean bullet strings.
    If no bullets, returns the cleaned lines as-is.
    """
    out: List[str] = []
    for ln in lines:
        ln2 = re.sub(r"^\s*(?:[-•*]|\d+\.)\s*", "", ln).strip()
        if ln2:
            out.append(ln2)
    return out


def _classify_mode(protocol_class: str, sections: Dict[str, List[str]], raw_block: str) -> str:
    pc = (protocol_class or "").upper()
    blob = (raw_block or "").upper()

    # If protocol explicitly says it must not be evaluated, treat as context only
    if "CLASS II" in pc or "CONTEXTUAL" in blob or "CONTEXT ONLY" in blob:
        # Some Class II may still be evaluable, but RAW text usually states prohibitions.
        return "CONTEXT_ONLY"

    return "EVALUABLE"


def _requirements_from_sections(sections: Dict[str, List[str]]) -> List[Dict[str, Any]]:
    """
    First-pass requirement extraction:
    - Uses Trigger Criteria (Exact) and Timing-Critical Elements / Required Data Elements
    - This is intentionally conservative: we create placeholder requirements rather than infer specifics.
    """
    trig = _split_bullets(_section(sections, "Trigger Criteria (Exact)"))
    req_data = _split_bullets(_section(sections, "Required Data Elements"))
    timing = _split_bullets(_section(sections, "Timing-Critical Elements"))
    failure = _split_bullets(_section(sections, "Failure Behavior"))
    sources = _split_bullets(_section(sections, "Authoritative Sources"))

    reqs: List[Dict[str, Any]] = []

    # Requirement 1: Trigger criteria presence (as textual gates)
    if trig:
        reqs.append(
            {
                "id": "REQ_TRIGGER_CRITERIA",
                "description": "Trigger criteria satisfied per protocol definition (textual gates).",
                "requirement_type": "MANDATORY",
                "trigger_conditions": trig,
                "acceptable_evidence": sources or ["UNKNOWN"],
                "failure_consequence": "INDETERMINATE if trigger data missing; NOT_TRIGGERED if criteria not met.",
                "notes": None,
            }
        )

    # Requirement 2: Required data presence
    if req_data:
        reqs.append(
            {
                "id": "REQ_REQUIRED_DATA_ELEMENTS",
                "description": "Required data elements present for evaluation and compliance determination.",
                "requirement_type": "MANDATORY",
                "trigger_conditions": req_data,
                "acceptable_evidence": sources or ["UNKNOWN"],
                "failure_consequence": "INDETERMINATE if required data elements are missing.",
                "notes": None,
            }
        )

    # Requirement 3: Timing critical actions (placeholder)
    if timing:
        reqs.append(
            {
                "id": "REQ_TIMING_CRITICAL",
                "description": "Timing-critical elements met (first-pass placeholder; refine later).",
                "requirement_type": "CONDITIONAL",
                "trigger_conditions": timing,
                "acceptable_evidence": sources or ["UNKNOWN"],
                "failure_consequence": "NON_COMPLIANT if timing-critical elements not met when applicable.",
                "notes": None,
            }
        )

    # Failure behavior captured as notes if present
    if failure and reqs:
        reqs[0]["notes"] = "Failure behavior (protocol text): " + " | ".join(failure)

    return reqs


def convert_one(p: Dict[str, Any]) -> Dict[str, Any]:
    sections = p.get("sections", {}) or {}
    raw = p.get("raw_block", "") or ""
    protocol_class = p.get("class", "UNKNOWN") or "UNKNOWN"

    mode = _classify_mode(protocol_class, sections, raw)

    inclusion = _split_bullets(_section(sections, "Applicability Gate")) \
        or _split_bullets(_section(sections, "Applicability Condition")) \
        or _split_bullets(_section(sections, "Applicability Context"))

    exclusion = _split_bullets(_section(sections, "Not Evaluated When"))

    references = _split_bullets(_section(sections, "Authoritative Sources"))

    structured = {
        "protocol_id": p.get("protocol_id"),
        "name": p.get("name"),
        "version": "1.0.0",
        "status": "ACTIVE",
        "protocol_class": protocol_class,
        "evaluation_mode": mode,
        "owning_service": "Deaconess Regional Trauma Center",
        "inclusion_criteria": inclusion,
        "exclusion_criteria": exclusion,
        "requirements": [],
        "references": references,
        "notes": {
            "extraction_warnings": p.get("extraction_warnings", []),
            "raw_block_preserved": True
        }
    }

    if mode == "EVALUABLE":
        structured["requirements"] = _requirements_from_sections(sections)
    else:
        structured["requirements"] = []

    return structured


def main() -> int:
    if not RAW_PATH.exists():
        raise SystemExit(f"Missing RAW ruleset: {RAW_PATH}")

    raw_obj = json.loads(RAW_PATH.read_text(encoding="utf-8"))
    raw_protocols = raw_obj.get("protocols", [])

    structured = [convert_one(p) for p in raw_protocols]

    out = {
        "meta": {
            "system": "Netrion Systems",
            "product": "CerebralOS",
            "ruleset": "Deaconess Protocols (STRUCTURED v1)",
            "version": "1.0.0",
            "source_raw": str(RAW_PATH),
            "protocol_count": len(structured),
        },
        "protocols": structured,
    }

    OUT_PATH.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"OK ✅ Structured protocols: {len(structured)}")
    print(f"Wrote: {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
