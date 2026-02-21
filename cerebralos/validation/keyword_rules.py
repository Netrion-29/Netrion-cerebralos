"""
Shared keyword rules for nursing screens, gap scans, and raw-text anchors.

Single source of truth — every validation / reporting script should import
from here instead of defining its own regex lists.

All patterns use word-boundary anchors to prevent substring false-positives.
SAT_TRIAL / SBT_TRIAL require clinical-trial context so that bare "SAT"
(O2 sat, "satting") and bare "SBT" do not produce false positives.
"""

from __future__ import annotations

import re
from typing import Dict, List

# ── helper: compile a list of patterns into one OR-ed pattern ───────
def _any(*patterns: str) -> re.Pattern[str]:
    """Compile multiple raw patterns into a single case-insensitive regex."""
    return re.compile("|".join(f"(?:{p})" for p in patterns), re.I)


# ── SAT / SBT contextual sub-patterns ──────────────────────────────
_RESULT_WORDS = r"pass|fail|done|performed|held|contraindicated|na|n/a"
_NEG_CONTEXT  = r"held|contraindicated|not appropriate|unable"

_SAT_TRIAL_PATTERNS: List[re.Pattern[str]] = [
    re.compile(r"\bspontaneous\s+awakening\s+trial\b", re.I),
    re.compile(r"\bsedation\s+awakening\s+trial\b", re.I),
    re.compile(rf"\bSAT\b\s*[:\-]\s*({_RESULT_WORDS})\b", re.I),
    re.compile(rf"\bSAT\b\s+({_RESULT_WORDS})\b", re.I),
    re.compile(rf"\bSAT\b.*\b({_NEG_CONTEXT})\b", re.I),
]

_SBT_TRIAL_PATTERNS: List[re.Pattern[str]] = [
    re.compile(r"\bspontaneous\s+breathing\s+trial\b", re.I),
    re.compile(rf"\bSBT\b\s*[:\-]\s*({_RESULT_WORDS})\b", re.I),
    re.compile(rf"\bSBT\b\s+({_RESULT_WORDS})\b", re.I),
    re.compile(rf"\bSBT\b.*\b({_NEG_CONTEXT})\b", re.I),
]

# ── Nursing-screen patterns ─────────────────────────────────────────
# Keys are display labels; values are lists of compiled patterns.
# A screen is considered a HIT if *any* pattern in its list matches.

NURSING_SCREENS: Dict[str, List[re.Pattern[str]]] = {
    "CAM-ICU": [
        re.compile(r"\bCAM-?ICU\b", re.I),
    ],
    "Delirium": [
        re.compile(r"\bdelirium\b", re.I),
    ],
    "Braden": [
        re.compile(r"\bBraden\b", re.I),
    ],
    "Fall risk": [
        re.compile(r"\bfall\s+risk\b", re.I),
        re.compile(r"\bmorse\s+fall\b", re.I),
    ],
    "Restraints": [
        re.compile(r"\brestraint(s)?\b", re.I),
    ],
    "SBT_TRIAL": _SBT_TRIAL_PATTERNS,
    "SAT_TRIAL": _SAT_TRIAL_PATTERNS,
}

# ── Keyword gap-scan targets ────────────────────────────────────────
# Each entry is (display_label, compiled_pattern).
# Used by build_audit_pack for the raw-vs-structured gap scan and by
# render_side_by_side_day_audit for raw-text keyword anchors.
#
# SAT_TRIAL / SBT_TRIAL use a single OR-ed pattern that covers all
# contextual sub-patterns so findall() returns correct hit counts.

GAP_KEYWORDS: List[tuple[str, re.Pattern[str]]] = [
    ("CAM-ICU",     re.compile(r"\bCAM-?ICU\b",                          re.I)),
    ("delirium",    re.compile(r"\bdelirium\b",                           re.I)),
    ("restraint",   re.compile(r"\brestraint(s)?\b",                      re.I)),
    ("Braden",      re.compile(r"\bBraden\b",                             re.I)),
    ("fall risk",   re.compile(r"\bfall\s+risk\b",                        re.I)),
    ("SBT_TRIAL",   _any(
        r"\bspontaneous\s+breathing\s+trial\b",
        rf"\bSBT\b\s*[:\-]\s*({_RESULT_WORDS})\b",
        rf"\bSBT\b\s+({_RESULT_WORDS})\b",
        rf"\bSBT\b.*\b({_NEG_CONTEXT})\b",
    )),
    ("SAT_TRIAL",   _any(
        r"\bspontaneous\s+awakening\s+trial\b",
        r"\bsedation\s+awakening\s+trial\b",
        rf"\bSAT\b\s*[:\-]\s*({_RESULT_WORDS})\b",
        rf"\bSAT\b\s+({_RESULT_WORDS})\b",
        rf"\bSAT\b.*\b({_NEG_CONTEXT})\b",
    )),
    ("foley",       re.compile(r"\bfoley\b",                              re.I)),
    ("PICC",        re.compile(r"\bPICC\b",                               re.I)),
    ("CVC",         re.compile(r"\bCVC\b",                                re.I)),
]

# Convenience: flat list of (label, pattern) for raw-text snippet anchors.
# Same order as GAP_KEYWORDS — consumers may iterate directly.
KEYWORD_ANCHORS = GAP_KEYWORDS
