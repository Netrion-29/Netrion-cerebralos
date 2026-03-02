#!/usr/bin/env python3
"""
Mechanism of Injury + Body Region Extraction v1 for CerebralOS.

Deterministic extraction of:
  1) Injury mechanism (e.g., fall, MVC, GSW, stab, crush, industrial)
  2) Body region mentions relevant to trauma protocols

Sources (priority order — earliest/arrival-context preferred):
  1. TRAUMA_HP  — HPI section (mechanism) + Secondary Survey (regions)
  2. ED_NOTE    — fallback if TRAUMA_HP absent
  3. PHYSICIAN_NOTE — fallback if both above absent
  4. CONSULT_NOTE — lowest priority

Output key: ``mechanism_region_v1`` (under top-level ``features`` dict)

Output schema::

    {
      "mechanism_present": "yes" | "no" | "DATA NOT AVAILABLE",
      "mechanism_primary": "<canonical label>" | null,
      "mechanism_labels": ["fall", ...] | [],
      "penetrating_mechanism": true | false | null,
      "body_region_present": "yes" | "no" | "DATA NOT AVAILABLE",
      "body_region_labels": ["head", "chest", ...] | [],
      "source_rule_id": "trauma_hp_hpi" | "ed_note_hpi" | "physician_note_hpi"
                        | "consult_note_hpi" | "no_qualifying_source" | null,
      "evidence": [
          {
              "raw_line_id": "...",
              "source": "TRAUMA_HP" | "ED_NOTE" | ...,
              "ts": "..." | null,
              "snippet": "...",
              "role": "mechanism" | "body_region"
          }, ...
      ],
      "notes": [ ... ],
      "warnings": [ ... ]
    }

Fail-closed behavior:
  - If no qualifying source exists → mechanism_present = "DATA NOT AVAILABLE"
  - If source exists but no mechanism pattern matches → mechanism_present = "no"
  - Chronic/history wording is excluded to avoid overmatching non-acute mechanisms
  - Penetrating mechanism derived only from explicit labels (GSW, stab, impalement)

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

# ── Source type priority (lower index = higher priority) ────────────
_SOURCE_PRIORITY = ["TRAUMA_HP", "ED_NOTE", "PHYSICIAN_NOTE", "CONSULT_NOTE"]

# ── Mechanism patterns ──────────────────────────────────────────────
# Each pattern: (compiled_regex, canonical_label, is_penetrating)
# Patterns are applied to HPI text.  Order matters for primary label
# selection (first match in priority order wins as primary).

_MECHANISM_PATTERNS: List[Tuple[re.Pattern[str], str, bool]] = [
    # Penetrating mechanisms
    (re.compile(r"\bGSW\b", re.IGNORECASE), "gsw", True),
    (re.compile(r"\bgunshot\s+wound\b", re.IGNORECASE), "gsw", True),
    (re.compile(r"\bgun\s*shot\b", re.IGNORECASE), "gsw", True),
    (re.compile(r"\bstab\s*(wound|bing|bed)?\b", re.IGNORECASE), "stab", True),
    (re.compile(r"\bimpale(?:d|ment)?\b", re.IGNORECASE), "impalement", True),

    # Motor vehicle / transport
    (re.compile(r"\bMVC\b"), "mvc", False),
    (re.compile(r"\bMVA\b"), "mva", False),
    (re.compile(r"\bmotor\s+vehicle\s+(?:crash|collision|accident)\b", re.IGNORECASE), "mvc", False),
    (re.compile(r"\bvehicle\s+(?:crash|collision|accident)\b", re.IGNORECASE), "mvc", False),
    (re.compile(r"\bcar\s+(?:crash|accident|wreck)\b", re.IGNORECASE), "mvc", False),
    (re.compile(r"\bhead[\s-]?on\s+collision\b", re.IGNORECASE), "mvc", False),
    (re.compile(r"\brollover\b", re.IGNORECASE), "mvc", False),
    (re.compile(r"\bT[\s-]?bone(?:d)?\b", re.IGNORECASE), "mvc", False),
    (re.compile(r"\bmotorcycle\s+(?:crash|collision|accident)\b", re.IGNORECASE), "mcc", False),
    (re.compile(r"\bMCC\b"), "mcc", False),
    (re.compile(r"\bbicycle\s+(?:crash|collision|accident)\b", re.IGNORECASE), "bicycle", False),
    (re.compile(r"\bbike\s+(?:crash|collision|accident)\b", re.IGNORECASE), "bicycle", False),
    (re.compile(r"\bpedestrian\s+(?:struck|hit|vs)\b", re.IGNORECASE), "pedestrian_struck", False),
    (re.compile(r"\bstruck\s+by\s+(?:a\s+)?(?:vehicle|car|truck|auto)\b", re.IGNORECASE), "pedestrian_struck", False),
    (re.compile(r"\bATV\s+(?:crash|accident|rollover)\b", re.IGNORECASE), "atv", False),
    (re.compile(r"\bATV\b"), "atv", False),

    # Falls — require explicit acute context, exclude history/chronic
    (re.compile(
        r"(?:presents?\s+(?:after|following|with|s/p|status\s+post)\s+(?:a\s+)?(?:ground\s+level\s+)?fall"
        r"|(?:had|experienced|suffered|reported|sustained)\s+(?:a\s+)?(?:ground\s+level\s+)?fall"
        r"|s/p\s+(?:ground\s+level\s+)?fall"
        r"|(?:ground\s+level\s+)?fall\s+(?:today|yesterday|this\s+morning|this\s+evening|this\s+afternoon|at\s+home|from|off|down|on)"
        r"|fell\s+(?:today|yesterday|this\s+morning|this\s+evening|down|off|from|on|at|striking|to\s+the\s+ground)"
        r"|found\s+(?:down|on\s+the\s+(?:floor|ground))\b)",
        re.IGNORECASE,
    ), "fall", False),

    # Crush / industrial
    (re.compile(r"\bcrush(?:ed|ing)?\s*(?:injury|injuries|syndrome)?\b", re.IGNORECASE), "crush", False),
    (re.compile(r"\bauger\b", re.IGNORECASE), "industrial", False),
    (re.compile(r"\bgrain\s+bin\b", re.IGNORECASE), "industrial", False),
    (re.compile(r"\bindustrial\s+(?:accident|injury)\b", re.IGNORECASE), "industrial", False),
    (re.compile(r"\bmachinery\s+(?:accident|injury)\b", re.IGNORECASE), "industrial", False),
    (re.compile(r"\bmining\s+accident\b", re.IGNORECASE), "industrial", False),
    (re.compile(r"\bcoal\s+mining\s+accident\b", re.IGNORECASE), "industrial", False),
    (re.compile(r"\btrapped\s+between\b", re.IGNORECASE), "crush", False),
    (re.compile(r"\bgot\s+(?:caught|trapped)\s+in\b", re.IGNORECASE), "industrial", False),

    # Burns
    (re.compile(r"\bburn(?:s|ed)?\b", re.IGNORECASE), "burn", False),
    (re.compile(r"\bthermal\s+injury\b", re.IGNORECASE), "burn", False),
    (re.compile(r"\bscald(?:s|ed|ing)?\b", re.IGNORECASE), "burn", False),

    # Assault / violence
    (re.compile(r"\bassault(?:ed)?\b", re.IGNORECASE), "assault", False),
    (re.compile(r"\battack(?:ed)?\b", re.IGNORECASE), "assault", False),
    (re.compile(r"\baltercation\b", re.IGNORECASE), "assault", False),
    (re.compile(r"\bbeat(?:en|ing)\b", re.IGNORECASE), "assault", False),

    # Blast
    (re.compile(r"\bblast\s+(?:injury|injuries)\b", re.IGNORECASE), "blast", False),
    (re.compile(r"\bexplosion\b", re.IGNORECASE), "blast", False),

    # Animal-related
    (re.compile(r"\bhorse\s+(?:kick|fall|accident)\b", re.IGNORECASE), "animal", False),

    # Hanging / strangulation
    (re.compile(r"\bhanging\b", re.IGNORECASE), "hanging", False),
    (re.compile(r"\bstrangulation\b", re.IGNORECASE), "strangulation", False),

    # Drowning / submersion
    (re.compile(r"\bdrowning\b", re.IGNORECASE), "drowning", False),
    (re.compile(r"\bsubmersion\b", re.IGNORECASE), "drowning", False),
]

# ── Negative context patterns (suppress false-positive mechanism match) ─
# If these appear near a mechanism match, it may be history/chronic
_HISTORY_EXCLUSION_PATTERNS: List[re.Pattern[str]] = [
    re.compile(r"\b(?:history\s+of|h/o|hx\s+of|previous|prior)\s+(?:\w+\s+){0,3}(?:fall|MVC|MVA|GSW|stab)\b", re.IGNORECASE),
    re.compile(r"\bPMH\s*(?:of|:|\s).*?(?:fall|MVC|MVA|GSW|stab)\b", re.IGNORECASE),
    re.compile(r"\bprevious\s+(?:SDH|subdural)\s+from\s+fall\b", re.IGNORECASE),
]

# ── Assault false-positive suppression ──────────────────────────────
# Medical compound terms where "attack" is NOT violence-related
_MEDICAL_ATTACK_RE = re.compile(
    r"\b(?:heart|cardiac|ischemic|transient\s+ischemic|panic|anxiety|asthma)\s+attack",
    re.IGNORECASE,
)

# "beating" in cardiac context (not violence-related)
_CARDIAC_BEATING_RE = re.compile(
    r"\bheart\s+beat(?:en|ing)\b",
    re.IGNORECASE,
)

# Denial/screening context that negates assault words
_ASSAULT_DENIAL_RE = re.compile(
    r"\b(?:den(?:y|ies|ied)|no\s+(?:history\s+of\s+)?|does\s+not\s+report|negative\s+for)\s*"
    r"(?:\w+\s+){0,2}(?:assault|attack|altercation|beat(?:en|ing))\b",
    re.IGNORECASE,
)

# History context for assault-family words (checked only for assault labels)
_ASSAULT_HISTORY_RE = re.compile(
    r"\b(?:history\s+of|h/o|hx\s+of|previous|prior)\s+(?:\w+\s+){0,3}(?:assault|attack|altercation|beat(?:en|ing))\b",
    re.IGNORECASE,
)

# ── Body region patterns ───────────────────────────────────────────
# Each: (compiled_regex, canonical_label)
# Applied to HPI + Secondary Survey text.

_BODY_REGION_PATTERNS: List[Tuple[re.Pattern[str], str]] = [
    # Head
    (re.compile(r"\b(?:head|skull|cranial|cranium|frontal|temporal|parietal|occipital)\b", re.IGNORECASE), "head"),
    (re.compile(r"\b(?:TBI|traumatic\s+brain\s+injury|intracranial|subdural|epidural|SAH|SDH|EDH)\b", re.IGNORECASE), "head"),
    (re.compile(r"\bforehead\b", re.IGNORECASE), "head"),

    # Face
    (re.compile(r"\b(?:face|facial|mandible|maxilla|orbit(?:al)?|zygoma|nasal|nose|jaw|malar)\b", re.IGNORECASE), "face"),
    (re.compile(r"\b(?:Le\s*Fort|midface)\b", re.IGNORECASE), "face"),

    # Neck
    (re.compile(r"\b(?:neck|cervical)\b", re.IGNORECASE), "neck"),
    (re.compile(r"\bc[\s-]?spine\b", re.IGNORECASE), "neck"),

    # Chest
    (re.compile(r"\b(?:chest|thorax|thoracic|rib|ribs|sternum|sternal|hemothorax|pneumothorax|hemopneumothorax)\b", re.IGNORECASE), "chest"),
    (re.compile(r"\b(?:pulmonary\s+contusion|flail\s+chest|chest\s+wall)\b", re.IGNORECASE), "chest"),

    # Abdomen
    (re.compile(r"\b(?:abdomen|abdominal|intra[\s-]?abdominal)\b", re.IGNORECASE), "abdomen"),
    (re.compile(r"\b(?:spleen|splenic|liver|hepatic|kidney|renal|bowel|mesenteric)\b", re.IGNORECASE), "abdomen"),
    (re.compile(r"\b(?:flank)\b", re.IGNORECASE), "abdomen"),

    # Pelvis
    (re.compile(r"\b(?:pelvis|pelvic)\b", re.IGNORECASE), "pelvis"),
    (re.compile(r"\b(?:acetabul(?:ar|um)|pubic|sacr(?:al|um)|iliac|SI\s+joint)\b", re.IGNORECASE), "pelvis"),

    # Spine
    (re.compile(r"\b(?:spine|spinal|vertebra[le]?)\b", re.IGNORECASE), "spine"),
    (re.compile(r"\b(?:t[\s-]?spine|l[\s-]?spine|thoracolumbar|lumbar|sacral)\b", re.IGNORECASE), "spine"),

    # Extremity
    (re.compile(
        r"\b(?:extremit(?:y|ies)|upper\s+extremit|lower\s+extremit"
        r"|femur|tibia|fibula|humerus|radius|ulna|ankle|wrist|knee|elbow|shoulder"
        r"|hip|thigh|forearm|hand|foot|leg\s+(?:injury|fracture|wound|pain)"
        r"|arm\s+(?:injury|fracture|wound|pain))\b",
        re.IGNORECASE,
    ), "extremity"),
    (re.compile(r"\bRLE\b|\bLLE\b|\bRUE\b|\bLUE\b", re.IGNORECASE), "extremity"),
    (re.compile(r"\b(?:left|right)\s+(?:upper|lower)\s+extremit", re.IGNORECASE), "extremity"),
]

# ── Section boundary patterns ──────────────────────────────────────

RE_HPI_START = re.compile(r"^HPI\s*:", re.IGNORECASE | re.MULTILINE)
RE_HPI_END = re.compile(
    r"^(?:Primary\s+Survey|Secondary\s+Survey|PMH|Past\s+Medical|ROS|Allergies|Medications|Review\s+of\s+Systems)\s*:",
    re.IGNORECASE | re.MULTILINE,
)

RE_SECONDARY_SURVEY_START = re.compile(r"Secondary\s+Survey\s*:", re.IGNORECASE)
RE_SECONDARY_SURVEY_END = re.compile(
    r"^(?:Impression|Assessment|Plan|Disposition|PMH|Past\s+Medical|Medications|Allergies)\s*:",
    re.IGNORECASE | re.MULTILINE,
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


def _extract_section(text: str, start_re: re.Pattern, end_re: re.Pattern) -> Optional[str]:
    """Extract text between start and end patterns, or None if not found."""
    m_start = start_re.search(text)
    if not m_start:
        return None
    rest = text[m_start.end():]
    m_end = end_re.search(rest)
    if m_end:
        return rest[:m_end.start()]
    return rest


def _is_history_context(line: str, match_start: int, match_end: int) -> bool:
    """
    Check whether a mechanism match is in history/chronic context.
    Look at the surrounding text to determine if the match is describing
    a prior/historical event rather than the current acute presentation.
    """
    # Check a window before the match for history exclusion words
    window_start = max(0, match_start - 80)
    preceding = line[window_start:match_end]
    for pat in _HISTORY_EXCLUSION_PATTERNS:
        if pat.search(preceding):
            return True
    return False


def _is_assault_false_positive(
    text: str,
    match: re.Match,  # type: ignore[type-arg]
    label: str,
) -> bool:
    """
    Check whether an assault-family match is a false positive.

    Suppresses:
      - "attack" in medical compound terms (heart attack, panic attack, …)
      - "beating" in cardiac context (heart beating)
      - assault-family words in explicit denial context ("denies assault")
    """
    match_start = match.start()
    match_end = match.end()
    matched_word = text[match_start:match_end].lower()

    # "attack"/"attacked" preceded by a medical modifier → suppress
    if matched_word.startswith("attack"):
        window_start = max(0, match_start - 40)
        preceding = text[window_start:match_end]
        if _MEDICAL_ATTACK_RE.search(preceding):
            return True

    # "beaten"/"beating" preceded by "heart" → suppress
    if matched_word.startswith("beat"):
        window_start = max(0, match_start - 20)
        preceding = text[window_start:match_end]
        if _CARDIAC_BEATING_RE.search(preceding):
            return True

    # Denial / screening context → suppress
    window_start = max(0, match_start - 60)
    preceding = text[window_start:match_end]
    if _ASSAULT_DENIAL_RE.search(preceding):
        return True

    # History context for assault-family words → suppress
    window_start = max(0, match_start - 80)
    preceding = text[window_start:match_end]
    if _ASSAULT_HISTORY_RE.search(preceding):
        return True

    return False


def _extract_mechanisms_from_text(
    hpi_text: str,
    source_type: str,
    source_id: Optional[str],
    ts: Optional[str],
) -> Tuple[List[str], bool, List[Dict[str, Any]], List[str]]:
    """
    Extract mechanism labels from HPI text.

    Returns: (labels, is_penetrating, evidence_entries, notes)
    """
    labels: List[str] = []
    seen_labels: set = set()
    is_penetrating = False
    evidence: List[Dict[str, Any]] = []
    notes: List[str] = []

    for pat, label, penetrating in _MECHANISM_PATTERNS:
        for m in pat.finditer(hpi_text):
            # Check for history context exclusion
            if _is_history_context(hpi_text, m.start(), m.end()):
                notes.append(
                    f"history_context_excluded: '{label}' matched but "
                    f"appears in history/chronic context"
                )
                continue

            # Assault-family false-positive suppression
            if label == "assault" and _is_assault_false_positive(hpi_text, m, label):
                notes.append(
                    f"assault_fp_excluded: '{label}' matched but "
                    f"appears in medical/denial context"
                )
                continue

            if label not in seen_labels:
                labels.append(label)
                seen_labels.add(label)
                if penetrating:
                    is_penetrating = True

                # Build evidence entry for first occurrence of this label
                match_line = hpi_text[max(0, m.start() - 40):m.end() + 40]
                raw_line_id = _make_raw_line_id(source_type, source_id, match_line)
                evidence.append({
                    "raw_line_id": raw_line_id,
                    "source": source_type,
                    "ts": ts,
                    "snippet": _snippet(match_line),
                    "role": "mechanism",
                    "label": label,
                })

    return labels, is_penetrating, evidence, notes


def _extract_body_regions_from_text(
    text: str,
    source_type: str,
    source_id: Optional[str],
    ts: Optional[str],
) -> Tuple[List[str], List[Dict[str, Any]]]:
    """
    Extract body region labels from text (HPI + Secondary Survey).

    Returns: (labels, evidence_entries)
    """
    labels: List[str] = []
    seen_labels: set = set()
    evidence: List[Dict[str, Any]] = []

    for pat, label in _BODY_REGION_PATTERNS:
        for m in pat.finditer(text):
            if label not in seen_labels:
                labels.append(label)
                seen_labels.add(label)

                match_line = text[max(0, m.start() - 40):m.end() + 40]
                raw_line_id = _make_raw_line_id(source_type, source_id, match_line)
                evidence.append({
                    "raw_line_id": raw_line_id,
                    "source": source_type,
                    "ts": ts,
                    "snippet": _snippet(match_line),
                    "role": "body_region",
                    "label": label,
                })

    return labels, evidence


def _make_dna_result(reason: str) -> Dict[str, Any]:
    """Build DATA NOT AVAILABLE stub."""
    return {
        "mechanism_present": _DNA,
        "mechanism_primary": None,
        "mechanism_labels": [],
        "penetrating_mechanism": None,
        "body_region_present": _DNA,
        "body_region_labels": [],
        "source_rule_id": "no_qualifying_source",
        "evidence": [],
        "notes": [reason],
        "warnings": [],
    }


# ── Core extraction ─────────────────────────────────────────────────

def extract_mechanism_region(
    pat_features: Dict[str, Any],
    days_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Deterministic mechanism + body region extraction from timeline items.

    Consumes timeline items (TRAUMA_HP, ED_NOTE, PHYSICIAN_NOTE, CONSULT_NOTE)
    to extract injury mechanism and body region mentions.

    Parameters
    ----------
    pat_features : dict
        The in-progress patient features dict (with "days" key containing
        per-day feature data).
    days_data : dict
        The full patient_days_v1.json structure for raw text access.

    Returns
    -------
    dict
        mechanism_region_v1 contract output.
    """
    evidence: List[Dict[str, Any]] = []
    notes: List[str] = []
    warnings: List[str] = []

    days_map = days_data.get("days") or {}

    # ── Collect qualifying items, sorted by source priority + timestamp ─
    qualifying_items: List[Tuple[int, str, Dict[str, Any]]] = []
    for day_iso in sorted(days_map.keys()):
        for item in days_map[day_iso].get("items") or []:
            item_type = item.get("type", "")
            if item_type in _SOURCE_PRIORITY:
                priority = _SOURCE_PRIORITY.index(item_type)
                dt = item.get("dt", "")
                qualifying_items.append((priority, dt, item))

    # Sort: highest priority source first, then earliest timestamp
    qualifying_items.sort(key=lambda x: (x[0], x[1]))

    if not qualifying_items:
        return _make_dna_result("no TRAUMA_HP, ED_NOTE, PHYSICIAN_NOTE, or CONSULT_NOTE items found")

    # ── Mechanism extraction: use HPI from best available source ────
    mechanism_labels: List[str] = []
    mechanism_penetrating = False
    mechanism_evidence: List[Dict[str, Any]] = []
    mechanism_notes: List[str] = []
    source_rule_id: Optional[str] = None

    for _priority, _dt, item in qualifying_items:
        item_type = item.get("type", "")
        text = (item.get("payload") or {}).get("text", "")
        source_id = item.get("source_id")
        ts = item.get("dt")

        if not text.strip():
            continue

        # Extract HPI section
        hpi_text = _extract_section(text, RE_HPI_START, RE_HPI_END)
        if hpi_text is None:
            # For non-TRAUMA_HP sources, try using the whole text as context
            # but only if it's short enough to be an HPI-like narrative
            if item_type != "TRAUMA_HP":
                # Skip — we only extract mechanism from identifiable HPI sections
                continue
            else:
                notes.append(f"no_hpi_section: {item_type} item has no HPI section")
                continue

        labels, penetrating, m_evidence, m_notes = _extract_mechanisms_from_text(
            hpi_text, item_type, source_id, ts,
        )

        if labels:
            mechanism_labels = labels
            mechanism_penetrating = penetrating
            mechanism_evidence = m_evidence
            mechanism_notes.extend(m_notes)
            source_rule_id = f"{item_type.lower()}_hpi"
            break  # Use first source with mechanism matches
        else:
            mechanism_notes.extend(m_notes)

    # ── Body region extraction: HPI + Secondary Survey from best source ─
    region_labels: List[str] = []
    region_evidence: List[Dict[str, Any]] = []

    for _priority, _dt, item in qualifying_items:
        item_type = item.get("type", "")
        text = (item.get("payload") or {}).get("text", "")
        source_id = item.get("source_id")
        ts = item.get("dt")

        if not text.strip():
            continue

        # Combine HPI + Secondary Survey text for body region extraction
        sections_text = ""

        hpi_text = _extract_section(text, RE_HPI_START, RE_HPI_END)
        if hpi_text:
            sections_text += hpi_text + "\n"

        ss_text = _extract_section(text, RE_SECONDARY_SURVEY_START, RE_SECONDARY_SURVEY_END)
        if ss_text:
            sections_text += ss_text + "\n"

        if not sections_text.strip():
            continue

        r_labels, r_evidence = _extract_body_regions_from_text(
            sections_text, item_type, source_id, ts,
        )

        if r_labels:
            region_labels = r_labels
            region_evidence = r_evidence
            if source_rule_id is None:
                source_rule_id = f"{item_type.lower()}_hpi"
            break  # Use first source with region matches

    # ── Assemble result ─────────────────────────────────────────────
    all_evidence = mechanism_evidence + region_evidence
    all_notes = notes + mechanism_notes

    # Determine mechanism_present
    if not any(item_type in [it[2].get("type") for it in qualifying_items] for item_type in _SOURCE_PRIORITY):
        mechanism_present = _DNA
    elif mechanism_labels:
        mechanism_present = "yes"
    else:
        mechanism_present = "no"

    # Determine body_region_present
    if region_labels:
        body_region_present = "yes"
    elif not qualifying_items:
        body_region_present = _DNA
    else:
        body_region_present = "no"

    # Primary mechanism is the first (highest-priority) label
    mechanism_primary = mechanism_labels[0] if mechanism_labels else None

    # Penetrating: derive from labels
    penetrating_out: Optional[bool] = None
    if mechanism_labels:
        penetrating_out = mechanism_penetrating

    return {
        "mechanism_present": mechanism_present,
        "mechanism_primary": mechanism_primary,
        "mechanism_labels": mechanism_labels,
        "penetrating_mechanism": penetrating_out,
        "body_region_present": body_region_present,
        "body_region_labels": sorted(set(region_labels)),
        "source_rule_id": source_rule_id or "no_qualifying_source",
        "evidence": all_evidence,
        "notes": all_notes,
        "warnings": warnings,
    }
