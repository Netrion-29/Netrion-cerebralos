#!/usr/bin/env python3
"""
ADT / Transfer Timeline Extraction v1 for CerebralOS.

Deterministic extraction of structured ADT (Admission–Discharge–Transfer)
events from the raw export header and/or embedded note sections.

Parses the "ADT Events" table (tab-delimited):
    timestamp  Unit  Room  Bed  Service  Event

Produces:
  - events[]: each with timestamp_raw, timestamp_iso, unit, room, bed,
      service, event_type, raw_line_id
  - summary: adt_event_count, first_admission_ts, transfer_count,
      discharge_ts, units_visited, los_hours, los_days,
      event_type_counts, services_seen, rooms_visited,
      patient_update_count, last_unit, last_room, last_bed

Fail-closed behaviour:
  - Returns empty events[] and null summary fields when no ADT table found.
  - Only structured table rows are captured — no inference.
  - Every event carries raw_line_id for evidence traceability.

v2 refinements:
  - Headerless ADT fallback: detects ADT data rows in header lines
    even when no "ADT Events" header is present (e.g. Ronald Bittner).
  - Defensive dedup on (timestamp_raw, unit, room, bed, event_type).
  - Chronology validation: warns if events are out of order.
  - Enriched summary: event_type_counts, services_seen, rooms_visited,
    patient_update_count, last_unit/room/bed, los_days.

Output key: ``adt_transfer_timeline_v1``
"""

from __future__ import annotations

import math
import re
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

_DNA = "DATA NOT AVAILABLE"

# ── ADT Events table regex ─────────────────────────────────────────

# Matches the "ADT Events" header line (section start marker).
RE_ADT_HEADER = re.compile(r"^\s*ADT\s+Events\s*$", re.IGNORECASE)

# Matches the column header line: <tab>Unit<tab>Room<tab>Bed<tab>Service<tab>Event
RE_ADT_COL_HEADER = re.compile(
    r"^\s*\t?\s*Unit\s+Room\s+Bed\s+Service\s+Event\s*$",
    re.IGNORECASE,
)

# Matches an ADT data row:
#   MM/DD/YY HHMM<tab>UNIT<tab>ROOM<tab>BED<tab>SERVICE<tab>EVENT
# Captures: (timestamp_raw, unit, room, bed, service, event_type)
RE_ADT_ROW = re.compile(
    r"^(\d{1,2}/\d{1,2}/\d{2,4}\s+\d{4})"  # timestamp: MM/DD/YY HHMM
    r"\t"                                      # tab separator
    r"([^\t]+)"                                # unit
    r"\t"                                      # tab separator
    r"([^\t]+)"                                # room
    r"\t"                                      # tab separator
    r"([^\t]+)"                                # bed
    r"\t"                                      # tab separator
    r"([^\t]+)"                                # service
    r"\t"                                      # tab separator
    r"(.+?)\s*$",                              # event_type
)

# Valid event types (whitelist for deterministic extraction).
VALID_EVENT_TYPES = frozenset({
    "Admission",
    "Transfer In",
    "Transfer Out",
    "Patient Update",
    "Discharge",
})


# ── Timestamp normalisation ────────────────────────────────────────

def _normalise_adt_timestamp(raw: str) -> Optional[str]:
    """
    Convert MM/DD/YY HHMM → ISO 8601 datetime string.

    Handles both 2-digit and 4-digit years.
    Returns None on parse failure (fail-closed).
    """
    raw = raw.strip()
    # Split date part and time part
    parts = raw.split()
    if len(parts) != 2:
        return None

    date_part, time_part = parts

    # Normalise time: HHMM → HH:MM
    if len(time_part) == 4 and time_part.isdigit():
        time_str = f"{time_part[:2]}:{time_part[2:]}"
    else:
        return None

    # Parse date: M/D/YY or MM/DD/YYYY
    date_segs = date_part.split("/")
    if len(date_segs) != 3:
        return None

    try:
        month = int(date_segs[0])
        day = int(date_segs[1])
        year_raw = int(date_segs[2])
    except ValueError:
        return None

    # 2-digit year → 4-digit (pivot at 80: 00-79 → 2000s, 80-99 → 1900s)
    if year_raw < 100:
        year = 2000 + year_raw if year_raw < 80 else 1900 + year_raw
    else:
        year = year_raw

    try:
        dt = datetime(year, month, day, int(time_str[:2]), int(time_str[3:]))
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


# ── Core extraction ────────────────────────────────────────────────

def _extract_adt_headerless(
    lines: List[str],
    raw_line_id_prefix: str = "header",
) -> List[Dict[str, Any]]:
    """
    Fallback: extract ADT data rows when no "ADT Events" header is present.

    Some raw files (e.g. Ronald Bittner) embed ADT rows directly after
    demographics (name / age / DOB) with no section header and no column
    header.  This function scans all lines for ADT data rows matching
    ``RE_ADT_ROW`` with a whitelisted event type and returns them in order.

    Only called when ``_extract_adt_from_lines`` yields no events.
    """
    events: List[Dict[str, Any]] = []
    for line_idx, line in enumerate(lines):
        m = RE_ADT_ROW.match(line)
        if not m:
            continue
        ts_raw = m.group(1).strip()
        unit = m.group(2).strip()
        room = m.group(3).strip()
        bed = m.group(4).strip()
        service = m.group(5).strip()
        event_type = m.group(6).strip()
        if event_type not in VALID_EVENT_TYPES:
            continue
        ts_iso = _normalise_adt_timestamp(ts_raw)
        events.append({
            "timestamp_raw": ts_raw,
            "timestamp_iso": ts_iso or _DNA,
            "unit": unit,
            "room": room,
            "bed": bed,
            "service": service,
            "event_type": event_type,
            "raw_line_id": f"{raw_line_id_prefix}:{line_idx}",
        })
    return events


def _dedup_events(
    events: List[Dict[str, Any]],
    warnings: List[str],
) -> List[Dict[str, Any]]:
    """
    Defensive dedup on (timestamp_raw, unit, room, bed, event_type).

    First occurrence wins; duplicates are dropped and warned.
    """
    seen: set = set()
    deduped: List[Dict[str, Any]] = []
    for ev in events:
        key = (
            ev["timestamp_raw"],
            ev["unit"],
            ev["room"],
            ev["bed"],
            ev["event_type"],
        )
        if key in seen:
            warnings.append(
                f"duplicate_adt_row_dropped: {ev['timestamp_raw']} "
                f"{ev['event_type']} {ev['unit']}"
            )
            continue
        seen.add(key)
        deduped.append(ev)
    return deduped


def _validate_chronology(
    events: List[Dict[str, Any]],
    warnings: List[str],
) -> None:
    """
    Warn if events are not in chronological order.

    Does NOT reorder — purely advisory.
    """
    prev_iso: Optional[str] = None
    for ev in events:
        iso = ev.get("timestamp_iso")
        if iso and iso != _DNA and prev_iso and prev_iso != _DNA:
            if iso < prev_iso:
                warnings.append(
                    f"chronology_break: {ev['timestamp_raw']} "
                    f"({ev['event_type']}) is before preceding event"
                )
        if iso and iso != _DNA:
            prev_iso = iso


def _extract_adt_from_lines(
    lines: List[str],
    raw_line_id_prefix: str = "header",
) -> List[Dict[str, Any]]:
    """
    Parse ADT Events table from a sequence of text lines.

    Returns list of event dicts, each with:
      timestamp_raw, timestamp_iso, unit, room, bed, service,
      event_type, raw_line_id
    """
    events: List[Dict[str, Any]] = []
    in_adt_section = False
    past_col_header = False

    for line_idx, line in enumerate(lines):
        # Detect section start
        if RE_ADT_HEADER.match(line):
            in_adt_section = True
            past_col_header = False
            continue

        if not in_adt_section:
            continue

        # Skip blank lines between header and column headers
        stripped = line.strip()
        if not stripped:
            # Stop parsing if we already had data rows and hit a blank line
            if past_col_header and events:
                break
            continue

        # Detect column header
        if RE_ADT_COL_HEADER.match(line):
            past_col_header = True
            continue

        # Try to match a data row
        m = RE_ADT_ROW.match(line)
        if m:
            past_col_header = True
            ts_raw = m.group(1).strip()
            unit = m.group(2).strip()
            room = m.group(3).strip()
            bed = m.group(4).strip()
            service = m.group(5).strip()
            event_type = m.group(6).strip()

            # Whitelist event type (fail-closed)
            if event_type not in VALID_EVENT_TYPES:
                continue

            ts_iso = _normalise_adt_timestamp(ts_raw)

            events.append({
                "timestamp_raw": ts_raw,
                "timestamp_iso": ts_iso or _DNA,
                "unit": unit,
                "room": room,
                "bed": bed,
                "service": service,
                "event_type": event_type,
                "raw_line_id": f"{raw_line_id_prefix}:{line_idx}",
            })
        else:
            # Non-matching non-blank line after data started → end of table
            if past_col_header and events:
                break

    return events


def _build_summary(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Derive summary fields from extracted ADT events.

    Returns dict with:
      adt_event_count, first_admission_ts, transfer_count,
      discharge_ts, units_visited, los_hours, los_days,
      event_type_counts, services_seen, rooms_visited,
      patient_update_count, last_unit, last_room, last_bed
    """
    if not events:
        return {
            "adt_event_count": 0,
            "first_admission_ts": None,
            "transfer_count": 0,
            "discharge_ts": None,
            "units_visited": [],
            "los_hours": None,
            "los_days": None,
            "event_type_counts": {},
            "services_seen": [],
            "rooms_visited": [],
            "patient_update_count": 0,
            "last_unit": None,
            "last_room": None,
            "last_bed": None,
        }

    # First admission
    first_admission_ts = None
    for ev in events:
        if ev["event_type"] == "Admission":
            first_admission_ts = ev["timestamp_iso"]
            break

    # Transfer count (Transfer In + Transfer Out pairs → count unique transfers)
    transfer_in_count = sum(1 for ev in events if ev["event_type"] == "Transfer In")
    transfer_out_count = sum(1 for ev in events if ev["event_type"] == "Transfer Out")
    transfer_count = max(transfer_in_count, transfer_out_count)

    # Discharge timestamp (last Discharge event)
    discharge_ts = None
    for ev in reversed(events):
        if ev["event_type"] == "Discharge":
            discharge_ts = ev["timestamp_iso"]
            break

    # Units visited (unique, preserving first-seen order)
    seen_units: List[str] = []
    seen_unit_set: set = set()
    for ev in events:
        u = ev["unit"]
        if u not in seen_unit_set:
            seen_units.append(u)
            seen_unit_set.add(u)

    # LOS hours (first admission → last discharge)
    los_hours = None
    los_days = None
    if first_admission_ts and discharge_ts:
        try:
            dt_admit = datetime.strptime(first_admission_ts, "%Y-%m-%d %H:%M:%S")
            dt_discharge = datetime.strptime(discharge_ts, "%Y-%m-%d %H:%M:%S")
            delta = dt_discharge - dt_admit
            los_hours = round(delta.total_seconds() / 3600, 1)
            los_days = round(los_hours / 24, 1)
        except (ValueError, TypeError):
            pass

    # ── Enriched summary fields (v2) ───────────────────────────
    # Event type counts
    event_type_counts: Dict[str, int] = dict(Counter(
        ev["event_type"] for ev in events
    ))

    # Services seen (sorted unique)
    services_seen = sorted({ev["service"] for ev in events})

    # Rooms visited (ordered unique, excluding system placeholders)
    _ROOM_EXCLUDE = {"MCTRANSITION", "NONE", ""}
    seen_rooms: List[str] = []
    seen_room_set: set = set()
    for ev in events:
        r = ev["room"]
        if r in _ROOM_EXCLUDE:
            continue
        if r not in seen_room_set:
            seen_rooms.append(r)
            seen_room_set.add(r)

    patient_update_count = sum(
        1 for ev in events if ev["event_type"] == "Patient Update"
    )

    # Last event location
    last_ev = events[-1]
    last_unit = last_ev["unit"]
    last_room = last_ev["room"]
    last_bed = last_ev["bed"]

    return {
        "adt_event_count": len(events),
        "first_admission_ts": first_admission_ts,
        "transfer_count": transfer_count,
        "discharge_ts": discharge_ts,
        "units_visited": seen_units,
        "los_hours": los_hours,
        "los_days": los_days,
        "event_type_counts": event_type_counts,
        "services_seen": services_seen,
        "rooms_visited": seen_rooms,
        "patient_update_count": patient_update_count,
        "last_unit": last_unit,
        "last_room": last_room,
        "last_bed": last_bed,
    }


# ── Public API ─────────────────────────────────────────────────────

def extract_adt_transfer_timeline(
    pat_features: Dict[str, Any],
    days_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Extract ADT transfer timeline from patient data.

    Strategy (dual source, deterministic):
      1. Check meta.raw_header_lines (from evidence JSON header) for ADT table.
      2. If not found, scan all timeline item payload texts.
      3. First source that yields events wins (no merging).

    Parameters
    ----------
    pat_features : dict
        {"days": feature_days} — currently unused but follows pattern.
    days_data : dict
        Full patient_days_v1.json dict (with meta.raw_header_lines injected).

    Returns
    -------
    dict with keys: events, summary, evidence, warnings, notes
    """
    meta = days_data.get("meta") or {}
    warnings: List[str] = []
    notes: List[str] = []
    events: List[Dict[str, Any]] = []

    # ── Source 1: raw_header_lines (file header, injected by orchestrator) ──
    raw_header_lines = meta.get("raw_header_lines") or []
    if raw_header_lines:
        events = _extract_adt_from_lines(raw_header_lines, raw_line_id_prefix="header")
        if events:
            notes.append(f"source=raw_header_lines, rows={len(events)}")
        else:
            # Fallback: headerless ADT rows in header (e.g. Ronald Bittner)
            events = _extract_adt_headerless(
                raw_header_lines, raw_line_id_prefix="header_headerless",
            )
            if events:
                notes.append(
                    f"source=raw_header_lines_headerless, rows={len(events)}"
                )

    # ── Source 2: scan timeline item payload texts ──────────────
    if not events:
        days_map = days_data.get("days") or {}
        for day_iso in sorted(days_map.keys()):
            day_info = days_map[day_iso]
            for item_idx, item in enumerate(day_info.get("items") or []):
                text = (item.get("payload") or {}).get("text", "")
                if "ADT Events" not in text:
                    continue

                # Split text into lines and extract
                text_lines = text.split("\n")
                item_events = _extract_adt_from_lines(
                    text_lines,
                    raw_line_id_prefix=f"item:{day_iso}:{item_idx}",
                )
                if item_events:
                    events = item_events
                    notes.append(
                        f"source=timeline_item, day={day_iso}, "
                        f"item_idx={item_idx}, rows={len(events)}"
                    )
                    break  # first source wins
            if events:
                break

    # ── Dedup & chronology validation (v2) ───────────────────────
    if events:
        events = _dedup_events(events, warnings)
        _validate_chronology(events, warnings)

    # ── Build summary ───────────────────────────────────────────
    summary = _build_summary(events)

    if not events:
        notes.append("no_adt_table_found")

    # ── Evidence list (for contract validator traceability) ─────
    evidence: List[Dict[str, Any]] = []
    for ev in events:
        evidence.append({
            "role": "adt_event",
            "snippet": (
                f"{ev['timestamp_raw']} {ev['event_type']} "
                f"{ev['unit']} {ev['room']}"
            )[:120],
            "raw_line_id": ev["raw_line_id"],
        })

    return {
        "events": events,
        "summary": summary,
        "evidence": evidence,
        "warnings": warnings,
        "notes": notes,
    }
