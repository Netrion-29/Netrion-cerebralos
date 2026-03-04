#!/usr/bin/env python3
"""
CerebralOS — NTDS Batch Runner (v1)

Evaluates all 21 NTDS hospital events for a single patient.
Reuses the same PatientFacts across events to avoid re-parsing.

Usage:
    python3 -m cerebralos.ntds_logic.run_all_events \
        --year 2026 --patient data_raw/Anna_Dennis.txt

Outputs:
    outputs/ntds/<slug>/ntds_event_<NN>_<year>_v1.json   (per event)
    outputs/ntds/<slug>/ntds_summary_<year>_v1.json        (rollup)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

from cerebralos.ntds_logic.model import Outcome
from cerebralos.ntds_logic.rules_loader import load_ruleset, load_mapper, _event_slug
from cerebralos.ntds_logic.build_patientfacts_from_txt import build_patientfacts
from cerebralos.ntds_logic.engine import evaluate_event, write_output, load_mapper as engine_load_mapper

REPO_ROOT = Path(__file__).resolve().parents[2]
ALL_EVENTS = list(range(1, 22))  # 1..21


def _slugify(name: str) -> str:
    """Deterministic, filesystem-safe slug: spaces → underscores, strip
    non-alphanumeric, collapse runs of underscores.

    Matches the canonical _slugify in cerebralos/ingest/parse_patient_txt.py.
    """
    s = name.strip().replace(" ", "_")
    s = re.sub(r"[^A-Za-z0-9_]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "UNKNOWN_PATIENT"


def run_all(year: int, patient_path: Path, arrival: str | None = None) -> List[Dict[str, Any]]:
    """Evaluate all 21 NTDS events for *patient_path* and return summary rows."""

    mapper = engine_load_mapper()
    qp = mapper.get("query_patterns", {})
    patient = build_patientfacts(patient_path, qp, arrival_time=arrival)

    slug = _slugify(patient_path.stem)
    out_dir = REPO_ROOT / "outputs" / "ntds" / slug
    out_dir.mkdir(parents=True, exist_ok=True)

    summary_rows: List[Dict[str, Any]] = []

    for eid in ALL_EVENTS:
        # Validate rules file exists before loading (mirrors engine.py CLI guard)
        rules_dir = REPO_ROOT / "rules" / "ntds" / "logic" / str(year)
        pattern = f"{eid:02d}_*.json"
        matches = list(rules_dir.glob(pattern)) if rules_dir.exists() else []
        if not matches:
            row = {
                "event_id": eid,
                "canonical_name": f"(unknown – no rules file for event {eid})",
                "outcome": "SKIPPED",
                "reason": f"No rules file matching {pattern} in {rules_dir}",
            }
            summary_rows.append(row)
            print(f"  Event {eid:02d}: SKIPPED (no rules file)")
            continue

        try:
            rs = load_ruleset(year, eid)
            event_rules = rs.event
            result = evaluate_event(event_rules, rs.contract, patient)

            out_path = out_dir / f"ntds_event_{eid:02d}_{year}_v1.json"
            write_output(result, out_path, patient=patient, event_rules=event_rules)

            row = {
                "event_id": result.event_id,
                "canonical_name": result.canonical_name,
                "outcome": result.outcome.value,
            }
            if result.hard_stop:
                row["hard_stop_reason"] = result.hard_stop.reason
            summary_rows.append(row)
            print(f"  Event {eid:02d} {result.canonical_name}: {result.outcome.value}")

        except SystemExit as exc:
            row = {
                "event_id": eid,
                "canonical_name": f"(load error for event {eid})",
                "outcome": "ERROR",
                "reason": str(exc),
            }
            summary_rows.append(row)
            print(f"  Event {eid:02d}: ERROR — {exc}")
        except Exception as exc:
            row = {
                "event_id": eid,
                "canonical_name": f"(runtime error for event {eid})",
                "outcome": "ERROR",
                "reason": str(exc),
            }
            summary_rows.append(row)
            print(f"  Event {eid:02d}: ERROR — {exc}")

    # Write rollup summary
    summary_path = out_dir / f"ntds_summary_{year}_v1.json"
    summary_path.write_text(json.dumps(summary_rows, indent=2), encoding="utf-8")
    print(f"\nSummary → {summary_path}")
    return summary_rows


def main() -> int:
    ap = argparse.ArgumentParser(description="Run all 21 NTDS events for a patient")
    ap.add_argument("--year", type=int, required=True, choices=[2025, 2026])
    ap.add_argument("--patient", required=True, help="Path to Epic TXT export")
    ap.add_argument("--arrival", default=None, help="Optional arrival_time override (ISO preferred)")
    args = ap.parse_args()

    p = Path(args.patient)
    if not p.exists():
        print(f"Patient file not found: {p}", file=sys.stderr)
        return 1

    print(f"== NTDS Batch Evaluation — {args.year} — {p.stem} ==\n")
    rows = run_all(args.year, p, arrival=args.arrival)

    # Fail-closed: any SKIPPED or ERROR event → non-zero exit
    failed = [r for r in rows if r.get("outcome") in ("SKIPPED", "ERROR")]
    if failed:
        print(f"\nFAIL-CLOSED: {len(failed)} event(s) SKIPPED/ERROR — exit 1", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
