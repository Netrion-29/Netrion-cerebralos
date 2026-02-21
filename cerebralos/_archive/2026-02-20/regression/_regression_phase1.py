#!/usr/bin/env python3
"""Phase 1 regression matrix for Daily Notes v4 stabilization."""

import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent
PATIENTS = ["Anna_Dennis", "William_Simmons", "Timothy_Nachtwey", "Timothy_Cowan"]

ABNORMAL_THRESHOLDS = {
    "hr": {"high": 120},
    "sbp": {"low": 90},
    "temp_f": {"high": 100.4},
    "spo2": {"low": 90},
    "rr": {"high": 24},
}

NARRATIVE_LAB_KEYWORDS = {
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

import re


def run_regression(pat: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"REGRESSION: {pat}")
    print("=" * 60)

    feat_path = REPO / "outputs" / "features" / pat / "patient_features_v1.json"
    timeline_path = REPO / "outputs" / "timeline" / pat / "patient_days_v1.json"
    v4_path = REPO / "outputs" / "reporting" / pat / "TRAUMA_DAILY_NOTES_v4.txt"

    if not feat_path.is_file():
        print(f"  FAIL: features file not found: {feat_path}")
        return

    with open(feat_path) as f:
        data = json.load(f)

    days = data.get("days", {})
    dated_keys = sorted(k for k in days if k != "__UNDATED__")

    # ── Arrival GCS block ──
    print("\n--- ARRIVAL GCS ---")
    found_arrival = False
    for dk in dated_keys:
        gcs = days[dk].get("gcs_daily", {})
        ag = gcs.get("arrival_gcs")
        if ag and ag != "DATA NOT AVAILABLE":
            found_arrival = True
            print(f"  Day: {dk}")
            if isinstance(ag, dict):
                print(f"  arrival_gcs_value: {ag.get('value')}")
            else:
                print(f"  arrival_gcs_value: {ag}")
            print(f"  arrival_gcs_ts: {gcs.get('arrival_gcs_ts')}")
            print(f"  arrival_gcs_source: {gcs.get('arrival_gcs_source')}")
            print(f"  arrival_gcs_missing_in_trauma_hp: {gcs.get('arrival_gcs_missing_in_trauma_hp')}")
            print(f"  arrival_gcs_source_rule_id: {gcs.get('arrival_gcs_source_rule_id')}")
            src = gcs.get("arrival_gcs_source", "") or ""
            ed_fb = gcs.get("arrival_gcs_missing_in_trauma_hp", False) and src.startswith("ED_NOTE")
            print(f"  ED fallback used: {'Yes' if ed_fb else 'No'}")
            break
    if not found_arrival:
        if dated_keys:
            dk = dated_keys[0]
            gcs = days[dk].get("gcs_daily", {})
            print(f"  Day: {dk}")
            print(f"  arrival_gcs: DATA NOT AVAILABLE")
            print(f"  arrival_gcs_value: {gcs.get('arrival_gcs_value')}")
            print(f"  arrival_gcs_ts: {gcs.get('arrival_gcs_ts')}")
            print(f"  arrival_gcs_source: {gcs.get('arrival_gcs_source')}")
            print(f"  arrival_gcs_missing_in_trauma_hp: {gcs.get('arrival_gcs_missing_in_trauma_hp')}")
            print(f"  arrival_gcs_source_rule_id: {gcs.get('arrival_gcs_source_rule_id')}")
            print(f"  ED fallback used: No")

    # ── Tabular vitals unsupported ──
    print("\n--- QA: TABULAR VITALS UNSUPPORTED ---")
    total_unsup = 0
    total_parsed = 0
    for dk in dated_keys:
        vqa = days[dk].get("vitals", {}).get("vitals_qa", {})
        total_unsup += vqa.get("tabular_note_vitals_unsupported", 0)
        total_parsed += vqa.get("vitals_readings_total", 0)
    print(f"  tabular_vitals_lines_total: {total_parsed + total_unsup}")
    print(f"  tabular_vitals_lines_parsed: {total_parsed}")
    print(f"  tabular_vitals_lines_unsupported: {total_unsup}")

    # ── Narrative lab mentions ──
    print("\n--- QA: NARRATIVE LAB MENTIONS ---")
    narr_hits = Counter()
    structured_comps = set()
    for dk in dated_keys:
        daily = days[dk].get("labs", {}).get("daily", {})
        for comp in daily:
            structured_comps.add(comp.lower())

    if timeline_path.is_file():
        with open(timeline_path) as f:
            tl = json.load(f)
        tl_days = tl.get("days", {})
        for day_iso_t, day_info_t in tl_days.items():
            for item in day_info_t.get("items", []):
                text = (item.get("payload") or {}).get("text", "")
                item_type = item.get("type", "")
                if item_type == "LAB":
                    continue
                for kw_name, kw_pat in NARRATIVE_LAB_KEYWORDS.items():
                    if re.search(kw_pat, text, re.IGNORECASE):
                        narr_hits[kw_name] += 1
    else:
        print("  (timeline not available — skipped)")

    present_missing = []
    for kw_name in sorted(NARRATIVE_LAB_KEYWORDS.keys()):
        found_struct = any(kw_name.lower() in sc or sc in kw_name.lower()
                          for sc in structured_comps)
        if narr_hits[kw_name] > 0 and not found_struct:
            present_missing.append(kw_name)

    print(f"  narrative_lab_mentions_detected: {sum(narr_hits.values())}")
    for kw in sorted(narr_hits.keys()):
        if narr_hits[kw] > 0:
            print(f"    {kw}: {narr_hits[kw]}")
    print(f"  narrative_labs_present_but_structured_missing: {len(present_missing)}")
    if present_missing:
        print(f"    missing: {', '.join(present_missing)}")

    # ── Evidence gap detection ──
    print("\n--- QA: EVIDENCE GAP DETECTION ---")
    egaps = data.get("evidence_gaps", {})
    print(f"  gap_count: {egaps.get('gap_count', 0)}")
    print(f"  max_gap_days: {egaps.get('max_gap_days', 0)}")
    for g in egaps.get("gaps", [])[:5]:
        print(f"  gap: {g['from']} -> {g['to']} ({g['gap_days']} days)")

    # Check v4 output for gap lines
    if v4_path.is_file():
        v4_text = v4_path.read_text()
        gap_lines = [l for l in v4_text.split("\n") if "EVIDENCE GAP:" in l]
        print(f"  v4 gap lines rendered: {len(gap_lines)}")
        for gl in gap_lines:
            print(f"    {gl.strip()}")
    else:
        print("  v4 file not found")

    # ── Abnormal vitals counts ──
    print("\n--- QA: ABNORMAL VITALS COUNTS ---")
    print("  Thresholds: HR>120, SBP<90, TempF>=100.4, SpO2<90, RR>24")
    abn = Counter()
    for dk in dated_keys:
        vit = days[dk].get("vitals", {})
        for metric, th in ABNORMAL_THRESHOLDS.items():
            for src in vit.get(metric, {}).get("sources", []):
                val = src.get("value")
                if val is None:
                    continue
                triggered = False
                if "high" in th and metric == "temp_f":
                    if val >= th["high"]:
                        triggered = True
                elif "high" in th:
                    if val > th["high"]:
                        triggered = True
                if "low" in th:
                    if val < th["low"]:
                        triggered = True
                if triggered:
                    abn[metric] += 1
    for m in ("hr", "sbp", "temp_f", "spo2", "rr"):
        print(f"  {m}: {abn.get(m, 0)}")


def main():
    for pat in PATIENTS:
        run_regression(pat)

    # ── Confirmation checks ──
    print(f"\n{'=' * 60}")
    print("CONFIRMATION CHECKS")
    print("=" * 60)

    # v3 renderer source unchanged
    import hashlib
    v3_path = REPO / "cerebralos" / "reporting" / "render_trauma_daily_notes_v3.py"
    v3_hash = hashlib.md5(v3_path.read_bytes()).hexdigest()
    print(f"  v3 renderer source hash: {v3_hash}")
    print(f"  v3 renderer UNCHANGED: {'YES' if v3_hash == '78ccffe75ccf6f98763f9efa8a8b917e' else 'NO'}")

    # Green Card untouched
    gc_files = sorted((REPO / "cerebralos" / "green_card").glob("*.py"))
    gc_hashes = {f.name: hashlib.md5(f.read_bytes()).hexdigest() for f in gc_files}
    gc_baseline = {
        "__init__.py": "aa2e2723d1535351cffddf9d12325d29",
        "extract_green_card_adjuncts_v1.py": "bf1387110c5fa2f000752251192ab9f7",
        "extract_green_card_hp_v1.py": "eb20794495b369a88c03dcd4a1671bc4",
        "extract_green_card_v1.py": "c1e696fc61850baf9540aa8fd478618b",
        "render_green_card_v1.py": "b1c3a0164f6cb1e82965b9d17774f53e",
    }
    gc_ok = all(gc_hashes.get(k) == v for k, v in gc_baseline.items())
    print(f"  Green Card files UNCHANGED: {'YES' if gc_ok else 'NO'}")

    # NTDS engine untouched
    ntds_files = sorted((REPO / "cerebralos" / "ntds_logic").glob("*.py"))
    ntds_baseline = {
        "build_patientfacts_from_txt.py": "7064ca2d158208124213bf52f124ee43",
        "engine.py": "80f7329474ac9300dcbdec8b8db043e1",
        "model.py": "6d232f48f1ecb243b9321d6d1d4dcec1",
        "rules_loader.py": "699a7cd30eb88216ac6cf6deb3c1b859",
    }
    ntds_hashes = {f.name: hashlib.md5(f.read_bytes()).hexdigest() for f in ntds_files}
    ntds_ok = all(ntds_hashes.get(k) == v for k, v in ntds_baseline.items())
    print(f"  NTDS engine UNCHANGED: {'YES' if ntds_ok else 'NO'}")

    # Protocol engine untouched
    pe_files = sorted((REPO / "cerebralos" / "protocol_engine").glob("*.py"))
    pe_baseline = {
        "build_protocolfacts.py": "7cd3b78dca8e674294486ee1d08baf3d",
        "engine.py": "f436ded9a6e22a9b5d484609f4a4f188",
        "model.py": "6c555f87c78032c115e32cb4d91229ee",
        "rules_loader.py": "117fa778a007e3a5bb4555b322034769",
    }
    pe_hashes = {f.name: hashlib.md5(f.read_bytes()).hexdigest() for f in pe_files}
    pe_ok = all(pe_hashes.get(k) == v for k, v in pe_baseline.items())
    print(f"  Protocol engine UNCHANGED: {'YES' if pe_ok else 'NO'}")

    print()


if __name__ == "__main__":
    main()
