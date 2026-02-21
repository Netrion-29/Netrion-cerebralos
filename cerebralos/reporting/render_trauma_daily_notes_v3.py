#!/usr/bin/env python3
"""
CerebralOS — PI Daily Notes Renderer (v3)

Goal:
- PI-focused daily clinical summary per calendar day
- Deterministic, no inference
- Strong noise filtering (MAR/ADS boilerplate, table headers, procedure log noise)
- Type-aware routing (RADIOLOGY -> Imaging, etc.)
- Imaging: Impression-first summarization + dedupe; structural validation
  * Only items with type == RADIOLOGY feed the Imaging section.
  * Narrative imaging refs in physician notes are NEVER routed to Imaging.
- Block-level cross-day carryover suppression via SHA-256 content hashing
- Per-day text hash deduplication for PHYSICIAN_NOTE / TRAUMA_HP
- Surface nursing assessment signals for protocol triggers

Input:  outputs/timeline/<PATIENT>/patient_days_v1.json
Output: outputs/reporting/<PATIENT>/TRAUMA_DAILY_NOTES_v3.txt
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


# ----------------------------
# Noise filters (hard excludes)
# ----------------------------
EXCLUDE_LINE_PATTERNS = [
    r"\bADS Dispense\b",
    r"\bOMNICELL\b",
    r"\bRoutine,\s*EVERY\b",
    r"\bProcedure Documentation Timeline\b",
    r"\bLink to Procedure Log\b",
    r"^\s*Procedure Log\s*$",
    r"^\s*Date and Time\b",  # vitals table headers
    r"^\s*Ordering Quantity\b",
    r"^\s*Panel Detail\b",
    r"^\s*Or Linked Group Details\b",
    r"^\s*Notes to Pharmacy\b",
    r"^\s*Note to Pharmacy\b",
    r"\bWorkstation:\b",
    # Procedure boilerplate (Problem E)
    r"^\s*Procedure Orders\s*$",
    r"\bExpected length of stay\b",
    r"^\s*All Administrations of\b",
]
EXCLUDE_LINE_RE = [re.compile(p, flags=re.IGNORECASE) for p in EXCLUDE_LINE_PATTERNS]


def is_noise_line(line: str) -> bool:
    if not line:
        return True
    # super short lines are often headers/fragments
    if len(line.strip()) <= 2:
        return True
    for rx in EXCLUDE_LINE_RE:
        if rx.search(line):
            return True
    return False


# ----------------------------
# Helpers
# ----------------------------
RE_MULTISPACE = re.compile(r"\s+")
RE_BULLET_PREFIX = re.compile(r"^\s*[-*•]+\s*")
RE_IMPRESSION = re.compile(r"^\s*IMPRESSION\s*:?", re.IGNORECASE)
RE_FINDINGS = re.compile(r"^\s*FINDINGS\s*:?", re.IGNORECASE)
RE_TECHNIQUE = re.compile(r"^\s*TECHNIQUE\s*:?", re.IGNORECASE)
RE_ADDENDUM = re.compile(r"^\s*ADDENDUM\s*:?", re.IGNORECASE)

# Imaging modality keywords (Problem A)
RE_MODALITY = re.compile(
    r"\bCT\b|\bCTA\b|\bMRI\b|\bMRA\b|\bXR\b|\bX[- ]?ray\b|\bCXR\b"
    r"|\bUltrasound\b|\bUS\b|\bfluoroscop\b|\bDXA\b|\bPET\b|\bNuc(?:lear)?\b",
    re.IGNORECASE,
)
# Radiology-report structural markers
RE_RAD_STRUCTURE = re.compile(
    r"^\s*(IMPRESSION|FINDINGS|TECHNIQUE|COMPARISON|INDICATION|CLINICAL)\s*:?",
    re.IGNORECASE,
)

# Physician-narrative impression detector (Problem A)
RE_NARRATIVE_IMPRESSION = re.compile(
    r"^\s*IMPRESSION\s*:?\s*(Patient|This|The patient|He|She|\d{1,3}\s*(y/?o|year))",
    re.IGNORECASE,
)

NURSING_SIGNAL = [
    r"\brestraint\b",
    r"\bsitter\b",
    r"\bfall risk\b|\bfall\b|\bfell\b",
    r"\bbed alarm\b",
    r"\baspirat",
    r"\bO2\b|\bSpO2\b|\bsat(uration)?\b|\bNC\b|\bHFNC\b|\bBiPAP\b|\bCPAP\b|\bvent(ilat)?\b",
    r"\bneuro\b|\bGCS\b|\bpupil\b|\bconfus\b|\bAMS\b|\bdelir|\bagitat",
    r"\bskin\b|\bpressure\b|\bwound\b|\bbreakdown\b|\bstage\s*[IViv1-4]",
    r"\bpain\b|\bpain\s*scale\b",
    r"\bnausea\b|\bvomit",
    r"\bfoley\b|\burine\b|\bI\/?O\b|\boutput\b|\bintake\b",
    r"\bambulat|\bmobil|\bturn\b|\bOOB\b|\bweight\s*bear",
    r"\boriented\b|\borientation\b|\bA&O\b|\balert\b",
    r"\bdrain(age)?\b|\bJP\b|\bHemovac\b",
    r"\bcough\b|\bbreath\b|\bdyspnea\b|\bwheezing\b",
    r"\btemp(erature)?\b|\bfever\b|\bfebrile\b|\bafebrile\b",
    r"\bdiet\b|\bNPO\b|\bswallow\b",
    r"\bglucose\b|\bfinger\s*stick\b|\bsliding\s*scale\b",
    r"\bIV\s*site\b|\bPIV\b|\binfiltrat",
    r"\bsleep\b|\brest\b|\binsomnia\b",
]
NURSING_RE = [re.compile(p, re.IGNORECASE) for p in NURSING_SIGNAL]

LAB_SIGNAL = [
    r"\bWBC\b", r"\bHgb\b", r"\bHCT\b", r"\bPlt\b|\bplatelet",
    r"\bINR\b|\bPTT\b",
    r"\bCr\b|\bcreatin|\bBUN\b",
    r"\blactate\b",
    r"\bNa\b|\bK\b|\bCO2\b",
    r"\btroponin\b",
]
LAB_RE = [re.compile(p, re.IGNORECASE) for p in LAB_SIGNAL]

# Procedure signal (Problem E — real interventions only)
RE_REAL_PROCEDURE = re.compile(
    r"\bintubat|\bextubat|\bcentral line\b|\bart(erial)?\s*line\b"
    r"|\bchest tube\b|\bbolus\b|\btransfus|\bEEG\b|\bOR\b"
    r"|\bthoracotomy\b|\bcricoth|\btrach(eostomy)?\b|\bICP\b"
    r"|\bcraniotomy\b|\bcraniectomy\b|\bLAP\b|\blaparotomy\b"
    r"|\bangio\b|\bemboliz|\bsplint|\bfixat|\bORIF\b"
    r"|\bpacked\s*red\b|\bFFP\b|\bcryo\b|\bplasma\b|\bMTP\b",
    re.IGNORECASE,
)

# Procedure boilerplate that should NOT count as a real procedure (Problem E)
RE_PROCEDURE_BOILERPLATE = re.compile(
    r"\bProcedure Orders\b|\bExpected length of stay\b"
    r"|\bAll Administrations of\b|\bProcedure Documentation\b"
    r"|\bLink to Procedure\b|\bProcedure Log\b"
    r"|\bProcedure Consent\b|\bpatient was consented\b",
    re.IGNORECASE,
)


def norm_line(s: str) -> str:
    s = (s or "").strip()
    s = RE_BULLET_PREFIX.sub("", s)
    s = RE_MULTISPACE.sub(" ", s)
    return s.strip(" -\u2013\u2014:;,")

def split_lines(text: str) -> List[str]:
    out: List[str] = []
    for raw in (text or "").splitlines():
        ln = norm_line(raw)
        if not ln:
            continue
        if is_noise_line(ln):
            continue
        out.append(ln)
    return out

def kind_upper(it: Dict[str, Any]) -> str:
    return str(it.get("type") or "").upper()

def dt_str(it: Dict[str, Any]) -> str:
    return it.get("dt") or "TIME DATA NOT AVAILABLE"

def sid_str(it: Dict[str, Any]) -> str:
    return str(it.get("source_id") or "SOURCE DATA NOT AVAILABLE")


# ----------------------------
# Block-level content hashing
# ----------------------------

def _block_hash(text: str) -> str:
    """SHA-256 of whitespace-normalised, lowercased full block text."""
    norm = re.sub(r"\s+", " ", (text or "").strip().lower())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def _line_hash(line: str) -> str:
    """SHA-256 of a single normalised line for per-day dedup."""
    return hashlib.sha256(line.strip().lower().encode("utf-8")).hexdigest()


_PREFIX_LEN = 200  # chars used for prefix-based carryover on long lines

def _line_prefix(line: str) -> str:
    """First _PREFIX_LEN chars of normalised line.

    Long narrative lines (Hospital Course, HPI) grow each day as physicians
    append new information.  Exact-match carryover misses them.  Prefix
    matching catches the repeated stem so only genuinely new content passes.
    Returns empty string for short lines (those use exact matching instead).
    """
    norm = line.strip().lower()
    if len(norm) <= _PREFIX_LEN:
        return ""  # handled by exact match
    return norm[:_PREFIX_LEN]


# ----------------------------
# Imaging validation (Problem A)
# ----------------------------

def _has_radiology_structure(lines: List[str]) -> bool:
    """
    Return True only if the text block looks like a genuine radiology report:
    - Contains at least one imaging modality keyword, AND
    - Contains at least one structural marker (IMPRESSION, FINDINGS, TECHNIQUE, etc.)
    """
    has_modality = False
    has_structure = False
    for ln in lines:
        if RE_MODALITY.search(ln):
            has_modality = True
        if RE_RAD_STRUCTURE.match(ln):
            has_structure = True
        if has_modality and has_structure:
            return True
    return has_modality and has_structure


def _is_narrative_impression(ln: str) -> bool:
    """Detect physician narrative disguised as IMPRESSION (long HPI-style)."""
    if RE_NARRATIVE_IMPRESSION.match(ln):
        return True
    # Also reject very long impression lines (>200 chars) — radiology
    # impressions are typically terse
    if RE_IMPRESSION.match(ln) and len(ln) > 200:
        return True
    return False


# ----------------------------
# Imaging summarization (Problem B)
# ----------------------------

def extract_imaging_snippets(lines: List[str]) -> List[str]:
    """
    Deterministic imaging extraction:
    - Skip TECHNIQUE paragraphs entirely
    - Prefer short IMPRESSION blocks (radiology-authored)
    - If impression missing, include concise finding lines
    - Dedupe lines; collapse addenda
    """
    if not lines:
        return []

    # --- Phase 0: strip TECHNIQUE blocks ---
    filtered: List[str] = []
    in_technique = False
    for ln in lines:
        if RE_TECHNIQUE.match(ln):
            in_technique = True
            continue
        # A new section header ends the technique block
        if in_technique and RE_RAD_STRUCTURE.match(ln):
            in_technique = False
        if in_technique:
            continue
        filtered.append(ln)

    # --- Phase 1: look for IMPRESSION ---
    out: List[str] = []
    for i, ln in enumerate(filtered):
        if RE_IMPRESSION.match(ln):
            # Reject physician-narrative impressions
            if _is_narrative_impression(ln):
                continue
            out.append(ln)
            for j in range(i + 1, min(i + 8, len(filtered))):
                nxt = filtered[j]
                # Stop if we hit another section header or addendum
                if RE_RAD_STRUCTURE.match(nxt) or RE_ADDENDUM.match(nxt):
                    break
                # Skip excessively long lines (likely pasted narrative)
                if len(nxt) > 250:
                    continue
                out.append(nxt)
            break  # use only the first valid IMPRESSION block

    # --- Phase 2: fallback to concise finding lines ---
    if not out:
        for ln in filtered:
            if len(ln) > 200:
                continue  # skip long narrative
            if re.search(
                r"\bno acute\b|\bfracture\b|\bhemorrhage\b|\bsubdural\b"
                r"|\bmidline shift\b|\bconcerning for\b|\bpneumothorax\b"
                r"|\beffusion\b|\bopacity\b|\bcontusion\b|\bedema\b",
                ln,
                re.IGNORECASE,
            ):
                out.append(ln)

    # --- Phase 3: dedupe, preserve order ---
    seen: Set[str] = set()
    deduped: List[str] = []
    for ln in out:
        k = ln.lower()
        if k in seen:
            continue
        seen.add(k)
        deduped.append(ln)
    return deduped


# ----------------------------
# Day rendering
# ----------------------------

def render(days_obj: Dict[str, Any]) -> str:
    meta = days_obj.get("meta") or {}
    days = days_obj.get("days") or {}

    day_keys = sorted([k for k in days.keys() if k != "UNDATED"])
    if "UNDATED" in days:
        day_keys.append("UNDATED")

    out: List[str] = []
    out.append("PI DAILY NOTES (v3)")
    out.append(f"Patient ID: {meta.get('patient_id','DATA NOT AVAILABLE')}")
    out.append(f"Arrival: {meta.get('arrival_datetime','DATA NOT AVAILABLE')}")
    out.append(f"Timezone: {meta.get('timezone','DATA NOT AVAILABLE')}")
    out.append("")

    # -- Cross-day suppression state ----------------------------------------
    # Block-level: SHA-256 hashes of full item text seen on any prior day.
    # If the same block reappears on a later day it is suppressed entirely
    # (covers Hospital Course, HPI, Admission Summary, etc.).
    prior_block_hashes: Set[str] = set()
    # Line-level content: raw text (no metadata prefix) from generic-routed
    # items on all prior days.  Catches Hospital Course lines that live inside
    # blocks whose overall hash changed (physician appends new text each day).
    prior_generic_content: Set[str] = set()
    # Prefix-level: first _PREFIX_LEN chars of long narrative lines from prior
    # days.  Catches Hospital Course lines whose tail grows each day.
    prior_generic_prefixes: Set[str] = set()
    # Line-level: rendered lines seen on the prior day (narrative + nursing).
    prior_event_lines: Set[str] = set()
    prior_nursing_lines: Set[str] = set()

    for dk in day_keys:
        items = ((days.get(dk) or {}).get("items") or [])
        out.append(f"===== {dk} =====")

        # Buckets (flexible headings)
        key_events: List[str] = []
        procedures: List[str] = []
        imaging: List[str] = []
        labs: List[str] = []
        nursing: List[str] = []
        consults: List[str] = []
        disposition: List[str] = []

        # Per-day within-bucket dedup (lowercased line text)
        seen_img: Set[str] = set()
        seen_proc: Set[str] = set()
        seen_lab: Set[str] = set()
        seen_consult: Set[str] = set()
        seen_disp: Set[str] = set()

        day_event_lines: Set[str] = set()
        day_nursing_lines: Set[str] = set()

        # Block hashes seen this day (updated to prior_block_hashes after the day)
        day_block_hashes: Set[str] = set()

        # Per-day block-level dedup for PHYSICIAN_NOTE / TRAUMA_HP -- prevents
        # identical blocks emitted by different source_ids on the same day.
        day_physician_block_hashes: Set[str] = set()

        # Per-day line-level text hash dedup for PHYSICIAN_NOTE / TRAUMA_HP
        day_note_line_hashes: Set[str] = set()

        # Collect raw line content from generic items this day (for cross-day)
        day_generic_content: Set[str] = set()
        day_generic_prefixes: Set[str] = set()

        # Cross-bucket dedup: prevents the same line appearing in both
        # key_events and procedures from the same generic item.
        day_emitted_lines: Set[str] = set()

        for it in items:
            kind = kind_upper(it)
            dt = dt_str(it)
            sid = sid_str(it)
            raw_text = (it.get("payload") or {}).get("text") or ""
            lines = split_lines(raw_text)
            blk_hash = _block_hash(raw_text)

            # Record every block hash for cross-day tracking
            day_block_hashes.add(blk_hash)

            # -- Type-aware routing ----------------------------------------

            # RADIOLOGY -- strict: ONLY RADIOLOGY items feed the Imaging bucket.
            # Narrative imaging references inside physician notes never reach
            # here and therefore never appear in the Imaging section.
            if kind == "RADIOLOGY":
                if _has_radiology_structure(lines):
                    snips = extract_imaging_snippets(lines)
                    for ln in snips:
                        k = ln.lower()
                        if k in seen_img:
                            continue
                        seen_img.add(k)
                        imaging.append(f"- {dt} [{kind}] ({sid}) {ln}")
                # RADIOLOGY items ALWAYS stop here -- never fall through to
                # generic routing regardless of structure validation result.
                continue

            if kind in ("LAB", "LAB_RESULT"):
                for ln in lines:
                    if any(rx.search(ln) for rx in LAB_RE):
                        k = ln.lower()
                        if k in seen_lab:
                            continue
                        seen_lab.add(k)
                        labs.append(f"- {dt} [{kind}] ({sid}) {ln}")
                continue

            if kind == "CONSULT_NOTE":
                for ln in lines:
                    if re.search(
                        r"\bconsult\b|\breason for consult\b|\bfollow up\b"
                        r"|\bneuro\b|\bortho\b|\btrauma\b",
                        ln,
                        re.IGNORECASE,
                    ):
                        k = ln.lower()
                        if k in seen_consult:
                            continue
                        seen_consult.add(k)
                        consults.append(f"- {dt} [{kind}] ({sid}) {ln}")
                continue

            if kind == "DISCHARGE":
                for ln in lines:
                    if re.search(
                        r"\bdischarg|\bhome\b|\bSNF\b|\breturn\b|\btransfer\b|\bdisposition\b",
                        ln,
                        re.IGNORECASE,
                    ):
                        k = ln.lower()
                        if k in seen_disp:
                            continue
                        seen_disp.add(k)
                        disposition.append(f"- {dt} [{kind}] ({sid}) {ln}")
                continue

            # MAR: only clinically relevant nursing/protocol items
            if kind == "MAR":
                for ln in lines:
                    if re.search(
                        r"\bhold for\b|\bSBP\b|\bBP\b|\bHR\b|\bplatelets\b|\bcontact\b",
                        ln,
                        re.IGNORECASE,
                    ):
                        k = ln.lower()
                        if k in day_event_lines:
                            continue
                        day_event_lines.add(k)
                        key_events.append(f"- {dt} [{kind}] ({sid}) {ln}")
                continue

            # Nursing note: expanded protocol signals (Problem C)
            if kind == "NURSING_NOTE":
                for ln in lines:
                    if any(rx.search(ln) for rx in NURSING_RE):
                        k = ln.lower()
                        if k in day_nursing_lines:
                            continue
                        day_nursing_lines.add(k)
                        nursing.append(f"- {dt} [{kind}] ({sid}) {ln}")
                continue

            # -- Generic types (ED_NOTE, PHYSICIAN_NOTE, TRAUMA_HP, PROGRESS_NOTE, etc.) --

            # 1) Block-level carryover suppression: if the FULL text of this
            #    item already appeared on any prior day, skip it entirely.
            #    This eliminates repeated Hospital Course / HPI / Admission
            #    Summary blocks that are copy-pasted across days.
            if blk_hash in prior_block_hashes:
                continue

            # 2) Per-day block dedup for PHYSICIAN_NOTE / TRAUMA_HP: if the
            #    same full text appeared from a different source_id on the
            #    SAME day, skip the duplicate block.
            is_physician_or_hp = kind in ("PHYSICIAN_NOTE", "TRAUMA_HP")
            if is_physician_or_hp:
                if blk_hash in day_physician_block_hashes:
                    continue
                day_physician_block_hashes.add(blk_hash)

            # Collect every line from generic items for cross-day tracking
            for ln in lines:
                norm_low = ln.strip().lower()
                day_generic_content.add(norm_low)
                pfx = _line_prefix(ln)
                if pfx:
                    day_generic_prefixes.add(pfx)

            def _is_carryover(line: str) -> bool:
                """True if *line* is repeated content from a prior day."""
                low = line.strip().lower()
                if low in prior_generic_content:
                    return True
                pfx = _line_prefix(line)
                if pfx and pfx in prior_generic_prefixes:
                    return True
                return False

            # Procedures/interventions -- real only, exclude boilerplate (Problem E)
            for ln in lines:
                if RE_PROCEDURE_BOILERPLATE.search(ln):
                    continue
                if RE_REAL_PROCEDURE.search(ln):
                    k = ln.lower()
                    if k in seen_proc:
                        continue
                    if _is_carryover(ln):
                        continue
                    # Cross-bucket dedup
                    if k in day_emitted_lines:
                        continue
                    seen_proc.add(k)
                    day_emitted_lines.add(k)
                    procedures.append(f"- {dt} [{kind}] ({sid}) {ln}")

            # Key events & changes (delta-focused)
            for ln in lines:
                if re.search(
                    r"\bseizure\b|\bfracture\b|\bhemorrhage\b|\bno acute\b"
                    r"|\bGCS\b|\bconfus\b|\bbaseline\b|\btransfer\b|\badmit\b",
                    ln,
                    re.IGNORECASE,
                ):
                    k = ln.lower()
                    if k in day_event_lines:
                        continue
                    if _is_carryover(ln):
                        continue
                    # Cross-bucket dedup
                    if k in day_emitted_lines:
                        continue
                    # 3) Per-day line hash dedup for PHYSICIAN_NOTE / TRAUMA_HP:
                    #    suppress the same line text even when it arrives from
                    #    items whose full blocks differ slightly.
                    if is_physician_or_hp:
                        lh = _line_hash(ln)
                        if lh in day_note_line_hashes:
                            continue
                        day_note_line_hashes.add(lh)
                    day_event_lines.add(k)
                    day_emitted_lines.add(k)
                    key_events.append(f"- {dt} [{kind}] ({sid}) {ln}")

        # -- Post-processing filters ---------------------------------------

        # Prior-day line-level suppression for narrative + nursing
        key_events_filtered = [
            ln for ln in key_events
            if ln.lower() not in prior_event_lines
        ]
        nursing_filtered = [
            ln for ln in nursing
            if ln.lower() not in prior_nursing_lines
        ]

        # Update priors (only for real dated days; don't use UNDATED as baseline)
        if dk != "UNDATED":
            prior_event_lines = set(ln.lower() for ln in key_events)
            prior_nursing_lines = set(ln.lower() for ln in nursing)
            # Accumulate block hashes across all prior days so that a block
            # first seen on Day 1 stays suppressed on Day 3+ even if Day 2
            # no longer contains it.
            prior_block_hashes |= day_block_hashes
            # Accumulate line-level content for cross-day carryover suppression
            prior_generic_content |= day_generic_content
            prior_generic_prefixes |= day_generic_prefixes

        def emit_section(title: str, lines: List[str]) -> None:
            out.append(f"{title}:")
            if lines:
                out.extend(lines[:60])
            else:
                out.append("DATA NOT AVAILABLE")
            out.append("")

        emit_section("Key events & changes", key_events_filtered)
        emit_section("Procedures & interventions", procedures)
        emit_section("Imaging (impression-first)", imaging)
        emit_section("Labs (signal only)", labs)
        emit_section("Nursing / protocol signals", nursing_filtered)
        emit_section("Consults", consults)
        emit_section("Disposition / transfers", disposition)

    return "\n".join(out).rstrip() + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="Render PI Daily Notes v3 from patient_days_v1.json")
    ap.add_argument("--in", dest="in_path", required=True)
    ap.add_argument("--out", dest="out_path", required=True)
    args = ap.parse_args()

    inp = Path(args.in_path).expanduser().resolve()
    outp = Path(args.out_path).expanduser().resolve()
    obj = json.loads(inp.read_text(encoding="utf-8"))
    text = render(obj)
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(text, encoding="utf-8")
    print(f"OK ✅ Wrote daily notes: {outp}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
