#!/usr/bin/env python3
"""
Deterministic QA report for patient_features_v1.json.

Prints a concise summary to stdout covering labs (daily deltas),
devices (tri-state counts), and services (note counts).

Usage:
    python3 cerebralos/validation/report_features_qa.py --pat Timothy_Cowan

Fail-closed: exits non-zero with clear message if features file missing.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from cerebralos.features.vitals_daily import ABNORMAL_THRESHOLDS, is_abnormal
from cerebralos.validation.keyword_rules import NURSING_SCREENS

# Metrics to include in ABNORMAL VITALS COUNTS (MAP explicitly included)
ABNORMAL_VITALS_METRICS = ("hr", "sbp", "map", "temp_f", "spo2", "rr")

# ── Narrative lab mention keywords (QA scan only, not structured) ───
_NARRATIVE_LAB_KEYWORDS: dict[str, str] = {
    "creatinine": r"\bcreatinine\b",
    "BUN":        r"\bBUN\b",
    "WBC":        r"\bWBC\b",
    "Hgb":        r"\b(Hgb|hemoglobin|hgb)\b",
    "INR":        r"\bINR\b",
    "lactate":    r"\blactate\b",
    "BD":         r"\b(base\s*deficit|BD)\b",
    "CK":         r"\b(CK|creatine\s*kinase|CPK)\b",
    "TSH":        r"\bTSH\b",
    "troponin":   r"\b(troponin|trop)\b",
}


def _features_path(pat: str) -> Path:
    repo = Path(__file__).resolve().parent.parent.parent
    return repo / "outputs" / "features" / pat / "patient_features_v1.json"


def _timeline_path(pat: str) -> Path:
    repo = Path(__file__).resolve().parent.parent.parent
    return repo / "outputs" / "timeline" / pat / "patient_days_v1.json"


# ── device keyword gap scan ─────────────────────────────────────

# Raw-text scan keywords grouped by device category.
# These are broad terms to find ANY mention in the raw text, so we can
# compare against what the structured device extraction found.
_DEVICE_SCAN_KEYWORDS: dict[str, list[str]] = {
    "foley": [
        r"\bfoley\b", r"\burinary catheter\b", r"\bindwelling catheter\b",
        r"\bcondom cath\b", r"\bexternal catheter\b", r"\bsuprapubic catheter\b",
    ],
    "central_line": [
        r"\bcentral line\b", r"\bcentral venous\b", r"\bcvc\b",
        r"\bpicc\b", r"\bcordis\b", r"\btriple lumen\b",
        r"\bsubclavian.{0,8}(line|catheter)\b",
        r"\binternal jugular\b", r"\b(right|left|r\.?|l\.?)\s*IJ\b",
        r"\bport-a-cath\b",
    ],
    "ett_vent": [
        r"\bett\b", r"\bintubat(ed|ion)\b", r"\bmechanical ventilation\b",
        r"\bventilator\b", r"\bventilated\b",
        r"\btrach(eostomy)?\b", r"\bendotracheal\b",
        r"\bvent settings\b", r"\bventilator mode\b",
        r"\btidal volume\b",
    ],
    "chest_tube": [
        r"\bchest tube\b", r"\bthoracostomy\b", r"\bblake drain\b",
    ],
    "drain": [
        r"\bjp\b", r"\bjackson.pratt\b", r"\bhemovac\b",
        r"\bsurgical drain\b", r"\bwound vac\b",
        r"\bnegative pressure wound therapy\b",
    ],
}

# Negative-context patterns — if these appear on the same line as a
# keyword match, it is a FALSE POSITIVE (e.g., DNI orders).
_DEVICE_NEGATIVE_CONTEXT: list[str] = [
    r"\bdo not intubate\b",
    r"\bdo not resuscitate\b",
    r"\bDNR.{0,5}DNI\b",
    r"\bno intubation\b",
    r"\bcode status\b",
]


def _device_gap_scan(timeline_data: dict, features_data: dict) -> None:
    """
    Compare raw-text device keyword hits vs. structured device results.

    Prints a section summarising:
    - How many raw-text lines mention each device category
    - What the structured extraction produced (PRESENT days)
    - Gap: raw mentions that were NOT captured as PRESENT
    """
    days_map = timeline_data.get("days") or {}
    feat_days = features_data.get("days") or {}

    # Compile patterns
    compiled_kw: dict[str, list[re.Pattern[str]]] = {}
    for cat, pats in _DEVICE_SCAN_KEYWORDS.items():
        compiled_kw[cat] = [re.compile(p, re.IGNORECASE) for p in pats]
    neg_pats = [re.compile(p, re.IGNORECASE) for p in _DEVICE_NEGATIVE_CONTEXT]

    # Scan raw text
    raw_hits: dict[str, list[dict]] = {cat: [] for cat in _DEVICE_SCAN_KEYWORDS}
    for day_iso, day_info in sorted(days_map.items()):
        for item in day_info.get("items") or []:
            text = (item.get("payload") or {}).get("text", "")
            for line in text.split("\n"):
                # Check negative context first
                neg = any(np.search(line) for np in neg_pats)
                for cat, pats in compiled_kw.items():
                    for pat in pats:
                        m = pat.search(line)
                        if m:
                            raw_hits[cat].append({
                                "day": day_iso,
                                "match": m.group(),
                                "context": line.strip()[:100],
                                "neg_context": neg,
                            })
                            break  # one hit per category per line

    # Structured results: count PRESENT days
    struct_present_days: dict[str, list[str]] = {cat: [] for cat in _DEVICE_SCAN_KEYWORDS}
    for day_iso in sorted(feat_days.keys()):
        canonical = feat_days[day_iso].get("devices", {}).get("canonical", {})
        for cat in _DEVICE_SCAN_KEYWORDS:
            if canonical.get(cat) == "PRESENT":
                struct_present_days[cat].append(day_iso)

    # Report
    print("DEVICE KEYWORD GAP SCAN (raw text vs. structured):")
    any_gap = False
    for cat in sorted(_DEVICE_SCAN_KEYWORDS.keys()):
        hits = raw_hits[cat]
        real_hits = [h for h in hits if not h["neg_context"]]
        neg_hits = [h for h in hits if h["neg_context"]]
        present_days = struct_present_days[cat]
        raw_days = sorted(set(h["day"] for h in real_hits))
        missing_days = sorted(set(raw_days) - set(present_days))

        status = "OK"
        if real_hits and not present_days:
            status = "GAP (raw mentions but no PRESENT days)"
            any_gap = True
        elif missing_days:
            status = f"GAP ({len(missing_days)} day(s) with raw mentions but not PRESENT)"
            any_gap = True

        print(f"  {cat:20s}  raw_lines={len(real_hits):3d}  "
              f"neg_ctx={len(neg_hits):2d}  "
              f"PRESENT_days={len(present_days):2d}  "
              f"raw_days={len(raw_days):2d}  "
              f"{status}")

        if real_hits and not present_days:
            # Show top 3 sample lines
            for h in real_hits[:3]:
                print(f"    sample [{h['day']}]: {h['context']}")

    if not any_gap:
        print("  (no gaps detected)")
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description="QA report for patient features v1")
    ap.add_argument("--pat", required=True, help="Patient folder name")
    args = ap.parse_args()

    path = _features_path(args.pat)
    if not path.is_file():
        print(f"FAIL: features file not found: {path}", file=sys.stderr)
        return 1

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    # Load timeline for device gap scan (optional — warn if missing)
    timeline_path = _timeline_path(args.pat)
    timeline_data: dict | None = None
    if timeline_path.is_file():
        with open(timeline_path, encoding="utf-8") as f:
            timeline_data = json.load(f)

    patient_id = data.get("patient_id", "unknown")
    days = data.get("days", {})
    day_keys = sorted(days.keys())
    has_undated = "__UNDATED__" in days
    dated_keys = [k for k in day_keys if k != "__UNDATED__"]

    # ── header ──────────────────────────────────────────────────
    print("=" * 60)
    print(f"FEATURES QA REPORT: {patient_id}")
    print("=" * 60)
    print(f"Days: {len(day_keys)} total ({len(dated_keys)} dated"
          f"{', +__UNDATED__' if has_undated else ''})")
    print(f"Day range: {dated_keys[0] if dated_keys else 'n/a'}"
          f" .. {dated_keys[-1] if dated_keys else 'n/a'}")
    print()

    # ── evidence gap-day detection ──────────────────────────────
    gaps: list[dict] = []
    if len(dated_keys) >= 2:
        for i in range(len(dated_keys) - 1):
            d1 = date.fromisoformat(dated_keys[i])
            d2 = date.fromisoformat(dated_keys[i + 1])
            gap_days = (d2 - d1).days
            if gap_days > 1:
                gaps.append({"from": dated_keys[i], "to": dated_keys[i + 1], "gap_days": gap_days})

    max_gap = max((g["gap_days"] for g in gaps), default=0)
    print("EVIDENCE GAP-DAY DETECTION:")
    print(f"  evidence_gap_detected: {len(gaps) > 0}")
    print(f"  evidence_gap_count: {len(gaps)}")
    print(f"  max_gap_days: {max_gap}")
    if gaps:
        top_gaps = sorted(gaps, key=lambda g: g["gap_days"], reverse=True)[:5]
        print("  Top gaps:")
        for i, g in enumerate(top_gaps, 1):
            print(f"    {i}. {g['from']} -> {g['to']}  ({g['gap_days']} days)")
    else:
        print("  (no gaps detected)")
    print()

    # ── warnings summary ────────────────────────────────────────
    ws = data.get("warnings_summary", {})
    print("WARNINGS SUMMARY:")
    if ws:
        for k in sorted(ws.keys()):
            print(f"  {k}: {ws[k]}")
    else:
        print("  (none)")
    print()

    # ── labs: daily deltas ──────────────────────────────────────
    all_deltas: list[dict] = []
    components_with_delta = 0
    for day_iso in day_keys:
        daily = days[day_iso].get("labs", {}).get("daily", {})
        for comp, info in daily.items():
            if info.get("delta") is not None:
                components_with_delta += 1
                all_deltas.append({
                    "component": comp,
                    "day": day_iso,
                    "delta": info["delta"],
                    "first": info.get("first"),
                    "last": info.get("last"),
                    "big_change": info.get("big_change", False),
                    "abnormal": info.get("abnormal_flag_present", False),
                })

    print(f"LABS: {components_with_delta} component-day pairs with deltas")
    if all_deltas:
        top = sorted(all_deltas, key=lambda x: abs(x["delta"]), reverse=True)[:10]
        print("  Top 10 absolute deltas:")
        for i, d in enumerate(top, 1):
            flag = " *BIG*" if d["big_change"] else ""
            abn = " [abnormal]" if d["abnormal"] else ""
            print(f"    {i:2d}. {d['component']:40s} {d['day']}  "
                  f"delta={d['delta']:+.2f}  ({d['first']}->{d['last']})"
                  f"{flag}{abn}")
    print()

    # ── devices: tri-state counts ───────────────────────────────
    device_counts: dict[str, Counter] = {}
    for day_iso in day_keys:
        canonical = days[day_iso].get("devices", {}).get("canonical", {})
        for dev, state in canonical.items():
            device_counts.setdefault(dev, Counter())[state] += 1

    print("DEVICES (canonical tri-state across all days):")
    if device_counts:
        for dev in sorted(device_counts.keys()):
            c = device_counts[dev]
            parts = []
            for s in ("PRESENT", "NOT_PRESENT", "UNKNOWN"):
                if c[s]:
                    parts.append(f"{s}={c[s]}")
            print(f"  {dev:20s}  {', '.join(parts)}")
    else:
        print("  (none)")
    print()

    # ── devices: carry-forward summary ──────────────────────────
    cf_counts: dict[str, Counter] = {}
    inferred_total = 0
    for day_iso in day_keys:
        cf = days[day_iso].get("devices", {}).get("carry_forward", {})
        for dev, state in cf.items():
            cf_counts.setdefault(dev, Counter())[state] += 1
            if state == "PRESENT_INFERRED":
                inferred_total += 1

    print("DEVICES (carry-forward across all days):")
    if cf_counts:
        for dev in sorted(cf_counts.keys()):
            c = cf_counts[dev]
            parts = []
            for s in ("PRESENT", "PRESENT_INFERRED", "NOT_PRESENT", "UNKNOWN"):
                if c[s]:
                    parts.append(f"{s}={c[s]}")
            print(f"  {dev:20s}  {', '.join(parts)}")
        print(f"  {'':20s}  TOTAL PRESENT_INFERRED = {inferred_total}")
    else:
        print("  (none)")
    print()

    # ── devices: day counts (last day snapshot) ─────────────────
    last_dated = [k for k in day_keys if k != "__UNDATED__"]
    if last_dated:
        last_day = sorted(last_dated)[-1]
        dc = days[last_day].get("devices", {}).get("day_counts", {})
        totals = dc.pop("totals", {}) if isinstance(dc, dict) else {}
        print(f"DEVICES DAY COUNTS (as of {last_day}):")
        if dc:
            for k in sorted(dc.keys()):
                print(f"  {k:40s}  {dc[k]}")
        if totals:
            print(f"  {'--- totals ---':40s}")
            for k in sorted(totals.keys()):
                print(f"  {k:40s}  {totals[k]}")
        if not dc and not totals:
            print("  (none)")
    else:
        print("DEVICES DAY COUNTS: (no dated days)")
    print()

    # ── device keyword gap scan (raw text vs. structured) ───────
    if timeline_data:
        _device_gap_scan(timeline_data, data)
    else:
        print("DEVICE KEYWORD GAP SCAN: (skipped — timeline file not found)")
        print()

    # ── labs: daily coverage (component counts per day) ─────────
    lab_day_counts: list[tuple[str, int]] = []
    for day_iso in day_keys:
        daily = days[day_iso].get("labs", {}).get("daily", {})
        lab_day_counts.append((day_iso, len(daily)))

    total_comp_days = sum(c for _, c in lab_day_counts)
    days_with_labs = sum(1 for _, c in lab_day_counts if c > 0)
    print(f"LABS COVERAGE: {total_comp_days} component-day pairs across "
          f"{days_with_labs}/{len(day_keys)} days")
    for day_iso, cnt in lab_day_counts:
        if cnt > 0:
            print(f"  {day_iso}: {cnt} components")
    print()

    # ── services: notes per service ─────────────────────────────
    svc_note_counts: Counter = Counter()
    svc_days: dict[str, set] = {}
    for day_iso in day_keys:
        nbs = days[day_iso].get("services", {}).get("notes_by_service", {})
        for svc, notes in nbs.items():
            svc_note_counts[svc] += len(notes)
            svc_days.setdefault(svc, set()).add(day_iso)

    print("SERVICES (notes_by_service counts):")
    if svc_note_counts:
        for svc, cnt in svc_note_counts.most_common():
            n_days = len(svc_days.get(svc, set()))
            print(f"  {svc:25s}  {cnt:3d} notes across {n_days} day(s)")
    else:
        print("  (none)")
    print()

    # ── vitals: coverage summary ────────────────────────────────
    vitals_days_any = 0
    vitals_days_missing: list[str] = []
    vitals_metric_counts: Counter = Counter()
    for day_iso in day_keys:
        vit = days[day_iso].get("vitals", {})
        has_any = False
        for mk in ("temp_f", "hr", "rr", "spo2", "sbp", "dbp", "map"):
            cnt = vit.get(mk, {}).get("count", 0)
            if cnt > 0:
                has_any = True
                vitals_metric_counts[mk] += cnt
        if has_any:
            vitals_days_any += 1
        else:
            vitals_days_missing.append(day_iso)

    print(f"VITALS COVERAGE:")
    print(f"  days_with_any_vitals: {vitals_days_any}/{len(day_keys)}")
    if vitals_days_missing:
        print(f"  missing_days ({len(vitals_days_missing)}): " +
              ", ".join(vitals_days_missing[:10]) +
              ("..." if len(vitals_days_missing) > 10 else ""))
    else:
        print("  missing_days: (none)")
    if vitals_metric_counts:
        print("  readings per metric:")
        for mk in ("temp_f", "hr", "rr", "spo2", "sbp", "dbp", "map"):
            cnt = vitals_metric_counts.get(mk, 0)
            print(f"    {mk:8s}  {cnt:4d}")
    print()

    # ── vitals: timestamp QA metrics ────────────────────────────
    vqa = data.get("vitals_qa", {})
    print("VITALS TIMESTAMP QA METRICS:")
    for k in ("vitals_readings_total", "vitals_readings_with_full_ts",
              "vitals_readings_missing_time", "vitals_readings_missing_date",
              "undated_vitals_count"):
        print(f"  {k}: {vqa.get(k, 0)}")
    print()

    # ── vitals: abnormal summary (per day) ──────────────────────
    print("VITALS ABNORMAL SUMMARY:")
    any_abnormal = False
    for day_iso in day_keys:
        vit = days[day_iso].get("vitals", {})
        abn_summ = vit.get("abnormal_summary", {})
        if abn_summ:
            any_abnormal = True
            parts = []
            for mk in ("temp_f", "hr", "rr", "spo2", "sbp", "dbp", "map"):
                info = abn_summ.get(mk)
                if info:
                    fa = info.get("first_abnormal", {})
                    fa_val = fa.get("value", "?") if fa else "?"
                    fa_dt = fa.get("dt", "no_ts") if fa else "no_ts"
                    fa_tm = " [time_missing]" if (fa and fa.get("time_missing")) else ""
                    parts.append(f"{mk}={info['count']}x (first: {fa_val} @{fa_dt}{fa_tm})")
            print(f"  {day_iso}: {'; '.join(parts)}")
    if not any_abnormal:
        print("  (no abnormal readings detected)")
    print()

    # ── tabular vitals unsupported metrics ──────────────────────
    tabular_total = 0
    tabular_parsed = 0
    tabular_unsupported = 0
    for day_iso in day_keys:
        vit = days[day_iso].get("vitals", {})
        vqa = vit.get("vitals_qa", {})
        day_unsup = vqa.get("tabular_note_vitals_unsupported", 0)
        tabular_unsupported += day_unsup
        # Total tabular lines: readings_total serves as proxy for parsed
        day_total = vqa.get("vitals_readings_total", 0)
        tabular_total += day_total + day_unsup
        tabular_parsed += day_total
    print("TABULAR VITALS UNSUPPORTED METRICS:")
    print(f"  tabular_vitals_lines_total: {tabular_total}")
    print(f"  tabular_vitals_lines_parsed: {tabular_parsed}")
    print(f"  tabular_vitals_lines_unsupported: {tabular_unsupported}")
    print()

    # ── narrative lab mention detection (QA only) ───────────────
    narrative_hit_counts: Counter = Counter()
    structured_lab_components: set[str] = set()
    # Collect which components exist in structured labs
    for day_iso in day_keys:
        daily = days[day_iso].get("labs", {}).get("daily", {})
        for comp in daily:
            structured_lab_components.add(comp.lower())

    # Scan raw text in timeline for narrative lab mentions
    if timeline_data:
        tl_days = timeline_data.get("days") or {}
        for day_iso_t, day_info_t in tl_days.items():
            for item in day_info_t.get("items") or []:
                text = (item.get("payload") or {}).get("text", "")
                item_type = item.get("type", "")
                # Skip LAB items (already structured)
                if item_type == "LAB":
                    continue
                for kw_name, kw_pat in _NARRATIVE_LAB_KEYWORDS.items():
                    if re.search(kw_pat, text, re.IGNORECASE):
                        narrative_hit_counts[kw_name] += 1

    present_but_missing: list[str] = []
    for kw_name in sorted(_NARRATIVE_LAB_KEYWORDS.keys()):
        if narrative_hit_counts[kw_name] > 0:
            # Check if this lab was captured in structured extraction
            # Use lowercase fuzzy match
            found_structured = False
            for sc in structured_lab_components:
                if kw_name.lower() in sc or sc in kw_name.lower():
                    found_structured = True
                    break
            if not found_structured:
                present_but_missing.append(kw_name)

    print("NARRATIVE LAB MENTION DETECTION (QA only — no structured parsing):")
    print(f"  narrative_lab_mentions_detected: {sum(narrative_hit_counts.values())}")
    if narrative_hit_counts:
        for kw in sorted(narrative_hit_counts.keys()):
            print(f"    {kw}: {narrative_hit_counts[kw]}")
    print(f"  narrative_labs_present_but_structured_missing: {len(present_but_missing)}")
    if present_but_missing:
        print(f"    missing: {', '.join(present_but_missing)}")
    print()

    # ── abnormal vitals counts (locked thresholds) ──────────────
    # Thresholds come from cerebralos.features.vitals_daily.ABNORMAL_THRESHOLDS
    # and are applied per-source via the enriched `abnormal` flag.
    _th_parts = []
    for m in ABNORMAL_VITALS_METRICS:
        th = ABNORMAL_THRESHOLDS.get(m, {})
        descs = []
        if "low" in th:
            op = "<=" if m == "temp_f" else "<"
            descs.append(f"{m.upper()}{op}{th['low']}")
        if "high" in th:
            op = ">=" if m == "temp_f" else ">"
            descs.append(f"{m.upper()}{op}{th['high']}")
        _th_parts.extend(descs)
    print("ABNORMAL VITALS COUNTS (locked thresholds):")
    print(f"  Thresholds: {', '.join(_th_parts)}")
    abn_counts: Counter = Counter()
    for day_iso in day_keys:
        vit = days[day_iso].get("vitals", {})
        for metric in ABNORMAL_VITALS_METRICS:
            metric_data = vit.get(metric, {})
            sources = metric_data.get("sources", [])
            for src in sources:
                # Prefer pre-computed abnormal flag (enriched sources)
                if src.get("abnormal"):
                    abn_counts[metric] += 1
                    continue
                # Fallback: re-derive from value + canonical thresholds
                val = src.get("value")
                if val is not None and is_abnormal(metric, val):
                    abn_counts[metric] += 1
    total_abnormal = sum(abn_counts.values())
    print(f"  total_abnormal_readings: {total_abnormal}")
    for metric in ABNORMAL_VITALS_METRICS:
        print(f"  {metric}: {abn_counts.get(metric, 0)}")
    print()

    # ── abnormal summary consistency check ──────────────────────
    # Cross-check: metric-level abnormal_count vs source-level tally
    mismatch_found = False
    for day_iso in day_keys:
        vit = days[day_iso].get("vitals", {})
        for metric in ABNORMAL_VITALS_METRICS:
            metric_data = vit.get(metric, {})
            rollup_abn = metric_data.get("abnormal_count", 0)
            src_abn = sum(1 for s in metric_data.get("sources", []) if s.get("abnormal"))
            if rollup_abn != src_abn:
                if not mismatch_found:
                    print("VITALS ABNORMAL CONSISTENCY CHECK:")
                    mismatch_found = True
                print(f"  MISMATCH {day_iso}/{metric}: rollup={rollup_abn} sources={src_abn}")
    if not mismatch_found:
        print("VITALS ABNORMAL CONSISTENCY CHECK: OK")
    print()

    # ── nursing screens (keyword scan) ──────────────────────────
    print("NURSING SCREENS (keyword scan):")
    if timeline_data:
        tl_days_ns = timeline_data.get("days") or {}
        screen_counts: Counter = Counter()
        for _day_iso_ns, day_info_ns in tl_days_ns.items():
            for item_ns in day_info_ns.get("items") or []:
                text_ns = (item_ns.get("payload") or {}).get("text", "")
                if not text_ns:
                    continue
                for label, patterns in NURSING_SCREENS.items():
                    for pat in patterns:
                        screen_counts[label] += len(pat.findall(text_ns))
        for label in ("CAM-ICU", "Delirium", "Braden", "Fall risk",
                      "Restraints", "SAT_TRIAL", "SBT_TRIAL"):
            cnt = screen_counts.get(label, 0)
            print(f"  {label}: {cnt}")
    else:
        print("  DATA NOT AVAILABLE (no timeline notes)")
    print()

    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
