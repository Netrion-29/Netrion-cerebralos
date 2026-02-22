#!/usr/bin/env python3
"""
Category I Trauma Activation Detection — v1

Patient-level feature: scans all evidence lines across every day in
patient_days_v1.json and emits a single feature blob indicating
whether a Category I trauma activation was detected.

Design:
- Deterministic, fail-closed.
- No LLM, no ML, no clinical inference.
- Ambiguous cat-I / cat-II on the same line → fail-closed (detected=false).
- raw_line_id required on every stored evidence row.
- Evidence deterministically sorted by (ts is None, ts or "", raw_line_id).
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── Config loading ──────────────────────────────────────────────────

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent.parent  # cerebralos/features -> cerebralos -> repo
_RULES_PATH = _REPO_ROOT / "rules" / "features" / "category_activation_v1.json"


def _load_rules() -> Dict[str, Any]:
    """Load the rules JSON, fail-closed on missing/malformed."""
    if not _RULES_PATH.is_file():
        raise FileNotFoundError(
            f"Required rule file not found: {_RULES_PATH}"
        )
    with open(_RULES_PATH, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(
            f"Rule file must be a JSON object, got {type(data).__name__}"
        )
    return data


def _compile_patterns(raw_list: List[str]) -> List[re.Pattern[str]]:
    """Compile a list of regex strings into Pattern objects (case-insensitive)."""
    return [re.compile(p, re.IGNORECASE) for p in raw_list]


# ── Helpers ─────────────────────────────────────────────────────────

def _make_raw_line_id(source_id: Any, dt: Optional[str], preview: str) -> str:
    """Deterministic raw_line_id — SHA-256[:16] of evidence coordinates."""
    key = f"{source_id or ''}|{dt or ''}|{preview or ''}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _snippet(text: str, max_len: int = 80) -> str:
    """Trim text to a short deterministic snippet."""
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[:max_len] + "…"


def _evidence_sort_key(ev: Dict[str, Any]) -> tuple:
    """
    Deterministic sort key: (ts_is_none, ts_or_empty, raw_line_id).
    Rows with ts sort before rows without.
    """
    ts = ev.get("ts")
    return (ts is None, ts or "", ev.get("raw_line_id", ""))


# ── Core extraction ─────────────────────────────────────────────────

def build_category_activation_v1(
    days_json: Dict[str, Any],
    *,
    reporting: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Extract Category I Trauma Activation evidence from the patient timeline.

    Parameters
    ----------
    days_json : dict
        The patient_days_v1.json dict (contains ``days`` → items with raw
        text and timestamps).
    reporting : dict, optional
        Shared reporting accumulator (unused currently; reserved for future
        governance hooks).

    Returns
    -------
    dict
        The ``category_activation_v1`` contract::

            {
                "detected": bool,
                "category": "I" | None,
                "method": "fail_closed_regex_v1",
                "evidence": [...],
                "notes": [...]
            }
    """
    rules = _load_rules()
    method = rules.get("method", "fail_closed_regex_v1")

    include_pats = _compile_patterns(rules.get("include_category_i_activation", []))
    exclude_pats = _compile_patterns(rules.get("exclude_context", []))
    ambig_pats = _compile_patterns(rules.get("ambiguous_block", []))

    days_map = days_json.get("days") or {}

    evidence: List[Dict[str, Any]] = []
    notes: List[str] = []
    ambiguity_detected = False

    for day_iso in sorted(days_map.keys()):
        day_info = days_map[day_iso]
        items: List[Dict[str, Any]] = day_info.get("items") or []

        for item in items:
            item_dt: Optional[str] = item.get("dt")
            source_id = item.get("source_id", "")
            text = (item.get("payload") or {}).get("text", "")
            if not text:
                continue

            for line in text.split("\n"):
                line_stripped = line.strip()
                if not line_stripped:
                    continue

                # ── Step 1: ambiguous block check (fail-closed) ───
                if any(p.search(line_stripped) for p in ambig_pats):
                    ambiguity_detected = True
                    if "AMBIGUOUS_CAT_I_CAT_II_SAME_LINE" not in notes:
                        notes.append("AMBIGUOUS_CAT_I_CAT_II_SAME_LINE")
                    # Do NOT store evidence for this ambiguous line.
                    # Fail-closed: even if other lines qualify, we abort.
                    continue

                # ── Step 2: inclusion check ───────────────────────
                if not any(p.search(line_stripped) for p in include_pats):
                    continue

                # ── Step 3: exclusion check ───────────────────────
                if any(p.search(line_stripped) for p in exclude_pats):
                    continue

                # ── Qualifying evidence ───────────────────────────
                raw_line_id = _make_raw_line_id(
                    source_id, item_dt, _snippet(line_stripped, 80),
                )

                if not raw_line_id:
                    # Should not happen with SHA-256, but guard anyway.
                    if "MISSING_RAW_LINE_ID_SKIPPED_EVIDENCE" not in notes:
                        notes.append("MISSING_RAW_LINE_ID_SKIPPED_EVIDENCE")
                    continue

                evidence.append({
                    "raw_line_id": raw_line_id,
                    "text": _snippet(line_stripped, 120),
                    "ts": item_dt,
                    "source": source_id if source_id else None,
                })

    # ── Fail-closed on ambiguity ────────────────────────────────
    if ambiguity_detected:
        return {
            "detected": False,
            "category": None,
            "method": method,
            "evidence": [],
            "notes": notes,
        }

    # ── Deterministic evidence ordering ─────────────────────────
    evidence.sort(key=_evidence_sort_key)

    detected = len(evidence) > 0

    return {
        "detected": detected,
        "category": "I" if detected else None,
        "method": method,
        "evidence": evidence,
        "notes": notes,
    }
