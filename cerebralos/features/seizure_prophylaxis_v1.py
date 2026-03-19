#!/usr/bin/env python3
"""
Seizure Prophylaxis — TBI Protocol Data Element

Extract seizure prophylaxis medication evidence: levetiracetam (Keppra),
phenytoin (Dilantin), and related antiepileptics used for TBI seizure
prevention.

Tracks:
- Agent detection with dose/route/frequency when available
- Home medication vs inpatient-initiated distinction
- Administration confirmation from MAR evidence
- Discontinuation detection
- Full evidence chain with raw_line_id traceability

Design:
- Deterministic, fail-closed.  No inference, no LLM, no ML.
- Requires explicit drug name mention — never infers seizure prophylaxis
  from general "anticonvulsant" language alone.
- Produces DATA NOT AVAILABLE when missing — never fabricates.
- All evidence traceable via raw_line_id (SHA-256[:16]).
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


# ── Agent patterns ──────────────────────────────────────────────────
# Each entry: (canonical_name, [compiled regex patterns])
_AGENT_PATTERNS: list[Tuple[str, list[re.Pattern[str]]]] = [
    ("levetiracetam", [
        re.compile(r"\blevetiracetam\b", re.IGNORECASE),
        re.compile(r"\blevETIRAcetam\b"),  # Epic mixed-case spelling
        re.compile(r"\bkeppra\b", re.IGNORECASE),
    ]),
    ("phenytoin", [
        re.compile(r"\bphenytoin\b", re.IGNORECASE),
        re.compile(r"\bdilantin\b", re.IGNORECASE),
        re.compile(r"\bfosphenytoin\b", re.IGNORECASE),
        re.compile(r"\bcerebyx\b", re.IGNORECASE),
    ]),
    ("valproate", [
        re.compile(r"\bvalproic\s+acid\b", re.IGNORECASE),
        re.compile(r"\bvalproate\b", re.IGNORECASE),
        re.compile(r"\bdepakote\b", re.IGNORECASE),
        re.compile(r"\bdepakene\b", re.IGNORECASE),
    ]),
    ("lacosamide", [
        re.compile(r"\blacosamide\b", re.IGNORECASE),
        re.compile(r"\bvimpat\b", re.IGNORECASE),
    ]),
]

# ── Administration confirmation signals ─────────────────────────────
_ADMIN_CONFIRM_SIGNALS: list[re.Pattern[str]] = [
    re.compile(r"\bgiven\b", re.IGNORECASE),
    re.compile(r"\badministered\b", re.IGNORECASE),
    re.compile(r"\bmedication\s+administration\b", re.IGNORECASE),
    re.compile(r"\bdose\s+given\b", re.IGNORECASE),
    re.compile(r"\blast\s+dose\b", re.IGNORECASE),
]

# ── Discontinuation signals ─────────────────────────────────────────
_DISCONTINUE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bDISCONTINUED\b"),
    re.compile(r"\bdiscontinued\b", re.IGNORECASE),
    re.compile(r"\b(?:stop|stopped)\s+(?:keppra|levetiracetam|phenytoin|dilantin)\b", re.IGNORECASE),
    re.compile(r"\b(?:keppra|levetiracetam|phenytoin|dilantin)\s+(?:was\s+)?discontinued\b", re.IGNORECASE),
    re.compile(r"\b(?:keppra|levetiracetam|phenytoin|dilantin)\s+(?:was\s+)?stopped\b", re.IGNORECASE),
]

# ── Outpatient / home medication section markers ────────────────────
_OUTPATIENT_SECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"Current\s+Outpatient\s+Medications?\s+on\s+File", re.IGNORECASE),
    re.compile(r"Outpatient\s+Medications?\s+(?:Prior|Before)", re.IGNORECASE),
    re.compile(r"Home\s+Medications?", re.IGNORECASE),
    re.compile(r"Medications?\s+Prior\s+to\s+(?:Admission|Encounter)", re.IGNORECASE),
]

# ── Dose extraction ─────────────────────────────────────────────────
_DOSE_PATTERN = re.compile(
    r"(\d[\d,]*(?:\.\d+)?)\s*(mg|MG|g|G|mcg|MCG)\b"
)
_ROUTE_PATTERN = re.compile(
    r"\b(oral|Oral|IV|intravenous|Intravenous|PO|IM|intramuscular)\b",
    re.IGNORECASE,
)
_FREQUENCY_PATTERN = re.compile(
    r"\b(BID|b\.i\.d\.|twice\s+daily|Q12H|q12h|TID|QD|daily|Q8H|q8h|Q6H)\b",
    re.IGNORECASE,
)

_DNA = "DATA_NOT_AVAILABLE"


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


def _extract_admin_timestamp(text: str, item_dt: Optional[str]) -> Optional[str]:
    """Extract precise admin timestamp from a MAR line, fallback to item dt."""
    m = re.search(
        r"\bGiven\s+(\d{1,2}/\d{1,2}/\d{4})\s+(\d{4})\b", text, re.IGNORECASE,
    )
    if m:
        try:
            dt = datetime.strptime(f"{m.group(1)} {m.group(2)}", "%m/%d/%Y %H%M")
            return dt.strftime("%Y-%m-%dT%H:%M:%S")
        except ValueError:
            pass
    m = re.search(
        r"\bGiven\s+(\d{1,2}/\d{1,2}/\d{4})\s+(\d{1,2}:\d{2})\b", text, re.IGNORECASE,
    )
    if m:
        try:
            dt = datetime.strptime(f"{m.group(1)} {m.group(2)}", "%m/%d/%Y %H:%M")
            return dt.strftime("%Y-%m-%dT%H:%M:%S")
        except ValueError:
            pass
    return item_dt


def _match_agent(line: str) -> Optional[str]:
    """Return the canonical agent name if line mentions a known agent, else None."""
    for canonical, patterns in _AGENT_PATTERNS:
        for pat in patterns:
            if pat.search(line):
                return canonical
    return None


def _has_admin_signal(line: str) -> bool:
    """Check if line contains administration confirmation language."""
    return any(p.search(line) for p in _ADMIN_CONFIRM_SIGNALS)


def _has_discontinue_signal(line: str) -> bool:
    """Check if line contains discontinuation language."""
    return any(p.search(line) for p in _DISCONTINUE_PATTERNS)


def _is_outpatient_section(line: str) -> bool:
    """Check if line marks the start of an outpatient medication section."""
    return any(p.search(line) for p in _OUTPATIENT_SECTION_PATTERNS)


def _extract_dose_info(line: str, agent: str) -> Optional[Dict[str, str]]:
    """Extract dose/route/frequency from a line if present."""
    dose_m = _DOSE_PATTERN.search(line)
    route_m = _ROUTE_PATTERN.search(line)
    freq_m = _FREQUENCY_PATTERN.search(line)
    if not dose_m:
        return None
    return {
        "agent": agent,
        "dose_text": dose_m.group(0),
        "route": _normalize_route(route_m.group(1)) if route_m else None,
        "frequency": freq_m.group(1).upper() if freq_m else None,
    }


def _normalize_route(raw: str) -> str:
    """Normalize route to standard abbreviation."""
    lower = raw.lower()
    if lower in ("oral", "po"):
        return "PO"
    if lower in ("iv", "intravenous"):
        return "IV"
    if lower in ("im", "intramuscular"):
        return "IM"
    return raw.upper()


def _earliest_ts(evidence: List[Dict[str, Any]]) -> Optional[str]:
    """Return the earliest timestamp from evidence list."""
    valid = [e["ts"] for e in evidence if e.get("ts")]
    if not valid:
        return None
    return min(valid)


def _dedup_evidence(evidence: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicate evidence by raw_line_id."""
    seen: set[str] = set()
    out: List[Dict[str, Any]] = []
    for e in evidence:
        rid = e.get("raw_line_id", "")
        if rid in seen:
            continue
        seen.add(rid)
        out.append(e)
    return out


# ── Main extractor ──────────────────────────────────────────────────

def extract_seizure_prophylaxis(
    pat_features: Dict[str, Any],
    days_json: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Extract seizure prophylaxis evidence from the patient timeline.

    Parameters
    ----------
    pat_features : dict
        The patient_features_v1 dict (used for cross-reference).
    days_json : dict
        The full patient_days_v1 dict with timeline items.

    Returns
    -------
    dict
        Seizure prophylaxis feature block with evidence chain.
    """
    days_map = days_json.get("days") or {}

    admin_evidence: List[Dict[str, Any]] = []
    mention_evidence: List[Dict[str, Any]] = []
    discontinue_evidence: List[Dict[str, Any]] = []
    dose_entries: List[Dict[str, str]] = []
    agents_found: set[str] = set()
    home_med_detected = False

    for day_iso in sorted(days_map.keys()):
        items = days_map[day_iso].get("items") or []
        for item in items:
            text = (item.get("payload") or {}).get("text", "")
            if not text:
                continue
            item_dt = item.get("dt")
            item_type = item.get("type", "")
            source_id = item.get("id", "")

            in_outpatient_section = False
            lines = text.split("\n")

            for idx, line in enumerate(lines):
                stripped = line.strip()
                if not stripped:
                    continue

                # Track outpatient section context
                if _is_outpatient_section(stripped):
                    in_outpatient_section = True

                # End of a section (crude heuristic: next section header)
                if in_outpatient_section and re.match(
                    r"^[A-Z][A-Za-z ]+:$", stripped,
                ):
                    if not _is_outpatient_section(stripped):
                        in_outpatient_section = False

                agent = _match_agent(stripped)
                if not agent:
                    continue

                agents_found.add(agent)
                raw_line_id = _make_raw_line_id(source_id, item_dt, stripped[:80])
                snip = _snippet(stripped)

                # Build a context window (current + next 3 lines) for
                # multi-line MAR entries where agent and "Given" are on
                # separate lines.
                context_lines = [stripped]
                for offset in range(1, 4):
                    if idx + offset < len(lines):
                        nl = lines[idx + offset].strip()
                        if nl:
                            context_lines.append(nl)
                context_block = " ".join(context_lines)

                # Home medication detection
                if in_outpatient_section:
                    home_med_detected = True

                # Discontinuation detection
                if _has_discontinue_signal(stripped) or _has_discontinue_signal(context_block):
                    discontinue_evidence.append({
                        "ts": item_dt,
                        "raw_line_id": raw_line_id,
                        "snippet": snip,
                        "agent": agent,
                    })
                    continue  # Don't double-count as admin/mention

                # Administration confirmation — check current line AND
                # nearby context (MAR splits agent name / "Given" across lines)
                if _has_admin_signal(stripped) or _has_admin_signal(context_block):
                    admin_ts = _extract_admin_timestamp(context_block, item_dt)
                    admin_evidence.append({
                        "ts": admin_ts,
                        "raw_line_id": raw_line_id,
                        "snippet": snip,
                        "agent": agent,
                    })
                else:
                    mention_evidence.append({
                        "ts": item_dt,
                        "raw_line_id": raw_line_id,
                        "snippet": snip,
                        "agent": agent,
                    })

                # Dose extraction (from current line or context block)
                dose = _extract_dose_info(stripped, agent)
                if not dose:
                    dose = _extract_dose_info(context_block, agent)
                if dose:
                    dose_entries.append(dose)

    # Deduplicate
    admin_evidence = _dedup_evidence(admin_evidence)
    mention_evidence = _dedup_evidence(mention_evidence)
    discontinue_evidence = _dedup_evidence(discontinue_evidence)

    # Deduplicate dose entries by (agent, dose_text, route, frequency)
    seen_doses: set[tuple] = set()
    unique_doses: List[Dict[str, str]] = []
    for d in dose_entries:
        key = (d["agent"], d["dose_text"], d.get("route"), d.get("frequency"))
        if key not in seen_doses:
            seen_doses.add(key)
            unique_doses.append(d)

    detected = bool(agents_found)
    first_mention_ts = _earliest_ts(mention_evidence + admin_evidence)
    first_admin_ts = _earliest_ts(admin_evidence)
    discontinued = len(discontinue_evidence) > 0
    discontinued_ts = _earliest_ts(discontinue_evidence)

    return {
        "detected": detected,
        "agents": sorted(agents_found),
        "home_med_present": home_med_detected,
        "first_mention_ts": first_mention_ts if detected else None,
        "first_admin_ts": first_admin_ts if detected else None,
        "discontinued": discontinued,
        "discontinued_ts": discontinued_ts if discontinued else None,
        "dose_entries": unique_doses,
        "admin_evidence_count": len(admin_evidence),
        "mention_evidence_count": len(mention_evidence),
        "evidence": {
            "admin": [
                {"ts": e["ts"], "raw_line_id": e["raw_line_id"],
                 "snippet": e["snippet"], "agent": e["agent"]}
                for e in admin_evidence
            ],
            "mention": [
                {"ts": e["ts"], "raw_line_id": e["raw_line_id"],
                 "snippet": e["snippet"], "agent": e["agent"]}
                for e in mention_evidence
            ],
            "discontinued": [
                {"ts": e["ts"], "raw_line_id": e["raw_line_id"],
                 "snippet": e["snippet"], "agent": e["agent"]}
                for e in discontinue_evidence
            ],
        },
    }
