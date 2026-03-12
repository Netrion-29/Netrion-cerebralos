#!/usr/bin/env python3
"""
Patient Movement v1 — Structured Patient-Movement Event-Log Extraction.

Deterministic extraction of the **Patient Movement** subsection from the
Epic-format encounter event log.  This captures every unit transfer,
admission, and discharge event recorded during the encounter, with
location details, level of care, service, providers, and disposition.

Complementary to ``adt_transfer_timeline_v1`` which extracts the ADT
Events header table.  Patient Movement provides richer per-event fields
(room, bed, level of care, providers, discharge disposition) from a
different section of the raw data.

v2 refinements (tier1/patient-movement-v2):
  - Deterministic dedup on (unit, date_raw, time_raw, event_type).
  - Additional section boundaries for robustness.
  - Medication-line guard to prevent false-match entry headers.
  - Enriched summary: admission_ts, discharge_disposition_final,
    event_type_counts, rooms_visited.
  - Handles "Checked Out" / "Checked In" bare entries (no body fields).

Source priority:
  1. Raw data file (``meta.source_file`` injected by the builder from
     the evidence JSON).
  2. Fail-closed when no raw file path or no Patient Movement subsection
     found.

Patient Movement subsection format (tab-delimited header + field blocks):

::

    Patient Movement              <CR>
    <UnitName>\\t<MM/DD>\\t<HHMM>\\t<EventType>
    <blank>
    Room
    <room_value>
    <blank>
    Bed
    <bed_value>
    <blank>
    Patient Class
    <class_value>
    <blank>
    Level of Care           (optional — may be absent)
    <loc_value>
    <blank>
    Service
    <service_value>
    <blank>
    [Admitting|Attending|Discharge] Provider   (optional, multiple)
    <provider_name>
    <blank>
    Discharge Disposition   (optional — only on Discharge events)
    <disposition_value>

Event types observed in real data:
  - Admission
  - Transfer In
  - Discharge
  - Checked In   (bare entry — no body fields)
  - Checked Out  (bare entry — no body fields)

Entries appear in reverse chronological order (most recent first).
Section ends when a line matches another event-log section header
(Notes, LDAs, Flowsheets, Meds, Labs, Imaging, etc.) or end of file.

Output key: ``patient_movement_v1``

Output schema::

    {
      "entries": [
        {
          "unit": "Ortho Neuro Trauma Care Center",
          "date_raw": "01/02",
          "time_raw": "1803",
          "event_type": "Discharge",
          "room": "4637",
          "bed": "4637-01",
          "patient_class": "Inpatient",
          "level_of_care": "Med/Surg" | null,
          "service": "General Medical" | null,
          "providers": {"discharge": "Iglesias, Roberto"} | {},
          "discharge_disposition": "Home" | null,
          "raw_line_id": "<sha256>"
        }, ...
      ],
      "summary": {
        "movement_event_count": <int>,
        "first_movement_ts": "MM/DD HHMM" | null,
        "discharge_ts": "MM/DD HHMM" | null,
        "transfer_count": <int>,
        "units_visited": ["...", ...],
        "levels_of_care": ["...", ...],
        "services_seen": ["...", ...]
      },
      "evidence": [
        {
          "role": "patient_movement_entry",
          "snippet": "<first 120 chars>",
          "raw_line_id": "<sha256>"
        }, ...
      ],
      "source_file": "<path>" | null,
      "source_rule_id": "patient_movement_raw_file" | "no_patient_movement_section",
      "warnings": [ ... ],
      "notes": [ ... ]
    }

Fail-closed behaviour:
  - No raw file path → entries=[], source_rule_id="no_patient_movement_section"
  - Raw file exists but no Patient Movement subsection → same
  - No entries extracted → movement_event_count=0

Design:
- Deterministic, fail-closed.
- No LLM, no ML, no clinical inference.
- raw_line_id required on every evidence entry.
- Dedup on (unit, date_raw, time_raw, event_type) — first occurrence wins.
"""

from __future__ import annotations

import hashlib
import os
import re
from typing import Any, Dict, List, Optional, Tuple

_DNA = "DATA NOT AVAILABLE"

# ── Discharge disposition normalization ───────────────────────────
# Maps raw values (case-insensitive) to canonical disposition strings.
_DISPOSITION_NORM: Dict[str, str] = {
    "home": "Home",
    "home health": "Home Health",
    "home health care": "Home Health",
    "skilled nursing facility": "SNF",
    "snf": "SNF",
    "rehab-inpt": "Rehab",
    "rehab": "Rehab",
    "acute rehab": "Rehab",
    "long term hospital": "LTAC",
    "ltac": "LTAC",
    "swing bed": "Swing Bed",
    "expired": "Expired",
    "deceased": "Expired",
}


def _normalize_disposition(raw: Optional[str]) -> Optional[str]:
    """Normalize a raw disposition string to its canonical form."""
    if not raw:
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    return _DISPOSITION_NORM.get(cleaned.lower(), cleaned)


# ── Discharge disposition fallback patterns ───────────────────────
# For patients without a structured "Discharge Disposition" in the
# Patient Movement section, scan the raw file for these patterns.

# "9. Disposition: Discharged to home."
_RE_NUMBERED_DISPO = re.compile(
    r"^\s*9\.\s*Disposition:\s*Discharged\s+to\s+(.+?)\.?\s*$",
    re.IGNORECASE,
)

# "Discharge Plan: SNF"
_RE_DISCHARGE_PLAN = re.compile(
    r"^\s*Discharge\s+Plan:\s*(.+?)\s*$",
    re.IGNORECASE,
)

# "Discharge Disposition: Home"  (outside the Patient Movement block)
_RE_DISCHARGE_DISPO_LINE = re.compile(
    r"^\s*Discharge\s+Disposition:\s*(.+?)\s*$",
    re.IGNORECASE,
)

# Values that indicate an interim/uncertain disposition — skip these.
_DISPO_EXCLUDE = re.compile(
    r"defer|pending|per\s+trauma|per\s+\w+\s+team|"
    r"to\s+be\s+determined|likely|possible|probably|if\s|when\s|consider",
    re.IGNORECASE,
)


def _scan_raw_disposition_fallback(source_file: str) -> Optional[str]:
    """
    Scan the raw patient file for discharge disposition patterns
    outside the Patient Movement structured table.

    Returns the LAST canonical match (most recent/final disposition)
    or None.
    """
    if not source_file or not os.path.isfile(source_file):
        return None
    try:
        with open(source_file, encoding="utf-8", errors="replace") as f:
            raw_lines = f.readlines()
    except OSError:
        return None

    last_dispo: Optional[str] = None
    for line in raw_lines:
        stripped = line.strip()
        if not stripped:
            continue
        # Try "Discharge Disposition:" field first
        m = _RE_DISCHARGE_DISPO_LINE.match(stripped)
        if m:
            val = m.group(1).strip()
            if val and not _DISPO_EXCLUDE.search(val):
                normed = _normalize_disposition(val)
                if normed:
                    last_dispo = normed
            continue
        # Try "9. Disposition: Discharged to <value>."
        m = _RE_NUMBERED_DISPO.match(stripped)
        if m:
            val = m.group(1).strip()
            if val and not _DISPO_EXCLUDE.search(val):
                normed = _normalize_disposition(val)
                if normed:
                    last_dispo = normed
            continue
        # Try "Discharge Plan:" (lower priority, but valid)
        m = _RE_DISCHARGE_PLAN.match(stripped)
        if m:
            val = m.group(1).strip()
            if val and not _DISPO_EXCLUDE.search(val):
                normed = _normalize_disposition(val)
                if normed:
                    last_dispo = normed
    return last_dispo

# ── Patient Movement section header pattern ────────────────────────
# Epic export format: "Patient Movement" followed by whitespace/tabs
RE_PM_HEADER = re.compile(r"^Patient Movement\s*$")

# ── Section boundary headers (end of Patient Movement section) ─────
_SECTION_BOUNDARIES = frozenset({
    "Notes",
    "LDAs",
    "Flowsheets",
    "Meds",
    "Labs",
    "Imaging",
    "Imaging, EKG, and Radiology",
    "Scheduled",
    "Procedures",
    "Orders",
    "Vitals",
    "Allergies",
    "Consults",
    "Results",
    "Micro",
    "I&O",
    "ADT Events",
})

RE_SECTION_BOUNDARY = re.compile(
    r"^(?:Notes|LDAs|Flowsheets|Meds|Labs|Scheduled|"
    r"Procedures|Orders|Vitals|Allergies|Consults|Results|Micro|"
    r"I\s*&\s*O|ADT\s*Events|"
    r"Imaging(?:,\s*EKG,?\s*and\s*Radiology)?)\s*$",
    re.IGNORECASE,
)

# ── Additional boundary: lab data lines ────────────────────────────
# Lines starting with a date in MM/DD/YY HH:MM format indicate we've
# left the Patient Movement section and entered labs/imaging data.
RE_LAB_LINE = re.compile(r"^\d{2}/\d{2}/\d{2}\s+\d{2}:\d{2}")

# ── Medication-line guard ─────────────────────────────────────────
# After a "Scheduled" boundary, medication lines use the same
# tab-delimited format as entry headers.  This pattern detects
# medication names (contain dosage units or parenthesised brand names)
# so we can reject false-match entry-header hits.
RE_MEDICATION_LINE = re.compile(
    r"\b(?:tablet|capsule|bottle|injection|solution|suspension|"
    r"patch|cream|ointment|suppository|inhaler|spray|vial|syringe|"
    r"mg|mcg|mL|units?\b|%\s)",
    re.IGNORECASE,
)

# ── Entry header pattern (tab-delimited) ──────────────────────────
# Format: UnitName\tMM/DD\tHHMM\tEventType
# The unit name can contain letters, numbers, spaces, dashes, ampersands
# The date/time/event are tab-separated
RE_ENTRY_HEADER = re.compile(
    r"^(?P<unit>.+?)"
    r"\t"
    r"(?P<date>\d{2}/\d{2})"
    r"\s+"
    r"(?P<time>\d{4})"
    r"\s+"
    r"(?P<event>.+?)"
    r"\s*$"
)

# ── Field labels (key lines) ──────────────────────────────────────
_FIELD_KEYS = frozenset({
    "Room",
    "Bed",
    "Patient Class",
    "Level of Care",
    "Service",
    "Admitting Provider",
    "Attending Provider",
    "Discharge Provider",
    "Discharge Disposition",
})

# Provider field names → provider role key
_PROVIDER_FIELDS = {
    "Admitting Provider": "admitting",
    "Attending Provider": "attending",
    "Discharge Provider": "discharge",
}


def _make_raw_line_id(text: str) -> str:
    """Deterministic SHA-256 hash of the raw line text."""
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _extract_pm_section_lines(filepath: str) -> Optional[List[Tuple[int, str]]]:
    """
    Read the raw data file and extract lines belonging to the
    Patient Movement event-log subsection.

    Returns a list of (line_number, line_text) tuples, or None if
    no Patient Movement section is found.

    line_number is 1-based.
    """
    if not filepath or not os.path.isfile(filepath):
        return None

    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
    except OSError:
        return None

    # Find the Patient Movement section header
    pm_start = None
    for i, line in enumerate(all_lines):
        stripped = line.strip().replace("\r", "")
        if RE_PM_HEADER.match(stripped):
            pm_start = i
            break

    if pm_start is None:
        return None

    # Find the end of the Patient Movement section
    pm_end = len(all_lines)
    for i in range(pm_start + 1, len(all_lines)):
        stripped = all_lines[i].strip().replace("\r", "")
        if stripped in _SECTION_BOUNDARIES or RE_SECTION_BOUNDARY.match(stripped):
            pm_end = i
            break
        # Also stop at lab-data lines (MM/DD/YY HH:MM ...)
        if RE_LAB_LINE.match(stripped):
            pm_end = i
            break

    # Collect lines (skip the header line itself)
    result: List[Tuple[int, str]] = []
    for i in range(pm_start + 1, pm_end):
        result.append((i + 1, all_lines[i]))  # 1-based line number

    return result


def _parse_movement_entries(
    section_lines: List[Tuple[int, str]],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Parse patient movement entries from the section lines.

    Returns (entries, warnings).

    Each entry dict:
      {
        "unit": str,
        "date_raw": "MM/DD",
        "time_raw": "HHMM",
        "event_type": str,
        "room": str | None,
        "bed": str | None,
        "patient_class": str | None,
        "level_of_care": str | None,
        "service": str | None,
        "providers": {role: name, ...},
        "discharge_disposition": str | None,
        "raw_line_id": str,
        "line_number": int,
      }
    """
    entries: List[Dict[str, Any]] = []
    warnings: List[str] = []

    # First pass: identify all entry header line indices
    header_indices: List[int] = []
    for idx, (line_num, line_text) in enumerate(section_lines):
        stripped = line_text.strip().replace("\r", "")
        m = RE_ENTRY_HEADER.match(stripped)
        if m:
            # Guard: reject lines that look like medication entries
            # (contain dosage units or pharma brand-name parentheses).
            if RE_MEDICATION_LINE.search(stripped):
                continue
            header_indices.append(idx)

    # Parse each entry: header + field block until next header
    for pos, hdr_idx in enumerate(header_indices):
        line_num, line_text = section_lines[hdr_idx]
        stripped = line_text.strip().replace("\r", "")
        m = RE_ENTRY_HEADER.match(stripped)
        if not m:
            continue  # safety

        unit = m.group("unit").strip()
        date_raw = m.group("date")
        time_raw = m.group("time")
        event_type = m.group("event").strip()
        raw_line_id = _make_raw_line_id(line_text.rstrip("\n\r"))

        # Determine field block range: after header until next header or end
        block_start = hdr_idx + 1
        block_end = header_indices[pos + 1] if pos + 1 < len(header_indices) else len(section_lines)

        # Parse field key/value pairs
        room: Optional[str] = None
        bed: Optional[str] = None
        patient_class: Optional[str] = None
        level_of_care: Optional[str] = None
        service: Optional[str] = None
        providers: Dict[str, str] = {}
        discharge_disposition: Optional[str] = None

        bi = block_start
        while bi < block_end:
            _, bline = section_lines[bi]
            bstripped = bline.strip().replace("\r", "")

            if not bstripped:
                bi += 1
                continue

            # Check if this line is a known field key
            if bstripped in _FIELD_KEYS:
                field_key = bstripped
                # Next non-blank line is the value
                vi = bi + 1
                field_value = None
                while vi < block_end:
                    _, vline = section_lines[vi]
                    vstripped = vline.strip().replace("\r", "")
                    if vstripped:
                        field_value = vstripped
                        break
                    vi += 1

                if field_value is not None:
                    if field_key == "Room":
                        room = field_value
                    elif field_key == "Bed":
                        bed = field_value
                    elif field_key == "Patient Class":
                        patient_class = field_value
                    elif field_key == "Level of Care":
                        level_of_care = field_value
                    elif field_key == "Service":
                        service = field_value
                    elif field_key in _PROVIDER_FIELDS:
                        providers[_PROVIDER_FIELDS[field_key]] = field_value
                    elif field_key == "Discharge Disposition":
                        discharge_disposition = field_value

                    bi = vi + 1
                    continue

            bi += 1

        entries.append({
            "unit": unit,
            "date_raw": date_raw,
            "time_raw": time_raw,
            "event_type": event_type,
            "room": room,
            "bed": bed,
            "patient_class": patient_class,
            "level_of_care": level_of_care,
            "service": service,
            "providers": providers,
            "discharge_disposition": discharge_disposition,
            "raw_line_id": raw_line_id,
            "line_number": line_num,
        })

    # ── Deterministic dedup on (unit, date_raw, time_raw, event_type) ──
    # Keep first occurrence; warn on duplicates.
    seen: set = set()
    deduped: List[Dict[str, Any]] = []
    dup_count = 0
    for e in entries:
        key = (e["unit"], e["date_raw"], e["time_raw"], e["event_type"])
        if key in seen:
            dup_count += 1
            continue
        seen.add(key)
        deduped.append(e)
    if dup_count:
        warnings.append(f"dedup_removed={dup_count}")
    entries = deduped

    return entries, warnings


def _build_summary(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build summary statistics from parsed movement entries."""
    if not entries:
        return {
            "movement_event_count": 0,
            "first_movement_ts": None,
            "admission_ts": None,
            "discharge_ts": None,
            "discharge_disposition_final": None,
            "transfer_count": 0,
            "units_visited": [],
            "levels_of_care": [],
            "services_seen": [],
            "rooms_visited": [],
            "event_type_counts": {},
        }

    units: List[str] = []
    rooms: List[str] = []
    levels: set = set()
    services: set = set()
    transfer_count = 0
    first_ts: Optional[str] = None
    admission_ts: Optional[str] = None
    discharge_ts: Optional[str] = None
    discharge_disposition_final: Optional[str] = None
    event_type_counts: Dict[str, int] = {}

    # Entries are in reverse chronological order (most recent first)
    # So "first" movement is the last entry, "latest discharge" is the
    # first Discharge entry
    for e in entries:
        unit = e["unit"]
        if unit not in units:
            units.append(unit)
        rm = e.get("room")
        if rm and rm not in rooms:
            rooms.append(rm)
        if e.get("level_of_care"):
            levels.add(e["level_of_care"])
        if e.get("service"):
            services.add(e["service"])
        et = e["event_type"]
        event_type_counts[et] = event_type_counts.get(et, 0) + 1
        if et.lower().startswith("transfer"):
            transfer_count += 1

    # First movement = last entry (reverse chron → last is earliest)
    last_entry = entries[-1]
    first_ts = f"{last_entry['date_raw']} {last_entry['time_raw']}"

    # Admission timestamp = latest (reverse chron) Admission entry → last one
    for e in reversed(entries):
        if e["event_type"].lower() == "admission":
            admission_ts = f"{e['date_raw']} {e['time_raw']}"
            break

    # Discharge timestamp = first Discharge entry found (most recent)
    for e in entries:
        if e["event_type"].lower() == "discharge":
            discharge_ts = f"{e['date_raw']} {e['time_raw']}"
            discharge_disposition_final = e.get("discharge_disposition")
            break

    return {
        "movement_event_count": len(entries),
        "first_movement_ts": first_ts,
        "admission_ts": admission_ts,
        "discharge_ts": discharge_ts,
        "discharge_disposition_final": discharge_disposition_final,
        "transfer_count": transfer_count,
        "units_visited": units,
        "levels_of_care": sorted(levels),
        "services_seen": sorted(services),
        "rooms_visited": rooms,
        "event_type_counts": event_type_counts,
    }


# ── Public API ──────────────────────────────────────────────────────

def extract_patient_movement(
    pat_features: Dict[str, Any],
    days_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Extract the Patient Movement event-log from the raw patient data file.

    Parameters
    ----------
    pat_features : dict
        {"days": feature_days} — currently unused but follows pattern.
    days_data : dict
        Full patient_days_v1.json dict (with meta.source_file injected
        by the builder from the evidence JSON).

    Returns
    -------
    dict with keys: entries, summary, evidence, source_file,
                    source_rule_id, warnings, notes
    """
    meta = days_data.get("meta") or {}
    source_file = meta.get("source_file")
    warnings: List[str] = []
    notes: List[str] = []

    # ── Read raw file and extract Patient Movement section ──────
    entries: List[Dict[str, Any]] = []
    section_lines = None

    if source_file:
        section_lines = _extract_pm_section_lines(source_file)

    if section_lines is not None:
        entries, parse_warnings = _parse_movement_entries(section_lines)
        warnings.extend(parse_warnings)
        notes.append(
            f"source=raw_file, section_lines={len(section_lines)}, "
            f"entries_parsed={len(entries)}"
        )
        source_rule_id = "patient_movement_raw_file"
    else:
        if not source_file:
            notes.append("no_source_file_in_meta")
        elif not os.path.isfile(source_file):
            notes.append(f"source_file_not_found: {source_file}")
            warnings.append("source_file_not_found")
        else:
            notes.append("no_patient_movement_section_found")
        source_rule_id = "no_patient_movement_section"

    # ── Build summary ───────────────────────────────────────────
    summary = _build_summary(entries)

    # ── Normalize structured disposition if present ─────────────
    if summary["discharge_disposition_final"]:
        summary["discharge_disposition_final"] = _normalize_disposition(
            summary["discharge_disposition_final"]
        )

    # ── Disposition fallback: scan raw file if not found in PM section ──
    if not summary["discharge_disposition_final"] and source_file:
        fallback_dispo = _scan_raw_disposition_fallback(source_file)
        if fallback_dispo:
            summary["discharge_disposition_final"] = fallback_dispo
            notes.append(
                f"discharge_disposition_fallback=raw_file_scan, "
                f"value={fallback_dispo}"
            )

    # ── Build evidence list ─────────────────────────────────────
    evidence: List[Dict[str, Any]] = []
    for e in entries:
        snippet = (
            f"{e['unit']} {e['date_raw']} {e['time_raw']} "
            f"{e['event_type']}"
        )[:120]
        evidence.append({
            "role": "patient_movement_entry",
            "snippet": snippet,
            "raw_line_id": e["raw_line_id"],
        })

    # ── Clean entries for output (remove internal fields) ──────
    output_entries = []
    for e in entries:
        output_entries.append({
            "unit": e["unit"],
            "date_raw": e["date_raw"],
            "time_raw": e["time_raw"],
            "event_type": e["event_type"],
            "room": e["room"],
            "bed": e["bed"],
            "patient_class": e["patient_class"],
            "level_of_care": e["level_of_care"],
            "service": e["service"],
            "providers": e["providers"],
            "discharge_disposition": e["discharge_disposition"],
            "raw_line_id": e["raw_line_id"],
        })

    return {
        "entries": output_entries,
        "summary": summary,
        "evidence": evidence,
        "source_file": source_file,
        "source_rule_id": source_rule_id,
        "warnings": warnings,
        "notes": notes,
    }
