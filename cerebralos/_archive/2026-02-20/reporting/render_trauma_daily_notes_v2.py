#!/usr/bin/env python3
"""
CerebralOS — Render TRAUMA DAILY NOTES (v2)

Input:  patient_days_v1.json
Output: TRAUMA_DAILY_NOTES_v2.txt

Deterministic:
- Extract clinically relevant lines per bucket via keyword matching
- Dedupe within-day and vs prior-day (carryover suppression)
- Protect daily-critical buckets (Procedures/Imaging/Labs) from prior-day suppression
- Highlight nursing assessment signal (protocol-relevant phrasing)
- No inference: only emits lines present in source text
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple


BUCKETS = [
    "Hemodynamic status",
    "Respiratory status",
    "Neuro status",
    "Procedures performed",
    "Imaging",
    "Labs (significant only)",
    "Consults",
    "Complications / Events",
]

# Buckets that should NOT be suppressed by "same as yesterday"
NO_PRIOR_DEDUPE = {
    "Procedures performed",
    "Imaging",
    "Labs (significant only)",
}

# Note: Keep patterns conservative. Missing data should produce DATA NOT AVAILABLE.
KW = {
    "Hemodynamic status": [
        r"\bBP\b", r"\bMAP\b", r"\bHR\b", r"\bhypoten", r"\bshock\b",
        r"\bpressors?\b", r"\bnorepi\b", r"\blevophed\b", r"\bvasopress",
        r"\bfluid\b", r"\bbolus\b", r"\btransfus", r"\bhemorr",
    ],
    "Respiratory status": [
        r"\bSpO2\b", r"\bsat(uration)?\b", r"\bO2\b", r"\bL\/?min\b",
        r"\bNC\b", r"\bHFNC\b", r"\bBiPAP\b", r"\bCPAP\b",
        r"\bvent\b", r"\bETT\b", r"\bintubat", r"\bwean\b",
    ],
    "Neuro status": [
        r"\bGCS\b", r"\bAOx\b", r"\boriented\b", r"\bconfus", r"\bAMS\b",
        r"\bpupil", r"\bseiz", r"\bweak(ness)?\b", r"\bneuro\b",
        r"\bheadache\b", r"\bstroke\b",
    ],
    "Procedures performed": [
        r"\bprocedure\b", r"\bOR\b", r"\bsurgery\b",
        r"\bcentral line\b", r"\bart(erial)? line\b", r"\bA[- ]line\b",
        r"\bintubat", r"\bchest tube\b", r"\bthora", r"\bbronch",
        r"\bPEG\b", r"\btrach\b",
    ],
    "Imaging": [
        r"\bCT\b", r"\bCTA\b", r"\bMRI\b", r"\bXR\b", r"\bX[- ]ray\b",
        r"\bCXR\b", r"\bultrasound\b", r"\bUS\b",
    ],
    "Labs (significant only)": [
        r"\bWBC\b", r"\bHgb\b", r"\bHCT\b", r"\bPlt\b", r"\bplatelet",
        r"\bINR\b", r"\bPTT\b", r"\bCr\b", r"\bcreatin", r"\bBUN\b",
        r"\blactate\b", r"\bNa\b", r"\bK\b", r"\bCO2\b", r"\bAG\b",
        r"\bAST\b", r"\bALT\b", r"\bbili\b", r"\btroponin\b",
    ],
    "Consults": [
        r"\bconsult\b", r"\bneurosurg\b", r"\bortho\b", r"\btrauma\b",
        r"\bPT\b", r"\bOT\b", r"\bSLP\b", r"\bcardio\b", r"\bnephro\b",
        r"\binfectious disease\b", r"\bID\b",
    ],
    "Complications / Events": [
        r"\bfall\b", r"\brapid response\b", r"\bcode\b",
        r"\bICU\b", r"\btransfer\b", r"\bresint", r"\brestraint\b",
        r"\baspirat", r"\bdelir", r"\bagitat", r"\brefus",
        r"\binfect", r"\bsepsis\b", r"\bfever\b",
        r"\bAKI\b", r"\bARDS\b", r"\bDVT\b", r"\bPE\b",
        r"\bpressure injury\b", r"\bskin\b", r"\bwound\b",
        r"\bbleed\b", r"\bhematoma\b",
    ],
}

# Extra nursing-assessment signal. These lines should tend to land in Events and/or physiologic buckets.
NURSING_SIGNAL = [
    r"\bpain\b", r"\bnausea\b", r"\bvomit", r"\bdiet\b", r"\bNPO\b",
    r"\bI\/O\b", r"\burine\b", r"\bfoley\b", r"\bstool\b",
    r"\bambulat", r"\bmobil", r"\bturn\b", r"\bskin\b", r"\bpressure\b",
    r"\bfall risk\b", r"\bbed alarm\b",
    r"\brestraint\b",
]

RE_MULTISPACE = re.compile(r"\s+")
RE_BULLET_PREFIX = re.compile(r"^\s*[-*•]+\s*")


def _read_json(p: Path) -> Dict[str, Any]:
    return json.loads(p.read_text(encoding="utf-8"))


def _write_text(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _norm_line(s: str) -> str:
    s = s.strip()
    s = RE_BULLET_PREFIX.sub("", s)
    s = RE_MULTISPACE.sub(" ", s)
    return s.strip(" -–—:;,")


def _split_lines(text: str) -> List[str]:
    if not isinstance(text, str) or not text.strip():
        return []
    # Keep original line boundaries; they carry meaning in Epic exports.
    raw_lines = text.splitlines()
    out: List[str] = []
    for rl in raw_lines:
        nl = _norm_line(rl)
        if not nl:
            continue
        # avoid extremely long copied paragraphs
        if len(nl) > 5000:
            nl = nl[:5000] + "…"
        out.append(nl)
    return out


def _match_any(patterns: List[str], line: str) -> bool:
    for pat in patterns:
        if re.search(pat, line, flags=re.IGNORECASE):
            return True
    return False


def _kind_upper(it: Dict[str, Any]) -> str:
    return str(it.get("type") or "").upper()


def _extract_bucket_lines(item: Dict[str, Any], bucket: str) -> List[str]:
    text = ((item.get("payload") or {}).get("text") or "")
    lines = _split_lines(text)
    if not lines:
        return []

    pats = KW[bucket]

    # If it's a nursing note, allow additional “signal” lines to be considered Events.
    kind = _kind_upper(item)
    extra_nursing = (bucket == "Complications / Events") and (kind == "NURSING_NOTE")

    out: List[str] = []
    for ln in lines:
        if _match_any(pats, ln):
            out.append(ln)
        elif extra_nursing and _match_any(NURSING_SIGNAL, ln):
            out.append(ln)

    return out


def _dedupe_preserve_order(lines: List[str]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for ln in lines:
        key = ln.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(ln)
    return out


def _render_day(day_key: str, day_items: List[Dict[str, Any]], prior_bucket_seen: Dict[str, Set[str]]) -> Tuple[List[str], Dict[str, Set[str]]]:
    """
    prior_bucket_seen: bucket -> set(lowercased line) from the previous calendar day (not global).
    Returns rendered lines + current_bucket_seen for this day.
    """
    lines_out: List[str] = []
    current_bucket_seen: Dict[str, Set[str]] = {b: set() for b in BUCKETS}

    lines_out.append(f"===== {day_key} =====")

    # Build bucket content
    bucket_lines: Dict[str, List[str]] = {b: [] for b in BUCKETS}

    for it in day_items:
        dt = it.get("dt") or "TIME DATA NOT AVAILABLE"
        kind = _kind_upper(it) or "UNKNOWN"
        sid = it.get("source_id") or "SOURCE DATA NOT AVAILABLE"

        for b in BUCKETS:
            extracted = _extract_bucket_lines(it, b)
            if not extracted:
                continue

            for ln in extracted:
                # Store line for this bucket with a stable prefix
                bucket_lines[b].append(f"- {dt} [{kind}] ({sid}) {ln}")

    # Dedupe within day, then suppress carryover vs prior day for selected buckets
    for b in BUCKETS:
        bl = _dedupe_preserve_order(bucket_lines[b])

        # prior-day suppression (carryover reduction)
        if b not in NO_PRIOR_DEDUPE:
            prior = prior_bucket_seen.get(b) or set()
            filtered: List[str] = []
            for ln in bl:
                # Suppress if exact same line existed yesterday (case-insensitive)
                key = ln.lower()
                if key in prior:
                    continue
                filtered.append(ln)
            bl = filtered

        # Update seen sets for today (for tomorrow’s suppression)
        for ln in bl:
            current_bucket_seen[b].add(ln.lower())

        bucket_lines[b] = bl

    # Emit buckets
    for b in BUCKETS:
        lines_out.append(f"{b}:")
        if bucket_lines[b]:
            # Cap to keep notes usable; deterministic
            lines_out.extend(bucket_lines[b][:40])
        else:
            lines_out.append("DATA NOT AVAILABLE")
        lines_out.append("")

    return lines_out, current_bucket_seen


def render(days_obj: Dict[str, Any]) -> str:
    meta = days_obj.get("meta") or {}
    days = days_obj.get("days") or {}

    day_keys = sorted([k for k in days.keys() if k != "UNDATED"])
    if "UNDATED" in days:
        day_keys.append("UNDATED")

    out: List[str] = []
    out.append("TRAUMA DAILY NOTES")
    out.append(f"Patient ID: {meta.get('patient_id','DATA NOT AVAILABLE')}")
    out.append(f"Arrival: {meta.get('arrival_datetime','DATA NOT AVAILABLE')}")
    out.append(f"Timezone: {meta.get('timezone','DATA NOT AVAILABLE')}")
    out.append("")

    prior_bucket_seen: Dict[str, Set[str]] = {b: set() for b in BUCKETS}

    prev_real_day = None
    for dk in day_keys:
        items = ((days.get(dk) or {}).get("items") or [])
        if dk == "UNDATED":
            # Don't do prior-day suppression against undated bucket; treat independently.
            day_lines, _ = _render_day(dk, items, {b: set() for b in BUCKETS})
            out.extend(day_lines)
            out.append("")
            continue

        # Only suppress against immediately prior calendar day section (not a running global suppressor)
        if prev_real_day is None:
            prior_for_this_day = {b: set() for b in BUCKETS}
        else:
            prior_for_this_day = prior_bucket_seen

        day_lines, current_seen = _render_day(dk, items, prior_for_this_day)
        out.extend(day_lines)
        out.append("")
        prior_bucket_seen = current_seen
        prev_real_day = dk

    return "\n".join(out).rstrip() + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="Render TRAUMA DAILY NOTES v2 from patient_days_v1.json")
    ap.add_argument("--in", dest="in_path", required=True)
    ap.add_argument("--out", dest="out_path", required=True)
    args = ap.parse_args()

    inp = Path(args.in_path).expanduser().resolve()
    outp = Path(args.out_path).expanduser().resolve()

    obj = _read_json(inp)
    text = render(obj)
    _write_text(outp, text)
    print(f"OK ✅ Wrote daily notes: {outp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
