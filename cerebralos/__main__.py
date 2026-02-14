#!/usr/bin/env python3
"""
CerebralOS CLI — Pure Python entry point.

Usage:
    python -m cerebralos run <patient.txt>
    python -m cerebralos run-all
    python -m cerebralos live <patient.txt>
    python -m cerebralos excel
    python -m cerebralos help

Works on Windows, macOS, and Linux without bash.
"""
from __future__ import annotations

import sys
import platform
import subprocess
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DATA_DIR = _PROJECT_ROOT / "data_raw"
_OUTPUT_DIR = _PROJECT_ROOT / "outputs" / "pi_reports"


def _resolve_patient_file(name: str) -> Path:
    """Resolve patient file from name, with or without .txt extension."""
    p = Path(name)
    if p.is_absolute() and p.exists():
        return p
    # Try as-is
    if p.exists():
        return p
    # Try in data_raw/
    candidate = _DATA_DIR / name
    if candidate.exists():
        return candidate
    # Try adding .txt
    if not name.endswith(".txt"):
        candidate = _DATA_DIR / f"{name}.txt"
        if candidate.exists():
            return candidate
        candidate = Path(f"{name}.txt")
        if candidate.exists():
            return candidate
    print(f"Error: Patient file not found: {name}")
    print(f"  Searched: {p}, {_DATA_DIR / name}")
    sys.exit(1)


def _open_file(path: Path) -> None:
    """Open a file with the platform default application."""
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


def cmd_run(args: list) -> int:
    """Run evaluation on a single patient."""
    if not args:
        print("Usage: python -m cerebralos run <patient_file>")
        return 1

    patient_path = _resolve_patient_file(args[0])
    print(f"CerebralOS -- Evaluating: {patient_path.name}")
    print()

    from cerebralos.ingestion.batch_eval import (
        _load_resources, evaluate_patient, generate_pi_report,
        _get_evaluable_protocols,
    )
    from cerebralos.reporting.html_report import generate_patient_html

    resources = _load_resources()
    evaluable_count = len(_get_evaluable_protocols(resources["protocols"]))
    ntds_count = len(resources.get("ntds_rulesets", {}))
    print(f"  {len(resources['action_patterns'])} pattern keys")
    print(f"  {evaluable_count} evaluable protocols")
    print(f"  {ntds_count} NTDS hospital events")
    print()

    evaluation = evaluate_patient(patient_path, resources)

    # Count outcomes
    outcomes = {}
    for r in evaluation["results"]:
        o = r["outcome"]
        outcomes[o] = outcomes.get(o, 0) + 1
    triggered = sum(v for k, v in outcomes.items() if k != "NOT_TRIGGERED")
    print(f"  Protocols: {triggered} triggered: {outcomes}")

    ntds_outcomes = {}
    for r in evaluation.get("ntds_results", []):
        o = r["outcome"]
        ntds_outcomes[o] = ntds_outcomes.get(o, 0) + 1
    if ntds_outcomes:
        print(f"  NTDS: {ntds_outcomes}")

    # Generate reports
    report_path = _OUTPUT_DIR / f"{patient_path.stem}_pi_report.txt"
    generate_pi_report(evaluation, report_path)
    print(f"  Text:  {report_path}")

    html_path = _OUTPUT_DIR / f"{patient_path.stem}_report.html"
    generate_patient_html(evaluation, html_path)
    print(f"  HTML:  {html_path}")

    # JSON
    import json
    json_path = _OUTPUT_DIR / f"{patient_path.stem}_results.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(evaluation, indent=2, default=str), encoding="utf-8")
    print(f"  JSON:  {json_path}")

    # Excel
    try:
        from cerebralos.reporting.excel_dashboard import update_excel_dashboard
        from cerebralos.classification.vrc_categories import classify_vrc_categories
        excel_path = _PROJECT_ROOT / "outputs" / "trauma_dashboard.xlsx"
        vrc = classify_vrc_categories(evaluation)
        update_excel_dashboard(evaluation, vrc, excel_path)
        print(f"  Excel: {excel_path}")
    except ImportError:
        pass
    except Exception as exc:
        print(f"  Excel: error -- {exc}")

    print()
    _open_file(html_path)
    print("Done.")
    return 0


def cmd_run_all(args: list) -> int:
    """Run evaluation on all patients in data_raw/."""
    from cerebralos.ingestion.batch_eval import main as batch_main

    # Build argv for batch_eval
    sys.argv = [
        "batch_eval",
        "--patient-dir", str(_DATA_DIR),
        "--all-reports",
        "--dashboard",
    ]
    batch_main()
    return 0


def cmd_live(args: list) -> int:
    """Run evaluation in live/provisional mode."""
    if not args:
        print("Usage: python -m cerebralos live <patient_file>")
        return 1

    patient_path = _resolve_patient_file(args[0])
    print(f"CerebralOS -- LIVE evaluation: {patient_path.name}")
    print()

    from cerebralos.ingestion.batch_eval import (
        _load_resources, evaluate_patient, generate_pi_report,
        _get_evaluable_protocols,
    )
    from cerebralos.reporting.html_report import generate_patient_html

    resources = _load_resources()
    evaluation = evaluate_patient(patient_path, resources)

    # Force live mode
    evaluation["is_live"] = True
    evaluation["has_discharge"] = False

    # Count outcomes
    outcomes = {}
    for r in evaluation["results"]:
        o = r["outcome"]
        outcomes[o] = outcomes.get(o, 0) + 1
    triggered = sum(v for k, v in outcomes.items() if k != "NOT_TRIGGERED")
    print(f"  Protocols: {triggered} triggered: {outcomes} [LIVE]")

    # Generate reports
    report_path = _OUTPUT_DIR / f"{patient_path.stem}_pi_report.txt"
    generate_pi_report(evaluation, report_path)
    print(f"  Text:  {report_path}")

    html_path = _OUTPUT_DIR / f"{patient_path.stem}_report.html"
    generate_patient_html(evaluation, html_path)
    print(f"  HTML:  {html_path}")

    print()
    _open_file(html_path)
    print("Done.")
    return 0


def cmd_excel(args: list) -> int:
    """Regenerate Excel dashboard from all patients."""
    print("CerebralOS -- Regenerating Excel dashboard")

    from cerebralos.ingestion.batch_eval import _load_resources, evaluate_patient
    from cerebralos.reporting.excel_dashboard import update_excel_dashboard
    from cerebralos.classification.vrc_categories import classify_vrc_categories

    resources = _load_resources()
    patient_files = sorted(_DATA_DIR.glob("*.txt"))
    excel_path = _PROJECT_ROOT / "outputs" / "trauma_dashboard.xlsx"

    for pf in patient_files:
        print(f"  Evaluating: {pf.name}")
        evaluation = evaluate_patient(pf, resources)
        vrc = classify_vrc_categories(evaluation)
        update_excel_dashboard(evaluation, vrc, excel_path)

    print(f"  Excel: {excel_path}")
    print("Done.")
    return 0


def cmd_help(args: list) -> int:
    """Show help."""
    print("CerebralOS Governance Engine")
    print()
    print("Usage: python -m cerebralos <command> [args]")
    print()
    print("Commands:")
    print("  run <patient.txt>    Evaluate a single patient (generates all reports)")
    print("  run-all              Evaluate all patients in data_raw/")
    print("  live <patient.txt>   Evaluate an in-hospital patient (provisional mode)")
    print("  excel                Regenerate Excel dashboard from all patients")
    print("  help                 Show this help message")
    print()
    print("Examples:")
    print("  python -m cerebralos run Dallas_Clark.txt")
    print("  python -m cerebralos run Dallas_Clark")
    print("  python -m cerebralos run-all")
    print("  python -m cerebralos live Lolita_Calcia")
    print()
    return 0


_COMMANDS = {
    "run": cmd_run,
    "run-all": cmd_run_all,
    "live": cmd_live,
    "excel": cmd_excel,
    "help": cmd_help,
}


def main() -> int:
    args = sys.argv[1:]
    if not args:
        return cmd_help([])

    command = args[0].lower()
    handler = _COMMANDS.get(command)
    if handler is None:
        print(f"Unknown command: {command}")
        print()
        return cmd_help([])

    return handler(args[1:])


if __name__ == "__main__":
    raise SystemExit(main())
