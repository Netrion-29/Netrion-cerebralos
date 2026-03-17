#!/usr/bin/env python3
"""
CerebralOS — Build PatientFacts from Epic TXT Export (v1)

Parses raw Epic .txt exports into PatientFacts for NTDS evaluation.

Design:
- Deterministic line-by-line parsing
- Fail-closed: missing data → empty or None (never guessed)
- Preserves original text for evidence receipts
- PHI handling: caller is responsible for ensuring PHI is not committed

Supported Epic export format:
- Section headers (e.g., "PHYSICIAN NOTES:", "IMAGING:")
- Timestamped entries (e.g., "01/15/26 0830")
- Free-text clinical notes
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from cerebralos.ntds_logic.model import (
    Evidence,
    EvidencePointer,
    PatientFacts,
    SourceType,
)


# Section header patterns map to SourceType
# Use [\s_]+ so both "PHYSICIAN NOTE" and "PHYSICIAN_NOTE" match
# (production Epic exports use spaces; synthetic test fixtures use underscores).
_SECTION_PATTERNS: Dict[str, SourceType] = {
    r"^\[?\s*PHYSICIAN[\s_]+NOTE": SourceType.PHYSICIAN_NOTE,
    r"CONSULT[\s_]+NOTE": SourceType.CONSULT_NOTE,
    r"^\[?\s*NURSING[\s_]+NOTE": SourceType.NURSING_NOTE,
    r"^\[?\s*IMAGING": SourceType.IMAGING,
    r"^\[?\s*RADIOLOGY": SourceType.IMAGING,
    r"^\[?\s*LABS?\b": SourceType.LAB,
    r"^\[?\s*MAR\b": SourceType.MAR,
    r"^\[?\s*MEDICATION[\s_]+ADMIN": SourceType.MAR,
    r"^\[?\s*PROCEDURE": SourceType.PROCEDURE,
    r"^\[?\s*(?:POST[-\s]?|BRIEF[\s_]+)?OPERATIVE[\s_]+NOTE": SourceType.OPERATIVE_NOTE,
    r"^\[?\s*(?:POST[-\s]?)?OP[\s_]+NOTE": SourceType.OPERATIVE_NOTE,
    r"^\[?\s*DISCHARGE": SourceType.DISCHARGE,
    r"^\[?\s*ED[\s_]+NOTE": SourceType.ED_NOTE,
    r"EMERGENCY[\s_]+(?:DEPARTMENT|DEPT)": SourceType.ED_NOTE,
    r"^\[?\s*(?:(?:BRIEF|CONSULT|DAILY|DEACONESS|ELECTROPHYSIOLOGY|ESA|HEART"
    r"|HOSPITAL(?:IST)?|INFECTIOUS|INPATIENT|NEUROLOGY|NON|PALLIATIVE|PHARMACY"
    r"|PODIATRY|POST[-\s]?OP|THE|TRAUMA|VASCULAR|WOUND)\b[\w\s,&-]{0,40})?"
    r"PROGRESS[\s_]+NOTE": SourceType.PROGRESS_NOTE,
    r"^\[?\s*ANESTHESIA[\s_]": SourceType.ANESTHESIA_NOTE,
}

# Words that, when appearing as the sole trailing text after a section keyword,
# indicate the line is clinical prose rather than a true section header.
_BLOCK_WORDS = {
    "PATIENT", "DISPOSITION", "PROVIDER", "PLANNING", "PLANNING.",
}

# Extended block words checked against the first trailing token (after
# stripping colons/periods) when the matched pattern is DISCHARGE.
# This catches admin-field lines like "Discharge Disposition: Rehab-Inpt"
# where the full trailing text differs from the bare block word.
_DISCHARGE_BLOCK_FIRST_WORDS = _BLOCK_WORDS | {
    "PATIENTON", "RECOMMENDATIONS", "MIM", "/TRANSFER",
    "COMMENTS", "ASSESSMENT",
    "AT", "ORDERS", "ORTHO", "PENDING", "PER", "PT", "TO",
}

# Phrases that, when appearing in text BEFORE "CONSULT NOTE",
# indicate the line is clinical prose rather than a section header.
# Examples blocked: "HPI from Initial Consult Note:",
#   "Please see EP consult note from Dr. Makati",
#   "This note will include ... consult notes"
_CONSULT_PROSE_BEFORE = re.compile(
    r"(?:(?:^|\s)from\s|(?:^|\s)see\s|(?:^|\s)per\s|(?:^|\s)refer\s"
    r"|history\s+of|HPI\s+from|please\s+see|this\s+note\s+will"
    r"|score\s+is|\*\s*Refer)",
    re.IGNORECASE,
)

# Words allowed immediately after EMERGENCY DEPARTMENT/DEPT.
# Anything else (MC, dates, clinical prose) is rejected.
_EMERGENCY_DEPT_ALLOW_AFTER = {"NOTE", "ENCOUNTER"}

# Phrases that, when appearing BEFORE "EMERGENCY DEPARTMENT/DEPT",
# indicate clinical prose rather than a section header.
# Blocks: "closed in the emergency department",
#   "performed in the Emergency Department", etc.
_EMERGENCY_PROSE_BEFORE = re.compile(
    r"(?:\bin\b|\bfrom\b|\bperformed\b|\bresults\b|\bclosed\b)",
    re.IGNORECASE,
)

# Timestamp patterns (various Epic formats)
_TIMESTAMP_PATTERNS = [
    # mm/dd/yy HHmm
    (r"(\d{1,2}/\d{1,2}/\d{2,4})\s+(\d{4})", "%m/%d/%y %H%M"),
    # mm/dd/yy HH:mm
    (r"(\d{1,2}/\d{1,2}/\d{2,4})\s+(\d{2}:\d{2})", "%m/%d/%y %H:%M"),
    # yyyy-mm-dd HH:mm:ss
    (r"(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2})", "%Y-%m-%d %H:%M:%S"),
    # yyyy-mm-dd HH:mm
    (r"(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})", "%Y-%m-%d %H:%M"),
    # ISO format
    (r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", "%Y-%m-%dT%H:%M:%S"),
]


def _detect_source_type(line: str, current_source: SourceType) -> SourceType:
    """Detect if line is a section header, return appropriate SourceType."""
    upper = line.upper().strip()
    for pattern, source_type in _SECTION_PATTERNS.items():
        m = re.search(pattern, upper)
        if m:
            trailing = upper[m.end():].strip().strip(":")
            if trailing in _BLOCK_WORDS:
                continue
            # For CONSULT_NOTE, block when text before the keyword
            # contains prose indicators (cross-references, boilerplate).
            if source_type is SourceType.CONSULT_NOTE:
                before = upper[:m.start()].strip()
                if before and _CONSULT_PROSE_BEFORE.search(line[:m.start()]):
                    continue
            # For EMERGENCY DEPARTMENT/DEPT: block ADT lines
            # ("EMERGENCY DEPT MC ...") and prose ("in the Emergency
            # Department") by whitelisting allowed trailing words.
            if source_type is SourceType.ED_NOTE and "EMERGENCY" in upper[m.start():m.end()]:
                after = upper[m.end():].strip()
                first_after = after.split()[0] if after.split() else ""
                if first_after and first_after not in _EMERGENCY_DEPT_ALLOW_AFTER:
                    continue
                before = upper[:m.start()].strip()
                if before and _EMERGENCY_PROSE_BEFORE.search(line[:m.start()]):
                    continue
            # For DISCHARGE, also block on the first trailing word to
            # catch admin fields like "Discharge Disposition: Rehab-Inpt".
            if source_type is SourceType.DISCHARGE:
                if trailing == ".":
                    continue
                first_word = trailing.split()[0].rstrip(":.") if trailing.split() else ""
                if first_word in _DISCHARGE_BLOCK_FIRST_WORDS:
                    continue
            return source_type
    return current_source


def _extract_timestamp(line: str) -> Optional[str]:
    """Extract timestamp from line if present, return ISO format or None."""
    for pattern, fmt in _TIMESTAMP_PATTERNS:
        match = re.search(pattern, line)
        if match:
            try:
                ts_str = match.group(0)
                # Handle mm/dd/yy HHmm format specially
                if " " in ts_str and len(ts_str.split()[-1]) == 4 and ":" not in ts_str.split()[-1]:
                    parts = ts_str.split()
                    date_part = parts[0]
                    time_part = parts[1]
                    # Parse with 2-digit year or 4-digit year
                    if len(date_part.split("/")[-1]) == 2:
                        dt = datetime.strptime(f"{date_part} {time_part}", "%m/%d/%y %H%M")
                    else:
                        dt = datetime.strptime(f"{date_part} {time_part}", "%m/%d/%Y %H%M")
                    return dt.strftime("%Y-%m-%dT%H:%M:%S")
                # Handle mm/dd/yy HH:mm format
                elif " " in ts_str and ":" in ts_str.split()[-1] and len(ts_str.split()[-1]) == 5:
                    parts = ts_str.split()
                    date_part = parts[0]
                    time_part = parts[1]
                    if len(date_part.split("/")[-1]) == 2:
                        dt = datetime.strptime(f"{date_part} {time_part}", "%m/%d/%y %H:%M")
                    else:
                        dt = datetime.strptime(f"{date_part} {time_part}", "%m/%d/%Y %H:%M")
                    return dt.strftime("%Y-%m-%dT%H:%M:%S")
                else:
                    dt = datetime.strptime(ts_str, fmt)
                    return dt.strftime("%Y-%m-%dT%H:%M:%S")
            except ValueError:
                continue
    return None


def _is_section_header(line: str) -> bool:
    """Check if line is a section header."""
    upper = line.upper().strip()
    for pattern in _SECTION_PATTERNS:
        source_type = _SECTION_PATTERNS[pattern]
        m = re.search(pattern, upper)
        if m:
            trailing = upper[m.end():].strip().strip(":")
            if trailing in _BLOCK_WORDS:
                continue
            # For CONSULT_NOTE, block when text before the keyword
            # contains prose indicators (cross-references, boilerplate).
            if source_type is SourceType.CONSULT_NOTE:
                before = upper[:m.start()].strip()
                if before and _CONSULT_PROSE_BEFORE.search(line[:m.start()]):
                    continue
            if source_type is SourceType.ED_NOTE and "EMERGENCY" in upper[m.start():m.end()]:
                after = upper[m.end():].strip()
                first_after = after.split()[0] if after.split() else ""
                if first_after and first_after not in _EMERGENCY_DEPT_ALLOW_AFTER:
                    continue
                before = upper[:m.start()].strip()
                if before and _EMERGENCY_PROSE_BEFORE.search(line[:m.start()]):
                    continue
            if source_type is SourceType.DISCHARGE:
                if trailing == ".":
                    continue
                first_word = trailing.split()[0].rstrip(":.") if trailing.split() else ""
                if first_word in _DISCHARGE_BLOCK_FIRST_WORDS:
                    continue
            return True
    return False


def build_patientfacts(
    txt_path: Path,
    query_patterns: Dict[str, Any],
    arrival_time: Optional[str] = None,
    patient_id: Optional[str] = None,
) -> PatientFacts:
    """Parse Epic TXT export into PatientFacts.

    Args:
        txt_path: Path to the Epic .txt export file
        query_patterns: Dictionary of query pattern keys to regex patterns
        arrival_time: Optional override for arrival time (ISO format preferred)
        patient_id: Optional de-identified patient identifier

    Returns:
        PatientFacts containing parsed evidence and facts

    Note:
        - Fails closed: if file is missing or unreadable, returns empty PatientFacts
        - PHI in txt_path is the caller's responsibility to handle
    """
    facts: Dict[str, Any] = {
        "query_patterns": query_patterns,
        "arrival_time": arrival_time,
    }
    evidence_list: List[Evidence] = []

    if not txt_path.exists():
        return PatientFacts(patient_id=patient_id, facts=facts, evidence=[])

    try:
        content = txt_path.read_text(encoding="utf-8")
    except (IOError, UnicodeDecodeError):
        return PatientFacts(patient_id=patient_id, facts=facts, evidence=[])

    lines = content.splitlines()
    current_source = SourceType.UNKNOWN
    current_timestamp: Optional[str] = None
    raw_timestamps: List[Optional[str]] = [None] * len(lines)

    for line_num, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            raw_timestamps[line_num - 1] = current_timestamp
            continue

        # Check for section header - section headers define the source type for
        # subsequent lines until a new section is detected. Any timestamp in the
        # header is preserved and applied to following evidence entries until
        # overwritten by a newer timestamp.
        new_source = _detect_source_type(stripped, current_source)
        if new_source != current_source:
            current_source = new_source
            # Section headers often contain timestamps too
            ts = _extract_timestamp(stripped)
            if ts:
                current_timestamp = ts
            raw_timestamps[line_num - 1] = current_timestamp
            continue

        # Check for timestamp in line - updates current_timestamp for this and
        # subsequent evidence entries
        ts = _extract_timestamp(stripped)
        if ts:
            current_timestamp = ts

        raw_timestamps[line_num - 1] = current_timestamp

        # Create evidence for this line
        pointer = EvidencePointer(ref={
            "file": txt_path.name,
            "line": line_num,
        })

        ev = Evidence(
            source_type=current_source,
            timestamp=current_timestamp,
            text=stripped,
            pointer=pointer,
        )
        evidence_list.append(ev)

    # ── Populate LDA episodes from raw text (day-counters + start/stop) ──
    lda_episodes = build_lda_episodes(
        patient_id=patient_id, raw_lines=lines, raw_timestamps=raw_timestamps,
    )
    if lda_episodes:
        device_day_counts: Dict[str, int] = {}
        for ep in lda_episodes:
            device_type = ep.get("device_type", "")
            days = ep.get("episode_days")
            if device_type and days is not None:
                if device_type not in device_day_counts or days > device_day_counts[device_type]:
                    device_day_counts[device_type] = int(days)
        facts["lda_episodes_v1"] = {
            "episodes": lda_episodes,
            "device_day_counts": device_day_counts,
        }

    return PatientFacts(
        patient_id=patient_id,
        facts=facts,
        evidence=evidence_list,
    )


# ── LDA text-derived extraction helpers ────────────────────────────

# ── Insertion / removal patterns for start/stop inference ──────────
# Each entry: (compiled regex, device_type, "insert" | "remove").
# Patterns are case-insensitive.  The regex does NOT capture timestamps;
# the calling code must pair each match with the line's timestamp
# (extracted from the surrounding section header or inline timestamp).

_LDA_STARTSTOP_PATTERNS: List[tuple] = [
    # ── URINARY_CATHETER insertion ──
    (re.compile(r"\bfoley\b.*?\b(?:placed|inserted|in\s+place)\b", re.IGNORECASE), "URINARY_CATHETER", "insert"),
    (re.compile(r"\burinary\s+catheter\b.*?\b(?:inserted|placed|in\s+place)\b", re.IGNORECASE), "URINARY_CATHETER", "insert"),
    (re.compile(r"\bindwelling\s+(?:urinary\s+)?catheter\b.*?\b(?:inserted|placed|in\s+place)\b", re.IGNORECASE), "URINARY_CATHETER", "insert"),
    # ── URINARY_CATHETER removal ──
    (re.compile(r"\bfoley\b.*?\b(?:removed|discontinued|d/?c['\u2019]?d)\b", re.IGNORECASE), "URINARY_CATHETER", "remove"),
    (re.compile(r"\burinary\s+catheter\b.*?\b(?:removed|discontinued)\b", re.IGNORECASE), "URINARY_CATHETER", "remove"),
    (re.compile(r"\b(?:remove|discontinue|d/?c)\b.*?\bfoley\b", re.IGNORECASE), "URINARY_CATHETER", "remove"),
    # Raw evidence: "[REMOVED] Urethral Catheter 16 fr Anchored"
    # (Lee_Woodard:6959, Margaret_Rudd:10729, Jamie_Hunter:19994)
    (re.compile(r"\[REMOVED\]\s+Urethral\s+Catheter\b", re.IGNORECASE), "URINARY_CATHETER", "remove"),

    # ── CENTRAL_LINE insertion ──
    (re.compile(r"\bcentral\s+(?:venous\s+)?(?:line|catheter|access)\b.*?\b(?:placed|inserted|in\s+place)\b", re.IGNORECASE), "CENTRAL_LINE", "insert"),
    (re.compile(r"\b(?:PICC|picc)\b.*?\b(?:placed|inserted|in\s+place)\b", re.IGNORECASE), "CENTRAL_LINE", "insert"),
    (re.compile(r"\b(?:CVL|CVC|CVP)\b.*?\b(?:placed|inserted|in\s+place)\b", re.IGNORECASE), "CENTRAL_LINE", "insert"),
    (re.compile(r"\btriple[- ]lumen\b.*?\b(?:placed|inserted|in\s+place)\b", re.IGNORECASE), "CENTRAL_LINE", "insert"),
    (re.compile(r"\b(?:Hickman|Broviac|port-?a-?cath)\b.*?\b(?:placed|inserted)\b", re.IGNORECASE), "CENTRAL_LINE", "insert"),
    # ── CENTRAL_LINE removal ──
    (re.compile(r"\bcentral\s+(?:venous\s+)?(?:line|catheter)\b.*?\b(?:removed|discontinued|pulled)\b", re.IGNORECASE), "CENTRAL_LINE", "remove"),
    (re.compile(r"\b(?:PICC|picc)\b.*?\b(?:removed|discontinued|pulled)\b", re.IGNORECASE), "CENTRAL_LINE", "remove"),
    (re.compile(r"\b(?:CVL|CVC|CVP)\b.*?\b(?:removed|discontinued|pulled)\b", re.IGNORECASE), "CENTRAL_LINE", "remove"),
    (re.compile(r"\b(?:remove|discontinue|pull)\b.*?\bcentral\s+(?:venous\s+)?(?:line|catheter)\b", re.IGNORECASE), "CENTRAL_LINE", "remove"),

    # ── MECHANICAL_VENTILATOR / ENDOTRACHEAL_TUBE insertion ──
    (re.compile(r"\bintubat(?:ed|ion)\b", re.IGNORECASE), "ENDOTRACHEAL_TUBE", "insert"),
    (re.compile(r"\bmechanical\s+ventilation\s+(?:initiated|started|begun)\b", re.IGNORECASE), "MECHANICAL_VENTILATOR", "insert"),
    (re.compile(r"\bplaced\s+on\s+(?:mechanical\s+)?vent(?:ilat(?:or|ion))?\b", re.IGNORECASE), "MECHANICAL_VENTILATOR", "insert"),
    # ── MECHANICAL_VENTILATOR status (active vent presence) ──
    # Raw evidence: "sedated and on mechanical ventilation" (Ronald_Bittner:2153),
    # "Sedated on mechanical ventilation" (Ronald_Bittner:12024),
    # "on the ventilator" (Ronald_Bittner:2590),
    # "remains on the vent" (Ronald_Bittner:3027),
    # "on ventilator via tracheostomy" (Ronald_Bittner:669, 803, 1006)
    # Fail-closed: requires "on [the] [mechanical] vent*"; intervening
    # qualifiers (non-invasive, BiPAP, CPAP) break the pattern match.
    (re.compile(r"\bon\s+(?:the\s+)?(?:mechanical\s+)?vent(?:ilat(?:or|ion))?\b", re.IGNORECASE), "MECHANICAL_VENTILATOR", "insert"),
    # ── MECHANICAL_VENTILATOR via tracheostomy ──
    # Raw evidence: "being ventilated via tracheostomy" (Ronald_Bittner:656)
    (re.compile(r"\bventilat(?:ed|or|ion)\s+via\s+trach(?:eostomy)?\b", re.IGNORECASE), "MECHANICAL_VENTILATOR", "insert"),
    # ── MECHANICAL_VENTILATOR / ENDOTRACHEAL_TUBE removal ──
    (re.compile(r"\bextubat(?:ed|ion)\b", re.IGNORECASE), "ENDOTRACHEAL_TUBE", "remove"),
    (re.compile(r"\bvent(?:ilat(?:or|ion))?\s+(?:discontinued|weaned\s+off|removed)\b", re.IGNORECASE), "MECHANICAL_VENTILATOR", "remove"),
    (re.compile(r"\btrach(?:eostomy)?\s+placed\b", re.IGNORECASE), "ENDOTRACHEAL_TUBE", "remove"),  # trach placement ends ETT episode
    # Raw evidence: "[REMOVED] Non-Surgical Airway ETT- Cuffed"
    # (Jamie_Hunter:19974, James_Eaton:10857)
    (re.compile(r"\[REMOVED\]\s+Non-Surgical\s+Airway\b", re.IGNORECASE), "ENDOTRACHEAL_TUBE", "remove"),

    # ── CHEST_TUBE insertion ──
    # Raw evidence: "right chest tube placed" (Ronald_Bittner:4675),
    # "post chest tube placement" (Ronald_Bittner:5215),
    # "pigtail catheter placement" (Ronald_Bittner:41210)
    (re.compile(r"\bchest\s+tube\b.*?\b(?:placed|inserted|in\s+place|placement)\b", re.IGNORECASE), "CHEST_TUBE", "insert"),
    (re.compile(r"\bthoracostomy\b.*?\b(?:placed|inserted|performed|tube)\b", re.IGNORECASE), "CHEST_TUBE", "insert"),
    (re.compile(r"\bpigtail\s+(?:catheter|drain)\b.*?\b(?:placed|inserted|placement)\b", re.IGNORECASE), "CHEST_TUBE", "insert"),
    # ── CHEST_TUBE removal ──
    # Raw evidence: "Pulled chest tube" (Ronald_Bittner:3784),
    # "S/p chest tube removal" (Ronald_Bittner:5185),
    # "Chest tube on the right been removed" (Ronald_Bittner:5185)
    (re.compile(r"\bchest\s+tube\b.*?\b(?:removed|pulled|discontinued|d/?c['\u2019]?d|removal)\b", re.IGNORECASE), "CHEST_TUBE", "remove"),
    (re.compile(r"\b(?:pulled|removed?)\b.*?\bchest\s+tube\b", re.IGNORECASE), "CHEST_TUBE", "remove"),

    # ── DRAIN_SURGICAL insertion ──
    # Raw evidence: "[REMOVED] Surgical Drain 1 Anterior;Left;Superior Other (Comment) Hemovac"
    # (Timothy_Cowan:20599), "Drain Tube Type: Hemovac" (Timothy_Cowan:20605)
    (re.compile(r"\b(?:JP|Jackson[- ]Pratt)\s*drain\b.*?\b(?:placed|inserted|in\s+place)\b", re.IGNORECASE), "DRAIN_SURGICAL", "insert"),
    (re.compile(r"\bhemovac\b.*?\b(?:placed|inserted|in\s+place)\b", re.IGNORECASE), "DRAIN_SURGICAL", "insert"),
    (re.compile(r"\bblake\s+drain\b.*?\b(?:placed|inserted|in\s+place)\b", re.IGNORECASE), "DRAIN_SURGICAL", "insert"),
    (re.compile(r"\bsurgical\s+drain\b.*?\b(?:placed|inserted|in\s+place)\b", re.IGNORECASE), "DRAIN_SURGICAL", "insert"),
    (re.compile(r"\[REMOVED\]\s+Surgical\s+Drain\b", re.IGNORECASE), "DRAIN_SURGICAL", "remove"),
    # ── DRAIN_SURGICAL removal ──
    # Raw evidence: "[REMOVED] Surgical Drain 1" (Timothy_Cowan:20599/28511)
    (re.compile(r"\b(?:JP|Jackson[- ]Pratt)\s*drain\b.*?\b(?:removed|pulled|discontinued|d/?c['\u2019]?d)\b", re.IGNORECASE), "DRAIN_SURGICAL", "remove"),
    (re.compile(r"\bhemovac\b.*?\b(?:removed|pulled|discontinued)\b", re.IGNORECASE), "DRAIN_SURGICAL", "remove"),
    (re.compile(r"\bblake\s+drain\b.*?\b(?:removed|pulled|discontinued)\b", re.IGNORECASE), "DRAIN_SURGICAL", "remove"),
    (re.compile(r"\bsurgical\s+drain\b.*?\b(?:removed|pulled|discontinued)\b", re.IGNORECASE), "DRAIN_SURGICAL", "remove"),
]

# Negation guard for vent-status insert phrases.
# Avoid false inserts from explicit non-presence statements:
# "not on the ventilator", "no longer on the vent", "off the vent".
_RE_MV_STATUS_NEGATION = re.compile(
    r"\b(?:not\s+on|no\s+longer\s+on|off)\s+(?:the\s+)?(?:mechanical\s+)?vent(?:ilat(?:or|ion))?\b",
    re.IGNORECASE,
)


def _extract_lda_startstop_episodes(
    lines: List[str],
    timestamps: Optional[List[Optional[str]]] = None,
) -> List[Dict[str, Any]]:
    """Scan raw clinical text for device insertion/removal language.

    Args:
        lines: Raw text lines from the clinical note.
        timestamps: Parallel list of ISO timestamp strings (one per line).
            If a line's timestamp is ``None``, the match is still recorded
            but the episode will lack that boundary.

    Returns:
        One or more episode dicts per device type containing ``start_ts``,
        ``stop_ts``, and ``episode_days`` (computed when both timestamps
        are available).  Source confidence is ``TEXT_DERIVED_STARTSTOP``.

    Multi-episode devices (MECHANICAL_VENTILATOR, ENDOTRACHEAL_TUBE)
    pair sequential insert→remove events to produce non-overlapping
    episodes.  Other device types use a single episode (earliest insert,
    latest remove).
    """
    from cerebralos.ntds_logic.model import LDA_DEVICE_TYPES

    # Collect (device_type, action, timestamp, line_idx) tuples.
    hits: List[tuple] = []
    for idx, line in enumerate(lines):
        ts = timestamps[idx] if timestamps and idx < len(timestamps) else None
        for pattern, device_type, action in _LDA_STARTSTOP_PATTERNS:
            if pattern.search(line):
                # Fail-closed: explicit vent negation must not create MV insert episodes.
                if (
                    device_type == "MECHANICAL_VENTILATOR"
                    and action == "insert"
                    and _RE_MV_STATUS_NEGATION.search(line)
                ):
                    continue
                hits.append((device_type, action, ts, idx))

    if not hits:
        return []

    # Group by device_type.
    from collections import defaultdict
    by_device: Dict[str, List[tuple]] = defaultdict(list)
    for device_type, action, ts, idx in hits:
        by_device[device_type].append((action, ts, idx))

    # Device types that support multiple non-overlapping episodes.
    # Other device types keep existing one-episode-per-device behaviour.
    _MULTI_EPISODE_DEVICES = frozenset({"MECHANICAL_VENTILATOR", "ENDOTRACHEAL_TUBE"})

    def _compute_episode_days(start: Optional[str], stop: Optional[str]) -> Optional[int]:
        """Calendar-day difference (date-to-date), not timed-delta floor."""
        if not start or not stop:
            return None
        try:
            from datetime import datetime as _dt
            s = _dt.fromisoformat(start)
            e = _dt.fromisoformat(stop)
            return max(0, (e.date() - s.date()).days)
        except Exception:
            return None

    def _make_episode(
        device_type: str,
        start_ts: Optional[str],
        stop_ts: Optional[str],
        line_ids: set,
    ) -> Dict[str, Any]:
        return {
            "device_type": device_type,
            "start_ts": start_ts,
            "stop_ts": stop_ts,
            "episode_days": _compute_episode_days(start_ts, stop_ts),
            "source_confidence": "TEXT_DERIVED_STARTSTOP",
            "location": None,
            "inserted_by": None,
            "notes": None,
            "raw_line_ids": [f"L{n}" for n in sorted(line_ids)],
        }

    episodes: List[Dict[str, Any]] = []
    for device_type, actions in sorted(by_device.items()):
        if device_type not in LDA_DEVICE_TYPES:
            continue

        if device_type in _MULTI_EPISODE_DEVICES:
            # ── Multi-episode: pair sequential insert→remove events ──
            # Sort by line index for deterministic ordering.
            sorted_actions = sorted(actions, key=lambda t: t[2])

            current_start_ts: Optional[str] = None
            current_line_ids: set = set()
            in_episode = False

            for act, ts, idx in sorted_actions:
                if act == "insert":
                    if not in_episode:
                        # Start a new episode.
                        current_start_ts = ts
                        current_line_ids = {idx + 1}
                        in_episode = True
                    else:
                        # Already in episode — absorb insert (keep earliest ts).
                        current_line_ids.add(idx + 1)
                        if ts and (current_start_ts is None or ts < current_start_ts):
                            current_start_ts = ts
                elif act == "remove":
                    if in_episode:
                        # Close the episode.
                        current_line_ids.add(idx + 1)
                        episodes.append(_make_episode(
                            device_type, current_start_ts, ts, current_line_ids,
                        ))
                        in_episode = False
                        current_start_ts = None
                        current_line_ids = set()
                    else:
                        # Orphan remove (no preceding insert) — emit as
                        # stop-only episode (fail-closed: do not discard).
                        episodes.append(_make_episode(
                            device_type, None, ts, {idx + 1},
                        ))

            # If still in episode at end (insert without remove), emit it.
            if in_episode and current_line_ids:
                episodes.append(_make_episode(
                    device_type, current_start_ts, None, current_line_ids,
                ))
        else:
            # ── Single-episode: earliest insert, latest remove ──
            inserts = [(ts, idx) for act, ts, idx in actions if act == "insert"]
            removes = [(ts, idx) for act, ts, idx in actions if act == "remove"]

            start_ts: Optional[str] = None
            stop_ts: Optional[str] = None
            if inserts:
                ts_vals = [t for t, _ in inserts if t]
                start_ts = min(ts_vals) if ts_vals else None
            if removes:
                ts_vals = [t for t, _ in removes if t]
                stop_ts = max(ts_vals) if ts_vals else None

            all_line_ids = {idx + 1 for _, _, idx in actions}
            episodes.append(_make_episode(device_type, start_ts, stop_ts, all_line_ids))

    return episodes


# Maps a regex pattern to the canonical device_type it produces.
# Each pattern captures at least one group containing the day count.
# Patterns are tried in order; the *highest* day count per device
# wins (a patient note may mention the same device multiple times).
_LDA_TEXT_PATTERNS: List[tuple] = [
    # "Catheter day 3", "Catheter day: 3", "Catheter day  3  -MW —"
    (re.compile(r"\b(?:catheter)\s+day[:\s]+(\d+)", re.IGNORECASE), "URINARY_CATHETER"),
    # "Central line day 4", "Central line day: 4"
    (re.compile(r"\b(?:central\s+line)\s+day[:\s]+(\d+)", re.IGNORECASE), "CENTRAL_LINE"),
    # "Line Day: 5", "Line day 5"
    (re.compile(r"\b(?:line)\s+day[:\s]+(\d+)", re.IGNORECASE), "CENTRAL_LINE"),
    # "CVC day: 3", "CVC day 3"
    (re.compile(r"\b(?:cvc)\s+day[:\s]+(\d+)", re.IGNORECASE), "CENTRAL_LINE"),
    # "Ventilator day 3", "Vent day: 4"
    (re.compile(r"\b(?:vent(?:ilator)?)\s+day[:\s]+(\d+)", re.IGNORECASE), "MECHANICAL_VENTILATOR"),
    # "Chest tube day 3", "Chest tube day: 4"
    (re.compile(r"\b(?:chest\s+tube)\s+day[:\s]+(\d+)", re.IGNORECASE), "CHEST_TUBE"),
]


def _extract_lda_episodes_from_lines(lines: List[str]) -> List[Dict[str, Any]]:
    """Scan raw clinical text lines for flowsheet day-counter patterns.

    Returns one episode dict per device type, using the **highest** day
    count observed across all matching lines.  Source confidence is
    ``TEXT_DERIVED``.
    """
    best: Dict[str, int] = {}       # device_type -> max day count
    refs: Dict[str, set] = {}       # device_type -> set of line numbers

    for line_idx, line in enumerate(lines):
        for pattern, device_type in _LDA_TEXT_PATTERNS:
            m = pattern.search(line)
            if m:
                day_count = int(m.group(1))
                if device_type not in best or day_count > best[device_type]:
                    best[device_type] = day_count
                refs.setdefault(device_type, set()).add(line_idx + 1)

    episodes: List[Dict[str, Any]] = []
    for device_type, days in sorted(best.items()):
        episodes.append({
            "device_type": device_type,
            "episode_days": days,
            "source_confidence": "TEXT_DERIVED",
            "start_ts": None,
            "stop_ts": None,
            "location": None,
            "inserted_by": None,
            "notes": None,
            "raw_line_ids": [f"L{n}" for n in sorted(refs.get(device_type, set()))],
        })
    return episodes


# ── LDA episode builder ────────────────────────────────────────────

def build_lda_episodes(
    patient_id: Optional[str] = None,
    lda_json_path: Optional[Path] = None,
    raw_lines: Optional[List[str]] = None,
    raw_timestamps: Optional[List[Optional[str]]] = None,
) -> List[Any]:
    """Build LDA device episodes from structured JSON and/or raw text.

    Sources (combined; highest-fidelity wins per device_type):
    1. *lda_json_path* — structured JSON feed (highest fidelity).
    2. *raw_lines* + *raw_timestamps* — insertion/removal language
       producing start/stop episodes (``TEXT_DERIVED_STARTSTOP``).
    3. *raw_lines* — flowsheet day-counter patterns such as
       ``Catheter day 3`` (``TEXT_DERIVED``).

    Merge precedence per device_type:
        STRUCTURED > TEXT_DERIVED_STARTSTOP > TEXT_DERIVED

    When a higher-tier episode exists for a device, it *replaces* the
    lower-tier one entirely.  Within the same tier, the episode with the
    higher ``episode_days`` wins.

    Returns:
        List of dicts matching the LDAEpisode schema defined in model.py.
    """
    from cerebralos.ntds_logic.model import LDA_DEVICE_TYPES, LDA_CONFIDENCE_LEVELS

    # ── 1. Structured JSON feed ──────────────────────────────────────────
    structured: List[Any] = []
    if lda_json_path is not None and lda_json_path.exists():
        try:
            import json as _json
            raw = _json.loads(lda_json_path.read_text(encoding="utf-8"))
        except Exception:
            raw = {}

        records = raw.get("lda_records", [])
        if not isinstance(records, list):
            records = []

        for rec in records:
            if not isinstance(rec, dict):
                continue
            device_type = str(rec.get("device_type", "")).upper()
            if device_type not in LDA_DEVICE_TYPES:
                continue
            confidence = str(rec.get("source_confidence", "STRUCTURED")).upper()
            if confidence not in LDA_CONFIDENCE_LEVELS:
                confidence = "STRUCTURED"
            ep = {
                "device_type": device_type,
                "start_ts": rec.get("start_ts"),
                "stop_ts": rec.get("stop_ts"),
                "episode_days": rec.get("episode_days"),
                "source_confidence": confidence,
                "location": rec.get("location"),
                "inserted_by": rec.get("inserted_by"),
                "notes": rec.get("notes"),
                "raw_line_ids": rec.get("raw_line_ids", []),
            }
            # Compute episode_days if not provided but timestamps available.
            # Use calendar-day difference (date-to-date), not timed-delta floor.
            if ep["episode_days"] is None and ep["start_ts"] and ep["stop_ts"]:
                try:
                    from datetime import datetime as _dt
                    start = _dt.fromisoformat(ep["start_ts"])
                    stop = _dt.fromisoformat(ep["stop_ts"])
                    ep["episode_days"] = max(0, (stop.date() - start.date()).days)
                except Exception:
                    pass
            structured.append(ep)

    # ── 2. Text-derived start/stop from insertion/removal language ──────
    startstop_derived: List[Dict[str, Any]] = []
    if raw_lines:
        startstop_derived = _extract_lda_startstop_episodes(
            raw_lines, timestamps=raw_timestamps,
        )

    # ── 3. Text-derived from flowsheet day-counter patterns ──────────────
    text_derived: List[Dict[str, Any]] = []
    if raw_lines:
        text_derived = _extract_lda_episodes_from_lines(raw_lines)

    # ── 4. Merge: highest-fidelity wins per device_type ──────────────────
    # Priority: STRUCTURED > TEXT_DERIVED_STARTSTOP > TEXT_DERIVED
    # Within the same tier, keep the one with higher episode_days.
    #
    # Multi-episode device types (MECHANICAL_VENTILATOR, ENDOTRACHEAL_TUBE)
    # can produce multiple episodes from startstop extraction.  For these
    # the merge replaces the entire list when a higher tier appears.
    _MULTI_EP_DEVICES = frozenset({"MECHANICAL_VENTILATOR", "ENDOTRACHEAL_TUBE"})

    # best stores List[Dict] per device_type.
    best: Dict[str, List[Dict[str, Any]]] = {}
    best_tier: Dict[str, int] = {}

    _TIER_ORDER = {c: i for i, c in enumerate(LDA_CONFIDENCE_LEVELS)}

    def _pick(existing: Optional[Dict[str, Any]], candidate: Dict[str, Any]) -> Dict[str, Any]:
        if existing is None:
            return candidate
        e_tier = _TIER_ORDER.get(str(existing.get("source_confidence", "")), -1)
        c_tier = _TIER_ORDER.get(str(candidate.get("source_confidence", "")), -1)
        if c_tier > e_tier:
            if candidate.get("episode_days") is None and existing.get("episode_days") is not None:
                candidate = dict(candidate)
                candidate["episode_days"] = existing["episode_days"]
            return candidate
        if c_tier == e_tier:
            e_days = existing.get("episode_days") or 0
            c_days = candidate.get("episode_days") or 0
            return candidate if c_days > e_days else existing
        return existing

    def _ingest(episodes_list: List[Dict[str, Any]]) -> None:
        for ep in episodes_list:
            dt = ep["device_type"]
            ep_tier = _TIER_ORDER.get(str(ep.get("source_confidence", "")), -1)
            cur_tier = best_tier.get(dt, -1)

            if dt in _MULTI_EP_DEVICES:
                if ep_tier > cur_tier:
                    # Higher tier replaces.  Backfill episode_days from
                    # the best lower-tier episode when the new one lacks it.
                    if ep.get("episode_days") is None and dt in best:
                        old_days = max(
                            (e.get("episode_days") or 0 for e in best[dt]),
                            default=0,
                        )
                        if old_days:
                            ep = dict(ep)
                            ep["episode_days"] = old_days
                    best[dt] = [ep]
                    best_tier[dt] = ep_tier
                elif ep_tier == cur_tier:
                    best.setdefault(dt, []).append(ep)
                # Lower tier → skip
            else:
                cur = best.get(dt, [None])[0]
                winner = _pick(cur, ep)
                best[dt] = [winner]
                best_tier[dt] = _TIER_ORDER.get(str(winner.get("source_confidence", "")), -1)

    _ingest(text_derived)
    _ingest(startstop_derived)
    _ingest(structured)

    # Flatten lists; preserve stable insertion order from merge precedence.
    result: List[Dict[str, Any]] = []
    for episodes_for_device in best.values():
        result.extend(episodes_for_device)
    return result
