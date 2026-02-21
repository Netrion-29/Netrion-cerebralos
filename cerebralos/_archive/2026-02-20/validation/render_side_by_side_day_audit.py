#!/usr/bin/env python3
"""
Render a side-by-side day-level audit page (Markdown) for CerebralOS.

Deterministic: pure string matching, no inference.
Fail-closed: exits non-zero if the requested day is not present in the data.

Usage:
    python3 cerebralos/validation/render_side_by_side_day_audit.py \
        --pat George_Kraus --day 2025-12-05

Inputs:
    outputs/audit/<PAT>/RAW.txt
    outputs/timeline/<PAT>/patient_days_v1.json
    outputs/features/<PAT>/patient_features_v1.json

Output:
    outputs/audit/<PAT>/side_by_side_<DAY>.md
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from cerebralos.validation.keyword_rules import NURSING_SCREENS, KEYWORD_ANCHORS

# ── repo layout ─────────────────────────────────────────────────────
_REPO = Path(__file__).resolve().parent.parent.parent

# ── nursing screen keywords (imported from keyword_rules) ───────────
_NURSING_SCREENS = NURSING_SCREENS

# ── keyword anchors for raw-text grep (imported from keyword_rules) ─
_KEYWORD_ANCHORS = KEYWORD_ANCHORS

_MAX_SNIPPET_LINES = 3  # per keyword


# ── helpers ──────────────────────────────────────────────────────────

def _load_json(path: Path) -> Any:
    with open(path, encoding="utf-8", errors="replace") as f:
        return json.load(f)


def _read_lines(path: Path) -> List[str]:
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.readlines()


def _date_patterns(day_iso: str) -> List[re.Pattern]:
    """
    Return compiled patterns matching the given ISO day in common
    chart date formats:  MM/DD/YYYY, M/D/YYYY, MM/DD/YY, M/D/YY,
    and YYYY-MM-DD.
    """
    dt = datetime.strptime(day_iso, "%Y-%m-%d")
    mm = dt.strftime("%m")       # zero-padded
    dd = dt.strftime("%d")
    yyyy = dt.strftime("%Y")
    yy = dt.strftime("%y")
    m = str(dt.month)            # no leading zero
    d = str(dt.day)

    variants: List[str] = list(dict.fromkeys([
        f"{mm}/{dd}/{yyyy}",     # 12/05/2025
        f"{m}/{d}/{yyyy}",       # 12/5/2025
        f"{mm}/{dd}/{yy}",       # 12/05/25
        f"{m}/{d}/{yy}",         # 12/5/25
        day_iso,                 # 2025-12-05
    ]))
    return [re.compile(re.escape(v)) for v in variants]


def _tri_state_label(val: str | None) -> str:
    if val is None:
        return "UNKNOWN"
    v = str(val).upper()
    if v in ("HIT", "YES", "TRUE", "PRESENT"):
        return "HIT"
    if v in ("NO HIT", "NO", "FALSE", "ABSENT", "NONE", "UNKNOWN"):
        return v
    return v  # pass through verbatim


# ── Section 1: Structured Day Summary ───────────────────────────────

def _render_devices(day_features: Dict) -> List[str]:
    """Render devices.canonical block."""
    lines: List[str] = ["### Devices (canonical)", ""]
    devices = day_features.get("devices", {})
    canonical = devices.get("canonical", {})
    if not canonical:
        lines.append("_No device data for this day._")
        lines.append("")
        return lines

    lines.append("| Device | Status |")
    lines.append("|--------|--------|")
    for dev in sorted(canonical):
        lines.append(f"| {dev} | {canonical[dev]} |")
    lines.append("")
    return lines


def _render_services(day_features: Dict) -> List[str]:
    """Render services.tags + notes_by_service counts."""
    lines: List[str] = ["### Services", ""]
    services = day_features.get("services", {})
    tags = services.get("tags", [])
    lines.append(f"**Tags:** {', '.join(sorted(tags)) if tags else '_none_'}")
    lines.append("")

    notes_by_svc = services.get("notes_by_service", {})
    if notes_by_svc:
        lines.append("| Service | Note count |")
        lines.append("|---------|------------|")
        for svc in sorted(notes_by_svc):
            lines.append(f"| {svc} | {len(notes_by_svc[svc])} |")
        lines.append("")
    return lines


def _render_labs_daily(day_features: Dict) -> List[str]:
    """Render top-10 absolute deltas from labs.daily."""
    lines: List[str] = ["### Labs – Top 10 Absolute Deltas", ""]
    labs = day_features.get("labs", {})
    daily = labs.get("daily", {})
    if not daily:
        lines.append("_No lab daily data for this day._")
        lines.append("")
        return lines

    # Sort by absolute delta descending
    ranked: List[Tuple[str, Dict]] = []
    for comp, info in daily.items():
        delta = info.get("delta")
        if delta is not None:
            ranked.append((comp, info))
    ranked.sort(key=lambda x: abs(x[1].get("delta", 0)), reverse=True)

    top = ranked[:10]
    if not top:
        lines.append("_No deltas available._")
        lines.append("")
        return lines

    lines.append("| Component | First | Last | Delta | Delta% | Big? | Abnormal? | N |")
    lines.append("|-----------|-------|------|-------|--------|------|-----------|---|")
    for comp, info in top:
        first = info.get("first", "")
        last = info.get("last", "")
        delta = info.get("delta", "")
        dpct = info.get("delta_pct", "")
        big = "Y" if info.get("big_change") else ""
        abn = "Y" if info.get("abnormal_flag_present") else ""
        n = info.get("n_values", "")
        lines.append(f"| {comp} | {first} | {last} | {delta} | {dpct} | {big} | {abn} | {n} |")
    lines.append("")
    return lines


def _render_nursing_screens(day_items: List[Dict]) -> List[str]:
    """Scan day items for nursing screen keywords → HIT / NO HIT / UNKNOWN."""
    lines: List[str] = ["### Nursing Screens", ""]

    # Combine all text payloads for the day
    all_text = "\n".join(
        (item.get("payload") or {}).get("text", "")
        for item in day_items
    )

    lines.append("| Screen | Result |")
    lines.append("|--------|--------|")
    for screen_name, patterns in _NURSING_SCREENS.items():
        hit = any(p.search(all_text) for p in patterns)
        if not all_text.strip():
            label = "UNKNOWN"
        elif hit:
            label = "HIT"
        else:
            label = "NO HIT"
        lines.append(f"| {screen_name} | {label} |")
    lines.append("")
    return lines


# ── Section 2: Raw Text Snippets ────────────────────────────────────

def _grep_raw_lines(
    raw_lines: List[str],
    date_pats: List[re.Pattern],
) -> List[Tuple[int, str]]:
    """Return (1-based line_no, line_text) for lines matching any date pattern."""
    hits: List[Tuple[int, str]] = []
    for idx, line in enumerate(raw_lines, start=1):
        if any(p.search(line) for p in date_pats):
            hits.append((idx, line))
    return hits


def _keyword_snippets(
    raw_lines: List[str],
    day_line_nos: set[int],
    kw_pat: re.Pattern,
) -> List[Tuple[int, str]]:
    """
    For a given keyword pattern, find matching lines that are within ±5 lines
    of any date-matched line.  Return up to _MAX_SNIPPET_LINES results.
    """
    # Expand day_line_nos to a window
    window: set[int] = set()
    for ln in day_line_nos:
        for offset in range(-5, 6):
            window.add(ln + offset)

    hits: List[Tuple[int, str]] = []
    for idx, line in enumerate(raw_lines, start=1):
        if idx in window and kw_pat.search(line):
            hits.append((idx, line.rstrip("\n")))
            if len(hits) >= _MAX_SNIPPET_LINES:
                break
    return hits


def _render_raw_snippets(
    raw_lines: List[str],
    day_iso: str,
) -> List[str]:
    """Build the Section 2 markdown for raw text snippets."""
    lines: List[str] = []
    date_pats = _date_patterns(day_iso)

    # 1) Date-matched lines
    date_hits = _grep_raw_lines(raw_lines, date_pats)
    day_line_nos = {ln for ln, _ in date_hits}

    lines.append("### Date-matched lines")
    lines.append("")
    if date_hits:
        lines.append(f"_{len(date_hits)} line(s) matching date {day_iso}_")
        lines.append("")
        lines.append("```")
        for ln, text in date_hits[:30]:  # cap preview
            lines.append(f"L{ln}: {text.rstrip()}")
        if len(date_hits) > 30:
            lines.append(f"  ... ({len(date_hits) - 30} more)")
        lines.append("```")
    else:
        lines.append("_No lines matched the target date._")
    lines.append("")

    # 2) Keyword anchors
    lines.append("### Keyword Anchor Snippets")
    lines.append("")

    for kw_label, kw_pat in _KEYWORD_ANCHORS:
        snippets = _keyword_snippets(raw_lines, day_line_nos, kw_pat)
        lines.append(f"**{kw_label}**")
        lines.append("")
        if snippets:
            lines.append("```")
            for ln, text in snippets:
                lines.append(f"L{ln}: {text}")
            lines.append("```")
        else:
            lines.append("_no match near this day_")
        lines.append("")

    return lines


# ── main render ──────────────────────────────────────────────────────

def render(pat: str, day_iso: str) -> str:
    """
    Build the full side-by-side markdown.  Returns the markdown text.
    Raises SystemExit on missing data (fail-closed).
    """
    # ── resolve paths ────────────────────────────────────────────
    raw_path = _REPO / "outputs" / "audit" / pat / "RAW.txt"
    days_path = _REPO / "outputs" / "timeline" / pat / "patient_days_v1.json"
    feat_path = _REPO / "outputs" / "features" / pat / "patient_features_v1.json"

    for label, p in [("RAW.txt", raw_path), ("patient_days_v1.json", days_path),
                     ("patient_features_v1.json", feat_path)]:
        if not p.exists():
            print(f"FAIL: {label} not found → {p}", file=sys.stderr)
            sys.exit(1)

    # ── load ─────────────────────────────────────────────────────
    raw_lines = _read_lines(raw_path)
    days_data = _load_json(days_path)
    feat_data = _load_json(feat_path)

    patient_id = feat_data.get("patient_id", "UNKNOWN")
    warnings_summary = feat_data.get("warnings_summary", {})

    # ── fail-closed: day must exist ──────────────────────────────
    feat_days = feat_data.get("days", {})
    timeline_days = days_data.get("days", {})

    if day_iso not in feat_days and day_iso not in timeline_days:
        print(
            f"FAIL: day {day_iso} not present in features or timeline for {pat}",
            file=sys.stderr,
        )
        sys.exit(1)

    day_features = feat_days.get(day_iso, {})
    day_items = timeline_days.get(day_iso, {}).get("items", [])

    # ── build markdown ───────────────────────────────────────────
    md: List[str] = []

    # Header
    md.append(f"# Side-by-Side Day Audit: {pat}")
    md.append("")
    md.append(f"- **patient_id:** {patient_id}")
    md.append(f"- **day:** {day_iso}")
    ws = ", ".join(f"{k}: {v}" for k, v in sorted(warnings_summary.items())) if warnings_summary else "_none_"
    md.append(f"- **warnings_summary:** {ws}")
    md.append("")

    # ── Section 1 ────────────────────────────────────────────────
    md.append("---")
    md.append("## Section 1 – Structured Day Summary")
    md.append("")

    md.extend(_render_devices(day_features))
    md.extend(_render_services(day_features))
    md.extend(_render_labs_daily(day_features))
    md.extend(_render_nursing_screens(day_items))

    # ── Section 2 ────────────────────────────────────────────────
    md.append("---")
    md.append("## Section 2 – Raw Text Snippets")
    md.append("")
    md.extend(_render_raw_snippets(raw_lines, day_iso))

    return "\n".join(md)


# ── CLI ──────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render side-by-side day audit (markdown).",
    )
    parser.add_argument("--pat", required=True, help="Patient folder name, e.g. George_Kraus")
    parser.add_argument("--day", required=True, help="Calendar day in YYYY-MM-DD format")
    args = parser.parse_args()

    pat: str = args.pat
    day_iso: str = args.day

    # Validate day format
    try:
        datetime.strptime(day_iso, "%Y-%m-%d")
    except ValueError:
        print(f"FAIL: --day must be YYYY-MM-DD, got '{day_iso}'", file=sys.stderr)
        sys.exit(1)

    md_text = render(pat, day_iso)

    # ── write output ─────────────────────────────────────────────
    out_dir = _REPO / "outputs" / "audit" / pat
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"side_by_side_{day_iso}.md"
    out_path.write_text(md_text, encoding="utf-8")
    print(f"OK: {out_path.relative_to(_REPO)}")


if __name__ == "__main__":
    main()
