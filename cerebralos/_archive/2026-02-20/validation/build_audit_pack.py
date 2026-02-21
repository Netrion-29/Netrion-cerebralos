#!/usr/bin/env python3
"""
Deterministic audit-pack builder for CerebralOS.

Collects all pipeline artefacts into a single outputs/audit/<PAT>/ folder
and generates audit_report_v1.txt with structured coverage checks.

Usage:
    python3 cerebralos/validation/build_audit_pack.py --pat Timothy_Cowan

Fail-closed: exits non-zero if required artefacts are missing.
No inference; pure string matching + counts + previews.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from cerebralos.validation.keyword_rules import NURSING_SCREENS, GAP_KEYWORDS

# ── repo layout ─────────────────────────────────────────────────────
_REPO = Path(__file__).resolve().parent.parent.parent

_ARTEFACTS = {
    "RAW.txt":                    lambda pat: _REPO / "data_raw" / f"{pat}.txt",
    "patient_evidence_v1.json":   lambda pat: _REPO / "outputs" / "evidence" / pat / "patient_evidence_v1.json",
    "patient_days_v1.json":       lambda pat: _REPO / "outputs" / "timeline" / pat / "patient_days_v1.json",
    "patient_features_v1.json":   lambda pat: _REPO / "outputs" / "features" / pat / "patient_features_v1.json",
    "TRAUMA_DAILY_NOTES_v3.txt":  lambda pat: _REPO / "outputs" / "reporting" / pat / "TRAUMA_DAILY_NOTES_v3.txt",
}

# Optional artefacts (loaded if present, not required)
_OPTIONAL_ARTEFACTS = {
    "green_card_evidence_v1.json": lambda pat: _REPO / "outputs" / "green_card" / pat / "green_card_evidence_v1.json",
}

# ── nursing screen keywords (imported from keyword_rules) ───────────
_NURSING_SCREENS = NURSING_SCREENS
_GAP_KEYWORDS = GAP_KEYWORDS


# ── helpers ──────────────────────────────────────────────────────────

def _load_json(path: Path) -> Any:
    with open(path, encoding="utf-8", errors="replace") as f:
        return json.load(f)


def _read_text(path: Path) -> str:
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def _count_keyword_in_text(pattern: re.Pattern, text: str) -> int:
    return len(pattern.findall(text))


def _preview(text: str, maxlen: int = 120) -> str:
    return text.replace("\n", " ").strip()[:maxlen]


# ── report sections ─────────────────────────────────────────────────

def _section_evidence_counts(evidence: Dict) -> List[str]:
    """Section 1: counts by evidence type."""
    lines = ["=" * 70, "1) EVIDENCE TYPE COUNTS", "=" * 70]
    counter: Counter = Counter()
    for item in evidence.get("items", []):
        counter[item.get("kind", "UNKNOWN")] += 1
    total = sum(counter.values())
    for kind in sorted(counter):
        lines.append(f"  {kind:30s} {counter[kind]:5d}")
    lines.append(f"  {'TOTAL':30s} {total:5d}")
    lines.append("")
    return lines


def _section_timestamp_coverage(evidence: Dict) -> List[str]:
    """Section 2: timestamp coverage + top 20 ts_missing."""
    lines = ["=" * 70, "2) TIMESTAMP COVERAGE", "=" * 70]
    items = evidence.get("items", [])
    with_ts = 0
    missing_ts: List[Dict] = []
    for item in items:
        dt = item.get("datetime")
        if dt:
            with_ts += 1
        else:
            missing_ts.append(item)

    total = len(items)
    lines.append(f"  with_ts:    {with_ts:5d}")
    lines.append(f"  missing_ts: {len(missing_ts):5d}")
    lines.append(f"  total:      {total:5d}")
    if total > 0:
        lines.append(f"  coverage:   {with_ts / total * 100:.1f}%")
    lines.append("")

    if missing_ts:
        lines.append(f"  Top {min(20, len(missing_ts))} ts_missing items:")
        for item in missing_ts[:20]:
            kind = item.get("kind", "?")
            idx = item.get("idx", "?")
            text = _preview(item.get("text", ""), 90)
            lines.append(f"    [{idx:>5}] {kind:20s} {text}")
    lines.append("")
    return lines


def _section_nursing_screens(days_data: Dict) -> List[str]:
    """Section 3: nursing screen coverage per calendar day."""
    lines = ["=" * 70, "3) NURSING SCREEN COVERAGE (keyword-based)", "=" * 70]

    days_map = days_data.get("days", {})
    day_keys = sorted(k for k in days_map if k != "__UNDATED__")

    # Build header row
    screen_names = list(_NURSING_SCREENS.keys())
    header = f"  {'Day':12s}"
    for sn in screen_names:
        header += f"  {sn:>20s}"
    lines.append(header)
    lines.append("  " + "-" * (12 + 22 * len(screen_names)))

    for day_iso in day_keys:
        items = days_map[day_iso].get("items", [])
        # Separate nursing note items vs all items
        nursing_texts: List[str] = []
        all_texts: List[str] = []
        for item in items:
            text = (item.get("payload") or {}).get("text", "")
            itype = item.get("type", "")
            all_texts.append(text)
            if itype in ("NURSING_NOTE", "MAR"):
                nursing_texts.append(text)

        has_nursing = len(nursing_texts) > 0
        combined_nursing = "\n".join(nursing_texts)
        combined_all = "\n".join(all_texts)

        row = f"  {day_iso:12s}"
        for sn in screen_names:
            patterns = _NURSING_SCREENS[sn]
            if not has_nursing:
                row += f"  {'UNKNOWN':>20s}"
            else:
                hit = any(p.search(combined_nursing) for p in patterns)
                if not hit:
                    # Also check all items in case screen is documented
                    # by a physician note (still deterministic)
                    hit = any(p.search(combined_all) for p in patterns)
                row += f"  {'HIT' if hit else 'NO HIT':>20s}"
        lines.append(row)

    lines.append("")
    return lines


def _section_device_evidence(features: Dict) -> List[str]:
    """Section 4: device coverage — evidence snippets for PRESENT devices."""
    lines = ["=" * 70, "4) DEVICE COVERAGE (canonical PRESENT + evidence)", "=" * 70]
    days = features.get("days", {})

    for day_iso in sorted(days.keys()):
        devices = days[day_iso].get("devices", {})
        canonical = devices.get("canonical", {})
        evidence = devices.get("evidence", {})
        present_devs = [d for d in sorted(canonical) if canonical[d] == "PRESENT"]
        if not present_devs:
            continue
        lines.append(f"  {day_iso}:")
        for dev in present_devs:
            snippets = evidence.get(dev, [])
            if snippets:
                snip = snippets[0]  # 1 snippet per device per day
                preview = _preview(snip.get("text_preview", ""), 100)
                lines.append(f"    {dev:20s} PRESENT  line_id={snip.get('line_id', '?')}  \"{preview}\"")
            else:
                lines.append(f"    {dev:20s} PRESENT  (no evidence snippet)")

    lines.append("")
    return lines


def _section_consultant_coverage(features: Dict) -> List[str]:
    """Section 5: consultant coverage from notes_by_service."""
    lines = ["=" * 70, "5) CONSULTANT COVERAGE (notes_by_service)", "=" * 70]
    days = features.get("days", {})
    day_keys = sorted(days.keys())

    # Collect all service names across all days
    all_services: Set[str] = set()
    for day_iso in day_keys:
        nbs = days[day_iso].get("services", {}).get("notes_by_service", {})
        all_services.update(nbs.keys())

    service_list = sorted(all_services - {"_untagged"})
    if not service_list:
        lines.append("  (no tagged services found)")
        lines.append("")
        return lines

    # Header
    header = f"  {'Day':12s}"
    for svc in service_list:
        header += f"  {svc:>15s}"
    lines.append(header)
    lines.append("  " + "-" * (12 + 17 * len(service_list)))

    for day_iso in day_keys:
        nbs = days[day_iso].get("services", {}).get("notes_by_service", {})
        row = f"  {day_iso:12s}"
        for svc in service_list:
            cnt = len(nbs.get(svc, []))
            row += f"  {cnt if cnt else '.':>15}"
        lines.append(row)

    # Totals
    row = f"  {'TOTAL':12s}"
    for svc in service_list:
        total = sum(
            len(days[d].get("services", {}).get("notes_by_service", {}).get(svc, []))
            for d in day_keys
        )
        row += f"  {total:>15d}"
    lines.append(row)
    lines.append("")
    return lines


def _section_keyword_gap_scan(
    raw_text: str,
    evidence: Dict,
) -> List[str]:
    """Section 6: raw text vs structured keyword gap scan."""
    lines = ["=" * 70, "6) KEYWORD GAP SCAN (raw vs structured)", "=" * 70]
    lines.append(f"  {'Keyword':20s} {'Raw hits':>10s} {'Structured':>12s} {'Status':>15s}")
    lines.append("  " + "-" * 60)

    # Build combined structured text from all evidence items
    structured_texts: List[str] = []
    for item in evidence.get("items", []):
        structured_texts.append(item.get("text", ""))
    structured_combined = "\n".join(structured_texts)

    any_miss = False
    for kw_label, kw_pat in _GAP_KEYWORDS:
        raw_hits = _count_keyword_in_text(kw_pat, raw_text)
        struct_hits = _count_keyword_in_text(kw_pat, structured_combined)
        if raw_hits > 0 and struct_hits == 0:
            status = "POSSIBLE MISS"
            any_miss = True
        elif raw_hits > 0:
            status = "OK"
        else:
            status = "-"
        lines.append(f"  {kw_label:20s} {raw_hits:>10d} {struct_hits:>12d} {status:>15s}")

    if not any_miss:
        lines.append("")
        lines.append("  No keyword gaps detected.")
    lines.append("")
    return lines


def _section_evidence_day_gaps(features: Dict) -> List[str]:
    """Section 7: Evidence day-gap detection."""
    lines = ["=" * 70, "7) EVIDENCE DAY-GAP DETECTION", "=" * 70]

    days = features.get("days", {})
    day_keys = sorted(k for k in days if k != "__UNDATED__")

    gaps: List[Dict] = []
    if len(day_keys) >= 2:
        for i in range(len(day_keys) - 1):
            d1 = date.fromisoformat(day_keys[i])
            d2 = date.fromisoformat(day_keys[i + 1])
            gap_days = (d2 - d1).days
            if gap_days > 1:
                gaps.append({"from": day_keys[i], "to": day_keys[i + 1], "gap_days": gap_days})

    max_gap = max((g["gap_days"] for g in gaps), default=0)
    lines.append(f"  gap_count:    {len(gaps)}")
    lines.append(f"  max_gap_days: {max_gap}")
    if gaps:
        top = sorted(gaps, key=lambda g: g["gap_days"], reverse=True)[:5]
        lines.append(f"  Top {len(top)} gaps:")
        for i, g in enumerate(top, 1):
            lines.append(f"    {i}. {g['from']} -> {g['to']}  ({g['gap_days']} days)")
    else:
        lines.append("  (no gaps detected)")
    lines.append("")
    return lines


def _section_green_card_doc_types(gc_evidence: Optional[Dict]) -> List[str]:
    """Section 8: Green Card doc_type classification counts."""
    lines = ["=" * 70, "8) GREEN CARD DOC-TYPE CLASSIFICATION", "=" * 70]
    if gc_evidence is None:
        lines.append("  (green_card_evidence_v1.json not available)")
        lines.append("")
        return lines

    classifications = gc_evidence.get("doc_type_classification", [])
    counter: Counter = Counter()
    for entry in classifications:
        counter[entry.get("doc_type", "unknown")] += 1

    if not counter:
        lines.append("  (no classifications)")
    else:
        for dtype in sorted(counter, key=lambda d: counter[d], reverse=True):
            marker = " ★" if dtype == "trauma_hp" else ""
            lines.append(f"  {dtype:25s} {counter[dtype]:4d}{marker}")
        lines.append(f"  {'TOTAL':25s} {sum(counter.values()):4d}")

    # Chosen trauma H&P summary
    chosen = gc_evidence.get("chosen_trauma_hp")
    if chosen:
        lines.append("")
        lines.append(f"  Chosen TRAUMA_HP: item_id={chosen.get('item_id')} "
                     f"tier={chosen.get('match_tier')} "
                     f"ts={chosen.get('ts')}")
        lines.append(f"    pattern: {chosen.get('matched_pattern', '')}")
        preview = chosen.get("matched_line_preview", "")
        if len(preview) > 100:
            preview = preview[:100] + "…"
        lines.append(f"    preview: {preview}")
    else:
        lines.append("")
        lines.append("  ⚠ No TRAUMA_HP chosen.")

    lines.append("")
    return lines


# ── main ─────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="Build deterministic audit pack")
    ap.add_argument("--pat", required=True, help="Patient folder name")
    args = ap.parse_args()
    pat = args.pat

    # ── verify all artefacts exist ──────────────────────────────
    missing = []
    resolved: Dict[str, Path] = {}
    for name, path_fn in _ARTEFACTS.items():
        p = path_fn(pat)
        resolved[name] = p
        if not p.is_file():
            missing.append(f"  {name}: {p}")
    if missing:
        print("FAIL: required artefact(s) missing:", file=sys.stderr)
        for m in missing:
            print(m, file=sys.stderr)
        return 1

    # ── create audit dir and copy artefacts ─────────────────────
    audit_dir = _REPO / "outputs" / "audit" / pat
    audit_dir.mkdir(parents=True, exist_ok=True)

    for name, src in resolved.items():
        dst = audit_dir / name
        shutil.copy2(src, dst)
    print(f"Copied {len(resolved)} artefacts to {audit_dir}/")

    # ── load data ───────────────────────────────────────────────
    raw_text = _read_text(resolved["RAW.txt"])
    evidence = _load_json(resolved["patient_evidence_v1.json"])
    days_data = _load_json(resolved["patient_days_v1.json"])
    features = _load_json(resolved["patient_features_v1.json"])

    # ── build report ────────────────────────────────────────────
    report: List[str] = []
    patient_id = features.get("patient_id", "unknown")
    report.append("=" * 70)
    report.append(f"AUDIT REPORT v1 — patient {patient_id} ({pat})")
    report.append(f"Generated deterministically — no inference")
    report.append("=" * 70)
    report.append("")

    report.extend(_section_evidence_counts(evidence))
    report.extend(_section_timestamp_coverage(evidence))
    report.extend(_section_nursing_screens(days_data))
    report.extend(_section_device_evidence(features))
    report.extend(_section_consultant_coverage(features))
    report.extend(_section_keyword_gap_scan(raw_text, evidence))
    report.extend(_section_evidence_day_gaps(features))

    # Section 8: Green Card doc-type classification (optional)
    gc_ev_path = _OPTIONAL_ARTEFACTS["green_card_evidence_v1.json"](pat)
    gc_evidence = None
    if gc_ev_path.is_file():
        gc_evidence = _load_json(gc_ev_path)
    report.extend(_section_green_card_doc_types(gc_evidence))

    report.append("=" * 70)
    report.append("END OF AUDIT REPORT")
    report.append("=" * 70)

    report_text = "\n".join(report) + "\n"

    # ── write report ────────────────────────────────────────────
    report_path = audit_dir / "audit_report_v1.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_text)

    print(f"OK ✅ Wrote audit_report_v1.txt ({len(report)} lines)")
    print(report_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
