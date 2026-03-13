#!/usr/bin/env python3
"""
Transfusion & Blood Product Extraction v1 — Protocol Slice B

Deterministic extraction of blood product transfusions and TXA
administration from raw patient text.

Products extracted:
  - pRBC  (packed red blood cells / red blood cells)
  - FFP   (fresh frozen plasma)
  - Platelets (platelet pheresis / apheresis platelets)
  - Cryoprecipitate
  - TXA   (tranexamic acid)
  - MTP   (massive transfusion protocol activation)

Sources:
  - Order headers:  TRANSFUSE RED BLOOD CELLS (Order NNN)
  - Order lines:    Transfuse RBC , N Units [NUR619]
  - Summary tables: Transfuse RBC   12/22   1015   1 more
  - Operative notes: TXA: 1 g was administered ...
  - Medication orders: tranexamic acid-NaCl IV premix ...
  - Med admin lines:   tranexamic acid 1 gram bolus  1,000 mg

Negative exclusions (deterministic reject):
  - Platelet Count / Mean Platelet Volume  (lab result, not product)
  - Transfusion Status  OK TO TRANSFUSE    (type-and-screen result)
  - "without blood product"                (radiology negation)
  - "Blood transfusion without reported diagnosis" (billing code)
  - "If platelets less than"               (med instruction)

Output key: transfusion_blood_products_v1 (under features dict)

Design:
  - Deterministic, fail-closed.
  - No LLM, no ML, no clinical inference.
  - Every evidence item carries raw_line_id (SHA-256[:16]).
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional


# ── raw_line_id generation ──────────────────────────────────────────

def _make_raw_line_id(
    product: str,
    day: str,
    line_num: Any,
    snippet: str,
) -> str:
    """Deterministic raw_line_id — SHA-256[:16] of extraction coordinates.

    Includes day + line_num so identical text at different positions
    yields distinct IDs (per-occurrence preservation, not content dedup).
    """
    key = f"{product}|{day}|{line_num}|{snippet}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


# ── Regex patterns ──────────────────────────────────────────────────

# --- Positive patterns ---

# Order header:  TRANSFUSE RED BLOOD CELLS (Order 464694986)
_RE_RBC_ORDER = re.compile(
    r"TRANSFUSE\s+RED\s+BLOOD\s+CELLS?\s*\(Order\s+\d+\)",
    re.IGNORECASE,
)

# Order line:  Transfuse RBC , 1 Units [NUR619] (Order 464666348)
_RE_RBC_ORDER_LINE = re.compile(
    r"Transfuse\s+RBC\s*,?\s*(\d+)\s+Units?",
    re.IGNORECASE,
)

# Summary table: Transfuse RBC   12/22   1015    1 more
_RE_RBC_SUMMARY = re.compile(
    r"Transfuse\s+RBC\s+\d{2}/\d{2}\s+\d{4}",
    re.IGNORECASE,
)

# Bare "Transfuse RBC" in transfusion information block
_RE_RBC_INFO = re.compile(
    r"^\s+Transfuse\s+RBC\s*$",
    re.IGNORECASE,
)

# FFP order header: TRANSFUSE FRESH FROZEN PLASMA
_RE_FFP_ORDER = re.compile(
    r"TRANSFUSE\s+FRESH\s+FROZEN\s+PLASMA",
    re.IGNORECASE,
)

# FFP order line: Transfuse fresh frozen plasma , 1 Units
_RE_FFP_ORDER_LINE = re.compile(
    r"Transfuse\s+fresh\s+frozen\s+plasma\s*,?\s*(\d+)\s+Units?",
    re.IGNORECASE,
)

# Platelet order header: TRANSFUSE PLATELET PHERESIS
_RE_PLATELET_ORDER = re.compile(
    r"TRANSFUSE\s+PLATELET\s+PHERESIS",
    re.IGNORECASE,
)

# Platelet order/summary line: Transfuse platelet pheresis
_RE_PLATELET_LINE = re.compile(
    r"Transfuse\s+platelet\s+pheresis",
    re.IGNORECASE,
)

# Cryoprecipitate: TRANSFUSE CRYOPRECIPITATE or Transfuse cryo
_RE_CRYO_ORDER = re.compile(
    r"(?:TRANSFUSE|Transfuse)\s+(?:CRYOPRECIPITATE|cryoprecipitate|cryo)",
    re.IGNORECASE,
)

# TXA in operative note: TXA: 1 g was administered
_RE_TXA_OPNOTE = re.compile(
    r"TXA:\s*[\d.]+\s*g\b",
    re.IGNORECASE,
)

# TXA medication order or admin: tranexamic acid
_RE_TXA_MED = re.compile(
    r"tranexamic\s+acid",
    re.IGNORECASE,
)

# MTP activation: massive transfusion protocol / MTP activated
_RE_MTP = re.compile(
    r"(?:massive\s+transfusion\s+protocol|MTP\s+activat)",
    re.IGNORECASE,
)


# --- Negative / exclusion patterns ---

# "Platelet Count" or "Mean Platelet Volume" — lab, not product
_RE_PLATELET_LAB = re.compile(
    r"(?:Platelet\s+Count|Mean\s+Platelet\s+Volume)",
    re.IGNORECASE,
)

# "Transfusion Status" — type-and-screen, not actual transfusion
_RE_TRANSFUSION_STATUS = re.compile(
    r"Transfusion\s+Status",
    re.IGNORECASE,
)

# "without blood product" — radiology negative
_RE_WITHOUT_BLOOD_PRODUCT = re.compile(
    r"without\s+blood\s+product",
    re.IGNORECASE,
)

# "Blood transfusion without reported diagnosis" — billing note
_RE_BILLING_TRANSFUSION = re.compile(
    r"Blood\s+transfusion\s+without\s+reported",
    re.IGNORECASE,
)

# "If platelets less than" — medication instruction
_RE_PLATELET_INSTRUCTION = re.compile(
    r"If\s+platelets?\s+(?:less\s+than|are\s+less|<)",
    re.IGNORECASE,
)

# OK TO TRANSFUSE — lab result, not actual product
_RE_OK_TO_TRANSFUSE = re.compile(
    r"OK\s+TO\s+TRANSFUSE",
    re.IGNORECASE,
)

# "Transfuse for hemoglobin below 7" — threshold instruction, not event
_RE_TRANSFUSE_THRESHOLD = re.compile(
    r"Transfuse\s+for\s+",
    re.IGNORECASE,
)

# "PREPARE PLATELET PHERESIS" — lab preparation order, not transfusion
_RE_PREPARE_BLOOD = re.compile(
    r"PREPARE\s+(?:PLATELET|RBC|FFP|CRYO)",
    re.IGNORECASE,
)


def _is_excluded(line: str) -> bool:
    """Return True if line matches a known false-positive pattern."""
    return bool(
        _RE_PLATELET_LAB.search(line)
        or _RE_TRANSFUSION_STATUS.search(line)
        or _RE_WITHOUT_BLOOD_PRODUCT.search(line)
        or _RE_BILLING_TRANSFUSION.search(line)
        or _RE_PLATELET_INSTRUCTION.search(line)
        or _RE_OK_TO_TRANSFUSE.search(line)
        or _RE_TRANSFUSE_THRESHOLD.search(line)
        or _RE_PREPARE_BLOOD.search(line)
    )


# ── product classification ─────────────────────────────────────────

def _classify_line(line: str) -> Optional[str]:
    """
    Classify a line as a blood product event.

    Returns product type string or None if not a match.
    Product types: 'prbc', 'ffp', 'platelets', 'cryo', 'txa', 'mtp'
    """
    # Check exclusions first (fail-closed)
    if _is_excluded(line):
        return None

    # MTP (check before individual products)
    if _RE_MTP.search(line):
        return "mtp"

    # pRBC
    if (_RE_RBC_ORDER.search(line)
            or _RE_RBC_ORDER_LINE.search(line)
            or _RE_RBC_SUMMARY.search(line)
            or _RE_RBC_INFO.search(line)):
        return "prbc"

    # FFP
    if _RE_FFP_ORDER.search(line) or _RE_FFP_ORDER_LINE.search(line):
        return "ffp"

    # Platelets
    if _RE_PLATELET_ORDER.search(line) or _RE_PLATELET_LINE.search(line):
        return "platelets"

    # Cryoprecipitate
    if _RE_CRYO_ORDER.search(line):
        return "cryo"

    # TXA
    if _RE_TXA_OPNOTE.search(line) or _RE_TXA_MED.search(line):
        return "txa"

    return None


# ── units extraction ───────────────────────────────────────────────

def _extract_units(line: str, product: str) -> Optional[int]:
    """
    Extract unit count from a transfusion order line.

    Returns integer unit count or None if not deterministically
    extractable.
    """
    m = _RE_RBC_ORDER_LINE.search(line)
    if m:
        return int(m.group(1))
    m = _RE_FFP_ORDER_LINE.search(line)
    if m:
        return int(m.group(1))
    return None


# ── main extraction entry point ────────────────────────────────────

def extract_transfusion_blood_products(
    pat_features: Dict[str, Any],
    days_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Extract transfusion/blood product events from raw patient text.

    Parameters
    ----------
    pat_features : dict
        Accepted for API consistency with other feature
        extractors; not consumed by this module.
    days_data : dict, optional
        Full days_json with raw text lines under
        days_data["days"][date]["raw_lines"].

    Returns
    -------
    dict
        Transfusion summary with evidence list,
        per-product counts, and MTP/TXA flags.
    """
    events: List[Dict[str, Any]] = []
    seen_hashes: set = set()

    if days_data is None:
        return _empty_result()

    raw_days = days_data.get("days", {})
    if not isinstance(raw_days, dict):
        return _empty_result()

    for day_iso, day_obj in sorted(raw_days.items()):
        if not isinstance(day_obj, dict):
            continue
        raw_lines = day_obj.get("raw_lines", [])
        if not isinstance(raw_lines, list):
            continue

        for line_idx, raw_line in enumerate(raw_lines):
            if not isinstance(raw_line, str):
                continue

            product = _classify_line(raw_line)
            if product is None:
                continue

            # Per-occurrence dedup: day + line_idx + full text in hash,
            # so identical content at different positions → distinct events.
            raw_line_id = _make_raw_line_id(
                product, day_iso, line_idx, raw_line.strip(),
            )

            if raw_line_id in seen_hashes:
                continue
            seen_hashes.add(raw_line_id)

            units = _extract_units(raw_line, product)

            event: Dict[str, Any] = {
                "product": product,
                "day": day_iso,
                "line_index": line_idx,
                "snippet": raw_line.strip()[:200],
                "raw_line_id": raw_line_id,
            }
            if units is not None:
                event["units"] = units

            events.append(event)

    return _build_result(events)


def _empty_result() -> Dict[str, Any]:
    """Return fail-closed empty result."""
    return {
        "status": "DATA NOT AVAILABLE",
        "products_detected": [],
        "mtp_activated": False,
        "txa_administered": False,
        "prbc_events": 0,
        "ffp_events": 0,
        "platelet_events": 0,
        "cryo_events": 0,
        "total_events": 0,
        "evidence": [],
    }


def _build_result(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Assemble structured result from classified events."""
    if not events:
        return _empty_result()

    products_detected = sorted(set(e["product"] for e in events))
    prbc_count = sum(1 for e in events if e["product"] == "prbc")
    ffp_count = sum(1 for e in events if e["product"] == "ffp")
    platelet_count = sum(1 for e in events if e["product"] == "platelets")
    cryo_count = sum(1 for e in events if e["product"] == "cryo")
    mtp = any(e["product"] == "mtp" for e in events)
    txa = any(e["product"] == "txa" for e in events)

    return {
        "status": "available",
        "products_detected": products_detected,
        "mtp_activated": mtp,
        "txa_administered": txa,
        "prbc_events": prbc_count,
        "ffp_events": ffp_count,
        "platelet_events": platelet_count,
        "cryo_events": cryo_count,
        "total_events": len(events),
        "evidence": events,
    }
