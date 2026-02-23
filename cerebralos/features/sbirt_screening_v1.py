#!/usr/bin/env python3
"""
SBIRT Screening Extraction v1 for CerebralOS.

Deterministic extraction of structured SBIRT screening data from
NURSING_NOTE, PHYSICIAN_NOTE, ED_NOTE, CARE_TEAM, and SOCIAL_WORK items.

Captures THREE categories of data:

1. **Explicit numeric scores** (when documented):
   - AUDIT-C  (0–12 integer)
   - DAST-10  (0–10 integer — only explicit summary, NEVER summed)
   - CAGE     (0–4 integer)

2. **Question-level responses** (Yes/No or option text):
   - Pattern A: Narrative consult note inline Q&A
     (e.g., "How often do you have a drink…?: 4 or more times a week")
   - Pattern B: Flowsheet tab-delimited columns with Yes/No data rows
     (e.g., "Does the patient have an injury?\\tNo A")
   - Instrument identification when possible
   - Per-response items with question text + answer text

3. **Screening metadata**:
   - Completion status per instrument
   - Refusal documentation (if explicitly stated in SBIRT section)
   - Substance use admission documentation (if explicit in SBIRT section)

Fail-closed behaviour:
  - Scores extracted ONLY from explicit numeric values.
  - DAST-10 per-question answers are NEVER summed.
  - Qualitative mentions ("positive screen") are NOT scores.
  - Flowsheet "—"/blank values → skipped (not treated as answers).
  - Nurse marker suffixes ("A", "B", "C") are stripped from Yes/No values.
  - No clinical inference, no LLM, no ML.

Sources (scanned in timeline order; first reliable value wins per instrument):
  NURSING_NOTE, PHYSICIAN_NOTE, ED_NOTE, CARE_TEAM, SOCIAL_WORK, REMOVED
  (REMOVED is included because Flowsheet History sections may trail a REMOVED block)

Output key: ``sbirt_screening_v1`` (under top-level ``features`` dict)
Replaces: ``sbirt_scores_v1`` (score-only extraction, renamed in this PR)
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional, Tuple

_DNA = "DATA NOT AVAILABLE"

# ── Source type priority ────────────────────────────────────────────
_SOURCE_TYPES = frozenset({
    "NURSING_NOTE",
    "PHYSICIAN_NOTE",
    "ED_NOTE",
    "CARE_TEAM",
    "SOCIAL_WORK",
    "REMOVED",  # Flowsheet History can trail inside a REMOVED block
})

# ── Score patterns ──────────────────────────────────────────────────

RE_AUDIT_C = re.compile(
    r"\baudit[\s-]?c\s+score\s*[:=]\s*(\d{1,2})\b",
    re.IGNORECASE,
)

RE_DAST_10 = re.compile(
    r"\bdast[\s-]?10\s+(?:score|total)\s*[:=]\s*(\d{1,2})\b",
    re.IGNORECASE,
)

RE_CAGE = re.compile(
    r"\bcage\s*(?:score\s*)?[:=]\s*(\d)\s*(?:/\s*4)?\b",
    re.IGNORECASE,
)

RE_FLOWSHEET_AUDIT_C_HEADER = re.compile(
    r"Audit[\s-]?C\s+Score",
    re.IGNORECASE,
)

# ── Narrative Q&A patterns (Pattern A) ──────────────────────────────
# These match single-line "Question?: Answer" pairs in consult notes.

# AUDIT-C Q&A (3 canonical questions)
RE_AUDIT_C_Q1 = re.compile(
    r"How often do you have a drink containing alcohol\?\s*:\s*(.+)",
    re.IGNORECASE,
)
RE_AUDIT_C_Q2 = re.compile(
    r"How many standard drinks containing alcohol do you have on a typical day\?\s*:\s*(.+)",
    re.IGNORECASE,
)
RE_AUDIT_C_Q3 = re.compile(
    r"How often do you have six or more drinks on one occasion\?\s*:\s*(.+)",
    re.IGNORECASE,
)

# DAST-10 Q&A (match the common first question — others follow same format)
RE_DAST_Q = re.compile(
    r"(?:Have you used drugs other than those required for medical reasons|"
    r"Do you abuse more than one drug at a time|"
    r"Are you always able to stop using drugs when you want to|"
    r"Have you ever had blackouts or flashbacks as a result of drug use|"
    r"Do you ever feel bad or guilty about your drug use|"
    r"Does your spouse.*ever complain about your involvement with drugs|"
    r"Have you neglected your family because of your use of drugs|"
    r"Have you engaged in illegal activities in order to obtain drugs|"
    r"Have you ever experienced withdrawal symptoms.*when you stopped taking drugs|"
    r"Have you had medical problems as a result of your drug use)"
    r".*?\?\s*(?:\(.*?\)\s*)?:\s*(.+)",
    re.IGNORECASE,
)

# Injury question (common to both narrative and flowsheet)
RE_INJURY_Q = re.compile(
    r"Does the patient have an injury\?\s*:\s*(.+)",
    re.IGNORECASE,
)

# ── Flowsheet question column identifiers (Pattern B) ──────────────
# Canonical question text fragments for column matching.
_FLOWSHEET_Q_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("injury", re.compile(r"Does the patient have an injury\?", re.IGNORECASE)),
    ("drug_use", re.compile(
        r"Have you used drugs other than those required for medical reasons",
        re.IGNORECASE)),
    ("alcohol_testing", re.compile(
        r"Do you drink alcohol\?.*(?:blood alcohol testing)?",
        re.IGNORECASE)),
    ("alcohol_history", re.compile(
        r"Do you have a history of alcohol use or withdrawals\?",
        re.IGNORECASE)),
    ("audit_c_q1", re.compile(
        r"How often do you have a drink containing alcohol\?",
        re.IGNORECASE)),
    ("audit_c_q2", re.compile(
        r"How many standard drinks",
        re.IGNORECASE)),
    ("audit_c_q3", re.compile(
        r"How often do you have six or more drinks",
        re.IGNORECASE)),
    ("audit_c_score", RE_FLOWSHEET_AUDIT_C_HEADER),
]

# ── Refusal and admission patterns ──────────────────────────────────
RE_SCREENING_REFUSAL = re.compile(
    r"(?:patient\s+)?(?:refused|declined)\s+(?:SBIRT|AUDIT|DAST|screening|"
    r"alcohol\s+screening|drug\s+screening)",
    re.IGNORECASE,
)

# Substance use admission: explicit statement in SBIRT context
RE_SUBSTANCE_ADMISSION = re.compile(
    r"(?:patient|pt)\s+(?:admits?|reports?|acknowledges?)\s+(?:to\s+)?"
    r"(?:alcohol|drug|substance)\s+use",
    re.IGNORECASE,
)

# Nurse marker strip: "Yes A" → "Yes", "No B" → "No"
RE_NURSE_MARKER = re.compile(r"\s+[A-Z]$")


# ── Helpers ─────────────────────────────────────────────────────────

def _make_raw_line_id(
    source_type: str,
    source_id: Optional[str],
    line_text: str,
) -> str:
    """Build a deterministic raw_line_id from evidence coordinates."""
    payload = f"{source_type}|{source_id or ''}|{line_text.strip()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _snippet(text: str, max_len: int = 120) -> str:
    """Trim text to a short deterministic snippet."""
    text = str(text).strip()
    if len(text) <= max_len:
        return text
    return text[:max_len] + "\u2026"


def _strip_nurse_marker(val: str) -> str:
    """Strip trailing single-letter nurse marker from flowsheet value."""
    return RE_NURSE_MARKER.sub("", val.strip())


def _validate_score_range(value: int, name: str) -> Optional[str]:
    """Return warning string if out-of-range, else None."""
    ranges = {
        "audit_c": (0, 12),
        "dast_10": (0, 10),
        "cage": (0, 4),
    }
    lo, hi = ranges.get(name, (0, 99))
    if value < lo or value > hi:
        return f"{name}_out_of_range: value={value} expected {lo}-{hi}"
    return None


def _is_flowsheet_blank(val: str) -> bool:
    """Check if a flowsheet cell is blank/dash (no data)."""
    stripped = val.strip()
    return stripped in ("", "—", "-", "--", "N/A")


# ── Score extraction (from text) ────────────────────────────────────

def _extract_scores(
    text: str,
    source_type: str,
    source_id: Optional[str],
    ts: Optional[str],
) -> Dict[str, Any]:
    """
    Extract explicit numeric scores from text.
    Returns dict with audit_c, dast_10, cage score results + evidence.
    """
    results: Dict[str, Any] = {
        "audit_c": None,
        "dast_10": None,
        "cage": None,
        "evidence": [],
    }

    def _add_ev(label: str, m: re.Match, ctx: str) -> str:
        window = ctx[max(0, m.start() - 40):m.end() + 40]
        raw_line_id = _make_raw_line_id(source_type, source_id, window)
        results["evidence"].append({
            "raw_line_id": raw_line_id,
            "source": source_type,
            "ts": ts,
            "snippet": _snippet(window),
            "role": "score",
            "label": label,
        })
        return raw_line_id

    for regex, name, rule_id in [
        (RE_AUDIT_C, "audit_c", "sbirt_section_audit_c"),
        (RE_DAST_10, "dast_10", "sbirt_section_dast_10"),
        (RE_CAGE, "cage", "sbirt_section_cage"),
    ]:
        m = regex.search(text)
        if m:
            try:
                value = int(m.group(1))
                raw_id = _add_ev(name, m, text)
                results[name] = {
                    "value": value,
                    "ts": ts,
                    "source_rule_id": rule_id,
                    "evidence": [{
                        "raw_line_id": raw_id,
                        "source": source_type,
                        "ts": ts,
                        "snippet": _snippet(text[max(0, m.start() - 40):m.end() + 40]),
                        "role": "score",
                    }],
                }
            except (ValueError, IndexError):
                pass

    # Flowsheet fallback for AUDIT-C
    if results["audit_c"] is None:
        _try_flowsheet_audit_c(text, source_type, source_id, ts, results)

    return results


def _try_flowsheet_audit_c(
    text: str,
    source_type: str,
    source_id: Optional[str],
    ts: Optional[str],
    results: Dict[str, Any],
) -> None:
    """Try to extract AUDIT-C score from flowsheet-style layout."""
    lines = text.split("\n")
    header_idx: Optional[int] = None
    col_idx: Optional[int] = None

    for i, line in enumerate(lines):
        if RE_FLOWSHEET_AUDIT_C_HEADER.search(line):
            cols = line.split("\t")
            for j, col in enumerate(cols):
                if RE_FLOWSHEET_AUDIT_C_HEADER.search(col):
                    header_idx = i
                    col_idx = j
                    break
            if col_idx is not None:
                break

    if header_idx is None or col_idx is None:
        return

    for i in range(header_idx + 1, min(header_idx + 20, len(lines))):
        line = lines[i].strip()
        if not line:
            continue
        cols = line.split("\t")
        if col_idx < len(cols):
            val_str = cols[col_idx].strip()
            if val_str.isdigit():
                value = int(val_str)
                raw_line_id = _make_raw_line_id(source_type, source_id, line)
                results["evidence"].append({
                    "raw_line_id": raw_line_id,
                    "source": source_type,
                    "ts": ts,
                    "snippet": _snippet(line),
                    "role": "score",
                    "label": "audit_c",
                })
                results["audit_c"] = {
                    "value": value,
                    "ts": ts,
                    "source_rule_id": "flowsheet_audit_c",
                    "evidence": [{
                        "raw_line_id": raw_line_id,
                        "source": source_type,
                        "ts": ts,
                        "snippet": _snippet(line),
                        "role": "score",
                    }],
                }
                return


# ── Narrative Q&A extraction (Pattern A) ────────────────────────────

def _extract_narrative_responses(
    text: str,
    source_type: str,
    source_id: Optional[str],
    ts: Optional[str],
) -> Dict[str, Any]:
    """
    Extract inline question-answer pairs from narrative consult notes.

    Returns dict with:
      instrument: "audit_c" | "dast_10" | "sbirt_consult"
      responses: list of {question_id, question_text, answer, raw_line_id}
      completion_status: "complete" | "partial" | "none"
    """
    responses: List[Dict[str, Any]] = []
    evidence: List[Dict[str, Any]] = []

    # AUDIT-C questions
    audit_c_qs = [
        ("audit_c_q1", RE_AUDIT_C_Q1),
        ("audit_c_q2", RE_AUDIT_C_Q2),
        ("audit_c_q3", RE_AUDIT_C_Q3),
    ]
    audit_c_found = 0

    for qid, regex in audit_c_qs:
        m = regex.search(text)
        if m:
            answer = m.group(1).strip()
            raw_id = _make_raw_line_id(
                source_type, source_id,
                text[max(0, m.start() - 20):m.end() + 20],
            )
            responses.append({
                "question_id": qid,
                "question_text": _snippet(m.group(0).split("?:")[0] + "?", 120),
                "answer": answer,
                "instrument": "audit_c",
                "raw_line_id": raw_id,
            })
            evidence.append({
                "raw_line_id": raw_id,
                "source": source_type,
                "ts": ts,
                "snippet": _snippet(text[max(0, m.start() - 20):m.end() + 20]),
                "role": "response",
                "label": qid,
            })
            audit_c_found += 1

    # DAST-10 questions
    dast_found = 0
    dast_q_num = 0
    for m in RE_DAST_Q.finditer(text):
        dast_q_num += 1
        answer = m.group(1).strip()
        raw_id = _make_raw_line_id(
            source_type, source_id,
            text[max(0, m.start() - 20):m.end() + 20],
        )
        qid = f"dast_10_q{dast_q_num}"
        responses.append({
            "question_id": qid,
            "question_text": _snippet(m.group(0).split("?:")[0].split("?)")[0] + "?", 120),
            "answer": answer,
            "instrument": "dast_10",
            "raw_line_id": raw_id,
        })
        evidence.append({
            "raw_line_id": raw_id,
            "source": source_type,
            "ts": ts,
            "snippet": _snippet(text[max(0, m.start() - 20):m.end() + 20]),
            "role": "response",
            "label": qid,
        })
        dast_found += 1

    # Injury question
    m = RE_INJURY_Q.search(text)
    if m:
        answer = m.group(1).strip()
        raw_id = _make_raw_line_id(
            source_type, source_id,
            text[max(0, m.start() - 20):m.end() + 20],
        )
        responses.append({
            "question_id": "injury",
            "question_text": "Does the patient have an injury?",
            "answer": answer,
            "instrument": "sbirt_general",
            "raw_line_id": raw_id,
        })
        evidence.append({
            "raw_line_id": raw_id,
            "source": source_type,
            "ts": ts,
            "snippet": _snippet(text[max(0, m.start() - 20):m.end() + 20]),
            "role": "response",
            "label": "injury",
        })

    # Determine instruments and completion
    instruments_detected: List[str] = []
    if audit_c_found > 0:
        instruments_detected.append("audit_c")
    if dast_found > 0:
        instruments_detected.append("dast_10")

    return {
        "responses": responses,
        "evidence": evidence,
        "instruments_detected": instruments_detected,
        "audit_c_responses_count": audit_c_found,
        "dast_10_responses_count": dast_found,
    }


# ── Flowsheet Q&A extraction (Pattern B) ───────────────────────────

def _extract_flowsheet_responses(
    text: str,
    source_type: str,
    source_id: Optional[str],
    ts: Optional[str],
) -> Dict[str, Any]:
    """
    Extract question-answer pairs from a tab-delimited flowsheet.

    Flowsheet format:
      Header: Date/Time\\t<Question1>\\t<Question2>\\t...
      Data:   12/18/25 1445\\tNo A\\tYes B\\t...

    Returns dict with responses[], evidence[], instruments_detected[].
    """
    responses: List[Dict[str, Any]] = []
    evidence: List[Dict[str, Any]] = []
    instruments_detected: List[str] = []

    lines = text.split("\n")
    header_idx: Optional[int] = None
    col_map: Dict[int, Tuple[str, str]] = {}  # col_idx → (question_id, question_text)

    # Find header row by looking for a tab-delimited line with Date/Time
    # and at least one recognized SBIRT question
    for i, line in enumerate(lines):
        if "\t" not in line:
            continue
        cols = line.split("\t")
        if len(cols) < 2:
            continue

        # Check first col for Date/Time header
        first_col = cols[0].strip()
        if not re.search(r"Date\s*/?\s*Time", first_col, re.IGNORECASE):
            continue

        # Map columns to known questions
        temp_map: Dict[int, Tuple[str, str]] = {}
        for j, col_text in enumerate(cols[1:], start=1):
            for q_id, q_pattern in _FLOWSHEET_Q_PATTERNS:
                if q_pattern.search(col_text):
                    temp_map[j] = (q_id, col_text.strip())
                    break

        if temp_map:
            header_idx = i
            col_map = temp_map
            break

    if header_idx is None or not col_map:
        return {
            "responses": [],
            "evidence": [],
            "instruments_detected": [],
            "flowsheet_rows_parsed": 0,
        }

    # Determine instruments from column types
    col_ids = {v[0] for v in col_map.values()}
    if col_ids & {"audit_c_q1", "audit_c_q2", "audit_c_q3", "audit_c_score"}:
        instruments_detected.append("audit_c")
    # The short-form questions are generic SBIRT screening, not instrument-specific
    if col_ids & {"injury", "drug_use", "alcohol_testing", "alcohol_history"}:
        if "sbirt_flowsheet" not in instruments_detected:
            instruments_detected.append("sbirt_flowsheet")

    # Parse data rows (take the first complete row — most recent assessment)
    rows_parsed = 0
    for i in range(header_idx + 1, min(header_idx + 30, len(lines))):
        line = lines[i].strip()
        if not line:
            continue
        cols = line.split("\t")
        if len(cols) < 2:
            continue
        # First col should look like a date/time
        if not re.match(r"\d{1,2}/\d{1,2}/\d{2,4}", cols[0].strip()):
            continue

        rows_parsed += 1
        row_ts_str = cols[0].strip()

        for col_idx, (q_id, q_text) in col_map.items():
            if col_idx >= len(cols):
                continue
            raw_val = cols[col_idx].strip()
            if _is_flowsheet_blank(raw_val):
                continue

            # Strip nurse marker
            answer = _strip_nurse_marker(raw_val)
            if not answer:
                continue

            raw_id = _make_raw_line_id(source_type, source_id, f"{row_ts_str}|{q_id}|{raw_val}")
            responses.append({
                "question_id": q_id,
                "question_text": _snippet(q_text, 120),
                "answer": answer,
                "instrument": "audit_c" if q_id.startswith("audit_c") else "sbirt_flowsheet",
                "flowsheet_row_ts": row_ts_str,
                "raw_line_id": raw_id,
            })
            evidence.append({
                "raw_line_id": raw_id,
                "source": source_type,
                "ts": ts,
                "snippet": _snippet(f"{row_ts_str}\t{raw_val} [{q_id}]"),
                "role": "response",
                "label": q_id,
            })

        # Only take the first (most recent) data row for structured responses
        break

    return {
        "responses": responses,
        "evidence": evidence,
        "instruments_detected": instruments_detected,
        "flowsheet_rows_parsed": rows_parsed,
    }


# ── Refusal / admission extraction ─────────────────────────────────

def _extract_refusal_and_admission(
    text: str,
    source_type: str,
    source_id: Optional[str],
    ts: Optional[str],
) -> Dict[str, Any]:
    """Extract screening refusal and substance use admission documentation."""
    result: Dict[str, Any] = {
        "refusal_documented": False,
        "refusal_evidence": [],
        "substance_use_admission_documented": False,
        "substance_use_admission_evidence": [],
    }

    m = RE_SCREENING_REFUSAL.search(text)
    if m:
        raw_id = _make_raw_line_id(
            source_type, source_id,
            text[max(0, m.start() - 30):m.end() + 30],
        )
        result["refusal_documented"] = True
        result["refusal_evidence"].append({
            "raw_line_id": raw_id,
            "source": source_type,
            "ts": ts,
            "snippet": _snippet(text[max(0, m.start() - 30):m.end() + 30]),
            "role": "refusal",
        })

    m = RE_SUBSTANCE_ADMISSION.search(text)
    if m:
        raw_id = _make_raw_line_id(
            source_type, source_id,
            text[max(0, m.start() - 30):m.end() + 30],
        )
        result["substance_use_admission_documented"] = True
        result["substance_use_admission_evidence"].append({
            "raw_line_id": raw_id,
            "source": source_type,
            "ts": ts,
            "snippet": _snippet(text[max(0, m.start() - 30):m.end() + 30]),
            "role": "admission",
        })

    return result


# ── Unified per-item scanner ───────────────────────────────────────

def _scan_item(
    text: str,
    source_type: str,
    source_id: Optional[str],
    ts: Optional[str],
) -> Dict[str, Any]:
    """
    Scan a single timeline item text for all SBIRT screening data.

    Returns unified result with scores, responses, refusal, admission,
    evidence, notes.
    """
    # 1. Scores
    scores = _extract_scores(text, source_type, source_id, ts)

    # 2. Narrative responses (Pattern A)
    narrative = _extract_narrative_responses(text, source_type, source_id, ts)

    # 3. Flowsheet responses (Pattern B) — only if no narrative responses found
    flowsheet: Dict[str, Any] = {
        "responses": [], "evidence": [], "instruments_detected": [],
        "flowsheet_rows_parsed": 0,
    }
    if not narrative["responses"]:
        flowsheet = _extract_flowsheet_responses(text, source_type, source_id, ts)

    # 4. Refusal and admission
    refusal = _extract_refusal_and_admission(text, source_type, source_id, ts)

    # Merge responses
    all_responses = narrative["responses"] + flowsheet["responses"]
    all_evidence = (
        scores["evidence"]
        + narrative["evidence"]
        + flowsheet["evidence"]
        + refusal.get("refusal_evidence", [])
        + refusal.get("substance_use_admission_evidence", [])
    )

    # Merge instruments
    instruments = list(dict.fromkeys(
        narrative["instruments_detected"] + flowsheet["instruments_detected"]
    ))

    # Notes
    notes: List[str] = []
    has_sbirt_mention = bool(re.search(r"\bSBIRT\b", text))
    has_any_content = bool(
        scores["audit_c"] or scores["dast_10"] or scores["cage"]
        or all_responses or refusal["refusal_documented"]
    )
    if has_sbirt_mention and not has_any_content:
        notes.append(
            "sbirt_section_found_no_extractable_data: SBIRT mention present "
            "but no scores, responses, or refusal extracted"
        )

    return {
        "scores": scores,
        "responses": all_responses,
        "evidence": all_evidence,
        "instruments_detected": instruments,
        "refusal_documented": refusal["refusal_documented"],
        "refusal_evidence": refusal.get("refusal_evidence", []),
        "substance_use_admission_documented": refusal["substance_use_admission_documented"],
        "substance_use_admission_evidence": refusal.get("substance_use_admission_evidence", []),
        "notes": notes,
    }


# ── Main extractor ──────────────────────────────────────────────────

def extract_sbirt_screening(
    pat_features: Dict[str, Any],
    days_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Extract SBIRT screening data from patient timeline.

    Args:
        pat_features: partial patient features dict (unused, API compat).
        days_data: full patient_days_v1.json dict.

    Returns:
        Structured dict with screening presence, per-instrument scores,
        question-level responses, refusal/admission documentation,
        evidence, notes, warnings.
    """
    all_evidence: List[Dict[str, Any]] = []
    all_responses: List[Dict[str, Any]] = []
    all_notes: List[str] = []
    all_warnings: List[str] = []
    all_instruments: List[str] = []

    # Best scores (first-found-wins per instrument)
    best_audit_c: Optional[Dict[str, Any]] = None
    best_dast_10: Optional[Dict[str, Any]] = None
    best_cage: Optional[Dict[str, Any]] = None

    # Refusal / admission (any-found)
    refusal_documented = False
    refusal_evidence: List[Dict[str, Any]] = []
    substance_admission_documented = False
    substance_admission_evidence: List[Dict[str, Any]] = []

    # Responses collected (first complete set wins per instrument)
    responses_collected = False

    days = days_data.get("days", {})
    if not days:
        return _build_result(
            audit_c=None, dast_10=None, cage=None,
            responses=[], instruments=[],
            refusal_documented=False, refusal_evidence=[],
            substance_admission_documented=False,
            substance_admission_evidence=[],
            evidence=[], notes=["no_days_data"], warnings=[],
        )

    sorted_days = sorted(days.keys())

    for day_key in sorted_days:
        day_val = days[day_key]
        items = day_val.get("items", [])

        for item in items:
            item_type = item.get("type", "")
            if item_type not in _SOURCE_TYPES:
                continue

            text = (item.get("payload") or {}).get("text", "")
            if not text.strip():
                continue

            item_ts = item.get("dt")
            item_id = item.get("id")

            scan = _scan_item(text, item_type, item_id, item_ts)

            # Collect evidence and notes
            all_evidence.extend(scan["evidence"])
            all_notes.extend(scan["notes"])

            # Scores: first-found-wins
            scores = scan["scores"]
            if best_audit_c is None and scores["audit_c"] is not None:
                best_audit_c = scores["audit_c"]
            if best_dast_10 is None and scores["dast_10"] is not None:
                best_dast_10 = scores["dast_10"]
            if best_cage is None and scores["cage"] is not None:
                best_cage = scores["cage"]

            # Responses: collect all (but first set wins for completeness)
            if scan["responses"]:
                if not responses_collected:
                    all_responses.extend(scan["responses"])
                    responses_collected = True

            # Instruments
            for inst in scan["instruments_detected"]:
                if inst not in all_instruments:
                    all_instruments.append(inst)

            # Refusal / admission
            if scan["refusal_documented"]:
                refusal_documented = True
                refusal_evidence.extend(scan["refusal_evidence"])
            if scan["substance_use_admission_documented"]:
                substance_admission_documented = True
                substance_admission_evidence.extend(
                    scan["substance_use_admission_evidence"]
                )

    # Score range validation
    for score_obj, name in [
        (best_audit_c, "audit_c"),
        (best_dast_10, "dast_10"),
        (best_cage, "cage"),
    ]:
        if score_obj is not None:
            w = _validate_score_range(score_obj["value"], name)
            if w:
                all_warnings.append(w)

    return _build_result(
        audit_c=best_audit_c, dast_10=best_dast_10, cage=best_cage,
        responses=all_responses, instruments=all_instruments,
        refusal_documented=refusal_documented,
        refusal_evidence=refusal_evidence,
        substance_admission_documented=substance_admission_documented,
        substance_admission_evidence=substance_admission_evidence,
        evidence=all_evidence, notes=all_notes, warnings=all_warnings,
    )


def _build_result(
    audit_c: Optional[Dict[str, Any]],
    dast_10: Optional[Dict[str, Any]],
    cage: Optional[Dict[str, Any]],
    responses: List[Dict[str, Any]],
    instruments: List[str],
    refusal_documented: bool,
    refusal_evidence: List[Dict[str, Any]],
    substance_admission_documented: bool,
    substance_admission_evidence: List[Dict[str, Any]],
    evidence: List[Dict[str, Any]],
    notes: List[str],
    warnings: List[str],
) -> Dict[str, Any]:
    """Assemble the final output dict."""
    any_score = (audit_c is not None
                 or dast_10 is not None
                 or cage is not None)
    has_responses = len(responses) > 0

    if any_score or has_responses:
        present = "yes"
    elif refusal_documented:
        present = "refused"
    elif any("sbirt_section_found" in n for n in notes):
        present = "no"
    else:
        present = _DNA

    # Per-instrument completion
    audit_c_completion = "not_performed"
    if audit_c is not None:
        audit_c_completion = "score_documented"
    elif any(r["instrument"] == "audit_c" for r in responses):
        audit_c_count = sum(1 for r in responses if r["instrument"] == "audit_c")
        audit_c_completion = "responses_only" if audit_c_count < 3 else "responses_complete"

    dast_10_completion = "not_performed"
    if dast_10 is not None:
        dast_10_completion = "score_documented"
    elif any(r["instrument"] == "dast_10" for r in responses):
        dast_10_completion = "responses_only"

    cage_completion = "not_performed"
    if cage is not None:
        cage_completion = "score_documented"

    return {
        "sbirt_screening_present": present,
        "instruments_detected": instruments,

        "audit_c": {
            "explicit_score": audit_c,
            "responses_present": any(
                r["instrument"] == "audit_c" for r in responses
            ),
            "responses": [r for r in responses if r["instrument"] == "audit_c"],
            "completion_status": audit_c_completion,
        },

        "dast_10": {
            "explicit_score": dast_10,
            "responses_present": any(
                r["instrument"] == "dast_10" for r in responses
            ),
            "responses": [r for r in responses if r["instrument"] == "dast_10"],
            "completion_status": dast_10_completion,
        },

        "cage": {
            "explicit_score": cage,
            "responses_present": False,  # CAGE responses not yet seen in data
            "responses": [],
            "completion_status": cage_completion,
        },

        "flowsheet_responses": [
            r for r in responses
            if r.get("instrument") == "sbirt_flowsheet"
        ],

        "refusal_documented": refusal_documented,
        "refusal_evidence": refusal_evidence,

        "substance_use_admission_documented": substance_admission_documented,
        "substance_use_admission_evidence": substance_admission_evidence,

        "evidence": evidence,
        "notes": notes,
        "warnings": warnings,
    }
