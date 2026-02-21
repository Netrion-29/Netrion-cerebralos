#!/usr/bin/env python3
"""
DVT Prophylaxis — Tier 1 Metric #1

Extract first *chemical* (pharmacologic) DVT prophylaxis timestamp,
compute delay from arrival, and flag >24 h delay.

Mechanical prophylaxis (SCDs) is tracked for context but does NOT
satisfy the DVT prophylaxis compliance metric.  dvt_first_ts and
delay_hours are derived from chemical prophylaxis only.

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

# ── Pharm admin gating — confirm actual administration ──────────
# Positive signals confirming drug was actually administered/dispensed.
_PHARM_ADMIN_CONFIRM_SIGNALS: list[re.Pattern[str]] = [
    re.compile(r"\bgiven\b", re.IGNORECASE),
    re.compile(r"\badministered\b", re.IGNORECASE),
    re.compile(r"\bmedication\s+administration\b", re.IGNORECASE),
    re.compile(r"\bdose\s+given\b", re.IGNORECASE),
    re.compile(r"\blast\s+dose\b", re.IGNORECASE),
    re.compile(r"\bscheduled\s+dose\s+administered\b", re.IGNORECASE),
    re.compile(r"\bdispens(e|ed|ing)\b", re.IGNORECASE),
]

# Negative signals — monitoring / plan / order text (not actual admin).
_PHARM_ADMIN_EXCLUDE_SIGNALS: list[re.Pattern[str]] = [
    re.compile(r"\bmonitor(ing)?\b", re.IGNORECASE),
    re.compile(r"\bplan\b", re.IGNORECASE),
    re.compile(r"\brecommend(ed|ing|ation)?\b", re.IGNORECASE),
    re.compile(r"\bconsider(ed|ing)?\b", re.IGNORECASE),
    re.compile(r"\bdiscuss(ed|ing|ion)?\b", re.IGNORECASE),
    re.compile(r"\bwill\s+start\b", re.IGNORECASE),
    re.compile(r"\bto\s+start\b", re.IGNORECASE),
    re.compile(r"\b(hold|held)\b", re.IGNORECASE),
]

# Chemical prophylaxis hold / contraindication patterns.
# Tightened to avoid false positives like "hold Eliquis, heparin subQ"
# where "hold" applies to a different drug.
_CHEM_HOLD_CONTRA_PATTERNS: list[re.Pattern[str]] = [
    # Direct: "hold <drug>" / "held <drug>" — immediately adjacent
    re.compile(r"\b(hold|held)\s+(lovenox|enoxaparin)\b", re.IGNORECASE),
    re.compile(r"\b(hold|held)\s+heparin\b", re.IGNORECASE),
    # "<drug> on hold" / "<drug> held" — drug directly before hold/held
    re.compile(r"\b(lovenox|enoxaparin)\b[^,.;]{0,20}\b(on\s+hold|held)\b", re.IGNORECASE),
    re.compile(r"\bheparin\b[^,.;]{0,20}\b(on\s+hold|held)\b", re.IGNORECASE),
    # Dash-list format: "- Lovenox on hold"
    re.compile(r"-\s*(lovenox|enoxaparin)\s+(on\s+hold|hold|held)\b", re.IGNORECASE),
    # Prophylaxis + contraindication language (broader scope OK here)
    re.compile(r"\bprophylax\w*\b[^.]*\bcontraindic", re.IGNORECASE),
    # Prophylaxis + specific clinical reasons
    re.compile(r"\bprophylax\w*\b[^.]*\bbleeding\s+risk\b", re.IGNORECASE),
    re.compile(r"\bbleeding\s+risk\b[^.]*\bprophylax\w*\b", re.IGNORECASE),
    re.compile(r"\bprophylax\w*\b[^.]*\bactive\s+bleed", re.IGNORECASE),
    re.compile(r"\bactive\s+bleed\w*\b[^.]*\bprophylax\w*\b", re.IGNORECASE),
    # Contraindications near bleeding/ICH
    re.compile(r"\bcontraindication\w*\b[^.]*\bbleeding\s+risk", re.IGNORECASE),
    re.compile(r"\bcontraindication\w*\b[^.]*\bactive\s+bleed", re.IGNORECASE),
    re.compile(r"\bcontraindication\w*\b[^.]*\bICH\b", re.IGNORECASE),
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


def _classify_pharm_mention(line: str, item_type: str) -> str:
    """Classify a pharm drug mention as ADMIN_CONFIRMED or AMBIGUOUS.

    Logic:
    1. Explicit admin signals (Given, Administered, …) always win → ADMIN_CONFIRMED.
    2. MAR item_type with explicit admin signal → ADMIN_CONFIRMED.
    3. MAR item_type without admin signal → AMBIGUOUS (header/order lines).
    4. Everything else → AMBIGUOUS_NON_ADMIN_MENTION.

    Note: MAR item_type alone is NOT sufficient.  MAR sections contain
    both order summaries and admin records.  We require an explicit admin
    signal (Given, Administered, etc.) on the line itself.
    """
    has_admin_sig = any(p.search(line) for p in _PHARM_ADMIN_CONFIRM_SIGNALS)

    # Explicit admin language takes priority
    if has_admin_sig:
        return "ADMIN_CONFIRMED"

    return "AMBIGUOUS_NON_ADMIN_MENTION"


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

    # Dose-based fallback: ≤ 5000 units without exclusion context
    # is very likely prophylactic (standard DVT prophylaxis dosing).
    if dose_match:
        try:
            dose_val = int(dose_match.group(1).replace(",", ""))
            if dose_val <= 5000:
                return True, None
        except ValueError:
            pass

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
    pharm_ambiguous: List[Dict[str, Any]] = []         # non-admin mentions
    mech_evidence: List[Dict[str, Any]] = []           # confirmed mech
    mech_orders_only: List[Dict[str, Any]] = []        # orders-only (not counted)
    hold_contra_evidence: List[Dict[str, Any]] = []    # chem hold / contraindication
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
            _section_drug: Optional[str] = None  # "enox" | "heparin" | None

            # Process each line independently for granular matching
            for line in text.split("\n"):
                line_stripped = line.strip()
                if not line_stripped:
                    continue

                # ── Update section-level drug context ──
                # Medication header pattern: line with [digits≥6] order ID
                # or "All Administrations of ..." header.
                _is_header = bool(re.search(r"\[\d{6,}\]", line_stripped))
                _is_all_admin = line_stripped.lower().startswith(
                    "all administrations of"
                )
                if _is_header or _is_all_admin:
                    if _is_enoxaparin_or_fondaparinux(line_stripped):
                        _section_drug = "enox"
                    elif re.search(r"\bheparin\b", line_stripped, re.IGNORECASE):
                        _section_drug = "heparin"
                    else:
                        _section_drug = None

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

                # ── Check for chemical prophylaxis held / contraindicated ──
                for hc_pat in _CHEM_HOLD_CONTRA_PATTERNS:
                    if hc_pat.search(line_stripped):
                        hold_contra_evidence.append({
                            "ts": item_dt,
                            "raw_line_id": raw_line_id,
                            "snippet": _snippet(line_stripped),
                            "reason": "CHEM_PROPHY_HELD_CONTRAINDICATION",
                        })
                        break  # one per line

                # ── Pharmacologic prophylaxis ──
                # Scan ALL lines for pharm drug keywords; admin gating
                # is applied inside _check_pharm_line via _classify_pharm_mention.
                _has_pharm_keyword = (
                    _is_enoxaparin_or_fondaparinux(line_stripped)
                    or re.search(r"\bheparin\b", line_stripped, re.IGNORECASE)
                )
                if _has_pharm_keyword:
                    _check_pharm_line(
                        line_stripped, item_type, item_dt, source_id,
                        raw_line_id,
                        pharm_evidence, pharm_ambiguous, exclusion_evidence,
                    )
                # Context-inherited admin: "Given :" tabular MAR rows that
                # lack the drug keyword on the same line but inherit it
                # from the section-level drug context.
                elif _section_drug is not None:
                    _check_pharm_given_inherited(
                        line_stripped,
                        _section_drug == "enox",
                        _section_drug == "heparin",
                        item_type, item_dt, source_id, raw_line_id,
                        pharm_evidence, pharm_ambiguous, exclusion_evidence,
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
        pharm_ambiguous = _filter_after_arrival(pharm_ambiguous, arrival_dt)
        mech_evidence = _filter_after_arrival(mech_evidence, arrival_dt)
        mech_orders_only = _filter_after_arrival(mech_orders_only, arrival_dt)

    # ── Deduplicate evidence by raw_line_id ─────────────────────
    pharm_evidence = _dedup_evidence(pharm_evidence)
    pharm_ambiguous = _dedup_evidence(pharm_ambiguous)
    mech_evidence = _dedup_evidence(mech_evidence)
    mech_orders_only = _dedup_evidence(mech_orders_only)
    hold_contra_evidence = _dedup_evidence(hold_contra_evidence)
    exclusion_evidence = _dedup_evidence(exclusion_evidence)

    # ── Move orders-only mech into exclusion for traceability ───
    for e in mech_orders_only:
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
            "reason": e.get("reason", "CHEM_PROPHY_HELD_CONTRAINDICATION"),
        })
    exclusion_evidence = _dedup_evidence(exclusion_evidence)

    # ── Determine exclusion reason (priority order) ─────────────
    therapeutic_exclusion = any(
        e.get("reason") == "THERAPEUTIC_ANTICOAG" for e in exclusion_evidence
    )
    has_hold_contra = len(hold_contra_evidence) > 0

    # ── Compute timestamps ──────────────────────────────────────
    # PRIMARY: chemical prophylaxis only
    pharm_first_ts = _earliest_ts(pharm_evidence)
    mech_first_ts = _earliest_ts(mech_evidence)   # informational only

    # first_ts = pharm_first_ts (mechanical does NOT satisfy metric)
    first_ts = pharm_first_ts

    # ── Compute delay (from pharm_first_ts only) ────────────────
    delay_hours: Optional[float] = None
    delay_flag_24h: Optional[bool] = None
    excluded_reason: Optional[str] = None

    if therapeutic_exclusion:
        excluded_reason = "THERAPEUTIC_ANTICOAG"
        delay_hours = None
        delay_flag_24h = None
    elif has_hold_contra and not pharm_first_ts:
        excluded_reason = "CHEM_PROPHY_HELD_CONTRAINDICATION"
        delay_hours = None
        delay_flag_24h = None
    elif pharm_first_ts and arrival_dt:
        first_dt = _parse_datetime(pharm_first_ts)
        if first_dt:
            delta = first_dt - arrival_dt
            delay_hours = round(delta.total_seconds() / 3600.0, 2)
            delay_flag_24h = delay_hours > 24.0
    else:
        # No confirmed chemical evidence
        if pharm_ambiguous or mech_orders_only or mech_evidence:
            excluded_reason = "NO_CHEMICAL_PROPHYLAXIS_EVIDENCE"
        elif not pharm_evidence:
            excluded_reason = "NO_CHEMICAL_PROPHYLAXIS_EVIDENCE"

    # ── Build output contract ───────────────────────────────────
    return {
        "pharm_first_ts": pharm_first_ts,
        "mech_first_ts": mech_first_ts,
        "first_ts": first_ts,   # deprecated — equals pharm_first_ts
        "delay_hours": delay_hours,
        "delay_flag_24h": delay_flag_24h,
        "excluded_reason": excluded_reason,
        "orders_only_count": len(mech_orders_only),
        "pharm_admin_evidence_count": len(pharm_evidence),
        "pharm_ambiguous_mention_count": len(pharm_ambiguous),
        "mech_admin_evidence_count": len(mech_evidence),
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
                {"ts": e["ts"], "raw_line_id": e["raw_line_id"],
                 "snippet": e["snippet"], "reason": e.get("reason", "")}
                for e in exclusion_evidence
            ],
        },
    }


# ── Internal matchers ───────────────────────────────────────────────

def _check_pharm_line(
    line: str,
    item_type: str,
    item_dt: Optional[str],
    source_id: str,
    raw_line_id: str,
    pharm_evidence: List[Dict[str, Any]],
    pharm_ambiguous: List[Dict[str, Any]],
    exclusion_evidence: List[Dict[str, Any]],
) -> None:
    """Check a single line for pharmacologic prophylaxis.

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

    # enoxaparin / lovenox / fondaparinux — always prophylactic when admin-confirmed
    if _is_enoxaparin_or_fondaparinux(line):
        classification = _classify_pharm_mention(line, item_type)
        if classification == "ADMIN_CONFIRMED":
            pharm_evidence.append(entry)
        else:
            pharm_ambiguous.append({**entry, "reason": "AMBIGUOUS_NON_ADMIN_MENTION"})
        return

    # heparin — requires context analysis + admin gating
    if re.search(r"\bheparin\b", line, re.IGNORECASE):
        is_prophy, exc_reason = _is_heparin_prophylaxis(line)
        if not is_prophy:
            # Non-prophylactic heparin (flush/drip/therapeutic dose)
            if exc_reason:
                exclusion_evidence.append({**entry, "reason": exc_reason})
            return
        # Prophylactic heparin — apply admin gating
        classification = _classify_pharm_mention(line, item_type)
        if classification == "ADMIN_CONFIRMED":
            pharm_evidence.append(entry)
        else:
            pharm_ambiguous.append({**entry, "reason": "AMBIGUOUS_NON_ADMIN_MENTION"})


def _check_pharm_given_inherited(
    line: str,
    item_has_enox: bool,
    item_has_heparin: bool,
    item_type: str,
    item_dt: Optional[str],
    source_id: str,
    raw_line_id: str,
    pharm_evidence: List[Dict[str, Any]],
    pharm_ambiguous: List[Dict[str, Any]],
    exclusion_evidence: List[Dict[str, Any]],
) -> None:
    """Process a 'Given :' tabular MAR line that inherits drug context.

    In structured MAR data, the drug name appears on a header line and
    individual admin rows (\"Given : dose : route ...\") lack the drug
    keyword.  This function catches those rows using item-level context.

    Only fires for lines that start with \"Given\" (case-insensitive)
    and explicitly skips \"Not Given\" / \"Patient Refused\" lines.
    """
    stripped = line.strip()

    # Must start with "Given" (tabular MAR admin status)
    if not re.match(r"^Given\b", stripped, re.IGNORECASE):
        return

    # Explicitly exclude "Not Given" lines
    if re.match(r"^Not\s+Given\b", stripped, re.IGNORECASE):
        return

    # Extract a precise timestamp from the tabular row.
    # Format: "Given : ... 12/18/25 0739 ..." or "Given ... 12/18/2025 0739"
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

    if item_has_enox:
        # Enoxaparin/fondaparinux — always prophylactic when administered
        pharm_evidence.append(entry)
        return

    if item_has_heparin:
        lower = stripped.lower()
        # Require subcutaneous route for heparin prophylaxis
        if not re.search(r"\bsubcutaneous\b|\bsubq\b|\bsq\b", lower):
            pharm_ambiguous.append({**entry, "reason": "AMBIGUOUS_NON_ADMIN_MENTION"})
            return
        # Check dose — > 5000 suggests therapeutic
        dose_match = _HEPARIN_HIGH_DOSE_PATTERN.search(stripped)
        if dose_match:
            try:
                dose_val = int(dose_match.group(1).replace(",", ""))
                if dose_val > 5000:
                    exclusion_evidence.append({**entry, "reason": "THERAPEUTIC_DOSE"})
                    return
            except ValueError:
                pass
        pharm_evidence.append(entry)


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
