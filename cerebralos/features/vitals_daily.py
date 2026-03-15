#!/usr/bin/env python3
"""
Per-day vitals extraction for CerebralOS features.

Extracts temp_f, hr, rr, spo2, sbp, dbp, map from:
  - Nursing flowsheet tables (highest priority)
  - ED Triage Vitals blocks
  - Visit Vitals blocks
  - Inline narrative vitals strings
  - Discharge/summary inline vitals
  - Tabular note-internal vitals (fallback — horizontal, vertical, vital-signs block)

Output per day::

    vitals: {
      temp_f: {min, max, last, last_dt, sources[]},
      hr:     {min, max, last, last_dt, sources[]},
      rr:     {min, max, last, last_dt, sources[]},
      spo2:   {min, max, last, last_dt, sources[]},
      sbp:    {min, max, last, last_dt, sources[]},
      dbp:    {min, max, last, last_dt, sources[]},
      map:    {min, max, last, last_dt, sources[]},
      warnings: [...]
    }

Design:
- Deterministic, fail-closed.  Config-driven patterns.
- Flowsheet-table rows preferred when present.
- last = latest timestamped value in that day.
- No LLM, no ML, no clinical inference.
"""

from __future__ import annotations

import re
from datetime import datetime as _dt
from typing import Any, Dict, List, Optional, Tuple

# ── metric keys in canonical order ──────────────────────────────────
METRIC_KEYS = ("temp_f", "hr", "rr", "spo2", "sbp", "dbp", "map")

# ── internal reading type ───────────────────────────────────────────
_VitalReading = Dict[str, Any]  # {metric, value, dt, source_type, source_id, line_preview, time_missing, abnormal}

# ── abnormal thresholds (clinical) ──────────────────────────────────
# Canonical thresholds — importable by QA / regression scripts.
ABNORMAL_THRESHOLDS: Dict[str, Dict[str, float]] = {
    "sbp":    {"low": 90},
    "map":    {"low": 65},
    "hr":     {"low": 50, "high": 120},
    "rr":     {"low": 10, "high": 24},
    "spo2":   {"low": 92},
    "temp_f": {"low": 96.0, "high": 100.4},   # <= 96.0 or >= 100.4
    "dbp":    {},  # no standalone threshold
}

# Keep private alias for internal callers (backward compat)
_ABNORMAL_THRESHOLDS = ABNORMAL_THRESHOLDS


def is_abnormal(metric: str, value: float) -> bool:
    """Check if a vital reading is outside normal clinical range.

    Public API — used by QA and regression scripts.
    """
    th = ABNORMAL_THRESHOLDS.get(metric)
    if not th:
        return False
    lo = th.get("low")
    hi = th.get("high")
    if lo is not None and value <= lo:  # <= for temp_f, < for others
        if metric == "temp_f":
            return value <= lo  # <= 96.0
        return value < lo
    if hi is not None and value >= hi:  # >= for temp_f, > for others
        if metric == "temp_f":
            return value >= hi  # >= 100.4
        return value > hi
    return False


# Keep private alias for internal callers (backward compat)
_is_abnormal = is_abnormal


# ── helpers ─────────────────────────────────────────────────────────

def _parse_dt_flowsheet(raw: str, day_iso: str) -> Optional[str]:
    """Parse '12/11/25 1216' → ISO string, or return None."""
    raw = raw.strip()
    for fmt in ("%m/%d/%y %H%M", "%m/%d/%Y %H%M"):
        try:
            dt = _dt.strptime(raw, fmt)
            return dt.strftime("%Y-%m-%dT%H:%M:%S")
        except ValueError:
            continue
    return None


def _parse_dt_triage_bracket(bracket: str) -> Optional[str]:
    """Parse '[12/09/25 1830]' → ISO string."""
    bracket = bracket.strip().strip("[]")
    return _parse_dt_flowsheet(bracket, "")


def _in_range(val: float, lo: float, hi: float) -> bool:
    return lo <= val <= hi


def _is_excluded_line(line: str, exclude_res: List["re.Pattern[str]"]) -> bool:
    for pat in exclude_res:
        if pat.search(line):
            return True
    return False


def _compute_map(sbp: float, dbp: float) -> float:
    """MAP = DBP + (SBP - DBP) / 3, rounded to 1 decimal."""
    return round(dbp + (sbp - dbp) / 3.0, 1)


def _source_entry(
    source_type: str,
    source_id: Any,
    preview: str,
    *,
    value: Any = None,
    dt: Optional[str] = None,
    abnormal: bool = False,
    time_missing: bool = False,
) -> Dict[str, Any]:
    return {
        "source_type": source_type,
        "source_id": source_id,
        "preview": preview[:200],
        "value": value,
        "dt": dt,
        "abnormal": abnormal,
        "time_missing": time_missing,
    }


# ═════════════════════════════════════════════════════════════════════
#  Parsers for each format
# ═════════════════════════════════════════════════════════════════════

def _parse_flowsheet_table(
    text: str,
    day_iso: str,
    config: Dict[str, Any],
    source_id: Any,
    guardrails: Dict[str, Dict[str, Any]],
) -> List[_VitalReading]:
    """Parse nursing flowsheet table rows."""
    readings: List[_VitalReading] = []
    ft_cfg = config.get("flowsheet_table", {})
    header_re = re.compile(ft_cfg.get("header_pattern", "^$"))
    lines = text.split("\n")

    in_table = False
    for line in lines:
        if header_re.search(line):
            in_table = True
            continue
        if in_table:
            # Table ends at blank line or non-table line
            if not line.strip() or not re.match(r"\d{1,2}/\d{1,2}/\d{2,4}\s+\d{4}\t", line):
                in_table = False
                continue

            parts = line.split("\t")
            if len(parts) < 6:
                continue

            dt_raw = parts[0].strip()
            dt_iso = _parse_dt_flowsheet(dt_raw, day_iso)
            if not dt_iso:
                continue
            # Only accept rows matching our target day
            if not dt_iso.startswith(day_iso):
                continue

            preview = line.strip()[:200]

            # Temp (col 1) — e.g. "98 °F (36.7 °C)" or "--"
            temp_raw = parts[1].strip()
            m_temp = re.search(r"([\d]+(?:\.\d+)?)\s*°?\s*F", temp_raw)
            if m_temp:
                val = float(m_temp.group(1))
                g = guardrails.get("temp_f", {})
                if _in_range(val, g.get("min", 85), g.get("max", 115)):
                    readings.append({
                        "metric": "temp_f", "value": val, "dt": dt_iso,
                        "source_type": "FLOWSHEET", "source_id": source_id,
                        "line_preview": preview,
                    })

            # Pulse (col 2) — e.g. "68" or "59 (Abnormal)"
            pulse_raw = parts[2].strip()
            m_pulse = re.match(r"(\d+)", pulse_raw)
            if m_pulse:
                val = float(m_pulse.group(1))
                g = guardrails.get("hr", {})
                if _in_range(val, g.get("min", 20), g.get("max", 300)):
                    readings.append({
                        "metric": "hr", "value": val, "dt": dt_iso,
                        "source_type": "FLOWSHEET", "source_id": source_id,
                        "line_preview": preview,
                    })

            # Resp (col 3)
            resp_raw = parts[3].strip()
            m_resp = re.match(r"(\d+)", resp_raw)
            if m_resp:
                val = float(m_resp.group(1))
                g = guardrails.get("rr", {})
                if _in_range(val, g.get("min", 4), g.get("max", 60)):
                    readings.append({
                        "metric": "rr", "value": val, "dt": dt_iso,
                        "source_type": "FLOWSHEET", "source_id": source_id,
                        "line_preview": preview,
                    })

            # BP (col 4) — e.g. "149/89 (Abnormal)" or "(!) 166/86"
            bp_raw = parts[4].strip()
            m_bp = re.search(r"(\d+)\s*/\s*(\d+)", bp_raw)
            if m_bp:
                sbp = float(m_bp.group(1))
                dbp = float(m_bp.group(2))
                g = guardrails.get("bp", {})
                if (_in_range(sbp, g.get("sbp_min", 40), g.get("sbp_max", 300)) and
                        _in_range(dbp, g.get("dbp_min", 20), g.get("dbp_max", 200))):
                    readings.append({
                        "metric": "sbp", "value": sbp, "dt": dt_iso,
                        "source_type": "FLOWSHEET", "source_id": source_id,
                        "line_preview": preview,
                    })
                    readings.append({
                        "metric": "dbp", "value": dbp, "dt": dt_iso,
                        "source_type": "FLOWSHEET", "source_id": source_id,
                        "line_preview": preview,
                    })
                    map_val = _compute_map(sbp, dbp)
                    readings.append({
                        "metric": "map", "value": map_val, "dt": dt_iso,
                        "source_type": "FLOWSHEET", "source_id": source_id,
                        "line_preview": preview,
                    })

            # SpO2 (col 5) — e.g. "97 %" or "97%"
            spo2_raw = parts[5].strip() if len(parts) > 5 else ""
            m_spo2 = re.match(r"(\d+(?:\.\d+)?)\s*%?", spo2_raw)
            if m_spo2:
                val = float(m_spo2.group(1))
                g = guardrails.get("spo2", {})
                if _in_range(val, g.get("min", 50), g.get("max", 100)):
                    readings.append({
                        "metric": "spo2", "value": val, "dt": dt_iso,
                        "source_type": "FLOWSHEET", "source_id": source_id,
                        "line_preview": preview,
                    })

    return readings


def _parse_ed_triage_block(
    text: str,
    day_iso: str,
    config: Dict[str, Any],
    source_id: Any,
    guardrails: Dict[str, Dict[str, Any]],
) -> List[_VitalReading]:
    """Parse ED Triage Vitals blocks."""
    readings: List[_VitalReading] = []
    et_cfg = config.get("ed_triage_table", {})
    header_re = re.compile(et_cfg.get("header_pattern", "(?!)"))
    col_hdr_re = re.compile(et_cfg.get("col_header_pattern", "(?!)"))
    lines = text.split("\n")

    i = 0
    while i < len(lines):
        hm = header_re.search(lines[i])
        if hm:
            bracket_dt = hm.group(1)
            dt_iso = _parse_dt_triage_bracket(bracket_dt)
            if dt_iso and dt_iso.startswith(day_iso):
                # Expect column header on next non-blank line, then data row
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if j < len(lines) and col_hdr_re.search(lines[j]):
                    # Data row follows
                    k = j + 1
                    while k < len(lines) and not lines[k].strip():
                        k += 1
                    if k < len(lines):
                        data_line = lines[k]
                        preview = data_line.strip()[:200]
                        parts = data_line.split("\t")
                        # Temp (col 0)
                        if len(parts) > 0:
                            m_t = re.search(r"([\d]+(?:\.\d+)?)\s*°?\s*F", parts[0])
                            if m_t:
                                val = float(m_t.group(1))
                                g = guardrails.get("temp_f", {})
                                if _in_range(val, g.get("min", 85), g.get("max", 115)):
                                    readings.append({
                                        "metric": "temp_f", "value": val, "dt": dt_iso,
                                        "source_type": "ED_TRIAGE", "source_id": source_id,
                                        "line_preview": preview,
                                    })
                        # col 1 = Temp src (skip)
                        # Pulse (col 2)
                        if len(parts) > 2:
                            m_p = re.match(r"(\d+)", parts[2].strip())
                            if m_p:
                                val = float(m_p.group(1))
                                g = guardrails.get("hr", {})
                                if _in_range(val, g.get("min", 20), g.get("max", 300)):
                                    readings.append({
                                        "metric": "hr", "value": val, "dt": dt_iso,
                                        "source_type": "ED_TRIAGE", "source_id": source_id,
                                        "line_preview": preview,
                                    })
                        # Resp (col 3)
                        if len(parts) > 3:
                            m_r = re.match(r"(\d+)", parts[3].strip())
                            if m_r:
                                val = float(m_r.group(1))
                                g = guardrails.get("rr", {})
                                if _in_range(val, g.get("min", 4), g.get("max", 60)):
                                    readings.append({
                                        "metric": "rr", "value": val, "dt": dt_iso,
                                        "source_type": "ED_TRIAGE", "source_id": source_id,
                                        "line_preview": preview,
                                    })
                        # BP (col 4)
                        if len(parts) > 4:
                            m_bp = re.search(r"(\d+)\s*/\s*(\d+)", parts[4])
                            if m_bp:
                                sbp = float(m_bp.group(1))
                                dbp = float(m_bp.group(2))
                                g = guardrails.get("bp", {})
                                if (_in_range(sbp, g.get("sbp_min", 40), g.get("sbp_max", 300)) and
                                        _in_range(dbp, g.get("dbp_min", 20), g.get("dbp_max", 200))):
                                    readings.append({
                                        "metric": "sbp", "value": sbp, "dt": dt_iso,
                                        "source_type": "ED_TRIAGE", "source_id": source_id,
                                        "line_preview": preview,
                                    })
                                    readings.append({
                                        "metric": "dbp", "value": dbp, "dt": dt_iso,
                                        "source_type": "ED_TRIAGE", "source_id": source_id,
                                        "line_preview": preview,
                                    })
                                    readings.append({
                                        "metric": "map", "value": _compute_map(sbp, dbp), "dt": dt_iso,
                                        "source_type": "ED_TRIAGE", "source_id": source_id,
                                        "line_preview": preview,
                                    })
                        # SpO2 (col 5)
                        if len(parts) > 5:
                            m_sp = re.match(r"(\d+(?:\.\d+)?)\s*%?", parts[5].strip())
                            if m_sp:
                                val = float(m_sp.group(1))
                                g = guardrails.get("spo2", {})
                                if _in_range(val, g.get("min", 50), g.get("max", 100)):
                                    readings.append({
                                        "metric": "spo2", "value": val, "dt": dt_iso,
                                        "source_type": "ED_TRIAGE", "source_id": source_id,
                                        "line_preview": preview,
                                    })
        i += 1

    return readings


def _parse_visit_vitals_block(
    text: str,
    day_iso: str,
    item_dt: Optional[str],
    config: Dict[str, Any],
    source_id: Any,
    guardrails: Dict[str, Dict[str, Any]],
    time_missing: bool = False,
) -> List[_VitalReading]:
    """Parse Visit Vitals block (label<TAB>value style)."""
    readings: List[_VitalReading] = []
    vv_cfg = config.get("visit_vitals_block", {})
    header_re = re.compile(vv_cfg.get("header_pattern", "(?!)"))
    lines = text.split("\n")

    dt_iso = item_dt if item_dt and item_dt.startswith(day_iso) else None
    if dt_iso is None:
        # Cannot assign timestamp — skip
        return readings

    i = 0
    while i < len(lines):
        if header_re.search(lines[i]):
            # Scan next ~15 lines for key-value pairs
            for j in range(i + 1, min(i + 16, len(lines))):
                ln = lines[j].strip()
                if not ln:
                    continue
                # Stop at next section header (no tab, not a kv pair)
                if not "\t" in ln and not re.match(r"(?i)^(BP|Pulse|Temp|Resp|SpO2|Ht|Wt|BMI)", ln):
                    break

                preview = ln[:200]

                # BP
                m = re.match(r"(?i)^BP\t(.+)", ln)
                if m:
                    m_bp = re.search(r"(\d+)\s*/\s*(\d+)", m.group(1))
                    if m_bp:
                        sbp = float(m_bp.group(1))
                        dbp = float(m_bp.group(2))
                        g = guardrails.get("bp", {})
                        if (_in_range(sbp, g.get("sbp_min", 40), g.get("sbp_max", 300)) and
                                _in_range(dbp, g.get("dbp_min", 20), g.get("dbp_max", 200))):
                            readings.append({"metric": "sbp", "value": sbp, "dt": dt_iso,
                                             "source_type": "VISIT_VITALS", "source_id": source_id,
                                             "line_preview": preview})
                            readings.append({"metric": "dbp", "value": dbp, "dt": dt_iso,
                                             "source_type": "VISIT_VITALS", "source_id": source_id,
                                             "line_preview": preview})
                            readings.append({"metric": "map", "value": _compute_map(sbp, dbp), "dt": dt_iso,
                                             "source_type": "VISIT_VITALS", "source_id": source_id,
                                             "line_preview": preview})
                    continue

                # Pulse
                m = re.match(r"(?i)^Pulse\t(\d+)", ln)
                if m:
                    val = float(m.group(1))
                    g = guardrails.get("hr", {})
                    if _in_range(val, g.get("min", 20), g.get("max", 300)):
                        readings.append({"metric": "hr", "value": val, "dt": dt_iso,
                                         "source_type": "VISIT_VITALS", "source_id": source_id,
                                         "line_preview": preview})
                    continue

                # Temp
                m = re.match(r"(?i)^Temp\t(.+)", ln)
                if m:
                    m_t = re.search(r"([\d]+(?:\.\d+)?)\s*°?\s*F", m.group(1))
                    if m_t:
                        val = float(m_t.group(1))
                        g = guardrails.get("temp_f", {})
                        if _in_range(val, g.get("min", 85), g.get("max", 115)):
                            readings.append({"metric": "temp_f", "value": val, "dt": dt_iso,
                                             "source_type": "VISIT_VITALS", "source_id": source_id,
                                             "line_preview": preview})
                    continue

                # Resp
                m = re.match(r"(?i)^Resp\t(\d+)", ln)
                if m:
                    val = float(m.group(1))
                    g = guardrails.get("rr", {})
                    if _in_range(val, g.get("min", 4), g.get("max", 60)):
                        readings.append({"metric": "rr", "value": val, "dt": dt_iso,
                                         "source_type": "VISIT_VITALS", "source_id": source_id,
                                         "line_preview": preview})
                    continue

                # SpO2
                m = re.match(r"(?i)^SpO2\t(\d+(?:\.\d+)?)\s*%?", ln)
                if m:
                    val = float(m.group(1))
                    g = guardrails.get("spo2", {})
                    if _in_range(val, g.get("min", 50), g.get("max", 100)):
                        readings.append({"metric": "spo2", "value": val, "dt": dt_iso,
                                         "source_type": "VISIT_VITALS", "source_id": source_id,
                                         "line_preview": preview})
                    continue
            # Advance past block
            i = min(i + 16, len(lines))
        else:
            i += 1

    return readings


# ═════════════════════════════════════════════════════════════════════
#  Tabular note-internal vitals parsing (fallback)
# ═════════════════════════════════════════════════════════════════════

# Pattern: multiple timestamps like "12/18/25 0730" on separate lines
# followed by rows of vital values — these appear in nursing notes.
_RE_TABULAR_TS_LINE = re.compile(
    r"^\s*(\d{1,2}/\d{1,2}/\d{2,4})\s+(\d{4})\s*$"
)

# Pattern: vital label at start of a line (colon-delimited)
_RE_TABULAR_VITAL_LABEL = re.compile(
    r"(?i)^\s*(BP|Pulse|Temp|Resp|SpO2)\s*:"
)

# Non-vital label lines to skip inside tabular blocks
_RE_TABULAR_SKIP_LABEL = re.compile(
    r"(?i)^\s*(TempSrc|Weight|Height|BMI|Ht|Wt|O2\s*(?:Flow|Device|Sat)"
    r"|PainAssessment)\s*:?"
)

# "Vital Signs:" header for single-value-per-line blocks
_RE_VITAL_SIGNS_HEADER = re.compile(
    r"(?i)^\s*(?:\d+\.\s*)?Vital\s+Signs?\s*(?:on\s+discharge\s*)?:\s*$"
)


def _extract_metric_from_cell(
    label: str,
    cell: str,
    guardrails: Dict[str, Dict[str, Any]],
) -> List[Tuple[str, float]]:
    """Extract metric readings from a single tabular cell.

    Returns list of (metric_name, value) tuples.
    BP yields (sbp, dbp, map).  Empty / malformed → [].
    """
    cell = cell.strip()
    if not cell:
        return []
    # Strip (!) abnormal marker
    cell = re.sub(r"\(\s*!?\s*\)", "", cell).strip()
    if not cell:
        return []

    label_lower = label.lower()
    results: List[Tuple[str, float]] = []

    if label_lower == "bp":
        m = re.search(r"(\d+)\s*/\s*(\d+)", cell)
        if m:
            sbp = float(m.group(1))
            dbp = float(m.group(2))
            g = guardrails.get("bp", {})
            if (_in_range(sbp, g.get("sbp_min", 40), g.get("sbp_max", 300)) and
                    _in_range(dbp, g.get("dbp_min", 20), g.get("dbp_max", 200))):
                results.append(("sbp", sbp))
                results.append(("dbp", dbp))
                results.append(("map", _compute_map(sbp, dbp)))

    elif label_lower in ("pulse", "hr"):
        m = re.search(r"(\d+)", cell)
        if m:
            val = float(m.group(1))
            g = guardrails.get("hr", {})
            if _in_range(val, g.get("min", 20), g.get("max", 300)):
                results.append(("hr", val))

    elif label_lower == "temp":
        m = re.search(r"([\d]+(?:\.\d+)?)\s*°?\s*F", cell)
        if m:
            val = float(m.group(1))
            g = guardrails.get("temp_f", {})
            if _in_range(val, g.get("min", 85), g.get("max", 115)):
                results.append(("temp_f", val))

    elif label_lower in ("resp", "rr"):
        m = re.search(r"(\d+)", cell)
        if m:
            val = float(m.group(1))
            g = guardrails.get("rr", {})
            if _in_range(val, g.get("min", 4), g.get("max", 60)):
                results.append(("rr", val))

    elif label_lower == "spo2":
        m = re.search(r"(\d+(?:\.\d+)?)\s*%?", cell)
        if m:
            val = float(m.group(1))
            g = guardrails.get("spo2", {})
            if _in_range(val, g.get("min", 50), g.get("max", 100)):
                results.append(("spo2", val))

    return results


def _parse_tabular_note_vitals(
    text: str,
    day_iso: str,
    item_dt: Optional[str],
    source_id: Any,
    guardrails: Dict[str, Dict[str, Any]],
    time_missing: bool = False,
) -> Tuple[List[_VitalReading], List[Dict[str, Any]]]:
    """Parse note-internal tabular vitals.

    Handles three sub-formats:
      A) Horizontal tabular — tab-separated timestamp header + label rows
      B) Vertical tabular   — consecutive timestamp lines + label/value groups
      C) Vital Signs block  — 'Vital Signs:' header + key: value per line

    Returns
    -------
    (readings, remaining_gaps)
        readings       : parsed vitals with source_type="TABULAR"
        remaining_gaps : blocks detected but not parseable (fail-closed)
    """
    readings: List[_VitalReading] = []
    gaps: List[Dict[str, Any]] = []
    lines = text.split("\n")
    parsed_set: set = set()  # line indices consumed by a sub-parser

    # ── A) Horizontal tabular ─────────────────────────────────────
    i = 0
    while i < len(lines):
        line = lines[i]
        tab_parts = line.split("\t")
        if len(tab_parts) >= 3:
            col_ts: List[Tuple[int, Optional[str]]] = []
            for ci, part in enumerate(tab_parts):
                p = part.strip()
                if re.match(r"^\d{1,2}/\d{1,2}/\d{2,4}\s+\d{4}$", p):
                    col_ts.append((ci, _parse_dt_flowsheet(p, day_iso)))

            valid_ts = [(ci, dt) for ci, dt in col_ts if dt is not None]
            if len(valid_ts) >= 2:
                parsed_set.add(i)
                blk: List[_VitalReading] = []
                j = i + 1
                while j < min(i + 25, len(lines)):
                    row = lines[j]
                    rp = row.split("\t")
                    first = (rp[0] if rp else "").strip()
                    label_m = _RE_TABULAR_VITAL_LABEL.match(first)
                    if label_m:
                        label = label_m.group(1)
                        parsed_set.add(j)
                        for ci, dt_iso in col_ts:
                            if dt_iso is None or not dt_iso.startswith(day_iso):
                                continue
                            if ci < len(rp):
                                for mk, mv in _extract_metric_from_cell(
                                    label, rp[ci], guardrails
                                ):
                                    blk.append({
                                        "metric": mk, "value": mv,
                                        "dt": dt_iso,
                                        "source_type": "TABULAR",
                                        "source_id": source_id,
                                        "line_preview": row.strip()[:200],
                                    })
                        j += 1
                    elif _RE_TABULAR_SKIP_LABEL.match(first):
                        parsed_set.add(j)
                        j += 1
                    elif row.strip() == "":
                        j += 1
                    else:
                        break

                if blk:
                    readings.extend(blk)
                else:
                    ts_samples = [tab_parts[ci].strip()
                                  for ci, _ in valid_ts[:5]]
                    gaps.append({
                        "gap_type": "TABULAR_NOTE_VITALS_UNSUPPORTED",
                        "source_id": source_id,
                        "timestamp_count": len(valid_ts),
                        "timestamp_samples": ts_samples,
                        "day_iso": day_iso,
                        "line_range": str(i + 1),
                        "preview": line.strip()[:200],
                    })
                i = j
                continue

        i += 1

    # ── B) Vertical tabular ───────────────────────────────────────
    i = 0
    while i < len(lines):
        if i in parsed_set:
            i += 1
            continue

        ts_cluster: List[Tuple[int, str, Optional[str]]] = []
        j = i
        while j < len(lines) and j not in parsed_set:
            m = _RE_TABULAR_TS_LINE.match(lines[j])
            if m:
                raw_ts = lines[j].strip()
                ts_cluster.append(
                    (j, raw_ts, _parse_dt_flowsheet(raw_ts, day_iso))
                )
                j += 1
            else:
                break

        if len(ts_cluster) >= 2:
            for ts_idx, _, _ in ts_cluster:
                parsed_set.add(ts_idx)
            num_ts = len(ts_cluster)
            blk = []
            scan_end = min(j + num_ts * 12 + 20, len(lines))

            k = j
            while k < scan_end:
                ln = lines[k].strip()
                if not ln:
                    k += 1
                    continue

                label_m = _RE_TABULAR_VITAL_LABEL.match(ln)
                if label_m:
                    label = label_m.group(1)
                    parsed_set.add(k)
                    for offset in range(num_ts):
                        val_idx = k + 1 + offset
                        if val_idx >= len(lines):
                            break
                        val_line = lines[val_idx].strip()
                        parsed_set.add(val_idx)
                        # Safety: stop if value line is another label
                        if (_RE_TABULAR_VITAL_LABEL.match(val_line) or
                                _RE_TABULAR_SKIP_LABEL.match(val_line)):
                            break
                        if not val_line:
                            continue

                        _, _, dt_iso = ts_cluster[offset]
                        if dt_iso is None or not dt_iso.startswith(day_iso):
                            continue

                        for mk, mv in _extract_metric_from_cell(
                            label, val_line, guardrails
                        ):
                            blk.append({
                                "metric": mk, "value": mv,
                                "dt": dt_iso,
                                "source_type": "TABULAR",
                                "source_id": source_id,
                                "line_preview": f"{label}: {val_line}"[:200],
                            })

                    k += 1 + num_ts
                    continue

                if _RE_TABULAR_SKIP_LABEL.match(ln):
                    parsed_set.add(k)
                    for si in range(k + 1, min(k + 1 + num_ts, len(lines))):
                        parsed_set.add(si)
                    k += 1 + num_ts
                    continue

                if blk:
                    break  # end of block after finding readings
                k += 1

            if blk:
                readings.extend(blk)
            else:
                ctx = "\n".join(
                    lines[max(0, j - 2):min(len(lines), j + 20)]
                )
                if re.search(
                    r"(?i)(BP|blood\s*press|pulse|temp|resp|SpO2"
                    r"|heart\s*rate)", ctx,
                ):
                    ts_samples = [c[1] for c in ts_cluster[:5]]
                    gaps.append({
                        "gap_type": "TABULAR_NOTE_VITALS_UNSUPPORTED",
                        "source_id": source_id,
                        "timestamp_count": num_ts,
                        "timestamp_samples": ts_samples,
                        "day_iso": day_iso,
                        "line_range": (
                            f"{ts_cluster[0][0]+1}-"
                            f"{ts_cluster[-1][0]+1}"
                        ),
                        "preview": "; ".join(ts_samples[:3]),
                    })

            i = k if k > j else j
        else:
            i = j if j > i else i + 1

    # ── C) Vital Signs block ──────────────────────────────────────
    dt_iso_c = item_dt if item_dt and item_dt.startswith(day_iso) else None
    for i, line in enumerate(lines):
        if i in parsed_set:
            continue
        if not _RE_VITAL_SIGNS_HEADER.match(line):
            continue
        if dt_iso_c is None:
            continue

        for j in range(i + 1, min(i + 12, len(lines))):
            if j in parsed_set:
                continue
            ln = lines[j].strip()
            if not ln:
                continue

            m = re.match(
                r"(?i)^(BP|Pulse|Temp|Resp|SpO2)\s*:\s*(.+)", ln
            )
            if m:
                label, value_str = m.group(1), m.group(2)
                parsed_set.add(j)
                for mk, mv in _extract_metric_from_cell(
                    label, value_str, guardrails
                ):
                    r_entry: _VitalReading = {
                        "metric": mk, "value": mv,
                        "dt": dt_iso_c,
                        "source_type": "TABULAR",
                        "source_id": source_id,
                        "line_preview": ln[:200],
                    }
                    if time_missing:
                        r_entry["time_missing"] = True
                    readings.append(r_entry)
            elif re.match(
                r"(?i)^\s*(TempSrc|Weight|Height|BMI|Temp\s*\(|"
                r"O2\s|Hunger|Housing)", ln
            ):
                continue
            else:
                break

    return readings, gaps


def _parse_inline_vitals(
    text: str,
    day_iso: str,
    item_dt: Optional[str],
    config: Dict[str, Any],
    source_id: Any,
    guardrails: Dict[str, Dict[str, Any]],
    exclude_res: List["re.Pattern[str]"],
    time_missing: bool = False,
) -> List[_VitalReading]:
    """Parse inline narrative vitals and discharge-summary inline vitals."""
    readings: List[_VitalReading] = []

    dt_iso = item_dt if item_dt and item_dt.startswith(day_iso) else None
    if dt_iso is None:
        return readings

    inline_cfg = config.get("inline_vitals", {})
    discharge_cfg = config.get("discharge_inline", {})
    trigger_re = re.compile(inline_cfg.get("trigger_pattern", "(?!)"))
    discharge_re = re.compile(discharge_cfg.get("trigger_pattern", "(?!)"))

    for line in text.split("\n"):
        ln = line.strip()
        if not ln:
            continue
        if _is_excluded_line(ln, exclude_res):
            continue

        is_vitals_line = trigger_re.search(ln) or discharge_re.search(ln)
        if not is_vitals_line:
            continue

        preview = ln[:200]

        # Temperature
        m = re.search(r"(?i)(?:temperature|temp)\s*(?:src)?[:\s]*(?:\(!?\)\s*)?([\d]+(?:\.\d+)?)\s*°?\s*F", ln)
        if m:
            val = float(m.group(1))
            g = guardrails.get("temp_f", {})
            if _in_range(val, g.get("min", 85), g.get("max", 115)):
                readings.append({"metric": "temp_f", "value": val, "dt": dt_iso,
                                 "source_type": "INLINE", "source_id": source_id,
                                 "line_preview": preview})

        # Blood pressure
        m = re.search(r"(?i)(?:blood\s*pressure|BP)\s*(?:\(!?\)\s*)?[:\s]*(?:\(!?\)\s*)?(\d+)\s*/\s*(\d+)", ln)
        if m:
            sbp = float(m.group(1))
            dbp = float(m.group(2))
            g = guardrails.get("bp", {})
            if (_in_range(sbp, g.get("sbp_min", 40), g.get("sbp_max", 300)) and
                    _in_range(dbp, g.get("dbp_min", 20), g.get("dbp_max", 200))):
                readings.append({"metric": "sbp", "value": sbp, "dt": dt_iso,
                                 "source_type": "INLINE", "source_id": source_id,
                                 "line_preview": preview})
                readings.append({"metric": "dbp", "value": dbp, "dt": dt_iso,
                                 "source_type": "INLINE", "source_id": source_id,
                                 "line_preview": preview})
                readings.append({"metric": "map", "value": _compute_map(sbp, dbp), "dt": dt_iso,
                                 "source_type": "INLINE", "source_id": source_id,
                                 "line_preview": preview})

        # Pulse / heart rate
        m = re.search(r"(?i)(?:pulse|heart\s*rate)\s*(?:\(!?\)\s*)?[:\s]*(?:\(!?\)\s*)?(\d+)", ln)
        if m:
            val = float(m.group(1))
            g = guardrails.get("hr", {})
            if _in_range(val, g.get("min", 20), g.get("max", 300)):
                readings.append({"metric": "hr", "value": val, "dt": dt_iso,
                                 "source_type": "INLINE", "source_id": source_id,
                                 "line_preview": preview})

        # Resp rate
        m = re.search(r"(?i)(?:resp\.?\s*rate|resp)\s*[:\s]*(\d+)", ln)
        if m:
            val = float(m.group(1))
            g = guardrails.get("rr", {})
            if _in_range(val, g.get("min", 4), g.get("max", 60)):
                readings.append({"metric": "rr", "value": val, "dt": dt_iso,
                                 "source_type": "INLINE", "source_id": source_id,
                                 "line_preview": preview})

        # SpO2
        m = re.search(r"(?i)SpO2\s*[:\s]*(\d+(?:\.\d+)?)\s*%?", ln)
        if m:
            val = float(m.group(1))
            g = guardrails.get("spo2", {})
            if _in_range(val, g.get("min", 50), g.get("max", 100)):
                readings.append({"metric": "spo2", "value": val, "dt": dt_iso,
                                 "source_type": "INLINE", "source_id": source_id,
                                 "line_preview": preview})

    return readings


# ═════════════════════════════════════════════════════════════════════
#  Rollup: aggregate readings → per-metric min/max/last
# ═════════════════════════════════════════════════════════════════════

def _rollup_metric(readings: List[_VitalReading]) -> Dict[str, Any]:
    """Given a list of readings for ONE metric, compute min/max/last/last_dt/sources + abnormal summary."""
    if not readings:
        return _empty_metric()

    values = [r["value"] for r in readings]
    # Sort by dt to find last
    sorted_by_dt = sorted(readings, key=lambda r: r.get("dt") or "")
    last_reading = sorted_by_dt[-1]
    sources = [
        _source_entry(
            r["source_type"], r["source_id"], r.get("line_preview", ""),
            value=r["value"],
            dt=r.get("dt"),
            abnormal=r.get("abnormal", False),
            time_missing=r.get("time_missing", False),
        )
        for r in readings
    ]

    # Abnormal summary
    abnormal_readings = [r for r in readings if r.get("abnormal")]
    abnormal_count = len(abnormal_readings)
    first_abnormal: Optional[Dict[str, Any]] = None
    if abnormal_readings:
        # Sort by dt to find first abnormal
        sorted_abn = sorted(abnormal_readings, key=lambda r: r.get("dt") or "")
        fa = sorted_abn[0]
        first_abnormal = {
            "value": fa["value"],
            "dt": fa.get("dt"),
            "time_missing": fa.get("time_missing", False),
            "source_type": fa["source_type"],
        }

    return {
        "min": min(values),
        "max": max(values),
        "last": last_reading["value"],
        "last_dt": last_reading.get("dt"),
        "count": len(values),
        "sources": sources,
        "abnormal_count": abnormal_count,
        "first_abnormal": first_abnormal,
    }


def _empty_metric() -> Dict[str, Any]:
    return {
        "min": None,
        "max": None,
        "last": None,
        "last_dt": None,
        "count": 0,
        "sources": [],
        "abnormal_count": 0,
        "first_abnormal": None,
    }


# ═════════════════════════════════════════════════════════════════════
#  Deduplication
# ═════════════════════════════════════════════════════════════════════

def _dedup_readings(readings: List[_VitalReading]) -> List[_VitalReading]:
    """Remove duplicate readings with same metric+dt+value.

    Prefer FLOWSHEET > ED_TRIAGE > VISIT_VITALS > INLINE source.
    """
    _PRIORITY = {"FLOWSHEET": 0, "ED_TRIAGE": 1, "VISIT_VITALS": 2, "TABULAR": 3, "INLINE": 4}
    seen: Dict[Tuple[str, Optional[str], float], _VitalReading] = {}
    for r in readings:
        key = (r["metric"], r.get("dt"), r["value"])
        if key not in seen:
            seen[key] = r
        else:
            existing_prio = _PRIORITY.get(seen[key]["source_type"], 99)
            new_prio = _PRIORITY.get(r["source_type"], 99)
            if new_prio < existing_prio:
                seen[key] = r
    return list(seen.values())


# ═════════════════════════════════════════════════════════════════════
#  PUBLIC API
# ═════════════════════════════════════════════════════════════════════

def extract_vitals_for_day(
    items: List[Dict[str, Any]],
    day_iso: str,
    config: Dict[str, Any],
) -> Tuple[Dict[str, Any], List[str]]:
    """
    Extract vitals for a single day from timeline items.

    Parameters
    ----------
    items   : timeline items for the day
    day_iso : 'YYYY-MM-DD'
    config  : loaded vitals_patterns_v1 config dict

    Returns
    -------
    (result_dict, warnings)
        result_dict has keys: temp_f, hr, rr, spo2, sbp, dbp, map, warnings
        Each metric is {min, max, last, last_dt, count, sources[]}.
    """
    warnings: List[str] = []

    # Load guardrails from config
    metric_cfg = config.get("metric_patterns", {})
    guardrails: Dict[str, Dict[str, Any]] = {}
    for mk in ("temp_f", "hr", "rr", "spo2", "bp"):
        mc = metric_cfg.get(mk, {})
        guardrails[mk] = mc.get("guardrails", {})

    # Compile negative-context exclusion patterns
    neg_cfg = config.get("negative_context", {})
    exclude_res = []
    for pat_str in neg_cfg.get("exclude_line_patterns", []):
        try:
            exclude_res.append(re.compile(pat_str))
        except re.error:
            continue

    all_readings: List[_VitalReading] = []
    tabular_vitals_gaps: List[Dict[str, Any]] = []
    has_evidence = len(items) > 0

    for item in items:
        text = (item.get("payload") or {}).get("text", "")
        if not text:
            continue
        source_id = item.get("source_id")
        item_dt = item.get("dt")
        item_time_missing = bool(item.get("time_missing"))

        # 1. Flowsheet table (highest priority — extracts own timestamps)
        all_readings.extend(
            _parse_flowsheet_table(text, day_iso, config, source_id, guardrails)
        )

        # 2. ED Triage Vitals block (extracts own timestamps)
        all_readings.extend(
            _parse_ed_triage_block(text, day_iso, config, source_id, guardrails)
        )

        # 3. Visit Vitals block (uses item_dt)
        vv_readings = _parse_visit_vitals_block(
            text, day_iso, item_dt, config, source_id, guardrails,
            time_missing=item_time_missing,
        )
        if item_time_missing:
            for r in vv_readings:
                r["time_missing"] = True
        all_readings.extend(vv_readings)

        # 4. Inline / discharge vitals (uses item_dt)
        in_readings = _parse_inline_vitals(
            text, day_iso, item_dt, config, source_id, guardrails, exclude_res,
            time_missing=item_time_missing,
        )
        if item_time_missing:
            for r in in_readings:
                r["time_missing"] = True
        all_readings.extend(in_readings)

        # 5. Tabular note vitals — fallback parse + gap detect
        tab_readings, tab_gaps = _parse_tabular_note_vitals(
            text, day_iso, item_dt, source_id, guardrails,
            time_missing=item_time_missing,
        )
        if item_time_missing:
            for r in tab_readings:
                r["time_missing"] = True
        all_readings.extend(tab_readings)
        tabular_vitals_gaps.extend(tab_gaps)

    # Deduplicate
    all_readings = _dedup_readings(all_readings)

    # Annotate each reading with abnormal flag
    for r in all_readings:
        r.setdefault("time_missing", False)
        r["abnormal"] = _is_abnormal(r["metric"], r["value"])

    # ── Vitals QA metrics ──────────────────────────────────────
    readings_total = len(all_readings)
    readings_with_full_ts = sum(
        1 for r in all_readings
        if r.get("dt") and not r.get("time_missing") and "T" in str(r.get("dt", ""))
    )
    readings_missing_time = sum(1 for r in all_readings if r.get("time_missing"))
    readings_missing_date = 0  # should be 0 if assigned to a real day
    if day_iso == "__UNDATED__":
        readings_missing_date = readings_total

    vitals_qa = {
        "vitals_readings_total": readings_total,
        "vitals_readings_with_full_ts": readings_with_full_ts,
        "vitals_readings_missing_time": readings_missing_time,
        "vitals_readings_missing_date": readings_missing_date,
        "tabular_note_vitals_unsupported": len(tabular_vitals_gaps),
        "tabular_note_vitals_gaps": tabular_vitals_gaps,
    }

    # Group by metric
    by_metric: Dict[str, List[_VitalReading]] = {mk: [] for mk in METRIC_KEYS}
    for r in all_readings:
        mk = r["metric"]
        if mk in by_metric:
            by_metric[mk].append(r)

    # Rollup
    result: Dict[str, Any] = {}
    for mk in METRIC_KEYS:
        if by_metric[mk]:
            result[mk] = _rollup_metric(by_metric[mk])
        else:
            result[mk] = _empty_metric()

    # Day-level abnormal summary
    abnormal_summary: Dict[str, Any] = {}
    for mk in METRIC_KEYS:
        ac = result[mk].get("abnormal_count", 0)
        if ac > 0:
            abnormal_summary[mk] = {
                "count": ac,
                "first_abnormal": result[mk].get("first_abnormal"),
            }
    result["abnormal_summary"] = abnormal_summary

    # Warning: day has evidence items but zero vitals extracted
    any_vitals = any(result[mk]["count"] > 0 for mk in METRIC_KEYS)
    if has_evidence and not any_vitals:
        warnings.append("vitals_missing_for_day")

    # Warning: tabular note vitals detected but not parsed (QA gap)
    if tabular_vitals_gaps:
        n_gaps = len(tabular_vitals_gaps)
        warnings.append(f"tabular_note_vitals_unsupported:{n_gaps}")

    result["warnings"] = warnings
    result["vitals_qa"] = vitals_qa
    return result, warnings


# ═════════════════════════════════════════════════════════════════════
#  Arrival vitals: item-type-aware extraction with priority hierarchy
# ═════════════════════════════════════════════════════════════════════

# Item types that represent Primary Survey / Trauma H&P context.
_ARRIVAL_PRIMARY_SURVEY_TYPES = frozenset({"TRAUMA_HP"})

# Item types that represent ED fallback context.
_ARRIVAL_ED_FALLBACK_TYPES = frozenset({"ED_NOTE", "ED_NURSING", "TRIAGE"})


def _extract_readings_for_items(
    items: List[Dict[str, Any]],
    day_iso: str,
    config: Dict[str, Any],
    guardrails: Dict[str, Dict[str, Any]],
    exclude_res: List["re.Pattern[str]"],
) -> List[_VitalReading]:
    """Extract vital readings from a set of items using all parsers."""
    all_readings: List[_VitalReading] = []
    for item in items:
        text = (item.get("payload") or {}).get("text", "")
        if not text:
            continue
        source_id = item.get("source_id")
        item_dt = item.get("dt")
        item_time_missing = bool(item.get("time_missing"))

        all_readings.extend(
            _parse_flowsheet_table(text, day_iso, config, source_id, guardrails)
        )
        all_readings.extend(
            _parse_ed_triage_block(text, day_iso, config, source_id, guardrails)
        )

        vv = _parse_visit_vitals_block(
            text, day_iso, item_dt, config, source_id, guardrails,
            time_missing=item_time_missing,
        )
        if item_time_missing:
            for r in vv:
                r["time_missing"] = True
        all_readings.extend(vv)

        inl = _parse_inline_vitals(
            text, day_iso, item_dt, config, source_id, guardrails,
            exclude_res, time_missing=item_time_missing,
        )
        if item_time_missing:
            for r in inl:
                r["time_missing"] = True
        all_readings.extend(inl)

        tab, _ = _parse_tabular_note_vitals(
            text, day_iso, item_dt, source_id, guardrails,
            time_missing=item_time_missing,
        )
        if item_time_missing:
            for r in tab:
                r["time_missing"] = True
        all_readings.extend(tab)

    return all_readings


def _build_arrival_result(
    readings: List[_VitalReading],
    source_context: str,
    source_items: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build arrival vitals result from extracted readings."""
    by_metric: Dict[str, List[_VitalReading]] = {mk: [] for mk in METRIC_KEYS}
    for r in readings:
        if r["metric"] in by_metric:
            by_metric[r["metric"]].append(r)

    vitals: Dict[str, Any] = {}
    first_preview: Optional[str] = None
    for mk in METRIC_KEYS:
        metric_readings = by_metric[mk]
        if metric_readings:
            sorted_r = sorted(metric_readings, key=lambda r: r.get("dt") or "")
            vitals[mk] = sorted_r[0]["value"]
            if first_preview is None:
                first_preview = sorted_r[0].get("line_preview")
        else:
            vitals[mk] = None

    # Pick earliest item that contributed readings
    contributing_ids = {r.get("source_id") for r in readings}
    source_item = next(
        (i for i in source_items if i.get("source_id") in contributing_ids),
        source_items[0],
    )

    return {
        "status": "selected",
        "source_context": source_context,
        "item_type": source_item.get("type"),
        "source_item_dt": source_item.get("dt"),
        "source_item_id": source_item.get("source_id"),
        "vitals": vitals,
        "readings_count": len(readings),
        "line_preview": first_preview,
        "warnings": [],
    }


def _arrival_vitals_stub() -> Dict[str, Any]:
    """DATA NOT AVAILABLE stub for arrival vitals."""
    return {
        "status": "DATA NOT AVAILABLE",
        "source_context": None,
        "item_type": None,
        "source_item_dt": None,
        "source_item_id": None,
        "vitals": {mk: None for mk in METRIC_KEYS},
        "readings_count": 0,
        "line_preview": None,
        "warnings": [],
    }


def extract_arrival_vitals(
    items: List[Dict[str, Any]],
    day_iso: str,
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Extract arrival vitals with deterministic priority hierarchy.

    Uses the timeline item ``type`` field to partition items and apply
    source-context priority:

      1. TRAUMA_HP items (Primary Survey context) → source_context="PRIMARY_SURVEY"
      2. ED_NOTE / ED_NURSING / TRIAGE items (ED fallback) → source_context="ED_FALLBACK"
      3. DATA NOT AVAILABLE

    Within each tier, all existing vitals parsers (flowsheet, ED triage,
    visit-vitals, inline, tabular) are applied.  The earliest reading per
    metric is selected.

    Parameters
    ----------
    items   : timeline items for the arrival day
    day_iso : 'YYYY-MM-DD'
    config  : loaded vitals_patterns_v1 config dict

    Returns
    -------
    dict
        ``status``='selected' with ``vitals`` sub-dict and provenance, or
        ``status``='DATA NOT AVAILABLE' stub.
    """
    # Load guardrails
    metric_cfg = config.get("metric_patterns", {})
    guardrails: Dict[str, Dict[str, Any]] = {}
    for mk in ("temp_f", "hr", "rr", "spo2", "bp"):
        mc = metric_cfg.get(mk, {})
        guardrails[mk] = mc.get("guardrails", {})

    # Compile negative-context exclusion patterns
    neg_cfg = config.get("negative_context", {})
    exclude_res: List[re.Pattern[str]] = []
    for pat_str in neg_cfg.get("exclude_line_patterns", []):
        try:
            exclude_res.append(re.compile(pat_str))
        except re.error:
            continue

    # Partition items by type
    primary_items = [i for i in items if i.get("type") in _ARRIVAL_PRIMARY_SURVEY_TYPES]
    ed_items = [i for i in items if i.get("type") in _ARRIVAL_ED_FALLBACK_TYPES]

    # Tier 1: Primary Survey (TRAUMA_HP)
    if primary_items:
        readings = _extract_readings_for_items(
            primary_items, day_iso, config, guardrails, exclude_res,
        )
        readings = _dedup_readings(readings)
        if readings:
            return _build_arrival_result(readings, "PRIMARY_SURVEY", primary_items)

    # Tier 2: ED fallback
    if ed_items:
        readings = _extract_readings_for_items(
            ed_items, day_iso, config, guardrails, exclude_res,
        )
        readings = _dedup_readings(readings)
        if readings:
            return _build_arrival_result(readings, "ED_FALLBACK", ed_items)

    # Tier 3: DATA NOT AVAILABLE
    return _arrival_vitals_stub()
