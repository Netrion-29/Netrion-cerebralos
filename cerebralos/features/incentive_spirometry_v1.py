#!/usr/bin/env python3
"""
Incentive Spirometry Extraction v1 for CerebralOS.

Deterministic extraction of incentive spirometry (IS) documentation from
timeline items.  Captures THREE categories of data:

1. **Plan / assessment mentions** (text scan):
   - "Pulm Hygiene, incentive spirometry"
   - "Pulmonary hygiene encouraged"
   - "encourage incentive spirometry use"
   - "Frequent IS use"
   - "Aggressive pulmonary toilet"
   - "Needs aerobic addition to incentive spirometer"

2. **Order entries** (text scan):
   - "INCENTIVE SPIROMETER Q2H While awake [RT16] (Order NNN)"
   - Extracts frequency (Q2H, Q1H), order number, status.

3. **Flowsheet numeric data** (structured extraction):
   - Sections headed by "Incentive Spirometry" label followed by
     column headers with "**" markers and timestamped data rows.
   - Extracts: goal_cc, num_breaths, avg_volume_cc, largest_volume_cc,
     patient_effort, assessment_recommendation, cough_effort,
     cough_production.

Fail-closed behaviour:
  - Numeric values extracted ONLY from explicit flowsheet data rows.
  - "Pulmonary hygiene" alone (without explicit IS context) is treated
    as a weak mention, not a confirmed IS reference.
  - PFT spirometry ("Spirometry suggests…") is explicitly excluded.
  - No clinical inference, no LLM, no ML.

Sources (scanned in timeline order):
  TRAUMA_HP, PHYSICIAN_NOTE, ED_NOTE, NURSING_NOTE, CONSULT_NOTE,
  RADIOLOGY, CASE_MGMT, REMOVED

Output key: ``incentive_spirometry_v1`` (under top-level ``features`` dict)
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional, Tuple

_DNA = "DATA NOT AVAILABLE"

# ── Source types to scan ────────────────────────────────────────────
_SOURCE_TYPES = frozenset({
    "TRAUMA_HP",
    "PHYSICIAN_NOTE",
    "ED_NOTE",
    "NURSING_NOTE",
    "CONSULT_NOTE",
    "RADIOLOGY",
    "CASE_MGMT",
    "REMOVED",
    "RT_ORDER",
    "IS_FLOWSHEET",
})

# ── Regex patterns ──────────────────────────────────────────────────

# Explicit IS mention (strong signal)
RE_IS_EXPLICIT = re.compile(
    r"incentive\s+spirometr[yie]|incentive\s+spirometer",
    re.IGNORECASE,
)

# IS order line:
#   INCENTIVE SPIROMETER Q2H While awake [RT16] (Order 466185479)
RE_IS_ORDER = re.compile(
    r"INCENTIVE\s+SPIROMETER\s+"
    r"(Q\d+H)\s+"              # frequency
    r"(.*?)"                   # context ("While awake")
    r"\s*\[([^\]]+)\]"         # designator e.g. [RT16]
    r"\s*"
    r"(?:\(Order\s+(\d+)\))?"  # optional order number
    ,
    re.IGNORECASE,
)

# IS order status line:
#   Status:  Discontinued (Patient Discharge)
RE_IS_ORDER_STATUS = re.compile(
    r"Status:\s*(\S.+?)(?:\s*$)",
    re.IGNORECASE,
)

# IS order standalone:
#   "INCENTIVE SPIROMETER" alone on a line (order reference without detail)
RE_IS_ORDER_STANDALONE = re.compile(
    r"^INCENTIVE\s+SPIROMETER\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# Plan/assessment IS mentions
RE_PLAN_IS = re.compile(
    r"(?:pulm(?:onary)?\s+hygiene\s*,?\s*incentive\s+spirometr[yie])"
    r"|(?:encourage\s+incentive\s+spirometr[yie]\s+use)"
    r"|(?:incentive\s+spirometr[yie]\s+encouraged)"
    r"|(?:pulmonary\s+hygiene\s*,?\s*incentive\s+spirometr[yie]\s+encouraged)"
    r"|(?:aerobika?\s+and\s+IS\b)"
    r"|(?:encourage\s+IS\s+and\s+aerobika?)"
    r"|(?:encourage\s+IS\s+use)"
    r"|(?:\bIS\s+and\s+aerobika?)"
    r"|(?:addition\s+to\s+incentive\s+spirometer)",
    re.IGNORECASE,
)

# Frequent IS use / Aggressive pulmonary toilet + IS
RE_IS_USE = re.compile(
    r"Frequent\s+IS\s+use"
    r"|Aggressive\s+pulmonary\s+(?:toilet|hygiene)\.?\s*(?:Frequent\s+IS\s+use)?"
    r"|Pulmonary\s+toilet\.?\s*Frequent\s+IS\s+use"
    r"|Pulmonary\s+hygiene\s+with\s+aerobika?\s+and\s+IS\b"
    r"|Continue\s+incentive\s+spirometer",
    re.IGNORECASE,
)

# Pulmonary hygiene alone (weak mention — no explicit IS)
RE_PULM_HYGIENE_ONLY = re.compile(
    r"(?:pulmonary\s+hygiene\s+encouraged)"
    r"|(?:aggressive\s+pulm(?:onary)?\s+hygiene)"
    r"|(?:pulmonary\s+toilet(?:\s*$|\.\s))",
    re.IGNORECASE,
)

# FALSE POSITIVE: PFT spirometry (exclude)
RE_PFT_SPIROMETRY = re.compile(
    r"spirometry\s+suggests|spirometry\s+reveals|spirometry\s+shows"
    r"|pulmonary\s+function\s+(?:test|study)"
    r"|spirometry\s+(?:mild|moderate|severe|normal|restrictiv)"
    r"|FEV1|FVC|DLCO",
    re.IGNORECASE,
)

# ── Flowsheet patterns ─────────────────────────────────────────────

# Flowsheet header: "Incentive Spirometry" on its own line or start
RE_FLOWSHEET_HEADER = re.compile(
    r"^Incentive\s+Spirometry\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# Flowsheet column header markers (contain **)
RE_FLOWSHEET_COL_HEADER = re.compile(
    r"(?:Assessment\s+Recommendation|Number\s+of\s+Breaths|"
    r"Average\s+Volume|Largest\s+Volume|Patient\s+Effort|"
    r"Inspiratory\s+Capacity\s+Goal|Cough\s+Effort|"
    r"Cough\s+Production|Therapy\s+Modification|"
    r"Reassessment\s+Needed|Comments)\s*\*\*",
    re.IGNORECASE,
)

# Flowsheet data row: MM/DD HHMM followed by tab-delimited values
RE_FLOWSHEET_DATA_ROW = re.compile(
    r"^(\d{2}/\d{2})\s+(\d{4})\s+(.*)$",
    re.MULTILINE,
)

# Numeric volume pattern (with or without unit)
RE_VOLUME_CC = re.compile(
    r"(\d{3,5})\s*(?:cc|mL|ml)?\b",
)

# Goal pattern: "2500 cc"
RE_GOAL_CC = re.compile(
    r"(\d{3,5})\s*cc\b",
    re.IGNORECASE,
)

# Patient effort values
_EFFORT_VALUES = frozenset({
    "good", "fair", "poor", "minimal", "moderate",
    "excellent", "none", "unable",
})

# Assessment recommendation values
_RECOMMENDATION_VALUES = frozenset({
    "continue present therapy",
})

# Cough effort values
_COUGH_EFFORT_VALUES = frozenset({
    "no cough", "effective", "ineffective", "weak",
    "strong", "productive", "nonproductive",
})


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


# ── Flowsheet parser ───────────────────────────────────────────────

def _parse_flowsheet_block(
    text: str,
    source_type: str,
    source_id: Optional[str],
    source_ts: Optional[str],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
    """
    Parse IS flowsheet data from text block.

    Returns (measurements, evidence, notes).
    """
    measurements: List[Dict[str, Any]] = []
    evidence: List[Dict[str, Any]] = []
    notes: List[str] = []

    # Find the "Incentive Spirometry" header
    header_match = RE_FLOWSHEET_HEADER.search(text)
    if not header_match:
        return measurements, evidence, notes

    # Text after the header
    block_start = header_match.end()
    remaining = text[block_start:]

    # Find the column header line(s) — they contain "**" markers
    col_match = RE_FLOWSHEET_COL_HEADER.search(remaining)
    if not col_match:
        return measurements, evidence, notes

    # Determine column layout from the header line
    # Look for the full line containing column headers
    lines = remaining.split("\n")
    col_header_line = ""
    col_header_idx = -1
    for i, line in enumerate(lines):
        if RE_FLOWSHEET_COL_HEADER.search(line):
            col_header_line = line
            col_header_idx = i
            break

    if col_header_idx < 0:
        return measurements, evidence, notes

    # Parse column names from header
    # Columns are separated by ** markers and tabs
    col_names = _parse_column_names(col_header_line)

    # Now parse data rows that follow
    # Data rows start with MM/DD HHMM pattern
    # Stop when we hit a line that starts a new section (e.g., "Intake")
    data_lines = lines[col_header_idx + 1:]
    stop_patterns = re.compile(
        r"^(?:Intake|Output|Intentional|Flowsheet|Date/Time|Height|Weight\b)",
        re.IGNORECASE,
    )

    for line in data_lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Stop at section boundary
        if stop_patterns.match(stripped):
            break

        row_match = RE_FLOWSHEET_DATA_ROW.match(stripped)
        if not row_match:
            # Could be a continuation line (e.g., "Continue present therapy")
            # or a recommendation-only line — skip
            continue

        date_part = row_match.group(1)  # MM/DD
        time_part = row_match.group(2)  # HHMM
        values_str = row_match.group(3)  # rest of data

        measurement = _parse_data_row(
            date_part, time_part, values_str, col_names,
        )

        if measurement:
            rid = _make_raw_line_id(source_type, source_id, stripped)
            measurement["raw_line_id"] = rid
            measurement["source_type"] = source_type
            measurements.append(measurement)

            evidence.append({
                "role": "flowsheet_data",
                "label": "is_measurement",
                "source_type": source_type,
                "source_id": source_id,
                "ts": source_ts,
                "raw_line_id": rid,
                "snippet": _snippet(stripped),
            })

    if measurements:
        notes.append(
            f"flowsheet_measurements_extracted: {len(measurements)} "
            f"data row(s) from IS flowsheet"
        )

    return measurements, evidence, notes


def _parse_column_names(header_line: str) -> List[str]:
    """
    Parse column names from flowsheet header line.

    Two known formats found in data:

    Format A (Michael_Dougan):
      Inspiratory Capacity Goal (cc) ** Number of Breaths **
      Average Volume (cc) ** Largest Volume (cc) ** Patient Effort **
      Assessment Recommendation ** Cough Effort  Cough Production
      Therapy Modification  Reassessment Needed

    Format B (Ronald_Bittner):
      Assessment Recommendation ** Number of Breaths **
      Average Volume (cc) ** Largest Volume (cc) ** Patient Effort **
      Cough Effort  Cough Production  Comments
      Inspiratory Capacity Goal (cc) **

    Returns ordered list of canonical column names.
    """
    # Normalize: extract column names between ** markers
    # Split by ** and clean up
    parts = re.split(r"\*\*", header_line)
    col_names: List[str] = []

    for part in parts:
        part = part.strip().strip("\t").strip()
        if not part:
            continue

        # Normalize known column names
        pl = part.lower()
        if "inspiratory capacity goal" in pl:
            col_names.append("goal_cc")
        elif "number of breaths" in pl:
            col_names.append("num_breaths")
        elif "average volume" in pl:
            col_names.append("avg_volume_cc")
        elif "largest volume" in pl:
            col_names.append("largest_volume_cc")
        elif "patient effort" in pl:
            col_names.append("patient_effort")
        elif "assessment recommendation" in pl:
            col_names.append("assessment_recommendation")
        elif "cough effort" in pl:
            # Cough Effort and Cough Production may be on same segment
            col_names.append("cough_effort")
            if "cough production" in pl:
                col_names.append("cough_production")
        elif "cough production" in pl:
            col_names.append("cough_production")
        elif "comments" in pl:
            col_names.append("comments")
        elif "therapy modification" in pl:
            col_names.append("therapy_modification")
        elif "reassessment needed" in pl:
            col_names.append("reassessment_needed")

    return col_names


def _parse_data_row(
    date_part: str,
    time_part: str,
    values_str: str,
    col_names: List[str],
) -> Optional[Dict[str, Any]]:
    """
    Parse a single flowsheet data row into a measurement dict.

    The values are tab-delimited but often sparse (many empty cells).
    We use a heuristic: split by tabs, match to columns positionally.
    """
    ts_str = f"{date_part} {time_part}"

    # Split values by tab
    raw_vals = values_str.split("\t")
    # Strip each
    raw_vals = [v.strip() for v in raw_vals]
    # Remove trailing empty values
    while raw_vals and not raw_vals[-1]:
        raw_vals.pop()

    result: Dict[str, Any] = {
        "ts": ts_str,
    }

    # Try to extract structured values by pattern matching rather than
    # strict positional mapping (data is too messy for strict column mapping)
    full_row = values_str

    # Goal (cc): look for "NNNN cc" pattern
    goal_match = RE_GOAL_CC.search(full_row)
    if goal_match:
        try:
            result["goal_cc"] = int(goal_match.group(1))
        except ValueError:
            pass

    # Number of breaths: single-digit or two-digit integer
    # (Appears between goal and volume, or first field)
    breaths_found = False
    for val in raw_vals:
        if not val:
            continue
        # Check for integer that looks like breath count (1-50)
        try:
            n = int(val)
            if 1 <= n <= 50 and "cc" not in val.lower():
                if not breaths_found:
                    result["num_breaths"] = n
                    breaths_found = True
                    continue
        except ValueError:
            pass

    # Volumes: look for 3-4 digit numbers (100-9999)
    vol_nums = []
    for val in raw_vals:
        if not val:
            continue
        m = re.match(r"^(\d{3,4})$", val)
        if m:
            try:
                v = int(m.group(1))
                if 100 <= v <= 9999:
                    vol_nums.append(v)
            except ValueError:
                pass

    if len(vol_nums) >= 2:
        result["avg_volume_cc"] = vol_nums[0]
        result["largest_volume_cc"] = vol_nums[1]
    elif len(vol_nums) == 1:
        # Single volume — could be either; mark as largest conservatively
        result["largest_volume_cc"] = vol_nums[0]

    # Patient effort
    for val in raw_vals:
        if val.lower() in _EFFORT_VALUES:
            result["patient_effort"] = val
            break

    # Assessment recommendation
    full_lower = full_row.lower()
    if "continue present therapy" in full_lower:
        result["assessment_recommendation"] = "Continue present therapy"

    # Cough effort
    for val in raw_vals:
        vl = val.lower()
        if vl in _COUGH_EFFORT_VALUES or vl == "no cough":
            result["cough_effort"] = val
            break

    # Cough production
    for val in raw_vals:
        vl = val.lower()
        if vl in ("none", "mucoid", "purulent", "bloody"):
            # Only set if we also found cough effort (to disambiguate)
            if "cough_effort" in result:
                result["cough_production"] = val
                break

    # Comments: check for free text that isn't a known value
    for val in raw_vals:
        vl = val.lower()
        if (vl and vl not in _EFFORT_VALUES
                and vl not in _COUGH_EFFORT_VALUES
                and vl not in _RECOMMENDATION_VALUES
                and vl not in ("none", "mucoid", "purulent", "bloody",
                               "no", "yes", "prn", "daily")
                and not re.match(r"^\d+$", val)
                and not RE_GOAL_CC.match(val)):
            # Looks like a comment — check for known patterns
            if ("sedated" in vl or "vent" in vl or "patient" in vl
                    or "unable" in vl):
                result["comments"] = val
                break

    # Only return if we have at least a timestamp
    has_data = any(
        k in result
        for k in ("goal_cc", "num_breaths", "avg_volume_cc",
                   "largest_volume_cc", "patient_effort",
                   "assessment_recommendation", "comments")
    )
    if has_data:
        return result

    # Even "recommendation only" rows are valid
    return result if len(result) > 1 else None


# ── Item scanner ────────────────────────────────────────────────────

def _scan_item(
    text: str,
    source_type: str,
    source_id: Optional[str],
    source_ts: Optional[str],
) -> Dict[str, Any]:
    """
    Scan a single timeline item text for IS-related content.

    Returns:
        Dict with keys: mentions, orders, flowsheet_measurements,
        evidence, notes, warnings.
    """
    mentions: List[Dict[str, Any]] = []
    orders: List[Dict[str, Any]] = []
    flowsheet_measurements: List[Dict[str, Any]] = []
    evidence: List[Dict[str, Any]] = []
    notes: List[str] = []
    warnings: List[str] = []

    # ── Check for PFT spirometry false positive ────────────────
    # If the item ONLY mentions PFT spirometry, skip entirely
    has_pft = bool(RE_PFT_SPIROMETRY.search(text))

    # ── Explicit IS mentions ───────────────────────────────────
    for m in RE_IS_EXPLICIT.finditer(text):
        # Check surrounding context for PFT false positive
        start = max(0, m.start() - 80)
        end = min(len(text), m.end() + 80)
        context = text[start:end]
        if RE_PFT_SPIROMETRY.search(context):
            continue  # This is PFT spirometry, not IS

        line = _get_line_containing(text, m.start())
        rid = _make_raw_line_id(source_type, source_id, line)
        mentions.append({
            "type": "explicit_is",
            "text": _snippet(line),
            "ts": source_ts,
            "raw_line_id": rid,
            "source_type": source_type,
        })
        evidence.append({
            "role": "is_mention",
            "label": "explicit_is",
            "source_type": source_type,
            "source_id": source_id,
            "ts": source_ts,
            "raw_line_id": rid,
            "snippet": _snippet(line),
        })

    # ── IS order entries ───────────────────────────────────────
    for m in RE_IS_ORDER.finditer(text):
        line = _get_line_containing(text, m.start())
        rid = _make_raw_line_id(source_type, source_id, line)
        order = {
            "type": "is_order",
            "frequency": m.group(1),  # e.g. "Q2H"
            "context": (m.group(2) or "").strip(),
            "designator": m.group(3),  # e.g. "RT16"
            "order_number": m.group(4),
            "ts": source_ts,
            "raw_line_id": rid,
            "source_type": source_type,
        }

        # Try to find status for this order
        order_num = m.group(4)
        if order_num:
            # Look for "Status:" after the order line
            status_search_start = m.end()
            status_search_end = min(len(text), status_search_start + 500)
            status_block = text[status_search_start:status_search_end]
            status_match = RE_IS_ORDER_STATUS.search(status_block)
            if status_match:
                order["status"] = status_match.group(1).strip()

        orders.append(order)
        evidence.append({
            "role": "is_order",
            "label": "is_order",
            "source_type": source_type,
            "source_id": source_id,
            "ts": source_ts,
            "raw_line_id": rid,
            "snippet": _snippet(line),
        })

    # ── Plan IS patterns ───────────────────────────────────────
    for m in RE_PLAN_IS.finditer(text):
        line = _get_line_containing(text, m.start())
        # Avoid double-counting if already captured as explicit IS
        rid = _make_raw_line_id(source_type, source_id, line)
        if any(e["raw_line_id"] == rid for e in evidence):
            continue

        mentions.append({
            "type": "plan_is",
            "text": _snippet(line),
            "ts": source_ts,
            "raw_line_id": rid,
            "source_type": source_type,
        })
        evidence.append({
            "role": "is_mention",
            "label": "plan_is",
            "source_type": source_type,
            "source_id": source_id,
            "ts": source_ts,
            "raw_line_id": rid,
            "snippet": _snippet(line),
        })

    # ── IS use patterns (Frequent IS use, etc.) ────────────────
    for m in RE_IS_USE.finditer(text):
        line = _get_line_containing(text, m.start())
        rid = _make_raw_line_id(source_type, source_id, line)
        if any(e["raw_line_id"] == rid for e in evidence):
            continue

        mentions.append({
            "type": "is_use",
            "text": _snippet(line),
            "ts": source_ts,
            "raw_line_id": rid,
            "source_type": source_type,
        })
        evidence.append({
            "role": "is_mention",
            "label": "is_use",
            "source_type": source_type,
            "source_id": source_id,
            "ts": source_ts,
            "raw_line_id": rid,
            "snippet": _snippet(line),
        })

    # ── Pulmonary hygiene only (weak mention) ──────────────────
    for m in RE_PULM_HYGIENE_ONLY.finditer(text):
        line = _get_line_containing(text, m.start())
        rid = _make_raw_line_id(source_type, source_id, line)
        if any(e["raw_line_id"] == rid for e in evidence):
            continue

        # Only record as weak mention — does NOT set is_mentioned=yes
        mentions.append({
            "type": "pulm_hygiene_only",
            "text": _snippet(line),
            "ts": source_ts,
            "raw_line_id": rid,
            "source_type": source_type,
        })
        evidence.append({
            "role": "is_mention",
            "label": "pulm_hygiene_only",
            "source_type": source_type,
            "source_id": source_id,
            "ts": source_ts,
            "raw_line_id": rid,
            "snippet": _snippet(line),
        })

    # ── Flowsheet data extraction ──────────────────────────────
    if RE_FLOWSHEET_HEADER.search(text) and RE_FLOWSHEET_COL_HEADER.search(text):
        fs_measurements, fs_evidence, fs_notes = _parse_flowsheet_block(
            text, source_type, source_id, source_ts,
        )
        flowsheet_measurements.extend(fs_measurements)
        evidence.extend(fs_evidence)
        notes.extend(fs_notes)

    return {
        "mentions": mentions,
        "orders": orders,
        "flowsheet_measurements": flowsheet_measurements,
        "evidence": evidence,
        "notes": notes,
        "warnings": warnings,
    }


def _get_line_containing(text: str, pos: int) -> str:
    """Extract the full line containing position `pos`."""
    start = text.rfind("\n", 0, pos)
    start = start + 1 if start >= 0 else 0
    end = text.find("\n", pos)
    end = end if end >= 0 else len(text)
    return text[start:end].strip()


# ── Main extractor ──────────────────────────────────────────────────

def extract_incentive_spirometry(
    pat_features: Dict[str, Any],
    days_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Extract incentive spirometry data from patient timeline.

    Args:
        pat_features: partial patient features dict (unused, API compat).
        days_data: full patient_days_v1.json dict.

    Returns:
        Structured dict with IS presence, mentions, orders,
        measurements, goals, evidence, notes, warnings.
    """
    all_mentions: List[Dict[str, Any]] = []
    all_orders: List[Dict[str, Any]] = []
    all_measurements: List[Dict[str, Any]] = []
    all_evidence: List[Dict[str, Any]] = []
    all_notes: List[str] = []
    all_warnings: List[str] = []

    days = days_data.get("days", {})
    if not days:
        return _build_result(
            mentions=[], orders=[], measurements=[],
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

            all_mentions.extend(scan["mentions"])
            all_orders.extend(scan["orders"])
            all_measurements.extend(scan["flowsheet_measurements"])
            all_evidence.extend(scan["evidence"])
            all_notes.extend(scan["notes"])
            all_warnings.extend(scan["warnings"])

    return _build_result(
        mentions=all_mentions,
        orders=all_orders,
        measurements=all_measurements,
        evidence=all_evidence,
        notes=all_notes,
        warnings=all_warnings,
    )


def _build_result(
    mentions: List[Dict[str, Any]],
    orders: List[Dict[str, Any]],
    measurements: List[Dict[str, Any]],
    evidence: List[Dict[str, Any]],
    notes: List[str],
    warnings: List[str],
) -> Dict[str, Any]:
    """Assemble the final output dict."""

    # Determine is_mentioned:
    #   "yes" if any strong IS reference (explicit, plan, order, is_use,
    #          flowsheet data)
    #   "no" if only pulm_hygiene_only (weak mention)
    #   _DNA if no mentions at all
    strong_mention_types = {"explicit_is", "plan_is", "is_use", "is_order"}
    has_strong = any(
        m.get("type") in strong_mention_types for m in mentions
    )
    has_order = len(orders) > 0
    has_measurement = len(measurements) > 0

    if has_strong or has_order or has_measurement:
        is_mentioned = "yes"
    elif mentions:
        # Only weak mentions (pulm_hygiene_only)
        is_mentioned = "no"
        notes.append(
            "pulm_hygiene_only_no_explicit_is: pulmonary hygiene "
            "mentioned but no explicit incentive spirometry reference"
        )
    else:
        is_mentioned = _DNA

    # is_value_present: "yes" only if numeric volumes in measurements
    has_values = any(
        "avg_volume_cc" in m or "largest_volume_cc" in m
        for m in measurements
    )
    is_value_present = "yes" if has_values else "no"

    # Extract unique goals
    goals: List[Dict[str, Any]] = []
    seen_goals: set = set()
    for m in measurements:
        g = m.get("goal_cc")
        if g and g not in seen_goals:
            seen_goals.add(g)
            goals.append({
                "value": g,
                "unit": "cc",
                "source_ts": m.get("ts"),
            })

    # Count by mention type
    mention_type_counts: Dict[str, int] = {}
    for m in mentions:
        mt = m.get("type", "unknown")
        mention_type_counts[mt] = mention_type_counts.get(mt, 0) + 1

    return {
        "is_mentioned": is_mentioned,
        "is_value_present": is_value_present,
        "mention_count": len(mentions),
        "mention_type_counts": mention_type_counts,
        "mentions": mentions,
        "order_count": len(orders),
        "orders": orders,
        "measurement_count": len(measurements),
        "measurements": measurements,
        "goals": goals,
        "source_rule_id": "incentive_spirometry_v1",
        "evidence": evidence,
        "notes": notes,
        "warnings": warnings,
    }
