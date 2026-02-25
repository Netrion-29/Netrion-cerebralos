#!/usr/bin/env python3
"""
Urine Output Events v1 — Deterministic urine output event extraction.

Extracts explicit urine output events from two source types in the raw
Epic-format encounter export:

  **Source 1 — Flowsheet "Urine Documentation"**
  Tab-delimited table under ``Urine Documentation`` header in the
  Flowsheets section.  Each row has: timestamp, Urine ml, Urine
  Unmeasured Occurrence, Urine Color, Urine Appearance, Urine Odor,
  Urine Source (e.g. "Voided").

  **Source 2 — LDA Assessment Rows (columnar)**
  Within ``[REMOVED]`` or ``[ACTIVE]`` Urethral Catheter / External
  Urinary Catheter device sections, ``Assessments`` blocks contain a
  ``Row Name`` header with timestamps as columns, and ``Output (ml)``
  / ``Urine Color`` / ``Urine Appearance`` / ``Urine Odor`` rows.
  Only catheter device contexts are used (not feeding tubes).

  **Source 3 — LDA Assessment Rows (vertical / Format A)**
  Within LDA summary sections, per-device assessment rows with
  ``\\tMM/DD\\tHHMM\\t`` timestamps followed by key-value pairs
  including ``Output (ml)``, ``Urine Color``, etc.  Only extracted
  when the parent device is a urethral or external urinary catheter.

Output key: ``urine_output_events_v1``

Output schema::

    {
      "events": [
        {
          "ts": "<MM/DD HHMM>",
          "output_ml": <int | null>,
          "source_type": "flowsheet | lda_assessment",
          "source_subtype": "<string>",
          "urine_color": "<string | null>",
          "urine_appearance": "<string | null>",
          "urine_odor": "<string | null>",
          "evidence": [
            {
              "role": "urine_output_entry",
              "snippet": "<first 120 chars>",
              "raw_line_id": "<sha256>"
            }
          ]
        }, ...
      ],
      "urine_output_event_count": <int>,
      "total_urine_output_ml": <int>,
      "first_urine_output_ts": "<string | null>",
      "last_urine_output_ts": "<string | null>",
      "source_types_present": ["flowsheet", "lda_assessment"],
      "source_rule_id": "urine_output_events_raw_file | no_urine_output_data",
      "warnings": [],
      "notes": []
    }

Fail-closed behaviour:
  - No raw file path → events=[], source_rule_id="no_urine_output_data"
  - Raw file exists but no urine sections → same
  - Section found, 0 events → urine_output_event_count=0

Boundary notes:
  - Only explicit urine output values are extracted; no inference from
    device presence alone.
  - ``Output (ml)`` is only extracted from urethral catheter / external
    urinary catheter device contexts, NOT from feeding tubes/drains.
  - Dash-only values (``—``) and explicitly-zero ``0 ml`` values from
    non-urine devices are skipped.
  - Intra-operative urine data (anesthesia case metrics) is out of scope.

Design:
  - Deterministic, fail-closed.
  - No LLM, no ML, no clinical inference.
  - raw_line_id required on every evidence entry.
"""

from __future__ import annotations

import hashlib
import os
import re
from typing import Any, Dict, List, Optional, Tuple


# ── Constants ────────────────────────────────────────────────────────

# Urine-specific device prefixes (only extract Output (ml) from these)
_URINE_DEVICE_PREFIXES = (
    "Urethral Catheter",
    "External Urinary Catheter",
)

# Section boundary: major Epic sections that terminate scanning
RE_SECTION_BOUNDARY = re.compile(
    r"^(?:Notes|Flowsheets|Meds|Medications|Labs|Orders|"
    r"Imaging|Procedures|Vitals|Vital Signs|"
    r"Lines / Drains / Airways|"
    r"Patient Lines/Drains/Airways Status|"
    r"Visit Information|Encounter Information|"
    r"Home Medications|Problem List|"
    r"Stool Documentation)\s*$",
    re.IGNORECASE,
)

# ── Flowsheet "Urine Documentation" patterns ────────────────────────

RE_URINE_DOC_HEADER = re.compile(r"^Urine Documentation\s*$")

# Data row: MM/DD HHMM followed by tab-separated values
# e.g. "01/02 0830\t200 mL\t1\tYellow/Straw\tClear\tNo odor\tVoided"
RE_URINE_DOC_ROW = re.compile(
    r"^(\d{2}/\d{2})\s+(\d{4})\t(.*)$"
)

# ── LDA Assessment columnar patterns ────────────────────────────────

# Matches "[REMOVED] Urethral Catheter ..." or "[ACTIVE] Urethral Catheter ..."
# or just "Urethral Catheter ..." at the start of an LDA device block
RE_CATHETER_DEVICE_HEADER = re.compile(
    r"^\[(?:REMOVED|ACTIVE)\]\s*(?:" +
    "|".join(re.escape(p) for p in _URINE_DEVICE_PREFIXES) +
    r")",
    re.IGNORECASE,
)

# Row Name header line with timestamps
# e.g. "Row Name\t01/08/26 1646\t01/08/26 1500\t..."
RE_ROW_NAME_HEADER = re.compile(r"^Row Name\t(.+)$")

# Timestamp in Row Name header: MM/DD/YY HHMM
RE_ASSESS_TS_COL = re.compile(r"(\d{2}/\d{2}/\d{2})\s+(\d{4})")

# ── LDA Format A vertical assessment timestamp ──────────────────────
# e.g. "\t01/01\t0615\tUrine Color"
RE_VERT_ASSESS_TS = re.compile(r"^\t(\d{2}/\d{2})\t(\d{4})\t")

# ── Output value extraction ─────────────────────────────────────────
RE_ML_VALUE = re.compile(r"(\d+)\s*(?:mL|ml)")

# ── LDAs header (Format A summary) ─────────────────────────────────
RE_LDA_HEADER = re.compile(r"^LDAs\s*$")

# ── Device label in Format A LDA ────────────────────────────────────
RE_FORMAT_A_DEVICE_LABEL = re.compile(
    r"^(?P<label>(?:" +
    "|".join(re.escape(p) for p in _URINE_DEVICE_PREFIXES) +
    r").+?)(?:\s+\d+\s+assessments?|\s+Placed)\s*$"
)

# Also match pure label (no "assessments" or "Placed" suffix)
RE_FORMAT_A_DEVICE_LABEL_BARE = re.compile(
    r"^(?P<label>(?:" +
    "|".join(re.escape(p) for p in _URINE_DEVICE_PREFIXES) +
    r").+?)\s*$"
)


# ── Helpers ──────────────────────────────────────────────────────────

def _make_raw_line_id(line: str) -> str:
    """SHA-256 of the raw line text (stripped)."""
    return hashlib.sha256(line.strip().encode("utf-8")).hexdigest()


def _clean_value(val: str) -> Optional[str]:
    """Return cleaned string or None if empty/dash."""
    val = val.strip()
    if not val or val == "—" or val == "-":
        return None
    # Strip author initials: "Yellow/Straw   -MW" → "Yellow/Straw"
    val = re.sub(r"\s+-[A-Z]{1,3}\s*$", "", val).strip()
    if not val or val == "—" or val == "-":
        return None
    return val


def _extract_ml(val: str) -> Optional[int]:
    """Extract integer mL value from '200 mL', '200 ml', or bare '200'."""
    if val is None:
        return None
    cleaned = _clean_value(val)
    if cleaned is None:
        return None
    m = RE_ML_VALUE.search(cleaned)
    if m:
        return int(m.group(1))
    # Bare integer (common in LDA Format A vertical rows)
    if cleaned.isdigit():
        return int(cleaned)
    return None


def _strip_author(val: str) -> str:
    """Remove trailing author initials like '   -MW'."""
    return re.sub(r"\s+-[A-Z]{1,3}\s*$", "", val).strip()


# ── Source 1: Flowsheet Urine Documentation ──────────────────────────

def _extract_flowsheet_urine(
    filepath: str,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Parse the Flowsheet 'Urine Documentation' section.

    Returns (events, warnings).
    """
    events: List[Dict[str, Any]] = []
    warnings: List[str] = []

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except (OSError, IOError) as exc:
        warnings.append(f"Cannot read raw file: {exc}")
        return events, warnings

    in_urine_doc = False
    # Column headers (parsed from the header line)
    col_names: List[str] = []

    for line_idx, line in enumerate(lines):
        stripped = line.strip()

        # Detect Urine Documentation header
        if RE_URINE_DOC_HEADER.match(stripped):
            in_urine_doc = True
            col_names = []
            continue

        if in_urine_doc:
            # Header row with column names (starts with tab)
            if stripped and not col_names and line.startswith("\t"):
                col_names = [c.strip() for c in line.split("\t")]
                # First element is empty (leading tab), skip it
                if col_names and col_names[0] == "":
                    col_names = col_names[1:]
                continue

            # Data row: starts with MM/DD HHMM
            m_row = RE_URINE_DOC_ROW.match(stripped)
            if m_row:
                date_part = m_row.group(1)
                time_part = m_row.group(2)
                ts = f"{date_part} {time_part}"
                rest = m_row.group(3)

                # Split rest by tab
                vals = rest.split("\t")

                # Map to column names
                urine_ml_raw = vals[0].strip() if len(vals) > 0 else ""
                # col indices: 0=Urine ml, 1=Urine Unmeasured Occurrence,
                #              2=Urine Color, 3=Urine Appearance,
                #              4=Urine Odor, 5=Urine Source
                urine_color = _clean_value(vals[2]) if len(vals) > 2 else None
                urine_appearance = _clean_value(vals[3]) if len(vals) > 3 else None
                urine_odor = _clean_value(vals[4]) if len(vals) > 4 else None
                urine_source = _clean_value(vals[5]) if len(vals) > 5 else None

                output_ml = _extract_ml(urine_ml_raw)

                raw_line_id = _make_raw_line_id(line)

                event: Dict[str, Any] = {
                    "ts": ts,
                    "output_ml": output_ml,
                    "source_type": "flowsheet",
                    "source_subtype": urine_source or "Voided",
                    "urine_color": urine_color,
                    "urine_appearance": urine_appearance,
                    "urine_odor": urine_odor,
                    "evidence": [{
                        "role": "urine_output_entry",
                        "snippet": line.strip()[:120],
                        "raw_line_id": raw_line_id,
                    }],
                }
                events.append(event)
                continue

            # End of Urine Documentation section: blank line or new section
            if not stripped:
                # Could be blank line within section — check next line
                # But in practice, Urine Documentation ends at first
                # non-data/non-header line after header
                in_urine_doc = False
                continue

            # If it's a totally different section header, stop
            if RE_SECTION_BOUNDARY.match(stripped):
                in_urine_doc = False
                continue

            # Also stop if it looks like a new flowsheet subsection
            # (no tab-delimited timestamp at start)
            if not stripped.startswith("\t") and not RE_URINE_DOC_ROW.match(stripped):
                in_urine_doc = False
                continue

    return events, warnings


# ── Source 2: LDA Columnar Assessment Rows ───────────────────────────

def _extract_lda_columnar_urine(
    filepath: str,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Parse LDA columnar assessment blocks for urethral/external urinary
    catheter devices.  Finds [REMOVED] or [ACTIVE] catheter device
    headers, then scans for Assessments blocks with Row Name headers
    containing timestamps, and extracts Output (ml) / Urine Color /
    Urine Appearance / Urine Odor values per column.

    Returns (events, warnings).
    """
    events: List[Dict[str, Any]] = []
    warnings: List[str] = []

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except (OSError, IOError) as exc:
        warnings.append(f"Cannot read raw file: {exc}")
        return events, warnings

    in_catheter_device = False
    col_timestamps: List[Optional[str]] = []

    # Per-block accumulators
    urine_colors: List[Optional[str]] = []
    urine_appearances: List[Optional[str]] = []
    urine_odors: List[Optional[str]] = []
    output_mls: List[Optional[str]] = []
    raw_line_for_output: Optional[str] = None
    device_subtype = ""

    def _flush_block() -> None:
        """Emit events for the current assessment block."""
        nonlocal col_timestamps, urine_colors, urine_appearances
        nonlocal urine_odors, output_mls, raw_line_for_output

        if not col_timestamps:
            return

        # Pad lists to match column count
        n = len(col_timestamps)
        while len(urine_colors) < n:
            urine_colors.append(None)
        while len(urine_appearances) < n:
            urine_appearances.append(None)
        while len(urine_odors) < n:
            urine_odors.append(None)
        while len(output_mls) < n:
            output_mls.append(None)

        for i, ts in enumerate(col_timestamps):
            if ts is None:
                continue

            ml_val = _extract_ml(output_mls[i]) if output_mls[i] else None
            color_val = _clean_value(urine_colors[i]) if urine_colors[i] else None
            app_val = _clean_value(urine_appearances[i]) if urine_appearances[i] else None
            odor_val = _clean_value(urine_odors[i]) if urine_odors[i] else None

            # Only emit events that have at least one meaningful urine field
            if ml_val is None and color_val is None and app_val is None and odor_val is None:
                continue

            # Skip 0 ml entries that have no other urine characteristics
            if ml_val == 0 and color_val is None and app_val is None and odor_val is None:
                continue

            snippet = f"Output (ml) {output_mls[i] or '—'} at {ts}" if raw_line_for_output else f"Urine data at {ts}"
            raw_id = _make_raw_line_id(raw_line_for_output or f"lda_col_{ts}")

            event: Dict[str, Any] = {
                "ts": ts,
                "output_ml": ml_val,
                "source_type": "lda_assessment",
                "source_subtype": device_subtype,
                "urine_color": color_val,
                "urine_appearance": app_val,
                "urine_odor": odor_val,
                "evidence": [{
                    "role": "urine_output_entry",
                    "snippet": snippet[:120],
                    "raw_line_id": raw_id,
                }],
            }
            events.append(event)

        # Reset accumulators
        col_timestamps = []
        urine_colors = []
        urine_appearances = []
        urine_odors = []
        output_mls = []
        raw_line_for_output = None

    for line_idx, line in enumerate(lines):
        stripped = line.strip()

        # Detect catheter device header
        if RE_CATHETER_DEVICE_HEADER.match(stripped):
            _flush_block()
            in_catheter_device = True
            # Determine subtype
            for prefix in _URINE_DEVICE_PREFIXES:
                if prefix.lower() in stripped.lower():
                    device_subtype = prefix
                    break
            col_timestamps = []
            continue

        # Exit catheter context on certain boundaries
        if in_catheter_device:
            # Another device or User Key section ends the catheter block
            if stripped.startswith("[REMOVED]") or stripped.startswith("[ACTIVE]"):
                if not RE_CATHETER_DEVICE_HEADER.match(stripped):
                    _flush_block()
                    in_catheter_device = False
                    continue
                else:
                    # New catheter device
                    _flush_block()
                    for prefix in _URINE_DEVICE_PREFIXES:
                        if prefix.lower() in stripped.lower():
                            device_subtype = prefix
                            break
                    col_timestamps = []
                    continue

            if stripped.startswith("User Key"):
                _flush_block()
                in_catheter_device = False
                continue

            # Row Name header — start new assessment block
            m_rn = RE_ROW_NAME_HEADER.match(stripped)
            if m_rn:
                _flush_block()
                header_rest = m_rn.group(1)
                # Parse timestamps from the header
                ts_parts = header_rest.split("\t")
                col_timestamps = []
                for tp in ts_parts:
                    tp = tp.strip()
                    m_ts = RE_ASSESS_TS_COL.match(tp)
                    if m_ts:
                        # Convert MM/DD/YY HHMM → MM/DD HHMM (drop year for
                        # consistency with flowsheet timestamps)
                        date_part = m_ts.group(1)[:5]  # MM/DD from MM/DD/YY
                        time_part = m_ts.group(2)
                        col_timestamps.append(f"{date_part} {time_part}")
                    else:
                        col_timestamps.append(None)
                # Reset field accumulators
                urine_colors = []
                urine_appearances = []
                urine_odors = []
                output_mls = []
                raw_line_for_output = None
                continue

            # Field rows
            if col_timestamps and "\t" in line:
                parts = stripped.split("\t")
                if len(parts) < 2:
                    continue
                field_name = parts[0].strip()
                field_vals = parts[1:]

                if field_name == "Output (ml)":
                    output_mls = [v.strip() for v in field_vals]
                    raw_line_for_output = line
                elif field_name == "Urine Color":
                    urine_colors = [v.strip() for v in field_vals]
                elif field_name == "Urine Appearance":
                    urine_appearances = [v.strip() for v in field_vals]
                elif field_name == "Urine Odor":
                    urine_odors = [v.strip() for v in field_vals]
                continue

    # Flush any remaining block
    _flush_block()

    return events, warnings


# ── Source 3: LDA Format A Vertical Assessment Rows ──────────────────

def _extract_lda_vertical_urine(
    filepath: str,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Parse LDA Format A (summary) sections for urine output data in
    vertical assessment rows attached to urethral/external urinary
    catheter devices.

    Vertical assessment format:
        \\tMM/DD\\tHHMM\\t<field_name>
        <field_value>
        <field_name>
        <field_value>
        ...
        \\tMM/DD\\tHHMM\\t...  (next assessment)

    Returns (events, warnings).
    """
    events: List[Dict[str, Any]] = []
    warnings: List[str] = []

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except (OSError, IOError) as exc:
        warnings.append(f"Cannot read raw file: {exc}")
        return events, warnings

    in_lda_section = False
    in_urine_device = False
    current_ts: Optional[str] = None
    current_output_ml: Optional[int] = None
    current_color: Optional[str] = None
    current_appearance: Optional[str] = None
    current_odor: Optional[str] = None
    current_first_line: Optional[str] = None
    pending_field: Optional[str] = None  # "Output (ml)", "Urine Color", etc.
    device_subtype = ""

    def _flush_event() -> None:
        nonlocal current_ts, current_output_ml, current_color
        nonlocal current_appearance, current_odor, current_first_line

        if current_ts is None:
            return

        # Only emit if there's at least one meaningful urine field
        if (current_output_ml is None and current_color is None
                and current_appearance is None and current_odor is None):
            current_ts = None
            current_output_ml = None
            current_color = None
            current_appearance = None
            current_odor = None
            current_first_line = None
            return

        raw_id = _make_raw_line_id(current_first_line or f"vert_{current_ts}")

        event: Dict[str, Any] = {
            "ts": current_ts,
            "output_ml": current_output_ml,
            "source_type": "lda_assessment",
            "source_subtype": device_subtype,
            "urine_color": current_color,
            "urine_appearance": current_appearance,
            "urine_odor": current_odor,
            "evidence": [{
                "role": "urine_output_entry",
                "snippet": (current_first_line or "").strip()[:120],
                "raw_line_id": raw_id,
            }],
        }
        events.append(event)

        current_ts = None
        current_output_ml = None
        current_color = None
        current_appearance = None
        current_odor = None
        current_first_line = None

    for line_idx, line in enumerate(lines):
        stripped = line.strip()

        # Detect LDAs header (Format A)
        if RE_LDA_HEADER.match(stripped):
            in_lda_section = True
            in_urine_device = False
            continue

        if not in_lda_section:
            continue

        # Section boundary exits LDA
        if RE_SECTION_BOUNDARY.match(stripped) and not RE_LDA_HEADER.match(stripped):
            _flush_event()
            in_lda_section = False
            in_urine_device = False
            continue

        # Detect urine device label in Format A
        # e.g. "Urethral Catheter 16 fr Anchored\t\t\tPlaced"
        # or "Urethral Catheter 16 fr Anchored\t\t\t23 assessments"
        m_dev = RE_FORMAT_A_DEVICE_LABEL.match(stripped)
        if not m_dev:
            m_dev = RE_FORMAT_A_DEVICE_LABEL_BARE.match(stripped)
        if m_dev:
            _flush_event()
            in_urine_device = True
            for prefix in _URINE_DEVICE_PREFIXES:
                if stripped.startswith(prefix):
                    device_subtype = prefix
                    break
            pending_field = None
            continue

        # Non-urine device label → exit urine context
        # Detect other device types that start Format A blocks
        if (not in_urine_device and stripped and
                not stripped.startswith("\t") and
                re.match(r"^(?:Peripheral IV|PICC|Arterial Line|Central Line|"
                         r"Chest Tube|Surgical Airway|Continuous Nerve Block|"
                         r"G-tube|J-tube|Feeding Tube|Wound|JP Drain|"
                         r"Surgical Drain)", stripped)):
            _flush_event()
            in_urine_device = False
            pending_field = None
            continue

        if in_urine_device and stripped and not stripped.startswith("\t"):
            # Check if this is a non-urine device starting
            if re.match(r"^(?:Peripheral IV|PICC|Arterial Line|Central Line|"
                        r"Chest Tube|Surgical Airway|Continuous Nerve Block|"
                        r"G-tube|J-tube|Feeding Tube|Wound|JP Drain|"
                        r"Surgical Drain)", stripped):
                _flush_event()
                in_urine_device = False
                pending_field = None
                continue

            # Category line (PIV Line, Drain, ... comma-separated types)
            if re.match(r"^(?:PIV Line|Drain|Wound|Line|Airway)", stripped) and "," in stripped:
                # Could be the start of a new device category
                _flush_event()
                in_urine_device = False
                pending_field = None
                continue

        if not in_urine_device:
            continue

        # Assessment timestamp line: \tMM/DD\tHHMM\t<optional field>
        m_ts = RE_VERT_ASSESS_TS.match(line)
        if m_ts:
            _flush_event()
            date_part = m_ts.group(1)
            time_part = m_ts.group(2)
            current_ts = f"{date_part} {time_part}"
            current_first_line = line
            pending_field = None

            # Check if there's a field name on the same line
            remainder = line[m_ts.end():].strip()
            if remainder:
                if remainder == "Output (ml)":
                    pending_field = "output_ml"
                elif remainder == "Urine Color":
                    pending_field = "urine_color"
                elif remainder == "Urine Appearance":
                    pending_field = "urine_appearance"
                elif remainder == "Urine Odor":
                    pending_field = "urine_odor"
                elif remainder.startswith("Site Assessment") or remainder.startswith("Catheter day"):
                    pending_field = None  # skip non-urine fields
                elif remainder.startswith("Present on Discharge"):
                    pending_field = None
                else:
                    pending_field = None
            continue

        if current_ts is None:
            continue

        # Handle pending field value
        if pending_field is not None and stripped:
            if pending_field == "output_ml":
                current_output_ml = _extract_ml(stripped)
            elif pending_field == "urine_color":
                current_color = _clean_value(stripped)
            elif pending_field == "urine_appearance":
                current_appearance = _clean_value(stripped)
            elif pending_field == "urine_odor":
                current_odor = _clean_value(stripped)
            pending_field = None
            continue

        # Field name on its own line (value on next)
        if stripped == "Output (ml)":
            pending_field = "output_ml"
            continue
        elif stripped == "Urine Color":
            pending_field = "urine_color"
            continue
        elif stripped == "Urine Appearance":
            pending_field = "urine_appearance"
            continue
        elif stripped == "Urine Odor":
            pending_field = "urine_odor"
            continue
        elif stripped in ("Placed", "Removed", "Duration",
                          "Present on Discharge", "Assessments",
                          "Assessment Complete", "Site Assessment",
                          "Catheter day", "Collection Container",
                          "Securement Device Care", "Criteria to Continue Met",
                          "Inserted By::", "Witnessed by::"):
            # Known non-value fields — skip value on next line
            pending_field = None
            continue

    # Flush any remaining event
    _flush_event()

    return events, warnings


# ── Deduplication ────────────────────────────────────────────────────

def _deduplicate_events(events: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
    """
    Remove duplicate urine events.

    **Phase 1 — same-source dedup**: exact ``(ts, output_ml, source_type)``
    tuple; first occurrence kept.

    **Phase 2 — cross-source dedup**: when the same timestamp has events
    from both ``flowsheet`` and ``lda_assessment``, and one reports 0/null
    mL while the other reports a positive value, prefer the event with the
    non-zero mL value.  This handles the common pattern where the
    flowsheet records a "Voided" 0 mL row at the same time a catheter
    actually measured output.

    Returns ``(deduped_events, cross_source_drops)``.
    """
    # ── Phase 1: same-source dedup ──────────────────────────────
    seen: set = set()
    phase1: List[Dict[str, Any]] = []
    for ev in events:
        key = (ev["ts"], ev.get("output_ml"), ev["source_type"])
        if key in seen:
            continue
        seen.add(key)
        phase1.append(ev)

    # ── Phase 2: cross-source dedup ─────────────────────────────
    # Group by timestamp
    from collections import defaultdict
    ts_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for ev in phase1:
        ts_groups[ev["ts"]].append(ev)

    deduped: List[Dict[str, Any]] = []
    cross_drops = 0

    for ts, group in ts_groups.items():
        if len(group) == 1:
            deduped.append(group[0])
            continue

        # Check for cross-source collision (different source_type at same ts)
        source_types = set(ev["source_type"] for ev in group)
        if len(source_types) < 2:
            # Same source type — keep all (already deduped by phase 1)
            deduped.extend(group)
            continue

        # Cross-source collision: separate by source
        positives = [ev for ev in group if ev.get("output_ml") and ev["output_ml"] > 0]
        zeros = [ev for ev in group if not ev.get("output_ml") or ev["output_ml"] == 0]

        if positives and zeros:
            # Keep the positive-ml events; drop zero/null events
            deduped.extend(positives)
            cross_drops += len(zeros)
        else:
            # No clear winner — keep all
            deduped.extend(group)

    return deduped, cross_drops


# ── Public API ───────────────────────────────────────────────────────

def extract_urine_output_events(
    pat_features: Dict[str, Any],
    days_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Extract explicit urine output events from the raw source file.

    Parameters
    ----------
    pat_features : dict
        Partial feature dict (unused — kept for API consistency).
    days_data : dict
        Full days JSON containing ``meta.source_file``.

    Returns
    -------
    dict
        ``urine_output_events_v1`` schema.
    """
    result: Dict[str, Any] = {
        "events": [],
        "urine_output_event_count": 0,
        "total_urine_output_ml": 0,
        "first_urine_output_ts": None,
        "last_urine_output_ts": None,
        "source_types_present": [],
        "source_rule_id": "no_urine_output_data",
        "warnings": [],
        "notes": [],
    }

    # Get raw source file path
    source_file = days_data.get("meta", {}).get("source_file")
    if not source_file or not os.path.isfile(source_file):
        result["notes"].append("No raw source file available")
        return result

    all_events: List[Dict[str, Any]] = []
    all_warnings: List[str] = []

    # Source 1: Flowsheet Urine Documentation
    fs_events, fs_warns = _extract_flowsheet_urine(source_file)
    all_events.extend(fs_events)
    all_warnings.extend(fs_warns)

    # Source 2: LDA Columnar Assessments
    col_events, col_warns = _extract_lda_columnar_urine(source_file)
    all_events.extend(col_events)
    all_warnings.extend(col_warns)

    # Source 3: LDA Format A Vertical Assessments
    vert_events, vert_warns = _extract_lda_vertical_urine(source_file)
    all_events.extend(vert_events)
    all_warnings.extend(vert_warns)

    # Deduplicate
    all_events, cross_source_drops = _deduplicate_events(all_events)

    # Sort by timestamp (chronological)
    all_events.sort(key=lambda e: e["ts"])

    # Compute summary fields
    source_types = sorted(set(e["source_type"] for e in all_events))
    total_ml = sum(e["output_ml"] for e in all_events if e["output_ml"] is not None)
    first_ts = all_events[0]["ts"] if all_events else None
    last_ts = all_events[-1]["ts"] if all_events else None

    result["events"] = all_events
    result["urine_output_event_count"] = len(all_events)
    result["total_urine_output_ml"] = total_ml
    result["first_urine_output_ts"] = first_ts
    result["last_urine_output_ts"] = last_ts
    result["source_types_present"] = source_types
    result["warnings"] = all_warnings

    if all_events:
        result["source_rule_id"] = "urine_output_events_raw_file"

        # Build notes
        source_notes: List[str] = []
        fs_count = sum(1 for e in all_events if e["source_type"] == "flowsheet")
        lda_count = sum(1 for e in all_events if e["source_type"] == "lda_assessment")
        if fs_count:
            source_notes.append(f"flowsheet={fs_count}")
        if lda_count:
            source_notes.append(f"lda_assessment={lda_count}")
        result["notes"].append(f"source_breakdown: {', '.join(source_notes)}")

        # Subtypes present
        subtypes = sorted(set(e.get("source_subtype", "") for e in all_events if e.get("source_subtype")))
        if subtypes:
            result["notes"].append(f"subtypes: {', '.join(subtypes)}")

        if cross_source_drops:
            result["notes"].append(
                f"cross_source_duplicates_dropped: {cross_source_drops}"
            )
    else:
        result["notes"].append("No explicit urine output data found in raw file")

    return result
