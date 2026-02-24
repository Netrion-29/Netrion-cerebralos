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
    feats = data.get("features", {})
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
    vqa = feats.get("vitals_qa", {})
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

    # ── canonical vitals v1 QA ──────────────────────────────────
    cv1 = feats.get("vitals_canonical_v1", {})
    cv1_days = cv1.get("days", {})
    cv1_total_records = 0
    cv1_days_with_vitals = 0
    cv1_total_abnormal = 0
    cv1_flag_counts: Counter = Counter()
    cv1_missing_line_id = 0

    for _cv_day, cv_day_data in cv1_days.items():
        recs = cv_day_data.get("records", [])
        cv1_total_records += len(recs)
        if recs:
            cv1_days_with_vitals += 1
        cv1_total_abnormal += cv_day_data.get("abnormal_total", 0)
        for rec in recs:
            for flag in rec.get("abnormal_flags", []):
                cv1_flag_counts[flag] += 1
            if not rec.get("raw_line_id"):
                cv1_missing_line_id += 1

    print("CANONICAL VITALS v1 QA:")
    print(f"  total_canonical_records: {cv1_total_records}")
    print(f"  days_with_canonical_vitals: {cv1_days_with_vitals}/{len(day_keys)}")
    print(f"  total_abnormal_flags: {cv1_total_abnormal}")
    if cv1_flag_counts:
        print("  top abnormal flag types:")
        for flag, cnt in cv1_flag_counts.most_common(5):
            print(f"    {flag}: {cnt}")
    else:
        print("  top abnormal flag types: (none)")
    print(f"  records_missing_raw_line_id: {cv1_missing_line_id}"
          + (" [OK]" if cv1_missing_line_id == 0 else " [FLAG]"))
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

    # ── DVT Prophylaxis v1 QA ───────────────────────────────────
    dvt = feats.get("dvt_prophylaxis_v1", {})
    print("DVT PROPHYLAXIS v1 QA (chemical-only timing):")
    dvt_pharm_ts = dvt.get("pharm_first_ts") or "DATA NOT AVAILABLE"
    dvt_mech_ts = dvt.get("mech_first_ts") or "DATA NOT AVAILABLE"
    dvt_delay = dvt.get("delay_hours")
    dvt_flag = dvt.get("delay_flag_24h")
    dvt_excluded = dvt.get("excluded_reason") or "none"
    pharm_ev = dvt.get("evidence", {}).get("pharm", [])
    mech_ev = dvt.get("evidence", {}).get("mech", [])
    excl_ev = dvt.get("evidence", {}).get("exclusion", [])
    orders_only_count = dvt.get("orders_only_count", 0)
    pharm_admin_count = dvt.get("pharm_admin_evidence_count", 0)
    pharm_ambig_count = dvt.get("pharm_ambiguous_mention_count", 0)
    mech_admin_count = dvt.get("mech_admin_evidence_count", 0)
    print(f"  pharm_first_ts (chemical): {dvt_pharm_ts}")
    print(f"  mech_first_ts (informational): {dvt_mech_ts}")
    print(f"  delay_hours (pharm): {dvt_delay if dvt_delay is not None else 'DATA NOT AVAILABLE'}")
    print(f"  delay_flag_24h (pharm): {dvt_flag if dvt_flag is not None else 'DATA NOT AVAILABLE'}")
    print(f"  excluded_reason: {dvt_excluded}")
    print(f"  pharm_admin_evidence_count: {pharm_admin_count}")
    print(f"  pharm_ambiguous_mention_count: {pharm_ambig_count}")
    print(f"  mech_admin_evidence_count: {mech_admin_count}")
    print(f"  orders_only_count: {orders_only_count}")
    print(f"  exclusion_count: {len(excl_ev)}")
    if pharm_ev:
        print("  pharm evidence (top 3):")
        for ev in pharm_ev[:3]:
            print(f"    [{ev.get('ts', 'no_ts')}] {ev.get('snippet', '')[:80]}")
    if mech_ev:
        print("  mech evidence (top 3, confirmed):")
        for ev in mech_ev[:3]:
            print(f"    [{ev.get('ts', 'no_ts')}] {ev.get('snippet', '')[:80]}")
    if orders_only_count:
        print(f"  NOTE: {orders_only_count} SCD order-only entries excluded (no admin evidence)")
    print()

    # ── GI Prophylaxis v1 QA ────────────────────────────────────
    gi = feats.get("gi_prophylaxis_v1", {})
    print("GI PROPHYLAXIS v1 QA (first admin timing):")
    gi_pharm_ts = gi.get("pharm_first_ts") or "DATA NOT AVAILABLE"
    gi_delay = gi.get("delay_hours")
    gi_flag = gi.get("delay_flag_48h")
    gi_excluded = gi.get("excluded_reason") or "none"
    gi_pharm_ev = gi.get("evidence", {}).get("pharm", [])
    gi_excl_ev = gi.get("evidence", {}).get("exclusion", [])
    gi_orders_only_count = gi.get("orders_only_count", 0)
    gi_pharm_admin_count = gi.get("pharm_admin_evidence_count", 0)
    gi_pharm_ambig_count = gi.get("pharm_ambiguous_mention_count", 0)
    print(f"  pharm_first_ts: {gi_pharm_ts}")
    print(f"  delay_hours: {gi_delay if gi_delay is not None else 'DATA NOT AVAILABLE'}")
    print(f"  delay_flag_48h: {gi_flag if gi_flag is not None else 'DATA NOT AVAILABLE'}")
    print(f"  excluded_reason: {gi_excluded}")
    print(f"  pharm_admin_evidence_count: {gi_pharm_admin_count}")
    print(f"  pharm_ambiguous_mention_count: {gi_pharm_ambig_count}")
    print(f"  orders_only_count: {gi_orders_only_count}")
    print(f"  exclusion_count: {len(gi_excl_ev)}")
    if gi_pharm_ev:
        print("  pharm evidence (top 3):")
        for ev in gi_pharm_ev[:3]:
            print(f"    [{ev.get('ts', 'no_ts')}] {ev.get('snippet', '')[:80]}")
    if gi_orders_only_count:
        print(f"  NOTE: {gi_orders_only_count} order-only entries excluded (no admin evidence)")
    print()

    # ── Base Deficit Monitoring v1 QA ───────────────────────────
    bdm = feats.get("base_deficit_monitoring_v1", {})
    print("BASE DEFICIT MONITORING v1 QA:")
    bdm_init_ts = bdm.get("initial_bd_ts") or "DATA NOT AVAILABLE"
    bdm_init_val = bdm.get("initial_bd_value")
    bdm_init_src = bdm.get("initial_bd_source") or "unknown"
    bdm_cat1_valid = bdm.get("category1_bd_validated")
    bdm_valid_reason = bdm.get("validation_failure_reason")
    bdm_trigger = bdm.get("trigger_bd_gt4")
    bdm_compliant = bdm.get("overall_compliant")
    bdm_series = bdm.get("bd_series", [])
    bdm_windows = bdm.get("monitoring_windows", [])
    bdm_notes = bdm.get("notes", [])
    bdm_nc = bdm.get("noncompliance_reasons", [])
    print(f"  initial_bd_ts: {bdm_init_ts}")
    print(f"  initial_bd_value: {bdm_init_val if bdm_init_val is not None else 'DATA NOT AVAILABLE'}")
    print(f"  initial_bd_source: {bdm_init_src}")
    print(f"  category1_bd_validated: {bdm_cat1_valid if bdm_cat1_valid is not None else 'DATA NOT AVAILABLE'}")
    if bdm_valid_reason:
        print(f"  validation_failure_reason: {bdm_valid_reason}")
    print(f"  trigger_bd_gt4: {bdm_trigger if bdm_trigger is not None else 'DATA NOT AVAILABLE'}")
    print(f"  overall_compliant: {bdm_compliant if bdm_compliant is not None else 'DATA NOT AVAILABLE'}")
    print(f"  bd_series_count: {len(bdm_series)}")
    for w in bdm_windows:
        phase = w.get("phase", "?")
        mg = w.get("max_gap_hours")
        mg_str = f"{mg:.1f}" if mg is not None else "N/A"
        v_count = len(w.get("violations", []))
        print(f"  window: {phase}  max_gap_hours={mg_str}  violations={v_count}  compliant={w.get('compliant')}")
    if bdm_nc:
        print(f"  noncompliance_reasons ({len(bdm_nc)}):")
        for r in bdm_nc[:5]:
            print(f"    - {r}")
    if bdm_notes:
        for n in bdm_notes:
            print(f"  note: {n}")
    print()

    # ── INR Normalization v1 QA ─────────────────────────────────
    inr = feats.get("inr_normalization_v1", {})
    print("INR NORMALIZATION v1 QA:")
    inr_init_ts = inr.get("initial_inr_ts") or "DATA NOT AVAILABLE"
    inr_init_val = inr.get("initial_inr_value")
    inr_count = inr.get("inr_count", 0)
    inr_series = inr.get("inr_series", [])
    inr_warns = inr.get("parse_warnings", [])
    inr_notes = inr.get("notes", [])
    print(f"  initial_inr_ts: {inr_init_ts}")
    print(f"  initial_inr_value: {inr_init_val if inr_init_val is not None else 'DATA NOT AVAILABLE'}")
    print(f"  initial_inr_source_lab: {inr.get('initial_inr_source_lab') or 'DATA NOT AVAILABLE'}")
    print(f"  inr_count: {inr_count}")
    if inr_series:
        print("  inr_series (first 3):")
        for e in inr_series[:3]:
            print(f"    [{e.get('ts', 'no_ts')}] value={e.get('inr_value')} lab={e.get('source_lab')}")
    if inr_warns:
        print(f"  parse_warnings ({len(inr_warns)}):")
        for w in inr_warns[:5]:
            print(f"    - {w}")
    if inr_notes:
        for n in inr_notes:
            print(f"  note: {n}")
    print()

    # ── FAST Exam v1 QA ────────────────────────────────────────
    fast = feats.get("fast_exam_v1", {})
    print("FAST EXAM v1 QA:")
    fast_performed = fast.get("fast_performed") or "DATA NOT AVAILABLE"
    fast_result = fast.get("fast_result")
    fast_ts = fast.get("fast_ts") or "DATA NOT AVAILABLE"
    fast_source = fast.get("fast_source") or "DATA NOT AVAILABLE"
    fast_rule = fast.get("fast_source_rule_id") or "none"
    fast_raw = fast.get("fast_raw_text") or "DATA NOT AVAILABLE"
    fast_evidence = fast.get("evidence", [])
    fast_notes = fast.get("notes", [])
    fast_warns = fast.get("warnings", [])
    print(f"  fast_performed: {fast_performed}")
    print(f"  fast_result: {fast_result if fast_result is not None else 'DATA NOT AVAILABLE'}")
    print(f"  fast_ts: {fast_ts}")
    print(f"  fast_source: {fast_source}")
    print(f"  fast_source_rule_id: {fast_rule}")
    print(f"  fast_raw_text: {fast_raw}")
    print(f"  evidence_count: {len(fast_evidence)}")
    if fast_evidence:
        for ev in fast_evidence[:3]:
            print(f"    [{ev.get('ts', 'no_ts')}] {ev.get('snippet', '')[:80]}")
    if fast_warns:
        print(f"  warnings ({len(fast_warns)}):")
        for w in fast_warns[:5]:
            print(f"    - {w}")
    if fast_notes:
        for n in fast_notes:
            print(f"  note: {n}")
    print()

    # ── ETOH + UDS v1 QA ───────────────────────────────────────
    eu = feats.get("etoh_uds_v1", {})
    print("ETOH + UDS v1 QA:")
    eu_etoh_val = eu.get("etoh_value")
    eu_etoh_raw = eu.get("etoh_value_raw")
    eu_etoh_ts = eu.get("etoh_ts") or "DATA NOT AVAILABLE"
    eu_etoh_ts_val = eu.get("etoh_ts_validation") or "DATA NOT AVAILABLE"
    eu_etoh_rule = eu.get("etoh_source_rule_id") or "none"
    print(f"  etoh_value: {eu_etoh_val if eu_etoh_val is not None else 'DATA NOT AVAILABLE'}")
    print(f"  etoh_value_raw: {eu_etoh_raw if eu_etoh_raw is not None else 'DATA NOT AVAILABLE'}")
    print(f"  etoh_ts: {eu_etoh_ts}")
    print(f"  etoh_ts_validation: {eu_etoh_ts_val}")
    print(f"  etoh_source_rule_id: {eu_etoh_rule}")

    eu_uds_perf = eu.get("uds_performed") or "DATA NOT AVAILABLE"
    eu_uds_ts = eu.get("uds_ts") or "DATA NOT AVAILABLE"
    eu_uds_ts_val = eu.get("uds_ts_validation") or "DATA NOT AVAILABLE"
    eu_uds_rule = eu.get("uds_source_rule_id") or "none"
    eu_uds_panel = eu.get("uds_panel")
    print(f"  uds_performed: {eu_uds_perf}")
    print(f"  uds_ts: {eu_uds_ts}")
    print(f"  uds_ts_validation: {eu_uds_ts_val}")
    print(f"  uds_source_rule_id: {eu_uds_rule}")
    if eu_uds_panel and isinstance(eu_uds_panel, dict):
        print("  uds_panel:")
        for analyte in ("thc", "cocaine", "opiates", "benzodiazepines",
                        "barbiturates", "amphetamines", "phencyclidine"):
            val = eu_uds_panel.get(analyte)
            print(f"    {analyte}: {val if val is not None else 'DATA NOT AVAILABLE'}")
    else:
        print("  uds_panel: DATA NOT AVAILABLE")

    eu_evidence = eu.get("evidence", [])
    eu_warns = eu.get("warnings", [])
    eu_notes = eu.get("notes", [])
    print(f"  evidence_count: {len(eu_evidence)}")
    if eu_evidence:
        for ev in eu_evidence[:5]:
            print(f"    [{ev.get('ts', 'no_ts')}] {ev.get('snippet', '')[:80]}")
    if eu_warns:
        print(f"  warnings ({len(eu_warns)}):")
        for w in eu_warns[:5]:
            print(f"    - {w}")
    if eu_notes:
        for n in eu_notes:
            print(f"  note: {n}")
    print()

    # ── Shock Trigger v1 QA ─────────────────────────────────────
    st = feats.get("shock_trigger_v1", {})
    print("SHOCK TRIGGER v1 QA:")
    st_triggered = st.get("shock_triggered") or "DATA NOT AVAILABLE"
    st_rule = st.get("trigger_rule_id") or "none"
    st_ts = st.get("trigger_ts") or "DATA NOT AVAILABLE"
    st_type = st.get("shock_type") or "none"
    st_vitals = st.get("trigger_vitals") or {}
    st_evidence = st.get("evidence", [])
    st_notes = st.get("notes", [])
    st_warns = st.get("warnings", [])
    print(f"  shock_triggered: {st_triggered}")
    print(f"  trigger_rule_id: {st_rule}")
    print(f"  trigger_ts: {st_ts}")
    print(f"  shock_type: {st_type}")
    if st_vitals:
        print(f"  trigger_vitals: SBP={st_vitals.get('sbp')}, "
              f"MAP={st_vitals.get('map')}, "
              f"BD={st_vitals.get('bd_value')}, "
              f"specimen={st_vitals.get('bd_specimen')}")
    print(f"  evidence_count: {len(st_evidence)}")
    if st_evidence:
        for ev in st_evidence[:5]:
            print(f"    [{ev.get('ts', 'no_ts')}] ({ev.get('role', '?')}) "
                  f"{ev.get('snippet', '')[:80]}")
    if st_warns:
        print(f"  warnings ({len(st_warns)}):")
        for w in st_warns[:5]:
            print(f"    - {w}")
    if st_notes:
        for n in st_notes:
            print(f"  note: {n}")
    print()

    # ── Neuro Trigger v1 QA ─────────────────────────────────────
    nt = feats.get("neuro_trigger_v1", {})
    print("NEURO TRIGGER v1 QA:")
    nt_triggered = nt.get("neuro_triggered") or "DATA NOT AVAILABLE"
    nt_rule = nt.get("trigger_rule_id") or "none"
    nt_ts = nt.get("trigger_ts") or "DATA NOT AVAILABLE"
    nt_inputs = nt.get("trigger_inputs") or {}
    nt_evidence = nt.get("evidence", [])
    nt_notes = nt.get("notes", [])
    nt_warns = nt.get("warnings", [])
    print(f"  neuro_triggered: {nt_triggered}")
    print(f"  trigger_rule_id: {nt_rule}")
    print(f"  trigger_ts: {nt_ts}")
    if nt_inputs:
        print(f"  trigger_inputs: GCS={nt_inputs.get('arrival_gcs_value')}, "
              f"source={nt_inputs.get('arrival_gcs_source')}, "
              f"rule={nt_inputs.get('arrival_gcs_source_rule_id')}, "
              f"intubated={nt_inputs.get('arrival_gcs_intubated')}")
    print(f"  evidence_count: {len(nt_evidence)}")
    if nt_evidence:
        for ev in nt_evidence[:5]:
            print(f"    [{ev.get('ts', 'no_ts')}] ({ev.get('role', '?')}) "
                  f"{ev.get('snippet', '')[:80]}")
    if nt_warns:
        print(f"  warnings ({len(nt_warns)}):")
        for w in nt_warns[:5]:
            print(f"    - {w}")
    if nt_notes:
        for n in nt_notes:
            print(f"  note: {n}")
    print()

    # ── Age Extraction v1 QA ───────────────────────────────────
    ae = feats.get("age_extraction_v1", {})
    print("AGE EXTRACTION v1 QA:")
    ae_avail = ae.get("age_available") or "DATA NOT AVAILABLE"
    ae_years = ae.get("age_years")
    ae_rule = ae.get("age_source_rule_id") or "none"
    ae_src = ae.get("age_source_text") or "DATA NOT AVAILABLE"
    ae_dob = ae.get("dob_iso") or "none"
    ae_evidence = ae.get("evidence", [])
    ae_notes = ae.get("notes", [])
    ae_warns = ae.get("warnings", [])
    print(f"  age_available: {ae_avail}")
    print(f"  age_years: {ae_years if ae_years is not None else 'DATA NOT AVAILABLE'}")
    print(f"  age_source_rule_id: {ae_rule}")
    print(f"  age_source_text: {ae_src}")
    print(f"  dob_iso: {ae_dob}")
    print(f"  evidence_count: {len(ae_evidence)}")
    if ae_evidence:
        for ev in ae_evidence[:3]:
            print(f"    [{ev.get('ts', 'no_ts')}] ({ev.get('role', '?')}) "
                  f"{ev.get('snippet', '')[:80]}")
    if ae_warns:
        print(f"  warnings ({len(ae_warns)}):")
        for w in ae_warns[:5]:
            print(f"    - {w}")
    if ae_notes:
        for n in ae_notes:
            print(f"  note: {n}")
    print()

    # ── Mechanism + Body Region v1 QA ───────────────────────────
    mr = feats.get("mechanism_region_v1", {})
    print("MECHANISM + BODY REGION v1 QA:")
    mr_mech_present = mr.get("mechanism_present") or "DATA NOT AVAILABLE"
    mr_mech_primary = mr.get("mechanism_primary") or "none"
    mr_mech_labels = mr.get("mechanism_labels", [])
    mr_penetrating = mr.get("penetrating_mechanism")
    mr_region_present = mr.get("body_region_present") or "DATA NOT AVAILABLE"
    mr_region_labels = mr.get("body_region_labels", [])
    mr_rule = mr.get("source_rule_id") or "none"
    mr_evidence = mr.get("evidence", [])
    mr_notes = mr.get("notes", [])
    mr_warns = mr.get("warnings", [])
    print(f"  mechanism_present: {mr_mech_present}")
    print(f"  mechanism_primary: {mr_mech_primary}")
    print(f"  mechanism_labels: {mr_mech_labels}")
    print(f"  penetrating_mechanism: {mr_penetrating if mr_penetrating is not None else 'DATA NOT AVAILABLE'}")
    print(f"  body_region_present: {mr_region_present}")
    print(f"  body_region_labels: {mr_region_labels}")
    print(f"  source_rule_id: {mr_rule}")
    print(f"  evidence_count: {len(mr_evidence)}")
    if mr_evidence:
        mech_ev = [e for e in mr_evidence if e.get("role") == "mechanism"]
        region_ev = [e for e in mr_evidence if e.get("role") == "body_region"]
        if mech_ev:
            print(f"  mechanism evidence ({len(mech_ev)}):")
            for ev in mech_ev[:5]:
                print(f"    [{ev.get('label', '?')}] {ev.get('snippet', '')[:80]}")
        if region_ev:
            print(f"  body_region evidence ({len(region_ev)}):")
            for ev in region_ev[:5]:
                print(f"    [{ev.get('label', '?')}] {ev.get('snippet', '')[:80]}")
    if mr_warns:
        print(f"  warnings ({len(mr_warns)}):")
        for w in mr_warns[:5]:
            print(f"    - {w}")
    if mr_notes:
        for n in mr_notes[:5]:
            print(f"  note: {n}")
    print()

    # ── Radiology Findings v1 QA ────────────────────────────────
    rf = feats.get("radiology_findings_v1", {})
    print("RADIOLOGY FINDINGS v1 QA:")
    rf_present = rf.get("findings_present") or "DATA NOT AVAILABLE"
    rf_labels = rf.get("findings_labels", [])
    rf_rule = rf.get("source_rule_id") or "none"
    rf_evidence = rf.get("evidence", [])
    rf_notes = rf.get("notes", [])
    rf_warns = rf.get("warnings", [])
    print(f"  findings_present: {rf_present}")
    print(f"  findings_labels: {rf_labels}")
    print(f"  source_rule_id: {rf_rule}")

    # Pneumothorax
    rf_ptx = rf.get("pneumothorax")
    if rf_ptx:
        print(f"  pneumothorax: present={rf_ptx.get('present')} subtype={rf_ptx.get('subtype')}")

    # Hemothorax
    rf_htx = rf.get("hemothorax")
    if rf_htx:
        print(f"  hemothorax: present={rf_htx.get('present')} qualifier={rf_htx.get('qualifier')}")

    # Rib fracture
    rf_rib = rf.get("rib_fracture")
    if rf_rib:
        print(f"  rib_fracture: present={rf_rib.get('present')} count={rf_rib.get('count')} ribs={rf_rib.get('rib_numbers')} laterality={rf_rib.get('laterality')}")

    # Flail chest
    rf_flail = rf.get("flail_chest")
    if rf_flail:
        print(f"  flail_chest: present={rf_flail.get('present')}")

    # Solid organ injuries
    rf_soi = rf.get("solid_organ_injuries", [])
    if rf_soi:
        print(f"  solid_organ_injuries ({len(rf_soi)}):")
        for soi in rf_soi:
            print(f"    {soi.get('organ')}: grade={soi.get('grade')}")

    # Intracranial hemorrhage
    rf_ich = rf.get("intracranial_hemorrhage", [])
    if rf_ich:
        print(f"  intracranial_hemorrhage ({len(rf_ich)}):")
        for ich in rf_ich:
            print(f"    subtype={ich.get('subtype')}")

    # Pelvic fracture
    rf_pelvic = rf.get("pelvic_fracture")
    if rf_pelvic:
        print(f"  pelvic_fracture: present={rf_pelvic.get('present')}")

    # Spinal fracture
    rf_spinal = rf.get("spinal_fracture")
    if rf_spinal:
        print(f"  spinal_fracture: present={rf_spinal.get('present')} level={rf_spinal.get('level')}")

    print(f"  evidence_count: {len(rf_evidence)}")
    if rf_evidence:
        for ev in rf_evidence[:5]:
            print(f"    [{ev.get('ts', 'no_ts')}] ({ev.get('role', '?')}/{ev.get('label', '?')}) "
                  f"{ev.get('snippet', '')[:80]}")
    if rf_warns:
        print(f"  warnings ({len(rf_warns)}):")
        for w in rf_warns[:5]:
            print(f"    - {w}")
    if rf_notes:
        for n in rf_notes[:5]:
            print(f"  note: {n}")
    print()

    # ── SBIRT Screening v1 QA ──────────────────────────────────
    sb = feats.get("sbirt_screening_v1", {})
    print("SBIRT SCREENING v1 QA:")
    sb_present = sb.get("sbirt_screening_present") or "DATA NOT AVAILABLE"
    sb_evidence = sb.get("evidence", [])
    sb_notes = sb.get("notes", [])
    sb_warns = sb.get("warnings", [])
    print(f"  sbirt_screening_present: {sb_present}")
    sb_instruments = sb.get("instruments_detected", [])
    if sb_instruments:
        print(f"  instruments_detected: {', '.join(sb_instruments)}")

    # AUDIT-C
    sb_audit = sb.get("audit_c", {})
    if sb_audit:
        print(f"  audit_c:")
        print(f"    explicit_score: {sb_audit.get('explicit_score')}")
        print(f"    responses_present: {sb_audit.get('responses_present')}")
        print(f"    completion_status: {sb_audit.get('completion_status')}")
        sb_audit_resp = sb_audit.get("responses", [])
        if sb_audit_resp:
            for r in sb_audit_resp[:5]:
                print(f"    response: q={r.get('question','?')[:40]} "
                      f"a={r.get('answer','?')[:30]}")
    else:
        print("  audit_c: null")

    # DAST-10
    sb_dast = sb.get("dast_10", {})
    if sb_dast:
        print(f"  dast_10:")
        print(f"    explicit_score: {sb_dast.get('explicit_score')}")
        print(f"    responses_present: {sb_dast.get('responses_present')}")
        print(f"    completion_status: {sb_dast.get('completion_status')}")
        sb_dast_resp = sb_dast.get("responses", [])
        if sb_dast_resp:
            for r in sb_dast_resp[:5]:
                print(f"    response: q={r.get('question','?')[:40]} "
                      f"a={r.get('answer','?')[:30]}")
    else:
        print("  dast_10: null")

    # CAGE
    sb_cage = sb.get("cage", {})
    if sb_cage:
        print(f"  cage:")
        print(f"    explicit_score: {sb_cage.get('explicit_score')}")
        print(f"    responses_present: {sb_cage.get('responses_present')}")
        print(f"    completion_status: {sb_cage.get('completion_status')}")
    else:
        print("  cage: null")

    # Flowsheet responses
    sb_flow = sb.get("flowsheet_responses", [])
    if sb_flow:
        print(f"  flowsheet_responses: {len(sb_flow)} entries")
        for fr in sb_flow[:5]:
            print(f"    q={fr.get('question','?')[:40]} a={fr.get('answer','?')[:20]}")

    # Refusal / Admission
    print(f"  refusal_documented: {sb.get('refusal_documented', False)}")
    print(f"  substance_use_admission_documented: "
          f"{sb.get('substance_use_admission_documented', False)}")

    print(f"  evidence_count: {len(sb_evidence)}")
    if sb_evidence:
        for ev in sb_evidence[:5]:
            print(f"    [{ev.get('ts', 'no_ts')}] ({ev.get('role', '?')}/{ev.get('label', '?')}) "
                  f"{ev.get('snippet', '')[:80]}")
    if sb_warns:
        print(f"  warnings ({len(sb_warns)}):")
        for w in sb_warns[:5]:
            print(f"    - {w}")
    if sb_notes:
        for n in sb_notes[:5]:
            print(f"  note: {n}")
    print()

    # ── Impression/Plan Drift v1 QA ─────────────────────────────
    ipd = feats.get("impression_plan_drift_v1", {})
    print("IMPRESSION/PLAN DRIFT v1 QA:")
    ipd_detected = ipd.get("drift_detected")
    ipd_days_compared = ipd.get("days_compared_count", 0)
    ipd_days_with = ipd.get("days_with_impression_count", 0)
    ipd_events = ipd.get("drift_events", [])
    ipd_evidence = ipd.get("evidence", [])
    ipd_notes = ipd.get("notes", [])
    ipd_warns = ipd.get("warnings", [])
    print(f"  drift_detected: {ipd_detected if ipd_detected is not None else 'DATA NOT AVAILABLE'}")
    print(f"  days_with_impression_count: {ipd_days_with}")
    print(f"  days_compared_count: {ipd_days_compared}")
    print(f"  drift_event_count: {len(ipd_events)}")
    print(f"  evidence_count: {len(ipd_evidence)}")
    if ipd_events:
        print("  drift events:")
        for ev in ipd_events:
            added = len(ev.get("added_items", []))
            removed = len(ev.get("removed_items", []))
            persisted = ev.get("persisted_count", 0)
            ratio = ev.get("drift_ratio", 0)
            print(f"    {ev.get('prev_date', '?')}->{ev.get('date', '?')}: "
                  f"added={added} removed={removed} "
                  f"persisted={persisted} ratio={ratio:.4f}")
    if ipd_warns:
        print(f"  warnings ({len(ipd_warns)}):")
        for w in ipd_warns[:5]:
            print(f"    - {w}")
    if ipd_notes:
        for n in ipd_notes:
            print(f"  note: {n}")
    print()

    # ── Note Sections v1 QA ────────────────────────────────────
    ns = feats.get("note_sections_v1", {})
    print("NOTE SECTIONS v1 QA:")
    ns_present = ns.get("sections_present")
    if ns_present is None:
        ns_present = "DATA NOT AVAILABLE"
    ns_src = ns.get("source_type") or "none"
    ns_rule = ns.get("source_rule_id") or "none"
    ns_ts = ns.get("source_ts") or "none"
    print(f"  sections_present: {ns_present}")
    print(f"  source_type: {ns_src}")
    print(f"  source_rule_id: {ns_rule}")
    print(f"  source_ts: {ns_ts}")

    for sec_name in ("hpi", "primary_survey", "secondary_survey", "impression", "plan"):
        sec = ns.get(sec_name, {})
        sec_present = sec.get("present", False)
        sec_lines = sec.get("line_count", 0)
        sec_text_len = len(sec.get("text") or "")
        label = f"  {sec_name}: present={sec_present}  lines={sec_lines}  chars={sec_text_len}"
        print(label)
        if sec_name == "primary_survey" and sec_present:
            fields = sec.get("fields", {})
            for fld in ("airway", "breathing", "circulation", "disability", "exposure", "fast"):
                fval = fields.get(fld)
                if fval:
                    print(f"    {fld}: {fval[:80]}")
                else:
                    print(f"    {fld}: null")

    ns_evidence = ns.get("evidence", [])
    print(f"  evidence_count: {len(ns_evidence)}")
    if ns_evidence:
        for ev in ns_evidence[:6]:
            print(f"    [{ev.get('section', '?')}] {ev.get('snippet', '')[:80]}")

    ns_warns = ns.get("warnings", [])
    ns_notes = ns.get("notes", [])
    if ns_warns:
        print(f"  warnings ({len(ns_warns)}):")
        for w in ns_warns[:5]:
            print(f"    - {w}")
    if ns_notes:
        for n in ns_notes[:5]:
            print(f"  note: {n}")
    print()

    # ── Incentive Spirometry v1 QA ────────────────────────────
    isp = feats.get("incentive_spirometry_v1", {})
    print("INCENTIVE SPIROMETRY v1 QA:")
    isp_mentioned = isp.get("is_mentioned") or "DATA NOT AVAILABLE"
    isp_value = isp.get("is_value_present", "no")
    isp_mention_count = isp.get("mention_count", 0)
    isp_order_count = isp.get("order_count", 0)
    isp_meas_count = isp.get("measurement_count", 0)
    isp_goals = isp.get("goals", [])
    isp_evidence = isp.get("evidence", [])
    isp_notes = isp.get("notes", [])
    isp_warns = isp.get("warnings", [])
    isp_rule = isp.get("source_rule_id") or "none"
    print(f"  is_mentioned: {isp_mentioned}")
    print(f"  is_value_present: {isp_value}")
    print(f"  mention_count: {isp_mention_count}")
    print(f"  order_count: {isp_order_count}")
    print(f"  measurement_count: {isp_meas_count}")
    print(f"  source_rule_id: {isp_rule}")
    # Mention type breakdown
    isp_type_counts = isp.get("mention_type_counts", {})
    if isp_type_counts:
        parts = ", ".join(f"{k}={v}" for k, v in sorted(isp_type_counts.items()))
        print(f"  mention_types: {parts}")
    # Orders
    if isp_order_count > 0:
        for o in isp.get("orders", [])[:5]:
            freq = o.get("frequency", "?")
            onum = o.get("order_number", "?")
            ost = o.get("status", "active")
            print(f"    order: freq={freq} order_num={onum} status={ost}")
    # Goals
    if isp_goals:
        for g in isp_goals:
            print(f"    goal: {g.get('value')} {g.get('unit', 'cc')}")
    # Measurements summary
    if isp_meas_count > 0:
        for m in isp.get("measurements", [])[:5]:
            vol = m.get("largest_volume_cc", "?")
            eff = m.get("patient_effort", "?")
            ts = m.get("ts", "?")
            print(f"    measurement: ts={ts} largest_vol={vol}cc effort={eff}")
        if isp_meas_count > 5:
            print(f"    ... and {isp_meas_count - 5} more")
    # Evidence
    print(f"  evidence_count: {len(isp_evidence)}")
    if isp_evidence:
        for ev in isp_evidence[:5]:
            print(f"    [{ev.get('ts', 'no_ts')}] ({ev.get('label', '?')}) "
                  f"{ev.get('snippet', '')[:80]}")
    if isp_warns:
        print(f"  warnings ({len(isp_warns)}):")
        for w in isp_warns[:5]:
            print(f"    - {w}")
    if isp_notes:
        for n in isp_notes[:5]:
            print(f"  note: {n}")
    print()

    # ── Hemodynamic Instability Pattern v1 QA ──────────────────
    hip = feats.get("hemodynamic_instability_pattern_v1", {})
    print("HEMODYNAMIC INSTABILITY PATTERN v1 QA:")
    hip_present = hip.get("pattern_present") or "DATA NOT AVAILABLE"
    hip_patterns = hip.get("patterns_detected", [])
    hip_total_abnormal = hip.get("total_abnormal_readings", 0)
    hip_total_vitals = hip.get("total_vitals_readings", 0)
    hip_rule = hip.get("source_rule_id") or "none"
    hip_evidence = hip.get("evidence", [])
    hip_notes = hip.get("notes", [])
    hip_warns = hip.get("warnings", [])
    print(f"  pattern_present: {hip_present}")
    print(f"  patterns_detected: {hip_patterns}")
    print(f"  total_abnormal_readings: {hip_total_abnormal}")
    print(f"  total_vitals_readings: {hip_total_vitals}")
    print(f"  source_rule_id: {hip_rule}")

    # Hypotension sub-pattern
    hip_hypo = hip.get("hypotension_pattern", {})
    if hip_hypo:
        print(f"  hypotension_pattern: detected={hip_hypo.get('detected')} "
              f"count={hip_hypo.get('reading_count')} "
              f"days={hip_hypo.get('days_affected')}")

    # MAP low sub-pattern
    hip_map = hip.get("map_low_pattern", {})
    if hip_map:
        print(f"  map_low_pattern: detected={hip_map.get('detected')} "
              f"count={hip_map.get('reading_count')} "
              f"days={hip_map.get('days_affected')}")

    # Tachycardia sub-pattern
    hip_tachy = hip.get("tachycardia_pattern", {})
    if hip_tachy:
        print(f"  tachycardia_pattern: detected={hip_tachy.get('detected')} "
              f"count={hip_tachy.get('reading_count')} "
              f"days={hip_tachy.get('days_affected')}")

    print(f"  evidence_count: {len(hip_evidence)}")
    if hip_evidence:
        for ev in hip_evidence[:8]:
            print(f"    [{ev.get('ts', 'no_ts')}] ({ev.get('pattern', '?')}) "
                  f"{ev.get('snippet', '')[:80]}")
    if hip_warns:
        print(f"  warnings ({len(hip_warns)}):")
        for w in hip_warns[:5]:
            print(f"    - {w}")
    if hip_notes:
        for n in hip_notes[:5]:
            print(f"  note: {n}")
    print()

    # ── Anticoagulation Context v1 QA ──────────────────────────
    ac = feats.get("anticoag_context_v1", {})
    print("ANTICOAG CONTEXT v1 QA:")
    ac_present = ac.get("anticoag_present") or "DATA NOT AVAILABLE"
    ap_present = ac.get("antiplatelet_present") or "DATA NOT AVAILABLE"
    ac_count = ac.get("anticoag_count", 0)
    ap_count = ac.get("antiplatelet_count", 0)
    ac_rule = ac.get("source_rule_id") or "none"
    ac_evidence = ac.get("evidence", [])
    ac_notes = ac.get("notes", [])
    ac_warns = ac.get("warnings", [])
    print(f"  anticoag_present: {ac_present}")
    print(f"  antiplatelet_present: {ap_present}")
    print(f"  home_anticoagulants: {ac_count}")
    print(f"  home_antiplatelets: {ap_count}")
    print(f"  source_rule_id: {ac_rule}")

    # List home anticoagulants
    for drug in ac.get("home_anticoagulants", []):
        disc_flag = " [DISCONTINUED]" if drug.get("discontinued") else ""
        print(f"    anticoag: {drug.get('normalized_name', '?')} "
              f"({drug.get('class', '?')}){disc_flag}"
              f"{' dose=' + drug['dose'] if drug.get('dose') else ''}")

    # List home antiplatelets
    for drug in ac.get("home_antiplatelets", []):
        disc_flag = " [DISCONTINUED]" if drug.get("discontinued") else ""
        print(f"    antiplatelet: {drug.get('normalized_name', '?')} "
              f"({drug.get('class', '?')}){disc_flag}"
              f"{' dose=' + drug['dose'] if drug.get('dose') else ''}")

    print(f"  evidence_count: {len(ac_evidence)}")
    if ac_evidence:
        for ev in ac_evidence[:8]:
            print(f"    [{ev.get('role', '?')}] {ev.get('snippet', '')[:80]}")
    if ac_warns:
        print(f"  warnings ({len(ac_warns)}):")
        for w in ac_warns[:5]:
            print(f"    - {w}")
    if ac_notes:
        for n in ac_notes[:5]:
            print(f"  note: {n}")
    print()

    # ── PMH / Social / Allergies v1 QA ────────────────────────
    psa = feats.get("pmh_social_allergies_v1", {})
    print("PMH / SOCIAL / ALLERGIES v1 QA:")
    psa_pmh_count = psa.get("pmh_count", 0)
    psa_allergy_count = psa.get("allergy_count", 0)
    psa_allergy_status = psa.get("allergy_status") or "DATA NOT AVAILABLE"
    psa_social = psa.get("social_history", {})
    psa_rule = psa.get("source_rule_id") or "none"
    psa_evidence = psa.get("evidence", [])
    psa_notes = psa.get("notes", [])
    psa_warns = psa.get("warnings", [])
    print(f"  pmh_count: {psa_pmh_count}")
    print(f"  allergy_status: {psa_allergy_status}")
    print(f"  allergy_count: {psa_allergy_count}")
    print(f"  source_rule_id: {psa_rule}")

    # List PMH items
    for item in psa.get("pmh_items", [])[:15]:
        sub = f" ({item['sub_comment']})" if item.get('sub_comment') else ''
        print(f"    pmh: {item.get('label', '?')}{sub}")
    if psa_pmh_count > 15:
        print(f"    ... and {psa_pmh_count - 15} more")

    # List allergies
    for item in psa.get("allergies", [])[:10]:
        rxn = f" -> {item['reaction']}" if item.get('reaction') else ''
        print(f"    allergy: {item.get('allergen', '?')}{rxn}")

    # Social history
    if psa_social:
        print(f"  social_history:")
        for k in sorted(psa_social.keys()):
            v = psa_social[k]
            if isinstance(v, dict):
                parts = [f"{v.get('status', '?')}"]
                if v.get("types"):
                    parts.append(f"types={v['types']}")
                if v.get("comment"):
                    parts.append(f"comment={v['comment']}")
                print(f"    {k}: {', '.join(parts)}")
            else:
                print(f"    {k}: {v}")

    print(f"  evidence_count: {len(psa_evidence)}")
    if psa_evidence:
        for ev in psa_evidence[:8]:
            print(f"    [{ev.get('role', '?')}] {ev.get('snippet', '')[:80]}")
    if psa_warns:
        print(f"  warnings ({len(psa_warns)}):")
        for w in psa_warns[:5]:
            print(f"    - {w}")
    if psa_notes:
        for n in psa_notes[:5]:
            print(f"  note: {n}")
    print()

    # ── ADT Transfer Timeline v1 QA ──────────────────────────────
    adt = feats.get("adt_transfer_timeline_v1", {})
    print("ADT TRANSFER TIMELINE v1 QA:")
    adt_summary = adt.get("summary", {})
    print(f"  adt_event_count: {adt_summary.get('adt_event_count', 0)}")
    print(f"  first_admission_ts: {adt_summary.get('first_admission_ts', 'N/A')}")
    print(f"  transfer_count: {adt_summary.get('transfer_count', 0)}")
    print(f"  discharge_ts: {adt_summary.get('discharge_ts', 'N/A')}")
    print(f"  los_hours: {adt_summary.get('los_hours', 'N/A')}")
    units = adt_summary.get("units_visited", [])
    print(f"  units_visited ({len(units)}): {', '.join(units[:10]) if units else 'none'}")
    adt_events = adt.get("events", [])
    if adt_events:
        print(f"  events ({len(adt_events)}):")
        for ev in adt_events[:20]:
            print(
                f"    {ev.get('timestamp_raw', '?'):16s} "
                f"{ev.get('event_type', '?'):16s} "
                f"{ev.get('unit', '?')}"
            )
    adt_evidence = adt.get("evidence", [])
    print(f"  evidence_count: {len(adt_evidence)}")
    adt_warns = adt.get("warnings", [])
    if adt_warns:
        print(f"  warnings ({len(adt_warns)}):")
        for w in adt_warns[:5]:
            print(f"    - {w}")
    adt_notes = adt.get("notes", [])
    if adt_notes:
        for n in adt_notes[:5]:
            print(f"  note: {n}")
    print()

    # ── Procedure / Operative Events v1 QA ───────────────────────
    proc = feats.get("procedure_operatives_v1", {})
    print("PROCEDURE / OPERATIVE EVENTS v1 QA:")
    print(f"  procedure_event_count: {proc.get('procedure_event_count', 0)}")
    print(f"  operative_event_count: {proc.get('operative_event_count', 0)}")
    print(f"  anesthesia_event_count: {proc.get('anesthesia_event_count', 0)}")
    cats = proc.get("categories_present", [])
    print(f"  categories_present: {', '.join(cats) if cats else 'none'}")
    proc_events = proc.get("events", [])
    if proc_events:
        print(f"  events ({len(proc_events)}):")
        for ev in proc_events[:25]:
            label = ev.get("label") or "(no label)"
            ts = ev.get("ts") or "?"
            kind = ev.get("source_kind", "?")
            cat = ev.get("category", "?")
            status = ev.get("status", "")
            ms_count = len(ev.get("milestones", []))
            ms_str = f" milestones={ms_count}" if ms_count else ""
            st_str = f" status={status}" if status else ""
            print(f"    {ts:20s} {kind:28s} [{cat:18s}] {label[:60]}{st_str}{ms_str}")
    proc_evidence = proc.get("evidence", [])
    print(f"  evidence_count: {len(proc_evidence)}")
    proc_warns = proc.get("warnings", [])
    if proc_warns:
        print(f"  warnings ({len(proc_warns)}):")
        for w in proc_warns[:5]:
            print(f"    - {w}")
    proc_notes = proc.get("notes", [])
    if proc_notes:
        for n in proc_notes[:5]:
            print(f"  note: {n}")
    print()

    # ── Anesthesia Case Metrics v1 QA ────────────────────────────
    anes = feats.get("anesthesia_case_metrics_v1", {})
    print("ANESTHESIA CASE METRICS v1 QA:")
    print(f"  case_count: {anes.get('case_count', 0)}")
    print(f"  or_hypothermia_any: {anes.get('or_hypothermia_any')}")
    anes_flags = anes.get("flags", [])
    if anes_flags:
        print(f"  flags: {', '.join(anes_flags)}")
    anes_cases = anes.get("cases", [])
    if anes_cases:
        print(f"  cases ({len(anes_cases)}):")
        for ac in anes_cases[:10]:
            lbl = ac.get("case_label") or "(no label)"
            atype = ac.get("anesthesia_type", "?")
            asa = ac.get("asa_status", "?")
            mal = ac.get("mallampati", "?")
            day = ac.get("case_day", "?")
            hypo = ac.get("or_hypothermia_flag")
            min_t = ac.get("min_temp_f")
            ebl_r = ac.get("ebl_raw")
            temp_str = f" min_temp={min_t}°F" if min_t is not None else ""
            hypo_str = f" hypothermia={hypo}" if hypo is not None else ""
            ebl_str = f" EBL={ebl_r}" if ebl_r and ebl_r != "DATA NOT AVAILABLE" else ""
            # Airway summary
            aw = ac.get("airway", {})
            if aw:
                aw_dev = aw.get("device") or "?"
                aw_sz = aw.get("size") or "?"
                aw_diff = aw.get("difficulty") or "?"
                aw_str = f" airway={aw_dev}/{aw_sz}/{aw_diff}"
            else:
                aw_str = ""
            print(
                f"    [{day}] {lbl[:50]} | {atype} ASA={asa} Mallampati={mal}"
                f"{aw_str}{temp_str}{hypo_str}{ebl_str}"
            )
    anes_evidence = anes.get("evidence", [])
    print(f"  evidence_count: {len(anes_evidence)}")
    anes_warns = anes.get("warnings", [])
    if anes_warns:
        print(f"  warnings ({len(anes_warns)}):")
        for w in anes_warns[:5]:
            print(f"    - {w}")
    anes_notes = anes.get("notes", [])
    if anes_notes:
        for n in anes_notes[:5]:
            print(f"  note: {n}")
    print()

    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
