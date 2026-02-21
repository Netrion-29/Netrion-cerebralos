#!/usr/bin/env python3
"""
GREEN CARD v1 – Markdown renderer.

Reads green_card_v1.json and emits GREEN_CARD_v1.md (Drafts-ready).

Usage:
    python3 -m cerebralos.green_card.render_green_card_v1 --pat Timothy_Cowan

Design:
- Deterministic. No LLM, no ML.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent.parent


def _bullet_list(items: list, indent: int = 0) -> str:
    """Render a list as Markdown bullets."""
    prefix = "  " * indent
    if not items:
        return f"{prefix}- _(none)_\n"
    return "".join(f"{prefix}- {item}\n" for item in items)


def _source_tag(sources: list) -> str:
    """Render source attribution as a compact tag."""
    if not sources:
        return ""
    types = sorted(set(s.get("source_type", "?") for s in sources))
    return f" `[{', '.join(types)}]`"


def render_green_card(gc: Dict[str, Any]) -> str:
    """Render green_card_v1.json dict into Markdown string."""
    meta = gc.get("meta", {})
    lines: list[str] = []

    # ── Header ──────────────────────────────────────────────────
    lines.append(f"# GREEN CARD v1 — {meta.get('patient_slug', 'unknown')}")
    lines.append("")
    lines.append(f"**Patient ID:** {meta.get('patient_id', 'unknown')}  ")
    lines.append(f"**Arrival:** {meta.get('arrival_datetime', 'unknown')}  ")
    lines.append(f"**Trauma Category:** {meta.get('trauma_category', 'unknown')}  ")

    admit_svc = gc.get("admitting_service", {})
    admit_val = admit_svc.get("value", "UNKNOWN")
    lines.append(f"**Admitting Service:** {admit_val}{_source_tag(admit_svc.get('sources', []))}")
    lines.append("")
    lines.append(f"_Generated: {meta.get('created_at_utc', 'unknown')} UTC_")
    lines.append("")

    # ── Mechanism of Injury ─────────────────────────────────────
    lines.append("---")
    lines.append("## Mechanism of Injury")
    lines.append("")
    moi = gc.get("mechanism_of_injury", {})
    moi_val = moi.get("value")
    if moi_val:
        moi_preview = ""
        srcs = moi.get("sources", [])
        if srcs and srcs[0].get("preview"):
            moi_preview = f'\n> {srcs[0]["preview"]}'
        lines.append(f"**{moi_val}**{_source_tag(srcs)}")
        if moi_preview:
            lines.append(moi_preview)
    else:
        lines.append("_(not identified)_")
    lines.append("")

    # ── MOI Narrative ──────────────────────────────────────────
    moi_narr = gc.get("moi_narrative", {})
    moi_narr_val = moi_narr.get("value")
    if moi_narr_val and moi_narr_val != "DATA NOT AVAILABLE":
        lines.append("### MOI Narrative")
        lines.append("")
        lines.append(f"> {moi_narr_val}")
        lines.append("")

    # ── HPI (Trauma H&P) ──────────────────────────────────────
    hpi = gc.get("hpi", {})
    hpi_val = hpi.get("value")
    if hpi_val and hpi_val != "DATA NOT AVAILABLE":
        lines.append("---")
        lines.append("## HPI (Trauma H&P)")
        lines.append("")
        lines.append(hpi_val)
        lines.append("")
        lines.append(f"_Source:{_source_tag(hpi.get('sources', []))}_")
        lines.append("")
    elif hpi_val == "DATA NOT AVAILABLE":
        lines.append("---")
        lines.append("## HPI (Trauma H&P)")
        lines.append("")
        lines.append("_(DATA NOT AVAILABLE)_")
        lines.append("")

    # ── Injuries ────────────────────────────────────────────────
    lines.append("---")
    lines.append("## Injuries (Explicit Diagnoses)")
    lines.append("")
    inj = gc.get("injuries", {})
    inj_val = inj.get("value") or []
    if inj_val:
        lines.append(_bullet_list(inj_val))
        lines.append(f"_Sources:{_source_tag(inj.get('sources', []))}_")
    else:
        lines.append("_(none extracted)_")
    lines.append("")

    # ── Procedures ──────────────────────────────────────────────
    lines.append("---")
    lines.append("## Procedures")
    lines.append("")
    proc = gc.get("procedures", {})
    proc_val = proc.get("value") or []
    if proc_val:
        lines.append(_bullet_list(proc_val))
        lines.append(f"_Sources:{_source_tag(proc.get('sources', []))}_")
    else:
        lines.append("_(none extracted)_")
    lines.append("")

    # ── Consultants ─────────────────────────────────────────────
    lines.append("---")
    lines.append("## Consultants")
    lines.append("")
    consult = gc.get("consultants", {})
    consult_val = consult.get("value") or []
    if consult_val:
        lines.append(_bullet_list(consult_val))
        lines.append(f"_Sources:{_source_tag(consult.get('sources', []))}_")
    else:
        lines.append("_(none extracted)_")
    lines.append("")

    # Service spread by day (if available)
    svc_by_day = gc.get("services_by_day", [])
    if svc_by_day:
        lines.append("### Service Notes by Day")
        lines.append("")
        lines.append("| Day | Service | Notes |")
        lines.append("|-----|---------|-------|")
        for entry in svc_by_day:
            lines.append(
                f"| {entry.get('day', '')} | {entry.get('service', '')} "
                f"| {entry.get('note_count', 0)} |"
            )
        lines.append("")

    # ── PMH ─────────────────────────────────────────────────────
    lines.append("---")
    lines.append("## Past Medical History (PMH)")
    lines.append("")
    pmh = gc.get("pmh", {})
    pmh_val = pmh.get("value") or []
    if pmh_val:
        lines.append(_bullet_list(pmh_val))
        lines.append(f"_Sources:{_source_tag(pmh.get('sources', []))}_")
    else:
        lines.append("_(not found)_")
    lines.append("")

    # ── Anticoagulants ──────────────────────────────────────────
    lines.append("---")
    lines.append("## Home Anticoagulants / Antiplatelets")
    lines.append("")
    ac = gc.get("home_anticoagulants", {})
    ac_val = ac.get("value") or []
    if ac_val:
        lines.append(_bullet_list(ac_val))
        lines.append(f"_Sources:{_source_tag(ac.get('sources', []))}_")
    else:
        lines.append("_(none identified)_")
    lines.append("")

    # ── Spine Clearance ─────────────────────────────────────────
    lines.append("---")
    lines.append("## Spine Clearance")
    lines.append("")
    spine = gc.get("spine_clearance", {})
    spine_status = spine.get("status", "UNKNOWN")
    spine_method = spine.get("method", "UNKNOWN")
    spine_details = spine.get("details", [])
    regions = spine.get("regions", {})
    cspine = regions.get("cspine", {})
    tlspine = regions.get("tlspine", {})
    if spine_status == "UNKNOWN" and not spine_details and not regions:
        lines.append("_(DATA NOT AVAILABLE)_")
    else:
        # Per-region display
        if regions:
            cspine_ord = cspine.get("ordered", "UNKNOWN")
            cspine_dt = cspine.get("final_dt")
            tlspine_ord = tlspine.get("ordered", "UNKNOWN")
            tlspine_dt = tlspine.get("final_dt")
            lines.append(
                f"**Cervical:** {cspine_ord}"
                f"{' (' + cspine_dt + ')' if cspine_dt else ''}  "
            )
            lines.append(
                f"**T/L:** {tlspine_ord}"
                f"{' (' + tlspine_dt + ')' if tlspine_dt else ''}  "
            )
        lines.append(f"**Overall:** {spine_status} — {spine_method}"
                      f"{_source_tag(spine.get('sources', []))}")
        if spine_details:
            lines.append("")
            lines.append(_bullet_list(spine_details))
    lines.append("")

    # ── DVT Prophylaxis ─────────────────────────────────────────
    lines.append("---")
    lines.append("## DVT Prophylaxis")
    lines.append("")
    dvt = gc.get("dvt_prophylaxis", {})
    dvt_agent = dvt.get("agent")
    if dvt_agent:
        lines.append(f"**Agent:** {dvt_agent}  ")
        if dvt.get("dose"):
            lines.append(f"**Dose:** {dvt['dose']}  ")
        if dvt.get("route"):
            lines.append(f"**Route:** {dvt['route']}  ")
        if dvt.get("first_order_dt"):
            lines.append(f"**First Order:** {dvt['first_order_dt']}  ")
        if dvt.get("first_admin_dt"):
            lines.append(f"**First Admin:** {dvt['first_admin_dt']}  ")
        else:
            lines.append("**First Admin:** _(not confirmed)_  ")
        lines.append(f"{_source_tag(dvt.get('sources', []))}")
    else:
        lines.append("_(DATA NOT AVAILABLE)_")
    dvt_warns = dvt.get("warnings", [])
    if dvt_warns:
        for w in dvt_warns:
            lines.append(f"- ⚠ {w}")
    lines.append("")

    # ── First ED Temperature ────────────────────────────────────
    lines.append("---")
    lines.append("## First ED Temperature")
    lines.append("")
    temp = gc.get("first_ed_temp", {})
    temp_val = temp.get("value")
    if temp_val:
        lines.append(f"**Temp:** {temp_val}  ")
        if temp.get("dt"):
            lines.append(f"**Recorded:** {temp['dt']}  ")
        lines.append(f"**Units:** {temp.get('units', 'UNKNOWN')}{_source_tag(temp.get('sources', []))}")
    else:
        lines.append("_(DATA NOT AVAILABLE)_")
    temp_warns = temp.get("warnings", [])
    if temp_warns:
        for w in temp_warns:
            lines.append(f"- ⚠ {w}")
    lines.append("")

    # ── GI Prophylaxis ──────────────────────────────────────────
    lines.append("---")
    lines.append("## GI Prophylaxis")
    lines.append("")
    gi = gc.get("gi_prophylaxis", {})
    gi_status = gi.get("status", "UNKNOWN")
    if gi_status in ("YES", "NO"):
        lines.append(f"**Status:** {gi_status}  ")
        if gi.get("agent"):
            lines.append(f"**Agent:** {gi['agent']}  ")
        if gi.get("first_order_dt"):
            lines.append(f"**Order dt:** {gi['first_order_dt']}  ")
        lines.append(f"{_source_tag(gi.get('sources', []))}")
    elif gi_status == "UNKNOWN":
        lines.append("_(DATA NOT AVAILABLE)_")
    else:
        lines.append(f"**Status:** {gi_status}")
    gi_warns = gi.get("warnings", [])
    if gi_warns:
        for w in gi_warns:
            lines.append(f"- ⚠ {w}")
    lines.append("")

    # ── Bowel Regimen ───────────────────────────────────────────
    lines.append("---")
    lines.append("## Bowel Regimen")
    lines.append("")
    bowel = gc.get("bowel_regimen", {})
    bowel_status = bowel.get("status", "UNKNOWN")
    if bowel_status in ("YES", "NO"):
        lines.append(f"**Status:** {bowel_status}  ")
        agents = bowel.get("agents", [])
        if agents:
            lines.append(f"**Agents:** {', '.join(agents)}  ")
        if bowel.get("first_order_dt"):
            lines.append(f"**Order dt:** {bowel['first_order_dt']}  ")
        lines.append(f"{_source_tag(bowel.get('sources', []))}")
    elif bowel_status == "UNKNOWN":
        lines.append("_(DATA NOT AVAILABLE)_")
    else:
        lines.append(f"**Status:** {bowel_status}")
    bowel_warns = bowel.get("warnings", [])
    if bowel_warns:
        for w in bowel_warns:
            lines.append(f"- ⚠ {w}")
    lines.append("")

    # ── Tourniquet ──────────────────────────────────────────────
    lines.append("---")
    lines.append("## Tourniquet")
    lines.append("")
    tq = gc.get("tourniquet", {})
    tq_placed = tq.get("placed", "UNKNOWN")
    if tq_placed == "YES":
        lines.append(f"**Placed:** YES  ")
        if tq.get("placed_time"):
            lines.append(f"**Placement Time:** {tq['placed_time']}  ")
        if tq.get("location"):
            lines.append(f"**Location:** {tq['location']}  ")
        tq_removed = tq.get("removed", "UNKNOWN")
        lines.append(f"**Removed:** {tq_removed}  ")
        if tq.get("removed_time"):
            lines.append(f"**Removal Time:** {tq['removed_time']}  ")
        if tq.get("details"):
            lines.append("")
            lines.append(_bullet_list(tq["details"]))
        lines.append(f"{_source_tag(tq.get('sources', []))}")
    elif tq_placed == "NO":
        lines.append("**Placed:** NO  ")
        lines.append(f"{_source_tag(tq.get('sources', []))}")
    else:
        lines.append("_(DATA NOT AVAILABLE)_")
    tq_warns = tq.get("warnings", [])
    if tq_warns:
        for w in tq_warns:
            lines.append(f"- ⚠ {w}")
    lines.append("")

    # ── Primary Survey ──────────────────────────────────────────
    lines.append("---")
    lines.append("## Primary Survey")
    lines.append("")
    ps = gc.get("primary_survey", {})
    if ps.get("raw_block"):
        if ps.get("airway"):
            lines.append(f"**Airway:** {ps['airway']}  ")
        if ps.get("breathing"):
            lines.append(f"**Breathing:** {ps['breathing']}  ")
        if ps.get("circulation"):
            lines.append(f"**Circulation:** {ps['circulation']}  ")
        if ps.get("disability"):
            lines.append(f"**Disability:** {ps['disability']}  ")
        if ps.get("exposure"):
            lines.append(f"**Exposure:** {ps['exposure']}  ")
        lines.append("")
        gcs = ps.get("gcs")
        if gcs is not None:
            gcs_label = str(gcs)
            if ps.get("gcs_intubated"):
                gcs_label += "T (intubated)"
            lines.append(f"**GCS:** {gcs_label}  ")
        else:
            lines.append("**GCS:** _(not extracted)_  ")
        pupils = ps.get("pupils")
        if pupils:
            lines.append(f"**Pupils:** {pupils}  ")
        lines.append("")
        fast_perf = ps.get("fast_performed", "UNKNOWN")
        fast_res = ps.get("fast_result", "UNKNOWN")
        lines.append(f"**FAST Performed:** {fast_perf}  ")
        if fast_perf == "YES":
            lines.append(f"**FAST Result:** {fast_res}  ")
        lines.append(f"{_source_tag(ps.get('sources', []))}")
    else:
        lines.append("_(DATA NOT AVAILABLE)_")
    ps_warns = ps.get("warnings", [])
    if ps_warns:
        for w in ps_warns:
            lines.append(f"- ⚠ {w}")
    lines.append("")

    # ── Admitting MD ────────────────────────────────────────────
    lines.append("---")
    lines.append("## Admitting / Signing Physician")
    lines.append("")
    amd = gc.get("admitting_md", {})
    if amd.get("name"):
        lines.append(f"**Name:** {amd['name']}  ")
        if amd.get("credential"):
            lines.append(f"**Credential:** {amd['credential']}  ")
        lines.append(f"**Role:** {amd.get('role', 'UNKNOWN')}  ")
        lines.append(f"{_source_tag(amd.get('sources', []))}")
    else:
        lines.append("_(not identified)_")
    amd_warns = amd.get("warnings", [])
    if amd_warns:
        for w in amd_warns:
            lines.append(f"- ⚠ {w}")
    lines.append("")

    # ── Anticoagulation Status ──────────────────────────────────
    lines.append("---")
    lines.append("## Anticoagulation Status")
    lines.append("")
    acs = gc.get("anticoag_status", {})
    ac_status = acs.get("status", "UNKNOWN")
    lines.append(f"**Status:** {ac_status}  ")
    ac_agents = acs.get("agents", [])
    if ac_agents:
        lines.append(f"**Agents:** {', '.join(ac_agents)}  ")
    hr_events = acs.get("hold_resume_events", [])
    if hr_events:
        lines.append("")
        lines.append("**Hold/Resume Events:**")
        for ev in hr_events:
            lines.append(f"- {ev.get('action', '?')}: {ev.get('agent', '?')} _{ev.get('doc_type', '')}_ — {ev.get('text', '')}")
    lines.append(f"{_source_tag(acs.get('sources', []))}")
    acs_warns = acs.get("warnings", [])
    if acs_warns:
        for w in acs_warns:
            lines.append(f"- ⚠ {w}")
    lines.append("")

    # ── ETOH ────────────────────────────────────────────────────
    lines.append("---")
    lines.append("## ETOH (Alcohol Level)")
    lines.append("")
    etoh = gc.get("etoh", {})
    if etoh.get("value") is not None:
        lines.append(f"**Value:** {etoh['value']}  ")
        if etoh.get("units"):
            lines.append(f"**Units:** {etoh['units']}  ")
        if etoh.get("date"):
            lines.append(f"**Date:** {etoh['date']}  ")
        lines.append(f"**Source:** {etoh.get('source_method', 'unknown')}{_source_tag(etoh.get('sources', []))}")
    else:
        lines.append("_(not found)_")
    etoh_warns = etoh.get("warnings", [])
    if etoh_warns:
        for w in etoh_warns:
            lines.append(f"- ⚠ {w}")
    lines.append("")

    # ── UDS ─────────────────────────────────────────────────────
    lines.append("---")
    lines.append("## UDS (Urine Drug Screen)")
    lines.append("")
    uds = gc.get("uds", {})
    if uds.get("performed"):
        lines.append(f"**Performed:** YES  ")
        if uds.get("date"):
            lines.append(f"**Date:** {uds['date']}  ")
        lines.append("")
        components = uds.get("components", {})
        if components:
            lines.append("| Component | Result |")
            lines.append("|-----------|--------|")
            for comp, res in sorted(components.items()):
                marker = "⚠" if res == "POSITIVE" else ""
                lines.append(f"| {comp} | {res} {marker}|")
        lines.append("")
        pos_flags = uds.get("positive_flags", [])
        if pos_flags:
            lines.append(f"**Positive:** {', '.join(pos_flags)}")
        lines.append(f"{_source_tag(uds.get('sources', []))}")
    else:
        lines.append("_(not performed / not found)_")
    uds_warns = uds.get("warnings", [])
    if uds_warns:
        for w in uds_warns:
            lines.append(f"- ⚠ {w}")
    lines.append("")

    # ── Base Deficit ────────────────────────────────────────────
    lines.append("---")
    lines.append("## Base Deficit")
    lines.append("")
    bd = gc.get("base_deficit", {})
    if bd.get("value") is not None:
        lines.append(f"**Value:** {bd['value']}  ")
        if bd.get("date"):
            lines.append(f"**Date:** {bd['date']}  ")
        lines.append(f"**Source:** {bd.get('source_method', 'unknown')}{_source_tag(bd.get('sources', []))}")
    else:
        lines.append("_(not found)_")
    if bd.get("is_category_1"):
        lines.append("")
        lines.append("**⚠ Category 1 Trauma**")
        if bd.get("value") is None:
            lines.append("- ⚠ Base deficit MISSING for Category 1 patient")
    bd_warns = bd.get("warnings", [])
    if bd_warns:
        for w in bd_warns:
            lines.append(f"- ⚠ {w}")
    lines.append("")

    # ── INR ─────────────────────────────────────────────────────
    lines.append("---")
    lines.append("## INR")
    lines.append("")
    inr = gc.get("inr", {})
    if inr.get("value") is not None:
        lines.append(f"**Value:** {inr['value']}  ")
        if inr.get("range"):
            lines.append(f"**Range:** {inr['range']}  ")
        if inr.get("date"):
            lines.append(f"**Date:** {inr['date']}  ")
        lines.append(f"**Source:** {inr.get('source_method', 'unknown')}{_source_tag(inr.get('sources', []))}")
    else:
        lines.append("_(not found)_")
    inr_warns = inr.get("warnings", [])
    if inr_warns:
        for w in inr_warns:
            lines.append(f"- ⚠ {w}")
    lines.append("")

    # ── Impression / Plan Timeline ──────────────────────────────
    lines.append("---")
    lines.append("## Impression / Plan Timeline")
    lines.append("")
    ip = gc.get("impression_plan", {})
    ip_entries = ip.get("entries", [])
    if ip_entries:
        for entry in ip_entries:
            dt = entry.get("date") or "unknown"
            dtype = entry.get("doc_type", "")
            lines.append(f"### {dt} ({dtype})")
            lines.append("")
            if entry.get("impression"):
                lines.append("**Impression:**")
                lines.append(f"> {entry['impression'][:500]}")
                lines.append("")
            if entry.get("plan"):
                lines.append("**Plan:**")
                lines.append(f"> {entry['plan'][:500]}")
                lines.append("")
        drift_flags = ip.get("drift_flags", [])
        if drift_flags:
            lines.append("### Drift Flags")
            lines.append("")
            for df in drift_flags:
                drift_type = df.get("type", "")
                if drift_type == "new_anticoag_in_plan":
                    lines.append(f"- ⚠ New anticoag in plan: **{df.get('agent')}** ({df.get('date')}, {df.get('doc_type')})")
                elif drift_type == "new_diagnosis_in_progress":
                    terms = ", ".join(df.get("new_terms", []))
                    lines.append(f"- ⚠ New diagnosis terms: **{terms}** ({df.get('date')}, {df.get('doc_type')})")
                else:
                    lines.append(f"- ⚠ {drift_type}: {df}")
            lines.append("")
    else:
        lines.append("_(no impression/plan sections found)_")
    ip_warns = ip.get("warnings", [])
    if ip_warns:
        for w in ip_warns:
            lines.append(f"- ⚠ {w}")
    lines.append("")

    # ── Warnings ────────────────────────────────────────────────
    all_warnings: list[str] = gc.get("warnings", [])
    # Collect field-level warnings
    for field_name in ["admitting_service", "mechanism_of_injury", "moi_narrative",
                       "hpi", "injuries",
                       "procedures", "consultants", "pmh", "home_anticoagulants"]:
        field = gc.get(field_name, {})
        for w in field.get("warnings", []):
            if isinstance(w, dict):
                all_warnings.append(
                    f"{w.get('code', 'warning')}: "
                    f"existing={w.get('existing_value', '?')} "
                    f"({w.get('existing_source', '?')}) vs "
                    f"discharge={w.get('discharge_value', '?')} "
                    f"({w.get('discharge_source', '?')})"
                )
            else:
                all_warnings.append(str(w))
    # Collect adjunct field warnings
    for adj_name in ["dvt_prophylaxis", "first_ed_temp", "gi_prophylaxis",
                     "bowel_regimen", "tourniquet",
                     "primary_survey", "admitting_md", "anticoag_status",
                     "etoh", "uds", "base_deficit", "inr", "impression_plan"]:
        adj = gc.get(adj_name, {})
        for w in adj.get("warnings", []):
            all_warnings.append(f"{adj_name}: {w}")

    lines.append("---")
    lines.append("## Data Warnings")
    lines.append("")
    if all_warnings:
        for w in all_warnings:
            lines.append(f"- ⚠ {w}")
    else:
        lines.append("_(no warnings)_")
    lines.append("")

    # ── Footer ──────────────────────────────────────────────────
    lines.append("---")
    lines.append(f"_GREEN CARD v1 • CerebralOS • {meta.get('created_at_utc', '')} UTC_")
    lines.append("")

    return "\n".join(lines)


# ── CLI ─────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description="GREEN CARD v1 Markdown renderer")
    ap.add_argument("--pat", required=True, help="Patient folder name")
    args = ap.parse_args()

    gc_path = _REPO_ROOT / "outputs" / "green_card" / args.pat / "green_card_v1.json"
    if not gc_path.is_file():
        print(f"FATAL: green_card_v1.json not found: {gc_path}", file=sys.stderr)
        return 1

    with open(gc_path, encoding="utf-8") as f:
        gc = json.load(f)

    md = render_green_card(gc)

    out_path = _REPO_ROOT / "outputs" / "green_card" / args.pat / "GREEN_CARD_v1.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md)

    print(f"GREEN CARD v1 MD: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
