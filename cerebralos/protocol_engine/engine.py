#!/usr/bin/env python3
"""
Protocol Evaluation Engine for CerebralOS.

Evaluates patient compliance with Deaconess Regional Trauma Center protocols.
Mirrors NTDS engine.py architecture but adapted for protocol compliance assessment.

Design:
- Deterministic: Same input always produces same output
- Fail-closed: Missing data → INDETERMINATE (never guess)
- Evidence-based: Every COMPLIANT determination requires supporting evidence
- Auditable: Full step-by-step trace with evidence links
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from cerebralos.protocol_engine.model import (
    MatchDetail,
    ProtocolEvidence,
    ProtocolFacts,
    ProtocolOutcome,
    ProtocolResult,
    RequirementType,
    StepResult,
)
from cerebralos.protocol_engine.rules_loader import load_protocol_ruleset
from cerebralos.protocol_engine.build_protocolfacts import build_protocolfacts

REPO_ROOT = Path(__file__).resolve().parents[2]


def _compile_patterns(patterns: List[str]) -> List[re.Pattern[str]]:
    """Compile list of regex pattern strings to compiled Pattern objects."""
    out: List[re.Pattern[str]] = []
    for p in patterns:
        try:
            out.append(re.compile(p, re.IGNORECASE))
        except re.error:
            out.append(re.compile(re.escape(p), re.IGNORECASE))
    return out


# ---------------------------------------------------------------------------
# Negation Detection (NegEx-style)
# ---------------------------------------------------------------------------
# Pre-negation cues: phrases that appear BEFORE a clinical concept to negate it.
# Ordered longest-first so greedy matching works correctly.
_PRE_NEGATION_CUES = [
    r"\bno\s+evidence\s+of\b",
    r"\bno\s+signs?\s+of\b",
    r"\bno\s+acute\b",
    r"\bno\s+(?:new|significant|obvious|gross)\b",
    r"\bnegative\s+for\b",
    r"\brule[ds]?\s+out\b",
    r"\bfailed\s+to\s+(?:reveal|show|demonstrate)\b",
    r"\bunremarkable\s+for\b",
    r"\bfree\s+of\b",
    r"\bwithout\b",
    r"\bdenies\b",
    r"\bno\b",
    r"\bnot\b",
    r"\babsent\b",
    r"\bnever\b",
]

# Post-negation cues: phrases that appear AFTER a clinical concept to negate it.
_POST_NEGATION_CUES = [
    r"\bnot\s+(?:seen|found|identified|demonstrated|present|confirmed|detected|noted)\b",
    r"\babsent\b",
    r"\bunlikely\b",
    r"\bnot\s+(?:elevated|positive)\b",
]

_PRE_NEGATION_COMPILED = [re.compile(p, re.IGNORECASE) for p in _PRE_NEGATION_CUES]
_POST_NEGATION_COMPILED = [re.compile(p, re.IGNORECASE) for p in _POST_NEGATION_CUES]

# Characters that break negation scope (negation doesn't cross these)
_SCOPE_BREAKER_CHARS = frozenset('.;\n!?')

# Phrase-level scope breakers
_SCOPE_BREAKER_PHRASES = (' but ', ' however ', ' although ', ' except ')

# Window sizes for negation context search
_PRE_NEGATION_WINDOW = 30   # characters before match
_POST_NEGATION_WINDOW = 20  # characters after match


def _is_negated(text: str, match_start: int, match_end: int) -> bool:
    """
    Check if a regex match is negated by surrounding context (NegEx-style).

    Looks backward and forward from the match for negation cues within a
    character window, respecting sentence/clause boundaries.

    Args:
        text: Full text being searched
        match_start: Start position of the regex match
        match_end: End position of the regex match

    Returns:
        True if the match appears to be negated
    """
    # --- Pre-negation check (look backward) ---
    pre_start = max(0, match_start - _PRE_NEGATION_WINDOW)
    pre_text = text[pre_start:match_start]

    # Find last scope breaker — negation doesn't cross these
    last_break = -1
    for i, ch in enumerate(pre_text):
        if ch in _SCOPE_BREAKER_CHARS:
            last_break = i
    for phrase in _SCOPE_BREAKER_PHRASES:
        pos = pre_text.lower().rfind(phrase)
        if pos >= 0 and pos > last_break:
            last_break = pos + len(phrase) - 1

    # Trim to only the current sentence/clause
    if last_break >= 0:
        pre_text = pre_text[last_break + 1:]

    # Check for negation cues
    if pre_text.strip():
        for cue in _PRE_NEGATION_COMPILED:
            if cue.search(pre_text):
                return True

    # --- Post-negation check (look forward) ---
    post_end = min(len(text), match_end + _POST_NEGATION_WINDOW)
    post_text = text[match_end:post_end]

    # Find first scope breaker
    first_break = len(post_text)
    for i, ch in enumerate(post_text):
        if ch in _SCOPE_BREAKER_CHARS:
            first_break = i
            break
    for phrase in _SCOPE_BREAKER_PHRASES:
        pos = post_text.lower().find(phrase)
        if pos >= 0 and pos < first_break:
            first_break = pos

    post_text = post_text[:first_break]

    if post_text.strip():
        for cue in _POST_NEGATION_COMPILED:
            if cue.search(post_text):
                return True

    return False


def _patterns_for_key(patient: ProtocolFacts, pattern_key: str) -> List[re.Pattern[str]]:
    """
    Get compiled regex patterns for a given pattern key.

    Looks up key in patient.facts["action_patterns"], compiles and returns patterns.
    """
    patterns_map = (patient.facts or {}).get("action_patterns", {}) or {}
    pats = patterns_map.get(pattern_key, [])
    if not isinstance(pats, list) or not pats:
        return []
    return _compile_patterns([str(x) for x in pats])


# Historical reference patterns (to exclude from current admission matching)
_HISTORICAL_PATTERNS = [
    r"\bhistory\s+of\b",
    r"\bpast\s+(?:medical|surgical)\s+history\b",
    r"\bpmh\s*:\b",
    r"\bpsh\s*:\b",
    r"\bprevious(?:ly)?\b",
    r"\bprior\s+to\s+(?:admission|this|current)\b",
    r"\d+\s+(?:months?|years?|weeks?)\s+ago\b",
    r"\bremote\s+history\b",
    r"\bold\s+fracture\b",
    r"\bhealed\s+fracture\b",
    r"\bstatus\s+post.*\d+\s+(?:months?|years?)\b",
    r"\bs/?p\s+.*\d+\s+(?:months?|years?)\b",
    r"\bprior\s+(?:surgery|procedure|repair|fixation|replacement)\b",
    r"\bchildhood\b",
    r"\bcongenital\b",
    r"\blong-?standing\b",
    r"\bchronic\b.*\b(?:surgery|repair|fixation|replacement)\b",
    r"\bprior\s+admission\b",
    r"\bprevious\s+hospitalization\b",
]
_HISTORICAL_COMPILED = [re.compile(p, re.IGNORECASE) for p in _HISTORICAL_PATTERNS]


def _is_historical_reference(text: str) -> bool:
    """Check if text refers to historical/past events rather than current admission."""
    if not text:
        return False
    for pattern in _HISTORICAL_COMPILED:
        if pattern.search(text):
            return True
    return False


def _is_match_in_historical_context(text: str, match_start: int, match_end: int,
                                      context_window: int = 400) -> bool:
    """
    Check if a specific regex match is in a historical context.

    Instead of flagging entire evidence blocks, checks the text surrounding
    a pattern match (400 chars before) for historical markers like
    'Past Surgical History', 'PMH:', 'history of', etc.

    This allows clinical notes that CONTAIN a PMH section to still match
    for patterns found in the current-assessment sections of the same note.
    """
    # Look at context BEFORE the match (where section headers appear)
    ctx_start = max(0, match_start - context_window)
    context_before = text[ctx_start:match_start].lower()

    # Check for section-level historical markers in the preceding context
    section_markers = [
        "past medical history", "past surgical history", "pmh:", "psh:",
        "surgical history:", "medical history:", "family history",
        "family hx", "fhx:", "social history",
        "previous surgeries", "prior procedures", "prior surgeries",
        "surgical hx", "medical hx",
    ]
    for marker in section_markers:
        if marker in context_before:
            # Verify no new section header appeared between the marker and the match
            # (which would mean we've left the historical section)
            marker_pos = context_before.rfind(marker)
            text_after_marker = context_before[marker_pos:]
            # Common section headers that indicate we've moved past history
            current_sections = [
                "\nassessment", "\nplan", "\nphysical exam", "\npe:",
                "\nreview of systems", "\nros:", "\nhpi:", "\nsubjective",
                "\nobjective", "\nimaging", "\nlabs", "\nradiograph",
                "\nimpression", "\nsecondary survey", "\nprimary survey",
                "\nchief complaint", "\nalert history",
                "\nmedications:", "\nallergies:",
            ]
            left_history = any(s in text_after_marker for s in current_sections)
            if not left_history:
                return True

    # Check for inline historical markers close to the match (100 chars)
    close_ctx_start = max(0, match_start - 100)
    close_before = text[close_ctx_start:match_start].lower()
    inline_markers = [
        "history of", "hx of", "previous", "prior ",
        "remote history", "old fracture", "healed fracture",
        "status post", "s/p ",
        "prior surgery", "prior repair", "prior fixation",
        "prior replacement", "prior procedure",
    ]
    for marker in inline_markers:
        if marker in close_before:
            return True

    # Check for date-based historical context (e.g., "4/22/2025" near the match
    # when it's clearly a past procedure date, not current admission)
    close_after = text[match_end:min(len(text), match_end + 100)].lower()
    close_context = close_before + close_after
    if re.search(r"\d+\s+(?:months?|years?|weeks?)\s+ago", close_context):
        return True

    # Check for past-tense procedure language near the match
    if re.search(r"\b(?:underwent|had|received|completed)\b.*\b(?:surgery|repair|fixation|replacement|procedure)\b",
                 close_context, re.IGNORECASE):
        return True

    return False


def match_evidence(
    patient: ProtocolFacts,
    pattern_key: str,
    allowed_sources: Optional[List[str]] = None,
    max_hits: int = 8,
    negation_aware: bool = True,
    skip_historical: bool = True,
    admission_window_hours: int = 24,
) -> List[ProtocolEvidence]:
    """
    Match evidence against pattern key with optional negation and historical filtering.

    When negation_aware=True (default), uses NegEx-style analysis to skip
    matches that appear in negated context (e.g., "no fracture", "denies pain").

    When skip_historical=True (default), skips evidence that appears to reference
    past medical/surgical history rather than current admission events (e.g.,
    "history of femur fracture repair 8 months ago").

    admission_window_hours: Evidence with timestamps more than this many hours
    BEFORE arrival is excluded. Set to 0 to disable. Default 24 hours allows
    for pre-hospital and transfer documentation.

    An evidence block is accepted if ANY pattern match within it is non-negated
    and non-historical.

    Args:
        patient: ProtocolFacts with evidence and action patterns
        pattern_key: Key to look up in action_patterns
        allowed_sources: Optional list of allowed source types
        max_hits: Maximum evidence items to return
        negation_aware: If True, apply NegEx negation detection (default True)
        skip_historical: If True, skip historical references (default True)
        admission_window_hours: Hours before arrival to accept evidence (default 24)

    Returns: List of matching ProtocolEvidence (up to max_hits)
    """
    compiled = _patterns_for_key(patient, pattern_key)
    if not compiled:
        return []

    allowed_set = None
    if allowed_sources:
        allowed_set = {s for s in allowed_sources}

    # Parse arrival time for admission window enforcement
    arrival_dt = None
    if admission_window_hours > 0:
        arrival_str = (patient.facts or {}).get("arrival_time", "")
        if arrival_str:
            arrival_dt = _parse_datetime(arrival_str)

    hits: List[ProtocolEvidence] = []
    for e in patient.evidence:
        if allowed_set and e.source_type.name not in allowed_set:
            continue

        # Admission window check: skip evidence from well before arrival
        if arrival_dt and e.timestamp and admission_window_hours > 0:
            e_dt = _parse_datetime(e.timestamp)
            if e_dt is not None:
                delta = arrival_dt - e_dt
                if delta.total_seconds() > admission_window_hours * 3600:
                    continue  # Evidence predates admission window

        txt = e.text or ""

        if negation_aware:
            # Accept evidence if ANY pattern has a non-negated, non-historical match
            matched = False
            for p in compiled:
                for m in p.finditer(txt):
                    if _is_negated(txt, m.start(), m.end()):
                        continue
                    if skip_historical and _is_match_in_historical_context(txt, m.start(), m.end()):
                        continue
                    matched = True
                    break
                if matched:
                    break
            if matched:
                hits.append(e)
                if len(hits) >= max_hits:
                    break
        else:
            # No negation check — but still respect historical context filtering
            matched = False
            for p in compiled:
                for m in p.finditer(txt):
                    if skip_historical and _is_match_in_historical_context(txt, m.start(), m.end()):
                        continue
                    matched = True
                    break
                if matched:
                    break
            if matched:
                hits.append(e)
                if len(hits) >= max_hits:
                    break
    return hits


def match_evidence_with_details(
    patient: ProtocolFacts,
    pattern_key: str,
    allowed_sources: Optional[List[str]] = None,
    max_hits: int = 8,
    negation_aware: bool = True,
    skip_historical: bool = True,
    admission_window_hours: int = 24,
) -> tuple[List[ProtocolEvidence], List[MatchDetail]]:
    """
    Match evidence and return both hits and match details explaining WHY.

    Same logic as match_evidence() but additionally tracks which pattern matched
    and what text was matched for each hit.

    Returns:
        (evidence_hits, match_details)
    """
    compiled = _patterns_for_key(patient, pattern_key)
    if not compiled:
        return ([], [])

    allowed_set = {s for s in allowed_sources} if allowed_sources else None

    arrival_dt = None
    if admission_window_hours > 0:
        arrival_str = (patient.facts or {}).get("arrival_time", "")
        if arrival_str:
            arrival_dt = _parse_datetime(arrival_str)

    hits: List[ProtocolEvidence] = []
    details: List[MatchDetail] = []

    for e in patient.evidence:
        if allowed_set and e.source_type.name not in allowed_set:
            continue

        if arrival_dt and e.timestamp and admission_window_hours > 0:
            e_dt = _parse_datetime(e.timestamp)
            if e_dt is not None:
                delta = arrival_dt - e_dt
                if delta.total_seconds() > admission_window_hours * 3600:
                    continue

        txt = e.text or ""
        for p in compiled:
            for m in p.finditer(txt):
                if negation_aware and _is_negated(txt, m.start(), m.end()):
                    continue
                if skip_historical and _is_match_in_historical_context(txt, m.start(), m.end()):
                    continue

                # Record the match
                hits.append(e)
                ctx_start = max(0, m.start() - 100)
                ctx_end = min(len(txt), m.end() + 100)
                details.append(MatchDetail(
                    pattern_key=pattern_key,
                    matched_text=m.group(0),
                    context=txt[ctx_start:ctx_end].strip(),
                ))
                break  # One match per pattern is enough
            if len(hits) > len(details) - 1:
                break  # Already matched this evidence block
        if len(hits) >= max_hits:
            break

    return (hits, details)


def line_matches_any(
    patient: ProtocolFacts,
    text: str,
    pattern_key: str,
    negation_aware: bool = True,
) -> bool:
    """Check if text matches any pattern for given key (negation-aware by default)."""
    compiled = _patterns_for_key(patient, pattern_key)
    if not compiled:
        return False
    t = text or ""
    if negation_aware:
        for p in compiled:
            for m in p.finditer(t):
                if not _is_negated(t, m.start(), m.end()):
                    return True
        return False
    return any(p.search(t) for p in compiled)


def _parse_pattern_with_source(condition_str: str) -> tuple[str, Optional[List[str]]]:
    """
    Parse pattern key with optional source type restriction.

    Syntax: pattern_key@SOURCE_TYPE
    Example: protocol_tbi_gcs_documented@TRAUMA_HP

    Returns:
        (pattern_key, source_list) where source_list is None if no restriction
    """
    if "@" in condition_str:
        parts = condition_str.split("@", 1)
        pattern_key = parts[0].strip()
        source_type = parts[1].strip()
        return (pattern_key, [source_type])
    return (condition_str, None)


def _parse_numeric_threshold(condition_str: str) -> Optional[tuple[str, str, float]]:
    """
    Parse numeric threshold condition.

    Syntax: parameter:operator:threshold
    Example: gcs_score:<=:8 → ("gcs_score", "<=", 8.0)

    Supported operators: <, <=, >, >=, ==, !=

    Returns:
        (parameter_name, operator, threshold_value) or None if not a threshold condition
    """
    parts = condition_str.split(":")
    if len(parts) != 3:
        return None

    parameter = parts[0].strip()
    operator = parts[1].strip()
    threshold_str = parts[2].strip()

    # Validate operator
    if operator not in ["<", "<=", ">", ">=", "==", "!="]:
        return None

    # Parse threshold value
    try:
        threshold = float(threshold_str)
    except ValueError:
        return None

    return (parameter, operator, threshold)


def _extract_numeric_value(text: str, parameter_name: str) -> Optional[float]:
    """
    Extract numeric value for a parameter from text.

    Examples:
        "GCS 12" → 12.0 (for parameter "gcs")
        "Glasgow Coma Scale: 14" → 14.0
        "BP 120/80" → 120.0 (for parameter "systolic_bp")
        "Hemoglobin 7.2 g/dL" → 7.2 (for parameter "hemoglobin")

    Returns:
        Numeric value or None if not found
    """
    text_lower = text.lower()
    param_lower = parameter_name.lower()

    # Define parameter patterns
    patterns = {
        "gcs": [
            r"\bGCS\s*:?\s*(\d+)",
            r"\bglasgow\s+coma\s+scale\s*:?\s*(\d+)",
        ],
        "gcs_score": [
            r"\bGCS\s*:?\s*(\d+)",
            r"\bglasgow\s+coma\s+scale\s*:?\s*(\d+)",
        ],
        "systolic_bp": [
            r"\bSBP\s*:?\s*(\d+)",
            r"\bBP\s*:?\s*(\d+)/\d+",
            r"\bblood\s+pressure\s*:?\s*(\d+)/\d+",
        ],
        "diastolic_bp": [
            r"\bBP\s*:?\s*\d+/(\d+)",
            r"\bblood\s+pressure\s*:?\s*\d+/(\d+)",
        ],
        "heart_rate": [
            r"\bHR\s*:?\s*(\d+)",
            r"\bheart\s+rate\s*:?\s*(\d+)",
        ],
        "hemoglobin": [
            r"\bhemoglobin\s*:?\s*(\d+\.?\d*)",
            r"\bHgb\s*:?\s*(\d+\.?\d*)",
            r"\bHb\s*:?\s*(\d+\.?\d*)",
        ],
        "temperature": [
            r"\btemp\s*:?\s*(\d+\.?\d*)",
            r"\btemperature\s*:?\s*(\d+\.?\d*)",
        ],
        "respiratory_rate": [
            r"\bRR\s*:?\s*(\d+)",
            r"\brespiratory\s+rate\s*:?\s*(\d+)",
        ],
        "age": [
            r"\b(\d+)[-\s]year[-\s]old\b",
            r"\b(\d+)\s*y/?o\b",
            r"\b(\d+)\s*yr\b",
            r"\bage\s*[:\s]\s*(\d+)",
            r"\bage\s+(\d+)\b",
        ],
        "tbsa": [
            r"\b(\d+)\s*%?\s*TBSA\b",
            r"\btotal\s+body\s+surface\s+area\s*:?\s*(\d+)",
            r"\bTBSA\s*:?\s*(\d+)",
        ],
        "rib_count": [
            r"\b(\d+)\s+rib\s+fractures?\b",
            r"\brib\s+fractures?\s*:?\s*(\d+)",
        ],
        "gfr": [
            r"\bGFR\s*:?\s*(\d+\.?\d*)",
            r"\bglomerular\s+filtration\s*:?\s*(\d+\.?\d*)",
        ],
        "ejection_fraction": [
            r"\bEF\s*:?\s*(\d+)",
            r"\bejection\s+fraction\s*:?\s*(\d+)",
        ],
        "bmi": [
            r"\bBMI\s*:?\s*(\d+\.?\d*)",
        ],
        "spirometry_pct": [
            r"\bspirometry\s*:?\s*(\d+)\s*%",
            r"\bincentive\s+spirometry\s*:?\s*(\d+)",
        ],
        "audit_c": [
            r"\bAUDIT-?C\s*:?\s*(\d+)",
        ],
        "dast_10": [
            r"\bDAST-?10\s*:?\s*(\d+)",
        ],
        "etoh": [
            r"\bETOH\s*:?\s*(\d+)",
            r"\bblood\s+alcohol\s*:?\s*(\d+)",
            r"\bBAC\s*:?\s*(\d+)",
        ],
        "injury_grade": [
            r"\bgrade\s*:?\s*(\d)",
            r"\bGrade\s+(\d)",
        ],
    }

    # Get patterns for this parameter
    param_patterns = patterns.get(param_lower, [])

    #Try each pattern
    for pattern in param_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except (ValueError, IndexError):
                continue

    return None


def _compare_numeric(value: float, operator: str, threshold: float) -> bool:
    """
    Compare numeric value against threshold using operator.

    Returns:
        True if comparison passes, False otherwise
    """
    if operator == "<":
        return value < threshold
    elif operator == "<=":
        return value <= threshold
    elif operator == ">":
        return value > threshold
    elif operator == ">=":
        return value >= threshold
    elif operator == "==":
        return value == threshold
    elif operator == "!=":
        return value != threshold
    else:
        return False


def _evaluate_numeric_threshold(
    patient: ProtocolFacts,
    parameter: str,
    operator: str,
    threshold: float,
    allowed_sources: Optional[List[str]] = None,
    max_hits: int = 8
) -> tuple[bool, List[ProtocolEvidence]]:
    """
    Evaluate numeric threshold condition against patient evidence.

    Args:
        patient: ProtocolFacts with evidence
        parameter: Parameter name (e.g., "gcs_score", "hemoglobin")
        operator: Comparison operator (<, <=, >, >=, ==, !=)
        threshold: Threshold value to compare against
        allowed_sources: Optional list of allowed source types
        max_hits: Maximum evidence items to return

    Returns:
        (passed, evidence, value_found) where passed is True if condition met,
        evidence is list of supporting evidence, value_found is True if any
        numeric value was extracted (even if threshold not met)
    """
    allowed_set = None
    if allowed_sources:
        allowed_set = {s for s in allowed_sources}

    hits: List[ProtocolEvidence] = []
    passed = False
    value_found = False

    for e in patient.evidence:
        if allowed_set and e.source_type.name not in allowed_set:
            continue

        # Extract numeric value from evidence text
        value = _extract_numeric_value(e.text or "", parameter)
        if value is not None:
            value_found = True
            # Compare against threshold
            if _compare_numeric(value, operator, threshold):
                hits.append(e)
                passed = True
                if len(hits) >= max_hits:
                    break

    return (passed, hits, value_found)


# ---------------------------------------------------------------------------
# Temporal condition evaluation
# ---------------------------------------------------------------------------

_TS_FORMATS = [
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%m/%d/%y %H%M",
    "%m/%d/%Y %H%M",
    "%m/%d/%Y %H:%M",
    "%m/%d/%y %H:%M",
]


def _parse_datetime(ts_str: str) -> Optional[datetime]:
    """Parse timestamp string into datetime, trying multiple formats."""
    if not ts_str:
        return None
    ts_str = ts_str.strip()
    for fmt in _TS_FORMATS:
        try:
            return datetime.strptime(ts_str, fmt)
        except ValueError:
            continue
    return None


def _parse_temporal_condition(condition_str: str) -> Optional[Dict[str, Any]]:
    """
    Parse temporal condition string.

    Syntax: temporal:within:N:unit:pattern_key
    Units: minutes, hours

    Example: temporal:within:24:hours:protocol_dvt_prophylaxis_ordered

    Returns:
        {"type": "within", "value": N, "unit": "hours"|"minutes", "pattern_key": "..."}
        or None if not a temporal condition.
    """
    if not condition_str.startswith("temporal:"):
        return None

    parts = condition_str.split(":", 4)
    if len(parts) != 5:
        return None

    _, temporal_type, value_str, unit, pattern_key = parts
    if temporal_type != "within":
        return None
    if unit not in ("minutes", "hours"):
        return None

    try:
        value = float(value_str)
    except ValueError:
        return None

    return {
        "type": "within",
        "value": value,
        "unit": unit,
        "pattern_key": pattern_key.strip(),
    }


def _evaluate_temporal_condition(
    patient: ProtocolFacts,
    temporal: Dict[str, Any],
    allowed_sources: Optional[List[str]] = None,
    max_hits: int = 8,
) -> tuple[bool, List[ProtocolEvidence]]:
    """
    Evaluate temporal condition against evidence timestamps.

    For "within" type:
    1. Find evidence matching pattern_key
    2. Parse evidence timestamp
    3. Parse arrival_time from patient.facts
    4. Compute delta
    5. Return True if ANY matching evidence is within the time window

    Returns:
        (passed, matching_evidence)
    """
    pattern_key = temporal["pattern_key"]
    time_value = temporal["value"]
    time_unit = temporal["unit"]

    # Parse arrival time
    arrival_str = (patient.facts or {}).get("arrival_time", "")
    arrival_dt = _parse_datetime(arrival_str) if arrival_str else None
    if arrival_dt is None:
        # Cannot evaluate temporal condition without arrival time
        return (False, [])

    # Compute max delta
    if time_unit == "hours":
        max_delta = timedelta(hours=time_value)
    else:
        max_delta = timedelta(minutes=time_value)

    # Find evidence matching pattern_key
    evidence_hits = match_evidence(
        patient, pattern_key, allowed_sources=allowed_sources, max_hits=max_hits
    )
    if not evidence_hits:
        return (False, [])

    # Check if any matching evidence is within the time window
    within_hits: List[ProtocolEvidence] = []
    for e in evidence_hits:
        e_dt = _parse_datetime(e.timestamp) if e.timestamp else None
        if e_dt is None:
            continue
        delta = e_dt - arrival_dt
        if timedelta(0) <= delta <= max_delta:
            within_hits.append(e)

    return (bool(within_hits), within_hits)


def _is_pattern_key(patient: ProtocolFacts, key: str) -> bool:
    """
    Check if a string is a pattern key (exists in action_patterns).

    Pattern keys start with specific prefixes or exist in action_patterns dict.
    Handles pattern@SOURCE_TYPE syntax by stripping source type.
    """
    # Strip source type restriction if present
    pattern_key, _ = _parse_pattern_with_source(key)
    patterns_map = (patient.facts or {}).get("action_patterns", {}) or {}
    return pattern_key in patterns_map


def eval_trigger_criteria(
    req: Dict[str, Any],
    patient: ProtocolFacts,
    contract: Dict[str, Any]
) -> StepResult:
    """
    Evaluate REQ_TRIGGER_CRITERIA requirement.

    Determines if protocol applies to this patient.

    Logic:
    - If data missing → passed=False, "INDETERMINATE: missing trigger data"
    - If criteria not met → passed=False, "NOT_TRIGGERED"
    - If criteria met → passed=True

    Returns: StepResult with evidence and missing_data array
    """
    req_id = str(req.get("id", "REQ_TRIGGER_CRITERIA"))
    req_type = RequirementType.MANDATORY
    trigger_conditions = req.get("trigger_conditions", [])
    acceptable_evidence = req.get("acceptable_evidence", [])
    max_items = int(contract.get("evidence", {}).get("max_items_per_requirement", 8))

    hits: List[ProtocolEvidence] = []
    all_match_details: List[MatchDetail] = []
    missing_data: List[str] = []

    # Evaluate trigger conditions sequentially.
    # First condition is the PRIMARY gate (eligibility criterion).
    # If it fails → NOT_TRIGGERED (protocol doesn't apply).
    # If subsequent conditions fail → INDETERMINATE (partial data).
    for i, condition in enumerate(trigger_conditions):
        condition_str = str(condition).strip()
        found = False

        # Try numeric threshold first (parameter:operator:threshold)
        threshold_parts = _parse_numeric_threshold(condition_str)
        if threshold_parts:
            parameter, operator, threshold = threshold_parts
            passed, threshold_hits, value_found = _evaluate_numeric_threshold(
                patient,
                parameter,
                operator,
                threshold,
                allowed_sources=acceptable_evidence if acceptable_evidence else None,
                max_hits=max_items
            )
            if passed:
                hits.extend(threshold_hits)
                found = True
            elif value_found:
                # Value extracted but threshold not met → patient explicitly
                # does not qualify (e.g., age 45 vs age < 16)
                return StepResult(
                    requirement_id=req_id,
                    requirement_type=req_type,
                    passed=False,
                    reason=f"NOT_TRIGGERED: {parameter} does not meet threshold ({operator} {threshold:.0f})",
                    evidence=[],
                    missing_data=[]
                )
        # Try pattern key matching (with optional @SOURCE_TYPE)
        elif _is_pattern_key(patient, condition_str):
            # Parse source restriction if present
            pattern_key, source_restriction = _parse_pattern_with_source(condition_str)

            # Use source_restriction if specified, otherwise use acceptable_evidence
            sources_to_use = source_restriction if source_restriction is not None else (acceptable_evidence if acceptable_evidence else None)

            pattern_hits, match_details = match_evidence_with_details(
                patient,
                pattern_key,
                allowed_sources=sources_to_use,
                max_hits=max_items,
            )
            if pattern_hits:
                hits.extend(pattern_hits)
                all_match_details.extend(match_details)
                found = True
        else:
            # Fall back to keyword matching for descriptive conditions
            condition_lower = condition_str.lower()
            for e in patient.evidence:
                if acceptable_evidence and e.source_type.value not in acceptable_evidence:
                    continue
                if condition_lower in (e.text or "").lower():
                    hits.append(e)
                found = True
                break

        if not found:
            if i == 0:
                # Primary trigger condition not met → protocol doesn't apply
                return StepResult(
                    requirement_id=req_id,
                    requirement_type=req_type,
                    passed=False,
                    reason="NOT_TRIGGERED: Primary trigger criteria not met",
                    evidence=[],
                    missing_data=[condition_str[:50]]
                )
            else:
                missing_data.append(condition_str[:50])  # Track first 50 chars

    if missing_data:
        return StepResult(
            requirement_id=req_id,
            requirement_type=req_type,
            passed=False,
            reason=f"INDETERMINATE: Missing trigger data ({len(missing_data)} conditions not documented)",
            evidence=hits[:max_items],
            missing_data=missing_data,
            match_details=all_match_details
        )

    if not hits:
        return StepResult(
            requirement_id=req_id,
            requirement_type=req_type,
            passed=False,
            reason="NOT_TRIGGERED: Trigger criteria not met",
            evidence=[],
            missing_data=[]
        )

    return StepResult(
        requirement_id=req_id,
        requirement_type=req_type,
        passed=True,
        reason="Trigger criteria satisfied",
        evidence=hits[:max_items],
        missing_data=[],
        match_details=all_match_details
    )


def eval_required_data_elements(
    req: Dict[str, Any],
    patient: ProtocolFacts,
    contract: Dict[str, Any]
) -> StepResult:
    """
    Evaluate REQ_REQUIRED_DATA_ELEMENTS requirement.

    Checks for presence of all required data elements.
    Negation detection is OFF here because documenting a negative finding
    (e.g., "No extravasation", "No compartment syndrome") is valid evidence
    that the concept was assessed/addressed.

    Logic:
    - If ANY element missing → passed=False, populate missing_data array
    - If all present → passed=True

    Returns: StepResult with evidence for found elements, missing_data for gaps
    """
    req_id = str(req.get("id", "REQ_REQUIRED_DATA_ELEMENTS"))
    req_type = RequirementType.MANDATORY
    trigger_conditions = req.get("trigger_conditions", [])
    acceptable_evidence = req.get("acceptable_evidence", [])
    max_items = int(contract.get("evidence", {}).get("max_items_per_requirement", 8))

    hits: List[ProtocolEvidence] = []
    all_match_details: List[MatchDetail] = []
    missing_data: List[str] = []

    # Enhanced: Support both pattern keys and keyword matching
    # negation_aware=False: documenting absence is still valid documentation
    for data_element in trigger_conditions:
        element_str = str(data_element).strip()
        found = False

        # Try pattern key matching first (with optional @SOURCE_TYPE)
        if _is_pattern_key(patient, element_str):
            # Parse source restriction if present
            pattern_key, source_restriction = _parse_pattern_with_source(element_str)

            # Use source_restriction if specified, otherwise use acceptable_evidence
            sources_to_use = source_restriction if source_restriction is not None else (acceptable_evidence if acceptable_evidence else None)

            pattern_hits, match_details = match_evidence_with_details(
                patient,
                pattern_key,
                allowed_sources=sources_to_use,
                max_hits=max_items,
                negation_aware=False,  # Negative findings are valid documentation
            )
            if pattern_hits:
                hits.extend(pattern_hits)
                all_match_details.extend(match_details)
                found = True
        else:
            # Fall back to keyword matching for descriptive elements
            element_lower = element_str.lower()
            for e in patient.evidence:
                if acceptable_evidence and e.source_type.value not in acceptable_evidence:
                    continue
                if element_lower in (e.text or "").lower():
                    hits.append(e)
                    found = True
                    break
        if not found:
            missing_data.append(element_str[:50])

    if missing_data:
        return StepResult(
            requirement_id=req_id,
            requirement_type=req_type,
            passed=False,
            reason=f"INDETERMINATE: Missing required data elements ({len(missing_data)} elements not documented)",
            evidence=hits[:max_items],
            missing_data=missing_data,
            match_details=all_match_details
        )

    return StepResult(
        requirement_id=req_id,
        requirement_type=req_type,
        passed=True,
        reason="All required data elements present",
        evidence=hits[:max_items],
        missing_data=[],
        match_details=all_match_details
    )


def eval_timing_critical(
    req: Dict[str, Any],
    patient: ProtocolFacts,
    contract: Dict[str, Any]
) -> StepResult:
    """
    Evaluate REQ_TIMING_CRITICAL requirement.

    Checks timing requirements and thresholds.

    Logic:
    - Check timing requirements from trigger_conditions
    - If timing not met → passed=False, "NON_COMPLIANT: timing violation"
    - If timing met → passed=True

    Returns: StepResult with timestamped evidence
    """
    req_id = str(req.get("id", "REQ_TIMING_CRITICAL"))
    req_type = RequirementType.CONDITIONAL
    trigger_conditions = req.get("trigger_conditions", [])
    acceptable_evidence = req.get("acceptable_evidence", [])
    max_items = int(contract.get("evidence", {}).get("max_items_per_requirement", 8))

    hits: List[ProtocolEvidence] = []
    all_match_details: List[MatchDetail] = []
    timing_failures: List[str] = []

    # Parse arrival time for timing failure reporting
    arrival_str = (patient.facts or {}).get("arrival_time", "")
    arrival_dt = _parse_datetime(arrival_str) if arrival_str else None

    # Enhanced: Support temporal, pattern key, and keyword matching
    for condition in trigger_conditions:
        condition_str = str(condition).strip()

        # Try temporal condition first (temporal:within:N:unit:pattern_key)
        temporal = _parse_temporal_condition(condition_str)
        if temporal is not None:
            passed, temporal_hits = _evaluate_temporal_condition(
                patient,
                temporal,
                allowed_sources=acceptable_evidence if acceptable_evidence else None,
                max_hits=max_items
            )
            if passed:
                hits.extend(temporal_hits)
            else:
                # Build detailed timing failure message
                time_val = temporal["value"]
                time_unit = temporal["unit"]
                pkey = temporal["pattern_key"]
                # Check if evidence exists at all (just outside window)
                any_evidence = match_evidence(
                    patient, pkey,
                    allowed_sources=acceptable_evidence if acceptable_evidence else None,
                    max_hits=1, admission_window_hours=0,
                )
                if any_evidence and any_evidence[0].timestamp:
                    e_ts = any_evidence[0].timestamp
                    timing_failures.append(
                        f"{pkey}: evidence found at {e_ts} but required within {time_val:.0f} {time_unit} of arrival ({arrival_str or 'unknown'})"
                    )
                else:
                    timing_failures.append(
                        f"{pkey}: no evidence found (required within {time_val:.0f} {time_unit} of arrival)"
                    )
            continue

        # Try pattern key matching (with optional @SOURCE_TYPE)
        if _is_pattern_key(patient, condition_str):
            # Parse source restriction if present
            pattern_key, source_restriction = _parse_pattern_with_source(condition_str)

            # Use source_restriction if specified, otherwise use acceptable_evidence
            sources_to_use = source_restriction if source_restriction is not None else (acceptable_evidence if acceptable_evidence else None)

            pattern_hits, match_details = match_evidence_with_details(
                patient,
                pattern_key,
                allowed_sources=sources_to_use,
                max_hits=max_items
            )
            if pattern_hits:
                hits.extend(pattern_hits)
                all_match_details.extend(match_details)
        else:
            # Fall back to keyword matching for descriptive conditions
            condition_lower = condition_str.lower()
            for e in patient.evidence:
                if acceptable_evidence and e.source_type.value not in acceptable_evidence:
                    continue
                if condition_lower in (e.text or "").lower():
                    hits.append(e)
                    break

    if not hits:
        # Build informative failure reason
        if timing_failures:
            failure_detail = "; ".join(timing_failures[:3])
            reason = f"NON_COMPLIANT: Timing requirements not met — {failure_detail}"
        else:
            reason = "NON_COMPLIANT: Timing-critical elements not documented"
        return StepResult(
            requirement_id=req_id,
            requirement_type=req_type,
            passed=False,
            reason=reason,
            evidence=[],
            missing_data=[],
            match_details=all_match_details
        )

    # Check exclusion conditions (negative patterns that indicate timing violation)
    exclusion_conditions = req.get("exclusion_conditions", [])
    for exclusion in exclusion_conditions:
        exclusion_str = str(exclusion).strip()

        if _is_pattern_key(patient, exclusion_str):
            pattern_key, source_restriction = _parse_pattern_with_source(exclusion_str)
            sources_to_use = source_restriction if source_restriction is not None else (acceptable_evidence if acceptable_evidence else None)

            exclusion_hits = match_evidence(
                patient,
                pattern_key,
                allowed_sources=sources_to_use,
                max_hits=max_items
            )
            if exclusion_hits:
                return StepResult(
                    requirement_id=req_id,
                    requirement_type=req_type,
                    passed=False,
                    reason=f"NON_COMPLIANT: Timing violation detected ({exclusion_str})",
                    evidence=exclusion_hits[:max_items],
                    missing_data=[],
                    match_details=all_match_details
                )

    return StepResult(
        requirement_id=req_id,
        requirement_type=req_type,
        passed=True,
        reason="Timing requirements met",
        evidence=hits[:max_items],
        missing_data=[],
        match_details=all_match_details
    )


def evaluate_protocol(
    protocol_rules: Dict[str, Any],
    contract: Dict[str, Any],
    patient: ProtocolFacts
) -> ProtocolResult:
    """
    Main protocol evaluation orchestrator.

    Flow:
    1. Check evaluation_mode (skip CONTEXT_ONLY)
    2. Evaluate requirements sequentially:
       a. REQ_TRIGGER_CRITERIA → NOT_TRIGGERED or INDETERMINATE if fails
       b. REQ_REQUIRED_DATA_ELEMENTS → INDETERMINATE if fails
       c. REQ_TIMING_CRITICAL → NON_COMPLIANT if fails
    3. All pass → COMPLIANT

    Returns: ProtocolResult with outcome, step_trace, warnings
    """
    proto_id = str(protocol_rules.get("protocol_id"))
    proto_name = str(protocol_rules.get("name"))
    proto_version = str(protocol_rules.get("version", "1.0.0"))
    eval_mode = str(protocol_rules.get("evaluation_mode"))

    r = ProtocolResult(
        protocol_id=proto_id,
        protocol_name=proto_name,
        protocol_version=proto_version,
        outcome=ProtocolOutcome.INDETERMINATE
    )

    # Skip evaluation for CONTEXT_ONLY protocols
    if eval_mode == "CONTEXT_ONLY":
        r.outcome = ProtocolOutcome.NOT_TRIGGERED
        r.warnings.append("CONTEXT_ONLY protocol: no compliance evaluation performed")
        return r

    # Evaluate requirements in order
    requirements = protocol_rules.get("requirements", [])

    for req in requirements:
        req_id = str(req.get("id", ""))

        # Dispatch to appropriate evaluator based on requirement ID
        if "TRIGGER" in req_id:
            step_result = eval_trigger_criteria(req, patient, contract)
        elif "DATA" in req_id:
            step_result = eval_required_data_elements(req, patient, contract)
        elif "TIMING" in req_id:
            step_result = eval_timing_critical(req, patient, contract)
        else:
            # Unknown requirement type - skip with warning
            r.warnings.append(f"Unknown requirement type: {req_id}")
            continue

        r.step_trace.append(step_result)

        # Check if requirement failed
        if not step_result.passed:
            req_type_str = req.get("requirement_type", "MANDATORY")

            if req_type_str == "MANDATORY":
                # Determine outcome from failure reason
                if "INDETERMINATE" in step_result.reason:
                    r.outcome = ProtocolOutcome.INDETERMINATE
                elif "NOT_TRIGGERED" in step_result.reason:
                    r.outcome = ProtocolOutcome.NOT_TRIGGERED
                else:
                    r.outcome = ProtocolOutcome.NON_COMPLIANT
                return r
            elif req_type_str == "CONDITIONAL":
                # Conditional failure → NON_COMPLIANT
                r.outcome = ProtocolOutcome.NON_COMPLIANT
                return r

    # All requirements passed
    r.outcome = ProtocolOutcome.COMPLIANT
    return r


def write_protocol_output(
    result: ProtocolResult,
    out_path: Path,
    patient: Optional[ProtocolFacts] = None,
    protocol_rules: Optional[Dict[str, Any]] = None
) -> None:
    """
    Generate JSON output for protocol evaluation.

    Output includes:
    - protocol_id, protocol_name, protocol_version
    - outcome (COMPLIANT/NON_COMPLIANT/NOT_TRIGGERED/INDETERMINATE)
    - step_trace with evidence
    - summary
    - warnings
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)

    def ev_to_dict(e: ProtocolEvidence) -> Dict[str, Any]:
        return {
            "source_type": e.source_type.value,
            "timestamp": e.timestamp,
            "text": e.text,
            "pointers": e.pointer.ref,
        }

    payload: Dict[str, Any] = {
        "protocol_id": result.protocol_id,
        "protocol_name": result.protocol_name,
        "protocol_version": result.protocol_version,
        "outcome": result.outcome.value,
        "step_trace": [],
        "summary": "",
        "warnings": result.warnings,
    }

    for step in result.step_trace:
        payload["step_trace"].append({
            "requirement_id": step.requirement_id,
            "requirement_type": step.requirement_type.value,
            "passed": step.passed,
            "reason": step.reason,
            "evidence": [ev_to_dict(e) for e in step.evidence],
            "missing_data": step.missing_data,
        })

    # Generate summary
    if result.outcome == ProtocolOutcome.COMPLIANT:
        payload["summary"] = "COMPLIANT — All protocol requirements met"
    elif result.outcome == ProtocolOutcome.NON_COMPLIANT:
        failed_step = next((s for s in result.step_trace if not s.passed), None)
        if failed_step:
            payload["summary"] = f"NON_COMPLIANT — {failed_step.requirement_id} failed"
        else:
            payload["summary"] = "NON_COMPLIANT"
    elif result.outcome == ProtocolOutcome.NOT_TRIGGERED:
        payload["summary"] = "NOT_TRIGGERED — Protocol does not apply to this patient"
    else:
        payload["summary"] = "INDETERMINATE — Missing required data for compliance determination"

    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_mapper() -> Dict[str, Any]:
    """Load Epic/Deaconess mapper patterns."""
    p = REPO_ROOT / "rules" / "mappers" / "epic_deaconess_mapper_v1.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def main() -> int:
    """
    CLI for evaluating single protocol.

    Usage:
        python3 cerebralos/protocol_engine/engine.py \
            --protocol TRAUMATIC_BRAIN_INJURY_MANAGEMENT \
            --patient data_raw/patient_12345.txt

    Outputs to: outputs/protocols/<patient_stem>/<protocol_id>_v1.json
    """
    ap = argparse.ArgumentParser()
    ap.add_argument("--protocol", required=True, help="Protocol ID to evaluate")
    ap.add_argument("--patient", required=True, help="Path to Epic TXT export")
    ap.add_argument("--arrival", default=None, help="Optional arrival_time override")
    args = ap.parse_args()

    # Load ruleset
    rs = load_protocol_ruleset(args.protocol)
    contract = rs.contract
    protocol_rules = rs.protocol

    # Load action patterns (from shared + mapper)
    action_patterns = {}
    action_patterns.update(rs.shared.get("action_buckets", {}))
    mapper = load_mapper()
    action_patterns.update(mapper.get("query_patterns", {}))

    # Build protocol facts
    p = Path(args.patient)
    patient = build_protocolfacts(p, action_patterns, arrival_time=args.arrival)

    # Evaluate protocol
    result = evaluate_protocol(protocol_rules, contract, patient)

    print(f"\nPROTOCOL EVALUATION — {result.protocol_name}")
    print(f"Outcome: {result.outcome.value}")

    # Write output
    out_path = REPO_ROOT / "outputs" / "protocols" / p.stem / f"{args.protocol}_v1.json"
    write_protocol_output(result, out_path, patient=patient, protocol_rules=protocol_rules)
    print(f"Wrote: {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
