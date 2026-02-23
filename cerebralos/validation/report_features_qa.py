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

    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
