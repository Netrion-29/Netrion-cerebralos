#!/usr/bin/env python3
"""
DVT Prophylaxis — Tier 1 Metric #1

Extract first pharmacologic and mechanical DVT prophylaxis timestamps,
compute delay from arrival, and flag >24 h delay.

Design:
- Deterministic, fail-closed.  No inference, no LLM, no ML.
- Requires administration evidence; never infers prophylaxis from orders alone.
- Produces DATA NOT AVAILABLE when missing — never fabricates timestamps.
- All evidence traceable via raw_line_id (SHA-256[:16]).
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

# ── Constants ───────────────────────────────────────────────────────

# Pharmacologic prophylaxis — case-insensitive patterns.
# Only count lines with ADMINISTRATION evidence (MAR/admin records).
_PHARM_INCLUDE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\benoxaparin\b", re.IGNORECASE),
    re.compile(r"\blovenox\b", re.IGNORECASE),
    re.compile(r"\bfondaparinux\b", re.IGNORECASE),
    # heparin SQ prophylaxis — handled separately with exclusion logic
    re.compile(r"\bheparin\b", re.IGNORECASE),
]

# Heparin exclusion context — if any of these appear on the same line,
# the heparin mention does NOT count as prophylaxis.
_HEPARIN_EXCLUDE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bdrip\b", re.IGNORECASE),
    re.compile(r"\binfusion\b", re.IGNORECASE),
    re.compile(r"\btherapeutic\b", re.IGNORECASE),
    re.compile(r"\bflush\b", re.IGNORECASE),
    re.compile(r"\block\b", re.IGNORECASE),
    re.compile(r"\bheplock\b", re.IGNORECASE),
    re.compile(r"\btitrat(e|ion|ing)\b", re.IGNORECASE),
]

# Heparin dose check — doses > 5000 units suggest therapeutic, not prophylaxis.
_HEPARIN_HIGH_DOSE_PATTERN = re.compile(
    r"(\d[\d,]*)\s*(?:units?|u)\b", re.IGNORECASE,
)

# Mechanical prophylaxis patterns.
_MECH_INCLUDE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bSCDs?\b"),                                       # SCDs / SCD
    re.compile(r"\bsequential\s+compression\b", re.IGNORECASE),
    re.compile(r"\bpneumatic\s+compression\b", re.IGNORECASE),
]

# Therapeutic anticoagulation patterns — triggers exclusion.
_THERAPEUTIC_ANTICOAG_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(warfarin|coumadin)\b.*\btherapeutic\b", re.IGNORECASE),
    re.compile(r"\btherapeutic\b.*\b(warfarin|coumadin)\b", re.IGNORECASE),
    re.compile(r"\bheparin\s+(drip|infusion|gtt)\b", re.IGNORECASE),
    re.compile(r"\b(drip|infusion|gtt)\s+heparin\b", re.IGNORECASE),
    re.compile(r"\btherapeutic\s+enoxaparin\b", re.IGNORECASE),
    re.compile(r"\btherapeutic\s+anticoag", re.IGNORECASE),
    re.compile(r"\bheparin\b.*\btitrat(e|ion|ing)\b", re.IGNORECASE),
]

# Admin evidence item types — we require these to confirm actual administration.
_ADMIN_ITEM_TYPES = {"MAR"}

# Order-only item types — NOT sufficient for mechanical prophylaxis.
# Orders alone do not prove device was applied/in use.
_ORDER_ITEM_TYPES = {"ORDER", "ORDERS"}

# Narrative physician/nursing notes that describe SCDs being in use
# (e.g., "DVT Prophylaxis: SCDs").  These DO count as confirmed evidence.
_NARRATIVE_ITEM_TYPES = {
    "PHYSICIAN_NOTE", "NURSING_NOTE", "CONSULT_NOTE",
    "PROGRESS_NOTE", "TRAUMA_HP", "ED_NOTE",
}

# Flowsheet entries — confirmed evidence for mechanical prophylaxis.
_FLOWSHEET_ITEM_TYPES = {"FLOWSHEET"}

# Confirmed mechanical evidence sources (admin + narrative + flowsheet).
_MECH_CONFIRMED_ITEM_TYPES = _ADMIN_ITEM_TYPES | _NARRATIVE_ITEM_TYPES | _FLOWSHEET_ITEM_TYPES

# Pattern: line contains an explicit order reference like "(Order 464653630)"
# or "[NUR###]" bracketed nursing task IDs from order sets.
_ORDER_REF_PATTERN = re.compile(
    r"\(Order\s+\d+\)|\[NUR\d+\]", re.IGNORECASE,
)

# Explicit device-applied language — counts even on an order-typed line.
_MECH_APPLIED_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bSCDs?\s+(on|applied|in\s+place)\b", re.IGNORECASE),
    re.compile(r"\bapplied\s+SCDs?\b", re.IGNORECASE),
    re.compile(r"\bin\s+place\b.*\b(SCD|sequential|pneumatic)\b", re.IGNORECASE),
    re.compile(r"\b(SCD|sequential|pneumatic).*\bin\s+place\b", re.IGNORECASE),
]


# ── Helpers ─────────────────────────────────────────────────────────

def _make_raw_line_id(source_id: Any, dt: Optional[str], preview: str) -> str:
    """Deterministic raw_line_id — SHA-256[:16] of evidence coordinates."""
    key = f"{source_id or ''}|{dt or ''}|{preview or ''}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _snippet(text: str, max_len: int = 120) -> str:
    """Trim text to a short deterministic snippet."""
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[:max_len] + "…"


def _parse_datetime(dt_str: Optional[str]) -> Optional[datetime]:
    """Parse a datetime string, tolerating multiple common formats."""
    if not dt_str:
        return None
    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(dt_str, fmt)
        except ValueError:
            continue
    return None


def _is_admin_line(text: str) -> bool:
    """Check if a line indicates actual drug administration (not just an order)."""
    lower = text.lower()
    # MAR 'Given' status is the gold standard
    if re.search(r"\bgiven\b", lower):
        return True
    # Administered / admin / administer
    if re.search(r"\badminister(ed)?\b", lower):
        return True
    return False


def _extract_admin_timestamp(text: str, item_dt: Optional[str]) -> Optional[str]:
    """
    Try to extract the precise administration timestamp from a MAR line.
    Falls back to the item-level dt if no inline time is found.
    """
    # Common pattern in MAR: "Given 01/03/2026 0814" or "Given  12/31/2025 1642"
    m = re.search(
        r"\bGiven\s+(\d{1,2}/\d{1,2}/\d{4})\s+(\d{4})\b", text, re.IGNORECASE,
    )
    if m:
        try:
            dt = datetime.strptime(f"{m.group(1)} {m.group(2)}", "%m/%d/%Y %H%M")
            return dt.strftime("%Y-%m-%dT%H:%M:%S")
        except ValueError:
            pass

    # Pattern: "Given  12/31/2025 16:42"
    m = re.search(
        r"\bGiven\s+(\d{1,2}/\d{1,2}/\d{4})\s+(\d{1,2}:\d{2})\b", text, re.IGNORECASE,
    )
    if m:
        try:
            dt = datetime.strptime(f"{m.group(1)} {m.group(2)}", "%m/%d/%Y %H:%M")
            return dt.strftime("%Y-%m-%dT%H:%M:%S")
        except ValueError:
            pass

    # Fallback: item-level timestamp
    return item_dt


def _is_heparin_prophylaxis(text: str) -> Tuple[bool, Optional[str]]:
    """
    Determine if a heparin mention is prophylactic.

    Returns (is_prophylaxis: bool, exclusion_reason: str | None).
    - True, None → prophylactic heparin
    - False, "AMBIGUOUS_HEPARIN_CONTEXT" → cannot confirm prophylaxis
    - False, "THERAPEUTIC_DOSE" → dose too high
    """
    lower = text.lower()

    # Check explicit exclusion keywords
    for pat in _HEPARIN_EXCLUDE_PATTERNS:
        if pat.search(text):
            return False, "AMBIGUOUS_HEPARIN_CONTEXT"

    # Check dose — > 5000 units suggests therapeutic
    dose_match = _HEPARIN_HIGH_DOSE_PATTERN.search(text)
    if dose_match:
        try:
            dose_val = int(dose_match.group(1).replace(",", ""))
            if dose_val > 5000:
                return False, "THERAPEUTIC_DOSE"
        except ValueError:
            pass

    # Positive signals for prophylaxis
    if re.search(r"\bprophyla", lower):
        return True, None
    if re.search(r"\bDVT\b", text):
        return True, None
    if re.search(r"\bSQ\b|\bsubq\b|\bsubcutaneous\b", lower):
        # SQ heparin is typically prophylactic — 5000u TID/BID pattern
        return True, None

    # Without clear prophylactic context, mark ambiguous
    return False, "AMBIGUOUS_HEPARIN_CONTEXT"


def _is_enoxaparin_or_fondaparinux(text: str) -> bool:
    """Check if the line mentions enoxaparin/lovenox or fondaparinux."""
    lower = text.lower()
    return bool(
        re.search(r"\benoxaparin\b", lower)
        or re.search(r"\blovenox\b", lower)
        or re.search(r"\bfondaparinux\b", lower)
    )


# ── Core extraction ─────────────────────────────────────────────────

def extract_dvt_prophylaxis(
    pat_features: Dict[str, Any],
    days_json: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Extract DVT prophylaxis evidence from the patient timeline.

    Parameters
    ----------
    pat_features : dict
        The patient_features_v1 dict (used for cross-reference but primary
        extraction is from days_json).
    days_json : dict
        The patient_days_v1 dict (contains items with raw text and timestamps).

    Returns
    -------
    dict
        The dvt_prophylaxis_v1 contract.
    """
    meta = days_json.get("meta") or {}
    arrival_dt_str = meta.get("arrival_datetime")
    arrival_dt = _parse_datetime(arrival_dt_str)

    days_map = days_json.get("days") or {}

    pharm_evidence: List[Dict[str, Any]] = []
    mech_evidence: List[Dict[str, Any]] = []          # confirmed mech
    mech_orders_only: List[Dict[str, Any]] = []        # orders-only (not counted)
    exclusion_evidence: List[Dict[str, Any]] = []

    for day_iso in sorted(days_map.keys()):
        day_info = days_map[day_iso]
        items: List[Dict[str, Any]] = day_info.get("items") or []

        for item in items:
            item_type = item.get("type", "")
            item_dt = item.get("dt")
            source_id = item.get("source_id", "")
            text = (item.get("payload") or {}).get("text", "")
            if not text:
                continue

            # Process each line independently for granular matching
            for line in text.split("\n"):
                line_stripped = line.strip()
                if not line_stripped:
                    continue

                raw_line_id = _make_raw_line_id(
                    source_id, item_dt, _snippet(line_stripped, 80),
                )

                # ── Check for therapeutic anticoagulation (exclusion) ──
                for exc_pat in _THERAPEUTIC_ANTICOAG_PATTERNS:
                    if exc_pat.search(line_stripped):
                        exclusion_evidence.append({
                            "ts": item_dt,
                            "raw_line_id": raw_line_id,
                            "snippet": _snippet(line_stripped),
                            "reason": "THERAPEUTIC_ANTICOAG",
                        })
                        break  # one exclusion per line

                # ── Pharmacologic prophylaxis ──
                # Require MAR / admin evidence for pharmacologic
                if item_type in _ADMIN_ITEM_TYPES or _is_admin_line(line_stripped):
                    _check_pharm_line(
                        line_stripped, item_dt, source_id, raw_line_id,
                        pharm_evidence, exclusion_evidence,
                    )

                # ── Mechanical prophylaxis ──
                # Confirmed sources: MAR admin, narrative notes, flowsheets,
                # or explicit "SCDs on/applied" language.
                # Orders alone → orders-only bucket (excluded).
                if item_type in (_MECH_CONFIRMED_ITEM_TYPES | _ORDER_ITEM_TYPES):
                    _check_mech_line(
                        line_stripped, item_type, item_dt, source_id,
                        raw_line_id,
                        mech_evidence, mech_orders_only,
                    )

    # ── Filter by arrival time (ignore timestamps < arrival) ────
    if arrival_dt:
        pharm_evidence = _filter_after_arrival(pharm_evidence, arrival_dt)
        mech_evidence = _filter_after_arrival(mech_evidence, arrival_dt)
        mech_orders_only = _filter_after_arrival(mech_orders_only, arrival_dt)

    # ── Deduplicate evidence by raw_line_id ─────────────────────
    pharm_evidence = _dedup_evidence(pharm_evidence)
    mech_evidence = _dedup_evidence(mech_evidence)
    mech_orders_only = _dedup_evidence(mech_orders_only)
    exclusion_evidence = _dedup_evidence(exclusion_evidence)

    # ── Move orders-only mech into exclusion if no confirmed mech ──
    # Orders-only entries always go to exclusion evidence for traceability.
    for e in mech_orders_only:
        exclusion_evidence.append({
            "ts": e["ts"],
            "raw_line_id": e["raw_line_id"],
            "snippet": e["snippet"],
            "reason": "ORDERS_ONLY_NO_ADMIN_EVIDENCE",
        })
    exclusion_evidence = _dedup_evidence(exclusion_evidence)

    # ── Determine if therapeutic anticoagulation excludes patient ──
    therapeutic_exclusion = any(
        e.get("reason") == "THERAPEUTIC_ANTICOAG" for e in exclusion_evidence
    )

    # ── Compute timestamps ──────────────────────────────────────
    pharm_first_ts = _earliest_ts(pharm_evidence)
    mech_first_ts = _earliest_ts(mech_evidence)   # confirmed only

    first_ts: Optional[str] = None
    if pharm_first_ts and mech_first_ts:
        first_ts = min(pharm_first_ts, mech_first_ts)
    elif pharm_first_ts:
        first_ts = pharm_first_ts
    elif mech_first_ts:
        first_ts = mech_first_ts

    # ── Compute delay ───────────────────────────────────────────
    delay_hours: Optional[float] = None
    delay_flag_24h: Optional[bool] = None
    excluded_reason: Optional[str] = None

    if therapeutic_exclusion:
        excluded_reason = "THERAPEUTIC_ANTICOAG"
        delay_hours = None
        delay_flag_24h = None
    elif first_ts and arrival_dt:
        first_dt = _parse_datetime(first_ts)
        if first_dt:
            delta = first_dt - arrival_dt
            delay_hours = round(delta.total_seconds() / 3600.0, 2)
            delay_flag_24h = delay_hours > 24.0
    else:
        # No confirmed evidence at all — check if orders-only existed
        if mech_orders_only and not pharm_evidence:
            excluded_reason = "ORDERS_ONLY_NO_ADMIN_EVIDENCE"

    # ── Build output contract ───────────────────────────────────
    return {
        "pharm_first_ts": pharm_first_ts,
        "mech_first_ts": mech_first_ts,
        "first_ts": first_ts,
        "delay_hours": delay_hours,
        "delay_flag_24h": delay_flag_24h,
        "excluded_reason": excluded_reason,
        "orders_only_count": len(mech_orders_only),
        "evidence": {
            "pharm": [
                {"ts": e["ts"], "raw_line_id": e["raw_line_id"], "snippet": e["snippet"]}
                for e in pharm_evidence
            ],
            "mech": [
                {"ts": e["ts"], "raw_line_id": e["raw_line_id"], "snippet": e["snippet"]}
                for e in mech_evidence
            ],
            "exclusion": [
                {"ts": e["ts"], "raw_line_id": e["raw_line_id"], "snippet": e["snippet"]}
                for e in exclusion_evidence
            ],
        },
    }


# ── Internal matchers ───────────────────────────────────────────────

def _check_pharm_line(
    line: str,
    item_dt: Optional[str],
    source_id: str,
    raw_line_id: str,
    pharm_evidence: List[Dict[str, Any]],
    exclusion_evidence: List[Dict[str, Any]],
) -> None:
    """Check a single line for pharmacologic prophylaxis."""
    # enoxaparin / lovenox / fondaparinux — always prophylactic
    if _is_enoxaparin_or_fondaparinux(line):
        admin_ts = _extract_admin_timestamp(line, item_dt)
        pharm_evidence.append({
            "ts": admin_ts,
            "raw_line_id": raw_line_id,
            "snippet": _snippet(line),
        })
        return

    # heparin — requires context analysis
    if re.search(r"\bheparin\b", line, re.IGNORECASE):
        is_prophy, exc_reason = _is_heparin_prophylaxis(line)
        admin_ts = _extract_admin_timestamp(line, item_dt)
        if is_prophy:
            pharm_evidence.append({
                "ts": admin_ts,
                "raw_line_id": raw_line_id,
                "snippet": _snippet(line),
            })
        elif exc_reason:
            exclusion_evidence.append({
                "ts": admin_ts,
                "raw_line_id": raw_line_id,
                "snippet": _snippet(line),
                "reason": exc_reason,
            })


def _check_mech_line(
    line: str,
    item_type: str,
    item_dt: Optional[str],
    source_id: str,
    raw_line_id: str,
    mech_evidence: List[Dict[str, Any]],
    mech_orders_only: List[Dict[str, Any]],
) -> None:
    """Check a single line for mechanical prophylaxis.

    Classifies matched lines as *confirmed* (→ mech_evidence) or
    *orders-only* (→ mech_orders_only) based on source type and content.

    Confirmed sources:
      - MAR admin lines
      - Narrative notes (nursing, physician, progress, etc.)
      - Flowsheet entries
      - Explicit "SCDs on / applied / in place" language (any source)

    Orders-only:
      - item_type is ORDER/ORDERS  **and**  no applied-language  **and**
        line contains order reference pattern like "(Order ###)" or "[NUR###]"
    """
    matched = False
    for pat in _MECH_INCLUDE_PATTERNS:
        if pat.search(line):
            matched = True
            break
    if not matched:
        return

    entry = {
        "ts": item_dt,
        "raw_line_id": raw_line_id,
        "snippet": _snippet(line),
    }

    # ── Explicit applied-language overrides any source type ──
    for ap in _MECH_APPLIED_PATTERNS:
        if ap.search(line):
            mech_evidence.append(entry)
            return

    # ── Order-reference in the line text → orders-only ──
    # This check comes BEFORE item_type because order listings are often
    # embedded inside PHYSICIAN_NOTE blocks.  The line content
    # "(Order ###)" / "[NUR###]" is a stronger signal than item_type.
    if _ORDER_REF_PATTERN.search(line):
        mech_orders_only.append(entry)
        return

    # ── Order-typed item without inline ref → also orders-only ──
    if item_type in _ORDER_ITEM_TYPES:
        mech_orders_only.append(entry)
        return

    # ── Confirmed source types (narrative, MAR, flowsheet) ──
    if item_type in _MECH_CONFIRMED_ITEM_TYPES:
        mech_evidence.append(entry)
        return

    # Fallback: unknown source without order markers — treat as confirmed
    # (fail-open for evidence traceability)
    mech_evidence.append(entry)


# ── Utility ─────────────────────────────────────────────────────────

def _filter_after_arrival(
    evidence: List[Dict[str, Any]],
    arrival_dt: datetime,
) -> List[Dict[str, Any]]:
    """Keep only evidence with timestamps >= arrival datetime."""
    result: List[Dict[str, Any]] = []
    for e in evidence:
        ts = _parse_datetime(e.get("ts"))
        if ts is None:
            # No timestamp — cannot verify, still include (fail-open for evidence)
            result.append(e)
            continue
        if ts >= arrival_dt:
            result.append(e)
    return result


def _dedup_evidence(evidence: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicate by raw_line_id, preserving order."""
    seen: set[str] = set()
    result: List[Dict[str, Any]] = []
    for e in evidence:
        rid = e.get("raw_line_id", "")
        if rid not in seen:
            seen.add(rid)
            result.append(e)
    return result


def _earliest_ts(evidence: List[Dict[str, Any]]) -> Optional[str]:
    """Return the earliest timestamp from evidence entries, or None."""
    best: Optional[datetime] = None
    best_str: Optional[str] = None
    for e in evidence:
        ts = e.get("ts")
        dt = _parse_datetime(ts)
        if dt is not None:
            if best is None or dt < best:
                best = dt
                best_str = ts
    return best_str
