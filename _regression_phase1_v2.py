#!/usr/bin/env python3
"""
Phase 1 Structured Regression Sweep — v2
Outputs per-patient validation boxes in the exact requested format.

What this validates
───────────────────
• Artifact integrity — v3 renderer, green card engine, NTDS engine, and
  protocol engine file hashes are compared to locked baselines.
• Determinism — runs the first patient through the pipeline twice and
  confirms both feature and v4 output hashes are identical.
• Per-patient QA boxes — GCS, vitals, labs, gap, and integrity summaries.

How to run
──────────
    python3 _regression_phase1_v2.py

Requires outputs/ to be populated (run_patient.sh for each patient first,
or let the script run the pipeline automatically).
"""
from __future__ import annotations
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent

# Ensure REPO is on sys.path for imports
import os as _os
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from cerebralos.features.vitals_daily import ABNORMAL_THRESHOLDS, is_abnormal

PATIENTS = ["Anna_Dennis", "William_Simmons", "Timothy_Nachtwey", "Timothy_Cowan"]
DNA = "DATA NOT AVAILABLE"

# Metrics to include in abnormal counts (MAP explicitly included)
ABNORMAL_VITALS_METRICS = ("hr", "sbp", "map", "temp_f", "spo2", "rr")

# ── Baseline protected-file hashes (captured at session start) ──
BASELINE_HASHES = {
    "v3_renderer":       "78ccffe75ccf6f98763f9efa8a8b917e",
    "green_card_init":   None,   # green_card not yet populated
    "green_card_adj":    None,   # green_card not yet populated
    "ntds_engine":       "19a7e89c7c3296193066bba2f5796c6b",
    "protocol_engine":   "82298c298385405ba88c1c2412d9b363",
}
PROTECTED_FILES = {
    "v3_renderer":       REPO / "cerebralos" / "reporting" / "render_trauma_daily_notes_v3.py",
    "green_card_init":   REPO / "cerebralos" / "green_card" / "__init__.py",
    "green_card_adj":    REPO / "cerebralos" / "green_card" / "extract_green_card_adjuncts_v1.py",
    "ntds_engine":       REPO / "cerebralos" / "ntds_logic" / "engine.py",
    "protocol_engine":   REPO / "cerebralos" / "protocol_engine" / "engine.py",
}

# QA thresholds — derived from canonical vitals_daily.ABNORMAL_THRESHOLDS
# (no local duplicate; see ABNORMAL_THRESHOLDS import above)

_NARRATIVE_LAB_KEYWORDS = {
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


def md5_file(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def load_json(path: Path):
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def get_v4_arrival_gcs_line(pat: str) -> str:
    """Read arrival GCS as it appears in v4 rendered output."""
    v4_path = REPO / "outputs" / "reporting" / pat / "TRAUMA_DAILY_NOTES_v4.txt"
    if not v4_path.is_file():
        return DNA
    for line in v4_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("Arrival GCS:"):
            return stripped.replace("Arrival GCS:", "").strip() or DNA
    return DNA


def compute_patient_box(pat: str) -> str:
    features_path = REPO / "outputs" / "features" / pat / "patient_features_v1.json"
    timeline_path = REPO / "outputs" / "timeline" / pat / "patient_days_v1.json"
    features = load_json(features_path)
    timeline = load_json(timeline_path)

    lines = []
    lines.append(f"PATIENT: {pat}")
    lines.append("")

    if features is None:
        lines.append("  ERROR: patient_features_v1.json not found")
        return "\n".join(lines)

    days = features.get("days", {})
    day_keys = sorted(k for k in days if k != "__UNDATED__")

    # ── Arrival GCS (v4 render) ──
    v4_arrival = get_v4_arrival_gcs_line(pat)
    lines.append(f"  Arrival GCS (v4 render): {v4_arrival}")

    # ── Find arrival day GCS data ──
    arrival_gcs_data = None
    for dk in day_keys:
        gcs = days[dk].get("gcs_daily", {})
        if gcs and gcs.get("arrival_gcs") != DNA and gcs.get("arrival_gcs") is not None:
            arrival_gcs_data = gcs
            break
    # If not found, use first day
    if arrival_gcs_data is None and day_keys:
        arrival_gcs_data = days[day_keys[0]].get("gcs_daily", {})

    # ── Arrival GCS value ──
    if arrival_gcs_data:
        arrival_gcs = arrival_gcs_data.get("arrival_gcs", DNA)
        if isinstance(arrival_gcs, dict):
            val = arrival_gcs.get("value", DNA)
            src = arrival_gcs.get("source", "")
            intub_str = " (T)" if arrival_gcs.get("intubated") else ""
            lines.append(f"  Arrival GCS: {val}{intub_str}")
        else:
            lines.append(f"  Arrival GCS: {arrival_gcs}")

        # Best GCS
        best = arrival_gcs_data.get("best_gcs", DNA)
        if isinstance(best, dict):
            lines.append(f"  Best GCS: {best.get('value', DNA)}")
        else:
            lines.append(f"  Best GCS: {best}")

        # Worst GCS
        worst = arrival_gcs_data.get("worst_gcs", DNA)
        if isinstance(worst, dict):
            lines.append(f"  Worst GCS: {worst.get('value', DNA)}")
        else:
            lines.append(f"  Worst GCS: {worst}")

        # GCS Metadata
        lines.append(f"  GCS Metadata:")
        lines.append(f"    arrival_gcs_source: {arrival_gcs_data.get('arrival_gcs_source') or DNA}")
        lines.append(f"    arrival_gcs_missing_in_trauma_hp: {arrival_gcs_data.get('arrival_gcs_missing_in_trauma_hp', DNA)}")

        # Determine if fallback was used
        warnings = arrival_gcs_data.get("warnings", [])
        fallback_used = "arrival_gcs_ed_fallback_used" in warnings
        lines.append(f"    arrival_gcs_fallback_used: {fallback_used}")
        lines.append(f"    arrival_gcs_source_rule_id: {arrival_gcs_data.get('arrival_gcs_source_rule_id') or DNA}")
    else:
        lines.append(f"  Arrival GCS: {DNA}")
        lines.append(f"  Best GCS: {DNA}")
        lines.append(f"  Worst GCS: {DNA}")
        lines.append(f"  GCS Metadata:")
        lines.append(f"    arrival_gcs_source: {DNA}")
        lines.append(f"    arrival_gcs_missing_in_trauma_hp: {DNA}")
        lines.append(f"    arrival_gcs_fallback_used: {DNA}")
        lines.append(f"    arrival_gcs_source_rule_id: {DNA}")

    lines.append("")

    # ── Vitals QA ──
    lines.append(f"  Vitals QA:")
    tabular_total = 0
    tabular_parsed = 0
    tabular_unsupported = 0
    abn_counts = Counter()

    for dk in day_keys:
        vit = days[dk].get("vitals", {})
        vqa = vit.get("vitals_qa", {})
        day_unsup = vqa.get("tabular_note_vitals_unsupported", 0)
        tabular_unsupported += day_unsup
        day_total = vqa.get("vitals_readings_total", 0)
        tabular_total += day_total + day_unsup
        tabular_parsed += day_total

        # Abnormal counts — use enriched source abnormal flag
        for metric in ABNORMAL_VITALS_METRICS:
            sources = vit.get(metric, {}).get("sources", [])
            for src in sources:
                # Prefer pre-computed flag; fallback to canonical threshold
                if src.get("abnormal"):
                    abn_counts[metric] += 1
                    continue
                val = src.get("value")
                if val is not None and is_abnormal(metric, val):
                    abn_counts[metric] += 1

    lines.append(f"    tabular_vitals_lines_total: {tabular_total}")
    lines.append(f"    tabular_vitals_lines_parsed: {tabular_parsed}")
    lines.append(f"    tabular_vitals_lines_unsupported: {tabular_unsupported}")
    total_abnormal = sum(abn_counts.values())
    lines.append(f"    abnormal_readings_count: {total_abnormal}")
    if abn_counts:
        for m in ABNORMAL_VITALS_METRICS:
            if abn_counts.get(m, 0) > 0:
                lines.append(f"      {m}: {abn_counts[m]}")

    lines.append("")

    # ── Labs QA ──
    lines.append(f"  Labs QA:")
    narrative_hit_counts = Counter()
    structured_lab_components = set()

    for dk in day_keys:
        daily = days[dk].get("labs", {}).get("daily", {})
        for comp in daily:
            structured_lab_components.add(comp.lower())

    if timeline:
        tl_days = timeline.get("days") or {}
        for day_iso_t, day_info_t in tl_days.items():
            for item in day_info_t.get("items") or []:
                text = (item.get("payload") or {}).get("text", "")
                item_type = item.get("type", "")
                if item_type == "LAB":
                    continue
                for kw_name, kw_pat in _NARRATIVE_LAB_KEYWORDS.items():
                    if re.search(kw_pat, text, re.IGNORECASE):
                        narrative_hit_counts[kw_name] += 1

    present_but_missing = []
    for kw_name in sorted(_NARRATIVE_LAB_KEYWORDS.keys()):
        if narrative_hit_counts[kw_name] > 0:
            found_structured = False
            for sc in structured_lab_components:
                if kw_name.lower() in sc or sc in kw_name.lower():
                    found_structured = True
                    break
            if not found_structured:
                present_but_missing.append(kw_name)

    total_mentions = sum(narrative_hit_counts.values())
    lines.append(f"    narrative_lab_mentions_detected: {total_mentions}")
    lines.append(f"    narrative_labs_present_but_structured_missing: {len(present_but_missing)}")
    if present_but_missing:
        lines.append(f"      missing: {', '.join(present_but_missing)}")

    lines.append("")

    # ── Gap QA ──
    lines.append(f"  Gap QA:")
    gaps = []
    prev_date_obj = None
    for dk in day_keys:
        try:
            cur = date.fromisoformat(dk)
        except ValueError:
            continue
        if prev_date_obj is not None:
            gap_days = (cur - prev_date_obj).days
            if gap_days > 1:
                gaps.append(gap_days - 1)
        prev_date_obj = cur

    lines.append(f"    evidence_gap_detected: {len(gaps) > 0}")
    lines.append(f"    evidence_gap_count: {len(gaps)}")
    lines.append(f"    max_gap_days: {max(gaps) if gaps else 0}")

    lines.append("")

    # ── Canonical Vitals v1 (informational) ──
    cv1 = features.get("vitals_canonical_v1", {})
    cv1_days = cv1.get("days", {})
    cv1_record_count = sum(d.get("count", 0) for d in cv1_days.values())
    cv1_abnormal_total = sum(d.get("abnormal_total", 0) for d in cv1_days.values())
    lines.append(f"  Canonical Vitals v1:")
    lines.append(f"    record_count: {cv1_record_count}")
    lines.append(f"    abnormal_total: {cv1_abnormal_total}")

    lines.append("")

    # ── DVT Prophylaxis v1 (informational) ──
    dvt = features.get("dvt_prophylaxis_v1", {})
    dvt_pharm_ts = dvt.get("pharm_first_ts") or DNA
    dvt_mech_ts = dvt.get("mech_first_ts") or DNA
    dvt_delay = dvt.get("delay_hours")
    dvt_flag = dvt.get("delay_flag_24h")
    dvt_excluded = dvt.get("excluded_reason") or "none"
    dvt_pharm_admin = dvt.get("pharm_admin_evidence_count", 0)
    dvt_pharm_ambig = dvt.get("pharm_ambiguous_mention_count", 0)
    dvt_mech_admin = dvt.get("mech_admin_evidence_count", 0)
    dvt_orders_only = dvt.get("orders_only_count", 0)
    lines.append(f"  DVT Prophylaxis v1 (chemical-only timing):")
    lines.append(f"    pharm_first_ts (chemical): {dvt_pharm_ts}")
    lines.append(f"    mech_first_ts (informational): {dvt_mech_ts}")
    lines.append(f"    delay_hours (pharm): {dvt_delay if dvt_delay is not None else DNA}")
    lines.append(f"    delay_flag_24h (pharm): {dvt_flag if dvt_flag is not None else DNA}")
    lines.append(f"    excluded_reason: {dvt_excluded}")
    lines.append(f"    pharm_admin_evidence_count: {dvt_pharm_admin}")
    lines.append(f"    pharm_ambiguous_mention_count: {dvt_pharm_ambig}")
    lines.append(f"    mech_admin_evidence_count: {dvt_mech_admin}")
    lines.append(f"    orders_only_count: {dvt_orders_only}")

    lines.append("")

    # ── Artifact Integrity ──
    lines.append(f"  Artifact Integrity:")
    current_hashes = {}
    for key, path in PROTECTED_FILES.items():
        if path.is_file():
            current_hashes[key] = md5_file(path)
        else:
            current_hashes[key] = "FILE_MISSING"

    v3_changed = current_hashes.get("v3_renderer") != BASELINE_HASHES.get("v3_renderer")
    # green_card: baseline=None means files not yet populated — treat as unchanged
    _gc_init_bl = BASELINE_HASHES.get("green_card_init")
    _gc_adj_bl  = BASELINE_HASHES.get("green_card_adj")
    gc_changed = (
        (_gc_init_bl is not None and current_hashes.get("green_card_init") != _gc_init_bl) or
        (_gc_adj_bl  is not None and current_hashes.get("green_card_adj")  != _gc_adj_bl)
    )
    ntds_changed = current_hashes.get("ntds_engine") != BASELINE_HASHES.get("ntds_engine")
    proto_changed = current_hashes.get("protocol_engine") != BASELINE_HASHES.get("protocol_engine")

    lines.append(f"    v3_changed: {v3_changed}")
    lines.append(f"    green_card_changed: {gc_changed}")
    lines.append(f"    ntds_logic_changed: {ntds_changed}")
    lines.append(f"    protocol_logic_changed: {proto_changed}")

    return "\n".join(lines)


def _william_detail() -> None:
    """Print per-day abnormal summary/count alignment for William_Simmons."""
    pat = "William_Simmons"
    features_path = REPO / "outputs" / "features" / pat / "patient_features_v1.json"
    features = load_json(features_path)
    if features is None:
        print("WILLIAM_SIMMONS ABNORMAL ALIGNMENT: features file missing")
        return

    print("=" * 70)
    print("WILLIAM_SIMMONS — ABNORMAL SUMMARY / COUNT ALIGNMENT")
    print("=" * 70)

    days = features.get("days", {})
    day_keys = sorted(k for k in days if k != "__UNDATED__")

    total_source_abn = Counter()
    total_rollup_abn = Counter()

    for dk in day_keys:
        vit = days[dk].get("vitals", {})
        day_mismatches = []
        for metric in ABNORMAL_VITALS_METRICS:
            mdata = vit.get(metric, {})
            rollup_abn = mdata.get("abnormal_count", 0)
            src_abn = sum(1 for s in mdata.get("sources", []) if s.get("abnormal"))
            total_source_abn[metric] += src_abn
            total_rollup_abn[metric] += rollup_abn
            if rollup_abn != src_abn:
                day_mismatches.append(f"{metric}: rollup={rollup_abn} src={src_abn}")

        day_abn_total = sum(
            sum(1 for s in vit.get(m, {}).get("sources", []) if s.get("abnormal"))
            for m in ABNORMAL_VITALS_METRICS
        )
        status = "OK" if not day_mismatches else "MISMATCH"
        print(f"  {dk}: abnormal={day_abn_total}  [{status}]"
              + (f"  {'; '.join(day_mismatches)}" if day_mismatches else ""))

    print()
    print("  TOTALS (source-level):")
    grand_total = sum(total_source_abn.values())
    for m in ABNORMAL_VITALS_METRICS:
        if total_source_abn[m] > 0:
            match_str = "OK" if total_source_abn[m] == total_rollup_abn[m] else "MISMATCH"
            print(f"    {m}: {total_source_abn[m]}  [{match_str}]")
    print(f"    total: {grand_total}")
    aligned = all(total_source_abn[m] == total_rollup_abn[m] for m in ABNORMAL_VITALS_METRICS)
    print(f"  FULLY ALIGNED: {aligned}")
    print()


def main() -> int:
    # ── Run pipeline for all patients ──
    import subprocess
    for pat in PATIENTS:
        print(f"{'='*60}")
        print(f"RUNNING PIPELINE: {pat}")
        print(f"{'='*60}")
        result = subprocess.run(
            ["bash", str(REPO / "run_patient.sh"), pat],
            cwd=str(REPO),
            env={**__import__("os").environ, "PYTHONPATH": str(REPO)},
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"  PIPELINE FAILED for {pat}:")
            print(result.stderr[-500:] if result.stderr else "(no stderr)")
            return 1
        print(f"  Pipeline OK for {pat}")
    print()

    # ── Determinism check: run pipeline again for first patient ──
    det_pat = PATIENTS[0]
    features_path = REPO / "outputs" / "features" / det_pat / "patient_features_v1.json"
    v4_path = REPO / "outputs" / "reporting" / det_pat / "TRAUMA_DAILY_NOTES_v4.txt"
    hash1_features = md5_file(features_path) if features_path.is_file() else "MISSING"
    hash1_v4 = md5_file(v4_path) if v4_path.is_file() else "MISSING"

    result = subprocess.run(
        ["bash", str(REPO / "run_patient.sh"), det_pat],
        cwd=str(REPO),
        env={**__import__("os").environ, "PYTHONPATH": str(REPO)},
        capture_output=True, text=True,
    )
    hash2_features = md5_file(features_path) if features_path.is_file() else "MISSING"
    hash2_v4 = md5_file(v4_path) if v4_path.is_file() else "MISSING"

    deterministic = (hash1_features == hash2_features) and (hash1_v4 == hash2_v4)

    # ── Output validation boxes ──
    print("=" * 70)
    print("PHASE 1 — STRUCTURED REGRESSION RESULTS")
    print("=" * 70)
    print()

    for pat in PATIENTS:
        box = compute_patient_box(pat)
        print(box)
        print()
        print("-" * 70)
        print()

    # ── William_Simmons: abnormal summary/count alignment detail ──
    _william_detail()

    # ── Determinism confirmation ──
    print("DETERMINISM CHECK:")
    print(f"  Patient: {det_pat}")
    print(f"  Run 1 features hash: {hash1_features}")
    print(f"  Run 2 features hash: {hash2_features}")
    print(f"  Run 1 v4 hash:       {hash1_v4}")
    print(f"  Run 2 v4 hash:       {hash2_v4}")
    print(f"  Deterministic: {deterministic}")
    print()

    # ── Diff summary ──
    print("DIFF SUMMARY (files modified by Phase 1):")
    phase1_files = [
        "cerebralos/features/gcs_daily.py",
        "cerebralos/features/build_patient_features_v1.py",
        "cerebralos/features/vitals_daily.py",
        "cerebralos/reporting/render_trauma_daily_notes_v4.py",
        "cerebralos/validation/report_features_qa.py",
    ]
    for f in phase1_files:
        p = REPO / f
        print(f"  MODIFIED: {f}  (exists={p.is_file()})")
    print(f"  NEW:      _regression_phase1_v2.py")
    print()

    # ── Artifact drift confirmation ──
    print("ARTIFACT INTEGRITY CONFIRMATION:")
    all_ok = True
    for key, baseline in BASELINE_HASHES.items():
        current = md5_file(PROTECTED_FILES[key]) if PROTECTED_FILES[key].is_file() else "MISSING"
        if baseline is None:
            # File not yet populated — skip drift check
            label = key.replace("_", " ").title()
            print(f"  {label}: baseline=N/A (not populated)  current={current[:12]}...  skip")
            continue
        match = current == baseline
        if not match:
            all_ok = False
        label = key.replace("_", " ").title()
        print(f"  {label}: baseline={baseline[:12]}... current={current[:12]}... match={match}")
    print(f"  Zero unintended artifact drift: {all_ok}")
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
