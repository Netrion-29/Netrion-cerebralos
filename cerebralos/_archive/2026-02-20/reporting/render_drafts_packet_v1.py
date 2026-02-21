#!/usr/bin/env python3
"""
Drafts-friendly daily packet renderer for CerebralOS.

Produces a deterministic Markdown summary per calendar day covering
devices (canonical tri-state), services, big lab changes, and
nursing screen keyword hits.

Usage:
    python3 cerebralos/reporting/render_drafts_packet_v1.py --pat Timothy_Cowan

Fail-closed: exits non-zero if features or timeline JSON is missing.
No inference; pure structured data + keyword matching.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

from cerebralos.validation.keyword_rules import NURSING_SCREENS

# ── repo layout ─────────────────────────────────────────────────────
_REPO = Path(__file__).resolve().parent.parent.parent

# ── nursing-screen keywords (imported from keyword_rules) ────────────
_NURSING_SCREENS = NURSING_SCREENS

# Canonical device display order
_DEVICE_ORDER = ["foley", "central_line", "ett_vent", "chest_tube", "drain"]


# ── helpers ──────────────────────────────────────────────────────────

def _load_json(path: Path) -> Any:
    with open(path, encoding="utf-8", errors="replace") as f:
        return json.load(f)


def _preview(text: str, maxlen: int = 120) -> str:
    return text.replace("\n", " ").strip()[:maxlen]


def _screen_day(items: List[Dict[str, Any]]) -> Dict[str, str]:
    """Evaluate nursing screen keywords for a day's timeline items.

    Returns {screen_name: "HIT"|"NO HIT"|"UNKNOWN"}.
    UNKNOWN if no nursing-ish notes exist for the day.
    """
    nursing_texts: List[str] = []
    all_texts: List[str] = []
    for item in items:
        text = (item.get("payload") or {}).get("text", "")
        itype = item.get("type", "")
        all_texts.append(text)
        if itype in ("NURSING_NOTE", "MAR"):
            nursing_texts.append(text)

    has_nursing = len(nursing_texts) > 0
    combined_all = "\n".join(all_texts)

    result: Dict[str, str] = {}
    for screen_name, patterns in _NURSING_SCREENS.items():
        if not has_nursing:
            result[screen_name] = "UNKNOWN"
        else:
            hit = any(p.search(combined_all) for p in patterns)
            result[screen_name] = "HIT" if hit else "NO HIT"
    return result


# ── renderer ─────────────────────────────────────────────────────────

def render_packet(
    pat: str,
    features: Dict[str, Any],
    days_data: Dict[str, Any],
) -> str:
    """Build the Markdown daily packet string."""
    lines: List[str] = []

    patient_id = features.get("patient_id", "unknown")
    feat_days = features.get("days", {})
    timeline_days = days_data.get("days", {})
    warnings_summary = features.get("warnings_summary", {})

    day_keys = sorted(feat_days.keys())
    dated_keys = [k for k in day_keys if k != "__UNDATED__"]

    # ── header ──────────────────────────────────────────────────
    lines.append(f"# {pat} — Daily Packet")
    lines.append("")
    lines.append(f"**Patient ID:** {patient_id}  ")
    if dated_keys:
        lines.append(f"**Date range:** {dated_keys[0]} … {dated_keys[-1]}  ")
    else:
        lines.append("**Date range:** n/a  ")
    undated_suffix = ", +\\_\\_UNDATED\\_\\_" if "__UNDATED__" in feat_days else ""
    lines.append(f"**Days:** {len(day_keys)} ({len(dated_keys)} dated{undated_suffix})")
    lines.append("")

    # ── warnings summary ────────────────────────────────────────
    lines.append("**Warnings:**")
    if warnings_summary:
        for k in sorted(warnings_summary):
            lines.append(f"- {k}: {warnings_summary[k]}")
    else:
        lines.append("- (none)")
    lines.append("")

    # ── per-day sections ────────────────────────────────────────
    for day_iso in day_keys:
        feat_day = feat_days[day_iso]
        timeline_items = (timeline_days.get(day_iso) or {}).get("items", [])

        lines.append(f"## {day_iso}")
        lines.append("")

        # ── vitals summary ──────────────────────────────────────
        lines.append("### Vitals Summary")
        vit = feat_day.get("vitals", {})
        _VIT_DISPLAY = [
            ("Temp (°F)", "temp_f"),
            ("HR", "hr"),
            ("RR", "rr"),
            ("SpO2 (%)", "spo2"),
            ("SBP", "sbp"),
            ("DBP", "dbp"),
            ("MAP", "map"),
        ]
        vit_parts: List[str] = []
        for label, mk in _VIT_DISPLAY:
            info = vit.get(mk, {})
            last_val = info.get("last")
            if last_val is not None:
                mn = info.get("min")
                mx = info.get("max")
                if mn is not None and mx is not None and mn != mx:
                    vit_parts.append(f"**{label}:** {last_val} ({mn}–{mx})")
                else:
                    vit_parts.append(f"**{label}:** {last_val}")
        if vit_parts:
            lines.append(" · ".join(vit_parts))
        else:
            lines.append("_(no vitals extracted)_")
        vit_warns = vit.get("warnings", [])
        for w in vit_warns:
            lines.append(f"- ⚠ {w}")
        lines.append("")

        # ── devices (canonical) ─────────────────────────────────
        lines.append("### Devices (canonical)")
        canonical = feat_day.get("devices", {}).get("canonical", {})
        for dev in _DEVICE_ORDER:
            state = canonical.get(dev, "UNKNOWN")
            lines.append(f"- **{dev}:** {state}")
        lines.append("")

        # ── services ────────────────────────────────────────────
        lines.append("### Services")
        nbs = feat_day.get("services", {}).get("notes_by_service", {})
        service_keys = sorted(k for k in nbs if k != "_untagged")
        if service_keys:
            for svc in service_keys:
                notes = nbs[svc]
                lines.append(f"- **{svc}:** {len(notes)} note(s)")
                for note in notes[:2]:
                    preview = _preview(note.get("preview", ""), 100)
                    nk = note.get("note_kind", "")
                    lines.append(f"  - _{nk}_ — {preview}")
        else:
            lines.append("- (none)")
        lines.append("")

        # ── labs — big changes only ─────────────────────────────
        lines.append("### Labs — Big Changes Only (explicit)")
        daily_labs = feat_day.get("labs", {}).get("daily", {})
        latest_labs = feat_day.get("labs", {}).get("latest", {})
        big_changes: List[str] = []
        for comp in sorted(daily_labs):
            info = daily_labs[comp]
            if info.get("big_change"):
                delta = info.get("delta", 0)
                first = info.get("first")
                last = info.get("last")
                # Try to get unit from latest
                unit = ""
                if comp in latest_labs and isinstance(latest_labs[comp], dict):
                    unit = latest_labs[comp].get("unit", "")
                flags_str = ""
                if info.get("abnormal_flag_present"):
                    flags_str = " ⚠ abnormal flag"
                big_changes.append(
                    f"- **{comp}:** first {first} → last {last}"
                    f" (Δ {delta:+.2f}"
                    f"{' ' + unit if unit else ''}){flags_str}"
                )
        if big_changes:
            lines.extend(big_changes)
        else:
            lines.append("None")
        lines.append("")

        # ── nursing screens ─────────────────────────────────────
        lines.append("### Nursing Screens (keyword-only)")
        screen_results = _screen_day(timeline_items)
        for screen_name in _NURSING_SCREENS:
            lines.append(f"- **{screen_name}:** {screen_results[screen_name]}")
        lines.append("")

    return "\n".join(lines) + "\n"


# ── main ─────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Render Drafts-friendly daily packet (Markdown)",
    )
    ap.add_argument("--pat", required=True, help="Patient folder name")
    args = ap.parse_args()
    pat = args.pat

    features_path = _REPO / "outputs" / "features" / pat / "patient_features_v1.json"
    timeline_path = _REPO / "outputs" / "timeline" / pat / "patient_days_v1.json"

    missing = []
    if not features_path.is_file():
        missing.append(f"  features: {features_path}")
    if not timeline_path.is_file():
        missing.append(f"  timeline: {timeline_path}")
    if missing:
        print("FAIL: required file(s) missing:", file=sys.stderr)
        for m in missing:
            print(m, file=sys.stderr)
        return 1

    features = _load_json(features_path)
    days_data = _load_json(timeline_path)

    md = render_packet(pat, features, days_data)

    out_dir = _REPO / "outputs" / "reporting" / pat
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "DRAFTS_DAILY_PACKET_v1.md"

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md)

    print(f"OK ✅ Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
