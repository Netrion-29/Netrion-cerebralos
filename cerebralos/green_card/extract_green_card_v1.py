#!/usr/bin/env python3
"""
GREEN CARD v1 – deterministic trauma green-card extractor.

Reads patient_evidence_v1.json, patient_days_v1.json, patient_features_v1.json,
and rules/green_card/green_card_patterns_v1.json.

Produces:
  outputs/green_card/<PAT>/green_card_v1.json          (structured)
  outputs/green_card/<PAT>/green_card_evidence_v1.json  (audit trail)

Design:
- H&P-first, source-priority: TRAUMA_HP > ED > PROGRESS > CONSULT/OP > IMAGING > DISCHARGE
- Discharge is "landmine": may add missing fields only, never overwrite.
- Deterministic regex, fail-closed. No LLM, no ML, no inference.

Usage:
    python3 -m cerebralos.green_card.extract_green_card_v1 --pat Timothy_Cowan
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import warnings as _warnings_mod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from cerebralos.green_card.extract_green_card_adjuncts_v1 import extract_adjuncts
from cerebralos.green_card.extract_green_card_hp_v1 import extract_hp_fields

# ── paths ───────────────────────────────────────────────────────────
_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent.parent
_RULES_PATH = _REPO_ROOT / "rules" / "green_card" / "green_card_patterns_v1.json"


# ── config loading ──────────────────────────────────────────────────
def _load_config() -> Dict[str, Any]:
    if not _RULES_PATH.is_file():
        print(f"FATAL: green card patterns not found: {_RULES_PATH}", file=sys.stderr)
        sys.exit(1)
    with open(_RULES_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    return cfg


def _compile_patterns(patterns: list[str]) -> list[re.Pattern]:
    return [re.compile(p) for p in patterns]


# ── doc-type classification ─────────────────────────────────────────
DOC_TYPES_ORDERED = [
    "trauma_hp", "discharge_summary", "ed_note", "trauma_progress",
    "consult_note", "op_note", "imaging",
]


class DocTypeResult:
    """Rich classification result for a single evidence item."""
    __slots__ = ("doc_type", "match_tier", "matched_pattern",
                 "matched_line_preview")

    def __init__(self, doc_type: str, match_tier: int = 0,
                 matched_pattern: str = "",
                 matched_line_preview: str = ""):
        self.doc_type = doc_type
        self.match_tier = match_tier
        self.matched_pattern = matched_pattern
        self.matched_line_preview = matched_line_preview

    def to_dict(self) -> Dict[str, Any]:
        return {
            "doc_type": self.doc_type,
            "match_tier": self.match_tier,
            "matched_pattern": self.matched_pattern,
            "matched_line_preview": self.matched_line_preview,
        }


def _line_preview_for_match(text: str, match: re.Match, context: int = 40) -> str:
    """Return a short context snippet around a regex match."""
    start = max(0, match.start() - context)
    end = min(len(text), match.end() + context)
    return text[start:end].replace("\n", " ").strip()[:200]


def _classify_trauma_hp_tiered(
    item: Dict[str, Any],
    spec: Dict[str, Any],
) -> Optional[DocTypeResult]:
    """Try tiered TRAUMA_HP classification. Returns DocTypeResult or None."""
    kind = item.get("kind", "")
    text_head = (item.get("text", "") or "")[:800]
    text_lines_top = "\n".join((item.get("text", "") or "").split("\n")[:30])
    full_text = (item.get("text", "") or "")

    # 0) exact kind match → tier 1
    if kind in spec.get("kind_exact", []):
        return DocTypeResult("trauma_hp", 1, f"kind_exact={kind}",
                             kind)

    # Tier 1 — strong headers (any match in first 800 chars)
    for pat_str in spec.get("tier1_any", []):
        try:
            m = re.search(pat_str, text_head)
            if m:
                return DocTypeResult(
                    "trauma_hp", 1, pat_str,
                    _line_preview_for_match(text_head, m),
                )
        except re.error:
            continue

    # Tier 2 — trauma service indicator near top AND HPI header anywhere
    tier2 = spec.get("tier2_all", {})
    near_top_hit: Optional[Tuple[str, re.Match]] = None
    for pat_str in tier2.get("near_top_any", []):
        try:
            m = re.search(pat_str, text_lines_top)
            if m:
                near_top_hit = (pat_str, m)
                break
        except re.error:
            continue
    if near_top_hit:
        for pat_str in tier2.get("must_have_any", []):
            try:
                m2 = re.search(pat_str, full_text)
                if m2:
                    combined_pat = f"tier2: near_top={near_top_hit[0]} + {pat_str}"
                    preview = _line_preview_for_match(text_lines_top, near_top_hit[1])
                    return DocTypeResult("trauma_hp", 2, combined_pat, preview)
            except re.error:
                continue

    # Tier 3 — ESA surgeon H&P with trauma context
    tier3 = spec.get("tier3_all", {})
    near_top_hit3: Optional[Tuple[str, re.Match]] = None
    for pat_str in tier3.get("near_top_any", []):
        try:
            m = re.search(pat_str, text_lines_top)
            if m:
                near_top_hit3 = (pat_str, m)
                break
        except re.error:
            continue
    if near_top_hit3:
        must_have_ok = False
        for pat_str in tier3.get("must_have_any", []):
            try:
                if re.search(pat_str, full_text[:2000]):
                    must_have_ok = True
                    break
            except re.error:
                continue
        context_ok = not tier3.get("must_have_context")
        if not context_ok:
            for pat_str in tier3.get("must_have_context", []):
                try:
                    if re.search(pat_str, full_text[:2000]):
                        context_ok = True
                        break
                except re.error:
                    continue
        if must_have_ok and context_ok:
            combined_pat = f"tier3: near_top={near_top_hit3[0]}"
            preview = _line_preview_for_match(text_lines_top, near_top_hit3[1])
            return DocTypeResult("trauma_hp", 3, combined_pat, preview)

    # Legacy text_patterns fallback → tier 1
    for pat_str in spec.get("text_patterns", []):
        try:
            m = re.search(pat_str, text_head)
            if m:
                return DocTypeResult(
                    "trauma_hp", 1, pat_str,
                    _line_preview_for_match(text_head, m),
                )
        except re.error:
            continue

    return None


def classify_doc_type(item: Dict[str, Any], cfg: Dict[str, Any]) -> DocTypeResult:
    """Classify an evidence item into a doc_type with tier metadata."""
    kind = item.get("kind", "")
    text_head = (item.get("text", "") or "")[:800]
    detection = cfg.get("doc_type_detection", {})

    # Try trauma_hp first with tiered logic
    trauma_spec = detection.get("trauma_hp", {})
    trauma_result = _classify_trauma_hp_tiered(item, trauma_spec)
    if trauma_result:
        return trauma_result

    # Other doc types — standard first-match
    for dtype in DOC_TYPES_ORDERED:
        if dtype == "trauma_hp":
            continue  # already tried
        spec = detection.get(dtype, {})
        # 1) exact kind match
        if kind in spec.get("kind_exact", []):
            return DocTypeResult(dtype, 0, f"kind_exact={kind}", kind)
        # 2) text pattern match
        for pat_str in spec.get("text_patterns", []):
            try:
                m = re.search(pat_str, text_head)
                if m:
                    return DocTypeResult(
                        dtype, 0, pat_str,
                        _line_preview_for_match(text_head, m),
                    )
            except re.error:
                continue
    return DocTypeResult("other", 0, "", "")


def get_priority(doc_type: str, cfg: Dict[str, Any]) -> int:
    return cfg.get("doc_type_priority", {}).get(doc_type, 8)


# ── section extraction helpers ──────────────────────────────────────
def _extract_section(text: str, header_patterns: list[str],
                     stop_patterns: Optional[list[str]] = None,
                     max_lines: int = 80) -> Optional[str]:
    """
    Extract a section from text starting at a header pattern line,
    ending at the next section header or stop_patterns or max_lines.
    Returns the section body (without the header line itself), or None.
    """
    lines = text.split("\n")
    header_res = [re.compile(p) for p in header_patterns]
    stop_res = [
        re.compile(r"(?i)^\\s*(?:Review of Systems|ROS|Physical Exam|Examination|"
                   r"Social History|Family History|Allergies|Surgical History|"
                   r"Assessment|Plan|Impression|Labs|Radiology|Secondary Survey|"
                   r"Primary Survey|Vital Signs|Medications|Orders)\\b"),
    ]
    if stop_patterns:
        stop_res.extend([re.compile(p) for p in stop_patterns])

    start_idx = None
    for i, line in enumerate(lines):
        for hre in header_res:
            if hre.search(line):
                start_idx = i
                break
        if start_idx is not None:
            break

    if start_idx is None:
        return None

    body_lines: list[str] = []
    for j in range(start_idx + 1, min(start_idx + 1 + max_lines, len(lines))):
        ln = lines[j]
        # stop at next section header
        is_stop = False
        for sre in stop_res:
            if sre.search(ln):
                is_stop = True
                break
        if is_stop and body_lines:  # don't stop on first line
            break
        body_lines.append(ln)

    return "\n".join(body_lines).strip() if body_lines else None


def _extract_section_robust(text: str, header_patterns: list[str],
                            max_lines: int = 80) -> Optional[str]:
    """More relaxed section extraction using common section headers as stop.
    
    Handles cases where a matched header is immediately followed by a
    related sub-header (e.g. 'PMH:' then 'Past Medical History:').
    """
    lines = text.split("\n")
    header_res = [re.compile(p) for p in header_patterns]
    # Common section headers that signal end of previous section
    _STOP_HEADERS = [
        r"Review of Systems", r"ROS\b", r"Physical Exam", r"Examination",
        r"Social History", r"Soci?al Hx", r"Family History", r"Allergies",
        r"Surgical History", r"Surg(?:ical)?\s+Hx",
        r"Past Surgical History", r"PSH\b",
        r"Assessment\s*/?\s*Plan", r"Plan\b",
        r"Impression", r"Labs\b", r"Radiology",
        r"Secondary Survey", r"Primary Survey", r"Vital Signs",
        r"Medications\b", r"Orders\b", r"Meds\b",
        r"Home Medications", r"Meds Prior",
        r"History of Present Illness", r"HPI\b", r"Chief Complaint", r"CC\b",
        r"Discharge Diagnos", r"Discharge Disposition", r"Discharge Medications",
        r"Hospital Course", r"Procedures?\b", r"Consultants?\b",
        r"Past Medical History", r"PMH\b",
    ]
    stop_re = re.compile(
        r"(?i)^\s*(?:" + "|".join(_STOP_HEADERS) + r")\s*[:\-]?"
    )

    start_idx = None
    for i, line in enumerate(lines):
        for hre in header_res:
            if hre.search(line):
                start_idx = i
                break
        if start_idx is not None:
            break

    if start_idx is None:
        return None

    # Collect body lines. Allow re-occurrence of our own header patterns
    # within the first 3 lines (handles PMH: -> Past Medical History: pattern).
    body_lines: list[str] = []
    non_empty_count = 0
    for j in range(start_idx + 1, min(start_idx + 1 + max_lines, len(lines))):
        ln = lines[j]
        ln_stripped = ln.strip()
        if ln_stripped:
            non_empty_count += 1
        # Check stop only after we have substantive content (>= 2 non-empty lines
        # that are NOT just sub-headers of the same section)
        if non_empty_count >= 2 and stop_re.match(ln):
            # Make sure it's not our own header pattern reappearing
            is_own = False
            for hre in header_res:
                if hre.search(ln):
                    is_own = True
                    break
            if not is_own:
                break
        body_lines.append(ln)

    return "\n".join(body_lines).strip() if body_lines else None


# ── bullet list parser ──────────────────────────────────────────────
def _parse_bullet_list(text: str) -> list[str]:
    """Parse a section of text into individual bullet items."""
    items: list[str] = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        # Strip leading bullets/numbers
        line = re.sub(r"^[\-\*\u2022\d]+[\.\)\:]?\s*", "", line).strip()
        if line and len(line) > 1:
            items.append(line)
    return items


def _extract_hp_final_assessment(text: str) -> list[str]:
    """
    Extract the final Assessment/Impression from an H&P note.
    
    The H&P note embeds radiology reports that each have their own IMPRESSION
    lines. We want only the FINAL assessment (the physician's summary of
    injuries), which typically appears after all imaging and labs sections.
    
    Strategy: search from the END of the text backwards for an Assessment/Plan
    or Impression section that is NOT inside a radiology block.
    """
    lines = text.split("\n")
    
    # Match standalone header OR header with inline content
    assessment_re = re.compile(
        r"(?i)^\s*(?:Assessment\s*/?\s*Plan|Assessment|Impression|"
        r"Injury\s*List|Injuries)\s*[:\-]"
    )
    
    # Find the LAST Assessment/Impression section header
    last_header_idx = None
    for i in range(len(lines) - 1, -1, -1):
        if assessment_re.search(lines[i]):
            last_header_idx = i
            break
    
    if last_header_idx is not None:
        result = []
        stop_re = re.compile(
            r"(?i)^\s*(?:Plan|Disposition|Discharge|Follow[- ]?up|"
            r"Attending|Signed|Electronically)\s*[:\-]?"
        )
        
        # Check if the header line itself has inline content (e.g.,
        #  "Impression: 60 yo male s/p auger accident with")
        header_line = lines[last_header_idx]
        header_match = assessment_re.search(header_line)
        if header_match:
            inline_content = header_line[header_match.end():].strip()
            # Strip the preamble like "60 yo male s/p auger accident with"
            # and keep only if it contains injury-like keywords
            if inline_content:
                # Check for bullet-style items after the header text
                pass  # We'll scan the next lines for bullets
        
        for j in range(last_header_idx + 1, min(last_header_idx + 50, len(lines))):
            ln = lines[j].strip()
            if stop_re.match(ln) and result:
                break
            if ln:
                ln_clean = re.sub(r"^[\-\*\u2022\d]+[\.\)\:]?\s*", "", ln).strip()
                if ln_clean and len(ln_clean) > 3:
                    result.append(ln_clean)
        if result:
            return result
    
    # Fallback: scan the last 200 lines for bullet-style injury list
    items: list[str] = []
    injury_list_re = re.compile(
        r"(?i)^\s*(?:\d+[\.\)]|[\-\*\u2022])\s*(?:.*(?:fracture|laceration|"
        r"injury|contusion|hematoma|hemorrhage|pneumothorax|"
        r"dislocation|rupture|tear|avulsion)\b)"
    )
    scan_start = max(0, len(lines) - 200)
    in_injury_block = False
    for i in range(scan_start, len(lines)):
        ln = lines[i].strip()
        if injury_list_re.match(ln):
            in_injury_block = True
        if in_injury_block:
            if not ln:
                if items:
                    break  # end of block
                continue
            ln_clean = re.sub(r"^[\-\*\u2022\d]+[\.\)\:]?\s*", "", ln).strip()
            if ln_clean and len(ln_clean) > 3:
                items.append(ln_clean)
    
    return items


# ── HPI extraction (full narrative from Trauma H&P) ─────────────────
def _extract_hpi(text: str, cfg: Dict[str, Any]) -> Optional[str]:
    """Extract the full HPI section from a Trauma H&P note.

    Uses config-driven header & stop patterns.
    Returns cleaned paragraph text (wrapped lines joined), or None.
    """
    header_pats = cfg.get("hpi_section_headers", [
        r"(?i)^\s*(?:HISTORY OF PRESENT ILLNESS|HPI)\s*[:\-]?",
    ])
    stop_pats = cfg.get("hpi_stop_headers", [])

    lines = text.split("\n")
    header_res = [re.compile(p) for p in header_pats]
    stop_res = [re.compile(p) for p in stop_pats] if stop_pats else []

    start_idx: Optional[int] = None
    for i, line in enumerate(lines):
        for hre in header_res:
            if hre.search(line):
                start_idx = i
                break
        if start_idx is not None:
            break

    if start_idx is None:
        return None

    # Check if header line itself contains inline text (e.g. "HPI: 45yo male…")
    header_line = lines[start_idx]
    inline_text = ""
    colon_idx = header_line.find(":")
    if colon_idx >= 0:
        after = header_line[colon_idx + 1:].strip()
        if after:
            inline_text = after

    body_lines: list[str] = []
    if inline_text:
        body_lines.append(inline_text)

    max_lines = 200  # generous limit for long HPIs
    for j in range(start_idx + 1, min(start_idx + 1 + max_lines, len(lines))):
        ln = lines[j]
        # Check stop headers
        hit_stop = False
        for sre in stop_res:
            if sre.search(ln):
                hit_stop = True
                break
        if hit_stop and body_lines:
            break
        body_lines.append(ln)

    if not body_lines:
        return None

    # Clean: join wrapped lines into paragraphs, preserving paragraph breaks
    paragraphs: list[str] = []
    current: list[str] = []
    for ln in body_lines:
        stripped = ln.strip()
        if not stripped:
            if current:
                paragraphs.append(" ".join(current))
                current = []
        else:
            current.append(stripped)
    if current:
        paragraphs.append(" ".join(current))

    return "\n\n".join(paragraphs).strip() or None


def _extract_moi_narrative(hpi_text: str, max_chars: int = 600) -> Tuple[str, bool]:
    """Extract first 1-3 sentences from HPI for MOI narrative.

    Returns (narrative_text, was_truncated).
    Deterministic sentence split on '. ' boundaries.
    """
    if not hpi_text:
        return ("", False)

    # Flatten to single paragraph for sentence splitting
    flat = hpi_text.replace("\n\n", " ").replace("\n", " ").strip()
    # Remove multiple spaces
    flat = re.sub(r"\s{2,}", " ", flat)

    # Sentence split: split on period followed by space and uppercase letter,
    # but not on common abbreviations
    abbrev_re = re.compile(
        r"(?:Dr|Mr|Mrs|Ms|vs|approx|yr|y\.o|yo|St|Pt|pt|Hx|hx|oz|lbs|etc|"  
        r"e\.g|i\.e|a\.m|p\.m|L\.?U\.?E|R\.?U\.?E|L\.?L\.?E|R\.?L\.?E|"  
        r"H\s*&\s*P|C\d+|T\d+|L\d+|S\d+)"
    )
    # Find sentence boundaries: period + space + uppercase
    boundaries: list[int] = []
    i = 0
    while i < len(flat) - 2:
        if flat[i] == '.' and flat[i + 1] == ' ' and flat[i + 2].isupper():
            # Check it's not an abbreviation ending
            # Look back up to 6 chars for abbreviation
            lookback = flat[max(0, i - 6):i + 1]
            if not abbrev_re.search(lookback):
                boundaries.append(i + 1)  # include the period
        i += 1

    # Extract first 3 sentences
    if boundaries and len(boundaries) >= 3:
        end = boundaries[2]
        narrative = flat[:end].strip()
        return (narrative, False)
    elif boundaries and len(boundaries) >= 1:
        # Take all if <=3 sentences
        end = boundaries[-1]
        rest = flat[end:].strip()
        # If remaining text is short (one more sentence), include it
        if len(rest) < 200:
            narrative = flat.strip()
            return (narrative, False)
        else:
            narrative = flat[:end].strip()
            return (narrative, False)
    else:
        # No sentence boundaries found; use char limit
        if len(flat) <= max_chars:
            return (flat, False)
        # Truncate at last space before max_chars
        trunc = flat[:max_chars]
        last_space = trunc.rfind(' ')
        if last_space > max_chars // 2:
            trunc = trunc[:last_space]
        return (trunc.rstrip('.').strip() + '…', True)


# ── field source tracking ───────────────────────────────────────────
class FieldSource:
    """Track a source for a field value."""
    def __init__(self, doc_type: str, priority: int, item_idx: int,
                 line_id: str, preview: str):
        self.doc_type = doc_type
        self.priority = priority
        self.item_idx = item_idx
        self.line_id = line_id
        self.preview = preview[:200]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_type": self.doc_type.upper(),
            "priority": self.priority,
            "item_id": self.item_idx,
            "source_line_id": self.line_id,
            "preview": self.preview,
        }


class TrackedField:
    """A field with value + provenance sources. Supports scalars and lists."""
    def __init__(self):
        self.value: Any = None
        self.sources: list[FieldSource] = []
        self.warnings: list[Dict[str, Any]] = []

    def set_scalar(self, value: str, source: FieldSource, is_discharge: bool = False) -> None:
        if self.value is not None:
            if is_discharge and self.value != value:
                self.warnings.append({
                    "code": "discharge_conflict",
                    "existing_value": self.value,
                    "discharge_value": value,
                    "existing_source": self.sources[0].doc_type if self.sources else "unknown",
                    "discharge_source": source.doc_type,
                })
                return  # keep higher-priority value
            elif self.value == value:
                self.sources.append(source)
                return
            elif not is_discharge:
                # Higher priority wins (lower number = higher priority)
                if source.priority < self.sources[0].priority:
                    self.value = value
                    self.sources = [source]
                    return
                elif source.priority == self.sources[0].priority:
                    self.sources.append(source)
                    return
                else:
                    return  # lower priority, skip
        self.value = value
        self.sources = [source]

    def add_list_items(self, items: list[str], source: FieldSource,
                       is_discharge: bool = False) -> None:
        if self.value is None:
            self.value = []
        existing_norm = {s.lower().strip() for s in (self.value or [])}
        added = False
        for item in items:
            norm = item.lower().strip()
            if norm and norm not in existing_norm:
                self.value.append(item)
                existing_norm.add(norm)
                added = True
        if added or not self.sources:
            self.sources.append(source)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "value": self.value,
            "confidence": "EXPLICIT",
            "sources": [s.to_dict() for s in self.sources],
            "warnings": self.warnings,
        }


# ── main extraction logic ──────────────────────────────────────────
def extract_green_card(pat: str, cfg: Dict[str, Any]) -> Tuple[Dict, Dict, list]:
    """
    Extract green card fields from patient evidence.

    Returns: (green_card_dict, evidence_dict, warnings)
    """
    evidence_path = _REPO_ROOT / "outputs" / "evidence" / pat / "patient_evidence_v1.json"
    days_path = _REPO_ROOT / "outputs" / "timeline" / pat / "patient_days_v1.json"
    features_path = _REPO_ROOT / "outputs" / "features" / pat / "patient_features_v1.json"

    if not evidence_path.is_file():
        print(f"FATAL: evidence file not found: {evidence_path}", file=sys.stderr)
        sys.exit(1)

    with open(evidence_path, encoding="utf-8") as f:
        evidence = json.load(f)

    days_data: Optional[Dict] = None
    if days_path.is_file():
        with open(days_path, encoding="utf-8") as f:
            days_data = json.load(f)

    features_data: Optional[Dict] = None
    if features_path.is_file():
        with open(features_path, encoding="utf-8") as f:
            features_data = json.load(f)

    meta = evidence.get("meta", {})
    header = evidence.get("header", {})
    items = evidence.get("items", [])
    warnings: list[str] = []

    # ── 1. Classify each evidence item (with tier metadata) ───
    classified: list[Tuple[Dict, DocTypeResult, int]] = []  # (item, result, priority)
    trauma_hp_candidates: list[Tuple[Dict, DocTypeResult, int]] = []
    for item in items:
        result = classify_doc_type(item, cfg)
        prio = get_priority(result.doc_type, cfg)
        classified.append((item, result, prio))
        if result.doc_type == "trauma_hp":
            trauma_hp_candidates.append((item, result, prio))

    # Sort by priority (ascending = higher priority first)
    classified.sort(key=lambda x: x[2])

    # ── 1b. Select best TRAUMA_HP ───────────────────────────────
    chosen_trauma_hp: Optional[Dict[str, Any]] = None
    if len(trauma_hp_candidates) > 1:
        warnings.append("multiple_trauma_hp_detected")
        # Select best: lowest tier → earliest ts → longest HPI
        def _hp_sort_key(c: Tuple[Dict, DocTypeResult, int]) -> Tuple:
            item_c, res_c, _ = c
            tier = res_c.match_tier
            ts = item_c.get("datetime", "") or "9999"
            hpi_len = len(_extract_hpi(item_c.get("text", "") or "", cfg) or "")
            return (tier, ts, -hpi_len)
        trauma_hp_candidates.sort(key=_hp_sort_key)

    if trauma_hp_candidates:
        best_item, best_result, _ = trauma_hp_candidates[0]
        chosen_trauma_hp = {
            "item_id": best_item.get("idx"),
            "ts": best_item.get("datetime"),
            "match_tier": best_result.match_tier,
            "matched_pattern": best_result.matched_pattern,
            "matched_line_preview": best_result.matched_line_preview,
        }

    # ── 2. Initialize tracked fields ────────────────────────────
    moi_field = TrackedField()
    hpi_field = TrackedField()
    moi_narrative_field = TrackedField()
    injuries_field = TrackedField()
    consultants_field = TrackedField()
    procedures_field = TrackedField()
    pmh_field = TrackedField()
    anticoag_field = TrackedField()
    admitting_service_field = TrackedField()

    # counts for QA
    doc_type_counts: Dict[str, int] = {}
    hp_found = False
    _meds_section_found = False

    # ── 3. Process each item in priority order ──────────────────
    for item, result, prio in classified:
        dtype = result.doc_type
        doc_type_counts[dtype] = doc_type_counts.get(dtype, 0) + 1
        if dtype == "trauma_hp":
            hp_found = True

        text = item.get("text", "") or ""
        item_idx = item.get("idx", -1)
        line_id = f"L{item.get('line_start', 0)}-L{item.get('line_end', 0)}"
        is_discharge = (dtype == "discharge_summary")

        def make_source(preview: str = "") -> FieldSource:
            return FieldSource(dtype, prio, item_idx, line_id,
                               preview or text[:200])

        # ── a0) HPI extraction (TRAUMA_HP only, best candidate) ──
        #    Only extract HPI from the chosen TRAUMA_HP, not random ones.
        if (dtype == "trauma_hp" and hpi_field.value is None
                and chosen_trauma_hp is not None
                and item.get("idx") == chosen_trauma_hp["item_id"]):
            hpi_text = _extract_hpi(text, cfg)
            if hpi_text:
                hpi_field.set_scalar(hpi_text, make_source(hpi_text[:200]))
                # Also build moi_narrative from HPI
                narrative, was_truncated = _extract_moi_narrative(hpi_text)
                if narrative:
                    moi_narrative_field.set_scalar(
                        narrative, make_source(narrative[:200])
                    )
                    if was_truncated:
                        moi_narrative_field.warnings.append({
                            "code": "moi_narrative_truncated",
                            "detail": "HPI exceeded 600 chars with no sentence boundaries; truncated.",
                        })

        # ── a) Mechanism of Injury ──────────────────────────────
        # For H&P notes, restrict MOI search to HPI section; for other notes
        # use the first 2000 chars.
        if moi_field.value is None or (not is_discharge):
            moi_text = text[:2000]
            if dtype == "trauma_hp":
                # Try to isolate HPI section
                hpi_match = re.search(r"(?i)\bHPI\s*:", moi_text)
                if hpi_match:
                    hpi_end = re.search(
                        r"(?i)^\s*(?:Primary Survey|PMH|Past Medical|Allergies|Meds|Secondary Survey)\s*[:\-]?",
                        moi_text[hpi_match.start():],
                        re.MULTILINE,
                    )
                    if hpi_end:
                        moi_text = moi_text[hpi_match.start():hpi_match.start() + hpi_end.start()]
                    else:
                        moi_text = moi_text[hpi_match.start():]

            # Find all matching MOI labels, prefer the last (most specific)
            # in the config list since we order generic -> specific
            best_moi_label = None
            best_moi_context = ""
            for moi_spec in cfg.get("moi_patterns", []):
                for pat_str in moi_spec.get("patterns", []):
                    try:
                        m = re.search(pat_str, moi_text)
                    except re.error:
                        continue
                    if m:
                        best_moi_label = moi_spec["label"]
                        start = max(0, m.start() - 40)
                        end = min(len(moi_text), m.end() + 120)
                        best_moi_context = moi_text[start:end].replace("\n", " ").strip()
                        break
            if best_moi_label:
                moi_field.set_scalar(best_moi_label, make_source(best_moi_context),
                                     is_discharge=is_discharge)

        # ── b) Primary injuries ─────────────────────────────────
        inj_items_raw: list[str] = []
        inj_preview = ""
        
        if dtype == "trauma_hp":
            # For H&P: look for the FINAL Assessment/Impression near the
            # end of the note (after Secondary Survey / Labs / Radiographs).
            # Skip embedded radiology IMPRESSION lines.
            inj_items_raw = _extract_hp_final_assessment(text)
            inj_preview = "H&P final assessment"
        elif dtype == "discharge_summary":
            # Discharge: look for discharge diagnoses
            discharge_dx = _extract_section_robust(
                text,
                [r"(?i)^\s*Discharge Diagnos[ei]s",
                 r"(?i)^\s*Final Diagnos[ei]s"],
                max_lines=40,
            )
            if discharge_dx:
                inj_items_raw = _parse_bullet_list(discharge_dx)
                inj_preview = discharge_dx[:200]
        elif dtype in ("consult_note", "op_note", "trauma_progress"):
            # Use Assessment/Impression patterns for non-HP notes
            inj_section = _extract_section_robust(
                text,
                [r"(?i)^\s*Assessment\b", r"(?i)^\s*Impression\b",
                 r"(?i)^\s*Assessment\s*/?\s*Plan\b"],
                max_lines=40,
            )
            if inj_section:
                inj_items_raw = _parse_bullet_list(inj_section)
                inj_preview = inj_section[:200]
        
        if inj_items_raw:
            # Filter noise: metadata, meds, radiology, dates, signatures,
            # plan text, short items
            _NOISE_RE = re.compile(
                r"(?i)^(?:Diagnosis Date|Medication|Result Date|Exam Ended|"
                r"Last Resulted|Order Details|View Encounter|Routing|"
                r"Result History|View All|Related Results|Released|Seen|"
                r"Back to Top|Reading Physician|Sign Physician|Imaging\b|"
                r"Original Order|Ordered On|Ordered By|Radiology Time|"
                r"Flowsheet Row|Verified|Time out|Acknowledge|No acknowledgement|"
                r"Result Care|Patient Communication|Read Physician|"
                r"Current Facility|Current Outpatient|Medications Ordered|"
                r"\[COMPLETED\]|Take \d|Dispense|Refill|"
                r"Comment:|NORMAL:|MG/DL|MMOL|ML/MIN|"
                r"HISTORY:|COMPARISON:|TECHNIQUE:|EXAMINATION:|"
                r"INDICATION:|CT\s\w|XR\s\w|MRI\s\w|"
                r"Final result|DISCUSSION:|Exams?:|Comparison stud|"
                r"Contiguous\b|scanned\b|were obtained|"
                r"Coronal|Sagittal|axial\sCT|"
                r"Signing Physician|"
                r"\d+/\d+/\d+\s+\d+:\d+\s+(AM|PM)|"
                r"^\w+day\s\w+\s\d+)",
                re.I,
            )
            # Plan/management noise
            _PLAN_RE = re.compile(
                r"(?i)(?:^(?:Signed|Respectfully|Available on|Please |"
                r"Thank you|One of my|untitled image|"
                r"Geriatric Trauma Screen|bCAM|PHQ-?9|6CIT|"
                r"Confusion Assessment|Depression|Dementia|"
                r"What year|What month|Correct|"
                r"Advanced Care|full code|"
                r"Continue\b|Ensure\b|Await\b|PT/OT|Tylenol|morphine|"
                r"oxycodone|melatonin|==>)|"
                r"Deaconess Care Group|Hospitalist|"
                r"^[A-Z][a-z]+ [A-Z]\s[A-Z][a-z]+,\s*(?:MD|DO|NP|PA)|"  # Name, MD
                r"^\s*/\d+/\d+\s*$)",  # bare date like /7/2025
                re.I,
            )
            # Bare date patterns
            _DATE_RE = re.compile(
                r"^/?(?:\d{1,2}/)?\d{1,2}/\d{2,4}\s*$"
            )
            # "Recent Labs" header
            _RECENT_LABS_RE = re.compile(r"(?i)^Recent Labs")
            # Demographics / overview line (not a diagnosis)
            _DEMO_RE = re.compile(
                r"(?i)(?:\d+\s*y\.?o\.?\s|year[- ]old|^PMH\b|^HPI\b|"
                r"\byo\s+(?:male|female|M|F)\b|^History of )"
            )
            # MOI masquerading as injury
            _MOI_AS_INJ_RE = re.compile(
                r"(?i)^\s*(?:Mechanical\s+Fall|Ground\s+Level\s+Fall|Fall|MVC|MVA|GSW)\s*$"
            )
            # IMPRESSION: prefix or embedded radiology
            _IMPRESSION_LINE_RE = re.compile(
                r"(?i)^\s*IMPRESSION\s*:"
            )
            # Precaution / management, not a diagnosis
            _MGMT_RE = re.compile(
                r"(?i)(?:precautions?\.|\bprecautions\s*$)"
            )
            # Date-prefix procedure lines ("/10 - ORIF...")
            _DATE_PROC_RE = re.compile(
                r"^\s*/\d+\s"
            )
            # S/p procedure descriptions
            _SP_PROC_RE = re.compile(
                r"(?i)(?:^S/p\s+(?:ORIF|kyphoplasty|vertebroplasty|surgery|repair)|"
                r"\bSurgeon:\s|^Procedure:\s|^Procedure\s+Laterality)"
            )
            # PMH conditions appearing in injury lists
            _PMH_IN_INJ_RE = re.compile(
                r"(?i)^(?:Type [12] diabetes|Diabetes|Hypertension|"
                r"Dyslipidemia|Anemia|ESRD|Atrial fibrillation|BPH|"
                r"Arthritis|Chronic\s+edema|COVID)\s*$"
            )
            # Radiology study references (not diagnoses)
            _RAD_STUDY_RE = re.compile(
                r"(?i)^(?:Right|Left)?\s*(?:foot|ankle|chest|hip|pelvis|spine|"
                r"knee|wrist|shoulder|head)[\s/]+(?:\w+[\s/]+)*?"
                r"(?:x-?ray|CT|MRI|radiograph)"
            )
            # Narrative phrases (not formal diagnoses)
            _NARRATIVE_RE = re.compile(
                r"(?i)(?:followed by|prior to followed|prior followed|"
                r"^Palpitations\b)"
            )
            # Trailing date pattern for stripping
            _TRAIL_DATE_RE = re.compile(
                r"\s+\d{1,2}/\d{1,2}/\d{2,4}\s*$"
            )
            
            inj_items_filtered = [
                i for i in inj_items_raw
                if len(i) > 5
                and len(i) < 150  # long lines are plan text, not diagnoses
                and not re.match(r"^\d+[\.\)]?\s*$", i)
                and not _NOISE_RE.search(i)
                and not _PLAN_RE.search(i)
                and not _DATE_RE.match(i)
                and not _RECENT_LABS_RE.match(i)
                and not _DEMO_RE.search(i)
                and not _MOI_AS_INJ_RE.match(i)
                and not _IMPRESSION_LINE_RE.match(i)
                and not _MGMT_RE.search(i)
                and not _DATE_PROC_RE.match(i)
                and not _SP_PROC_RE.search(i)
                and not _PMH_IN_INJ_RE.match(i)
                and not _RAD_STUDY_RE.match(i)
                and not _NARRATIVE_RE.search(i)
            ]
            # Strip trailing dates and deduplicate
            inj_items_filtered = [
                _TRAIL_DATE_RE.sub("", i).strip() for i in inj_items_filtered
            ]
            seen_inj: set[str] = set()
            inj_deduped: list[str] = []
            for item in inj_items_filtered:
                key = item.lower().strip()
                if key and key not in seen_inj:
                    seen_inj.add(key)
                    inj_deduped.append(item)
            inj_items_filtered = inj_deduped
            
            # For non-H&P sources, further filter to diagnosis-like items
            if dtype in ("consult_note", "trauma_progress", "discharge_summary"):
                _DX_LIKE_RE = re.compile(
                    r"(?i)(?:fracture|laceration|contusion|hematoma|hemorrhage|"
                    r"pneumothorax|dislocation|rupture|tear|avulsion|injury|"
                    r"concussion|edema|stenosis|effusion|lesion|"
                    r"wound|burn|amputation|transection|dissection|"
                    r"compression\s+fracture|insufficiency\s+fracture|"
                    r"subluxation|sprain|strain|"
                    r"acute|closed|open|displaced|nondisplaced|comminuted|"
                    r"s/p\s|status\s+post\b|"
                    r"UTI|infection|sepsis|DVT|PE\b|"
                    r"syncope\b|MVC\b|MVA\b|GSW\b)"
                )
                inj_items_filtered = [
                    i for i in inj_items_filtered
                    if _DX_LIKE_RE.search(i)
                ]
            if inj_items_filtered:
                injuries_field.add_list_items(
                    inj_items_filtered, make_source(inj_preview),
                    is_discharge=is_discharge
                )

        # ── c) Consultants ──────────────────────────────────────
        found_consultants: list[str] = []
        for svc_spec in cfg.get("consultant_services", {}).get("services", []):
            tag = svc_spec["tag"]
            for pat_str in svc_spec.get("patterns", []):
                try:
                    if re.search(pat_str, text):
                        if tag not in found_consultants:
                            found_consultants.append(tag)
                        break
                except re.error:
                    continue
        # Also check for explicit "consult" mentions
        if found_consultants:
            consultants_field.add_list_items(
                found_consultants, make_source(),
                is_discharge=is_discharge
            )

        # ── d) Procedures ───────────────────────────────────────
        found_procedures: list[str] = []
        for pat_str in cfg.get("procedure_markers", []):
            try:
                m = re.search(pat_str, text)
            except re.error:
                continue
            if m:
                start = max(0, m.start() - 10)
                end = min(len(text), m.end() + 80)
                proc_context = text[start:end].replace("\n", " ").strip()
                # Normalize to just the matched procedure
                proc_label = m.group(0).strip().rstrip(":")
                if proc_label not in found_procedures:
                    found_procedures.append(proc_label)
        if found_procedures:
            procedures_field.add_list_items(
                found_procedures, make_source(),
                is_discharge=is_discharge
            )

        # ── e) Past Medical History ─────────────────────────────
        pmh_section = _extract_section_robust(
            text, cfg.get("pmh_section_headers", []), max_lines=40
        )
        if pmh_section:
            pmh_items = _parse_bullet_list(pmh_section)
            # Filter out sub-headers, noise, and date-only lines
            _PMH_NOISE = re.compile(
                r"(?i)^(?:Past Medical History|PMH|Medical History|"
                r"Diagnosis\s*$|Diagnosis\s+Date|Date\b|Significant Medical|"
                r"Problem List|Active Problems?|See EPIC|"
                r"Signed|untitled|No Known)\s*[:\-]?\s*$"
            )
            _PMH_DATE = re.compile(
                r"^/?(?:\d{1,2}/)?\d{1,2}/\d{2,4}\s*$"
            )
            # Filter items that are mostly date fragments or metadata
            _PMH_FRAGMENT = re.compile(
                r"^/?(?:\d{1,2}/){1,2}\d{2,4}\s*(?:\w{0,3})$"  # /09/2021, /13/2021 etc.
            )
            # Filter short fragments that look like procedure notes, not PMH
            _PMH_PROC_NOISE = re.compile(
                r"(?i)(?:^bx\s|^exc\b|^monitor$|\bNFT\b|\bBenign\b|^\w+\s+cheek|^Right\s|^Left\s)"
            )
            # Filter known medication names that appear in PMH sections
            _PMH_MED_RE = re.compile(
                r"(?i)^\s*(?:Amiodarone|Warfarin|Coumadin|Eliquis|Apixaban|"
                r"Xarelto|Rivaroxaban|Plavix|Clopidogrel|Aspirin|Brilinta|"
                r"Lovenox|Enoxaparin|Heparin|Pradaxa|Dabigatran|Effient|"
                r"Prasugrel|Savaysa|Edoxaban|Arixtra|Fondaparinux|"
                r"Hypoglycemic|Lantus|Metformin|Lisinopril|Amlodipine)\b"
            )
            # Procedure/surgical history items leaking into PMH
            _PMH_SURG_RE = re.compile(
                r"(?i)(?:^Procedure[:\s]|^Surgeon[:\s]|^Ankle fracture surgery|"
                r"^Cesarean\b|^Cholecystectomy\b|^Thrombolysis\b|^Ercp\b|"
                r"^Dialysis fistula|^Vertebroplasty\b|ORIF|Kyphoplasty|"
                r"^Percutaneous embolectomy|^intragraft\b|"
                r"\bSurgeon:\s|\bLocation:\s|\bService:\s|\bLaterality:\s|"
                r"^PSH\b|^PAST SURGICAL|^Past Surgical|SOCIAL HISTORY|"
                r"^There are no diagnos|^No (?:known )?diagnos)"
            )
            # Continuation fragments (start with lowercase word)
            _PMH_CONTINUATION = re.compile(
                r"^(?:with\s|type\s?\d|and\s|or\s)"
            )
            # Date-suffixed items (e.g. "Condition   11/10/2023")
            _PMH_DATE_SUFFIX_RE = re.compile(
                r"\s+\d{1,2}/\d{1,2}/\d{2,4}\s*$"
            )
            pmh_items = [
                i for i in pmh_items
                if len(i) > 2
                and len(i) < 200  # skip long narrative paragraphs
                and not _PMH_NOISE.match(i)
                and not _PMH_DATE.match(i)
                and not _PMH_FRAGMENT.match(i)
                and not _PMH_PROC_NOISE.search(i)
                and not _PMH_MED_RE.match(i)
                and not _PMH_SURG_RE.search(i)
                and not _PMH_CONTINUATION.match(i)
            ]
            # Strip trailing date from items like "Condition   11/10/2023"
            pmh_items = [
                _PMH_DATE_SUFFIX_RE.sub("", i).strip() for i in pmh_items
            ]
            # Deduplicate after date-stripping
            seen_pmh: set[str] = set()
            pmh_deduped: list[str] = []
            for item in pmh_items:
                key = item.lower().strip()
                if key and key not in seen_pmh:
                    seen_pmh.add(key)
                    pmh_deduped.append(item)
            pmh_items = pmh_deduped
            if pmh_items:
                pmh_field.add_list_items(
                    pmh_items, make_source(pmh_section[:200]),
                    is_discharge=is_discharge
                )

        # ── f) Home anticoagulants/antiplatelets ────────────────
        meds_section = _extract_section_robust(
            text, cfg.get("home_meds_section_headers", []), max_lines=60
        )
        if meds_section:
            _meds_section_found = True
        meds_text = meds_section if meds_section else text[:3000]
        found_anticoag: list[str] = []
        ac_cfg = cfg.get("anticoagulant_keywords", {})
        for pat_str in ac_cfg.get("anticoagulants", []):
            try:
                m = re.search(pat_str, meds_text)
            except re.error:
                continue
            if m:
                med = m.group(0).lower()
                if med not in found_anticoag:
                    found_anticoag.append(med)
        for pat_str in ac_cfg.get("antiplatelets", []):
            try:
                m = re.search(pat_str, meds_text)
            except re.error:
                continue
            if m:
                med = m.group(0).lower() + " (antiplatelet)"
                if med not in found_anticoag:
                    found_anticoag.append(med)
        if found_anticoag:
            anticoag_field.add_list_items(
                found_anticoag, make_source(
                    (meds_section or "")[:200]
                ),
                is_discharge=is_discharge
            )

        # ── g) Admitting service ────────────────────────────────
        # Only from H&P and early notes (high priority)
        if dtype in ("trauma_hp", "ed_note", "discharge_summary"):
            admit_cfg = cfg.get("admitting_service", {})
            # Check trauma first
            for pat_str in admit_cfg.get("trauma", []):
                try:
                    if re.search(pat_str, text[:3000]):
                        admitting_service_field.set_scalar(
                            "TRAUMA", make_source(),
                            is_discharge=is_discharge
                        )
                        break
                except re.error:
                    continue
            # Check DCG
            if admitting_service_field.value is None:
                for pat_str in admit_cfg.get("dcg", []):
                    try:
                        if re.search(pat_str, text[:3000]):
                            admitting_service_field.set_scalar(
                                "DCG", make_source(),
                                is_discharge=is_discharge
                            )
                            break
                    except re.error:
                        continue
            # Check ESA
            if admitting_service_field.value is None:
                for pat_str in admit_cfg.get("esa", []):
                    try:
                        if re.search(pat_str, text[:3000]):
                            admitting_service_field.set_scalar(
                                "ESA", make_source(),
                                is_discharge=is_discharge
                            )
                            break
                    except re.error:
                        continue

    # ── Adjunct fields ──────────────────────────────────────────
    adjunct_classified = [
        (item, result.doc_type, prio) for item, result, prio in classified
    ]
    _chosen_hp_id = chosen_trauma_hp["item_id"] if chosen_trauma_hp else None
    adjuncts = extract_adjuncts(
        adjunct_classified, gc_cfg=cfg,
        chosen_trauma_hp_item_id=_chosen_hp_id,
        all_items=items,
        arrival_datetime=meta.get("arrival_datetime"),
    )

    # ── HP-centric fields (spec items 1-6) ──────────────────────
    hp_classified = [
        (item, result.doc_type, prio) for item, result, prio in classified
    ]
    hp_fields = extract_hp_fields(
        classified_items=hp_classified,
        chosen_trauma_hp_item_id=_chosen_hp_id,
        all_items=items,
        features_data=features_data,
        existing_anticoag_list=(
            anticoag_field.value if isinstance(anticoag_field.value, list) else None
        ),
        trauma_category=meta.get("trauma_category"),
    )

    # ── Post-processing / defaults ──────────────────────────────
    if admitting_service_field.value is None:
        admitting_service_field.value = "UNKNOWN"
        warnings.append("admitting_service_unknown")

    if moi_field.value is None:
        warnings.append("moi_missing")

    if injuries_field.value is None or not injuries_field.value:
        warnings.append("injuries_missing")

    if pmh_field.value is None or not pmh_field.value:
        warnings.append("pmh_missing")

    # If home meds section was not found at all, mark anticoag as unknown
    if anticoag_field.value is None:
        if _meds_section_found:
            anticoag_field.value = ["none identified in home medications"]
            warnings.append("no_anticoagulants_found")
        else:
            anticoag_field.value = ["unknown – home medications section not found"]
            warnings.append("home_meds_section_missing")

    if not consultants_field.value:
        warnings.append("consultants_missing")

    if not procedures_field.value:
        warnings.append("procedures_missing")

    if not hp_found:
        warnings.append("no_trauma_hp_detected")

    # ── Fail-closed: no TRAUMA_HP → HPI = DATA NOT AVAILABLE ───
    if not hp_found and hpi_field.value is None:
        hpi_field.value = "DATA NOT AVAILABLE"
        warnings.append("hpi_missing")
    elif hpi_field.value is None:
        hpi_field.value = "DATA NOT AVAILABLE"
        warnings.append("hpi_missing")

    if moi_narrative_field.value is None:
        moi_narrative_field.value = "DATA NOT AVAILABLE"

    # ── Gather services from features data if available ─────────
    services_summary: list[Dict[str, Any]] = []
    if features_data:
        for day_iso, day_data in sorted(features_data.get("days", {}).items()):
            svc = day_data.get("services", {})
            nbs = svc.get("notes_by_service", {})
            for svc_tag, notes in nbs.items():
                services_summary.append({
                    "day": day_iso,
                    "service": svc_tag,
                    "note_count": len(notes),
                })

    # ── Build output ────────────────────────────────────────────
    green_card = {
        "meta": {
            "artifact": "green_card_v1",
            "version": "1.0.0",
            "created_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "patient_slug": pat,
            "patient_id": meta.get("patient_id", "unknown"),
            "arrival_datetime": meta.get("arrival_datetime"),
            "trauma_category": meta.get("trauma_category"),
        },
        "admitting_service": admitting_service_field.to_dict(),
        "mechanism_of_injury": moi_field.to_dict(),
        "moi_narrative": moi_narrative_field.to_dict(),
        "hpi": hpi_field.to_dict(),
        "injuries": injuries_field.to_dict(),
        "procedures": procedures_field.to_dict(),
        "consultants": consultants_field.to_dict(),
        "pmh": pmh_field.to_dict(),
        "home_anticoagulants": anticoag_field.to_dict(),
        "spine_clearance": adjuncts["spine_clearance"],
        "dvt_prophylaxis": adjuncts["dvt_prophylaxis"],
        "first_ed_temp": adjuncts["first_ed_temp"],
        "gi_prophylaxis": adjuncts["gi_prophylaxis"],
        "bowel_regimen": adjuncts["bowel_regimen"],
        "tourniquet": adjuncts["tourniquet"],
        "primary_survey": hp_fields["primary_survey"],
        "admitting_md": hp_fields["admitting_md"],
        "anticoag_status": hp_fields["anticoag_status"],
        "etoh": hp_fields["etoh"],
        "uds": hp_fields["uds"],
        "base_deficit": hp_fields["base_deficit"],
        "inr": hp_fields["inr"],
        "impression_plan": hp_fields["impression_plan"],
        "services_by_day": services_summary,
        "doc_type_counts": doc_type_counts,
        "warnings": warnings,
    }

    # ── Build evidence/audit ────────────────────────────────────
    evidence_out = {
        "meta": {
            "artifact": "green_card_evidence_v1",
            "version": "1.0.0",
            "created_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "patient_slug": pat,
            "patient_id": meta.get("patient_id", "unknown"),
        },
        "fields": {
            "admitting_service": admitting_service_field.to_dict(),
            "mechanism_of_injury": moi_field.to_dict(),
            "moi_narrative": moi_narrative_field.to_dict(),
            "hpi": hpi_field.to_dict(),
            "injuries": injuries_field.to_dict(),
            "procedures": procedures_field.to_dict(),
            "consultants": consultants_field.to_dict(),
            "pmh": pmh_field.to_dict(),
            "home_anticoagulants": anticoag_field.to_dict(),
            "spine_clearance": adjuncts["spine_clearance"],
            "dvt_prophylaxis": adjuncts["dvt_prophylaxis"],
            "first_ed_temp": adjuncts["first_ed_temp"],
            "gi_prophylaxis": adjuncts["gi_prophylaxis"],
            "bowel_regimen": adjuncts["bowel_regimen"],
            "tourniquet": adjuncts["tourniquet"],
            "primary_survey": hp_fields["primary_survey"],
            "admitting_md": hp_fields["admitting_md"],
            "anticoag_status": hp_fields["anticoag_status"],
            "etoh": hp_fields["etoh"],
            "uds": hp_fields["uds"],
            "base_deficit": hp_fields["base_deficit"],
            "inr": hp_fields["inr"],
            "impression_plan": hp_fields["impression_plan"],
        },
        "doc_type_classification": [
            {
                "item_idx": item.get("idx"),
                "kind": item.get("kind"),
                "doc_type": result.doc_type,
                "match_tier": result.match_tier,
                "matched_pattern": result.matched_pattern,
                "matched_line_preview": result.matched_line_preview,
                "priority": prio,
                "datetime": item.get("datetime"),
                "preview": (item.get("text", "") or "")[:150],
            }
            for item, result, prio in classified
        ],
        "doc_type_counts": {k.upper(): v for k, v in doc_type_counts.items()},
        "chosen_trauma_hp": {
            "item_id": chosen_trauma_hp["item_id"],
            "ts": chosen_trauma_hp["ts"],
            "doc_type": "TRAUMA_HP",
            "match_tier": chosen_trauma_hp["match_tier"],
            "matched_pattern": chosen_trauma_hp["matched_pattern"],
            "matched_line_preview": chosen_trauma_hp["matched_line_preview"],
            "hpi_length_chars": len(hpi_field.value or "") if hpi_field.value and hpi_field.value != "DATA NOT AVAILABLE" else 0,
        } if chosen_trauma_hp else {},
        "hpi_evidence": {
            "field": "hpi",
            "chosen_doc_type": "TRAUMA_HP" if chosen_trauma_hp else None,
            "match_tier": chosen_trauma_hp["match_tier"] if chosen_trauma_hp else None,
            "matched_pattern": chosen_trauma_hp["matched_pattern"] if chosen_trauma_hp else None,
            "matched_line_preview": chosen_trauma_hp["matched_line_preview"] if chosen_trauma_hp else None,
            "item_id": chosen_trauma_hp["item_id"] if chosen_trauma_hp else None,
            "ts": chosen_trauma_hp["ts"] if chosen_trauma_hp else None,
            "hpi_length_chars": len(hpi_field.value or "") if hpi_field.value and hpi_field.value != "DATA NOT AVAILABLE" else 0,
        },
        "warnings": warnings,
    }

    return green_card, evidence_out, warnings


# ── CLI entry point ─────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description="GREEN CARD v1 extractor")
    ap.add_argument("--pat", required=True, help="Patient folder name")
    args = ap.parse_args()

    cfg = _load_config()
    green_card, evidence_out, warnings = extract_green_card(args.pat, cfg)

    out_dir = _REPO_ROOT / "outputs" / "green_card" / args.pat
    out_dir.mkdir(parents=True, exist_ok=True)

    gc_path = out_dir / "green_card_v1.json"
    ev_path = out_dir / "green_card_evidence_v1.json"

    with open(gc_path, "w", encoding="utf-8") as f:
        json.dump(green_card, f, indent=2, ensure_ascii=False)

    with open(ev_path, "w", encoding="utf-8") as f:
        json.dump(evidence_out, f, indent=2, ensure_ascii=False)

    # ── Write impression_plan_timeline_v1.json (separate file) ──
    ip_data = green_card.get("impression_plan", {})
    ip_path = out_dir / "impression_plan_timeline_v1.json"
    try:
        ip_timeline = {
            "meta": {
                "artifact": "impression_plan_timeline_v1",
                "version": "1.0.0",
                "created_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                "patient_slug": args.pat,
            },
            "entries": ip_data.get("entries", []),
            "drift_flags": ip_data.get("drift_flags", []),
            "sources": ip_data.get("sources", []),
            "warnings": ip_data.get("warnings", []),
        }
        with open(ip_path, "w", encoding="utf-8") as f:
            json.dump(ip_timeline, f, indent=2, ensure_ascii=False)
        print(f"  timeline:    {ip_path}")
    except Exception as exc:  # noqa: BLE001 – fail-closed
        _warnings_mod.warn("impression_plan_timeline_write_failed", stacklevel=1)
        print(
            f"WARNING: impression_plan_timeline_write_failed: {exc}",
            file=sys.stderr,
        )

    print(f"GREEN CARD v1: {gc_path}")
    print(f"  evidence:    {ev_path}")
    print(f"  warnings:    {len(warnings)}")
    for w in warnings:
        print(f"    - {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
