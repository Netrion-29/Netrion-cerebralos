#!/usr/bin/env python3
"""
GI Prophylaxis — Tier 1 Metric #2

Extract first *pharmacologic* GI prophylaxis administration timestamp,
compute delay from arrival, and flag >48 h delay.

Drug classes:  PPIs, H2-receptor antagonists, mucosal protectants.
Only administration/dispense evidence counts (MAR/Given/Administered/
Dispensed).  Orders-only and home-med/discharge-only mentions are
classified as ambiguous.

Design:
- Deterministic, fail-closed.  No inference, no LLM, no ML.
- Requires administration/dispense evidence for pharmacologic lines;
  monitoring, plan, and order text are classified as ambiguous.
- Produces DATA NOT AVAILABLE when missing — never fabricates timestamps.
- All evidence traceable via raw_line_id (SHA-256[:16]).
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# ── Constants ───────────────────────────────────────────────────────

# GI prophylaxis drug patterns — case-insensitive.
_GI_DRUG_PATTERNS: list[re.Pattern[str]] = [
    # PPIs
    re.compile(r"\bpantoprazole\b", re.IGNORECASE),
    re.compile(r"\bprotonix\b", re.IGNORECASE),
    re.compile(r"\bomeprazole\b", re.IGNORECASE),
    re.compile(r"\blansoprazole\b", re.IGNORECASE),
    re.compile(r"\besomeprazole\b", re.IGNORECASE),
    # H2 blockers
    re.compile(r"\bfamotidine\b", re.IGNORECASE),
    re.compile(r"\bpepcid\b", re.IGNORECASE),
    re.compile(r"\branitidine\b", re.IGNORECASE),
    # Mucosal protectants
    re.compile(r"\bsucralfate\b", re.IGNORECASE),
]

# ── Admin gating — confirm actual administration ────────────────
# Positive signals confirming drug was actually administered/dispensed.
_ADMIN_CONFIRM_SIGNALS: list[re.Pattern[str]] = [
    re.compile(r"\bgiven\b", re.IGNORECASE),
    re.compile(r"\badministered\b", re.IGNORECASE),
    re.compile(r"\bmedication\s+administration\b", re.IGNORECASE),
    re.compile(r"\bdose\s+given\b", re.IGNORECASE),
    re.compile(r"\blast\s+dose\b", re.IGNORECASE),
    re.compile(r"\bscheduled\s+dose\s+administered\b", re.IGNORECASE),
    re.compile(r"\bdispens(e|ed|ing)\b", re.IGNORECASE),
]

# Negative signals — monitoring / plan / order text (not actual admin).
_ADMIN_EXCLUDE_SIGNALS: list[re.Pattern[str]] = [
    re.compile(r"\bmonitor(ing)?\b", re.IGNORECASE),
    re.compile(r"\bplan\b", re.IGNORECASE),
    re.compile(r"\brecommend(ed|ing|ation)?\b", re.IGNORECASE),
    re.compile(r"\bconsider(ed|ing)?\b", re.IGNORECASE),
    re.compile(r"\bdiscuss(ed|ing|ion)?\b", re.IGNORECASE),
    re.compile(r"\bwill\s+start\b", re.IGNORECASE),
    re.compile(r"\bto\s+start\b", re.IGNORECASE),
    re.compile(r"\b(hold|held)\b", re.IGNORECASE),
]

# Home-med / discharge-only context patterns → ambiguous.
_HOME_MED_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bhome\s+med(ication)?s?\b", re.IGNORECASE),
    re.compile(r"\bhome\s+rx\b", re.IGNORECASE),
    re.compile(r"\bprior\s+to\s+admission\b", re.IGNORECASE),
    re.compile(r"\bpreadmission\b", re.IGNORECASE),
    re.compile(r"\bmedication\s+reconciliation\b", re.IGNORECASE),
    re.compile(r"\btakes\s+at\s+home\b", re.IGNORECASE),
    re.compile(r"\bhome\s+regimen\b", re.IGNORECASE),
]

_DISCHARGE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bdischarge\s+summar(y|ies)\b", re.IGNORECASE),
    re.compile(r"\bdischarge\s+med(ication)?s?\b", re.IGNORECASE),
    re.compile(r"\bupon\s+discharge\b", re.IGNORECASE),
    re.compile(r"\bat\s+discharge\b", re.IGNORECASE),
]

# Hold / contraindication patterns — explicit proximity required.
_GI_HOLD_CONTRA_PATTERNS: list[re.Pattern[str]] = [
    # "PPI on hold" / "PPI held"
    re.compile(r"\bPPI\s+(on\s+hold|held|hold)\b", re.IGNORECASE),
    # "<drug> on hold" / "<drug> held" / "hold <drug>" / "held <drug>"
    re.compile(r"\b(hold|held)\s+(pantoprazole|protonix)\b", re.IGNORECASE),
    re.compile(r"\b(hold|held)\s+(omeprazole)\b", re.IGNORECASE),
    re.compile(r"\b(hold|held)\s+(lansoprazole)\b", re.IGNORECASE),
    re.compile(r"\b(hold|held)\s+(esomeprazole)\b", re.IGNORECASE),
    re.compile(r"\b(hold|held)\s+(famotidine|pepcid)\b", re.IGNORECASE),
    re.compile(r"\b(hold|held)\s+(ranitidine)\b", re.IGNORECASE),
    re.compile(r"\b(hold|held)\s+(sucralfate)\b", re.IGNORECASE),
    # Drug directly before hold/held
    re.compile(r"\b(pantoprazole|protonix)\b[^,.;]{0,20}\b(on\s+hold|held)\b", re.IGNORECASE),
    re.compile(r"\b(omeprazole)\b[^,.;]{0,20}\b(on\s+hold|held)\b", re.IGNORECASE),
    re.compile(r"\b(lansoprazole)\b[^,.;]{0,20}\b(on\s+hold|held)\b", re.IGNORECASE),
    re.compile(r"\b(esomeprazole)\b[^,.;]{0,20}\b(on\s+hold|held)\b", re.IGNORECASE),
    re.compile(r"\b(famotidine|pepcid)\b[^,.;]{0,20}\b(on\s+hold|held)\b", re.IGNORECASE),
    re.compile(r"\b(ranitidine)\b[^,.;]{0,20}\b(on\s+hold|held)\b", re.IGNORECASE),
    re.compile(r"\b(sucralfate)\b[^,.;]{0,20}\b(on\s+hold|held)\b", re.IGNORECASE),
    # GI prophylaxis contraindicated
    re.compile(r"\bGI\s+prophylax\w*\b[^.]*\bcontraindic", re.IGNORECASE),
    re.compile(r"\bcontraindic\w*\b[^.]*\bGI\s+prophylax", re.IGNORECASE),
    # Dash-list format: "- famotidine on hold"
    re.compile(r"-\s*(pantoprazole|protonix|omeprazole|lansoprazole|esomeprazole|famotidine|pepcid|ranitidine|sucralfate)\s+(on\s+hold|hold|held)\b", re.IGNORECASE),
]

# Admin item types — MAR records
_ADMIN_ITEM_TYPES = {"MAR"}

# Order-only item types — NOT sufficient for admin evidence.
_ORDER_ITEM_TYPES = {"ORDER", "ORDERS"}


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


def _has_gi_drug_keyword(text: str) -> bool:
    """Check if any GI prophylaxis drug keyword matches."""
    for pat in _GI_DRUG_PATTERNS:
        if pat.search(text):
            return True
    return False


def _classify_admin(line: str, item_type: str) -> str:
    """Classify a GI drug mention as ADMIN_CONFIRMED or AMBIGUOUS.

    Logic:
    1. Explicit admin signals (Given, Administered, …) → ADMIN_CONFIRMED.
    2. Everything else → AMBIGUOUS_NON_ADMIN_MENTION.
    """
    has_admin_sig = any(p.search(line) for p in _ADMIN_CONFIRM_SIGNALS)
    if has_admin_sig:
        return "ADMIN_CONFIRMED"
    return "AMBIGUOUS_NON_ADMIN_MENTION"


def _extract_admin_timestamp(text: str, item_dt: Optional[str]) -> Optional[str]:
    """
    Try to extract the precise administration timestamp from a MAR line.
    Falls back to the item-level dt if no inline time is found.
    """
    # Common pattern in MAR: "Given 01/03/2026 0814"
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


def _is_home_med_or_discharge(line: str) -> bool:
    """Check if a line is a home-med or discharge-summary-only mention."""
    for pat in _HOME_MED_PATTERNS:
        if pat.search(line):
            return True
    for pat in _DISCHARGE_PATTERNS:
        if pat.search(line):
            return True
    return False


# ── Core extraction ─────────────────────────────────────────────────

def extract_gi_prophylaxis(
    pat_features: Dict[str, Any],
    days_json: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Extract GI prophylaxis evidence from the patient timeline.

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
        The gi_prophylaxis_v1 contract.
    """
    meta = days_json.get("meta") or {}
    arrival_dt_str = meta.get("arrival_datetime")
    arrival_dt = _parse_datetime(arrival_dt_str)

    days_map = days_json.get("days") or {}

    pharm_evidence: List[Dict[str, Any]] = []
    pharm_ambiguous: List[Dict[str, Any]] = []
    orders_only: List[Dict[str, Any]] = []
    hold_contra_evidence: List[Dict[str, Any]] = []
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

            # Section-level drug context for admin-line inheritance.
            # In structured MAR data, a medication header line (containing
            # drug name + order ID bracket like [464395730]) starts a new
            # medication section.  Subsequent "Given :" lines inherit that
            # drug context until a new header resets it.
            _section_drug: Optional[str] = None  # drug name or None

            for line in text.split("\n"):
                line_stripped = line.strip()
                if not line_stripped:
                    continue

                # ── Update section-level drug context ──
                _is_header = bool(re.search(r"\[\d{6,}\]", line_stripped))
                _is_all_admin = line_stripped.lower().startswith(
                    "all administrations of"
                )
                if _is_header or _is_all_admin:
                    if _has_gi_drug_keyword(line_stripped):
                        _section_drug = "gi_drug"
                    else:
                        _section_drug = None

                raw_line_id = _make_raw_line_id(
                    source_id, item_dt, _snippet(line_stripped, 80),
                )

                # ── Check for GI prophylaxis held / contraindicated ──
                for hc_pat in _GI_HOLD_CONTRA_PATTERNS:
                    if hc_pat.search(line_stripped):
                        hold_contra_evidence.append({
                            "ts": item_dt,
                            "raw_line_id": raw_line_id,
                            "snippet": _snippet(line_stripped),
                            "reason": "GI_PROPHY_HELD_CONTRAINDICATION",
                        })
                        break  # one per line

                # ── GI drug keyword match ──
                _has_keyword = _has_gi_drug_keyword(line_stripped)
                if _has_keyword:
                    _check_gi_pharm_line(
                        line_stripped, item_type, item_dt, source_id,
                        raw_line_id,
                        pharm_evidence, pharm_ambiguous, orders_only,
                    )
                # Context-inherited admin: "Given :" tabular MAR rows
                elif _section_drug is not None:
                    _check_gi_given_inherited(
                        line_stripped,
                        item_type, item_dt, source_id, raw_line_id,
                        pharm_evidence, pharm_ambiguous,
                    )

    # ── Filter by arrival time (ignore timestamps < arrival) ────
    if arrival_dt:
        # Fail-closed: entries without timestamps cannot participate in
        # timing computation — route to ambiguous evidence.
        _no_ts = [e for e in pharm_evidence if e.get("ts") is None]
        for e in _no_ts:
            pharm_ambiguous.append({**e, "reason": "AMBIGUOUS_NO_TIMESTAMP"})
        pharm_evidence = [e for e in pharm_evidence if e.get("ts") is not None]

        pharm_evidence = _filter_after_arrival(pharm_evidence, arrival_dt)
        pharm_ambiguous = _filter_after_arrival(pharm_ambiguous, arrival_dt)
        orders_only = _filter_after_arrival(orders_only, arrival_dt)

    # ── Deduplicate evidence by raw_line_id ─────────────────────
    pharm_evidence = _dedup_evidence(pharm_evidence)
    pharm_ambiguous = _dedup_evidence(pharm_ambiguous)
    orders_only = _dedup_evidence(orders_only)
    hold_contra_evidence = _dedup_evidence(hold_contra_evidence)
    exclusion_evidence = _dedup_evidence(exclusion_evidence)

    # ── Move orders-only into exclusion for traceability ────────
    for e in orders_only:
        exclusion_evidence.append({
            "ts": e["ts"],
            "raw_line_id": e["raw_line_id"],
            "snippet": e["snippet"],
            "reason": "ORDERS_ONLY_NO_ADMIN_EVIDENCE",
        })
    # ── Move pharm ambiguous into exclusion for traceability ────
    for e in pharm_ambiguous:
        exclusion_evidence.append({
            "ts": e["ts"],
            "raw_line_id": e["raw_line_id"],
            "snippet": e["snippet"],
            "reason": e.get("reason", "AMBIGUOUS_NON_ADMIN_MENTION"),
        })
    # ── Move hold/contra into exclusion ─────────────────────────
    for e in hold_contra_evidence:
        exclusion_evidence.append({
            "ts": e["ts"],
            "raw_line_id": e["raw_line_id"],
            "snippet": e["snippet"],
            "reason": e.get("reason", "GI_PROPHY_HELD_CONTRAINDICATION"),
        })
    exclusion_evidence = _dedup_evidence(exclusion_evidence)

    # ── Determine exclusion reason (priority order) ─────────────
    has_hold_contra = len(hold_contra_evidence) > 0

    # ── Compute timestamps ──────────────────────────────────────
    pharm_first_ts = _earliest_ts(pharm_evidence)

    # ── Compute delay (from pharm_first_ts) ─────────────────────
    delay_hours: Optional[float] = None
    delay_flag_48h: Optional[bool] = None
    excluded_reason: Optional[str] = None

    if has_hold_contra and not pharm_first_ts:
        excluded_reason = "GI_PROPHY_HELD_CONTRAINDICATION"
        delay_hours = None
        delay_flag_48h = None
    elif pharm_first_ts and arrival_dt:
        first_dt = _parse_datetime(pharm_first_ts)
        if first_dt:
            delta = first_dt - arrival_dt
            delay_hours = round(delta.total_seconds() / 3600.0, 2)
            delay_flag_48h = delay_hours > 48.0
    else:
        # No confirmed admin evidence
        excluded_reason = "NO_GI_PROPHYLAXIS_EVIDENCE"

    # ── Build output contract ───────────────────────────────────
    return {
        "pharm_first_ts": pharm_first_ts,
        "delay_hours": delay_hours,
        "delay_flag_48h": delay_flag_48h,
        "excluded_reason": excluded_reason,
        "pharm_admin_evidence_count": len(pharm_evidence),
        "pharm_ambiguous_mention_count": len(pharm_ambiguous),
        "orders_only_count": len(orders_only),
        "evidence": {
            "pharm": [
                {"ts": e["ts"], "raw_line_id": e["raw_line_id"], "snippet": e["snippet"]}
                for e in pharm_evidence
            ],
            "exclusion": [
                {"ts": e["ts"], "raw_line_id": e["raw_line_id"],
                 "snippet": e["snippet"], "reason": e.get("reason", "")}
                for e in exclusion_evidence
            ],
        },
    }


# ── Internal matchers ───────────────────────────────────────────────

def _check_gi_pharm_line(
    line: str,
    item_type: str,
    item_dt: Optional[str],
    source_id: str,
    raw_line_id: str,
    pharm_evidence: List[Dict[str, Any]],
    pharm_ambiguous: List[Dict[str, Any]],
    orders_only: List[Dict[str, Any]],
) -> None:
    """Check a single line for GI prophylaxis drug administration.

    Admin gating: line must show admin/dispense evidence to count.
    Lines that match drug keywords but fail admin gating go to
    pharm_ambiguous as AMBIGUOUS_NON_ADMIN_MENTION.
    """
    admin_ts = _extract_admin_timestamp(line, item_dt)
    entry = {
        "ts": admin_ts,
        "raw_line_id": raw_line_id,
        "snippet": _snippet(line),
    }

    # Home-med / discharge-summary-only → always ambiguous
    if _is_home_med_or_discharge(line):
        pharm_ambiguous.append({**entry, "reason": "AMBIGUOUS_HOME_MED_OR_DISCHARGE"})
        return

    # Check for order-only context (item_type is ORDER or line has order ref)
    _order_ref = bool(re.search(r"\(Order\s+\d+\)|\[NUR\d+\]", line, re.IGNORECASE))
    if item_type in _ORDER_ITEM_TYPES or _order_ref:
        # Still check for admin signal — a line can have order ref AND admin status
        classification = _classify_admin(line, item_type)
        if classification == "ADMIN_CONFIRMED":
            pharm_evidence.append(entry)
        else:
            orders_only.append(entry)
        return

    # Standard admin gating
    classification = _classify_admin(line, item_type)
    if classification == "ADMIN_CONFIRMED":
        pharm_evidence.append(entry)
    else:
        pharm_ambiguous.append({**entry, "reason": "AMBIGUOUS_NON_ADMIN_MENTION"})


def _check_gi_given_inherited(
    line: str,
    item_type: str,
    item_dt: Optional[str],
    source_id: str,
    raw_line_id: str,
    pharm_evidence: List[Dict[str, Any]],
    pharm_ambiguous: List[Dict[str, Any]],
) -> None:
    """Process a 'Given :' tabular MAR line that inherits GI drug context.

    In structured MAR data, the drug name appears on a header line and
    individual admin rows ("Given : dose : route ...") lack the drug
    keyword.  This function catches those rows using section-level context.

    Only fires for lines that start with "Given" (case-insensitive)
    and explicitly skips "Not Given" / "Patient Refused" lines.
    """
    stripped = line.strip()

    # Must start with "Given" (tabular MAR admin status)
    if not re.match(r"^Given\b", stripped, re.IGNORECASE):
        return

    # Explicitly exclude "Not Given" lines
    if re.match(r"^Not\s+Given\b", stripped, re.IGNORECASE):
        return

    # Extract a precise timestamp from the tabular row.
    admin_ts = item_dt
    for ts_pat in (
        r"(\d{1,2}/\d{1,2}/\d{2})\s+(\d{4})\b",    # MM/DD/YY HHMM
        r"(\d{1,2}/\d{1,2}/\d{4})\s+(\d{4})\b",     # MM/DD/YYYY HHMM
    ):
        m = re.search(ts_pat, stripped)
        if m:
            date_str, time_str = m.group(1), m.group(2)
            for fmt in ("%m/%d/%y %H%M", "%m/%d/%Y %H%M"):
                try:
                    dt = datetime.strptime(f"{date_str} {time_str}", fmt)
                    admin_ts = dt.strftime("%Y-%m-%dT%H:%M:%S")
                    break
                except ValueError:
                    continue
            if admin_ts != item_dt:
                break

    entry = {
        "ts": admin_ts,
        "raw_line_id": raw_line_id,
        "snippet": _snippet(line),
    }

    pharm_evidence.append(entry)


# ── Utility ─────────────────────────────────────────────────────────

def _filter_after_arrival(
    evidence: List[Dict[str, Any]],
    arrival_dt: datetime,
) -> List[Dict[str, Any]]:
    """Keep only evidence with timestamps >= arrival datetime.

    Fail-closed: entries with ts=None are excluded (cannot verify timing).
    """
    result: List[Dict[str, Any]] = []
    for e in evidence:
        ts = _parse_datetime(e.get("ts"))
        if ts is None:
            # Fail-closed: no timestamp — cannot verify timing
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
