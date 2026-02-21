#!/usr/bin/env python3
"""
Deterministic lab extraction for CerebralOS.

Parsers applied in priority order:

1) "Lab Test Results" strict table (highest priority):
   Header: ``Lab Test Results``
   Columns: Component | Date/Time | Value | Range & Unit | Status
   (example: Lolita_Calcia)

2) Tab-delimited lab table:
   Columns: Component(tab)Date(tab)Value(tab)Ref Range(tab)Status
   Rows:    bullet(tab)Component(tab)MM/DD/YYYY(tab)Value (flag)(tab)Range UNIT(tab)Status
   (example: Timothy_Cowan)

3) Relaxed table row parser:
   Matches rows with Component + Date + Time + Value, even when
   Range/Unit/Status columns are absent.  Whitespace-separated.

4) Single-line lab result parser:
   Matches "Component  Value [Unit] [flags]" commonly seen in
   narrative / LAB sections without date/time on the line.

5) "Recent Labs" matrix (fully parsed):
   Epic "Recent Labs" format with datetime column headers and
   component value rows.  Supports two sub-variants:
   a) Tab-delimited: dates/times in tab-separated header cells,
      data rows also tab-delimited.
   b) Newline-delimited: each date, time, component name, and value
      on its own line.
   Handles missing values (' -- '), dual values ('1.0 | 0.8'),
   flagged values ('12.3*'), and optional 'Lab' prefix column.

Design:
- Fail-closed: unparseable lab-like lines captured with warning
  ``unparsed_lab_line``.
- Order text is skipped (no false positives from order verbs).
- Relaxed / single-line parsers run only within LAB-typed items
  or detected lab sections to prevent false positives from
  imaging, vitals, or medication data.
- No clinical inference, no ML/LLM.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# ----------------------------------------------------------------
# Regex patterns
# ----------------------------------------------------------------

# --- Priority 1: Strict "Lab Test Results" table ---
LAB_TABLE_HEADER_RE = re.compile(
    r"^\s*Lab Test Results\s*$", re.IGNORECASE
)
LAB_TABLE_COLS_RE = re.compile(
    r"^\s*Component\s+Date/Time\s+Value\s+Range\s*&\s*Unit\s+Status\s*$",
    re.IGNORECASE,
)
LAB_TABLE_ROW_RE = re.compile(
    r"^\s*(?P<component>[A-Za-z0-9\-\./%() ]+?)\s+"
    r"(?P<date>\d{1,2}/\d{1,2}/\d{2})\s+"
    r"(?P<time>\d{3,4})\s+"
    r"(?P<value>[-+<>]?\s*[A-Za-z0-9\.,]+)\s+"
    r"(?P<range_unit>.+?)\s+"
    r"(?P<status>Final|Preliminary|Corrected|In process|In Process|Canceled|Cancelled)\s*$",
    re.IGNORECASE,
)

# --- Priority 2: Tab-delimited lab table ---
TAB_TABLE_COLS_RE = re.compile(
    r"^\s*Component\tDate\tValue\tRef Range\tStatus\s*$",
    re.IGNORECASE,
)

# --- Priority 3: Relaxed table row (whitespace, date+time+value) ---
RELAXED_ROW_RE = re.compile(
    r"^\s*(?P<component>[A-Za-z0-9][A-Za-z0-9\-\./%() ]+?)\s+"
    r"(?P<date>\d{1,2}/\d{1,2}/\d{2,4})\s+"
    r"(?P<time>\d{3,4})\s+"
    r"(?P<value>[-+<>]?\s*\d+(?:\.\d+)?)\s*"
    r"(?P<tail>.*)$"
)

# --- Priority 4: Single-line result ---
SINGLE_LINE_RE = re.compile(
    r"^\s*(?P<component>[A-Za-z][A-Za-z0-9\-\./%() ]{1,40}?)\s+"
    r"(?P<value>[-+<>]?\s*\d+(?:\.\d+)?)\s*"
    r"(?:(?P<unit>[A-Za-z/%][A-Za-z0-9/%\.\-\*]{0,12})\s*)?"
    r"(?P<flag>\(?[Hh]{1,2}\)?|\(?[Ll]{1,2}\)?|HH|LL|High|Low)?\s*$"
)

# --- Recent Labs matrix ---
RECENT_LABS_HEADER_RE = re.compile(r"^\s*Recent Labs\s*$", re.IGNORECASE)
RECENT_LABS_DATE_RE = re.compile(r"^\s*\d{1,2}/\d{1,2}/\d{2}\s*$")
RECENT_LABS_TIME_RE = re.compile(r"^\s*\d{3,4}\s*$")

# Component names used in Epic Recent Labs matrices (upper-case).
# This is used to detect the boundary between the datetime header block
# and the data rows in the newline-delimited variant.
_RECENT_LABS_COMPONENTS = {
    "WBC", "HGB", "HCT", "PLT", "NA", "K", "CL", "CO2", "BUN",
    "CREATININE", "INR", "LABBILI", "AST", "ALT", "ALKPHOS", "LIPASE",
    "GLU", "LABALBU", "CHOL", "TRIG", "LDLCALC", "CHOLHDL", "VLDL",
    "POCGLU", "PROTIME", "PTT", "APTT", "FIBRINOGEN", "CA", "MG",
    "PHOS", "PHOSPHORUS", "ALBUMIN", "PROTEIN", "TBILI", "DBILI",
    "AMMONIA", "LACTATE", "GFR", "EGFR", "TROPONIN", "TROPONI",
    "BNP", "PROCALCITONIN", "CRP", "ESR", "FERRITIN", "IRON",
    "TIBC", "TRANSFERRIN", "HEMOGLOBIN", "HEMATOCRIT",
    "RBC", "MCV", "MCH", "MCHC", "RDW", "MPV",
    "NEUTROPHILS", "LYMPHS", "MONOCYTES", "EOSINOPHILS", "BASOPHILS",
    "BANDS", "RETICULOCYTES", "RETICULOCYTE", "URICACID",
    "LDH", "CK", "CPK", "CKMB", "MAGNESIUM", "CALCIUM",
    "GLUCOSE", "SODIUM", "POTASSIUM", "CHLORIDE", "BICARBONATE",
}

# Regex for a date token: MM/DD/YY
_MATRIX_DATE_TOK_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{2}$")
# Regex for a time token: 3-4 digit military time
_MATRIX_TIME_TOK_RE = re.compile(r"^\d{3,4}$")
# Regex for matrix value tokens: number, possibly with * flag, or " -- " (missing)
_MATRIX_VALUE_RE = re.compile(
    r"^[-+<>]?\s*\d+(?:\.\d+)?\s*\*?\s*(?:\|.*)?$|^\s*--\s*$|^\s*< >\s*$"
)
# Component-like line: starts with a letter, uppercase, 2-20 chars
_MATRIX_COMPONENT_RE = re.compile(r"^[A-Z][A-Z0-9]{1,20}$")

# --- Order / skip detection ---
ORDER_VERB_RE = re.compile(
    r"\b(Ordered|Order|Specimen|Collect|Pending|To be collected)\b",
    re.IGNORECASE,
)

# Lab section markers
LAB_SECTION_RE = re.compile(r"^\s*(?:\[LAB\]|Labs?\s*:)", re.IGNORECASE)

# Lines to always skip inside lab context (lowercased prefix check)
_SKIP_LINE_PREFIXES = (
    "comment:", "admission on", "discharged on", "===", "---",
    "age(years)", "see chart", "<60", "60-69", ">70",
    "tracking links", "order audit", "providers", "pharmacy",
    "[physician_note]", "impression:", "plan:",
    "labs:", "labs ", "[lab]",
    "component\t",
)

BULLET = "\u2022"  # Unicode bullet character


# ----------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------

def _parse_date_opt_time(date_s, time_s=None):
    """Parse MM/DD/YY or MM/DD/YYYY with optional military time HHMM."""
    warnings = []
    try:
        parts = date_s.strip().split("/")
        if len(parts) != 3:
            return None, ["date_parse_failed"]
        mm, dd = int(parts[0]), int(parts[1])
        yr_s = parts[2]
        if len(yr_s) == 4:
            year = int(yr_s)
        else:
            yy = int(yr_s)
            year = 2000 + yy if yy < 70 else 1900 + yy
        if time_s and time_s.strip():
            hhmm = time_s.strip().zfill(4)
            hh, mi = int(hhmm[:2]), int(hhmm[2:])
        else:
            hh, mi = 0, 0
            warnings.append("time_defaulted_0000")
        dt = datetime(year, mm, dd, hh, mi)
        return dt.isoformat(), warnings
    except Exception:
        return None, ["date_parse_failed"]


def _parse_mmddyy_hhmm(date_s, time_s):
    """Legacy helper kept for the strict table parser."""
    iso, _ = _parse_date_opt_time(date_s, time_s)
    return iso


def _to_float(value_raw):
    v = value_raw.strip().replace(",", "").replace("<", "").replace(">", "")
    try:
        return float(v)
    except Exception:
        return None


def _extract_value_and_flags(val_str):
    """Split '364 (H)' -> ('364', ['H']),  '1.2 ' -> ('1.2', [])."""
    val_str = val_str.strip()
    flags = []
    m = re.search(r"\s*\(([HhLl]{1,2})\)\s*$", val_str)
    if m:
        flags.append(m.group(1).upper())
        val_str = val_str[:m.start()].strip()
    else:
        m = re.search(r"\s+([HhLl]{1,2})\s*$", val_str)
        if m and m.group(1).upper() in ("H", "L", "HH", "LL"):
            flags.append(m.group(1).upper())
            val_str = val_str[:m.start()].strip()
    return val_str, flags


def _extract_unit_from_range(range_unit_str):
    """Extract unit from range+unit string like '70 - 99 MG/DL'."""
    s = range_unit_str.strip()
    if not s:
        return ""
    tokens = s.split()
    unit_tokens = []
    for tok in reversed(tokens):
        if re.match(r"^[A-Za-z%][A-Za-z0-9/%\.\-\*\']{0,20}$", tok):
            unit_tokens.insert(0, tok)
        else:
            break
    return " ".join(unit_tokens)


def _extract_unit_and_flag_from_tail(tail):
    """From the tail of a relaxed row, extract optional unit and flags."""
    tail = tail.strip()
    flags = []
    unit = ""
    if not tail:
        return unit, flags
    for fm in re.finditer(
        r"\(?([HhLl]{1,2})\)?|(?<![A-Za-z])(High|Low)(?![A-Za-z])", tail,
    ):
        flag_val = (fm.group(1) or fm.group(2) or "").upper()
        if flag_val in ("H", "L", "HH", "LL", "HIGH", "LOW"):
            normalized = {"HIGH": "H", "LOW": "L"}.get(flag_val, flag_val)
            if normalized not in flags:
                flags.append(normalized)
    cleaned = re.sub(
        r"\(?[HhLl]{1,2}\)?|(?<![A-Za-z])(?:High|Low)(?![A-Za-z])",
        "", tail,
    ).strip()
    tokens = cleaned.split()
    unit_parts = []
    for tok in tokens:
        if re.match(r"^[A-Za-z/%][A-Za-z0-9/%\.\-\*]{0,12}$", tok):
            unit_parts.append(tok)
    unit = " ".join(unit_parts) if unit_parts else ""
    return unit, flags


def _normalize_flag(s):
    s = s.strip().upper().replace("(", "").replace(")", "")
    return {"HIGH": "H", "LOW": "L"}.get(s, s)


def _is_order_line(text):
    """True when line has order verbs and no numeric result value."""
    if not ORDER_VERB_RE.search(text):
        return False
    no_dates = re.sub(r"\d{1,2}/\d{1,2}/\d{2,4}", "", text)
    no_dates = re.sub(r"\b\d{3,4}\b", "", no_dates)
    return not re.search(r"\d+(?:\.\d+)?", no_dates)


def _is_skip_line(text):
    """True for lines that should never be parsed as lab results."""
    low = text.strip().lower()
    if not low:
        return True
    for prefix in _SKIP_LINE_PREFIXES:
        if low.startswith(prefix):
            return True
    if low.startswith("[") or low.startswith("="):
        return True
    return False


def _parse_tab_row(text):
    """Parse bullet tab row: BULLET(tab)Component(tab)Date(tab)Value(tab)Range(tab)Status"""
    if not text.startswith(BULLET):
        return None
    fields = text.split("\t")
    if len(fields) < 4:
        return None
    component = fields[1].strip() if len(fields) > 1 else ""
    date_str = fields[2].strip() if len(fields) > 2 else ""
    value_raw = fields[3].strip() if len(fields) > 3 else ""
    range_unit = fields[4].strip() if len(fields) > 4 else ""
    status = fields[5].strip() if len(fields) > 5 else ""
    if not component or not re.match(r"\d{1,2}/\d{1,2}/\d{2,4}$", date_str):
        return None
    return {
        "component": component,
        "date": date_str,
        "value_raw_full": value_raw,
        "range_unit": range_unit,
        "status": status,
    }


# ----------------------------------------------------------------
# Recent Labs matrix parser
# ----------------------------------------------------------------

def _extract_matrix_value(tok: str) -> Tuple[str, Optional[float], List[str]]:
    """
    Parse a single matrix cell value like '12.3*', '134*', ' -- ', '< >',
    '1.0 | 0.8'.

    Returns (value_raw, value_num, flags).
    For dual values like '1.0 | 0.8', takes the FIRST value.
    """
    tok = tok.strip()
    if tok in ("--", ""):
        return "", None, []
    if tok == "< >":
        return "", None, []

    # Handle dual values: "1.0 | 0.8" -> take first
    if "|" in tok:
        tok = tok.split("|")[0].strip()

    flags: List[str] = []
    if tok.endswith("*"):
        flags.append("ABNORMAL")
        tok = tok[:-1].strip()

    # Extract H/L flags in parens
    m = re.search(r"\(([HhLl]{1,2})\)\s*$", tok)
    if m:
        flags.append(m.group(1).upper())
        tok = tok[:m.start()].strip()

    value_num = _to_float(tok)
    return tok, value_num, flags


def _parse_recent_labs_matrix_tab(
    lines: List[Dict[str, Any]],
    start_idx: int,
) -> Tuple[List[Dict[str, Any]], List[str], int]:
    """
    Parse a tab-delimited Recent Labs matrix.

    Epic cells contain "DATE\\nTIME" tab-separated. After newline splitting
    the tokens interleave across lines:
        Line 0: [Lab\\t | \\t]DATE_1
        Line 1: TIME_1[\\tDATE_2]
        Line 2: TIME_2[\\tDATE_3]
        ...
        Line N: TIME_N
    Then data rows: COMPONENT\\tVAL1\\tVAL2\\t...
    """
    labs: List[Dict[str, Any]] = []
    warnings: List[str] = []
    j = start_idx + 1  # skip "Recent Labs" header

    # Skip blanks
    while j < len(lines):
        t = (lines[j].get("text") or "").strip()
        if t:
            break
        j += 1

    if j >= len(lines):
        return labs, ["recent_labs_matrix_empty"], j

    # Detect tab-delimited format: the next non-blank line contains tabs
    header_line = (lines[j].get("text") or "").rstrip("\n")
    if "\t" not in header_line:
        return [], [], start_idx  # Not tab-delimited, signal to caller

    # ── Collect all tokens from header lines in order ──────────────
    # We read header lines until we hit a data row (component + tab + values).
    # Each header line is split by tab, and each cell classified as date/time/prefix.
    all_header_tokens: List[str] = []

    def _collect_tokens_from_line(line_text: str) -> List[str]:
        cells = line_text.split("\t")
        return [c.strip() for c in cells]

    # Read header lines: they contain dates and times interleaved
    # Stop when we hit a line whose first tab-cell looks like a component name
    # (i.e., not a date, not a time, not "Lab", not blank)
    while j < len(lines):
        lt = (lines[j].get("text") or "").rstrip("\n")
        lt_stripped = lt.strip()

        if not lt_stripped:
            j += 1
            continue

        cells = _collect_tokens_from_line(lt)
        first = cells[0] if cells else ""

        # Is this still a header line?
        # Header lines have their first cell as: blank, "Lab", a date, or a time
        is_header = (
            first == ""
            or first.upper() == "LAB"
            or _MATRIX_DATE_TOK_RE.match(first)
            or _MATRIX_TIME_TOK_RE.match(first)
        )

        if not is_header:
            # Might be a data row or end-of-block — stop header collection
            break

        all_header_tokens.extend(cells)
        j += 1

    # ── Extract dates and times in order from collected tokens ─────
    dates_raw: List[str] = []
    times_raw: List[str] = []
    for tok in all_header_tokens:
        if not tok or tok.upper() == "LAB":
            continue
        if _MATRIX_DATE_TOK_RE.match(tok):
            dates_raw.append(tok)
        elif _MATRIX_TIME_TOK_RE.match(tok):
            times_raw.append(tok)

    if not dates_raw:
        warnings.append("recent_labs_matrix_no_datetime_columns")
        return labs, warnings, j

    # Pair dates with times (they alternate: DATE1, TIME1, DATE2, TIME2, ...)
    col_dts: List[Optional[str]] = []
    for k in range(len(dates_raw)):
        time_s = times_raw[k] if k < len(times_raw) else None
        iso, dt_w = _parse_date_opt_time(dates_raw[k], time_s)
        col_dts.append(iso)
        warnings.extend(dt_w)

    n_cols = len(col_dts)

    # ── Parse data rows ───────────────────────────────────────────
    MAX_ROWS = 150
    row_count = 0
    while j < len(lines) and row_count < MAX_ROWS:
        row_text = (lines[j].get("text") or "").rstrip("\n")
        row_stripped = row_text.strip()

        # End-of-block detection
        if not row_stripped:
            j += 1
            continue
        if row_stripped.startswith("[") and "NOTE" in row_stripped:
            break
        if re.match(r"^\s*[A-Z][A-Z \-/]{3,}:\s*$", row_stripped):
            break
        if row_stripped.lower().startswith(("impression", "plan:", "prophylaxis",
                                            "antibiotics", "objective")):
            break
        if RECENT_LABS_HEADER_RE.match(row_stripped):
            break
        # "< > = values..." disclaimer
        if row_stripped.startswith("< >"):
            j += 1
            continue

        if "\t" in row_text:
            cells = row_text.split("\t")
            comp = cells[0].strip()
            if not comp or comp.upper() in ("LAB", ""):
                j += 1
                continue
            values = [c.strip() for c in cells[1:]]

            for col_idx in range(min(len(values), n_cols)):
                val_raw, val_num, val_flags = _extract_matrix_value(values[col_idx])
                if val_raw == "" and val_num is None:
                    continue  # skip missing
                labs.append({
                    "component": comp,
                    "observed_dt": col_dts[col_idx],
                    "value_raw": val_raw,
                    "value_num": val_num,
                    "unit": "",
                    "flags": val_flags,
                    "source_block_type": "recent_labs_matrix",
                    "source_line": j,
                })
            row_count += 1
        else:
            # Non-tab line inside tab block — probably end of block
            if re.match(r"^[A-Za-z]", row_stripped) and not _MATRIX_VALUE_RE.match(row_stripped):
                break
        j += 1

    return labs, warnings, j


def _parse_recent_labs_matrix_newline(
    lines: List[Dict[str, Any]],
    start_idx: int,
) -> Tuple[List[Dict[str, Any]], List[str], int]:
    """
    Parse a newline-delimited Recent Labs matrix.

    Format (each token on its own line):
        Recent Labs
        <blank>
        MM/DD/YY        ← date col 1
        HHMM            ← time col 1
        MM/DD/YY        ← date col 2
        HHMM            ← time col 2
        ...
        COMPONENT1      ← component name
        val1            ← value for col 1
        val2            ← value for col 2
        COMPONENT2
        val1
        val2
        ...
    """
    labs: List[Dict[str, Any]] = []
    warnings: List[str] = []
    j = start_idx + 1  # skip "Recent Labs"

    # Skip blanks and optional "Lab" token
    while j < len(lines):
        t = (lines[j].get("text") or "").strip()
        if t and t.upper() != "LAB":
            break
        j += 1

    if j >= len(lines):
        return labs, ["recent_labs_matrix_empty"], j

    # Phase 1: Collect datetime columns (date/time pairs)
    col_dts: List[Optional[str]] = []
    while j < len(lines):
        t = (lines[j].get("text") or "").strip()
        if not t:
            j += 1
            continue
        if _MATRIX_DATE_TOK_RE.match(t):
            date_s = t
            j += 1
            # Look for time on next line
            time_s = None
            if j < len(lines):
                t2 = (lines[j].get("text") or "").strip()
                if _MATRIX_TIME_TOK_RE.match(t2):
                    time_s = t2
                    j += 1
            iso, dt_w = _parse_date_opt_time(date_s, time_s)
            col_dts.append(iso)
            warnings.extend(dt_w)
        else:
            # Not a date — we've hit the component/data section
            break

    n_cols = len(col_dts)
    if n_cols == 0:
        warnings.append("recent_labs_matrix_no_datetime_columns")
        return labs, warnings, j

    # Phase 2: Parse component rows.
    # Pattern: COMPONENT_NAME followed by n_cols value lines.
    MAX_COMPONENTS = 100
    comp_count = 0
    while j < len(lines) and comp_count < MAX_COMPONENTS:
        t = (lines[j].get("text") or "").strip()

        # Skip blanks
        if not t:
            j += 1
            continue

        # End-of-block detection
        if t.startswith("[") and "NOTE" in t:
            break
        if re.match(r"^\s*[A-Z][A-Z \-/]{3,}:\s*$", t):
            break
        if t.lower().startswith(("impression", "plan:", "prophylaxis",
                                  "antibiotics", "objective", "assessment")):
            break
        if RECENT_LABS_HEADER_RE.match(t):
            break
        # Disclaimer lines
        if t.startswith("< >"):
            j += 1
            continue

        # Is this a component name?
        # A component token: uppercase letters/digits, 2-20 chars, and is
        # NOT a pure number or date or time.
        t_upper = t.upper()
        is_comp = (
            t_upper in _RECENT_LABS_COMPONENTS
            or (
                _MATRIX_COMPONENT_RE.match(t_upper)
                and not _MATRIX_DATE_TOK_RE.match(t)
                and not _MATRIX_TIME_TOK_RE.match(t)
                and not _MATRIX_VALUE_RE.match(t)
            )
        )

        if is_comp:
            comp_name = t_upper
            comp_line = j
            j += 1
            # Read n_cols value lines
            values_read = 0
            while values_read < n_cols and j < len(lines):
                vt = (lines[j].get("text") or "").strip()
                if not vt:
                    j += 1
                    continue
                # If we hit another component name or end marker, stop
                vt_upper = vt.upper()
                if vt_upper in _RECENT_LABS_COMPONENTS:
                    break
                if (
                    _MATRIX_COMPONENT_RE.match(vt_upper)
                    and not _MATRIX_DATE_TOK_RE.match(vt)
                    and not _MATRIX_TIME_TOK_RE.match(vt)
                    and not _MATRIX_VALUE_RE.match(vt)
                ):
                    break
                if vt.startswith("[") or RECENT_LABS_HEADER_RE.match(vt):
                    break

                val_raw, val_num, val_flags = _extract_matrix_value(vt)
                col_idx = values_read
                if col_idx < n_cols:
                    if val_raw != "" or val_num is not None:
                        labs.append({
                            "component": comp_name,
                            "observed_dt": col_dts[col_idx],
                            "value_raw": val_raw,
                            "value_num": val_num,
                            "unit": "",
                            "flags": val_flags,
                            "source_block_type": "recent_labs_matrix",
                            "source_line": j,
                        })
                values_read += 1
                j += 1
            comp_count += 1
        else:
            # Unknown line — might be end of block
            # If it looks like a value, skip (stray value)
            if _MATRIX_VALUE_RE.match(t):
                j += 1
                continue
            # Otherwise break out
            break

    return labs, warnings, j


def _parse_recent_labs_matrix(
    lines: List[Dict[str, Any]],
    start_idx: int,
) -> Tuple[List[Dict[str, Any]], List[str], int]:
    """
    Dispatch to the appropriate Recent Labs matrix parser variant.

    Tries tab-delimited first; if that returns no results
    (signals not-tab-delimited), falls back to newline-delimited.
    """
    # Try tab-delimited
    labs, warnings, j = _parse_recent_labs_matrix_tab(lines, start_idx)
    if labs or (j > start_idx + 2 and warnings):
        # Tab parser consumed something
        return labs, warnings, j

    # Fall back to newline-delimited
    return _parse_recent_labs_matrix_newline(lines, start_idx)


# ----------------------------------------------------------------
# Main extraction
# ----------------------------------------------------------------

def extract_labs_from_lines(lines, _all_lab_context=False):
    """
    Input:  list of evidence-ish dicts with at least 'text'
            and optional 'ts', 'item_type'.
    Output: (labs, warnings)

    _all_lab_context: when True every line is treated as being inside
    LAB context (caller already filtered to LAB-typed items).
    """
    warnings = []
    labs = []
    in_lab_section = _all_lab_context

    i = 0
    while i < len(lines):
        text = (lines[i].get("text") or "").rstrip("\n")
        ts = lines[i].get("ts")
        item_type = lines[i].get("item_type")
        stripped = text.strip()

        # -- track lab section context --
        if LAB_SECTION_RE.match(text):
            in_lab_section = True
        if re.match(r"^\s*\[(?!LAB)[A-Z_]+\]", text):
            in_lab_section = False

        # ============================================================
        # Priority 1: Strict "Lab Test Results" table
        # ============================================================
        if LAB_TABLE_HEADER_RE.match(text):
            j = i + 1
            while j < len(lines) and not (lines[j].get("text") or "").strip():
                j += 1
            if j < len(lines) and LAB_TABLE_COLS_RE.match(
                (lines[j].get("text") or "").strip()
            ):
                j += 1
                while j < len(lines):
                    row = (lines[j].get("text") or "").strip()
                    if not row:
                        break
                    if row.lower().startswith((
                        "tracking links", "order audit", "providers",
                        "pharmacy", "[physician_note]",
                    )):
                        break
                    m = LAB_TABLE_ROW_RE.match(row)
                    if m:
                        obs_iso = _parse_mmddyy_hhmm(
                            m.group("date"), m.group("time")
                        )
                        value_raw = m.group("value").strip()
                        labs.append({
                            "component": m.group("component").strip(),
                            "observed_dt": obs_iso,
                            "value_raw": value_raw,
                            "value_num": _to_float(value_raw),
                            "unit": _extract_unit_from_range(
                                m.group("range_unit").strip()
                            ),
                            "range_unit": m.group("range_unit").strip(),
                            "flags": [],
                            "status": m.group("status").strip(),
                            "source_block_type": "lab_table",
                            "source_line": j,
                        })
                    else:
                        labs.append({
                            "raw": row,
                            "source_block_type": "lab_table",
                            "source_line": j,
                            "warnings": ["unparsed_lab_row"],
                        })
                    j += 1
                i = j
                continue
            else:
                warnings.append("lab_table_header_found_but_columns_missing")
                i += 1
                continue

        # ============================================================
        # Priority 2: Tab-delimited lab table
        # ============================================================
        if TAB_TABLE_COLS_RE.match(text):
            j = i + 1
            while j < len(lines):
                row_text = (lines[j].get("text") or "").rstrip("\n")
                row_stripped = row_text.strip()

                if not row_stripped:
                    j += 1
                    continue

                if TAB_TABLE_COLS_RE.match(row_text):
                    j += 1
                    continue

                if row_stripped.lower().startswith("admission"):
                    j += 1
                    continue

                if row_text.startswith(" \t") or row_text.startswith("\t"):
                    j += 1
                    continue

                if "\t" not in row_text and not row_text.startswith(BULLET):
                    low = row_stripped.lower()
                    if (
                        low.startswith("impression")
                        or low.startswith("plan")
                        or row_stripped.startswith("[")
                    ):
                        break
                    j += 1
                    continue

                parsed = _parse_tab_row(row_text)
                if parsed:
                    value_clean, row_flags = _extract_value_and_flags(
                        parsed["value_raw_full"]
                    )
                    obs_iso, dt_warnings = _parse_date_opt_time(
                        parsed["date"]
                    )
                    unit = _extract_unit_from_range(parsed["range_unit"])
                    row_warnings = list(dt_warnings)
                    labs.append({
                        "component": parsed["component"],
                        "observed_dt": obs_iso,
                        "value_raw": value_clean,
                        "value_num": _to_float(value_clean),
                        "unit": unit,
                        "range_unit": parsed["range_unit"],
                        "flags": row_flags,
                        "status": parsed["status"],
                        "source_block_type": "tab_table",
                        "source_line": j,
                        **({"warnings": row_warnings} if row_warnings else {}),
                    })
                else:
                    if row_text.startswith(BULLET):
                        labs.append({
                            "raw": row_stripped,
                            "source_block_type": "tab_table",
                            "source_line": j,
                            "warnings": ["unparsed_lab_row"],
                        })
                j += 1
            i = j
            continue

        # ============================================================
        # Priority 5: Recent Labs matrix (full parser)
        # ============================================================
        if RECENT_LABS_HEADER_RE.match(text):
            matrix_labs, matrix_warnings, j = _parse_recent_labs_matrix(
                lines, i,
            )
            labs.extend(matrix_labs)
            all_warnings_ext = matrix_warnings
            warnings.extend(all_warnings_ext)
            i = j
            continue

        # ============================================================
        # Non-table line-by-line parsers (only within LAB context)
        # ============================================================
        line_is_lab_ctx = (
            in_lab_section or item_type == "LAB" or _all_lab_context
        )

        if line_is_lab_ctx and stripped:
            if _is_skip_line(stripped) or _is_order_line(stripped):
                i += 1
                continue

            # -- Relaxed table row (date + time + value) --
            m_rel = RELAXED_ROW_RE.match(stripped)
            if m_rel:
                comp = m_rel.group("component").strip()
                date_s = m_rel.group("date")
                time_s = m_rel.group("time")
                value_raw = m_rel.group("value").strip()
                tail = m_rel.group("tail") or ""
                obs_iso, dt_warnings = _parse_date_opt_time(date_s, time_s)
                unit, tail_flags = _extract_unit_and_flag_from_tail(tail)
                row_warnings = list(dt_warnings)
                labs.append({
                    "component": comp,
                    "observed_dt": obs_iso,
                    "value_raw": value_raw,
                    "value_num": _to_float(value_raw),
                    "unit": unit,
                    "flags": tail_flags,
                    "source_block_type": "relaxed_row",
                    "source_line": i,
                    **({"warnings": row_warnings} if row_warnings else {}),
                })
                i += 1
                continue

            # -- Single-line result --
            m_sl = SINGLE_LINE_RE.match(stripped)
            if m_sl:
                comp = m_sl.group("component").strip()
                value_raw = m_sl.group("value").strip()
                unit = (m_sl.group("unit") or "").strip()
                flag_raw = (m_sl.group("flag") or "").strip()
                sl_flags = [_normalize_flag(flag_raw)] if flag_raw else []
                obs_iso = ts if ts else None
                row_warnings_sl = []
                if not obs_iso:
                    row_warnings_sl.append("ts_missing")
                labs.append({
                    "component": comp,
                    "observed_dt": obs_iso,
                    "value_raw": value_raw,
                    "value_num": _to_float(value_raw),
                    "unit": unit,
                    "flags": sl_flags,
                    "source_block_type": "single_line",
                    "source_line": i,
                    **({"warnings": row_warnings_sl} if row_warnings_sl else {}),
                })
                i += 1
                continue

            # -- Unparsed lab-like line --
            if (
                re.match(r"[A-Za-z]", stripped)
                and re.search(r"\d", stripped)
                and len(stripped) > 3
            ):
                labs.append({
                    "raw": stripped,
                    "source_block_type": "lab_unparsed",
                    "source_line": i,
                    "warnings": ["unparsed_lab_line"],
                })

        i += 1

    return labs, warnings


# ----------------------------------------------------------------
# Daily aggregation
# ----------------------------------------------------------------

def compute_daily_latest_and_deltas(labs, day_iso):
    """
    Given all extracted labs, compute per-day latest for a single day.
    day_iso: 'YYYY-MM-DD'
    """
    by_component = {}
    for r in labs:
        obs = r.get("observed_dt")
        if not obs or not isinstance(obs, str) or not obs.startswith(day_iso):
            continue
        comp = (r.get("component") or "").strip()
        if not comp:
            continue
        by_component.setdefault(comp, []).append(r)

    latest = {}
    for comp, rows in by_component.items():
        rows_sorted = sorted(rows, key=lambda x: x.get("observed_dt") or "")
        latest[comp] = rows_sorted[-1]

    return {"latest": latest}


# Alias expected by build_patient_features_v1
compute_daily_latest = compute_daily_latest_and_deltas
