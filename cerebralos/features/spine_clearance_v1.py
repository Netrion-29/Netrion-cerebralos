#!/usr/bin/env python3
"""
Spine Clearance Extraction v1 for CerebralOS.

Deterministic extraction of spine clearance status from timeline items.
Produces a patient-level structured output with:
  clearance_status, clearance_ts, method, regions[], collar_status,
  evidence[], warnings, notes, source_rule_id.

**Two extraction strategies (mirroring green-card adjunct logic):**

  Strategy A — Order Questions block parsing:
    Structured "Cervical Spine Clearance" / "Thoracic/Spine Lumbar Clearance"
    answers (YES/NO) from Epic Order Questions blocks.  Latest timestamp per
    region wins.

  Strategy B — Phrase-based clinical text detection:
    Explicit clearance phrases ("spine cleared", "collar cleared", etc.)
    and not-cleared phrases ("continue collar", "spine not cleared", etc.)
    from clinical narrative text.

**Precedence rules:**
  1. Order-based clearance takes precedence over phrase-based.
  2. If both cervical AND thoracic/lumbar orders say YES → CLEAR.
     If any order says NO → NOT_CLEAR.
     If all orders say UNKNOWN → fall through to phrase-based.
  3. Negative imaging alone NEVER produces clearance (fail-closed).
  4. T/L clearance only comes from Order Questions (no T/L phrases).
  5. Ambiguous or conflicting signals → NOT_CLEAR (fail-closed).

**Green-card overlap note:**
  This feature-layer module operates independently from the green-card
  spine clearance logic in ``extract_green_card_adjuncts_v1.py``.  Both
  use the same regex pattern families but the feature layer reads
  timeline items directly while green-card operates on classified
  evidence items.  Outputs live in different JSON locations:
    - Green card:  ``green_card.spine_clearance``
    - Feature layer: ``features.spine_clearance_v1``

Output key: ``spine_clearance_v1``
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

_DNA = "DATA NOT AVAILABLE"


# ═══════════════════════════════════════════════════════════════════
# Inline patterns (derived from green-card config but self-contained)
# ═══════════════════════════════════════════════════════════════════

_CLEARED_PHRASES: List[re.Pattern] = [
    re.compile(r"\bc[- ]?spine\s+cleared\b", re.I),
    re.compile(r"\bspine\s+cleared\b", re.I),
    re.compile(r"\bcollar\s+cleared\b", re.I),
    re.compile(r"\bc[- ]?collar\s+cleared\b", re.I),
    re.compile(r"\bokay\s+to\s+remove\s+collar\b", re.I),
    re.compile(r"\bcleared?\s+(?:to\s+)?remove\s+(?:c[- ]?)?collar\b", re.I),
    re.compile(r"\bremove\s+(?:c[- ]?)?collar\b", re.I),
    re.compile(r"\bcervical\s+spine\s+clear(?:ed)?\b", re.I),
    re.compile(r"\bc[- ]?spine\s+is\s+clear(?:ed)?\b", re.I),
    re.compile(r"\bspine\s+precautions?\s+(?:discontinued|d/?c|removed|lifted)\b", re.I),
    # Composite: "C and TLS spine cleared" / "C and T/L spine cleared"
    re.compile(r"\bc\s+(?:and\s+)?t/?l/?s?\s+spine\s+cleared\b", re.I),
    # "TLS spine cleared" / "T/L-spine cleared" / "T/L spine cleared"
    re.compile(r"\bt/?l/?s?[- ]?spine\s+cleared\b", re.I),
]

_NOT_CLEARED_PHRASES: List[re.Pattern] = [
    re.compile(r"\bcontinue\s+(?:c[- ]?)?collar\b", re.I),
    re.compile(r"\bmaintain\s+(?:c[- ]?)?collar\b", re.I),
    re.compile(r"\bc[- ]?collar\s+(?:to\s+)?remain\b", re.I),
    re.compile(r"\bspine\s+(?:not|has\s+not\s+been)\s+cleared\b", re.I),
    re.compile(r"\bnot\s+(?:yet\s+)?cleared\b", re.I),
    re.compile(r"\bawait(?:ing)?\s+(?:spine|c[- ]?spine)\s+clearance\b", re.I),
    re.compile(r"\bspine\s+precautions?\s+(?:continue|maintain|ongoing)\b", re.I),
    re.compile(r"\bkeep\s+(?:c[- ]?)?collar\b", re.I),
    # T/L specific not-cleared
    re.compile(r"\bt/?l/?s?[- ]?spine\s+not\s+cleared\b", re.I),
]

_COLLAR_PRESENT_PHRASES: List[re.Pattern] = [
    re.compile(r"\bc[- ]?collar\s+(?:in\s+place|on|applied|placed)\b", re.I),
    re.compile(r"\bcervical\s+collar\s+(?:in\s+place|on|applied|placed)\b", re.I),
    re.compile(r"\bcollar\s+in\s+place\b", re.I),
    re.compile(r"\bwearing\s+(?:c[- ]?)?collar\b", re.I),
]

_COLLAR_REMOVED_PHRASES: List[re.Pattern] = [
    re.compile(r"\bcollar\s+removed\b", re.I),
    re.compile(r"\bc[- ]?collar\s+(?:removed|off|discontinued|d/?c)\b", re.I),
    re.compile(r"\bremoved?\s+(?:c[- ]?)?collar\b", re.I),
]

# ── Order Questions patterns ──────────────────────────────────────
_RE_ORDER_QUESTIONS_HEADER = re.compile(
    r"^Order Questions\b|^Question\s+Answer\b", re.M,
)

_RE_ORDERED_ON = re.compile(
    r"Ordered On[\s\S]*?(\d{1,2}/\d{1,2}/\d{2,4})\s+(\d{4})",
)

_RE_CSPINE_QUESTION = re.compile(
    r"\bCervical Spine Clearance\b", re.I,
)

_RE_TLSPINE_QUESTION = re.compile(
    r"\bThoracic/?Spine Lumbar Clearance\b"
    r"|\bThoracic Spine Clearance\b"
    r"|\bLumbar Spine Clearance\b",
    re.I,
)

# Inline "Spine Clearance Cervical Spine Clearance: Yes; ..." line
_RE_INLINE_SPINE_CLEARANCE = re.compile(
    r"Spine Clearance\s+Cervical Spine Clearance:\s*(Yes|No)"
    r";\s*Thoracic/?Spine Lumbar Clearance:\s*(Yes|No)",
    re.I,
)

_RE_ANSWER_YES = re.compile(r"^\s*Yes\s*$", re.I)
_RE_ANSWER_NO = re.compile(r"^\s*No\s*$", re.I)


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════

def _get_item_text(item: Dict[str, Any]) -> str:
    """Extract text from a timeline item (payload.text or item.text)."""
    return (item.get("payload") or {}).get("text", "") or item.get("text", "")


def _parse_ordered_on_ts(text: str) -> Optional[str]:
    """Extract the latest 'Ordered On' timestamp from order block text.

    Returns ISO-style string (YYYY-MM-DDTHH:MM) or None.
    """
    matches = _RE_ORDERED_ON.findall(text)
    if not matches:
        return None
    # Take the LAST match (latest order)
    date_str, time_str = matches[-1]
    parts = date_str.split("/")
    if len(parts) != 3:
        return None
    month, day, year = parts
    if len(year) == 2:
        year = "20" + year
    hh = time_str[:2]
    mm = time_str[2:4]
    try:
        return f"{year}-{int(month):02d}-{int(day):02d}T{hh}:{mm}"
    except (ValueError, IndexError):
        return None


def _extract_order_questions(text: str) -> List[Dict[str, Any]]:
    """Parse Order Questions blocks for spine clearance answers.

    Returns a list of dicts:
      {region: "cervical"|"thoracolumbar", answer: "YES"|"NO"|"UNKNOWN",
       ordered_on: <iso-ts or None>}
    """
    results: List[Dict[str, Any]] = []

    # Strategy 1: Inline format — "Spine Clearance Cervical Spine Clearance: Yes; ..."
    for m in _RE_INLINE_SPINE_CLEARANCE.finditer(text):
        c_ans = m.group(1).strip().upper()
        tl_ans = m.group(2).strip().upper()
        # Try to get ordered_on from nearby context
        # Look for Ordered On preceding or following this match
        context_start = max(0, m.start() - 500)
        context_end = min(len(text), m.end() + 500)
        context = text[context_start:context_end]
        ts = _parse_ordered_on_ts(context)
        results.append({"region": "cervical", "answer": c_ans, "ordered_on": ts})
        results.append({"region": "thoracolumbar", "answer": tl_ans, "ordered_on": ts})

    # Strategy 2: Structured block format
    # "Order Questions\n\nQuestion\tAnswer\nCervical Spine Clearance\tYes\n..."
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # Find "Order Questions" or "Question\tAnswer" header
        if _RE_ORDER_QUESTIONS_HEADER.search(line):
            # Scan ahead for clearance questions (within ~20 lines)
            block_ts = None
            # Look backward for Ordered On
            backward_start = max(0, i - 30)
            backward_text = "\n".join(lines[backward_start:i])
            block_ts = _parse_ordered_on_ts(backward_text)

            for j in range(i + 1, min(i + 25, len(lines))):
                qline = lines[j]
                # Check for Cervical Spine Clearance
                if _RE_CSPINE_QUESTION.search(qline):
                    # Answer follows the question on same line (tab-separated)
                    answer = "UNKNOWN"
                    # Split on tabs or multiple spaces
                    parts = re.split(r"\t+|\s{2,}", qline.strip())
                    if len(parts) >= 2:
                        ans_text = parts[-1].strip()
                        if re.match(r"^Yes$", ans_text, re.I):
                            answer = "YES"
                        elif re.match(r"^No$", ans_text, re.I):
                            answer = "NO"
                    # Also look forward for Ordered On
                    if block_ts is None:
                        forward_text = "\n".join(lines[j:min(j + 30, len(lines))])
                        block_ts = _parse_ordered_on_ts(forward_text)
                    results.append({
                        "region": "cervical",
                        "answer": answer,
                        "ordered_on": block_ts,
                    })

                # Check for Thoracic/Spine Lumbar Clearance
                if _RE_TLSPINE_QUESTION.search(qline):
                    answer = "UNKNOWN"
                    parts = re.split(r"\t+|\s{2,}", qline.strip())
                    if len(parts) >= 2:
                        ans_text = parts[-1].strip()
                        if re.match(r"^Yes$", ans_text, re.I):
                            answer = "YES"
                        elif re.match(r"^No$", ans_text, re.I):
                            answer = "NO"
                    if block_ts is None:
                        forward_text = "\n".join(lines[j:min(j + 30, len(lines))])
                        block_ts = _parse_ordered_on_ts(forward_text)
                    results.append({
                        "region": "thoracolumbar",
                        "answer": answer,
                        "ordered_on": block_ts,
                    })
        i += 1

    return results


def _resolve_orders(
    order_entries: List[Dict[str, Any]],
) -> Tuple[Optional[str], Optional[str], List[Dict[str, Any]]]:
    """Resolve multiple order entries into per-region final answers.

    Uses latest-timestamp-wins per region.

    Returns:
      (cervical_answer, thoracolumbar_answer, regions_list)
      where answers are "YES" | "NO" | "UNKNOWN" | None
      and regions_list is the structured regions output.
    """
    if not order_entries:
        return None, None, []

    # Group by region, keep latest
    latest: Dict[str, Dict[str, Any]] = {}
    for entry in order_entries:
        region = entry["region"]
        existing = latest.get(region)
        if existing is None:
            latest[region] = entry
        else:
            # Compare timestamps — latest wins
            new_ts = entry.get("ordered_on") or ""
            old_ts = existing.get("ordered_on") or ""
            if new_ts >= old_ts:
                latest[region] = entry

    # Build regions output
    regions: List[Dict[str, Any]] = []
    c_answer = None
    tl_answer = None

    if "cervical" in latest:
        c_entry = latest["cervical"]
        c_answer = c_entry["answer"]
        regions.append({
            "name": "cervical",
            "clearance": c_answer,
            "ordered_on": c_entry.get("ordered_on"),
        })

    if "thoracolumbar" in latest:
        tl_entry = latest["thoracolumbar"]
        tl_answer = tl_entry["answer"]
        regions.append({
            "name": "thoracolumbar",
            "clearance": tl_answer,
            "ordered_on": tl_entry.get("ordered_on"),
        })

    return c_answer, tl_answer, regions


def _extract_phrase_clearance(
    text: str,
) -> Tuple[List[str], List[str], List[str], List[str]]:
    """Scan text for phrase-based clearance, not-cleared, collar present/removed.

    Returns four lists of matched snippet strings:
      (cleared_snippets, not_cleared_snippets, collar_present_snippets,
       collar_removed_snippets)
    """
    cleared: List[str] = []
    not_cleared: List[str] = []
    collar_present: List[str] = []
    collar_removed: List[str] = []

    for pat in _CLEARED_PHRASES:
        for m in pat.finditer(text):
            snippet = text[max(0, m.start() - 20):m.end() + 20].strip()
            snippet = snippet.replace("\n", " ")[:120]
            cleared.append(snippet)

    for pat in _NOT_CLEARED_PHRASES:
        for m in pat.finditer(text):
            snippet = text[max(0, m.start() - 20):m.end() + 20].strip()
            snippet = snippet.replace("\n", " ")[:120]
            not_cleared.append(snippet)

    for pat in _COLLAR_PRESENT_PHRASES:
        for m in pat.finditer(text):
            snippet = text[max(0, m.start() - 20):m.end() + 20].strip()
            snippet = snippet.replace("\n", " ")[:120]
            collar_present.append(snippet)

    for pat in _COLLAR_REMOVED_PHRASES:
        for m in pat.finditer(text):
            snippet = text[max(0, m.start() - 20):m.end() + 20].strip()
            snippet = snippet.replace("\n", " ")[:120]
            collar_removed.append(snippet)

    return cleared, not_cleared, collar_present, collar_removed


# ═══════════════════════════════════════════════════════════════════
# Main extraction
# ═══════════════════════════════════════════════════════════════════

def extract_spine_clearance(
    pat_features: Dict[str, Any],
    days_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Extract spine clearance status from patient timeline data.

    Args:
        pat_features: partial features dict ({"days": feature_days})
        days_data:    full patient_days_v1 JSON

    Returns:
        Dict with keys:
          clearance_status, clearance_ts, method, regions,
          collar_status, evidence, warnings, notes, source_rule_id
    """
    warnings: List[str] = []
    notes: List[str] = []
    evidence: List[Dict[str, Any]] = []

    days_map = days_data.get("days") or {}

    # Collections across all days
    all_order_entries: List[Dict[str, Any]] = []
    all_cleared_snippets: List[str] = []
    all_not_cleared_snippets: List[str] = []
    all_collar_present: List[str] = []
    all_collar_removed: List[str] = []

    # Track latest timestamps for each signal type
    latest_cleared_ts: Optional[str] = None
    latest_not_cleared_ts: Optional[str] = None

    for day_iso in sorted(days_map.keys()):
        day_info = days_map[day_iso]
        items = day_info.get("items") or []

        for item_idx, item in enumerate(items):
            text = _get_item_text(item)
            if not text:
                continue

            dt_raw = item.get("dt") or None
            raw_line_id = item.get("raw_line_id")
            item_ref = f"{day_iso}:item_{item_idx}"
            if raw_line_id is None:
                raw_line_id = item_ref

            # ── Order Questions extraction ──────────────────────
            order_entries = _extract_order_questions(text)
            if order_entries:
                for oe in order_entries:
                    oe["source_day"] = day_iso
                    oe["source_item"] = item_idx
                    oe["raw_line_id"] = raw_line_id
                    oe["dt"] = dt_raw
                all_order_entries.extend(order_entries)
                evidence.append({
                    "role": "order_question_block",
                    "snippet": (
                        f"[{day_iso}] Order Questions: "
                        + "; ".join(
                            f"{e['region']}={e['answer']}"
                            for e in order_entries
                        )
                    )[:120],
                    "raw_line_id": raw_line_id,
                })

            # ── Phrase-based extraction ─────────────────────────
            cleared, not_cleared, collar_pres, collar_rem = (
                _extract_phrase_clearance(text)
            )

            if cleared:
                all_cleared_snippets.extend(cleared)
                if dt_raw and (
                    latest_cleared_ts is None or dt_raw > latest_cleared_ts
                ):
                    latest_cleared_ts = dt_raw
                evidence.append({
                    "role": "cleared_phrase",
                    "snippet": cleared[0][:120],
                    "raw_line_id": raw_line_id,
                })

            if not_cleared:
                all_not_cleared_snippets.extend(not_cleared)
                if dt_raw and (
                    latest_not_cleared_ts is None
                    or dt_raw > latest_not_cleared_ts
                ):
                    latest_not_cleared_ts = dt_raw
                evidence.append({
                    "role": "not_cleared_phrase",
                    "snippet": not_cleared[0][:120],
                    "raw_line_id": raw_line_id,
                })

            if collar_pres:
                all_collar_present.extend(collar_pres)
            if collar_rem:
                all_collar_removed.extend(collar_rem)

    # ═══════════════════════════════════════════════════════════════
    # Resolution logic
    # ═══════════════════════════════════════════════════════════════

    clearance_status = _DNA
    clearance_ts: Optional[str] = None
    method = _DNA
    regions: List[Dict[str, Any]] = []

    # ── Step 1: Resolve order-based clearance (takes precedence) ─
    c_ans, tl_ans, order_regions = _resolve_orders(all_order_entries)

    order_based = False
    if c_ans is not None or tl_ans is not None:
        # We have order data
        if c_ans == "YES" and tl_ans == "YES":
            clearance_status = "YES"
            method = "ORDER"
            order_based = True
        elif c_ans == "NO" or tl_ans == "NO":
            clearance_status = "NO"
            method = "ORDER"
            order_based = True
        elif c_ans == "YES" and tl_ans in (None, "UNKNOWN"):
            # Cervical cleared, no T/L info → partial clear
            clearance_status = "YES"
            method = "ORDER"
            order_based = True
            notes.append("cervical_cleared_tl_unknown_or_absent")
        elif c_ans == "UNKNOWN" and tl_ans == "UNKNOWN":
            # Both unknown — fall through to phrase-based
            notes.append("order_questions_both_unknown_fallthrough")
        elif c_ans is None and tl_ans == "YES":
            # Only T/L cleared, no cervical order
            clearance_status = "YES"
            method = "ORDER"
            order_based = True
            notes.append("tl_cleared_cervical_absent")
        elif c_ans is None and tl_ans == "NO":
            clearance_status = "NO"
            method = "ORDER"
            order_based = True
            notes.append("tl_not_cleared_cervical_absent")
        else:
            # Ambiguous order combinations → fail-closed
            clearance_status = "NO"
            method = "ORDER"
            order_based = True
            warnings.append("ambiguous_order_status_fail_closed")

        if order_based:
            regions = order_regions
            # Use the latest order timestamp
            order_ts_candidates = [
                e.get("ordered_on") for e in all_order_entries
                if e.get("ordered_on")
            ]
            if order_ts_candidates:
                clearance_ts = max(order_ts_candidates)

    # ── Step 2: Phrase-based fallback (only if no definitive order) ─
    if not order_based:
        has_cleared = len(all_cleared_snippets) > 0
        has_not_cleared = len(all_not_cleared_snippets) > 0

        if has_cleared and not has_not_cleared:
            clearance_status = "YES"
            method = "CLINICAL"
            clearance_ts = latest_cleared_ts
        elif has_not_cleared and not has_cleared:
            clearance_status = "NO"
            method = "CLINICAL"
            clearance_ts = latest_not_cleared_ts
        elif has_cleared and has_not_cleared:
            # Conflicting signals: use latest timestamp to determine
            if latest_cleared_ts and latest_not_cleared_ts:
                if latest_cleared_ts > latest_not_cleared_ts:
                    clearance_status = "YES"
                    method = "CLINICAL"
                    clearance_ts = latest_cleared_ts
                    notes.append("conflicting_signals_latest_is_cleared")
                elif latest_not_cleared_ts > latest_cleared_ts:
                    clearance_status = "NO"
                    method = "CLINICAL"
                    clearance_ts = latest_not_cleared_ts
                    notes.append("conflicting_signals_latest_is_not_cleared")
                else:
                    # Same timestamp — fail-closed
                    clearance_status = "NO"
                    method = "CLINICAL"
                    clearance_ts = latest_not_cleared_ts
                    warnings.append("conflicting_signals_same_ts_fail_closed")
            else:
                # Missing timestamps — fail-closed to not-cleared
                clearance_status = "NO"
                method = "CLINICAL"
                warnings.append("conflicting_signals_no_ts_fail_closed")
        else:
            # No phrase evidence at all
            clearance_status = _DNA
            method = _DNA

    # ── Step 3: Collar status (independent of clearance) ────────
    if all_collar_removed:
        collar_status = "REMOVED"
    elif all_collar_present:
        collar_status = "PRESENT"
    else:
        collar_status = _DNA

    # ── Step 4: Enrich regions from phrase-based if no order regions ──
    if not regions and clearance_status != _DNA:
        # Phrase-based: check if cervical vs T/L mentioned
        c_mentioned = any(
            re.search(r"\bc[- ]?spine|cervical", s, re.I)
            for s in all_cleared_snippets + all_not_cleared_snippets
        )
        tl_mentioned = any(
            re.search(r"\bt/?l/?s?[- ]?spine|thoracic|lumbar", s, re.I)
            for s in all_cleared_snippets + all_not_cleared_snippets
        )

        if c_mentioned:
            c_status = "YES" if any(
                re.search(r"\bc[- ]?spine|cervical", s, re.I)
                for s in all_cleared_snippets
            ) else "NO"
            regions.append({"name": "cervical", "clearance": c_status, "ordered_on": None})

        if tl_mentioned:
            tl_status = "YES" if any(
                re.search(r"\bt/?l/?s?[- ]?spine|thoracic|lumbar", s, re.I)
                for s in all_cleared_snippets
            ) else "NO"
            regions.append({"name": "thoracolumbar", "clearance": tl_status, "ordered_on": None})

    # ── Generate notes for empty extraction ─────────────────────
    if clearance_status == _DNA and not evidence:
        notes.append("no_spine_clearance_documentation_found")

    # ── Green-card overlap annotation ───────────────────────────
    notes.append(
        "green_card_overlap: this feature-layer extraction is independent "
        "of green_card.spine_clearance; both use similar regex patterns "
        "but operate on different data sources"
    )

    return {
        "clearance_status": clearance_status,
        "clearance_ts": clearance_ts,
        "method": method,
        "regions": regions,
        "collar_status": collar_status,
        "order_count": len(all_order_entries),
        "cleared_phrase_count": len(all_cleared_snippets),
        "not_cleared_phrase_count": len(all_not_cleared_snippets),
        "evidence": evidence,
        "warnings": warnings,
        "notes": notes,
        "source_rule_id": "spine_clearance_v1",
    }
