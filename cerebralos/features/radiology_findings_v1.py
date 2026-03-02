#!/usr/bin/env python3
"""
Radiology Findings Extraction v1 for CerebralOS.

Deterministic extraction of structured, protocol-relevant radiology
findings from RADIOLOGY, TRAUMA_HP, ED_NOTE, and PHYSICIAN_NOTE items.

Targeted finding categories (fail-closed on every subtype/count/grade):
  - Pneumothorax (presence + explicit subtype)
  - Hemothorax (presence + explicit qualifier)
  - Rib fracture (presence + explicit count + explicit rib numbers)
  - Flail chest (presence)
  - Solid organ injury — liver / spleen / kidney (presence + explicit grade)
  - Intracranial hemorrhage subtypes (EDH / SDH / SAH / ICH / IVH)
  - Pelvic fracture (presence)
  - Spinal fracture (presence + explicit level)
  - Extremity/long-bone fracture — femur / tibia / fibula / humerus /
    radius / ulna / clavicle / ankle / wrist / patella / scapula
    (presence + laterality + pathologic qualifier)

Sources (priority order):
  1. RADIOLOGY items — IMPRESSION section preferred, FINDINGS fallback
  2. TRAUMA_HP — impression/assessment sections
  3. ED_NOTE — impression/assessment
  4. PHYSICIAN_NOTE — impression/assessment

Output key: ``radiology_findings_v1`` (under top-level ``features`` dict)

Output schema::

    {
      "findings_present": "yes" | "no" | "DATA NOT AVAILABLE",
      "findings_labels": ["pneumothorax", "rib_fracture", ...],
      "pneumothorax": { ... } | null,
      "hemothorax": { ... } | null,
      "rib_fracture": { ... } | null,
      "flail_chest": { ... } | null,
      "solid_organ_injuries": [ ... ] | [],
      "intracranial_hemorrhage": [ ... ] | [],
      "pelvic_fracture": { ... } | null,
      "spinal_fracture": { ... } | null,
      "extremity_fracture": [ { "bone", "present", "laterality", "pathologic", "raw_line_id" } ] | [],
      "source_rule_id": "radiology_impression" | ... | "no_qualifying_source",
      "evidence": [ { "raw_line_id", "source", "ts", "snippet", "role" } ],
      "notes": [ ... ],
      "warnings": [ ... ]
    }

Fail-closed behavior:
  - Explicitly negated findings (e.g., "No pneumothorax") → NOT extracted
  - Subtypes/counts/grades only when explicitly documented
  - Chronic/stable/old findings excluded unless clearly acute
  - No inference from weak phrasing

Design:
- Deterministic, fail-closed.
- No LLM, no ML, no clinical inference.
- raw_line_id required on every stored evidence entry.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional, Tuple

_DNA = "DATA NOT AVAILABLE"

# ── Source type priority ────────────────────────────────────────────
_SOURCE_PRIORITY = ["RADIOLOGY", "TRAUMA_HP", "ED_NOTE", "PHYSICIAN_NOTE"]

# ── Section boundary patterns ──────────────────────────────────────

RE_IMPRESSION_START = re.compile(
    r"\bIMPRESSION\s*:", re.IGNORECASE,
)
RE_IMPRESSION_END = re.compile(
    r"\n\s*(?:FINDINGS|TECHNIQUE|HISTORY|INDICATION|COMPARISON|CLINICAL|"
    r"Electronically signed|Reading Physician)\b",
    re.IGNORECASE,
)
RE_FINDINGS_START = re.compile(
    r"\bFINDINGS\s*:", re.IGNORECASE,
)
RE_FINDINGS_END = re.compile(
    r"\b(?:IMPRESSION|TECHNIQUE|HISTORY|INDICATION|COMPARISON)\s*:",
    re.IGNORECASE,
)

# ── Negation context ───────────────────────────────────────────────
# Patterns that, when immediately preceding a finding keyword, negate it
_NEGATION_PREFIX = re.compile(
    # NOTE: longer phrases MUST come before shorter ones so Python's
    # left-to-right alternation selects the most specific match.
    r"(?:(?:no\s+evidence\s+of|no\s+acute|no\s+significant|no\s+definite"
    r"|no\s+associated|negative\s+for|not\s+identified"
    r"|without\s+evidence\s+of|without\s+associated|without"
    r"|absent|rules?\s+out|ruled\s+out|r/o"
    r"|no)\s+)"
    r"(?:(?:acute|significant|definite|obvious|residual)\s+)*",
    re.IGNORECASE,
)

# Chronic/history context — these indicate non-acute findings
_CHRONIC_PATTERNS = [
    re.compile(r"\b(?:chronic|stable|old|remote|healed|healing|prior|previous|"
               r"known|unchanged|resolved|resolving|residual)\b", re.IGNORECASE),
]


# ── Finding patterns ───────────────────────────────────────────────

# --- Pneumothorax ---
RE_PNEUMOTHORAX = re.compile(
    r"\b(pneumothorax|pneumothoraces|hemopneumothorax)\b", re.IGNORECASE,
)
RE_PNEUMOTHORAX_TYPE = re.compile(
    r"\b(tension|open|occult|simple|small|large|moderate|basilar|apical)\s+"
    r"(?:pneumothorax|pneumothoraces)\b",
    re.IGNORECASE,
)

# --- Hemothorax ---
RE_HEMOTHORAX = re.compile(
    r"\b(hemothorax|haemothorax|hemothoraces|hemopneumothorax)\b", re.IGNORECASE,
)
RE_HEMOTHORAX_QUALIFIER = re.compile(
    r"\b(massive|retained|large|small|moderate)\s+"
    r"(?:hemothorax|haemothorax)\b",
    re.IGNORECASE,
)

# --- Rib fracture ---
# Positional/laterality modifiers can appear in any order before "ribs"
_RIB_MOD = r"(?:(?:posterior|lateral|anterior|right|left|bilateral)\s+)*"
RE_RIB_FRACTURE = re.compile(
    r"\b(?:rib\s+fracture|rib\s+fx|fractured?\s+rib|rib\s+fractures"
    r"|fracture[sd]?\s+(?:(?:of|in)\s+)?(?:the\s+)?" + _RIB_MOD + r"ribs?"
    r"|fracture[sd]?\s+(?:(?:of|in)\s+)?(?:the\s+)?" + _RIB_MOD
    + r"(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|eleventh|twelfth|\d+(?:st|nd|rd|th)?)"
    r"(?:[,\s\-\u2013]+(?:and\s+|to\s+|through\s+)?(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|eleventh|twelfth|\d+(?:st|nd|rd|th)?))*\s*ribs?)\b",
    re.IGNORECASE,
)
# Also catch patterns like "right 1, 3, 4, 6, 7 rib fractures"
RE_RIB_FRACTURE_ALT = re.compile(
    r"\b(?:right|left|bilateral)\s+(?:\d+(?:\s*,\s*\d+)*)\s+rib\s+fractures?\b",
    re.IGNORECASE,
)
# Rib numbers extraction — e.g., "ribs 4-7", "ribs 1, 3, 4, 6, 7", "4th through 7th ribs"
RE_RIB_NUMBERS = re.compile(
    r"(?:ribs?\s+|rib\s+)(\d+(?:\s*[-–]\s*\d+)?(?:\s*,\s*\d+(?:\s*[-–]\s*\d+)?)*)"
    r"|(\d+(?:st|nd|rd|th)?(?:\s*[-–]\s*\d+(?:st|nd|rd|th)?)?)\s+ribs?\b"
    r"|(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|eleventh|twelfth)"
    r"(?:[,\s]+(?:and\s+)?(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|eleventh|twelfth))*\s+ribs?\b",
    re.IGNORECASE,
)
# Count of rib fractures — "multiple rib fractures", "5 rib fractures"
RE_RIB_COUNT = re.compile(
    r"(\d+)\s+rib\s+fractures?",
    re.IGNORECASE,
)

# --- Flail chest ---
RE_FLAIL_CHEST = re.compile(
    r"\bflail\s+chest\b", re.IGNORECASE,
)

# --- Solid organ injury ---
# Liver
RE_LIVER_INJURY = re.compile(
    r"\b(?:liver|hepatic)\s+(?:laceration|injury|contusion|hematoma|fracture|avulsion)\b"
    r"|\blaceration\s+(?:of\s+)?(?:the\s+)?liver\b",
    re.IGNORECASE,
)
RE_LIVER_GRADE = re.compile(
    r"\b(?:(?:AAST\s+)?(?:grade|gr\.?)\s*([IViv]+|\d+)"   # grade before organ
    r"|(?:laceration|injury|contusion|hematoma),?\s*(?:AAST\s+)?(?:grade|gr\.?)\s*([IViv]+|\d+))\b",  # grade after injury
    re.IGNORECASE,
)
# Spleen
RE_SPLEEN_INJURY = re.compile(
    r"\b(?:spleen|splenic)\s+(?:laceration|injury|contusion|hematoma|fracture|rupture|avulsion)\b"
    r"|\blaceration\s+(?:of\s+)?(?:the\s+)?spleen\b",
    re.IGNORECASE,
)
RE_SPLEEN_GRADE = re.compile(
    r"\b(?:(?:AAST\s+)?(?:grade|gr\.?)\s*([IViv]+|\d+)"   # grade before organ
    r"|(?:laceration|injury|contusion|hematoma),?\s*(?:AAST\s+)?(?:grade|gr\.?)\s*([IViv]+|\d+))\b",  # grade after injury
    re.IGNORECASE,
)
# Kidney
# Kidney — NOTE: "kidney injury" excluded (ambiguous with AKI medical diagnosis)
RE_KIDNEY_INJURY = re.compile(
    r"\b(?:kidney|renal)\s+(?:laceration|contusion|hematoma|fracture|avulsion)\b"
    r"|\blaceration\s+(?:of\s+)?(?:the\s+)?kidney\b",
    re.IGNORECASE,
)
RE_KIDNEY_GRADE = re.compile(
    r"\b(?:(?:AAST\s+)?(?:grade|gr\.?)\s*([IViv]+|\d+)"   # grade before organ
    r"|(?:laceration|injury|contusion|hematoma),?\s*(?:AAST\s+)?(?:grade|gr\.?)\s*([IViv]+|\d+))\b",  # grade after injury
    re.IGNORECASE,
)

# --- Intracranial hemorrhage subtypes ---
RE_ICH_SUBTYPES: List[Tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(?:epidural\s+(?:hemorrhage|hematoma|haematoma)|EDH)\b", re.IGNORECASE), "edh"),
    (re.compile(r"\b(?:subdural\s+(?:hemorrhage|hematoma|haematoma)|SDH)\b", re.IGNORECASE), "sdh"),
    (re.compile(r"\b(?:subarachnoid\s+(?:hemorrhage|haemorrhage)|SAH)\b", re.IGNORECASE), "sah"),
    (re.compile(r"\b(?:intraparenchymal\s+(?:hemorrhage|haemorrhage)|intracerebral\s+(?:hemorrhage|haemorrhage)|ICH)\b", re.IGNORECASE), "ich"),
    (re.compile(r"\b(?:intraventricular\s+(?:hemorrhage|haemorrhage)|IVH)\b", re.IGNORECASE), "ivh"),
]
# Generic intracranial hemorrhage (positive statement only)
RE_INTRACRANIAL_HEMORRHAGE = re.compile(
    r"\b(?:intracranial\s+hemorrhage|intracranial\s+haemorrhage"
    r"|intracranial\s+bleed(?:ing)?)\b",
    re.IGNORECASE,
)

# --- Pelvic fracture ---
RE_PELVIC_FRACTURE = re.compile(
    r"\b(?:pelvic\s+fracture|pelvis\s+fracture|fractured?\s+pelvis"
    r"|(?:acetabul(?:ar|um)|pubic\s+ramus|pubic\s+rami|iliac|sacr(?:al|um))\s+fracture"
    r"|fracture[sd]?\s+(?:of\s+)?(?:the\s+)?(?:pelvis|acetabulum|pubic))\b",
    re.IGNORECASE,
)
# Also catch "left hip fracture", "hip fracture" as pelvic category
RE_HIP_FRACTURE = re.compile(
    r"\b(?:hip\s+fracture|fractured?\s+hip|fracture[sd]?\s+(?:of\s+)?(?:the\s+)?(?:left\s+|right\s+)?hip)\b",
    re.IGNORECASE,
)

# --- Extremity / long-bone fracture ---
# Femur (shaft, neck, proximal, distal, intertrochanteric, subtrochanteric)
RE_FEMUR_FRACTURE = re.compile(
    r"\b(?:femur|femoral)(?:\s+(?:shaft|neck|head|proximal|distal"
    r"|intertrochanteric|subtrochanteric|supracondylar|trochanter(?:ic)?"
    r"|greater\s+trochanter|lesser\s+trochanter))?\s+fracture"
    r"|fracture[sd]?\s+(?:(?:of|in|through)\s+)?(?:the\s+)?"
    r"(?:(?:right|left)\s+)?(?:proximal\s+|distal\s+)?"
    r"(?:femur|femoral\s+(?:neck|shaft|head))"
    r"|(?:intertrochanteric|subtrochanteric|supracondylar|trochanteric)"
    r"\s+(?:femur\s+)?fracture\b",
    re.IGNORECASE,
)
# Tibia (plateau, shaft, proximal, distal, pilon)
RE_TIBIA_FRACTURE = re.compile(
    r"\b(?:tibia[l]?|tibial)(?:\s+(?:plateau|shaft|proximal|distal|pilon"
    r"|eminence|spine|tubercle))?\s+fracture"
    r"|fracture[sd]?\s+(?:(?:of|in|through)\s+)?(?:the\s+)?"
    r"(?:(?:right|left)\s+)?(?:proximal\s+|distal\s+)?tibia"
    r"|tibial\s+plateau\s+fracture\b",
    re.IGNORECASE,
)
# Fibula
RE_FIBULA_FRACTURE = re.compile(
    r"\b(?:fibula[r]?|fibular)(?:\s+(?:shaft|head|proximal|distal|styloid))?"
    r"\s+fracture"
    r"|fracture[sd]?\s+(?:(?:of|in|through)\s+)?(?:the\s+)?"
    r"(?:(?:right|left)\s+)?fibu?la\b",
    re.IGNORECASE,
)
# Humerus (shaft, proximal, distal, supracondylar, surgical-neck)
RE_HUMERUS_FRACTURE = re.compile(
    r"\b(?:humer(?:us|al))(?:\s+(?:shaft|head|proximal|distal"
    r"|supracondylar|surgical\s+neck|anatomical\s+neck|greater\s+tuberosity"
    r"|lesser\s+tuberosity))?\s+fracture"
    r"|fracture[sd]?\s+(?:(?:of|in|through)\s+)?(?:the\s+)?"
    r"(?:(?:right|left)\s+)?(?:proximal\s+|distal\s+)?humerus\b",
    re.IGNORECASE,
)
# Radius (distal, head, shaft, Colles, Smith)
RE_RADIUS_FRACTURE = re.compile(
    r"\b(?:radi(?:us|al))(?:\s+(?:shaft|head|proximal|distal|styloid))?"
    r"\s+fracture"
    r"|fracture[sd]?\s+(?:(?:of|in|through)\s+)?(?:the\s+)?"
    r"(?:(?:right|left)\s+)?(?:distal\s+)?radius"
    r"|(?:Colles|Smith)(?:'s)?\s+fracture\b",
    re.IGNORECASE,
)
# Ulna (olecranon, shaft, coronoid, Monteggia)
RE_ULNA_FRACTURE = re.compile(
    r"\b(?:uln(?:a[r]?|ar))(?:\s+(?:shaft|proximal|distal|coronoid|olecranon))?"
    r"\s+fracture"
    r"|fracture[sd]?\s+(?:(?:of|in|through)\s+)?(?:the\s+)?"
    r"(?:(?:right|left)\s+)?ulna"
    r"|olecranon\s+fracture"
    r"|Monteggia(?:'s)?\s+fracture\b",
    re.IGNORECASE,
)
# Clavicle
RE_CLAVICLE_FRACTURE = re.compile(
    r"\b(?:clavicle|clavicular)(?:\s+(?:shaft|mid[\s-]?shaft|proximal|distal|lateral))?"
    r"\s+fracture"
    r"|fracture[sd]?\s+(?:(?:of|in|through)\s+)?(?:the\s+)?"
    r"(?:(?:right|left)\s+)?clavicle\b",
    re.IGNORECASE,
)
# Ankle (malleolus, bimalleolar, trimalleolar)
RE_ANKLE_FRACTURE = re.compile(
    r"\b(?:ankle\s+fracture|fractured?\s+ankle"
    r"|(?:lateral|medial|posterior)\s+malleol(?:us|ar)\s+fracture"
    r"|(?:bi|tri)malleolar\s+fracture"
    r"|malleol(?:us|ar)\s+fracture"
    r"|fracture[sd]?\s+(?:(?:of|in|through)\s+)?(?:the\s+)?ankle)\b",
    re.IGNORECASE,
)
# Wrist (scaphoid, distal-radius already above, generic wrist fracture)
RE_WRIST_FRACTURE = re.compile(
    r"\b(?:wrist\s+fracture|fractured?\s+wrist"
    r"|scaphoid\s+fracture"
    r"|fracture[sd]?\s+(?:(?:of|in|through)\s+)?(?:the\s+)?wrist)\b",
    re.IGNORECASE,
)
# Patella
RE_PATELLA_FRACTURE = re.compile(
    r"\b(?:patell(?:a[r]?|ar)\s+fracture"
    r"|fracture[sd]?\s+(?:(?:of|in|through)\s+)?(?:the\s+)?patella)\b",
    re.IGNORECASE,
)
# Scapula
RE_SCAPULA_FRACTURE = re.compile(
    r"\b(?:scapul(?:a[r]?|ar)\s+fracture"
    r"|fracture[sd]?\s+(?:(?:of|in|through)\s+)?(?:the\s+)?scapula)\b",
    re.IGNORECASE,
)

# All extremity fracture patterns: (regex, bone_label)
_EXTREMITY_FRACTURE_PATTERNS: List[Tuple[re.Pattern[str], str]] = [
    (RE_FEMUR_FRACTURE, "femur"),
    (RE_TIBIA_FRACTURE, "tibia"),
    (RE_FIBULA_FRACTURE, "fibula"),
    (RE_HUMERUS_FRACTURE, "humerus"),
    (RE_RADIUS_FRACTURE, "radius"),
    (RE_ULNA_FRACTURE, "ulna"),
    (RE_CLAVICLE_FRACTURE, "clavicle"),
    (RE_ANKLE_FRACTURE, "ankle"),
    (RE_WRIST_FRACTURE, "wrist"),
    (RE_PATELLA_FRACTURE, "patella"),
    (RE_SCAPULA_FRACTURE, "scapula"),
]

# Pathologic-fracture qualifier (applied to any fracture context)
RE_PATHOLOGIC_QUALIFIER = re.compile(
    r"\bpathologic(?:al)?\s+fracture\b",
    re.IGNORECASE,
)

# Laterality for extremity fractures
RE_EXTREMITY_LATERALITY = re.compile(
    r"\b(right|left|bilateral)\b",
    re.IGNORECASE,
)

# --- Spinal fracture ---
RE_SPINAL_FRACTURE = re.compile(
    r"\b(?:spinal\s+fracture|spine\s+fracture|vertebral?\s+(?:body\s+)?fracture"
    r"|(?:distraction|extension|flexion|compression|burst)\s+fracture"
    r"|fracture[sd]?\s+(?:(?:of|in|through)\s+)?(?:the\s+)?(?:spine|vertebra[le]?|vertebral\s+body)"
    r"|compression\s+fracture|burst\s+fracture"
    r"|(?:C[1-7]|T\d{1,2}|L[1-5]|S[1-5])\s+(?:vertebral\s+body\s+)?(?:distraction\s+|compression\s+|burst\s+)?fracture"
    r"|fracture\s+(?:(?:of|in|through)\s+)?(?:the\s+)?(?:C[1-7]|T\d{1,2}|L[1-5]|S[1-5])(?:\s+vertebral\s+body)?)\b",
    re.IGNORECASE,
)
# Extract spinal level (e.g., "S4", "L1", "T5-T6")
RE_SPINAL_LEVEL = re.compile(
    r"\b(C[1-7]|T\d{1,2}|L[1-5]|S[1-5])(?:\s*[-–]\s*(C[1-7]|T\d{1,2}|L[1-5]|S[1-5]))?\b",
    re.IGNORECASE,
)


# ── Helpers ─────────────────────────────────────────────────────────

def _make_raw_line_id(
    source_type: str,
    source_id: Optional[str],
    line_text: str,
) -> str:
    """Build a deterministic raw_line_id from evidence coordinates."""
    payload = f"{source_type}|{source_id or ''}|{line_text.strip()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _snippet(text: str, max_len: int = 120) -> str:
    """Trim text to a short deterministic snippet."""
    text = str(text).strip()
    if len(text) <= max_len:
        return text
    return text[:max_len] + "\u2026"


def _extract_section(
    text: str, start_re: re.Pattern, end_re: re.Pattern,
) -> Optional[str]:
    """Extract text between start and end patterns."""
    m_start = start_re.search(text)
    if not m_start:
        return None
    rest = text[m_start.end():]
    m_end = end_re.search(rest)
    if m_end:
        return rest[:m_end.start()]
    return rest


def _is_negated(text: str, match_start: int, match_end: int) -> bool:
    """
    Check if a finding match is preceded by negation context.

    We look at the 80 characters before the match for negation phrases.
    Two tiers:
      1. Gap <= 10 chars  → always negated (adjective gap)
      2. Gap <= 60 chars  → negated only if no sentence boundary (period
         followed by space/end) exists between the negation phrase and
         the match.  This covers coordinated-conjunction constructions
         like "No pleural effusion or pneumothorax".
    """
    window_start = max(0, match_start - 80)
    pre_text = text[window_start:match_start]
    # Search for negation patterns in the preceding window
    for m_neg in _NEGATION_PREFIX.finditer(pre_text):
        # The negation phrase ending should be close to match_start
        neg_end_pos = window_start + m_neg.end()
        gap = match_start - neg_end_pos
        if gap <= 10:
            return True
        # Larger gap: allow if within the same clause (no sentence break)
        if gap <= 60:
            between = text[neg_end_pos:match_start]
            # A sentence break is a period followed by whitespace + capital,
            # or a period at the very end of the intervening text.
            if not re.search(r'\.\s+[A-Z]', between) and not between.rstrip().endswith('.'):
                return True
    return False


def _is_chronic(text: str, match_start: int, match_end: int) -> bool:
    """
    Check if a finding match is in chronic/stable/old context.

    Scans a window around the match for chronic qualifiers.
    Only suppresses if the chronic word is within ~40 chars before the match.
    """
    window_start = max(0, match_start - 40)
    window = text[window_start:match_start]
    for pat in _CHRONIC_PATTERNS:
        if pat.search(window):
            return True
    return False


# Laterality pattern — "right", "left", "bilateral" near rib context
RE_RIB_LATERALITY = re.compile(
    r"\b(right|left|bilateral)\b",
    re.IGNORECASE,
)


def _parse_rib_numbers(text: str) -> Optional[List[str]]:
    """
    Extract explicit rib numbers from text near a rib fracture mention.

    Handles:
      - Bare numeric ranges: "4-7" → [4,5,6,7]
      - Ordinal-suffix ranges: "5th-7th", "9th-10th" → [5,6,7], [9,10]
      - Partial-suffix ranges: "5-7th", "9-10th" → [5,6,7], [9,10]
      - Word range separators: "5th to 7th", "5th through 7th"
      - Comma-separated values: "1, 3, 4, 6, 7"
      - Ordinal words: "first", "ninth" etc.
      - Mixed ordinal word + suffix: "ninth and 10th"

    Returns a sorted list of rib number strings, or None if not deterministic.
    """
    # Ordinal word to number mapping
    word_to_num = {
        "first": "1", "second": "2", "third": "3", "fourth": "4",
        "fifth": "5", "sixth": "6", "seventh": "7", "eighth": "8",
        "ninth": "9", "tenth": "10", "eleventh": "11", "twelfth": "12",
    }

    numbers: List[int] = []

    # Try numeric / ordinal-suffix ranges:
    #   "4-7", "5th-7th", "5-7th", "5th to 7th", "5th through 7th"
    _RE_RIB_RANGE = re.compile(
        r"(\d+)(?:st|nd|rd|th)?\s*(?:[-–]|\bto\b|\bthrough\b)\s*(\d+)(?:st|nd|rd|th)?",
        re.IGNORECASE,
    )
    num_matches = _RE_RIB_RANGE.findall(text)
    for start, end in num_matches:
        s, e = int(start), int(end)
        if 1 <= s <= 12 and 1 <= e <= 12 and s <= e:
            numbers.extend(range(s, e + 1))

    # Individual digits near "rib" context (skip those already captured)
    # Must handle ordinal suffixes: "10th" → 10
    # Exclude list markers like "2." via negative lookahead
    simple_nums = re.findall(r"\b(\d{1,2})(?:st|nd|rd|th)?\b(?!\.)", text)
    for n_str in simple_nums:
        n = int(n_str)
        if 1 <= n <= 12:
            if n not in numbers:
                numbers.append(n)

    # Ordinal words
    for word, num_str in word_to_num.items():
        if re.search(r"\b" + word + r"\b", text, re.IGNORECASE):
            n = int(num_str)
            if n not in numbers:
                numbers.append(n)

    if not numbers:
        return None

    return sorted(set(str(n) for n in numbers), key=lambda x: int(x))


def _parse_rib_laterality(text: str) -> Optional[str]:
    """
    Extract laterality from text near a rib fracture mention.

    Returns "right", "left", "bilateral", or None.
    """
    m = RE_RIB_LATERALITY.search(text)
    if m:
        return m.group(1).lower()
    return None


def _grade_to_string(raw: str) -> Optional[str]:
    """Normalize a grade string (roman or arabic) to arabic string."""
    roman_map = {"i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5"}
    lower = raw.strip().lower()
    if lower in roman_map:
        return roman_map[lower]
    if lower.isdigit() and 1 <= int(lower) <= 5:
        return lower
    return None


# ── Core per-text extraction ────────────────────────────────────────

def _extract_findings_from_text(
    text: str,
    source_type: str,
    source_id: Optional[str],
    ts: Optional[str],
) -> Dict[str, Any]:
    """
    Scan a single text block for radiology findings.

    Prefers IMPRESSION section, falls back to FINDINGS section,
    then full text for TRAUMA_HP sources.

    Returns a dict of per-category results + evidence list.
    """
    # Choose the best section to scan
    impression = _extract_section(text, RE_IMPRESSION_START, RE_IMPRESSION_END)
    findings_section = _extract_section(text, RE_FINDINGS_START, RE_FINDINGS_END)

    # For RADIOLOGY items: prefer impression, fall back to findings
    # For clinical notes: scan impression/assessment + findings
    scan_text = ""
    section_source = None
    if impression:
        scan_text = impression
        section_source = "impression"
    elif findings_section:
        scan_text = findings_section
        section_source = "findings"
    elif source_type == "TRAUMA_HP":
        # For TRAUMA_HP, scan full text as it may embed findings inline
        scan_text = text
        section_source = "full_text"
    elif source_type in ("ED_NOTE", "PHYSICIAN_NOTE"):
        # For clinical notes, try full text only if short
        scan_text = text
        section_source = "full_text"

    if not scan_text.strip():
        return {"categories": {}, "evidence": [], "notes": [], "section_source": None}

    categories: Dict[str, Dict[str, Any]] = {}
    evidence: List[Dict[str, Any]] = []
    notes: List[str] = []

    def _add_evidence(role: str, label: str, m: re.Match, ctx_text: str) -> str:
        """Add an evidence entry and return raw_line_id."""
        window = ctx_text[max(0, m.start() - 40):m.end() + 40]
        raw_line_id = _make_raw_line_id(source_type, source_id, window)
        evidence.append({
            "raw_line_id": raw_line_id,
            "source": source_type,
            "ts": ts,
            "snippet": _snippet(window),
            "role": role,
            "label": label,
        })
        return raw_line_id

    # ── Pneumothorax ────────────────────────────────────────────
    for m in RE_PNEUMOTHORAX.finditer(scan_text):
        if _is_negated(scan_text, m.start(), m.end()):
            continue
        if _is_chronic(scan_text, m.start(), m.end()):
            notes.append("chronic_context_excluded: pneumothorax appears in chronic context")
            continue
        # Extract subtype if explicit
        subtype = None
        m_type = RE_PNEUMOTHORAX_TYPE.search(scan_text)
        if m_type:
            subtype = m_type.group(1).lower()
        raw_id = _add_evidence("finding", "pneumothorax", m, scan_text)
        if "pneumothorax" not in categories:
            categories["pneumothorax"] = {
                "present": True,
                "subtype": subtype,
                "raw_line_id": raw_id,
            }
        break  # One pneumothorax finding per text block

    # ── Hemothorax ──────────────────────────────────────────────
    for m in RE_HEMOTHORAX.finditer(scan_text):
        if _is_negated(scan_text, m.start(), m.end()):
            continue
        if _is_chronic(scan_text, m.start(), m.end()):
            notes.append("chronic_context_excluded: hemothorax appears in chronic context")
            continue
        qualifier = None
        m_qual = RE_HEMOTHORAX_QUALIFIER.search(scan_text)
        if m_qual:
            qualifier = m_qual.group(1).lower()
        # hemopneumothorax also counts as pneumothorax
        matched_term = m.group(1).lower()
        if matched_term == "hemopneumothorax" and "pneumothorax" not in categories:
            categories["pneumothorax"] = {
                "present": True,
                "subtype": None,
                "raw_line_id": _make_raw_line_id(source_type, source_id,
                    scan_text[max(0, m.start()-40):m.end()+40]),
            }
        raw_id = _add_evidence("finding", "hemothorax", m, scan_text)
        if "hemothorax" not in categories:
            categories["hemothorax"] = {
                "present": True,
                "qualifier": qualifier,
                "raw_line_id": raw_id,
            }
        break

    # ── Rib fracture ────────────────────────────────────────────
    rib_found = False
    for m in list(RE_RIB_FRACTURE.finditer(scan_text)) + list(RE_RIB_FRACTURE_ALT.finditer(scan_text)):
        if _is_negated(scan_text, m.start(), m.end()):
            continue
        if _is_chronic(scan_text, m.start(), m.end()):
            notes.append("chronic_context_excluded: rib fracture appears in chronic context")
            continue
        if rib_found:
            break
        rib_found = True

        # Extract count if explicit
        count = None
        m_count = RE_RIB_COUNT.search(scan_text)
        if m_count:
            try:
                count = int(m_count.group(1))
            except ValueError:
                pass

        # Extract rib numbers — scan broader context
        rib_context = scan_text[max(0, m.start() - 80):m.end() + 80]
        rib_numbers = _parse_rib_numbers(rib_context)

        # If we found rib numbers, derive count from them if not explicit
        if rib_numbers and count is None:
            count = len(rib_numbers)

        # Extract laterality
        laterality = _parse_rib_laterality(rib_context)

        raw_id = _add_evidence("finding", "rib_fracture", m, scan_text)
        categories["rib_fracture"] = {
            "present": True,
            "count": count,
            "rib_numbers": rib_numbers,
            "laterality": laterality,
            "raw_line_id": raw_id,
        }

    # ── Flail chest ─────────────────────────────────────────────
    for m in RE_FLAIL_CHEST.finditer(scan_text):
        if _is_negated(scan_text, m.start(), m.end()):
            continue
        raw_id = _add_evidence("finding", "flail_chest", m, scan_text)
        if "flail_chest" not in categories:
            categories["flail_chest"] = {
                "present": True,
                "raw_line_id": raw_id,
            }
        break

    # ── Solid organ injuries ────────────────────────────────────
    for organ, injury_re, grade_re, organ_label in [
        ("liver", RE_LIVER_INJURY, RE_LIVER_GRADE, "liver"),
        ("spleen", RE_SPLEEN_INJURY, RE_SPLEEN_GRADE, "spleen"),
        ("kidney", RE_KIDNEY_INJURY, RE_KIDNEY_GRADE, "kidney"),
    ]:
        for m in injury_re.finditer(scan_text):
            if _is_negated(scan_text, m.start(), m.end()):
                continue
            if _is_chronic(scan_text, m.start(), m.end()):
                notes.append(f"chronic_context_excluded: {organ} injury appears in chronic context")
                continue
            # Look for grade near this mention (within ~60 chars)
            grade = None
            grade_window = scan_text[max(0, m.start() - 60):m.end() + 60]
            m_grade = grade_re.search(grade_window)
            if m_grade:
                # grade regex has two groups: group(1) for grade-before,
                # group(2) for grade-after-injury.  Use whichever matched.
                raw_grade = m_grade.group(1) or m_grade.group(2)
                if raw_grade:
                    grade = _grade_to_string(raw_grade)
            raw_id = _add_evidence("finding", f"{organ_label}_injury", m, scan_text)
            categories.setdefault("solid_organ_injuries", []).append({
                "organ": organ_label,
                "present": True,
                "grade": grade,
                "raw_line_id": raw_id,
            })
            break  # One per organ per text block

    # ── Intracranial hemorrhage ─────────────────────────────────
    for ich_re, subtype_label in RE_ICH_SUBTYPES:
        for m in ich_re.finditer(scan_text):
            if _is_negated(scan_text, m.start(), m.end()):
                continue
            if _is_chronic(scan_text, m.start(), m.end()):
                notes.append(
                    f"chronic_context_excluded: {subtype_label} appears in chronic context"
                )
                continue
            raw_id = _add_evidence("finding", subtype_label, m, scan_text)
            categories.setdefault("intracranial_hemorrhage", []).append({
                "subtype": subtype_label,
                "present": True,
                "raw_line_id": raw_id,
            })
            break  # One per subtype per text block

    # Also check generic intracranial hemorrhage
    for m in RE_INTRACRANIAL_HEMORRHAGE.finditer(scan_text):
        if _is_negated(scan_text, m.start(), m.end()):
            continue
        if _is_chronic(scan_text, m.start(), m.end()):
            continue
        # Only add generic if no specific subtypes found
        existing_subtypes = [
            e.get("subtype") for e in categories.get("intracranial_hemorrhage", [])
        ]
        if not existing_subtypes:
            raw_id = _add_evidence("finding", "intracranial_hemorrhage", m, scan_text)
            categories.setdefault("intracranial_hemorrhage", []).append({
                "subtype": "unspecified",
                "present": True,
                "raw_line_id": raw_id,
            })
        break

    # ── Pelvic fracture ─────────────────────────────────────────
    pelvic_found = False
    for pat in [RE_PELVIC_FRACTURE, RE_HIP_FRACTURE]:
        if pelvic_found:
            break
        for m in pat.finditer(scan_text):
            if _is_negated(scan_text, m.start(), m.end()):
                continue
            if _is_chronic(scan_text, m.start(), m.end()):
                notes.append("chronic_context_excluded: pelvic/hip fracture appears in chronic context")
                continue
            raw_id = _add_evidence("finding", "pelvic_fracture", m, scan_text)
            if "pelvic_fracture" not in categories:
                categories["pelvic_fracture"] = {
                    "present": True,
                    "raw_line_id": raw_id,
                }
            pelvic_found = True
            break

    # ── Extremity / long-bone fracture ──────────────────────────
    extremity_entries: List[Dict[str, Any]] = []
    seen_bones: set = set()
    for ext_re, bone_label in _EXTREMITY_FRACTURE_PATTERNS:
        for m in ext_re.finditer(scan_text):
            if _is_negated(scan_text, m.start(), m.end()):
                continue
            if _is_chronic(scan_text, m.start(), m.end()):
                notes.append(
                    f"chronic_context_excluded: {bone_label} fracture "
                    f"appears in chronic context"
                )
                continue
            if bone_label in seen_bones:
                break  # one per bone per text block
            seen_bones.add(bone_label)
            # Laterality
            lat_window = scan_text[max(0, m.start() - 30):m.end() + 10]
            m_lat = RE_EXTREMITY_LATERALITY.search(lat_window)
            laterality = m_lat.group(1).lower() if m_lat else None
            # Pathologic qualifier
            path_window = scan_text[max(0, m.start() - 80):m.end() + 40]
            pathologic = bool(RE_PATHOLOGIC_QUALIFIER.search(path_window))
            raw_id = _add_evidence(
                "finding", f"{bone_label}_fracture", m, scan_text,
            )
            extremity_entries.append({
                "bone": bone_label,
                "present": True,
                "laterality": laterality,
                "pathologic": pathologic,
                "raw_line_id": raw_id,
            })
            break  # first non-negated, non-chronic match per bone
    if extremity_entries:
        categories["extremity_fracture"] = extremity_entries

    # ── Spinal fracture ─────────────────────────────────────────
    for m in RE_SPINAL_FRACTURE.finditer(scan_text):
        if _is_negated(scan_text, m.start(), m.end()):
            continue
        if _is_chronic(scan_text, m.start(), m.end()):
            notes.append("chronic_context_excluded: spinal fracture appears in chronic context")
            continue
        # Extract level
        level = None
        level_window = scan_text[max(0, m.start() - 20):m.end() + 20]
        m_level = RE_SPINAL_LEVEL.search(level_window)
        if m_level:
            level = m_level.group(0).upper().strip()
        raw_id = _add_evidence("finding", "spinal_fracture", m, scan_text)
        if "spinal_fracture" not in categories:
            categories["spinal_fracture"] = {
                "present": True,
                "level": level,
                "raw_line_id": raw_id,
            }
        break

    return {
        "categories": categories,
        "evidence": evidence,
        "notes": notes,
        "section_source": section_source,
    }


# ── Public API ──────────────────────────────────────────────────────

def extract_radiology_findings(
    pat_features: Dict[str, Any],
    days_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Deterministic radiology findings extraction from timeline items.

    Parameters
    ----------
    pat_features : dict
        The in-progress patient features dict (with "days" key).
    days_data : dict
        The full patient_days_v1.json structure for raw text access.

    Returns
    -------
    dict
        radiology_findings_v1 contract output.
    """
    evidence: List[Dict[str, Any]] = []
    notes: List[str] = []
    warnings: List[str] = []

    days_map = days_data.get("days") or {}

    # ── Collect qualifying items, sorted by priority + timestamp ─
    qualifying_items: List[Tuple[int, str, Dict[str, Any]]] = []
    for day_iso in sorted(days_map.keys()):
        for item in days_map[day_iso].get("items") or []:
            item_type = item.get("type", "")
            if item_type in _SOURCE_PRIORITY:
                priority = _SOURCE_PRIORITY.index(item_type)
                dt = item.get("dt", "")
                qualifying_items.append((priority, dt, item))

    qualifying_items.sort(key=lambda x: (x[0], x[1]))

    if not qualifying_items:
        return {
            "findings_present": _DNA,
            "findings_labels": [],
            "pneumothorax": None,
            "hemothorax": None,
            "rib_fracture": None,
            "flail_chest": None,
            "solid_organ_injuries": [],
            "intracranial_hemorrhage": [],
            "pelvic_fracture": None,
            "spinal_fracture": None,
            "extremity_fracture": [],
            "source_rule_id": "no_qualifying_source",
            "evidence": [],
            "notes": ["no RADIOLOGY, TRAUMA_HP, ED_NOTE, or PHYSICIAN_NOTE items found"],
            "warnings": [],
        }

    # ── Scan ALL qualifying items and merge findings ────────────
    merged_categories: Dict[str, Any] = {}
    all_evidence: List[Dict[str, Any]] = []
    all_notes: List[str] = []
    source_rule_ids: List[str] = []

    for _priority, _dt, item in qualifying_items:
        item_type = item.get("type", "")
        text = (item.get("payload") or {}).get("text", "")
        source_id = item.get("source_id")
        ts = item.get("dt")

        if not text.strip():
            continue

        result = _extract_findings_from_text(text, item_type, source_id, ts)

        cats = result["categories"]
        all_evidence.extend(result["evidence"])
        all_notes.extend(result["notes"])

        if cats:
            section = result["section_source"] or "full_text"
            rule_id = f"{item_type.lower()}_{section}"
            if rule_id not in source_rule_ids:
                source_rule_ids.append(rule_id)

        # Merge categories — first occurrence wins for scalar categories
        for cat_key, cat_val in cats.items():
            if cat_key in ("solid_organ_injuries", "intracranial_hemorrhage",
                           "extremity_fracture"):
                # Merge lists, dedup by organ/subtype
                existing = merged_categories.setdefault(cat_key, [])
                if isinstance(cat_val, list):
                    for entry in cat_val:
                        # Check if organ/subtype/bone already seen
                        key_field = (
                            "organ" if cat_key == "solid_organ_injuries"
                            else "bone" if cat_key == "extremity_fracture"
                            else "subtype"
                        )
                        existing_keys = [e.get(key_field) for e in existing]
                        if entry.get(key_field) not in existing_keys:
                            existing.append(entry)
            else:
                # First occurrence wins for scalar categories
                if cat_key not in merged_categories:
                    merged_categories[cat_key] = cat_val

    # ── Build findings_labels from merged categories ────────────
    findings_labels: List[str] = []
    for label in [
        "pneumothorax", "hemothorax", "rib_fracture", "flail_chest",
        "pelvic_fracture", "spinal_fracture", "extremity_fracture",
    ]:
        if label in merged_categories:
            findings_labels.append(label)

    # Add individual extremity bone labels
    for entry in merged_categories.get("extremity_fracture", []):
        bone = entry.get("bone")
        if bone:
            label = f"{bone}_fracture"
            if label not in findings_labels:
                findings_labels.append(label)

    # Add solid organ labels
    for entry in merged_categories.get("solid_organ_injuries", []):
        organ = entry.get("organ")
        if organ:
            label = f"{organ}_injury"
            if label not in findings_labels:
                findings_labels.append(label)

    # Add intracranial hemorrhage labels
    for entry in merged_categories.get("intracranial_hemorrhage", []):
        subtype = entry.get("subtype")
        if subtype:
            label = subtype if subtype != "unspecified" else "intracranial_hemorrhage"
            if label not in findings_labels:
                findings_labels.append(label)

    # ── Determine findings_present ──────────────────────────────
    if findings_labels:
        findings_present = "yes"
    else:
        findings_present = "no"

    # ── Select primary source_rule_id ───────────────────────────
    source_rule_id = source_rule_ids[0] if source_rule_ids else "no_findings_matched"

    return {
        "findings_present": findings_present,
        "findings_labels": findings_labels,
        "pneumothorax": merged_categories.get("pneumothorax"),
        "hemothorax": merged_categories.get("hemothorax"),
        "rib_fracture": merged_categories.get("rib_fracture"),
        "flail_chest": merged_categories.get("flail_chest"),
        "solid_organ_injuries": merged_categories.get("solid_organ_injuries", []),
        "intracranial_hemorrhage": merged_categories.get("intracranial_hemorrhage", []),
        "pelvic_fracture": merged_categories.get("pelvic_fracture"),
        "spinal_fracture": merged_categories.get("spinal_fracture"),
        "extremity_fracture": merged_categories.get("extremity_fracture", []),
        "source_rule_id": source_rule_id,
        "evidence": all_evidence,
        "notes": all_notes,
        "warnings": warnings,
    }
