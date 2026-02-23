#!/usr/bin/env python3
"""
GREEN CARD v1 – QA report.

Prints which doc types were detected, whether Trauma H&P was found,
completeness checklist, and top warnings.

Usage:
    python3 cerebralos/validation/report_green_card_qa.py --pat Timothy_Cowan

Design: Deterministic. No LLM, no ML.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent.parent


def main() -> int:
    ap = argparse.ArgumentParser(description="GREEN CARD v1 QA report")
    ap.add_argument("--pat", required=True, help="Patient folder name")
    args = ap.parse_args()

    gc_path = _REPO_ROOT / "outputs" / "green_card" / args.pat / "green_card_v1.json"
    ev_path = _REPO_ROOT / "outputs" / "green_card" / args.pat / "green_card_evidence_v1.json"

    if not gc_path.is_file():
        print(f"FAIL: green_card_v1.json not found: {gc_path}", file=sys.stderr)
        return 1

    with open(gc_path, encoding="utf-8") as f:
        gc = json.load(f)

    ev = None
    if ev_path.is_file():
        with open(ev_path, encoding="utf-8") as f:
            ev = json.load(f)

    meta = gc.get("meta", {})
    doc_counts = gc.get("doc_type_counts", {})
    warnings = gc.get("warnings", [])

    print("=" * 60)
    print(f"GREEN CARD QA: {meta.get('patient_slug', 'unknown')}")
    print("=" * 60)

    # ── Doc types detected ──────────────────────────────────────
    print("\nDOC TYPE COUNTS:")
    if doc_counts:
        for dtype, cnt in sorted(doc_counts.items(), key=lambda x: x[1], reverse=True):
            marker = " ★" if dtype == "trauma_hp" else ""
            print(f"  {dtype:25s} {cnt:4d}{marker}")
    else:
        print("  (none)")

    # ── Trauma H&P found? ───────────────────────────────────────
    hp_found = doc_counts.get("trauma_hp", 0) > 0
    hp_count = doc_counts.get("trauma_hp", 0)
    print(f"\nTRAUMA H&P FOUND: {'YES ✓' if hp_found else 'NO ✗'}")

    # ── Trauma H&P QA block ─────────────────────────────────────
    print(f"\nTRAUMA H&P QA:")
    print(f"  trauma_hp_detected_count: {hp_count}")
    chosen_hp = None
    hpi_length = 0
    if ev:
        chosen_hp = ev.get("chosen_trauma_hp")
        hpi_ev = ev.get("hpi_evidence", {})
        hpi_length = hpi_ev.get("hpi_length_chars", 0)
    if chosen_hp:
        print(f"  chosen_trauma_hp:")
        print(f"    item_id:        {chosen_hp.get('item_id')}")
        print(f"    ts:             {chosen_hp.get('ts')}")
        print(f"    match_tier:     {chosen_hp.get('match_tier')}")
        print(f"    matched_pattern: {chosen_hp.get('matched_pattern')}")
        preview = chosen_hp.get("matched_line_preview", "")
        if len(preview) > 80:
            preview = preview[:80] + "…"
        print(f"    line_preview:   {preview}")
    else:
        print("  chosen_trauma_hp: (none)")
    print(f"  hpi_length_chars: {hpi_length}")
    hp_warnings: list[str] = []
    if "no_trauma_hp_detected" in warnings:
        hp_warnings.append("no_trauma_hp_detected")
    if "multiple_trauma_hp_detected" in warnings:
        hp_warnings.append("multiple_trauma_hp_detected")
    if hp_warnings:
        print(f"  hp_warnings: {', '.join(hp_warnings)}")
    else:
        print("  hp_warnings: (none)")

    # ── Admitting service ───────────────────────────────────────
    admit = gc.get("admitting_service", {})
    print(f"ADMITTING SERVICE: {admit.get('value', 'UNKNOWN')}")

    # ── Completeness checklist ──────────────────────────────────
    print("\nCOMPLETENESS CHECKLIST:")
    checks = [
        ("MOI",             gc.get("mechanism_of_injury", {}).get("value") is not None),
        ("HPI",             _field_has_data(gc, "hpi")),
        ("Injuries",        bool(gc.get("injuries", {}).get("value"))),
        ("PMH",             bool(gc.get("pmh", {}).get("value"))),
        ("Anticoagulants",  _anticoag_present(gc)),
        ("Consultants",     bool(gc.get("consultants", {}).get("value"))),
        ("Procedures",      bool(gc.get("procedures", {}).get("value"))),
        ("Admit Service",   admit.get("value") not in (None, "UNKNOWN")),
        ("Spine Clearance", _adjunct_present(gc, "spine_clearance", "status")),
        ("DVT Prophylaxis", _adjunct_dvt_present(gc)),
        ("First ED Temp",   _adjunct_has_value(gc, "first_ed_temp")),
        ("GI Prophylaxis",  _adjunct_present(gc, "gi_prophylaxis", "status")),
        ("Bowel Regimen",   _adjunct_present(gc, "bowel_regimen", "status")),
        ("Tourniquet",      _adjunct_present(gc, "tourniquet", "placed")),
        ("Primary Survey",  gc.get("primary_survey", {}).get("raw_block") is not None),
        ("GCS",             gc.get("primary_survey", {}).get("gcs") is not None),
        ("FAST",            gc.get("primary_survey", {}).get("fast_performed") != "UNKNOWN"),
        ("Admitting MD",    gc.get("admitting_md", {}).get("name") is not None),
        ("Anticoag Status", gc.get("anticoag_status", {}).get("status") != "UNKNOWN"),
        ("ETOH",            gc.get("etoh", {}).get("value") is not None),
        ("UDS",             gc.get("uds", {}).get("performed", False)),
        ("Base Deficit",    gc.get("base_deficit", {}).get("value") is not None),
        ("INR",             gc.get("inr", {}).get("value") is not None),
        ("Impression/Plan", bool(gc.get("impression_plan", {}).get("entries"))),
    ]
    complete = 0
    for label, ok in checks:
        status = "✓" if ok else "✗"
        print(f"  [{status}] {label}")
        if ok:
            complete += 1
    print(f"\n  Score: {complete}/{len(checks)}")

    # ── Validate impression_plan_timeline_v1.json when CEREBRAL_GREEN=1 ──
    if os.environ.get("CEREBRAL_GREEN") == "1":
        ip_timeline_path = (
            _REPO_ROOT / "outputs" / "green_card" / args.pat
            / "impression_plan_timeline_v1.json"
        )
        if ip_timeline_path.is_file():
            print("\n  [✓] impression_plan_timeline_v1.json exists")
        else:
            print("\n  [✗] impression_plan_timeline_v1.json MISSING")
            warnings.append("impression_plan_timeline_v1_missing")

    # ── Top warnings ────────────────────────────────────────────
    print(f"\nWARNINGS ({len(warnings)}):")
    if warnings:
        for w in warnings[:20]:
            print(f"  - {w}")
    else:
        print("  (none)")

    # ── Field-level discharge conflicts ─────────────────────────
    conflict_count = 0
    for field_name in ["admitting_service", "mechanism_of_injury", "moi_narrative",
                       "hpi", "injuries",
                       "procedures", "consultants", "pmh", "home_anticoagulants"]:
        field = gc.get(field_name, {})
        for w in field.get("warnings", []):
            if isinstance(w, dict) and w.get("code") == "discharge_conflict":
                conflict_count += 1
                print(f"\n  DISCHARGE CONFLICT in {field_name}:")
                print(f"    existing = {w.get('existing_value')} ({w.get('existing_source')})")
                print(f"    discharge = {w.get('discharge_value')} ({w.get('discharge_source')})")

    if conflict_count:
        print(f"\n  Total discharge conflicts: {conflict_count}")

    # ── Adjunct field QA ────────────────────────────────────────
    print("\nADJUNCT FIELDS:")
    _adjunct_names = [
        ("Spine Clearance", "spine_clearance"),
        ("DVT Prophylaxis", "dvt_prophylaxis"),
        ("First ED Temp",   "first_ed_temp"),
        ("GI Prophylaxis",  "gi_prophylaxis"),
        ("Bowel Regimen",   "bowel_regimen"),
        ("Tourniquet",      "tourniquet"),
        ("Primary Survey",  "primary_survey"),
        ("Admitting MD",    "admitting_md"),
        ("Anticoag Status", "anticoag_status"),
        ("ETOH",            "etoh"),
        ("UDS",             "uds"),
        ("Base Deficit",    "base_deficit"),
        ("INR",             "inr"),
        ("Impression/Plan", "impression_plan"),
    ]
    for label, key in _adjunct_names:
        adj = gc.get(key, {})
        # Determine presence
        if key == "spine_clearance":
            status = adj.get("status", "UNKNOWN")
            present = status != "UNKNOWN"
            detail = f"status={status}, method={adj.get('method', 'UNKNOWN')}"
            # Region-level detail
            regions = adj.get("regions", {})
            cs = regions.get("cspine", {})
            tl = regions.get("tlspine", {})
            cs_ord = cs.get("ordered", "UNKNOWN")
            cs_dt = cs.get("final_dt")
            tl_ord = tl.get("ordered", "UNKNOWN")
            tl_dt = tl.get("final_dt")
            detail += f"\n      cspine_final={cs_ord}"
            if cs_dt:
                detail += f" ({cs_dt})"
            detail += f", tlspine_final={tl_ord}"
            if tl_dt:
                detail += f" ({tl_dt})"
            # Check for order-question evidence
            has_oq = any(
                s.get("source_type") == "ORDER_QUESTION"
                for s in adj.get("sources", [])
            )
            detail += f"\n      order_question_evidence={'YES' if has_oq else 'NO'}"
        elif key == "dvt_prophylaxis":
            agent = adj.get("agent")
            present = agent is not None
            detail = f"agent={agent or '(none)'}"
            if adj.get("first_order_dt"):
                detail += f", order={adj['first_order_dt']}"
            if adj.get("first_admin_dt"):
                detail += f", admin={adj['first_admin_dt']}"
        elif key == "first_ed_temp":
            val = adj.get("value")
            present = val is not None
            detail = f"value={val or '(none)'}, units={adj.get('units', 'UNKNOWN')}"
        elif key == "gi_prophylaxis":
            status = adj.get("status", "UNKNOWN")
            present = status in ("YES", "NO")
            detail = f"status={status}, agent={adj.get('agent') or '(none)'}"
            if adj.get("first_order_dt"):
                detail += f", order_dt={adj['first_order_dt']}"
        elif key == "bowel_regimen":
            status = adj.get("status", "UNKNOWN")
            present = status in ("YES", "NO")
            agents = adj.get("agents", [])
            detail = f"status={status}, agents={', '.join(agents) if agents else '(none)'}"
            if adj.get("first_order_dt"):
                detail += f", order_dt={adj['first_order_dt']}"
        elif key == "tourniquet":
            tq_placed = adj.get("placed", "UNKNOWN")
            present = tq_placed in ("YES", "NO")
            detail = f"placed={tq_placed}"
            if adj.get("placed_time"):
                detail += f", placed_time={adj['placed_time']}"
            if adj.get("location"):
                detail += f", location={adj['location']}"
            if adj.get("removed"):
                detail += f", removed={adj['removed']}"
            if adj.get("removed_time"):
                detail += f", removed_time={adj['removed_time']}"
        elif key == "primary_survey":
            has_block = adj.get("raw_block") is not None
            present = has_block
            gcs = adj.get("gcs")
            fast_perf = adj.get("fast_performed", "UNKNOWN")
            fast_res = adj.get("fast_result", "UNKNOWN")
            detail = f"found={'YES' if has_block else 'NO'}"
            if gcs is not None:
                detail += f", GCS={gcs}"
            else:
                detail += ", GCS=(not extracted)"
            detail += f", FAST_performed={fast_perf}, FAST_result={fast_res}"
            if adj.get("pupils"):
                detail += f", pupils={adj['pupils']}"
        elif key == "admitting_md":
            name = adj.get("name")
            present = name is not None
            cred = adj.get("credential") or "(none)"
            role = adj.get("role", "UNKNOWN")
            detail = f"name={name or '(none)'}, credential={cred}, role={role}"
        elif key == "anticoag_status":
            ac_st = adj.get("status", "UNKNOWN")
            present = ac_st != "UNKNOWN"
            agents = adj.get("agents", [])
            detail = f"status={ac_st}"
            if agents:
                detail += f", agents={', '.join(agents)}"
            hr = adj.get("hold_resume_events", [])
            if hr:
                detail += f", hold_resume_events={len(hr)}"
        elif key == "etoh":
            val = adj.get("value")
            present = val is not None
            detail = f"value={val or '(none)'}"
            if adj.get("units"):
                detail += f", units={adj['units']}"
            if adj.get("date"):
                detail += f", date={adj['date']}"
            detail += f", method={adj.get('source_method', '(none)')}"
        elif key == "uds":
            performed = adj.get("performed", False)
            present = performed
            comps = adj.get("components", {})
            pos = adj.get("positive_flags", [])
            detail = f"performed={'YES' if performed else 'NO'}, components={len(comps)}"
            if pos:
                detail += f", POSITIVE: {', '.join(pos)}"
            if adj.get("date"):
                detail += f", date={adj['date']}"
        elif key == "base_deficit":
            val = adj.get("value")
            present = val is not None
            detail = f"value={val or '(none)'}"
            if adj.get("date"):
                detail += f", date={adj['date']}"
            if adj.get("is_category_1"):
                detail += ", ⚠ CATEGORY_1"
            detail += f", method={adj.get('source_method', '(none)')}"
        elif key == "inr":
            val = adj.get("value")
            present = val is not None
            detail = f"value={val or '(none)'}"
            if adj.get("range"):
                detail += f", range={adj['range']}"
            if adj.get("date"):
                detail += f", date={adj['date']}"
            detail += f", method={adj.get('source_method', '(none)')}"
        elif key == "impression_plan":
            entries = adj.get("entries", [])
            present = bool(entries)
            detail = f"entries={len(entries)}"
            drift = adj.get("drift_flags", [])
            if drift:
                detail += f", drift_flags={len(drift)}"
            for e in entries[:3]:
                detail += f"\n      [{e.get('date', '?')}] {e.get('doc_type', '?')}"
                if e.get("impression"):
                    detail += f" imp={len(e['impression'])}ch"
                if e.get("plan"):
                    detail += f" plan={len(e['plan'])}ch"
        else:
            present = False
            detail = ""

        marker = "✓" if present else "✗"
        print(f"  [{marker}] {label}: {detail}")

        # Print warnings
        adj_warnings = adj.get("warnings", [])
        if adj_warnings:
            for w in adj_warnings:
                print(f"      ⚠ {w}")

    print("\n" + "=" * 60)
    return 0


def _anticoag_present(gc: dict) -> bool:
    """Check if anticoagulant field has real data (not just 'unknown')."""
    val = gc.get("home_anticoagulants", {}).get("value") or []
    return bool(val) and not all("unknown" in str(v).lower() for v in val)


def _field_has_data(gc: dict, key: str) -> bool:
    """Check if a tracked field has real data (not DATA NOT AVAILABLE)."""
    val = gc.get(key, {}).get("value")
    if val is None:
        return False
    if isinstance(val, str) and val.strip().upper() in ("", "DATA NOT AVAILABLE"):
        return False
    return True


def _adjunct_present(gc: dict, key: str, status_key: str) -> bool:
    """Check if an adjunct field has a known status (not UNKNOWN)."""
    adj = gc.get(key, {})
    status = adj.get(status_key, "UNKNOWN")
    return status not in (None, "UNKNOWN")


def _adjunct_dvt_present(gc: dict) -> bool:
    """Check if DVT prophylaxis has an identified agent."""
    adj = gc.get("dvt_prophylaxis", {})
    return adj.get("agent") is not None


def _adjunct_has_value(gc: dict, key: str) -> bool:
    """Check if an adjunct field has a non-null value."""
    adj = gc.get(key, {})
    return adj.get("value") is not None


if __name__ == "__main__":
    raise SystemExit(main())
