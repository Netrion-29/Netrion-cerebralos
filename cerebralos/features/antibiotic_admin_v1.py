#!/usr/bin/env python3
"""
Antibiotic Administration — Trauma Protocol Data Element

Extract antibiotic administration evidence: cephalosporins, glycopeptides,
beta-lactam combinations, fluoroquinolones, and other IV/PO antibiotics
administered during the trauma encounter.

Tracks:
- Agent detection with dose/route/frequency when available
- MAR administration evidence (bullet-point med lists, inline dosing lines)
- Clinical narrative mentions (progress notes, discharge summaries)
- Discontinuation / completion detection
- Allergy-section exclusion (prevents false positives from allergy lists)
- Full evidence chain with raw_line_id traceability

Design:
- Deterministic, fail-closed.  No inference, no LLM, no ML.
- Requires explicit antibiotic drug name mention — never infers from
  general "antibiotics" or "abx" language alone.
- Produces DATA NOT AVAILABLE when missing — never fabricates.
- All evidence traceable via raw_line_id (SHA-256[:16]).
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional, Tuple


# ── Agent patterns ──────────────────────────────────────────────────
# Each entry: (canonical_name, [compiled regex patterns])
# Epic mixed-case spellings (e.g. ceFAZolin, cefTRIAXone, ceFEPIme)
# are matched by case-insensitive patterns on the generic name.
_AGENT_PATTERNS: list[Tuple[str, list[re.Pattern[str]]]] = [
    # ── Cephalosporins ──
    ("cefazolin", [
        re.compile(r"\bcefazolin\b", re.IGNORECASE),
        re.compile(r"\bceFAZolin\b"),  # Epic mixed-case
        re.compile(r"\bancef\b", re.IGNORECASE),
    ]),
    ("ceftriaxone", [
        re.compile(r"\bceftriaxone\b", re.IGNORECASE),
        re.compile(r"\bcefTRIAXone\b"),  # Epic mixed-case
        re.compile(r"\brocephin\b", re.IGNORECASE),
    ]),
    ("cefepime", [
        re.compile(r"\bcefepime\b", re.IGNORECASE),
        re.compile(r"\bceFEPIme\b"),  # Epic mixed-case
        re.compile(r"\bmaxipime\b", re.IGNORECASE),
    ]),
    ("ceftazidime", [
        re.compile(r"\bceftazidime\b", re.IGNORECASE),
        re.compile(r"\bfortaz\b", re.IGNORECASE),
    ]),
    # ── Glycopeptides ──
    ("vancomycin", [
        re.compile(r"\bvancomycin\b", re.IGNORECASE),
        re.compile(r"\bvancocin\b", re.IGNORECASE),
    ]),
    # ── Beta-lactam combinations ──
    ("piperacillin-tazobactam", [
        re.compile(r"\bpiperacillin[- ]?tazobactam\b", re.IGNORECASE),
        re.compile(r"\bzosyn\b", re.IGNORECASE),
    ]),
    ("ampicillin-sulbactam", [
        re.compile(r"\bampicillin[- ]?sulbactam\b", re.IGNORECASE),
        re.compile(r"\bunasyn\b", re.IGNORECASE),
    ]),
    # ── Carbapenems ──
    ("meropenem", [
        re.compile(r"\bmeropenem\b", re.IGNORECASE),
        re.compile(r"\bmerrem\b", re.IGNORECASE),
    ]),
    # ── Nitroimidazoles ──
    ("metronidazole", [
        re.compile(r"\bmetronidazole\b", re.IGNORECASE),
        re.compile(r"\bflagyl\b", re.IGNORECASE),
    ]),
    # ── Fluoroquinolones ──
    ("levofloxacin", [
        re.compile(r"\blevofloxacin\b", re.IGNORECASE),
        re.compile(r"\blevaquin\b", re.IGNORECASE),
    ]),
    ("ciprofloxacin", [
        re.compile(r"\bciprofloxacin\b", re.IGNORECASE),
        re.compile(r"\bcipro\b", re.IGNORECASE),
    ]),
    # ── Lincosamides ──
    ("clindamycin", [
        re.compile(r"\bclindamycin\b", re.IGNORECASE),
        re.compile(r"\bcleocin\b", re.IGNORECASE),
    ]),
    # ── Aminoglycosides ──
    ("gentamicin", [
        re.compile(r"\bgentamicin\b", re.IGNORECASE),
        re.compile(r"\bgaramycin\b", re.IGNORECASE),
    ]),
    ("tobramycin", [
        re.compile(r"\btobramycin\b", re.IGNORECASE),
    ]),
    # ── Macrolides ──
    ("azithromycin", [
        re.compile(r"\bazithromycin\b", re.IGNORECASE),
        re.compile(r"\bzithromax\b", re.IGNORECASE),
        re.compile(r"\bz-?pack\b", re.IGNORECASE),
    ]),
    # ── Tetracyclines ──
    ("doxycycline", [
        re.compile(r"\bdoxycycline\b", re.IGNORECASE),
    ]),
    # ── Oxazolidinones ──
    ("linezolid", [
        re.compile(r"\blinezolid\b", re.IGNORECASE),
        re.compile(r"\bzyvox\b", re.IGNORECASE),
    ]),
    # ── Penicillins (standalone) ──
    ("ampicillin", [
        # Match standalone ampicillin but NOT ampicillin-sulbactam
        re.compile(r"\bampicillin\b(?!\s*[-/]?\s*sulbactam)", re.IGNORECASE),
    ]),
    ("nafcillin", [
        re.compile(r"\bnafcillin\b", re.IGNORECASE),
    ]),
    ("oxacillin", [
        re.compile(r"\boxacillin\b", re.IGNORECASE),
    ]),
]

# ── Allergy section markers (lines in these sections are excluded) ──
_ALLERGY_SECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^Allerg(?:ies|y)\s*$", re.IGNORECASE),
    re.compile(r"^Allergen\s+Reactions?\s*$", re.IGNORECASE),
    re.compile(r"^Allergy\s+(?:List|Review)", re.IGNORECASE),
]

# ── Administration confirmation signals ─────────────────────────────
_ADMIN_CONFIRM_SIGNALS: list[re.Pattern[str]] = [
    re.compile(r"\bgiven\b", re.IGNORECASE),
    re.compile(r"\badministered\b", re.IGNORECASE),
    re.compile(r"\bmedication\s+administration\b", re.IGNORECASE),
    re.compile(r"\bdose\s+given\b", re.IGNORECASE),
    re.compile(r"\blast\s+dose\b", re.IGNORECASE),
]

# ── Discontinuation / completion signals ────────────────────────────
_DISCONTINUE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bDISCONTINUED\b"),
    re.compile(r"\bdiscontinued\b", re.IGNORECASE),
    re.compile(r"\bcompleted\s+course\b", re.IGNORECASE),
    re.compile(r"\bcompleted\b.*\b(?:antibiotic|abx)\b", re.IGNORECASE),
    re.compile(r"\b(?:antibiotic|abx)\b.*\bcompleted\b", re.IGNORECASE),
]

# ── Negative MAR statuses ──────────────────────────────────────────
_NEGATIVE_STATUS_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bNot\s+Given\b", re.IGNORECASE),
    re.compile(r"\bPatient\s+Refused\b", re.IGNORECASE),
    re.compile(r"\bHeld\b"),
]

# ── Dose extraction ─────────────────────────────────────────────────
_DOSE_PATTERN = re.compile(
    r"(\d[\d,]*(?:\.\d+)?)\s*(mg|MG|g|G|gm|GM|mcg|MCG)\b"
)
_ROUTE_PATTERN = re.compile(
    r"\b(oral|Oral|IV|intravenous|Intravenous|PO|IM|intramuscular|IVPB)\b",
    re.IGNORECASE,
)
_FREQUENCY_PATTERN = re.compile(
    r"\b(BID|b\.i\.d\.|twice\s+daily|Q12H|q12h|TID|QD|daily|Q8H|q8h|"
    r"Q6H|q6h|Q24H|q24h|Q18H|q18h|EVERY\s+\d+\s+HOURS?|"
    r"3\s+times\s+per\s+day|once\s+daily)\b",
    re.IGNORECASE,
)

# ── MAR structured format: bullet-point multi-line entries ──────────
# Pattern for lines like:
#   ceFAZolin 2 g in sodium chloride 0.9% 50mL IVPB  3 times per day
_INLINE_MED_PATTERN = re.compile(
    r"^(?:\[START\s+ON\s+[\d/]+\]\s*)?"
    r"([\w\-]+(?:\s*\([\w\s]+\))?(?:\s+IV)?)\s+"
    r"(\d[\d,]*(?:\.\d+)?)\s*(mg|g|gm|mcg)\b",
    re.IGNORECASE,
)

# Start-date pattern: [START ON MM/DD/YYYY]
_START_DATE_PATTERN = re.compile(
    r"\[START\s+ON\s+(\d{1,2}/\d{1,2}/\d{4})\]", re.IGNORECASE,
)

# Dose/Frequency/Start/End table header pattern
_ORDER_TABLE_PATTERN = re.compile(
    r"Dose\s+Frequency\s+Start\s+End", re.IGNORECASE,
)


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


def _match_agent(line: str) -> Optional[str]:
    """Return the canonical agent name if line mentions a known antibiotic, else None."""
    for canonical, patterns in _AGENT_PATTERNS:
        for pat in patterns:
            if pat.search(line):
                return canonical
    return None


def _has_negative_status(line: str) -> bool:
    """Check if line contains a negative MAR status."""
    return any(p.search(line) for p in _NEGATIVE_STATUS_PATTERNS)


def _has_admin_signal(line: str) -> bool:
    """Check if line contains administration confirmation language."""
    return any(p.search(line) for p in _ADMIN_CONFIRM_SIGNALS)


def _has_discontinue_signal(line: str) -> bool:
    """Check if line contains discontinuation / completion language."""
    return any(p.search(line) for p in _DISCONTINUE_PATTERNS)


def _is_allergy_section(line: str) -> bool:
    """Check if line marks the start of an allergy section."""
    return any(p.search(line) for p in _ALLERGY_SECTION_PATTERNS)


def _extract_dose_info(line: str, agent: str) -> Optional[Dict[str, Optional[str]]]:
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
        "frequency": _normalize_frequency(freq_m.group(0)) if freq_m else None,
    }


def _normalize_route(raw: str) -> str:
    """Normalize route to standard abbreviation."""
    lower = raw.lower()
    if lower in ("oral", "po"):
        return "PO"
    if lower in ("iv", "intravenous", "ivpb"):
        return "IV"
    if lower in ("im", "intramuscular"):
        return "IM"
    return raw.upper()


def _normalize_frequency(raw: str) -> str:
    """Normalize frequency to a consistent representation."""
    upper = raw.upper().strip()
    # Normalize "3 times per day" → "TID", "EVERY 8 HOURS" → "Q8H", etc.
    if re.match(r"3\s+TIMES\s+PER\s+DAY", upper):
        return "Q8H"
    if re.match(r"ONCE\s+DAILY", upper):
        return "DAILY"
    m = re.match(r"EVERY\s+(\d+)\s+HOURS?", upper)
    if m:
        return f"Q{m.group(1)}H"
    if upper in ("B.I.D.", "TWICE DAILY"):
        return "BID"
    return upper


def _extract_admin_timestamp(text: str, item_dt: Optional[str]) -> Optional[str]:
    """Extract precise admin timestamp from a MAR line, fallback to item dt."""
    # Given MM/DD/YYYY HHMM
    m = re.search(
        r"\bGiven\s+(\d{1,2}/\d{1,2}/\d{4})\s+(\d{4})\b", text, re.IGNORECASE,
    )
    if m:
        try:
            from datetime import datetime
            dt = datetime.strptime(f"{m.group(1)} {m.group(2)}", "%m/%d/%Y %H%M")
            return dt.strftime("%Y-%m-%dT%H:%M:%S")
        except ValueError:
            pass
    # Given MM/DD/YYYY HH:MM
    m = re.search(
        r"\bGiven\s+(\d{1,2}/\d{1,2}/\d{4})\s+(\d{1,2}:\d{2})\b", text, re.IGNORECASE,
    )
    if m:
        try:
            from datetime import datetime
            dt = datetime.strptime(f"{m.group(1)} {m.group(2)}", "%m/%d/%Y %H:%M")
            return dt.strftime("%Y-%m-%dT%H:%M:%S")
        except ValueError:
            pass
    return item_dt


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

def extract_antibiotic_admin(
    pat_features: Dict[str, Any],
    days_json: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Extract antibiotic administration evidence from the patient timeline.

    Parameters
    ----------
    pat_features : dict
        The patient_features_v1 dict (used for cross-reference).
    days_json : dict
        The full patient_days_v1 dict with timeline items.

    Returns
    -------
    dict
        Antibiotic administration feature block with evidence chain.
    """
    days_map = days_json.get("days") or {}

    admin_evidence: List[Dict[str, Any]] = []
    mention_evidence: List[Dict[str, Any]] = []
    discontinue_evidence: List[Dict[str, Any]] = []
    dose_entries: List[Dict[str, Optional[str]]] = []
    agents_found: set[str] = set()

    for day_iso in sorted(days_map.keys()):
        items = days_map[day_iso].get("items") or []
        for item in items:
            text = (item.get("payload") or {}).get("text", "")
            if not text:
                continue
            item_dt = item.get("dt")
            source_id = item.get("id", "")

            in_allergy_section = False
            lines = text.split("\n")

            for idx, line in enumerate(lines):
                stripped = line.strip()
                if not stripped:
                    continue

                # Track allergy section context — antibiotics listed here
                # are allergies, NOT administrations.
                if _is_allergy_section(stripped):
                    in_allergy_section = True
                    continue

                # Exit allergy section on next section header
                if in_allergy_section and re.match(
                    r"^[A-Z][A-Za-z ]+:?\s*$", stripped,
                ):
                    if not _is_allergy_section(stripped):
                        in_allergy_section = False

                # Skip lines inside allergy sections
                if in_allergy_section:
                    continue

                agent = _match_agent(stripped)
                if not agent:
                    continue

                agents_found.add(agent)
                raw_line_id = _make_raw_line_id(source_id, item_dt, stripped[:80])
                snip = _snippet(stripped)

                # Build context window (current + next 4 lines) for
                # multi-line MAR entries where agent, dose, route, freq
                # are on separate lines.
                context_lines = [stripped]
                for offset in range(1, 5):
                    if idx + offset < len(lines):
                        nl = lines[idx + offset].strip()
                        if nl:
                            context_lines.append(nl)
                context_block = " ".join(context_lines)

                # Discontinuation / completion detection
                if _has_discontinue_signal(stripped) or _has_discontinue_signal(context_block):
                    discontinue_evidence.append({
                        "ts": item_dt,
                        "raw_line_id": raw_line_id,
                        "snippet": snip,
                        "agent": agent,
                    })
                    continue  # Don't double-count

                # Negative MAR status — skip as admin
                if _has_negative_status(stripped) or _has_negative_status(context_block):
                    mention_evidence.append({
                        "ts": item_dt,
                        "raw_line_id": raw_line_id,
                        "snippet": snip,
                        "agent": agent,
                    })
                    continue

                # Administration confirmation
                if _has_admin_signal(stripped) or _has_admin_signal(context_block):
                    admin_ts = _extract_admin_timestamp(context_block, item_dt)
                    admin_evidence.append({
                        "ts": admin_ts,
                        "raw_line_id": raw_line_id,
                        "snippet": snip,
                        "agent": agent,
                    })
                else:
                    # MAR structured entries (bullet-point med lists)
                    # count as mention — dosing info present but no
                    # explicit "Given" confirmation.
                    mention_evidence.append({
                        "ts": item_dt,
                        "raw_line_id": raw_line_id,
                        "snippet": snip,
                        "agent": agent,
                    })

                # Dose extraction from current line or multi-line context
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
    unique_doses: List[Dict[str, Optional[str]]] = []
    for d in dose_entries:
        key = (d["agent"], d["dose_text"], d.get("route"), d.get("frequency"))
        if key not in seen_doses:
            seen_doses.add(key)
            unique_doses.append(d)

    detected = bool(agents_found)
    first_mention_ts = _earliest_ts(mention_evidence + admin_evidence)
    first_admin_ts = _earliest_ts(admin_evidence)
    discontinued = len(discontinue_evidence) > 0

    return {
        "detected": detected,
        "agents": sorted(agents_found),
        "first_mention_ts": first_mention_ts if detected else None,
        "first_admin_ts": first_admin_ts if detected else None,
        "discontinued": discontinued,
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
