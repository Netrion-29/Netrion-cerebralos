#!/usr/bin/env python3
"""
Trauma Category Detection — v1

Patient-level feature: determines the trauma activation category (I or II)
using a multi-source detection cascade:

  1. Evidence meta header field (``TRAUMA_CATEGORY`` from raw export header)
  2. Explicit ``TRAUMA CATEGORY: N`` / ``TRAUMA_CATEGORY: N`` lines in note body
  3. Regex-based activation text scan (original v1 behaviour)

Design:
- Deterministic, fail-closed.
- No LLM, no ML, no clinical inference.
- Ambiguous cat-I / cat-II on the same activation-text line → fail-closed.
- raw_line_id required on every stored evidence row.
- Evidence deterministically sorted by (ts is None, ts or "", raw_line_id).
- Category normalisation: "1"/"I"/"i" → "I", "2"/"II"/"ii" → "II".
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── Config loading ──────────────────────────────────────────────────

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent.parent  # cerebralos/features -> cerebralos -> repo
_RULES_PATH = _REPO_ROOT / "rules" / "features" / "category_activation_v1.json"

# ── Category normalisation map ──────────────────────────────────────
_CATEGORY_NORM: Dict[str, str] = {
    "1": "I", "i": "I", "I": "I",
    "2": "II", "ii": "II", "II": "II",
}

# ── Regex for explicit TRAUMA CATEGORY field in note body ──────────
_RE_TRAUMA_CATEGORY_FIELD = re.compile(
    r"(?i)TRAUMA[\s_]+CATEGORY\s*:\s*(\S+)",
)

# ── Regex for "category N trauma activation" or "category N alert" in prose ──
_RE_CATEGORY_N_ACTIVATION = re.compile(
    r"(?i)\bcategory\s+(\d+|I{1,2})\s+"
    r"(?:trauma\s+(?:\w+\s+)?)?(?:alert|activation|activated)\b",
)


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

def _normalize_category(raw: str) -> Optional[str]:
    """Normalise a raw category token to 'I' or 'II', or None if unknown."""
    return _CATEGORY_NORM.get(raw.strip())


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


# ── Source 1: evidence meta header ──────────────────────────────────

def _detect_from_evidence_meta(
    meta: Dict[str, Any],
) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """
    Check evidence_trauma_category injected into days_json meta by the build
    pipeline.  Returns (normalised_category, evidence_list).
    """
    raw_val = str(meta.get("evidence_trauma_category") or "").strip()
    if not raw_val or raw_val == "DATA_NOT_AVAILABLE":
        return None, []
    cat = _normalize_category(raw_val)
    if cat is None:
        return None, []
    ev = {
        "raw_line_id": _make_raw_line_id("evidence_meta", None, f"TRAUMA_CATEGORY: {raw_val}"),
        "text": f"TRAUMA_CATEGORY: {raw_val}",
        "ts": None,
        "source": "evidence_meta_header",
    }
    return cat, [ev]


# ── Source 2: explicit TRAUMA CATEGORY field in note body text ──────

def _detect_from_note_body_field(
    days_map: Dict[str, Any],
) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """
    Scan all timeline items for explicit ``TRAUMA CATEGORY: N`` or
    ``TRAUMA_CATEGORY: N`` lines.  Returns (normalised_category, evidence_list).
    First qualifying match wins (deterministic: sorted by day, then item order).
    """
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
                m = _RE_TRAUMA_CATEGORY_FIELD.search(line_stripped)
                if m:
                    cat = _normalize_category(m.group(1))
                    if cat is not None:
                        ev = {
                            "raw_line_id": _make_raw_line_id(
                                source_id, item_dt, _snippet(line_stripped, 80),
                            ),
                            "text": _snippet(line_stripped, 120),
                            "ts": item_dt,
                            "source": source_id if source_id else None,
                        }
                        return cat, [ev]
                # Also check prose form: "category 2 trauma activation"
                m2 = _RE_CATEGORY_N_ACTIVATION.search(line_stripped)
                if m2:
                    cat = _normalize_category(m2.group(1))
                    if cat is not None:
                        ev = {
                            "raw_line_id": _make_raw_line_id(
                                source_id, item_dt, _snippet(line_stripped, 80),
                            ),
                            "text": _snippet(line_stripped, 120),
                            "ts": item_dt,
                            "source": source_id if source_id else None,
                        }
                        return cat, [ev]
    return None, []


# ── Source 3: regex-based activation text scan (original v1) ────────

def _detect_from_activation_regex(
    days_map: Dict[str, Any],
    rules: Dict[str, Any],
) -> Tuple[Optional[str], List[Dict[str, Any]], List[str]]:
    """
    Original v1 logic: scan timeline items for Category I activation patterns.
    Returns (normalised_category, evidence_list, notes).
    """
    include_pats = _compile_patterns(rules.get("include_category_i_activation", []))
    exclude_pats = _compile_patterns(rules.get("exclude_context", []))
    ambig_pats = _compile_patterns(rules.get("ambiguous_block", []))

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
                    if "MISSING_RAW_LINE_ID_SKIPPED_EVIDENCE" not in notes:
                        notes.append("MISSING_RAW_LINE_ID_SKIPPED_EVIDENCE")
                    continue

                evidence.append({
                    "raw_line_id": raw_line_id,
                    "text": _snippet(line_stripped, 120),
                    "ts": item_dt,
                    "source": source_id if source_id else None,
                })

    if ambiguity_detected:
        return None, [], notes

    evidence.sort(key=_evidence_sort_key)
    detected = len(evidence) > 0
    return ("I" if detected else None), evidence, notes


# ── Core extraction ─────────────────────────────────────────────────

def build_category_activation_v1(
    days_json: Dict[str, Any],
    *,
    reporting: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Detect trauma activation category via a multi-source cascade.

    Detection priority (first match wins):
      1. Evidence meta header field (``evidence_trauma_category``)
      2. Explicit ``TRAUMA CATEGORY: N`` line in note body text
      3. Regex-based activation text scan (original v1 patterns)

    Parameters
    ----------
    days_json : dict
        The patient_days_v1.json dict (contains ``meta`` and ``days``).
    reporting : dict, optional
        Reserved for governance hooks.

    Returns
    -------
    dict
        The ``category_activation_v1`` contract::

            {
                "detected": bool,
                "category": "I" | "II" | None,
                "source_rule_id": str,
                "method": str,
                "evidence": [...],
                "notes": [...]
            }
    """
    meta = days_json.get("meta") or {}
    days_map = days_json.get("days") or {}
    rules = _load_rules()
    method = rules.get("method", "fail_closed_regex_v1")
    notes: List[str] = []

    # ── Source 1: evidence meta header ──────────────────────────
    cat, ev = _detect_from_evidence_meta(meta)
    if cat is not None:
        return {
            "detected": True,
            "category": cat,
            "source_rule_id": "evidence_meta_header",
            "method": method,
            "evidence": ev,
            "notes": notes,
        }

    # ── Source 2: explicit TRAUMA CATEGORY field in note body ───
    cat, ev = _detect_from_note_body_field(days_map)
    if cat is not None:
        return {
            "detected": True,
            "category": cat,
            "source_rule_id": "note_body_trauma_category_field",
            "method": method,
            "evidence": ev,
            "notes": notes,
        }

    # ── Source 3: regex-based activation text scan ─────────────
    cat, ev, scan_notes = _detect_from_activation_regex(days_map, rules)
    notes.extend(scan_notes)
    if cat is not None:
        return {
            "detected": True,
            "category": cat,
            "source_rule_id": "text_scan_activation_regex",
            "method": method,
            "evidence": ev,
            "notes": notes,
        }

    # ── Not detected ───────────────────────────────────────────
    return {
        "detected": False,
        "category": None,
        "source_rule_id": "not_detected",
        "method": method,
        "evidence": [],
        "notes": notes,
    }
