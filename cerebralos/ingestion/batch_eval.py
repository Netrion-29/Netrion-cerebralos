#!/usr/bin/env python3
"""
CerebralOS Batch Protocol Evaluator and PI Report Generator.

Processes parsed patient files through all EVALUABLE protocols and generates
structured PI compliance reports.

Usage:
    python -m cerebralos.ingestion.batch_eval --patient data_raw/Dallas_Clark.txt
    python -m cerebralos.ingestion.batch_eval --patient-dir data_raw/ --report outputs/pi_report.txt
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add project to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from cerebralos.protocol_engine.engine import evaluate_protocol
from cerebralos.protocol_engine.build_protocolfacts import build_protocolfacts
from cerebralos.ntds_logic.engine import evaluate_event
from cerebralos.ntds_logic.build_patientfacts_from_txt import build_patientfacts
from cerebralos.ntds_logic.rules_loader import load_ruleset
from cerebralos import GOVERNANCE_VERSION, ENGINE_VERSION, RULES_VERSIONS


# ---------------------------------------------------------------------------
# Evidence serialization helpers
# ---------------------------------------------------------------------------

# Import evidence cleaning utilities
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cerebralos.reporting.evidence_utils import get_clean_snippet, is_historical_reference


def _serialize_protocol_evidence(ev) -> Dict[str, Any]:
    """Serialize a ProtocolEvidence object to a JSON-safe dict with cleaned text."""
    source_type_str = ev.source_type.value if hasattr(ev.source_type, "value") else str(ev.source_type)

    # For TRAUMA_HP, MAR, and LAB, preserve full text with newlines intact (don't use clean_evidence_text)
    if source_type_str in ("TRAUMA_HP", "MAR", "LAB"):
        if source_type_str == "TRAUMA_HP":
            max_len = 15000
        elif source_type_str == "MAR":
            max_len = 50000  # MAR can be very large (40k+ chars)
        else:  # LAB
            max_len = 10000  # Lab tables can be large
        raw_text = (ev.text or "")[:max_len] if hasattr(ev, 'text') else ""
        is_hist = is_historical_reference(raw_text)
        return {
            "source_type": source_type_str,
            "timestamp": ev.timestamp,
            "text": raw_text,  # Preserve structure for section/table parsing
            "text_raw": raw_text,
            "is_historical": is_hist,
            "pointer": ev.pointer.ref if ev.pointer else {},
        }

    # Per-type limits for clinical document extraction
    _TYPE_LIMITS = {
        "DISCHARGE": 8000,
        "PHYSICIAN_NOTE": 8000,
        "RADIOLOGY": 3000,
        "CONSULT_NOTE": 3000,
        "ED_NOTE": 3000,
        "NURSING_NOTE": 2000,
    }
    max_len = _TYPE_LIMITS.get(source_type_str, 1000)
    cleaned_text, is_hist = get_clean_snippet(ev, max_length=max_len, skip_if_historical=False)
    raw_text = (ev.text or "")[:max_len] if hasattr(ev, 'text') else ""

    return {
        "source_type": source_type_str,
        "timestamp": ev.timestamp,
        "text": cleaned_text or raw_text,
        "text_raw": raw_text,
        "is_historical": is_hist,
        "pointer": ev.pointer.ref if ev.pointer else {},
    }


def _serialize_ntds_evidence(ev) -> Dict[str, Any]:
    """Serialize an NTDS Evidence object to a JSON-safe dict with cleaned text."""
    source_type_str = ev.source_type.value if hasattr(ev.source_type, "value") else str(ev.source_type)

    # For TRAUMA_HP, MAR, and LAB, preserve full text with newlines intact
    if source_type_str in ("TRAUMA_HP", "MAR", "LAB"):
        if source_type_str == "TRAUMA_HP":
            max_len = 15000
        elif source_type_str == "MAR":
            max_len = 50000  # MAR can be very large
        else:  # LAB
            max_len = 10000  # Lab tables can be large
        raw_text = (ev.text or "")[:max_len] if hasattr(ev, 'text') else ""
        is_hist = is_historical_reference(raw_text)
        return {
            "source_type": source_type_str,
            "timestamp": ev.timestamp,
            "text": raw_text,  # Preserve structure for section/table parsing
            "text_raw": raw_text,
            "is_historical": is_hist,
            "pointer": ev.pointer.ref if ev.pointer else {},
        }

    # Per-type limits for clinical document extraction
    _TYPE_LIMITS = {
        "DISCHARGE": 8000,
        "PHYSICIAN_NOTE": 8000,
        "RADIOLOGY": 3000,
        "CONSULT_NOTE": 3000,
        "ED_NOTE": 3000,
        "NURSING_NOTE": 2000,
    }
    max_len = _TYPE_LIMITS.get(source_type_str, 1000)
    cleaned_text, is_hist = get_clean_snippet(ev, max_length=max_len, skip_if_historical=False)
    raw_text = (ev.text or "")[:max_len] if hasattr(ev, 'text') else ""

    return {
        "source_type": source_type_str,
        "timestamp": ev.timestamp,
        "text": cleaned_text or raw_text,
        "text_raw": raw_text,
        "is_historical": is_hist,
        "pointer": ev.pointer.ref if ev.pointer else {},
    }


# ---------------------------------------------------------------------------
# Resource loading
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

_PROTOCOLS_PATH = _PROJECT_ROOT / "rules" / "deaconess" / "protocols_deaconess_structured_v1.json"
_MAPPER_PATH = _PROJECT_ROOT / "rules" / "mappers" / "epic_deaconess_mapper_v1.json"
_CONTRACT_PATH = _PROJECT_ROOT / "rules" / "ntds" / "logic" / "contract_v1.json"
_SHARED_PATH = _PROJECT_ROOT / "rules" / "deaconess" / "shared_action_buckets_v1.json"


_NTDS_YEAR = 2026
_NTDS_EVENT_IDS = list(range(1, 22))  # Events 1-21


def _load_resources() -> Dict[str, Any]:
    """Load all protocol definitions, mapper, contract, shared buckets, and NTDS rulesets."""
    protocols = json.loads(_PROTOCOLS_PATH.read_text(encoding="utf-8"))
    mapper = json.loads(_MAPPER_PATH.read_text(encoding="utf-8"))
    shared = {}
    if _SHARED_PATH.exists():
        shared = json.loads(_SHARED_PATH.read_text(encoding="utf-8"))

    contract = {"evidence": {"max_items_per_requirement": 8}}
    if _CONTRACT_PATH.exists():
        contract = json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))

    # Build action patterns
    action_patterns = {}
    action_patterns.update(shared.get("action_buckets", {}))
    action_patterns.update(mapper.get("query_patterns", {}))

    # Load NTDS rulesets for all 21 events
    ntds_rulesets: Dict[int, Any] = {}
    for eid in _NTDS_EVENT_IDS:
        try:
            rs = load_ruleset(_NTDS_YEAR, eid)
            ntds_rulesets[eid] = rs
        except SystemExit:
            pass  # skip events with missing rule files

    return {
        "protocols": protocols,
        "action_patterns": action_patterns,
        "contract": contract,
        "ntds_rulesets": ntds_rulesets,
        "query_patterns": mapper.get("query_patterns", {}),
    }


def _get_evaluable_protocols(protocols: Dict) -> List[Dict]:
    """Return only protocols that are EVALUABLE with requirements defined."""
    evaluable = []
    for proto in protocols.get("protocols", []):
        if proto.get("evaluation_mode") != "EVALUABLE":
            continue
        reqs = proto.get("requirements", [])
        if not reqs:
            continue
        evaluable.append(proto)
    return evaluable


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------
def evaluate_patient(
    patient_path: Path,
    resources: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Evaluate a single patient file against all EVALUABLE protocols.

    Returns dict with patient info and protocol results.
    """
    # Build ProtocolFacts from parsed patient file
    patient = build_protocolfacts(
        patient_path,
        resources["action_patterns"],
    )

    # Extract patient metadata from file header
    patient_id = (patient.facts or {}).get("patient_id", patient_path.stem)
    arrival_time = (patient.facts or {}).get("arrival_time", "")

    # Read extra metadata lines (PATIENT_NAME, DOB, TRAUMA_CATEGORY)
    extra_meta = {}
    try:
        with open(patient_path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith("PATIENT_NAME:"):
                    extra_meta["patient_name"] = stripped.split(":", 1)[1].strip()
                elif stripped.startswith("DOB:"):
                    extra_meta["dob"] = stripped.split(":", 1)[1].strip()
                elif stripped.startswith("TRAUMA_CATEGORY:"):
                    extra_meta["trauma_category"] = stripped.split(":", 1)[1].strip()
                elif stripped.startswith("[") or not stripped:
                    break
    except Exception:
        pass

    evaluable = _get_evaluable_protocols(resources["protocols"])
    results = []

    # Detect live/discharge status
    has_discharge = any(
        e.source_type.value == "DISCHARGE" if hasattr(e.source_type, "value")
        else str(e.source_type) == "DISCHARGE"
        for e in patient.evidence
    )

    # Serialize all evidence blocks for trauma summary / daily notes
    all_evidence_snippets = []
    for e in patient.evidence:
        all_evidence_snippets.append(_serialize_protocol_evidence(e))

    for proto in evaluable:
        try:
            result = evaluate_protocol(proto, resources["contract"], patient)
            results.append({
                "protocol_id": result.protocol_id,
                "protocol_name": result.protocol_name,
                "outcome": result.outcome.value,
                "step_trace": [
                    {
                        "requirement_id": step.requirement_id,
                        "passed": step.passed,
                        "reason": step.reason,
                        "missing_data": step.missing_data,
                        "evidence_count": len(step.evidence),
                        "evidence_snippets": [_serialize_protocol_evidence(e) for e in step.evidence[:4]],
                        "match_details": [
                            {
                                "pattern_key": md.pattern_key,
                                "matched_text": md.matched_text,
                                "context": md.context[:200],
                            }
                            for md in step.match_details
                        ] if step.match_details else [],
                    }
                    for step in result.step_trace
                ],
                "warnings": result.warnings,
            })
        except Exception as e:
            results.append({
                "protocol_id": proto.get("protocol_id", "UNKNOWN"),
                "protocol_name": proto.get("protocol_name", "Unknown"),
                "outcome": "ERROR",
                "error": str(e),
                "step_trace": [],
                "warnings": [],
            })

    return {
        "patient_id": patient_id,
        "patient_name": extra_meta.get("patient_name", ""),
        "dob": extra_meta.get("dob", ""),
        "trauma_category": extra_meta.get("trauma_category", ""),
        "arrival_time": arrival_time,
        "source_file": str(patient_path),
        "evidence_blocks": len(patient.evidence),
        "has_discharge": has_discharge,
        "is_live": not has_discharge,
        "all_evidence_snippets": all_evidence_snippets,
        "protocols_evaluated": len(results),
        "results": results,
        "ntds_results": _evaluate_ntds(patient_path, resources),
        "governance_version": GOVERNANCE_VERSION,
        "engine_version": ENGINE_VERSION,
        "rules_versions": RULES_VERSIONS,
    }


def _evaluate_ntds(
    patient_path: Path,
    resources: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Evaluate a single patient file against all 21 NTDS hospital events.

    Returns list of event result dicts.
    """
    ntds_rulesets = resources.get("ntds_rulesets", {})
    query_patterns = resources.get("query_patterns", {})
    if not ntds_rulesets:
        return []

    # Build NTDS PatientFacts from the same parsed patient file
    ntds_patient = build_patientfacts(patient_path, query_patterns)

    ntds_results: List[Dict[str, Any]] = []
    for eid in sorted(ntds_rulesets.keys()):
        rs = ntds_rulesets[eid]
        try:
            result = evaluate_event(rs.event, rs.contract, ntds_patient)
            gate_trace = []
            for g in result.gate_trace:
                gate_trace.append({
                    "gate": g.gate,
                    "passed": g.passed,
                    "reason": g.reason,
                    "evidence_count": len(g.evidence),
                    "evidence_snippets": [_serialize_ntds_evidence(e) for e in g.evidence[:4]],
                })
            ntds_results.append({
                "event_id": result.event_id,
                "canonical_name": result.canonical_name,
                "outcome": result.outcome.value,
                "gate_trace": gate_trace,
                "warnings": result.warnings,
            })
        except Exception as e:
            meta = rs.event.get("meta", {})
            ntds_results.append({
                "event_id": eid,
                "canonical_name": meta.get("canonical_name", "Unknown"),
                "outcome": "ERROR",
                "error": str(e),
                "gate_trace": [],
                "warnings": [],
            })

    return ntds_results


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------
def generate_pi_report(
    evaluation: Dict[str, Any],
    output_path: Optional[Path] = None,
) -> str:
    """
    Generate a human-readable PI compliance report.

    Returns the report text. Optionally writes to file.
    """
    lines = []
    lines.append("=" * 70)
    lines.append("CEREBRAL OS — PROTOCOL COMPLIANCE REPORT")
    lines.append("=" * 70)
    lines.append("")

    # Patient header
    lines.append(f"Patient:          {evaluation.get('patient_name', 'Unknown')}")
    lines.append(f"Patient ID/MRN:   {evaluation.get('patient_id', 'Unknown')}")
    lines.append(f"DOB:              {evaluation.get('dob', 'Unknown')}")
    lines.append(f"Arrival:          {evaluation.get('arrival_time', 'Unknown')}")
    lines.append(f"Trauma Category:  {evaluation.get('trauma_category', 'N/A')}")
    lines.append(f"Evidence Blocks:  {evaluation.get('evidence_blocks', 0)}")
    lines.append(f"Source:           {evaluation.get('source_file', 'Unknown')}")
    lines.append("")

    results = evaluation.get("results", [])

    # Categorize results
    triggered = [r for r in results if r["outcome"] != "NOT_TRIGGERED"]
    not_triggered = [r for r in results if r["outcome"] == "NOT_TRIGGERED"]
    compliant = [r for r in triggered if r["outcome"] == "COMPLIANT"]
    non_compliant = [r for r in triggered if r["outcome"] == "NON_COMPLIANT"]
    indeterminate = [r for r in triggered if r["outcome"] == "INDETERMINATE"]
    errors = [r for r in triggered if r["outcome"] == "ERROR"]

    # Summary
    lines.append("-" * 70)
    lines.append("SUMMARY")
    lines.append("-" * 70)
    lines.append(f"Protocols evaluated:  {len(results)}")
    lines.append(f"Triggered:            {len(triggered)}")
    lines.append(f"  COMPLIANT:          {len(compliant)}")
    lines.append(f"  NON_COMPLIANT:      {len(non_compliant)}")
    lines.append(f"  INDETERMINATE:      {len(indeterminate)}")
    if errors:
        lines.append(f"  ERROR:              {len(errors)}")
    lines.append(f"Not triggered:        {len(not_triggered)}")
    lines.append("")

    # NON_COMPLIANT (highest priority for PI review)
    if non_compliant:
        lines.append("-" * 70)
        lines.append("NON-COMPLIANT PROTOCOLS (REQUIRES PI REVIEW)")
        lines.append("-" * 70)
        for r in non_compliant:
            _append_protocol_detail(lines, r)
        lines.append("")

    # INDETERMINATE (needs documentation review)
    if indeterminate:
        lines.append("-" * 70)
        lines.append("INDETERMINATE PROTOCOLS (DOCUMENTATION GAPS)")
        lines.append("-" * 70)
        for r in indeterminate:
            _append_protocol_detail(lines, r)
        lines.append("")

    # COMPLIANT (good news)
    if compliant:
        lines.append("-" * 70)
        lines.append("COMPLIANT PROTOCOLS")
        lines.append("-" * 70)
        for r in compliant:
            lines.append(f"  [COMPLIANT] {r['protocol_name']}")
        lines.append("")

    # NOT_TRIGGERED (for reference)
    if not_triggered:
        lines.append("-" * 70)
        lines.append("NOT TRIGGERED (protocol did not apply)")
        lines.append("-" * 70)
        for r in not_triggered:
            lines.append(f"  [ — ] {r['protocol_name']}")
        lines.append("")

    # ERRORS
    if errors:
        lines.append("-" * 70)
        lines.append("ERRORS")
        lines.append("-" * 70)
        for r in errors:
            lines.append(f"  [ERROR] {r['protocol_name']}: {r.get('error', 'Unknown error')}")
        lines.append("")

    # ---- NTDS Hospital Events Section ----
    ntds_results = evaluation.get("ntds_results", [])
    if ntds_results:
        ntds_yes = [r for r in ntds_results if r["outcome"] == "YES"]
        ntds_no = [r for r in ntds_results if r["outcome"] == "NO"]
        ntds_excluded = [r for r in ntds_results if r["outcome"] == "EXCLUDED"]
        ntds_unable = [r for r in ntds_results if r["outcome"] == "UNABLE_TO_DETERMINE"]
        ntds_errors = [r for r in ntds_results if r["outcome"] == "ERROR"]

        lines.append("=" * 70)
        lines.append("NTDS HOSPITAL EVENTS (2026)")
        lines.append("=" * 70)
        lines.append(f"Events evaluated:         {len(ntds_results)}")
        lines.append(f"  YES (event occurred):   {len(ntds_yes)}")
        lines.append(f"  NO:                     {len(ntds_no)}")
        lines.append(f"  EXCLUDED:               {len(ntds_excluded)}")
        lines.append(f"  UNABLE TO DETERMINE:    {len(ntds_unable)}")
        if ntds_errors:
            lines.append(f"  ERROR:                  {len(ntds_errors)}")
        lines.append("")

        # YES events — highest priority for PI review
        if ntds_yes:
            lines.append("-" * 70)
            lines.append("HOSPITAL EVENTS DETECTED (YES)")
            lines.append("-" * 70)
            for r in ntds_yes:
                eid = r["event_id"]
                name = r["canonical_name"]
                lines.append(f"  [YES] #{eid:02d} {name}")
                for g in r.get("gate_trace", []):
                    status = "PASS" if g["passed"] else "FAIL"
                    lines.append(f"    {g['gate']}: {status} — {g['reason']}")
                    # Evidence snippets for passed gates
                    if g["passed"]:
                        for s in g.get("evidence_snippets", [])[:2]:
                            src = s.get("source_type", "")
                            ts = s.get("timestamp") or ""
                            text = (s.get("text") or "").strip()
                            lines.append(f"      [{src}] {ts}")
                            if text:
                                display = text[:120].replace('\n', ' ')
                                if len(text) > 120:
                                    display += "..."
                                lines.append(f'        "{display}"')
            lines.append("")

        # UNABLE_TO_DETERMINE — documentation gaps
        if ntds_unable:
            lines.append("-" * 70)
            lines.append("UNABLE TO DETERMINE (documentation gaps)")
            lines.append("-" * 70)
            for r in ntds_unable:
                eid = r["event_id"]
                name = r["canonical_name"]
                lines.append(f"  [UNABLE] #{eid:02d} {name}")
                for g in r.get("gate_trace", []):
                    if not g["passed"]:
                        lines.append(f"    {g['gate']}: FAIL — {g['reason']}")
            lines.append("")

        # NO events — confirmed absent (compact list)
        if ntds_no:
            lines.append("-" * 70)
            lines.append("NO EVENTS DETECTED")
            lines.append("-" * 70)
            for r in ntds_no:
                lines.append(f"  [NO] #{r['event_id']:02d} {r['canonical_name']}")
            lines.append("")

        # EXCLUDED events
        if ntds_excluded:
            lines.append("-" * 70)
            lines.append("EXCLUDED (present on arrival or other exclusion)")
            lines.append("-" * 70)
            for r in ntds_excluded:
                lines.append(f"  [EXCLUDED] #{r['event_id']:02d} {r['canonical_name']}")
            lines.append("")

        # NTDS ERRORS
        if ntds_errors:
            lines.append("-" * 70)
            lines.append("NTDS ERRORS")
            lines.append("-" * 70)
            for r in ntds_errors:
                lines.append(f"  [ERROR] #{r['event_id']:02d} {r['canonical_name']}: {r.get('error', 'Unknown error')}")
            lines.append("")

    # ---- Narrative Trauma Summary ----
    try:
        from cerebralos.reporting.narrative_report import (
            generate_narrative_trauma_summary,
            generate_daily_notes,
        )
        from cerebralos.reporting.medication_timeline import (
            extract_blood_thinner_timeline,
            format_blood_thinner_report,
        )
        from cerebralos.reporting.lab_values import (
            extract_lab_values,
            format_lab_report,
        )
        from cerebralos.reporting.progress_note_delta import (
            extract_note_deltas,
            format_note_deltas_report,
        )

        narrative = generate_narrative_trauma_summary(evaluation)
        if narrative:
            lines.append("=" * 70)
            lines.append("NARRATIVE TRAUMA SUMMARY")
            lines.append("=" * 70)
            lines.append("")
            lines.append(narrative)
            lines.append("")

        # Add blood thinner timeline
        blood_thinners = extract_blood_thinner_timeline(evaluation)
        if blood_thinners:
            lines.append("=" * 70)
            blood_thinner_report = format_blood_thinner_report(blood_thinners)
            lines.append(blood_thinner_report)
            lines.append("")

        # Add lab values
        lab_values = extract_lab_values(evaluation)
        if lab_values:
            lines.append("=" * 70)
            lab_report = format_lab_report(lab_values)
            lines.append(lab_report)
            lines.append("")

        # Add progress note deltas (what changed day-to-day)
        note_deltas = extract_note_deltas(evaluation)
        if note_deltas:
            lines.append("=" * 70)
            delta_report = format_note_deltas_report(note_deltas)
            lines.append(delta_report)
            lines.append("")

        # Add daily notes
        daily = generate_daily_notes(evaluation)
        if daily:
            lines.append("=" * 70)
            lines.append(daily)
            lines.append("")
    except Exception as e:
        # If narrative generation fails, continue without it
        lines.append("")
        lines.append(f"(Narrative summary generation error: {e})")
        lines.append("")

    lines.append("=" * 70)
    lines.append(f"Report generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"CerebralOS Governance Engine {GOVERNANCE_VERSION} (engine {ENGINE_VERSION})")
    lines.append("=" * 70)

    report = "\n".join(lines)

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report, encoding="utf-8")

    return report


def _append_protocol_detail(lines: List[str], result: Dict) -> None:
    """Append detailed protocol evaluation info to report lines."""
    from cerebralos.reporting.protocol_explainer import explain_pattern_key, explain_requirement

    outcome = result["outcome"]
    name = result["protocol_name"]
    lines.append(f"  [{outcome}] {name}")

    for step in result.get("step_trace", []):
        req_id = step["requirement_id"]
        passed = "PASS" if step["passed"] else "FAIL"
        reason = step["reason"]

        # Use plain language requirement name
        req_name = explain_requirement(req_id)
        lines.append(f"    {req_name}: {passed}")
        lines.append(f"      {reason}")

        if step.get("missing_data"):
            # Convert pattern keys to plain language
            missing_explained = [explain_pattern_key(key) for key in step['missing_data']]
            lines.append(f"      Missing:")
            for explained in missing_explained:
                lines.append(f"        • {explained}")
        # Match details — explain WHY evidence matched
        match_details = step.get("match_details", [])
        if match_details:
            lines.append(f"      Matched on:")
            for md in match_details[:4]:
                pkey = explain_pattern_key(md.get("pattern_key", ""))
                matched_text = md.get("matched_text", "")
                lines.append(f"        • {pkey}: \"{matched_text}\"")
        # Evidence snippets
        snippets = step.get("evidence_snippets", [])
        if snippets:
            lines.append(f"      Evidence ({step.get('evidence_count', len(snippets))} items):")
            for s in snippets[:3]:
                src = s.get("source_type", "")
                ts = s.get("timestamp") or ""
                text = (s.get("text") or "").strip()
                lines.append(f"        [{src}] {ts}")
                if text:
                    # Show first 120 chars of evidence text
                    display = text[:120].replace('\n', ' ')
                    if len(text) > 120:
                        display += "..."
                    lines.append(f'          "{display}"')
    lines.append("")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    import argparse
    import platform
    import subprocess

    ap = argparse.ArgumentParser(
        description="CerebralOS — Evaluate patient files against all protocols and NTDS events"
    )
    ap.add_argument("--patient", "-p", help="Single parsed patient .txt file")
    ap.add_argument("--patient-dir", help="Directory of parsed patient files")
    ap.add_argument("--report", "-r", help="Output report file path")
    ap.add_argument("--json", action="store_true", help="Also output JSON results")
    ap.add_argument("--html", action="store_true", help="Generate HTML reports per patient")
    ap.add_argument("--dashboard", action="store_true", help="Generate dashboard index.html (implies --html for batch)")
    ap.add_argument("--excel", action="store_true", help="Update Excel trauma dashboard")
    ap.add_argument("--live", action="store_true", help="Force live mode display on all patients")
    ap.add_argument("--all-reports", action="store_true", help="Generate all formats (text + HTML + JSON + dashboard + Excel)")
    ap.add_argument("--output-dir", help="Custom output directory (default: outputs/pi_reports)")
    ap.add_argument("--open", action="store_true", default=False, help="Auto-open HTML report in browser")
    ap.add_argument("--no-open", action="store_true", help="Suppress auto-open")

    args = ap.parse_args()

    if not args.patient and not args.patient_dir:
        ap.print_help()
        sys.exit(1)

    # --all-reports implies everything
    if args.all_reports:
        args.html = True
        args.json = True
        args.dashboard = True
        args.excel = True

    # --dashboard implies --html
    if args.dashboard:
        args.html = True

    # Auto-open: default ON for single patient with --html, OFF for batch
    auto_open = args.open or (args.html and args.patient and not args.patient_dir)
    if args.no_open:
        auto_open = False

    report_dir = Path(args.output_dir) if args.output_dir else Path("outputs") / "pi_reports"

    print("Loading resources...")
    resources = _load_resources()
    evaluable_count = len(_get_evaluable_protocols(resources["protocols"]))
    ntds_count = len(resources.get("ntds_rulesets", {}))
    print(f"  {len(resources['action_patterns'])} pattern keys")
    print(f"  {evaluable_count} evaluable protocols")
    print(f"  {ntds_count} NTDS hospital events")
    print()

    patient_files = []
    if args.patient:
        patient_files.append(Path(args.patient))
    elif args.patient_dir:
        pdir = Path(args.patient_dir)
        patient_files = sorted(pdir.glob("*.txt"))

    all_evaluations = []
    last_html_path = None

    for pf in patient_files:
        if not pf.exists():
            print(f"ERROR: File not found: {pf}")
            continue

        print(f"Evaluating: {pf.name}")
        evaluation = evaluate_patient(pf, resources)

        # Force live mode if --live flag
        if args.live:
            evaluation["is_live"] = True
            evaluation["has_discharge"] = False

        all_evaluations.append(evaluation)

        # Count protocol outcomes
        outcomes = {}
        for r in evaluation["results"]:
            o = r["outcome"]
            outcomes[o] = outcomes.get(o, 0) + 1

        triggered = sum(v for k, v in outcomes.items() if k != "NOT_TRIGGERED")
        live_tag = " [LIVE]" if evaluation.get("is_live") else ""
        print(f"  → Protocols: {triggered} triggered: {outcomes}{live_tag}")

        # Count NTDS outcomes
        ntds_outcomes = {}
        for r in evaluation.get("ntds_results", []):
            o = r["outcome"]
            ntds_outcomes[o] = ntds_outcomes.get(o, 0) + 1
        if ntds_outcomes:
            print(f"  → NTDS: {ntds_outcomes}")

        # Generate text report
        report_path = report_dir / f"{pf.stem}_pi_report.txt"
        generate_pi_report(evaluation, report_path)
        print(f"  → Text: {report_path}")

        # Generate HTML report
        if args.html:
            from cerebralos.reporting.html_report import generate_patient_html
            html_path = report_dir / f"{pf.stem}_report.html"
            generate_patient_html(evaluation, html_path)
            last_html_path = html_path
            print(f"  → HTML: {html_path}")

        # Save JSON
        if args.json:
            json_path = report_dir / f"{pf.stem}_results.json"
            json_path.parent.mkdir(parents=True, exist_ok=True)
            json_path.write_text(
                json.dumps(evaluation, indent=2, default=str),
                encoding="utf-8",
            )
            print(f"  → JSON: {json_path}")

        print()

    # Dashboard
    if args.dashboard and len(all_evaluations) > 0:
        from cerebralos.reporting.dashboard import generate_dashboard
        dash_path = generate_dashboard(all_evaluations, report_dir)
        print(f"Dashboard: {dash_path}")

    # Excel
    if args.excel:
        try:
            from cerebralos.reporting.excel_dashboard import update_excel_dashboard
            from cerebralos.classification.vrc_categories import classify_vrc_categories
            excel_path = Path("outputs") / "trauma_dashboard.xlsx"
            for ev in all_evaluations:
                vrc = classify_vrc_categories(ev)
                update_excel_dashboard(ev, vrc, excel_path)
            print(f"Excel: {excel_path}")
        except ImportError as ie:
            print(f"Excel: skipped ({ie})")
        except Exception as exc:
            print(f"Excel: error — {exc}")

    # Aggregate summary
    if len(all_evaluations) > 1:
        _print_aggregate_summary(all_evaluations)

    # Auto-open
    if auto_open and last_html_path and last_html_path.exists():
        _open_file(last_html_path)

    print("Done.")


def _open_file(path: Path) -> None:
    """Open a file using the platform's default application."""
    import platform
    import subprocess
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.run(["open", str(path)], check=False)
        elif system == "Linux":
            subprocess.run(["xdg-open", str(path)], check=False)
        elif system == "Windows":
            subprocess.run(["start", "", str(path)], shell=True, check=False)
    except Exception:
        pass


def _print_aggregate_summary(evaluations: List[Dict]) -> None:
    """Print aggregate summary across all patients."""
    print("=" * 70)
    print("AGGREGATE SUMMARY")
    print("=" * 70)
    print(f"Patients evaluated: {len(evaluations)}")
    print()

    # Aggregate protocol outcome counts
    protocol_outcomes: Dict[str, Dict[str, int]] = {}
    for ev in evaluations:
        for r in ev["results"]:
            pid = r["protocol_id"]
            outcome = r["outcome"]
            if pid not in protocol_outcomes:
                protocol_outcomes[pid] = {}
            protocol_outcomes[pid][outcome] = protocol_outcomes[pid].get(outcome, 0) + 1

    # Show protocols with non-compliant or indeterminate results
    print("Protocols with findings:")
    for pid, outcomes in sorted(protocol_outcomes.items()):
        nc = outcomes.get("NON_COMPLIANT", 0)
        ind = outcomes.get("INDETERMINATE", 0)
        comp = outcomes.get("COMPLIANT", 0)
        if nc > 0 or ind > 0 or comp > 0:
            parts = []
            if comp: parts.append(f"{comp} compliant")
            if nc: parts.append(f"{nc} non-compliant")
            if ind: parts.append(f"{ind} indeterminate")
            print(f"  {pid}: {', '.join(parts)}")
    print()

    # Aggregate NTDS event outcome counts
    ntds_event_outcomes: Dict[int, Dict[str, int]] = {}
    ntds_event_names: Dict[int, str] = {}
    for ev in evaluations:
        for r in ev.get("ntds_results", []):
            eid = r["event_id"]
            outcome = r["outcome"]
            ntds_event_names[eid] = r["canonical_name"]
            if eid not in ntds_event_outcomes:
                ntds_event_outcomes[eid] = {}
            ntds_event_outcomes[eid][outcome] = ntds_event_outcomes[eid].get(outcome, 0) + 1

    if ntds_event_outcomes:
        print("NTDS Hospital Events with YES findings:")
        any_yes = False
        for eid in sorted(ntds_event_outcomes.keys()):
            outcomes = ntds_event_outcomes[eid]
            yes_count = outcomes.get("YES", 0)
            if yes_count > 0:
                any_yes = True
                name = ntds_event_names.get(eid, "Unknown")
                total = sum(outcomes.values())
                print(f"  #{eid:02d} {name}: {yes_count}/{total} patients")
        if not any_yes:
            print("  (none)")
        print()

        # NTDS summary totals
        total_yes = sum(o.get("YES", 0) for o in ntds_event_outcomes.values())
        total_no = sum(o.get("NO", 0) for o in ntds_event_outcomes.values())
        total_excl = sum(o.get("EXCLUDED", 0) for o in ntds_event_outcomes.values())
        total_unable = sum(o.get("UNABLE_TO_DETERMINE", 0) for o in ntds_event_outcomes.values())
        total_err = sum(o.get("ERROR", 0) for o in ntds_event_outcomes.values())
        print(f"NTDS totals across {len(evaluations)} patients × {len(ntds_event_outcomes)} events:")
        print(f"  YES: {total_yes}  NO: {total_no}  EXCLUDED: {total_excl}  UNABLE: {total_unable}", end="")
        if total_err:
            print(f"  ERROR: {total_err}")
        else:
            print()

    print("=" * 70)


if __name__ == "__main__":
    main()
