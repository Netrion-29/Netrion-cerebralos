#!/usr/bin/env python3
"""
GREEN CARD v1 – Adjunct field extractor.

Extracts protocol-critical adjunct fields from patient evidence:
  - spine_clearance
  - dvt_prophylaxis
  - first_ed_temp
  - gi_prophylaxis
  - bowel_regimen

Design:
- Deterministic regex, fail-closed. No LLM, no ML, no inference.
- H&P-first, source-priority: TRAUMA_HP > ED > PROGRESS > CONSULT/OP > IMAGING > DISCHARGE
- If not found, fields default to UNKNOWN/NO (fail-closed).
- DVT first_admin_dt comes only from MAR/admin evidence; order alone → null.
- Temperature: only ED/initial vitals context. If ambiguous, use earliest + warning.
- Spine clearance: do NOT infer from negative CT alone; require explicit clearance
  language OR negative imaging + collar removal order.

Usage (called by extract_green_card_v1):
    from cerebralos.green_card.extract_green_card_adjuncts_v1 import extract_adjuncts
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime as _dt
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── paths ───────────────────────────────────────────────────────────
_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent.parent
_ADJUNCT_RULES_PATH = (
    _REPO_ROOT / "rules" / "green_card" / "green_card_adjunct_patterns_v1.json"
)

# ── doc-type priority (mirrors extract_green_card_v1) ───────────────
_DEFAULT_PRIORITY = {
    "trauma_hp": 1,
    "ed_note": 2,
    "trauma_progress": 3,
    "consult_note": 4,
    "op_note": 4,
    "imaging": 5,
    "other": 8,
    "discharge_summary": 9,
}


# ── helpers ─────────────────────────────────────────────────────────
def _load_adjunct_config() -> Dict[str, Any]:
    if not _ADJUNCT_RULES_PATH.is_file():
        print(
            f"FATAL: adjunct patterns not found: {_ADJUNCT_RULES_PATH}",
            file=sys.stderr,
        )
        sys.exit(1)
    with open(_ADJUNCT_RULES_PATH, encoding="utf-8") as f:
        return json.load(f)


def _line_preview(text: str, match: re.Match, context: int = 60) -> str:
    start = max(0, match.start() - context)
    end = min(len(text), match.end() + context)
    return text[start:end].replace("\n", " ").strip()[:250]


def _make_source(doc_type: str, priority: int, item_idx: int,
                 line_id: str, preview: str) -> Dict[str, Any]:
    return {
        "source_type": doc_type.upper(),
        "priority": priority,
        "item_id": item_idx,
        "source_line_id": line_id,
        "preview": preview[:200],
    }


def _get_priority(doc_type: str, cfg: Optional[Dict[str, Any]] = None) -> int:
    prio_map = (cfg or {}).get("doc_type_priority", _DEFAULT_PRIORITY)
    return prio_map.get(doc_type, 8)


def _try_iso_from_item(item: Dict[str, Any]) -> Optional[str]:
    """Return ISO datetime string from an evidence item if present."""
    dt = item.get("datetime") or item.get("ts") or item.get("date")
    if dt and isinstance(dt, str):
        return dt
    return None


def _search_any(patterns: List[str], text: str) -> Optional[re.Match]:
    """Return the first match from a list of regex pattern strings."""
    for pat_str in patterns:
        try:
            m = re.search(pat_str, text)
            if m:
                return m
        except re.error:
            continue
    return None


# ── spine clearance: Order Questions parser ─────────────────────────

def _parse_ordered_on_dt(date_str: str, time_str: str) -> Optional[str]:
    """Parse 'Ordered On' date/time → ISO string.

    E.g. ('12/19/2025', '0740') → '2025-12-19T07:40:00'
    """
    try:
        parts = date_str.split("/")
        month, day, year = int(parts[0]), int(parts[1]), int(parts[2])
        if year < 100:
            year += 2000
        hour = int(time_str[:2])
        minute = int(time_str[2:4])
        return _dt(year, month, day, hour, minute).isoformat()
    except (ValueError, IndexError):
        return None


def _extract_spine_clearance_orders(
    all_items: List[Dict[str, Any]],
    acfg: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Extract spine clearance data from 'Order Questions' blocks.

    Scans ALL evidence items (regardless of doc_type) for Epic-style
    order-question blocks containing cervical / thoraco-lumbar spine
    clearance answers.

    Returns a list of order records, each containing:
        item_idx, ordered_dt (ISO or None),
        cspine (YES/NO/UNKNOWN), tlspine (YES/NO/UNKNOWN),
        source dict, preview str
    Ordered by appearance (item index then line position).
    """
    spec = acfg.get("spine_clearance", {})
    oq_block = spec.get("spine_order_questions_block", {})
    header_pats = oq_block.get("header_patterns", [])
    ordered_on_pat_str = oq_block.get("ordered_on_pattern", "")

    q_pats = spec.get("spine_question_patterns", {})
    cspine_pat = q_pats.get("cspine", "")
    tlspine_pat = q_pats.get("tlspine", "")

    a_pats = spec.get("spine_answer_patterns", {})
    yes_pat = a_pats.get("yes", r"^\s*Yes\s*$")
    no_pat = a_pats.get("no", r"^\s*No\s*$")

    if not header_pats or not cspine_pat:
        return []

    order_records: List[Dict[str, Any]] = []

    for item in all_items:
        text = item.get("text", "") or ""
        if not text:
            continue
        item_idx = item.get("idx", -1)
        line_start = item.get("line_start", 0)

        lines = text.split("\n")

        # Scan for "Order Questions" header lines
        i = 0
        while i < len(lines):
            line = lines[i]

            # Check for "Order Questions" header
            is_oq_header = False
            for hp in header_pats:
                try:
                    if re.search(hp, line.strip()):
                        is_oq_header = True
                        break
                except re.error:
                    continue

            if not is_oq_header:
                i += 1
                continue

            # Found "Order Questions" header.  Look ahead for
            # "Question  Answer" sub-header, then spine rows.
            # Also look backward for "Ordered On  <date> <time>"
            # within about 30 lines.
            ordered_dt: Optional[str] = None
            if ordered_on_pat_str:
                lookback_start = max(0, i - 30)
                lookback_text = "\n".join(lines[lookback_start:i])
                try:
                    m_dt = re.search(ordered_on_pat_str, lookback_text)
                    if m_dt:
                        ordered_dt = _parse_ordered_on_dt(
                            m_dt.group(1), m_dt.group(2)
                        )
                except re.error:
                    pass

            # Scan up to 10 lines after the header for question rows
            cspine_answer: Optional[str] = None
            tlspine_answer: Optional[str] = None
            preview_lines: List[str] = []
            j = i + 1
            scan_limit = min(len(lines), i + 12)
            while j < scan_limit:
                row = lines[j]
                stripped = row.strip()

                # Skip the "Question  Answer" sub-header
                if re.match(r"^Question\s+Answer\b", stripped):
                    j += 1
                    continue

                # Check for cspine question
                try:
                    if re.search(cspine_pat, stripped):
                        # Answer is the trailing word(s) after the question
                        # In tab-delimited Epic exports: "Cervical Spine Clearance\tYes"
                        answer_part = re.split(
                            cspine_pat, stripped, maxsplit=1
                        )[-1].strip()
                        if re.match(yes_pat, answer_part):
                            cspine_answer = "YES"
                        elif re.match(no_pat, answer_part):
                            cspine_answer = "NO"
                        else:
                            cspine_answer = "UNKNOWN"
                        preview_lines.append(stripped)
                except re.error:
                    pass

                # Check for tlspine question
                try:
                    if re.search(tlspine_pat, stripped):
                        answer_part = re.split(
                            tlspine_pat, stripped, maxsplit=1
                        )[-1].strip()
                        if re.match(yes_pat, answer_part):
                            tlspine_answer = "YES"
                        elif re.match(no_pat, answer_part):
                            tlspine_answer = "NO"
                        else:
                            tlspine_answer = "UNKNOWN"
                        preview_lines.append(stripped)
                except re.error:
                    pass

                # Stop scanning if we hit an empty line after finding
                # at least one answer, or another section header
                if (cspine_answer or tlspine_answer) and not stripped:
                    break

                j += 1

            # Only record if we found at least one spine answer
            if cspine_answer is not None or tlspine_answer is not None:
                line_id = f"L{line_start + i}-L{line_start + j}"
                preview = "; ".join(preview_lines)[:200]
                order_records.append({
                    "item_idx": item_idx,
                    "ordered_dt": ordered_dt,
                    "cspine": cspine_answer or "UNKNOWN",
                    "tlspine": tlspine_answer or "UNKNOWN",
                    "line_id": line_id,
                    "preview": preview,
                })

            i = j  # advance past this block

    return order_records


def _resolve_final_order_status(
    order_records: List[Dict[str, Any]],
    region_key: str,
) -> Tuple[str, Optional[str]]:
    """Determine the final clearance answer for a region across all order records.

    Selection: prefer latest timestamped record; ties broken by higher
    item_idx (later appearance in the chart).  Returns (answer, iso_dt).
    """
    if not order_records:
        return "UNKNOWN", None

    # Filter to records that have a non-UNKNOWN answer for this region
    relevant = [r for r in order_records if r.get(region_key, "UNKNOWN") != "UNKNOWN"]
    if not relevant:
        return "UNKNOWN", None

    def _sort_key(rec: Dict[str, Any]) -> Tuple[str, int]:
        dt = rec.get("ordered_dt") or ""
        return (dt, rec.get("item_idx", -1))

    relevant.sort(key=_sort_key)
    final = relevant[-1]
    return final[region_key], final.get("ordered_dt")


# ── spine_clearance ─────────────────────────────────────────────────
def _extract_spine_clearance(
    classified_items: List[Tuple[Dict, str, int]],
    acfg: Dict[str, Any],
    all_items: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Extract spine clearance status from classified evidence items.

    Combines:
    1. Phrase-based detection (cleared/not-cleared/imaging).
    2. Order Questions block parsing (cspine + tlspine per-region).
    """
    spec = acfg.get("spine_clearance", {})
    cleared_pats = spec.get("cleared_phrases", [])
    not_cleared_pats = spec.get("not_cleared_phrases", [])
    imaging_marker_pats = spec.get("imaging_markers", [])
    imaging_neg_pats = spec.get("imaging_negative_results", [])
    method_clinical_pats = spec.get("method_clinical", [])
    method_imaging_pats = spec.get("method_imaging", [])

    best_status: Optional[str] = None
    best_method: Optional[str] = None
    best_priority: int = 99
    details: List[str] = []
    sources: List[Dict[str, Any]] = []
    seen_details: set = set()

    has_neg_imaging = False
    has_clear_language = False

    for item, doc_type, prio in classified_items:
        text = item.get("text", "") or ""
        item_idx = item.get("idx", -1)
        line_id = f"L{item.get('line_start', 0)}-L{item.get('line_end', 0)}"

        # Check explicit CLEARED phrases
        for pat_str in cleared_pats:
            try:
                m = re.search(pat_str, text)
            except re.error:
                continue
            if m:
                has_clear_language = True
                detail = m.group(0).strip()
                if detail.lower() not in seen_details:
                    details.append(detail)
                    seen_details.add(detail.lower())
                if prio < best_priority or best_status != "CLEAR":
                    best_status = "CLEAR"
                    best_priority = prio
                    sources.append(
                        _make_source(doc_type, prio, item_idx, line_id,
                                     _line_preview(text, m))
                    )

        # Check NOT_CLEARED phrases
        for pat_str in not_cleared_pats:
            try:
                m = re.search(pat_str, text)
            except re.error:
                continue
            if m:
                detail = m.group(0).strip()
                if detail.lower() not in seen_details:
                    details.append(detail)
                    seen_details.add(detail.lower())
                # NOT_CLEAR only wins if no CLEAR found at same/higher priority
                if best_status != "CLEAR" or prio < best_priority:
                    if best_status != "CLEAR":
                        best_status = "NOT_CLEAR"
                        best_priority = prio
                        sources.append(
                            _make_source(doc_type, prio, item_idx, line_id,
                                         _line_preview(text, m))
                        )

        # Check imaging markers + negative results
        img_match = _search_any(imaging_marker_pats, text)
        if img_match:
            neg_match = _search_any(imaging_neg_pats, text)
            if neg_match:
                has_neg_imaging = True
                detail_str = neg_match.group(0).strip()
                if detail_str.lower() not in seen_details:
                    details.append(detail_str)
                    seen_details.add(detail_str.lower())
                sources.append(
                    _make_source(doc_type, prio, item_idx, line_id,
                                 _line_preview(text, neg_match))
                )

    # ── Order Questions block parsing ──────────────────────────
    order_records: List[Dict[str, Any]] = []
    has_order_evidence = False
    if all_items:
        order_records = _extract_spine_clearance_orders(all_items, acfg)

    if order_records:
        has_order_evidence = True
        cspine_final, cspine_dt = _resolve_final_order_status(
            order_records, "cspine"
        )
        tlspine_final, tlspine_dt = _resolve_final_order_status(
            order_records, "tlspine"
        )

        # Add order evidence sources
        for rec in order_records:
            oq_dt = rec.get("ordered_dt")
            sources.append({
                "source_type": "ORDER_QUESTION",
                "priority": 0,
                "item_id": rec["item_idx"],
                "source_line_id": rec["line_id"],
                "ts": oq_dt,
                "preview": rec["preview"][:200],
                "order_dt_iso": oq_dt,
                "ordered_dt": oq_dt,
            })
            detail_str = (
                f"Order({rec.get('ordered_dt', '?')}): "
                f"C-spine={rec['cspine']}, T/L-spine={rec['tlspine']}"
            )
            if detail_str not in seen_details:
                details.append(detail_str)
                seen_details.add(detail_str)
    else:
        cspine_final = "UNKNOWN"
        cspine_dt = None
        tlspine_final = "UNKNOWN"
        tlspine_dt = None

    # ── Determine method ────────────────────────────────────────
    all_text_for_method = " ".join(d for d in details)
    has_clinical = bool(_search_any(method_clinical_pats, all_text_for_method))
    has_imaging_method = has_neg_imaging or bool(
        _search_any(method_imaging_pats, all_text_for_method)
    )

    method_parts: List[str] = []
    if has_order_evidence:
        method_parts.append("ORDER")
    if has_clinical:
        method_parts.append("CLINICAL")
    if has_imaging_method:
        method_parts.append("IMAGING")

    if not method_parts:
        best_method = "UNKNOWN"
    elif len(method_parts) == 1:
        best_method = method_parts[0]
    else:
        # Combine: ORDER+IMAGING → "BOTH", ORDER+CLINICAL → "BOTH", etc.
        best_method = "BOTH"

    # ── Determine overall status ────────────────────────────────
    # Order-question evidence takes precedence for final determination.
    if has_order_evidence:
        if cspine_final == "YES" and tlspine_final == "YES":
            best_status = "CLEAR"
        elif cspine_final == "NO" or tlspine_final == "NO":
            best_status = "NOT_CLEAR"
        else:
            # Both UNKNOWN from orders – fall through to phrase-based
            if best_status is None:
                best_status = "UNKNOWN"
    else:
        # No order evidence – use phrase-based determination (original)
        if best_status is None:
            if has_neg_imaging and not has_clear_language:
                best_status = "NOT_CLEAR"
                details.append("Negative imaging without explicit clearance language")
            else:
                best_status = "UNKNOWN"
                best_method = "UNKNOWN"

    # Build regions sub-structure
    regions: Dict[str, Any] = {
        "cspine": {
            "ordered": cspine_final,
            "final_dt": cspine_dt,
        },
        "tlspine": {
            "ordered": tlspine_final,
            "final_dt": tlspine_dt,
        },
    }

    return {
        "status": best_status,
        "method": best_method,
        "regions": regions,
        "details": details if details else [],
        "sources": sources,
    }


# ── dvt_prophylaxis ────────────────────────────────────────────────
def _extract_dvt_prophylaxis(
    classified_items: List[Tuple[Dict, str, int]],
    acfg: Dict[str, Any],
) -> Dict[str, Any]:
    """Extract DVT prophylaxis order and administration data."""
    spec = acfg.get("dvt_prophylaxis", {})
    agent_specs = spec.get("agents", [])
    order_cues = spec.get("order_cues", [])
    admin_cues = spec.get("admin_cues", [])
    dose_pat_str = spec.get("dose_pattern", "")
    route_pat_str = spec.get("route_pattern", "")

    best_agent: Optional[str] = None
    best_dose: Optional[str] = None
    best_route: Optional[str] = None
    first_order_dt: Optional[str] = None
    first_admin_dt: Optional[str] = None
    sources: List[Dict[str, Any]] = []
    warnings: List[str] = []

    order_found = False
    admin_found = False

    for item, doc_type, prio in classified_items:
        text = item.get("text", "") or ""
        item_idx = item.get("idx", -1)
        line_id = f"L{item.get('line_start', 0)}-L{item.get('line_end', 0)}"
        item_dt = _try_iso_from_item(item)

        # Detect DVT prophylaxis agent
        matched_agent: Optional[str] = None
        agent_match: Optional[re.Match] = None
        for agent_spec in agent_specs:
            for pat_str in agent_spec.get("patterns", []):
                try:
                    m = re.search(pat_str, text)
                except re.error:
                    continue
                if m:
                    matched_agent = agent_spec["generic"]
                    agent_match = m
                    break
            if matched_agent:
                break

        if not matched_agent:
            # Also check order cues that mention agents indirectly
            order_match = _search_any(order_cues, text)
            if order_match:
                order_found = True
                if not first_order_dt and item_dt:
                    first_order_dt = item_dt
                sources.append(
                    _make_source(doc_type, prio, item_idx, line_id,
                                 _line_preview(text, order_match))
                )
            continue

        # We have an agent match. Now figure out context: order vs. admin
        # Look within a window around the agent match for dose/route/admin cues
        start = max(0, agent_match.start() - 300)  # type: ignore[union-attr]
        end = min(len(text), agent_match.end() + 300)  # type: ignore[union-attr]
        window = text[start:end]

        is_order = bool(_search_any(order_cues, window))
        is_admin = bool(_search_any(admin_cues, window))

        if best_agent is None:
            best_agent = matched_agent

        # Extract dose
        if dose_pat_str and best_dose is None:
            try:
                dm = re.search(dose_pat_str, window)
                if dm:
                    best_dose = dm.group(1).strip()
            except re.error:
                pass

        # Extract route
        if route_pat_str and best_route is None:
            try:
                rm = re.search(route_pat_str, window)
                if rm:
                    best_route = rm.group(1).strip()
            except re.error:
                pass

        if is_order and not order_found:
            order_found = True
            if not first_order_dt and item_dt:
                first_order_dt = item_dt

        if is_admin and not admin_found:
            admin_found = True
            if not first_admin_dt and item_dt:
                first_admin_dt = item_dt

        sources.append(
            _make_source(doc_type, prio, item_idx, line_id,
                         _line_preview(text, agent_match))  # type: ignore[arg-type]
        )

    # Warnings
    if order_found and not admin_found:
        warnings.append("dvt_order_found_no_admin")
    if admin_found and not order_found:
        warnings.append("dvt_admin_found_no_order")

    # DVT first_admin_dt comes only from MAR/admin evidence
    # If only order exists, first_admin_dt stays null
    return {
        "first_order_dt": first_order_dt,
        "first_admin_dt": first_admin_dt,
        "agent": best_agent,
        "dose": best_dose,
        "route": best_route,
        "sources": sources,
        "warnings": warnings,
    }


# ── first_ed_temp – flowsheet vitals parsing ────────────────────────
#
# Primary strategy: scan ALL evidence items for tabular flowsheet rows
# (e.g.  "12/18/25 1600  98 °F (36.7 °C)  120  20  158/91  96%  …")
# and pick the reading closest to arrival_datetime.
#
# Fallback: scored H&P approach (original logic) if no flowsheet found.
# ────────────────────────────────────────────────────────────────────

# Flowsheet row regex: date HHMM  temp °F …
_FLOWSHEET_ROW_RE = re.compile(
    r"(\d{1,2}/\d{1,2}/\d{2,4})\s+(\d{4})\s+"      # group 1: date, group 2: HHMM
    r"(\d{2,3}(?:\.\d{1,2})?)\s*°\s*F"                # group 3: temp (°F)
)

# Fallback scoring anchors (used only when no flowsheet found)
_ED_ARRIVAL_ANCHORS_RE = re.compile(
    r"(?i)\b(?:ED|Emergency\s+Department|Trauma\s+Bay|Arrival|Initial|"
    r"Triage|Vital\s+Signs?|\bVS\b|Vitals)\b"
)
_ICU_DAILY_ANCHORS_RE = re.compile(
    r"(?i)\b(?:ICU|Floor|Hospital\s+Day|post[- ]?op|POD\s*\d|AM\s+vitals)\b"
)
_TEMP_LINE_START_RE = re.compile(
    r"(?i)(?:^\s*Temp\b|Temp\s*:)"
)
_VITALS_CLUSTER_RE = re.compile(
    r"(?i)\b(?:HR|RR|BP|SpO2|pulse|heart\s+rate|respiratory\s+rate|blood\s+pressure|O2\s+sat)\b"
)


def _parse_flowsheet_dt(date_str: str, time_str: str) -> Optional[_dt]:
    """Parse flowsheet inline timestamp → datetime.

    E.g. ('12/18/25', '1600') → datetime(2025, 12, 18, 16, 0)
    """
    try:
        parts = date_str.split("/")
        month, day, year = int(parts[0]), int(parts[1]), int(parts[2])
        if year < 100:
            year += 2000
        hour = int(time_str[:2])
        minute = int(time_str[2:4])
        return _dt(year, month, day, hour, minute)
    except (ValueError, IndexError):
        return None


def _parse_arrival_dt(arrival_str: Optional[str]) -> Optional[_dt]:
    """Parse arrival_datetime from meta → datetime."""
    if not arrival_str:
        return None
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
    ):
        try:
            return _dt.strptime(arrival_str, fmt)
        except ValueError:
            continue
    return None


def _lines_around(text: str, char_pos: int, radius: int = 6) -> str:
    """Return text of ±radius lines around char_pos."""
    lines = text.split("\n")
    cumlen = 0
    target_line = 0
    for i, ln in enumerate(lines):
        cumlen += len(ln) + 1
        if cumlen > char_pos:
            target_line = i
            break
    lo = max(0, target_line - radius)
    hi = min(len(lines), target_line + radius + 1)
    return "\n".join(lines[lo:hi])


def _match_line_number(text: str, char_pos: int) -> int:
    """Return 0-based line number for a character position."""
    return text[:char_pos].count("\n")


def _score_temp_candidate(
    text: str,
    m: re.Match,
    doc_type: str,
    is_chosen_hp: bool,
) -> Tuple[int, List[str]]:
    """Score a temperature candidate. Returns (score, list_of_anchors_hit).

    Used only in the fallback (non-flowsheet) path.
    """
    score = 0
    anchors: List[str] = []

    if doc_type in ("trauma_hp", "ed_note"):
        score += 5
        anchors.append(f"doc_type={doc_type}")

    if is_chosen_hp:
        line_num = _match_line_number(text, m.start())
        if line_num < 250:
            score += 5
            anchors.append(f"chosen_hp_line={line_num}")

    nearby = _lines_around(text, m.start(), radius=6)

    ed_hit = _ED_ARRIVAL_ANCHORS_RE.search(nearby)
    if ed_hit:
        score += 4
        anchors.append(f"ed_anchor={ed_hit.group(0).strip()}")

    match_line_start = text.rfind("\n", 0, m.start())
    match_line = (
        text[match_line_start + 1: m.end() + 80]
        if match_line_start >= 0
        else text[: m.end() + 80]
    )
    if _TEMP_LINE_START_RE.search(match_line):
        score += 3
        anchors.append("temp_label")

    if _VITALS_CLUSTER_RE.search(nearby):
        score += 2
        anchors.append("vitals_cluster")

    icu_hit = _ICU_DAILY_ANCHORS_RE.search(nearby)
    if icu_hit:
        score -= 3
        anchors.append(f"icu_daily_anchor={icu_hit.group(0).strip()}")

    return score, anchors


# ── first_ed_temp ───────────────────────────────────────────────────
_FLOWSHEET_WINDOW_SECONDS = 4 * 3600  # ±4 hours


def _extract_first_ed_temp(
    classified_items: List[Tuple[Dict, str, int]],
    acfg: Dict[str, Any],
    chosen_trauma_hp_item_id: Optional[int] = None,
    all_items: Optional[List[Dict]] = None,
    arrival_datetime: Optional[str] = None,
) -> Dict[str, Any]:
    """Extract first ED/arrival temperature.

    Strategy
    --------
    1. **Primary**: Scan *all* evidence items for tabular flowsheet vitals
       rows (date HHMM  temp °F …).  Select the reading closest to
       ``arrival_datetime`` within a ±4-hour window.
    2. **Fallback**: If no flowsheet rows matched, use scored regex search
       across classified H&P / ED / progress / discharge items.
    """
    spec = acfg.get("first_ed_temp", {})
    temp_pats = spec.get("temp_patterns", [])
    warnings: List[str] = []

    # ── Strategy 1: flowsheet vitals ────────────────────────────
    arrival_dt = _parse_arrival_dt(arrival_datetime)
    flowsheet_candidates: List[Dict[str, Any]] = []

    scan_items = all_items if all_items else [ci[0] for ci in classified_items]

    for item in scan_items:
        text = item.get("text", "") or ""
        item_idx = item.get("idx", -1)
        line_id = f"L{item.get('line_start', 0)}-L{item.get('line_end', 0)}"

        for m in _FLOWSHEET_ROW_RE.finditer(text):
            row_dt = _parse_flowsheet_dt(m.group(1), m.group(2))
            if row_dt is None:
                continue

            try:
                num_val = float(m.group(3))
            except ValueError:
                continue

            # Sanity: 85–115 °F
            if num_val < 85 or num_val > 115:
                continue

            delta_s = (
                abs((row_dt - arrival_dt).total_seconds())
                if arrival_dt
                else None
            )

            preview_start = max(0, m.start() - 20)
            preview_end = min(len(text), m.end() + 60)
            preview = text[preview_start:preview_end].replace("\n", " ").strip()[:200]

            flowsheet_candidates.append({
                "value": f"{m.group(3)} °F",
                "numeric": num_val,
                "units": "F",
                "row_dt": row_dt,
                "dt": row_dt.strftime("%Y-%m-%d %H:%M"),
                "delta_seconds": delta_s,
                "item_idx": item_idx,
                "line_id": line_id,
                "preview": preview,
            })

    if flowsheet_candidates:
        chosen_fs: Optional[Dict] = None

        if arrival_dt:
            # Filter to ±4-hour window, pick closest
            nearby = [
                c for c in flowsheet_candidates
                if c["delta_seconds"] is not None
                and c["delta_seconds"] <= _FLOWSHEET_WINDOW_SECONDS
            ]
            if nearby:
                nearby.sort(key=lambda c: c["delta_seconds"])
                chosen_fs = nearby[0]
            else:
                warnings.append("flowsheet_temps_found_but_none_within_4h")
        else:
            # No arrival_datetime → take earliest flowsheet row
            warnings.append("arrival_datetime_missing_using_earliest_flowsheet")
            flowsheet_candidates.sort(key=lambda c: c["row_dt"])
            chosen_fs = flowsheet_candidates[0]

        if chosen_fs is not None:
            source = _make_source(
                "FLOWSHEET", 0,
                chosen_fs["item_idx"], chosen_fs["line_id"],
                chosen_fs["preview"],
            )
            source["method"] = "flowsheet_arrival_proximity"
            if chosen_fs["delta_seconds"] is not None:
                source["delta_minutes"] = round(
                    chosen_fs["delta_seconds"] / 60, 1
                )
            if arrival_datetime:
                source["arrival_datetime"] = arrival_datetime

            return {
                "value": chosen_fs["value"],
                "dt": chosen_fs["dt"],
                "units": chosen_fs["units"],
                "sources": [source],
                "warnings": warnings,
            }

    # ── Strategy 2: fallback – scored H&P approach ──────────────
    if not flowsheet_candidates:
        warnings.append("no_flowsheet_vitals_found_using_hp_fallback")

    candidates: List[Dict[str, Any]] = []

    for item, doc_type, prio in classified_items:
        text = item.get("text", "") or ""
        item_idx = item.get("idx", -1)
        line_id = f"L{item.get('line_start', 0)}-L{item.get('line_end', 0)}"
        item_dt = _try_iso_from_item(item)

        if doc_type not in (
            "trauma_hp", "ed_note", "trauma_progress", "discharge_summary",
        ):
            continue

        is_chosen_hp = (
            doc_type == "trauma_hp"
            and chosen_trauma_hp_item_id is not None
            and item_idx == chosen_trauma_hp_item_id
        )

        for pat_str in temp_pats:
            try:
                for m in re.finditer(pat_str, text):
                    temp_val = (
                        m.group(1)
                        if m.lastindex and m.lastindex >= 1
                        else None
                    )
                    temp_unit = None
                    if m.lastindex and m.lastindex >= 2:
                        temp_unit = m.group(2)

                    if temp_val is None:
                        continue

                    try:
                        num_val = float(temp_val)
                    except ValueError:
                        continue
                    if num_val < 30 or num_val > 115:
                        continue

                    if temp_unit:
                        units = temp_unit.upper()
                    elif num_val >= 85:
                        units = "F"
                    elif num_val < 50:
                        units = "C"
                    else:
                        units = "UNKNOWN"

                    score, anchors_hit = _score_temp_candidate(
                        text, m, doc_type, is_chosen_hp,
                    )

                    orig_str = temp_val
                    if temp_unit:
                        orig_str = f"{temp_val} {temp_unit}"

                    candidates.append({
                        "value": orig_str,
                        "numeric": num_val,
                        "dt": item_dt,
                        "units": units,
                        "score": score,
                        "anchors": anchors_hit,
                        "priority": prio,
                        "doc_type": doc_type,
                        "item_idx": item_idx,
                        "line_id": line_id,
                        "preview": _line_preview(text, m),
                    })
            except re.error:
                continue

    if not candidates:
        return {
            "value": None,
            "dt": None,
            "units": "UNKNOWN",
            "sources": [],
            "warnings": warnings + ["temp_missing"],
        }

    def _sort_key(c: Dict) -> Tuple:
        dt = c.get("dt") or "9999"
        return (-c["score"], dt)

    candidates.sort(key=_sort_key)
    chosen = candidates[0]

    if chosen["score"] < 6:
        warnings.append("temp_context_unclear")

    if chosen.get("units", "UNKNOWN") == "UNKNOWN":
        warnings.append("temp_found_no_units")

    source = _make_source(
        chosen["doc_type"], chosen["priority"],
        chosen["item_idx"], chosen["line_id"],
        chosen["preview"],
    )
    source["score"] = chosen["score"]
    source["anchors"] = chosen["anchors"]
    source["method"] = "hp_fallback_scoring"

    return {
        "value": chosen["value"],
        "dt": chosen["dt"],
        "units": chosen["units"],
        "sources": [source],
        "warnings": warnings,
    }


# ── gi_prophylaxis (ORDER-ONLY) ─────────────────────────────────────
def _extract_gi_prophylaxis(
    classified_items: List[Tuple[Dict, str, int]],
    acfg: Dict[str, Any],
) -> Dict[str, Any]:
    """Extract GI prophylaxis order status.

    ORDER-ONLY: determines whether a GI prophylaxis order/plan exists.
    Does NOT track administration (first_admin_dt).
    """
    spec = acfg.get("gi_prophylaxis", {})
    agent_specs = spec.get("agents", [])
    explicit_pats = spec.get("explicit_phrases", [])
    negative_pats = spec.get("negative_phrases", [])

    best_agent: Optional[str] = None
    first_order_dt: Optional[str] = None
    sources: List[Dict[str, Any]] = []
    warnings: List[str] = []
    found = False
    negative_found = False
    found_only_in_discharge = True  # tracks whether ALL evidence is discharge-only

    for item, doc_type, prio in classified_items:
        text = item.get("text", "") or ""
        item_idx = item.get("idx", -1)
        line_id = f"L{item.get('line_start', 0)}-L{item.get('line_end', 0)}"
        item_dt = _try_iso_from_item(item)

        # Check negative/hold phrases first
        neg_match = _search_any(negative_pats, text)
        if neg_match:
            negative_found = True
            sources.append(
                _make_source(doc_type, prio, item_idx, line_id,
                             _line_preview(text, neg_match))
            )

        # Check explicit GI prophylaxis phrases
        phrase_match = _search_any(explicit_pats, text)

        # Check agent names
        agent_hit = False
        for agent_spec in agent_specs:
            for pat_str in agent_spec.get("patterns", []):
                try:
                    m = re.search(pat_str, text)
                except re.error:
                    continue
                if m:
                    agent_hit = True
                    found = True
                    if doc_type != "discharge_summary":
                        found_only_in_discharge = False
                    if best_agent is None:
                        best_agent = agent_spec["generic"]
                    if not first_order_dt and item_dt:
                        first_order_dt = item_dt
                    sources.append(
                        _make_source(doc_type, prio, item_idx, line_id,
                                     _line_preview(text, m))
                    )
                    break
            if agent_hit:
                break

        if phrase_match and not agent_hit:
            found = True
            if doc_type != "discharge_summary":
                found_only_in_discharge = False
            sources.append(
                _make_source(doc_type, prio, item_idx, line_id,
                             _line_preview(text, phrase_match))
            )

    # Determine status
    if negative_found and not found:
        status = "NO"
    elif found:
        status = "YES"
    else:
        status = "UNKNOWN"

    # Warn if evidence only from discharge summary
    if found and found_only_in_discharge:
        warnings.append("order_from_discharge_only")

    return {
        "status": status,
        "agent": best_agent,
        "first_order_dt": first_order_dt,
        "sources": sources,
        "warnings": warnings,
    }


# ── bowel_regimen (ORDER-ONLY) ──────────────────────────────────────
def _extract_bowel_regimen(
    classified_items: List[Tuple[Dict, str, int]],
    acfg: Dict[str, Any],
) -> Dict[str, Any]:
    """Extract bowel regimen order status.

    ORDER-ONLY: determines whether a bowel regimen order/plan exists.
    Does NOT track administration (first_admin_dt).
    """
    spec = acfg.get("bowel_regimen", {})
    agent_specs = spec.get("agents", [])
    explicit_pats = spec.get("explicit_phrases", [])
    negative_pats = spec.get("negative_phrases", [])

    found_agents: List[str] = []
    first_order_dt: Optional[str] = None
    sources: List[Dict[str, Any]] = []
    warnings: List[str] = []
    found = False
    negative_found = False
    seen_agents: set = set()
    found_only_in_discharge = True  # tracks whether ALL evidence is discharge-only

    for item, doc_type, prio in classified_items:
        text = item.get("text", "") or ""
        item_idx = item.get("idx", -1)
        line_id = f"L{item.get('line_start', 0)}-L{item.get('line_end', 0)}"
        item_dt = _try_iso_from_item(item)

        # Check negative/hold phrases first
        neg_match = _search_any(negative_pats, text)
        if neg_match:
            negative_found = True
            sources.append(
                _make_source(doc_type, prio, item_idx, line_id,
                             _line_preview(text, neg_match))
            )

        # Check explicit bowel regimen phrases
        phrase_match = _search_any(explicit_pats, text)
        if phrase_match:
            found = True
            if doc_type != "discharge_summary":
                found_only_in_discharge = False
            sources.append(
                _make_source(doc_type, prio, item_idx, line_id,
                             _line_preview(text, phrase_match))
            )

        # Check agent names
        for agent_spec in agent_specs:
            for pat_str in agent_spec.get("patterns", []):
                try:
                    m = re.search(pat_str, text)
                except re.error:
                    continue
                if m:
                    found = True
                    if doc_type != "discharge_summary":
                        found_only_in_discharge = False
                    agent_name = agent_spec["generic"]
                    if agent_name not in seen_agents:
                        found_agents.append(agent_name)
                        seen_agents.add(agent_name)
                    if not first_order_dt and item_dt:
                        first_order_dt = item_dt
                    sources.append(
                        _make_source(doc_type, prio, item_idx, line_id,
                                     _line_preview(text, m))
                    )
                    break

    # Determine status
    if negative_found and not found:
        status = "NO"
    elif found:
        status = "YES"
    else:
        status = "UNKNOWN"

    # Warn if evidence only from discharge summary
    if found and found_only_in_discharge:
        warnings.append("order_from_discharge_only")

    return {
        "status": status,
        "agents": found_agents,
        "first_order_dt": first_order_dt,
        "sources": sources,
        "warnings": warnings,
    }


# ── tourniquet ───────────────────────────────────────────────────────

def _is_surgical_tourniquet(text: str, match: re.Match,
                            exclusion_pats: List[str]) -> bool:
    """Return True if the tourniquet mention is intra-operative / surgical.

    Uses a context window around the match to check for surgical exclusion
    patterns (e.g. "hemostasis", "Bovie", "ORIF", "sterile prep").
    """
    window_start = max(0, match.start() - 300)
    window_end = min(len(text), match.end() + 300)
    window = text[window_start:window_end]
    for pat_str in exclusion_pats:
        try:
            if re.search(pat_str, window):
                return True
        except re.error:
            continue
    return False


def _parse_tq_time(text: str, match: re.Match,
                   time_pats: List[str]) -> Optional[str]:
    """Try to extract a time string near a tourniquet mention.

    Searches within a ±200-char window around the match for time patterns.
    Returns the time string (e.g. "1430", "14:30", "2:30 PM") or None.
    """
    window_start = max(0, match.start() - 200)
    window_end = min(len(text), match.end() + 200)
    window = text[window_start:window_end]
    for pat_str in time_pats:
        try:
            m = re.search(pat_str, window)
            if m:
                return m.group("time")
        except (re.error, IndexError):
            continue
    return None


def _parse_tq_location(text: str, match: re.Match,
                       loc_pats: List[str]) -> Optional[str]:
    """Try to extract an anatomical location near a tourniquet mention.

    Searches within a ±200-char window around the match.
    Returns location string or None.
    """
    window_start = max(0, match.start() - 200)
    window_end = min(len(text), match.end() + 200)
    window = text[window_start:window_end]
    for pat_str in loc_pats:
        try:
            m = re.search(pat_str, window)
            if m:
                return m.group("loc").strip()
        except (re.error, IndexError):
            continue
    return None


def _extract_tourniquet(
    classified_items: List[Tuple[Dict, str, int]],
    acfg: Dict[str, Any],
    chosen_trauma_hp_item_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Extract tourniquet placement and removal data.

    Focuses on prehospital / ED trauma tourniquet application.
    Filters out intra-operative / surgical tourniquet mentions using
    exclusion patterns.

    Returns
    -------
    Dict with structure:
        placed: YES | NO | UNKNOWN
        placed_time: <string|null>   (time of placement if documented)
        removed: YES | NO | UNKNOWN
        removed_time: <string|null>  (time of removal if documented)
        location: <string|null>      (anatomical site, e.g. "right upper extremity")
        details: [<str>, ...]        (raw matched snippets)
        sources: [...]
        warnings: [...]
    """
    spec = acfg.get("tourniquet", {})
    placed_pats = spec.get("placed_phrases", [])
    removed_pats = spec.get("removed_phrases", [])
    location_pats = spec.get("location_patterns", [])
    time_pats = spec.get("time_patterns", [])
    exclusion_pats = spec.get("surgical_exclusion_phrases", [])
    no_tq_pats = spec.get("no_tourniquet_phrases", [])

    placed: Optional[str] = None        # YES / NO / UNKNOWN
    placed_time: Optional[str] = None
    removed: Optional[str] = None       # YES / NO / UNKNOWN
    removed_time: Optional[str] = None
    location: Optional[str] = None
    details: List[str] = []
    sources: List[Dict[str, Any]] = []
    warnings: List[str] = []
    seen_details: set = set()

    # Track best priority for placement evidence (lower = better)
    best_placed_prio: int = 99
    best_removed_prio: int = 99
    explicit_no: bool = False

    for item, doc_type, prio in classified_items:
        text = item.get("text", "") or ""
        if not text:
            continue
        item_idx = item.get("idx", -1)
        line_id = f"L{item.get('line_start', 0)}-L{item.get('line_end', 0)}"

        # ── Check explicit NO tourniquet ────────────────────────
        for pat_str in no_tq_pats:
            try:
                m = re.search(pat_str, text)
            except re.error:
                continue
            if m:
                explicit_no = True
                detail = m.group(0).strip()
                if detail.lower() not in seen_details:
                    details.append(detail)
                    seen_details.add(detail.lower())
                sources.append(
                    _make_source(doc_type, prio, item_idx, line_id,
                                 _line_preview(text, m))
                )

        # ── Check PLACED phrases ────────────────────────────────
        for pat_str in placed_pats:
            try:
                m = re.search(pat_str, text)
            except re.error:
                continue
            if m:
                # Filter surgical tourniquet
                if _is_surgical_tourniquet(text, m, exclusion_pats):
                    if "surgical_tourniquet_excluded" not in [w for w in warnings]:
                        warnings.append("surgical_tourniquet_excluded")
                    continue

                detail = m.group(0).strip()
                if detail.lower() not in seen_details:
                    details.append(detail)
                    seen_details.add(detail.lower())

                if prio <= best_placed_prio:
                    placed = "YES"
                    best_placed_prio = prio

                    # Try to get placement time
                    t = _parse_tq_time(text, m, time_pats)
                    if t and placed_time is None:
                        placed_time = t

                    # Try to get location
                    loc = _parse_tq_location(text, m, location_pats)
                    if loc and location is None:
                        location = loc

                sources.append(
                    _make_source(doc_type, prio, item_idx, line_id,
                                 _line_preview(text, m))
                )

        # ── Check REMOVED phrases ───────────────────────────────
        for pat_str in removed_pats:
            try:
                m = re.search(pat_str, text)
            except re.error:
                continue
            if m:
                # Filter surgical tourniquet release
                if _is_surgical_tourniquet(text, m, exclusion_pats):
                    continue

                detail = m.group(0).strip()
                if detail.lower() not in seen_details:
                    details.append(detail)
                    seen_details.add(detail.lower())

                if prio <= best_removed_prio:
                    removed = "YES"
                    best_removed_prio = prio

                    # Try to get removal time
                    t = _parse_tq_time(text, m, time_pats)
                    if t and removed_time is None:
                        removed_time = t

                sources.append(
                    _make_source(doc_type, prio, item_idx, line_id,
                                 _line_preview(text, m))
                )

    # ── Determine final status ──────────────────────────────────
    if placed is None and explicit_no:
        placed = "NO"
    elif placed is None:
        placed = "UNKNOWN"

    if removed is None:
        if placed == "YES":
            # Tourniquet was placed but no removal documented
            removed = "UNKNOWN"
            warnings.append("tourniquet_removal_not_documented")
        elif placed == "NO":
            removed = "N/A"
        else:
            removed = "UNKNOWN"

    # Warn if placed in low-priority doc only
    if placed == "YES" and best_placed_prio >= 9:
        warnings.append("tourniquet_from_discharge_only")

    # Add smartphrase warning if from H&P and no verifiable time
    if placed == "YES" and placed_time is None:
        warnings.append("tourniquet_time_not_documented")

    return {
        "placed": placed,
        "placed_time": placed_time,
        "removed": removed,
        "removed_time": removed_time,
        "location": location,
        "details": details if details else [],
        "sources": sources,
        "warnings": warnings,
    }


# ── public API ──────────────────────────────────────────────────────
def extract_adjuncts(
    classified_items: List[Tuple[Dict, str, int]],
    gc_cfg: Optional[Dict[str, Any]] = None,
    chosen_trauma_hp_item_id: Optional[int] = None,
    all_items: Optional[List[Dict]] = None,
    arrival_datetime: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Extract all adjunct green card fields.

    Parameters
    ----------
    classified_items
        List of (item_dict, doc_type_str, priority_int) tuples,
        already sorted by priority (ascending).
    gc_cfg
        Main green card config (for doc_type_priority lookup).
    chosen_trauma_hp_item_id
        The item_id (idx) of the selected TRAUMA_HP evidence item,
        used for proximity scoring in first_ed_temp.
    all_items
        The full raw evidence items list (unclassified).  Needed so
        first_ed_temp can scan flowsheet vitals items that may not
        appear in classified_items (e.g. kind=REMOVED).
    arrival_datetime
        ISO arrival datetime string from evidence meta, used for
        flowsheet proximity scoring in first_ed_temp.

    Returns
    -------
    Dict with keys: spine_clearance, dvt_prophylaxis, first_ed_temp,
                    gi_prophylaxis, bowel_regimen, tourniquet.
    """
    acfg = _load_adjunct_config()

    return {
        "spine_clearance": _extract_spine_clearance(
            classified_items, acfg, all_items=all_items,
        ),
        "dvt_prophylaxis": _extract_dvt_prophylaxis(classified_items, acfg),
        "first_ed_temp": _extract_first_ed_temp(
            classified_items, acfg,
            chosen_trauma_hp_item_id=chosen_trauma_hp_item_id,
            all_items=all_items,
            arrival_datetime=arrival_datetime,
        ),
        "gi_prophylaxis": _extract_gi_prophylaxis(classified_items, acfg),
        "bowel_regimen": _extract_bowel_regimen(classified_items, acfg),
        "tourniquet": _extract_tourniquet(
            classified_items, acfg,
            chosen_trauma_hp_item_id=chosen_trauma_hp_item_id,
        ),
    }
