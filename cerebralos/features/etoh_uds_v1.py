#!/usr/bin/env python3
"""
ETOH + UDS Extraction with Timestamp Validation v1 — Roadmap Step 5

Deterministic extraction of alcohol (ETOH) and urine drug screen (UDS)
results from structured lab data with timestamp validation.

Sources (priority order):
  1. Structured LAB items — tab-delimited / tabular lab results already
     parsed by labs_extract into the ``series`` dict.
  2. Raw LAB / ED_NOTE / PHYSICIAN_NOTE text — regex scan for
     ``Alcohol Serum``, ``DRUG SCREEN MEDICAL``, and UDS analyte lines
     not captured by structured extraction.

Timestamp validation rules:
  - Each result timestamp must be ≥ arrival_datetime (if known).
  - Each result timestamp must be ≤ discharge_datetime (if known).
  - If timestamp is missing, mark the result as
    ``ts_validation = "MISSING_TS"`` and keep the value but flag it.
  - If timestamp is out-of-window, mark result as
    ``ts_validation = "OUT_OF_WINDOW"`` with a descriptive warning.
  - Valid timestamps are marked ``ts_validation = "VALID"``.
  - Fail-closed: we never infer or fabricate a timestamp.

Output key: ``etoh_uds_v1`` (under top-level ``features`` dict)

Output schema::

    {
      "etoh_value": <float | str | null>,
      "etoh_value_raw": "<raw string>" | null,
      "etoh_ts": "<ISO datetime>" | null,
      "etoh_ts_validation": "VALID" | "MISSING_TS" | "OUT_OF_WINDOW" | null,
      "etoh_unit": "MG/DL" | null,
      "etoh_source_rule_id": "lab_series_alcohol_serum"
                            | "raw_text_alcohol_serum"
                            | null,
      "etoh_raw_line_id": "<sha256 evidence coordinate>" | null,

      "uds_performed": "yes" | "no" | "DATA NOT AVAILABLE",
      "uds_panel": {
          "thc": "POSITIVE" | "NEGATIVE" | null,
          "cocaine": "POSITIVE" | "NEGATIVE" | null,
          "opiates": "POSITIVE" | "NEGATIVE" | null,
          "benzodiazepines": "POSITIVE" | "NEGATIVE" | null,
          "barbiturates": "POSITIVE" | "NEGATIVE" | null,
          "amphetamines": "POSITIVE" | "NEGATIVE" | null,
          "phencyclidine": "POSITIVE" | "NEGATIVE" | null,
      } | null,
      "uds_ts": "<ISO datetime>" | null,
      "uds_ts_validation": "VALID" | "MISSING_TS" | "OUT_OF_WINDOW" | null,
      "uds_source_rule_id": "lab_series_uds_panel"
                           | "raw_text_drug_screen"
                           | null,
      "uds_raw_line_id": "<sha256 evidence coordinate>" | null,

      "evidence": [ { "raw_line_id": ..., "source": ..., "ts": ..., "snippet": ... }, ... ],
      "notes": [ ... ],
      "warnings": [ ... ]
    }

Design:
- Deterministic, fail-closed.
- No LLM, no ML, no clinical inference.
- No invented timestamps.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

_DNA = "DATA NOT AVAILABLE"

# ── UDS analyte component name mapping ──────────────────────────────
# Maps from various raw component names to canonical panel keys.
_UDS_COMPONENT_MAP: Dict[str, str] = {
    "thc": "thc",
    "cannabinoid": "thc",
    "marijuana": "thc",
    "cocaine metabolites urine": "cocaine",
    "cocaine metabolites": "cocaine",
    "cocaine": "cocaine",
    "opiate screen, urine": "opiates",
    "opiate screen urine": "opiates",
    "opiates": "opiates",
    "opiate": "opiates",
    "benzodiazepine screen, urine": "benzodiazepines",
    "benzodiazepine screen urine": "benzodiazepines",
    "benzodiazepines": "benzodiazepines",
    "benzodiazepine": "benzodiazepines",
    "barbiturate screen, urine": "barbiturates",
    "barbiturate screen urine": "barbiturates",
    "barbiturates": "barbiturates",
    "barbiturate": "barbiturates",
    "amphetamine/methamph screen, urine": "amphetamines",
    "amphetamine/methamph screen urine": "amphetamines",
    "amphetamines": "amphetamines",
    "amphetamine": "amphetamines",
    "phencyclidine screen urine": "phencyclidine",
    "phencyclidine screen, urine": "phencyclidine",
    "phencyclidine": "phencyclidine",
    "pcp": "phencyclidine",
}

# Alcohol Serum component patterns (case-insensitive).
_ETOH_COMPONENT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^Alcohol\s+Serum$", re.IGNORECASE),
    re.compile(r"^ETOH\b", re.IGNORECASE),
    re.compile(r"^Ethanol\b", re.IGNORECASE),
]

# UDS component patterns (case-insensitive) — matches any analyte.
_UDS_COMPONENT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^THC$", re.IGNORECASE),
    re.compile(r"^Cannabi", re.IGNORECASE),
    re.compile(r"^Marijuana$", re.IGNORECASE),
    re.compile(r"^Cocaine\s*Metabolit", re.IGNORECASE),
    re.compile(r"^Opiate\s*Screen", re.IGNORECASE),
    re.compile(r"^Benzodiazepine\s*Screen", re.IGNORECASE),
    re.compile(r"^Barbiturate\s*Screen", re.IGNORECASE),
    re.compile(r"^Amphetamine", re.IGNORECASE),
    re.compile(r"^Phencyclidine\s*Screen", re.IGNORECASE),
]

# Raw-text regex for ETOH line in lab blocks.
RE_ETOH_LINE = re.compile(
    r"(?:^|\n)\s*\u2022?\s*Alcohol\s+Serum\s+"
    r"(?P<date>\d{1,2}/\d{1,2}/\d{2,4})\s+"
    r"(?P<value>[<>]?\s*\d+(?:\.\d+)?)\s+"
    r"(?P<tail>.*?)$",
    re.IGNORECASE | re.MULTILINE,
)

# Raw-text regex for DRUG SCREEN section header.
RE_DRUG_SCREEN_HEADER = re.compile(
    r"DRUG\s+SCREEN\s+MEDICAL", re.IGNORECASE,
)

# Raw-text regex for individual UDS analyte lines (tabular).
RE_UDS_ANALYTE_LINE = re.compile(
    r"(?:^|\n)\s*\u2022?\s*"
    r"(?P<component>THC|Cocaine\s+Metabolites(?:\s+Urine)?|"
    r"Opiate\s+Screen[,]?\s*(?:Urine)?|"
    r"Benzodiazepine\s+Screen[,]?\s*(?:Urine)?|"
    r"Barbiturate\s+Screen[,]?\s*(?:Urine)?|"
    r"Amphetamine/Methamph\s+Screen[,]?\s*(?:Urine)?|"
    r"Phencyclidine\s+Screen\s*(?:Urine)?)"
    r"\s+(?:(?P<date>\d{1,2}/\d{1,2}/\d{2,4})\s+)?"
    r"(?P<value>POSITIVE|NEGATIVE)",
    re.IGNORECASE | re.MULTILINE,
)

# Narrative ETOH pattern (SBIRT notes): "BAL: <value>"
RE_NARRATIVE_BAL = re.compile(
    r"BAL\s*:\s*(?P<value>[<>]?\s*\d+(?:\.\d+)?|\w+)",
    re.IGNORECASE,
)

# Narrative UDS pattern (SBIRT notes): "UDS: <summary>"
RE_NARRATIVE_UDS = re.compile(
    r"UDS\s*:\s*(?P<value>\S+.*?)$",
    re.IGNORECASE | re.MULTILINE,
)


# ── Helpers ─────────────────────────────────────────────────────────

def _make_raw_line_id(
    source_type: str,
    source_id: Optional[str],
    line_text: str,
) -> str:
    """Build a deterministic raw_line_id from evidence coordinates."""
    payload = f"{source_type}|{source_id or ''}|{line_text.strip()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _is_etoh_component(comp: str) -> bool:
    """Return True if comp matches an ETOH component name."""
    for pat in _ETOH_COMPONENT_PATTERNS:
        if pat.search(comp):
            return True
    return False


def _is_uds_component(comp: str) -> bool:
    """Return True if comp matches a UDS analyte component name."""
    for pat in _UDS_COMPONENT_PATTERNS:
        if pat.search(comp):
            return True
    return False


def _canonical_uds_key(comp: str) -> Optional[str]:
    """Map a raw component name to a canonical UDS panel key."""
    comp_lower = comp.strip().lower()
    if comp_lower in _UDS_COMPONENT_MAP:
        return _UDS_COMPONENT_MAP[comp_lower]
    # Fuzzy match via patterns
    for pat in _UDS_COMPONENT_PATTERNS:
        if pat.search(comp):
            # Find the first matching key in our map
            for raw_key, canonical in _UDS_COMPONENT_MAP.items():
                if pat.search(raw_key) or pat.search(comp):
                    return canonical
    return None


def _parse_etoh_value(raw: str) -> Tuple[Optional[float], str]:
    """
    Parse an ETOH value string.

    Returns (numeric_value, raw_string).
    Handles qualifiers like ``<10`` → 10.0 (with qualifier preserved in raw).
    """
    cleaned = raw.strip()
    # Remove qualifier symbols but keep raw
    numeric_str = cleaned.replace("<", "").replace(">", "").strip()
    try:
        return float(numeric_str), cleaned
    except (ValueError, TypeError):
        return None, cleaned


def _parse_datetime_lenient(dt_str: Optional[str]) -> Optional[datetime]:
    """Parse a datetime string leniently, returning None on failure."""
    if not dt_str:
        return None
    dt_str = dt_str.strip()
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


def _validate_timestamp(
    ts_str: Optional[str],
    arrival_dt: Optional[datetime],
    discharge_dt: Optional[datetime],
) -> Tuple[str, Optional[str]]:
    """
    Validate a result timestamp against admission window.

    Returns (validation_status, warning_or_none).

    validation_status:
      - "VALID" — timestamp within window
      - "MISSING_TS" — no timestamp provided
      - "OUT_OF_WINDOW" — timestamp outside admission window
    """
    if not ts_str:
        return "MISSING_TS", "timestamp missing; fail-closed (no inference)"

    parsed = _parse_datetime_lenient(ts_str)
    if parsed is None:
        return "MISSING_TS", f"timestamp '{ts_str}' could not be parsed"

    # Check lower bound (arrival)
    if arrival_dt and parsed < arrival_dt:
        return (
            "OUT_OF_WINDOW",
            f"timestamp {ts_str} is before arrival {arrival_dt.isoformat()}",
        )

    # Check upper bound (discharge)
    if discharge_dt and parsed > discharge_dt:
        return (
            "OUT_OF_WINDOW",
            f"timestamp {ts_str} is after discharge {discharge_dt.isoformat()}",
        )

    return "VALID", None


def _empty_panel() -> Dict[str, Optional[str]]:
    """Return a UDS panel with all analytes None."""
    return {
        "thc": None,
        "cocaine": None,
        "opiates": None,
        "benzodiazepines": None,
        "barbiturates": None,
        "amphetamines": None,
        "phencyclidine": None,
    }


# ── ETOH extraction from structured labs ────────────────────────────

def _extract_etoh_from_series(
    feat_days: Dict[str, Any],
    arrival_dt: Optional[datetime],
    discharge_dt: Optional[datetime],
) -> Optional[Dict[str, Any]]:
    """
    Extract ETOH from pre-extracted lab series data.

    Returns the first (chronologically earliest) Alcohol Serum result
    with timestamp validation applied.
    """
    candidates: List[Dict[str, Any]] = []

    for day_iso in sorted(feat_days.keys()):
        day_block = feat_days[day_iso]
        labs = day_block.get("labs", {})
        series = labs.get("series", {})

        for comp_name, obs_list in series.items():
            if not _is_etoh_component(comp_name):
                continue

            for obs in obs_list:
                obs_dt = obs.get("observed_dt") or obs.get("dt")
                value_num = obs.get("value_num")
                value_raw = str(obs.get("value_raw", ""))

                if value_num is None and value_raw:
                    value_num, _ = _parse_etoh_value(value_raw)

                raw_line_id = obs.get("raw_line_id")
                if not raw_line_id:
                    raw_line_id = _make_raw_line_id(
                        "lab_series", obs_dt or day_iso, value_raw[:80],
                    )

                ts_validation, ts_warning = _validate_timestamp(
                    obs_dt, arrival_dt, discharge_dt,
                )

                candidates.append({
                    "etoh_value": round(value_num, 2) if value_num is not None else value_raw or None,
                    "etoh_value_raw": value_raw or None,
                    "etoh_ts": obs_dt,
                    "etoh_ts_validation": ts_validation,
                    "etoh_unit": "MG/DL",
                    "etoh_source_rule_id": "lab_series_alcohol_serum",
                    "etoh_raw_line_id": raw_line_id,
                    "ts_warning": ts_warning,
                })

    if not candidates:
        return None

    # Sort by timestamp (earliest first), prefer VALID timestamps
    candidates.sort(key=lambda c: (
        0 if c["etoh_ts_validation"] == "VALID" else 1,
        c["etoh_ts"] or "",
    ))
    return candidates[0]


# ── UDS extraction from structured labs ─────────────────────────────

def _extract_uds_from_series(
    feat_days: Dict[str, Any],
    arrival_dt: Optional[datetime],
    discharge_dt: Optional[datetime],
) -> Optional[Dict[str, Any]]:
    """
    Extract UDS panel from pre-extracted lab series data.

    Collects all UDS analytes from the earliest day with UDS data.
    """
    # Find earliest day with any UDS component in series
    panel = _empty_panel()
    panel_ts: Optional[str] = None
    panel_day: Optional[str] = None
    panel_raw_line_id: Optional[str] = None
    found_any = False

    for day_iso in sorted(feat_days.keys()):
        day_block = feat_days[day_iso]
        labs = day_block.get("labs", {})
        series = labs.get("series", {})

        for comp_name, obs_list in series.items():
            if not _is_uds_component(comp_name):
                continue

            canonical_key = _canonical_uds_key(comp_name)
            if canonical_key is None:
                continue

            for obs in obs_list:
                obs_dt = obs.get("observed_dt") or obs.get("dt")
                value_raw = str(obs.get("value_raw", "")).strip().upper()

                if value_raw in ("POSITIVE", "NEGATIVE"):
                    panel[canonical_key] = value_raw
                    if panel_ts is None:
                        panel_ts = obs_dt
                        panel_day = day_iso
                    if not panel_raw_line_id:
                        raw_line_id = obs.get("raw_line_id")
                        if not raw_line_id:
                            raw_line_id = _make_raw_line_id(
                                "lab_series_uds", obs_dt or day_iso, comp_name,
                            )
                        panel_raw_line_id = raw_line_id
                    found_any = True

        if found_any:
            break  # Use earliest day only

    if not found_any:
        return None

    ts_validation, ts_warning = _validate_timestamp(
        panel_ts, arrival_dt, discharge_dt,
    )

    return {
        "uds_performed": "yes",
        "uds_panel": panel,
        "uds_ts": panel_ts,
        "uds_ts_validation": ts_validation,
        "uds_source_rule_id": "lab_series_uds_panel",
        "uds_raw_line_id": panel_raw_line_id,
        "ts_warning": ts_warning,
    }


# ── Raw-text extraction fallback ───────────────────────────────────

def _extract_etoh_from_raw_text(
    days_data: Dict[str, Any],
    arrival_dt: Optional[datetime],
    discharge_dt: Optional[datetime],
) -> Optional[Dict[str, Any]]:
    """
    Fallback: scan raw timeline text for Alcohol Serum results.

    Used when structured lab extraction doesn't find ETOH.
    """
    days_map = days_data.get("days") or {}

    for day_iso in sorted(days_map.keys()):
        items = days_map[day_iso].get("items") or []
        for item in items:
            item_type = item.get("type") or ""
            if item_type not in ("LAB", "ED_NOTE", "PHYSICIAN_NOTE"):
                continue

            text = (item.get("payload") or {}).get("text", "")
            if not text:
                continue

            m = RE_ETOH_LINE.search(text)
            if not m:
                continue

            value_str = m.group("value")
            value_num, value_raw = _parse_etoh_value(value_str)

            item_dt = item.get("dt")
            raw_line_id = _make_raw_line_id(
                item_type, item.get("source_id"), m.group(0).strip()[:80],
            )

            ts_validation, ts_warning = _validate_timestamp(
                item_dt, arrival_dt, discharge_dt,
            )

            return {
                "etoh_value": round(value_num, 2) if value_num is not None else value_raw,
                "etoh_value_raw": value_raw,
                "etoh_ts": item_dt,
                "etoh_ts_validation": ts_validation,
                "etoh_unit": "MG/DL",
                "etoh_source_rule_id": "raw_text_alcohol_serum",
                "etoh_raw_line_id": raw_line_id,
                "ts_warning": ts_warning,
            }

    return None


def _extract_uds_from_raw_text(
    days_data: Dict[str, Any],
    arrival_dt: Optional[datetime],
    discharge_dt: Optional[datetime],
) -> Optional[Dict[str, Any]]:
    """
    Fallback: scan raw timeline text for DRUG SCREEN MEDICAL sections.

    Parses individual analyte results from the text block.
    """
    days_map = days_data.get("days") or {}

    for day_iso in sorted(days_map.keys()):
        items = days_map[day_iso].get("items") or []
        for item in items:
            item_type = item.get("type") or ""
            if item_type not in ("LAB", "ED_NOTE", "PHYSICIAN_NOTE"):
                continue

            text = (item.get("payload") or {}).get("text", "")
            if not text:
                continue

            # Look for DRUG SCREEN MEDICAL header
            if not RE_DRUG_SCREEN_HEADER.search(text):
                continue

            # Found a drug screen section — parse analytes
            panel = _empty_panel()
            found_any = False

            for am in RE_UDS_ANALYTE_LINE.finditer(text):
                comp = am.group("component").strip()
                value = am.group("value").strip().upper()
                canonical_key = _canonical_uds_key(comp)
                if canonical_key and value in ("POSITIVE", "NEGATIVE"):
                    panel[canonical_key] = value
                    found_any = True

            if not found_any:
                continue

            item_dt = item.get("dt")
            raw_line_id = _make_raw_line_id(
                item_type, item.get("source_id"),
                "DRUG SCREEN MEDICAL",
            )

            ts_validation, ts_warning = _validate_timestamp(
                item_dt, arrival_dt, discharge_dt,
            )

            return {
                "uds_performed": "yes",
                "uds_panel": panel,
                "uds_ts": item_dt,
                "uds_ts_validation": ts_validation,
                "uds_source_rule_id": "raw_text_drug_screen",
                "uds_raw_line_id": raw_line_id,
                "ts_warning": ts_warning,
            }

    return None


# ── Empty result ────────────────────────────────────────────────────

def _empty_etoh() -> Dict[str, Any]:
    """Return a fail-closed empty ETOH result."""
    return {
        "etoh_value": None,
        "etoh_value_raw": None,
        "etoh_ts": None,
        "etoh_ts_validation": None,
        "etoh_unit": None,
        "etoh_source_rule_id": None,
        "etoh_raw_line_id": None,
    }


def _empty_uds() -> Dict[str, Any]:
    """Return a fail-closed empty UDS result."""
    return {
        "uds_performed": _DNA,
        "uds_panel": None,
        "uds_ts": None,
        "uds_ts_validation": None,
        "uds_source_rule_id": None,
        "uds_raw_line_id": None,
    }


# ── Public API ──────────────────────────────────────────────────────

def extract_etoh_uds(
    pat_features: Dict[str, Any],
    days_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Extract ETOH and UDS results with timestamp validation.

    Parameters
    ----------
    pat_features : dict
        ``{"days": {day_iso: {feature_key: ...}}}`` — the per-day
        features assembled so far (includes labs.series).
    days_data : dict
        Full ``patient_days_v1.json`` content (raw timeline).

    Returns
    -------
    dict
        Combined ETOH + UDS result dict (see module docstring for schema).
    """
    meta = days_data.get("meta") or {}
    feat_days = pat_features.get("days") or {}

    # Parse arrival/discharge datetimes
    arrival_dt = _parse_datetime_lenient(meta.get("arrival_datetime"))
    discharge_dt = _parse_datetime_lenient(meta.get("discharge_datetime"))

    evidence: List[Dict[str, Any]] = []
    notes: List[str] = []
    warnings: List[str] = []

    # ── ETOH extraction ─────────────────────────────────────────
    etoh_result = _extract_etoh_from_series(feat_days, arrival_dt, discharge_dt)
    if etoh_result is None:
        etoh_result = _extract_etoh_from_raw_text(days_data, arrival_dt, discharge_dt)
    if etoh_result is None:
        etoh_result = _empty_etoh()
        notes.append("DATA NOT AVAILABLE: no ETOH/Alcohol Serum values found")

    # Collect ETOH warnings
    etoh_ts_warning = etoh_result.pop("ts_warning", None)
    if etoh_ts_warning:
        warnings.append(f"etoh_ts: {etoh_ts_warning}")

    # Build ETOH evidence entry
    if etoh_result.get("etoh_raw_line_id"):
        evidence.append({
            "raw_line_id": etoh_result["etoh_raw_line_id"],
            "source": etoh_result.get("etoh_source_rule_id"),
            "ts": etoh_result.get("etoh_ts"),
            "snippet": f"Alcohol Serum: {etoh_result.get('etoh_value_raw', '')}",
        })

    # ── UDS extraction ──────────────────────────────────────────
    uds_result = _extract_uds_from_series(feat_days, arrival_dt, discharge_dt)
    if uds_result is None:
        uds_result = _extract_uds_from_raw_text(days_data, arrival_dt, discharge_dt)
    if uds_result is None:
        uds_result = _empty_uds()
        notes.append("DATA NOT AVAILABLE: no UDS/Drug Screen panel found")

    # Collect UDS warnings
    uds_ts_warning = uds_result.pop("ts_warning", None)
    if uds_ts_warning:
        warnings.append(f"uds_ts: {uds_ts_warning}")

    # Build UDS evidence entry
    if uds_result.get("uds_raw_line_id"):
        panel_summary = ""
        if uds_result.get("uds_panel"):
            pos_keys = [
                k for k, v in uds_result["uds_panel"].items()
                if v == "POSITIVE"
            ]
            panel_summary = f" positive=[{', '.join(pos_keys)}]" if pos_keys else " all negative"
        evidence.append({
            "raw_line_id": uds_result["uds_raw_line_id"],
            "source": uds_result.get("uds_source_rule_id"),
            "ts": uds_result.get("uds_ts"),
            "snippet": f"Drug Screen{panel_summary}",
        })

    # ── Assemble output ─────────────────────────────────────────
    return {
        # ETOH fields
        "etoh_value": etoh_result.get("etoh_value"),
        "etoh_value_raw": etoh_result.get("etoh_value_raw"),
        "etoh_ts": etoh_result.get("etoh_ts"),
        "etoh_ts_validation": etoh_result.get("etoh_ts_validation"),
        "etoh_unit": etoh_result.get("etoh_unit"),
        "etoh_source_rule_id": etoh_result.get("etoh_source_rule_id"),
        "etoh_raw_line_id": etoh_result.get("etoh_raw_line_id"),
        # UDS fields
        "uds_performed": uds_result.get("uds_performed"),
        "uds_panel": uds_result.get("uds_panel"),
        "uds_ts": uds_result.get("uds_ts"),
        "uds_ts_validation": uds_result.get("uds_ts_validation"),
        "uds_source_rule_id": uds_result.get("uds_source_rule_id"),
        "uds_raw_line_id": uds_result.get("uds_raw_line_id"),
        # Traceability
        "evidence": evidence,
        "notes": notes,
        "warnings": warnings,
    }
