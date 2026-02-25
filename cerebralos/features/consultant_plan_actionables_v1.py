#!/usr/bin/env python3
"""
consultant_plan_actionables_v1  — Deterministic actionable extraction
======================================================================

This feature transforms ``consultant_plan_items_v1`` items into
protocol-friendly structured actionables.  It is a feature-first
consumer: it reads **only** from the already-assembled
``consultant_plan_items_v1`` feature output and performs deterministic
category mapping, normalization, and filtering.

Strategy
--------
1. Read ``consultant_plan_items_v1.items[]`` from the assembled features
   dict.
2. Map each item to an actionable category using ``item_type`` +
   keyword refinement on ``item_text``.
3. Normalize ``action_text`` (trim, collapse whitespace, cap length).
4. Preserve service, ts, author_name, evidence linkage.
5. Exclude non-actionable items (those that only provide context but
   no explicit clinical action).
6. Deduplicate identical (service, category, action_text_lower) tuples.

Category mapping (deterministic)
---------------------------------
``item_type`` from consultant_plan_items_v1 is the primary signal:

  =========== ===================== ===================================
  item_type    actionable category   notes
  =========== ===================== ===================================
  imaging      imaging               pass-through
  procedure    procedure             pass-through
  medication   medication            pass-through
  follow-up    follow_up             renamed (hyphen → underscore)
  activity     activity              pass-through
  discharge    discharge             pass-through
  ----------- --------------------- -----------------------------------
  recommendation  (keyword scan)     secondary keyword scan for:
                  brace_immobilization  brace|sling|collar|splint|jewett
                  monitoring_labs       labs ordered|telemetry|monitor
                  follow_up             follow.?up|f/u|return to
                  medication            start|continue|resume|hold + drug
                  imaging               CT|MRI|X-ray|TTE|ECHO|ultrasound
                  procedure             surgery|ORIF|debridement|repair
                  activity              mobiliz|ambul|weight.?bearing
                  discharge             discharg|d/c|disposition|SNF
                  recommendation        (fallback)
  =========== ===================== ===================================

Items typed as ``recommendation`` that survive keyword scanning
are kept as category ``recommendation``.  These provide clinical
context but are not categorized into a specific protocol bucket.

Non-actionable exclusion (v1)
-----------------------------
Items whose ``item_text`` is purely contextual/diagnostic are excluded
at this layer:

- Standalone diagnosis names (≤ 5 words, no verb/action keyword)
- "Okay for diet" type lines (minimal clinical action value)
  → These are **not** excluded in v1 to preserve conservative coverage.
  Refinement is planned for v2 if protocol checks need tighter signal.

Output key: ``consultant_plan_actionables_v1``

Output schema::

    {
      "actionables": [
        {
          "service": "Orthopedics",
          "ts": "2026-01-01T09:30:00",
          "author_name": "Smith, John",
          "category": "activity",
          "action_text": "May use R arm for writing/feeding, otherwise NWB on RUE",
          "source_item_type": "activity",
          "evidence": [
            {
              "role": "consultant_plan_actionable",
              "snippet": "[Orthopedics] activity:: May use R arm...",
              "raw_line_id": "<sha256>"
            }
          ]
        }, ...
      ],
      "actionable_count": <int>,
      "services_with_actionables": ["Orthopedics", ...],
      "category_counts": {
        "imaging": 2,
        "procedure": 1,
        "medication": 3,
        ...
      },
      "source_rule_id": "consultant_actionables_from_plan_items"
                       | "no_plan_items"
                       | "no_actionables_extracted",
      "warnings": [...],
      "notes": [...]
    }

Fail-closed behaviour:
  - No ``consultant_plan_items_v1`` or item_count == 0
    → actionable_count=0, source_rule_id="no_plan_items"
  - Plan items present but no actionables extracted
    → actionable_count=0, source_rule_id="no_actionables_extracted"
  - Actionables extracted
    → source_rule_id="consultant_actionables_from_plan_items"

Design:
  - Deterministic, fail-closed.
  - Feature-first: reads only from consultant_plan_items_v1.
  - No LLM, no ML, no clinical inference.
  - raw_line_id evidence preserved via passthrough from source items.
  - Explicit-only: category mapping is keyword-deterministic.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from typing import Any, Dict, List, Set, Tuple

# ── Maximum action_text length ────────────────────────────────────
_MAX_ACTION_TEXT_LEN = 200

# ── Category keyword patterns for "recommendation" item_type ──────
# These are checked only when item_type == "recommendation" to try
# to promote the item into a more specific actionable category.

_RECO_CATEGORY_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("brace_immobilization", re.compile(
        r"\b(?:brace|bracing|sling|collar|splint|Jewett|immobiliz)\b",
        re.IGNORECASE,
    )),
    ("monitoring_labs", re.compile(
        r"\b(?:labs?\s+ordered|telemetry\s+monitor|monitor\s+on\s+telemetry"
        r"|serial\s+troponin|serial\s+labs?"
        r"|TSH|free\s+T4|cortisol|proBNP|procalcitonin"
        r"|Telemetry\s+monitoring)\b",
        re.IGNORECASE,
    )),
    ("follow_up", re.compile(
        r"\b(?:follow[\s-]?up|f/u|return\s+to\s+clinic"
        r"|outpatient\s+follow|recheck|see\s+in\s+\d"
        r"|neurosurgical\s+follow)\b",
        re.IGNORECASE,
    )),
    ("medication", re.compile(
        r"\b(?:start|continue|resume|discontinue|hold|titrate"
        r"|wean|increase|decrease|taper|prescribe|administer"
        r"|Nimodipine|amoxicillin|alprazolam|memantine|donepezil"
        r"|Wellbutrin|hydralazine|Lasix|xanax)\b",
        re.IGNORECASE,
    )),
    ("imaging", re.compile(
        r"\b(?:CT\s|MRI\s|X-?ray|XR\s|CTA\b|ultrasound|ECHO\b"
        r"|TTE\b|TEE\b|angiogram|upright\s+x-?ray)\b",
        re.IGNORECASE,
    )),
    ("procedure", re.compile(
        r"\b(?:surgery|operative|OR\s|ORIF|I&D|debridement"
        r"|reduction|repair|chest\s+tube)\b",
        re.IGNORECASE,
    )),
    ("activity", re.compile(
        r"\b(?:weight[\s-]?bearing|NWB|WBAT|TDWB|PWB|FWB"
        r"|mobiliz\w*|ambul\w*|PT/OT\b|PT\s+eval|OT\s+eval"
        r"|bed\s+rest|OOB|incentive\s+spirometry"
        r"|bronchopulmonary\s+hygiene)\b",
        re.IGNORECASE,
    )),
    ("discharge", re.compile(
        r"\b(?:discharg|d/c\s+from|d/c\s+when|disposition"
        r"|home\s+with|SNF|rehab\s+facility)\b",
        re.IGNORECASE,
    )),
]

# ── Direct item_type → category mapping ────────────────────────────
_ITEM_TYPE_TO_CATEGORY = {
    "imaging": "imaging",
    "procedure": "procedure",
    "medication": "medication",
    "follow-up": "follow_up",
    "activity": "activity",
    "discharge": "discharge",
}


def _sha256(text: str) -> str:
    """Return SHA-256 hex digest of text."""
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _normalize_action_text(text: str) -> str:
    """Normalize action text: collapse whitespace, cap length."""
    s = re.sub(r"\s+", " ", text.strip())
    if len(s) > _MAX_ACTION_TEXT_LEN:
        s = s[:_MAX_ACTION_TEXT_LEN].rsplit(" ", 1)[0] + "..."
    return s


def _map_category(item_type: str, item_text: str) -> str:
    """
    Map a consultant plan item to an actionable category.

    Uses item_type as primary signal.  For 'recommendation' items,
    performs a secondary keyword scan to promote into a specific
    category if deterministically possible.

    Returns the actionable category string.
    """
    # Direct mapping for typed items
    if item_type in _ITEM_TYPE_TO_CATEGORY:
        return _ITEM_TYPE_TO_CATEGORY[item_type]

    # For "recommendation" items, attempt keyword promotion
    for category, pattern in _RECO_CATEGORY_PATTERNS:
        if pattern.search(item_text):
            return category

    # Fallback: keep as recommendation
    return "recommendation"


def _build_evidence(
    service: str,
    category: str,
    action_text: str,
    source_evidence: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Build evidence entries for an actionable.

    Passes through the raw_line_id from the source plan item evidence,
    wraps in actionable-specific role and snippet.
    """
    evidence: List[Dict[str, Any]] = []
    for src_ev in source_evidence:
        raw_line_id = src_ev.get("raw_line_id", "")
        if not raw_line_id:
            # Fallback: generate from action text
            raw_line_id = _sha256(
                f"{service}|{category}|{action_text}"
            )
        snippet = (
            f"[{service}] {category}:: "
            f"{action_text[:60]}"
        )
        evidence.append({
            "role": "consultant_plan_actionable",
            "snippet": snippet,
            "raw_line_id": raw_line_id,
        })
    # If no source evidence at all, generate minimal evidence
    if not evidence:
        evidence.append({
            "role": "consultant_plan_actionable",
            "snippet": f"[{service}] {category}:: {action_text[:60]}",
            "raw_line_id": _sha256(
                f"{service}|{category}|{action_text}"
            ),
        })
    return evidence


# ── Public API ──────────────────────────────────────────────────────

def extract_consultant_plan_actionables(
    pat_features: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Extract structured actionables from consultant_plan_items_v1.

    Parameters
    ----------
    pat_features : dict
        Assembled features dict.  Must contain ``consultant_plan_items_v1``.

    Returns
    -------
    dict with keys: actionables, actionable_count,
                    services_with_actionables, category_counts,
                    source_rule_id, warnings, notes
    """
    warnings: List[str] = []
    notes: List[str] = []

    # ── Check for consultant_plan_items_v1 ──
    cpi = pat_features.get("consultant_plan_items_v1")
    if cpi is None:
        notes.append("consultant_plan_items_v1 not available in features")
        return {
            "actionables": [],
            "actionable_count": 0,
            "services_with_actionables": [],
            "category_counts": {},
            "source_rule_id": "no_plan_items",
            "warnings": warnings,
            "notes": notes,
        }

    items = cpi.get("items", [])
    if not items or cpi.get("item_count", 0) == 0:
        src = cpi.get("source_rule_id", "unknown")
        notes.append(
            f"consultant_plan_items_v1 has 0 items "
            f"(source_rule_id={src})"
        )
        return {
            "actionables": [],
            "actionable_count": 0,
            "services_with_actionables": [],
            "category_counts": {},
            "source_rule_id": "no_plan_items",
            "warnings": warnings,
            "notes": notes,
        }

    # ── Map each plan item to an actionable ──
    all_actionables: List[Dict[str, Any]] = []

    for item in items:
        service = item.get("service", "")
        ts = item.get("ts", "")
        author_name = item.get("author_name", "")
        item_text = item.get("item_text", "")
        item_type = item.get("item_type", "recommendation")
        source_evidence = item.get("evidence", [])

        if not item_text:
            continue

        # Map to actionable category
        category = _map_category(item_type, item_text)

        # Normalize action text
        action_text = _normalize_action_text(item_text)
        if not action_text:
            continue

        # Build evidence
        evidence = _build_evidence(
            service, category, action_text, source_evidence,
        )

        all_actionables.append({
            "service": service,
            "ts": ts,
            "author_name": author_name,
            "category": category,
            "action_text": action_text,
            "source_item_type": item_type,
            "evidence": evidence,
        })

    # ── Deduplicate identical (service, category, action_text) ──
    seen: Set[Tuple[str, str, str]] = set()
    deduped: List[Dict[str, Any]] = []
    for act in all_actionables:
        key = (act["service"], act["category"], act["action_text"].lower())
        if key not in seen:
            seen.add(key)
            deduped.append(act)
        else:
            warnings.append(
                f"Duplicate actionable removed: [{act['service']}] "
                f"{act['category']}:: {act['action_text'][:50]}"
            )

    # ── Build category counts ──
    cat_counter: Counter = Counter()
    for act in deduped:
        cat_counter[act["category"]] += 1
    category_counts = dict(sorted(cat_counter.items()))

    # ── Build services list ──
    services_with_actionables = sorted(set(
        act["service"] for act in deduped
    ))

    # ── Determine source_rule_id ──
    if deduped:
        source_rule_id = "consultant_actionables_from_plan_items"
    else:
        source_rule_id = "no_actionables_extracted"
        notes.append(
            f"Processed {len(items)} plan items but no actionables "
            f"survived mapping/dedup"
        )

    notes.append(
        f"mapped {len(items)} plan items → "
        f"{len(deduped)} actionables "
        f"(from {len(all_actionables)} pre-dedup), "
        f"categories: {dict(cat_counter)}"
    )

    return {
        "actionables": deduped,
        "actionable_count": len(deduped),
        "services_with_actionables": services_with_actionables,
        "category_counts": category_counts,
        "source_rule_id": source_rule_id,
        "warnings": warnings,
        "notes": notes,
    }
