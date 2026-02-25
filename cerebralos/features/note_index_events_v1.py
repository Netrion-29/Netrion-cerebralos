#!/usr/bin/env python3
"""
Note Index Events v1 — Structured Note-Index / Event-Log Extraction.

Deterministic extraction of the **Notes subsection** from the Epic-format
encounter event log.  This is the index/listing of all notes authored
during the encounter, with timestamps, authors, credentials, and service
tags.  It does NOT extract the note bodies themselves (that is handled
by ``note_sections_v1`` and the per-note timeline items).

Only the ``Notes`` subsection is parsed — NOT Meds / Labs / Imaging /
LDAs / Flowsheets / Patient Movement (other event-log subsections).

Source priority:
  1. Raw data file (``meta.source_file`` injected by the builder from
     the evidence JSON).
  2. Fail-closed when no raw file path or no Notes subsection found.

Notes subsection format (tab-delimited, Epic export):

::

    Notes                           <CR>
    Consults       01/01   1020    Chacko, Chris E, MD
    <blank>
    Service
    Otolaryngology
    <blank>
    ED Notes       01/01   0002    PROVIDER, SCANNING
    ...

Entry format: ``<NoteType>\\t<MM/DD>\\t<HHMM>\\t<AuthorName, Credentials>``

Service field: appears on lines below entries as::

    Service
    <service_name>

Section boundaries: the Notes section ends when a line matches one of the
other event-log section headers (LDAs, Flowsheets, Patient Movement, etc.)
or end of file.

Output key: ``note_index_events_v1``

Output schema::

    {
      "entries": [
        {
          "note_type": "Consults",
          "date_raw": "01/01",
          "time_raw": "1020",
          "author_raw": "Chacko, Chris E, MD",
          "author_name": "Chacko, Chris E",
          "author_credential": "MD",
          "service": "Otolaryngology" | null,
          "raw_line_id": "<sha256>"
        }, ...
      ],
      "summary": {
        "note_index_event_count": <int>,
        "unique_authors_count": <int>,
        "unique_note_types_count": <int>,
        "services_detected": ["Otolaryngology", ...],
        "consult_note_count": <int>
      },
      "evidence": [
        {
          "role": "note_index_entry",
          "snippet": "<first 120 chars of raw line>",
          "raw_line_id": "<sha256>"
        }, ...
      ],
      "source_file": "<path>" | null,
      "source_rule_id": "note_index_raw_file" | "no_notes_section",
      "warnings": [ ... ],
      "notes": [ ... ]
    }

Fail-closed behaviour:
  - No raw file path → entries=[], source_rule_id="no_notes_section"
  - Raw file exists but no Notes subsection → same
  - No entries extracted → note_index_event_count=0

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

_DNA = "DATA NOT AVAILABLE"

# ── Notes section header pattern ───────────────────────────────────
# Epic export format: "Notes" followed by whitespace/tabs and optional \r
RE_NOTES_HEADER = re.compile(r"^Notes\s*$")

# ── Section boundary headers (end of Notes section) ───────────────
_SECTION_BOUNDARIES = frozenset({
    "LDAs",
    "Flowsheets",
    "Patient Movement",
    "Meds",
    "Labs",
    "Imaging",
    "Imaging, EKG, and Radiology",
})

# More flexible boundary: any of these at start of line
RE_SECTION_BOUNDARY = re.compile(
    r"^(?:LDAs|Flowsheets|Patient Movement|Meds|Labs|"
    r"Imaging(?:,\s*EKG,?\s*and\s*Radiology)?)\s*$",
    re.IGNORECASE,
)

# ── Note entry pattern (tab-delimited) ────────────────────────────
# Format: NoteType\tMM/DD\tHHMM\tAuthorName, Credentials
RE_NOTE_ENTRY = re.compile(
    r"^(?P<note_type>[A-Za-z][A-Za-z &/\-]*?)"  # note type (letters, spaces, &, /)
    r"\t"
    r"(?P<date>\d{2}/\d{2})"                      # MM/DD
    r"\t"
    r"(?P<time>\d{4})"                             # HHMM
    r"\t"
    r"(?P<author>.+?)"                             # author name + credentials
    r"\s*$"
)

# ── Additional entries appended to the same note type line ────────
# Some entries end with "N more" to indicate continuation
RE_MORE_SUFFIX = re.compile(r"\t(\d+)\s+more\s*$")

# ── Service line pattern ──────────────────────────────────────────
# "Service" on its own line, followed by the service name on the next line
RE_SERVICE_MARKER = re.compile(r"^Service\s*$")

# ── Known credentials ────────────────────────────────────────────
# Common medical credentials appearing after the last comma in author string
_KNOWN_CREDENTIALS = frozenset({
    "MD", "DO", "NP", "PA", "RN", "LPN", "RT", "PT", "OT",
    "DPT", "OTR", "CRNA", "ARNP", "PA-C", "PharmD", "RPh",
    "LCSW", "MSW", "RD", "CNA", "BSN", "MSN", "DNP",
    "MA", "CMA", "EMT", "AEMT", "RRT", "SCANNING",
})


def _make_raw_line_id(text: str) -> str:
    """Deterministic SHA-256 hash of the raw line text."""
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _parse_author(author_raw: str) -> Tuple[str, Optional[str]]:
    """
    Parse author string into (name, credential).

    Handles formats like:
      "Chacko, Chris E, MD"     → ("Chacko, Chris E", "MD")
      "Lauer, Jenna L, RN"     → ("Lauer, Jenna L", "RN")
      "PROVIDER, SCANNING"     → ("PROVIDER", "SCANNING")
      "Sharp, Kelsey, PT, DPT" → ("Sharp, Kelsey", "PT, DPT")
      "Adams, Phillip, MD"     → ("Adams, Phillip", "MD")

    Strategy: scan from the end, collecting known credentials.
    Everything before the first credential is the name.
    """
    parts = [p.strip() for p in author_raw.split(",")]
    if len(parts) <= 1:
        return (author_raw.strip(), None)

    # Collect credentials from the end
    creds: List[str] = []
    name_parts = list(parts)
    while len(name_parts) > 1:
        candidate = name_parts[-1].strip().upper()
        # Check against known credentials (case-insensitive)
        if candidate in _KNOWN_CREDENTIALS or candidate.replace("-", "") in _KNOWN_CREDENTIALS:
            creds.insert(0, name_parts.pop().strip())
        else:
            break

    author_name = ", ".join(name_parts).strip()
    author_credential = ", ".join(creds).strip() if creds else None

    return (author_name, author_credential)


def _extract_notes_section_lines(filepath: str) -> Optional[List[Tuple[int, str]]]:
    """
    Read the raw data file and extract lines belonging to the Notes
    event-log subsection.

    Returns a list of (line_number, line_text) tuples, or None if
    no Notes section is found.

    line_number is 1-based (matching file editors).
    """
    if not filepath or not os.path.isfile(filepath):
        return None

    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
    except OSError:
        return None

    # Find the Notes section header
    notes_start = None
    for i, line in enumerate(all_lines):
        stripped = line.strip().replace("\r", "")
        if stripped == "Notes":
            # Verify it looks like a section header — standalone line
            # not part of a longer phrase like "Notes to Pharmacy"
            notes_start = i
            break

    if notes_start is None:
        return None

    # Find the end of the Notes section
    notes_end = len(all_lines)
    for i in range(notes_start + 1, len(all_lines)):
        stripped = all_lines[i].strip().replace("\r", "")
        if stripped in _SECTION_BOUNDARIES or RE_SECTION_BOUNDARY.match(stripped):
            notes_end = i
            break

    # Collect lines (skip the header line itself)
    result: List[Tuple[int, str]] = []
    for i in range(notes_start + 1, notes_end):
        result.append((i + 1, all_lines[i]))  # 1-based line number

    return result


def _parse_note_entries(
    section_lines: List[Tuple[int, str]],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Parse note index entries from the Notes section lines.

    Returns (entries, warnings).

    Each entry:
      {
        "note_type": str,
        "date_raw": "MM/DD",
        "time_raw": "HHMM",
        "author_raw": str,
        "author_name": str,
        "author_credential": str | None,
        "service": str | None,
        "raw_line_id": str,
        "line_number": int,
      }
    """
    entries: List[Dict[str, Any]] = []
    warnings: List[str] = []

    i = 0
    while i < len(section_lines):
        line_num, line_text = section_lines[i]
        stripped = line_text.strip().replace("\r", "")

        # Skip blank lines
        if not stripped:
            i += 1
            continue

        # Skip "Service" marker lines and service name lines
        if RE_SERVICE_MARKER.match(stripped):
            i += 1
            continue

        # Try to match a note entry
        m = RE_NOTE_ENTRY.match(stripped)
        if m:
            note_type = m.group("note_type").strip()
            date_raw = m.group("date")
            time_raw = m.group("time")
            author_raw = m.group("author").strip()

            # Check for "N more" suffix on author (e.g., "951 more")
            more_m = RE_MORE_SUFFIX.search(line_text)
            if more_m:
                # Remove the "N more" from author
                author_raw = author_raw.rsplit("\t", 1)[0].strip() if "\t" in author_raw else author_raw

            author_name, author_credential = _parse_author(author_raw)
            raw_line_id = _make_raw_line_id(line_text.rstrip("\n\r"))

            # Look ahead for Service field
            service = None
            j = i + 1
            while j < len(section_lines):
                _, next_line = section_lines[j]
                next_stripped = next_line.strip().replace("\r", "")
                if not next_stripped:
                    j += 1
                    continue
                if RE_SERVICE_MARKER.match(next_stripped):
                    # Next non-blank line after "Service" is the service name
                    k = j + 1
                    while k < len(section_lines):
                        _, svc_line = section_lines[k]
                        svc_stripped = svc_line.strip().replace("\r", "")
                        if svc_stripped:
                            service = svc_stripped
                            break
                        k += 1
                    break
                else:
                    # Not a Service marker — this is either another entry or
                    # something else; the current entry has no service
                    break
                j += 1

            entries.append({
                "note_type": note_type,
                "date_raw": date_raw,
                "time_raw": time_raw,
                "author_raw": author_raw,
                "author_name": author_name,
                "author_credential": author_credential,
                "service": service,
                "raw_line_id": raw_line_id,
                "line_number": line_num,
            })

        else:
            # Non-entry, non-blank, non-service line — could be
            # a service name for a preceding entry, or noise
            # Check if this looks like a service name (after Service marker
            # in previous line was already consumed by look-ahead)
            # Just skip — the look-ahead handles service association
            pass

        i += 1

    return entries, warnings


def _build_summary(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build summary statistics from parsed entries."""
    if not entries:
        return {
            "note_index_event_count": 0,
            "unique_authors_count": 0,
            "unique_note_types_count": 0,
            "services_detected": [],
            "consult_note_count": 0,
        }

    unique_authors = set()
    unique_types = set()
    services = set()
    consult_count = 0

    for e in entries:
        unique_authors.add(e["author_name"])
        unique_types.add(e["note_type"])
        if e["service"]:
            services.add(e["service"])
        if e["note_type"].lower().startswith("consult"):
            consult_count += 1

    return {
        "note_index_event_count": len(entries),
        "unique_authors_count": len(unique_authors),
        "unique_note_types_count": len(unique_types),
        "services_detected": sorted(services),
        "consult_note_count": consult_count,
    }


# ── Public API ──────────────────────────────────────────────────────

def extract_note_index_events(
    pat_features: Dict[str, Any],
    days_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Extract the Notes event-log index from the raw patient data file.

    Parameters
    ----------
    pat_features : dict
        {"days": feature_days} — currently unused but follows pattern.
    days_data : dict
        Full patient_days_v1.json dict (with meta.source_file injected
        by the builder from the evidence JSON).

    Returns
    -------
    dict with keys: entries, summary, evidence, source_file, source_rule_id,
                    warnings, notes
    """
    meta = days_data.get("meta") or {}
    source_file = meta.get("source_file")
    warnings: List[str] = []
    notes: List[str] = []

    # ── Read raw file and extract Notes section ─────────────────
    entries: List[Dict[str, Any]] = []
    section_lines = None

    if source_file:
        section_lines = _extract_notes_section_lines(source_file)

    if section_lines is not None:
        entries, parse_warnings = _parse_note_entries(section_lines)
        warnings.extend(parse_warnings)
        notes.append(
            f"source=raw_file, section_lines={len(section_lines)}, "
            f"entries_parsed={len(entries)}"
        )
        source_rule_id = "note_index_raw_file"
    else:
        if not source_file:
            notes.append("no_source_file_in_meta")
        elif not os.path.isfile(source_file):
            notes.append(f"source_file_not_found: {source_file}")
            warnings.append("source_file_not_found")
        else:
            notes.append("no_notes_section_found")
        source_rule_id = "no_notes_section"

    # ── Build summary ───────────────────────────────────────────
    summary = _build_summary(entries)

    # ── Build evidence list ─────────────────────────────────────
    evidence: List[Dict[str, Any]] = []
    for e in entries:
        snippet = (
            f"{e['note_type']} {e['date_raw']} {e['time_raw']} "
            f"{e['author_raw']}"
        )[:120]
        evidence.append({
            "role": "note_index_entry",
            "snippet": snippet,
            "raw_line_id": e["raw_line_id"],
        })

    # ── Clean entries for output (remove internal fields) ──────
    output_entries = []
    for e in entries:
        output_entries.append({
            "note_type": e["note_type"],
            "date_raw": e["date_raw"],
            "time_raw": e["time_raw"],
            "author_raw": e["author_raw"],
            "author_name": e["author_name"],
            "author_credential": e["author_credential"],
            "service": e["service"],
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
