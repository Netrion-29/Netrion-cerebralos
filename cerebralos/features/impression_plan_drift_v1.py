#!/usr/bin/env python3
"""
Impression/Plan Drift Diff v1 — Roadmap Step 6

Deterministic day-to-day comparison of Impression/Plan content extracted
from PHYSICIAN_NOTE and TRAUMA_HP items.

Source selection:
  For each day, extract all IMPRESSION and Assessment/Plan sections from
  PHYSICIAN_NOTE and TRAUMA_HP items.  Normalise bullets, then diff
  consecutive days to surface added / removed / persisted items.

Normalisation pipeline (deterministic, no LLM):
  1. Lowercase
  2. Strip leading bullet markers (•, -, *, 1., 2., …)
  3. Collapse whitespace
  4. Replace bare date-like tokens (``MM/DD/YYYY``, ``MM/DD/YY``) with
     ``<DATE>``
  5. Replace standalone numeric tokens (vitals / labs) with ``<NUM>``
  6. Strip trailing punctuation

Diff algorithm:
  Stable sentence hashing (SHA-256 truncated to 16 hex).  Comparison is
  set-based on normalised hashes:
  - ``added_items``: in current day but not previous day
  - ``removed_items``: in previous day but not current day
  - ``persisted_items``: in both

Drift metric:
  ``drift_ratio = (len(added) + len(removed)) / max(len(prev_items), 1)``

Output key: ``impression_plan_drift_v1`` (under top-level ``features`` dict)

Output schema::

    {
      "drift_detected": true | false | "DATA NOT AVAILABLE",
      "days_compared_count": <int>,
      "days_with_impression_count": <int>,
      "drift_events": [
        {
          "date": "<YYYY-MM-DD>",
          "prev_date": "<YYYY-MM-DD>",
          "source_note_types": ["PHYSICIAN_NOTE", ...],
          "added_items": ["<normalised text>", ...],
          "removed_items": ["<normalised text>", ...],
          "persisted_count": <int>,
          "drift_ratio": <float>,
          "evidence": [
            {
              "raw_line_id": "<sha256 hex>",
              "day": "<YYYY-MM-DD>",
              "source_type": "<item type>",
              "snippet": "<first 120 chars>"
            }, ...
          ]
        }, ...
      ],
      "evidence": [ ... ],
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
from typing import Any, Dict, List, Optional, Tuple

_DNA = "DATA NOT AVAILABLE"

# ── Section boundary patterns ───────────────────────────────────────

# "Impression:" or "IMPRESSION:" at the start of a line.
RE_IMPRESSION_START = re.compile(
    r"^\s*(Impression|IMPRESSION)\s*[:.]?\s*$|"
    r"^\s*(Impression|IMPRESSION)\s*[:]\s*\S",
    re.IGNORECASE | re.MULTILINE,
)

# "Narrative & Impression" header — the impression section follows.
RE_NARRATIVE_IMPRESSION = re.compile(
    r"^\s*Narrative\s*&?\s*Impression\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# "Assessment/Plan" or "Assessment and Plan" header.
RE_ASSESSMENT_PLAN_START = re.compile(
    r"^\s*Assessment\s*/?\s*Plan\s*[:.]?\s*$|"
    r"^\s*Assessment\s+and\s+Plan\s*[:.]?\s*$|"
    r"^\s*A\s*/\s*P\s*[:.]?\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# Section terminators — when we hit one of these headers, the
# impression/plan block has ended.
RE_SECTION_END = re.compile(
    r"^\s*("
    r"Electronically\s+signed|"
    r"Exam\s+Ended|"
    r"Order\s+Details|"
    r"Reading\s+Physician|"
    r"Signing\s+Physician|"
    r"Result\s+Care|"
    r"Patient\s+Communication|"
    r"______|"
    r"Plan\s*:|"         # if we were in an "Impression" block, "Plan:" ends it
    r"Disposition\s*:|"
    r"Assessment\s*/\s*Plan|"
    r"Assessment\s+and\s+Plan|"
    r"A\s*/\s*P\s*:|"
    r"Attestation|"
    r"Back\s+to\s+Top"
    r")\s*",
    re.IGNORECASE,
)

# Assessment/Plan ends at these additional boundaries.
RE_AP_SECTION_END = re.compile(
    r"^\s*("
    r"Electronically\s+signed|"
    r"Attestation|"
    r"I\s+have\s+seen\s+and\s+examined|"
    r"______|"
    r"Exam\s+Ended|"
    r"Back\s+to\s+Top"
    r")\s*",
    re.IGNORECASE,
)

# ── Normalisation helpers ───────────────────────────────────────────

# Leading bullet / number marker.
RE_BULLET_MARKER = re.compile(
    r"^\s*(?:[-•*]|\d{1,2}[.)]\s*)\s*"
)

# Date patterns: MM/DD/YYYY, MM/DD/YY, YYYY-MM-DD.
RE_DATE_TOKEN = re.compile(
    r"\b\d{1,2}/\d{1,2}/\d{2,4}\b|"
    r"\b\d{4}-\d{2}-\d{2}\b"
)

# Standalone numeric tokens (integers, decimals, percentages).
RE_NUM_TOKEN = re.compile(
    r"\b\d+(?:\.\d+)?%?\b"
)

# Trailing punctuation.
RE_TRAILING_PUNCT = re.compile(r"[.,;:]+$")

# Whitespace collapse.
RE_WHITESPACE = re.compile(r"\s+")


def _normalise_item(text: str) -> str:
    """
    Apply the normalisation pipeline to a single impression/plan bullet.

    Returns a normalised string suitable for stable hashing.
    Idempotent: normalising an already-normalised string returns the same result.
    """
    s = text.strip()
    # 1. Strip leading bullet markers
    s = RE_BULLET_MARKER.sub("", s)
    # 2. Lowercase
    s = s.lower()
    # 3. Replace dates with <date> (lowercase for idempotency)
    s = RE_DATE_TOKEN.sub("<date>", s)
    # 4. Replace numbers with <num> (lowercase for idempotency)
    #    Protect existing <date>/<num> tokens from being re-processed
    s = re.sub(r'<date>', '\x00DATE\x00', s)
    s = re.sub(r'<num>', '\x00NUM\x00', s)
    s = RE_NUM_TOKEN.sub("<num>", s)
    s = s.replace('\x00DATE\x00', '<date>')
    s = s.replace('\x00NUM\x00', '<num>')
    # 5. Collapse whitespace
    s = RE_WHITESPACE.sub(" ", s).strip()
    # 6. Strip trailing punctuation
    s = RE_TRAILING_PUNCT.sub("", s).strip()
    return s


def _stable_hash(text: str) -> str:
    """SHA-256 truncated to 16 hex chars for normalised-text identity."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# ── Evidence helpers ────────────────────────────────────────────────

def _make_raw_line_id(
    source_type: str,
    source_id: Optional[str],
    line_text: str,
) -> str:
    """Build a deterministic raw_line_id from evidence coordinates."""
    payload = f"{source_type}|{source_id or ''}|{line_text.strip()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# ── Section extraction ──────────────────────────────────────────────

def _extract_impression_items(text: str) -> List[str]:
    """
    Extract impression bullet items from a note text block.

    Returns a list of non-empty stripped lines from IMPRESSION sections.
    """
    lines = text.split("\n")
    items: List[str] = []
    in_section = False

    for i, line in enumerate(lines):
        stripped = line.strip()
        ll = stripped.lower()

        # Check for section start
        if (re.match(r"^impression\s*[:.]?", ll)
                or re.match(r"^narrative\s*&?\s*impression\s*$", ll)):
            in_section = True
            # If the line has content after "IMPRESSION: <text>", capture it
            after = re.sub(r"^(?:impression|narrative\s*&?\s*impression)\s*[:.]?\s*",
                           "", stripped, flags=re.IGNORECASE).strip()
            if after:
                items.append(after)
            continue

        if in_section:
            # Check for section terminator
            if RE_SECTION_END.match(line):
                in_section = False
                continue
            # Skip empty lines within section (don't terminate)
            if not stripped:
                continue
            items.append(stripped)

    return items


def _extract_assessment_plan_items(text: str) -> List[str]:
    """
    Extract Assessment/Plan bullet items from a note text block.

    Returns a list of non-empty stripped lines from A/P sections.
    """
    lines = text.split("\n")
    items: List[str] = []
    in_section = False

    for i, line in enumerate(lines):
        stripped = line.strip()
        ll = stripped.lower()

        # Check for A/P section start
        if (re.match(r"^assessment\s*/?\s*plan\s*[:.]?\s*$", ll)
                or re.match(r"^assessment\s+and\s+plan\s*[:.]?\s*$", ll)
                or re.match(r"^a\s*/\s*p\s*[:.]?\s*$", ll)):
            in_section = True
            continue

        if in_section:
            if RE_AP_SECTION_END.match(line):
                in_section = False
                continue
            if not stripped:
                continue
            items.append(stripped)

    return items


def _extract_all_impression_plan_from_note(
    text: str,
) -> List[str]:
    """
    Extract all Impression and Assessment/Plan items from one note.

    Items from both sections are merged and deduplicated (by exact text)
    preserving order.
    """
    impression = _extract_impression_items(text)
    ap = _extract_assessment_plan_items(text)

    seen: set[str] = set()
    result: List[str] = []
    for item in impression + ap:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


# ── Per-day aggregation ─────────────────────────────────────────────

def _collect_daily_impressions(
    days_data: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
    """
    Walk the timeline and collect impression/plan items per day.

    Returns::

        {
            "YYYY-MM-DD": {
                "items": ["raw bullet 1", "raw bullet 2", ...],
                "normalised": ["normalised 1", ...],
                "hashes": {"<hash>": "normalised text", ...},
                "source_note_types": {"PHYSICIAN_NOTE", ...},
                "evidence": [ { raw_line_id, day, source_type, snippet }, ... ],
            },
            ...
        }
    """
    days_map = days_data.get("days") or {}
    result: Dict[str, Dict[str, Any]] = {}

    for day_iso in sorted(days_map.keys()):
        if day_iso == "__UNDATED__":
            continue
        day_info = days_map[day_iso]
        all_items: List[str] = []
        note_types: set[str] = set()
        evidence: List[Dict[str, Any]] = []

        for it in day_info.get("items") or []:
            item_type = it.get("type", "")
            if item_type not in ("PHYSICIAN_NOTE", "TRAUMA_HP"):
                continue
            text = (it.get("payload") or {}).get("text", "")
            if not text:
                continue
            extracted = _extract_all_impression_plan_from_note(text)
            if extracted:
                note_types.add(item_type)
                for bullet in extracted:
                    all_items.append(bullet)
                    evidence.append({
                        "raw_line_id": _make_raw_line_id(
                            item_type, it.get("dt"), bullet,
                        ),
                        "day": day_iso,
                        "source_type": item_type,
                        "snippet": bullet[:120],
                    })

        if all_items:
            normalised = [_normalise_item(b) for b in all_items]
            # Deduplicate by normalised hash (keep unique normalised items)
            hashes: Dict[str, str] = {}
            unique_normalised: List[str] = []
            for norm in normalised:
                h = _stable_hash(norm)
                if h not in hashes:
                    hashes[h] = norm
                    unique_normalised.append(norm)

            result[day_iso] = {
                "items": all_items,
                "normalised": unique_normalised,
                "hashes": hashes,
                "source_note_types": note_types,
                "evidence": evidence,
            }

    return result


# ── Drift computation ───────────────────────────────────────────────

def _compute_drift_events(
    daily_impressions: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Compare consecutive days and produce drift_events list.

    Only days that actually have impression/plan content participate.
    """
    dated_keys = sorted(daily_impressions.keys())
    if len(dated_keys) < 2:
        return []

    events: List[Dict[str, Any]] = []
    for i in range(1, len(dated_keys)):
        prev_day = dated_keys[i - 1]
        curr_day = dated_keys[i]

        prev_data = daily_impressions[prev_day]
        curr_data = daily_impressions[curr_day]

        prev_hashes = set(prev_data["hashes"].keys())
        curr_hashes = set(curr_data["hashes"].keys())

        added_hashes = curr_hashes - prev_hashes
        removed_hashes = prev_hashes - curr_hashes
        persisted_hashes = prev_hashes & curr_hashes

        added_items = [curr_data["hashes"][h] for h in sorted(added_hashes)]
        removed_items = [prev_data["hashes"][h] for h in sorted(removed_hashes)]

        drift_ratio = (
            (len(added_items) + len(removed_items))
            / max(len(prev_data["normalised"]), 1)
        )

        # Merge evidence from both days for this comparison
        pair_evidence = []
        for ev in curr_data["evidence"]:
            pair_evidence.append(ev)
        for ev in prev_data["evidence"]:
            pair_evidence.append(ev)

        events.append({
            "date": curr_day,
            "prev_date": prev_day,
            "source_note_types": sorted(
                curr_data["source_note_types"] | prev_data["source_note_types"]
            ),
            "added_items": added_items,
            "removed_items": removed_items,
            "persisted_count": len(persisted_hashes),
            "drift_ratio": round(drift_ratio, 4),
            "evidence": pair_evidence,
        })

    return events


# ── Public API ──────────────────────────────────────────────────────

def extract_impression_plan_drift(
    pat_features: Dict[str, Any],
    days_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Extract day-to-day Impression/Plan drift.

    Parameters
    ----------
    pat_features : dict
        ``{"days": {day_iso: {feature_key: ...}}}`` — per-day features
        assembled so far (not directly used, kept for API consistency).
    days_data : dict
        Full ``patient_days_v1.json`` content (raw timeline).

    Returns
    -------
    dict
        Impression/Plan drift result (see module docstring for schema).
    """
    notes: List[str] = []
    warnings: List[str] = []

    # ── Collect daily impressions from raw timeline ─────────────
    daily_impressions = _collect_daily_impressions(days_data)

    days_with_impression = len(daily_impressions)

    # ── Fail-closed: insufficient evidence ──────────────────────
    if days_with_impression == 0:
        notes.append(
            "DATA NOT AVAILABLE: no Impression/Plan sections found "
            "in any PHYSICIAN_NOTE or TRAUMA_HP items"
        )
        return {
            "drift_detected": _DNA,
            "days_compared_count": 0,
            "days_with_impression_count": 0,
            "drift_events": [],
            "evidence": [],
            "notes": notes,
            "warnings": warnings,
        }

    if days_with_impression == 1:
        only_day = list(daily_impressions.keys())[0]
        day_data = daily_impressions[only_day]
        notes.append(
            f"Only 1 day with Impression/Plan content ({only_day}); "
            "drift comparison requires >= 2 days"
        )
        return {
            "drift_detected": _DNA,
            "days_compared_count": 0,
            "days_with_impression_count": 1,
            "drift_events": [],
            "evidence": day_data["evidence"],
            "notes": notes,
            "warnings": warnings,
        }

    # ── Compute drift events ────────────────────────────────────
    drift_events = _compute_drift_events(daily_impressions)
    days_compared = len(drift_events)

    # drift_detected: True if any event has added or removed items
    drift_detected = any(
        len(ev["added_items"]) > 0 or len(ev["removed_items"]) > 0
        for ev in drift_events
    )

    # ── Aggregate all evidence ──────────────────────────────────
    all_evidence: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    for day_iso in sorted(daily_impressions.keys()):
        for ev in daily_impressions[day_iso]["evidence"]:
            eid = ev["raw_line_id"]
            if eid not in seen_ids:
                seen_ids.add(eid)
                all_evidence.append(ev)

    # ── Warnings for large drift ────────────────────────────────
    for ev in drift_events:
        if ev["drift_ratio"] > 0.5:
            warnings.append(
                f"high_drift_ratio: {ev['prev_date']}->{ev['date']} "
                f"ratio={ev['drift_ratio']}"
            )

    return {
        "drift_detected": drift_detected,
        "days_compared_count": days_compared,
        "days_with_impression_count": days_with_impression,
        "drift_events": drift_events,
        "evidence": all_evidence,
        "notes": notes,
        "warnings": warnings,
    }
