#!/usr/bin/env python3
"""
CerebralOS Governance Checklist Validator — Section 10.3.

Validates structural completeness and consistency across all domains.
Each domain check returns pass/fail with specific errors and warnings.

Domains:
- protocol: Protocol rule definitions, pattern keys, evaluation modes
- ntds: NTDS hospital event rules, gates, query keys
- evidence: Evidence pattern coverage and integrity
- output: Output assembly order and version stamps
- governance: System-level governance (failure log, versions, change log)

Usage (via CLI):
    python -m cerebralos governance checklist
    python -m cerebralos governance checklist --domain protocol
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from cerebralos import GOVERNANCE_VERSION, ENGINE_VERSION, RULES_VERSIONS
from cerebralos.governance.failure_log import FailureLog, FailureEntry


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_RULES_DIR = _PROJECT_ROOT / "rules"


@dataclass
class CheckResult:
    """Result of a single checklist item."""
    name: str
    passed: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class DomainResult:
    """Result of validating a domain."""
    domain: str
    passed: bool
    checks: List[CheckResult] = field(default_factory=list)
    error_count: int = 0
    warning_count: int = 0


# ---------------------------------------------------------------------------
# Domain validators
# ---------------------------------------------------------------------------

def check_protocol_domain() -> DomainResult:
    """Validate protocol rule definitions and pattern key references."""
    result = DomainResult(domain="protocol", passed=True)

    # 1. Protocol definitions file exists and loads
    proto_path = _RULES_DIR / "deaconess" / "protocols_deaconess_structured_v1.json"
    cr = CheckResult(name="protocol_definitions_load", passed=True)
    try:
        protocols = json.loads(proto_path.read_text(encoding="utf-8"))
        proto_list = protocols.get("protocols", [])
        cr.passed = len(proto_list) > 0
        if not cr.passed:
            cr.errors.append("No protocols found in definitions file")
    except FileNotFoundError:
        cr.passed = False
        cr.errors.append(f"Protocol definitions file missing: {proto_path}")
    except json.JSONDecodeError as e:
        cr.passed = False
        cr.errors.append(f"Protocol definitions JSON parse error: {e}")
    result.checks.append(cr)

    if not cr.passed:
        result.passed = False
        result.error_count = sum(len(c.errors) for c in result.checks)
        return result

    # 2. Load mapper for pattern key validation
    mapper_path = _RULES_DIR / "mappers" / "epic_deaconess_mapper_v1.json"
    shared_path = _RULES_DIR / "deaconess" / "shared_action_buckets_v1.json"
    all_pattern_keys: set = set()
    try:
        mapper = json.loads(mapper_path.read_text(encoding="utf-8"))
        all_pattern_keys.update(mapper.get("query_patterns", {}).keys())
    except Exception:
        pass
    try:
        shared = json.loads(shared_path.read_text(encoding="utf-8"))
        all_pattern_keys.update(shared.get("action_buckets", {}).keys())
    except Exception:
        pass

    # 3. Validate each protocol
    evaluable_count = 0
    context_count = 0
    duplicate_ids: Dict[str, int] = {}

    for proto in proto_list:
        pid = proto.get("protocol_id", "UNKNOWN")
        duplicate_ids[pid] = duplicate_ids.get(pid, 0) + 1
        eval_mode = proto.get("evaluation_mode", "")

        if eval_mode == "EVALUABLE":
            evaluable_count += 1
        elif eval_mode == "CONTEXT_ONLY":
            context_count += 1

        # Check required fields
        pcr = CheckResult(name=f"protocol_{pid}_structure", passed=True)
        for req_field in ("protocol_id", "name", "version", "evaluation_mode"):
            if not proto.get(req_field):
                pcr.passed = False
                pcr.errors.append(f"{pid}: missing required field '{req_field}'")

        # Check requirements exist for EVALUABLE protocols
        reqs = proto.get("requirements", [])
        if eval_mode == "EVALUABLE" and not reqs:
            pcr.passed = False
            pcr.errors.append(f"{pid}: EVALUABLE protocol with no requirements")

        # Check pattern key references
        for req in reqs:
            for condition in req.get("trigger_conditions", []):
                cond_str = str(condition).strip()
                # Strip @SOURCE_TYPE suffix
                if "@" in cond_str:
                    cond_str = cond_str.split("@", 1)[0].strip()
                # Skip temporal, numeric, and descriptive conditions
                if cond_str.startswith("temporal:") or ":" in cond_str:
                    continue
                if cond_str.startswith("protocol_") or cond_str.startswith("geriatric_"):
                    if cond_str not in all_pattern_keys:
                        pcr.warnings.append(f"{pid}: pattern key '{cond_str}' not in mapper")

        if not pcr.passed:
            result.checks.append(pcr)

    # 4. Check for duplicate IDs
    cr_dup = CheckResult(name="protocol_no_duplicates", passed=True)
    for pid, count in duplicate_ids.items():
        if count > 1:
            cr_dup.passed = False
            cr_dup.errors.append(f"Duplicate protocol_id: {pid} (appears {count} times)")
    result.checks.append(cr_dup)

    # 5. Evaluable protocol count check
    cr_count = CheckResult(name="protocol_evaluable_count", passed=evaluable_count > 0)
    if not cr_count.passed:
        cr_count.errors.append("No EVALUABLE protocols found")
    result.checks.append(cr_count)

    result.passed = all(c.passed for c in result.checks)
    result.error_count = sum(len(c.errors) for c in result.checks)
    result.warning_count = sum(len(c.warnings) for c in result.checks)
    return result


def check_ntds_domain() -> DomainResult:
    """Validate NTDS hospital event rules and gate structure."""
    result = DomainResult(domain="ntds", passed=True)

    # 1. Contract file
    contract_path = _RULES_DIR / "ntds" / "logic" / "contract_v1.json"
    cr = CheckResult(name="ntds_contract_load", passed=True)
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        if "outcomes" not in contract:
            cr.warnings.append("Contract missing 'outcomes' key")
    except FileNotFoundError:
        cr.passed = False
        cr.errors.append(f"NTDS contract file missing: {contract_path}")
    except json.JSONDecodeError as e:
        cr.passed = False
        cr.errors.append(f"NTDS contract JSON parse error: {e}")
    result.checks.append(cr)

    # 2. Load mapper for query key validation
    mapper_path = _RULES_DIR / "mappers" / "epic_deaconess_mapper_v1.json"
    all_query_keys: set = set()
    try:
        mapper = json.loads(mapper_path.read_text(encoding="utf-8"))
        all_query_keys.update(mapper.get("query_patterns", {}).keys())
    except Exception:
        pass

    # 3. Check all 21 event files exist and load
    events_dir = _RULES_DIR / "ntds" / "logic" / "2026"
    expected_events = list(range(1, 22))
    found_events: List[int] = []

    for eid in expected_events:
        pattern = f"{eid:02d}_*.json"
        matches = list(events_dir.glob(pattern)) if events_dir.exists() else []

        ecr = CheckResult(name=f"ntds_event_{eid:02d}_load", passed=True)
        if not matches:
            ecr.passed = False
            ecr.errors.append(f"NTDS event #{eid:02d}: rule file missing")
            result.checks.append(ecr)
            continue

        found_events.append(eid)
        try:
            event_data = json.loads(matches[0].read_text(encoding="utf-8"))
            meta = event_data.get("meta", {})

            # Check required meta fields
            for req_field in ("event_id", "canonical_name", "ntds_year"):
                if req_field not in meta:
                    ecr.passed = False
                    ecr.errors.append(f"Event #{eid:02d}: missing meta.{req_field}")

            # Check gates exist
            gates = event_data.get("gates", [])
            if not gates:
                ecr.warnings.append(f"Event #{eid:02d}: no gates defined")

            # Check query key references
            for gate in gates:
                for qk in gate.get("query_keys", []):
                    if str(qk) not in all_query_keys:
                        ecr.warnings.append(f"Event #{eid:02d}: query key '{qk}' not in mapper")
                qk_single = gate.get("query_key")
                if qk_single and str(qk_single) not in all_query_keys:
                    ecr.warnings.append(f"Event #{eid:02d}: query key '{qk_single}' not in mapper")

        except json.JSONDecodeError as e:
            ecr.passed = False
            ecr.errors.append(f"Event #{eid:02d}: JSON parse error: {e}")

        if not ecr.passed or ecr.warnings:
            result.checks.append(ecr)

    # 4. Coverage check
    cr_coverage = CheckResult(name="ntds_event_coverage", passed=len(found_events) == 21)
    if not cr_coverage.passed:
        missing = set(expected_events) - set(found_events)
        cr_coverage.errors.append(f"Missing NTDS events: {sorted(missing)}")
    result.checks.append(cr_coverage)

    result.passed = all(c.passed for c in result.checks)
    result.error_count = sum(len(c.errors) for c in result.checks)
    result.warning_count = sum(len(c.warnings) for c in result.checks)
    return result


def check_evidence_domain() -> DomainResult:
    """Validate evidence pattern coverage and integrity."""
    result = DomainResult(domain="evidence", passed=True)

    # 1. Mapper loads
    mapper_path = _RULES_DIR / "mappers" / "epic_deaconess_mapper_v1.json"
    cr = CheckResult(name="evidence_mapper_load", passed=True)
    try:
        mapper = json.loads(mapper_path.read_text(encoding="utf-8"))
        patterns = mapper.get("query_patterns", {})
    except FileNotFoundError:
        cr.passed = False
        cr.errors.append(f"Mapper file missing: {mapper_path}")
        result.checks.append(cr)
        result.passed = False
        result.error_count = 1
        return result
    except json.JSONDecodeError as e:
        cr.passed = False
        cr.errors.append(f"Mapper JSON parse error: {e}")
        result.checks.append(cr)
        result.passed = False
        result.error_count = 1
        return result
    result.checks.append(cr)

    # 2. Shared action buckets load
    shared_path = _RULES_DIR / "deaconess" / "shared_action_buckets_v1.json"
    cr_shared = CheckResult(name="evidence_shared_buckets_load", passed=True)
    shared_patterns = {}
    try:
        shared = json.loads(shared_path.read_text(encoding="utf-8"))
        shared_patterns = shared.get("action_buckets", {})
    except FileNotFoundError:
        cr_shared.warnings.append("Shared action buckets file missing (optional)")
    except json.JSONDecodeError as e:
        cr_shared.passed = False
        cr_shared.errors.append(f"Shared buckets JSON parse error: {e}")
    result.checks.append(cr_shared)

    # 3. Check for empty pattern lists
    all_patterns = {}
    all_patterns.update(shared_patterns)
    all_patterns.update(patterns)

    cr_empty = CheckResult(name="evidence_no_empty_patterns", passed=True)
    empty_keys: List[str] = []
    for key, pats in all_patterns.items():
        if not isinstance(pats, list) or len(pats) == 0:
            empty_keys.append(key)
    if empty_keys:
        cr_empty.passed = False
        cr_empty.errors.append(f"Empty pattern lists: {empty_keys[:10]}")
    result.checks.append(cr_empty)

    # 4. Pattern count
    cr_count = CheckResult(name="evidence_pattern_count", passed=len(all_patterns) > 0)
    if not cr_count.passed:
        cr_count.errors.append("No patterns found in mapper or shared buckets")
    result.checks.append(cr_count)

    # 5. Verify patterns compile as regex
    cr_regex = CheckResult(name="evidence_patterns_compile", passed=True)
    import re
    bad_patterns: List[str] = []
    for key, pats in all_patterns.items():
        if not isinstance(pats, list):
            continue
        for p in pats:
            try:
                re.compile(str(p), re.IGNORECASE)
            except re.error:
                bad_patterns.append(f"{key}: {p}")
    if bad_patterns:
        cr_regex.warnings.append(f"Non-regex patterns (will be escaped): {bad_patterns[:5]}")
    result.checks.append(cr_regex)

    result.passed = all(c.passed for c in result.checks)
    result.error_count = sum(len(c.errors) for c in result.checks)
    result.warning_count = sum(len(c.warnings) for c in result.checks)
    return result


def check_output_domain() -> DomainResult:
    """Validate output assembly and version stamps."""
    result = DomainResult(domain="output", passed=True)

    # 1. Version stamps present
    cr_ver = CheckResult(name="output_version_stamps", passed=True)
    if not GOVERNANCE_VERSION:
        cr_ver.passed = False
        cr_ver.errors.append("GOVERNANCE_VERSION not set")
    if not ENGINE_VERSION:
        cr_ver.passed = False
        cr_ver.errors.append("ENGINE_VERSION not set")
    if not RULES_VERSIONS:
        cr_ver.passed = False
        cr_ver.errors.append("RULES_VERSIONS not set")
    result.checks.append(cr_ver)

    # 2. Output directory writable
    output_dir = _PROJECT_ROOT / "outputs"
    cr_out = CheckResult(name="output_directory_writable", passed=True)
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        test_file = output_dir / ".checklist_test"
        test_file.write_text("test", encoding="utf-8")
        test_file.unlink()
    except Exception as e:
        cr_out.passed = False
        cr_out.errors.append(f"Output directory not writable: {e}")
    result.checks.append(cr_out)

    # 3. Check reporting modules importable
    cr_modules = CheckResult(name="output_reporting_modules", passed=True)
    for module_name in (
        "cerebralos.reporting.html_report",
        "cerebralos.reporting.narrative_report",
        "cerebralos.reporting.trauma_doc_extractor",
    ):
        try:
            __import__(module_name)
        except ImportError as e:
            cr_modules.passed = False
            cr_modules.errors.append(f"Cannot import {module_name}: {e}")
    result.checks.append(cr_modules)

    result.passed = all(c.passed for c in result.checks)
    result.error_count = sum(len(c.errors) for c in result.checks)
    result.warning_count = sum(len(c.warnings) for c in result.checks)
    return result


def check_governance_domain() -> DomainResult:
    """Validate governance infrastructure."""
    result = DomainResult(domain="governance", passed=True)

    # 1. Failure log writable
    cr_log = CheckResult(name="governance_failure_log", passed=True)
    try:
        log = FailureLog()
        log_path = log.path
        log_path.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        cr_log.passed = False
        cr_log.errors.append(f"Failure log not accessible: {e}")
    result.checks.append(cr_log)

    # 2. Governance version format
    cr_version = CheckResult(name="governance_version_format", passed=True)
    if not GOVERNANCE_VERSION.startswith("v"):
        cr_version.passed = False
        cr_version.errors.append(f"GOVERNANCE_VERSION should start with 'v': got '{GOVERNANCE_VERSION}'")
    result.checks.append(cr_version)

    # 3. Change log exists (GAP 10 — structural check only)
    change_log_path = _PROJECT_ROOT / "outputs" / "governance_change_log.jsonl"
    cr_changelog = CheckResult(name="governance_change_log", passed=True)
    if not change_log_path.exists():
        cr_changelog.warnings.append("Governance change log not yet created (will be created on first write)")
    result.checks.append(cr_changelog)

    result.passed = all(c.passed for c in result.checks)
    result.error_count = sum(len(c.errors) for c in result.checks)
    result.warning_count = sum(len(c.warnings) for c in result.checks)
    return result


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

_DOMAIN_VALIDATORS = {
    "protocol": check_protocol_domain,
    "ntds": check_ntds_domain,
    "evidence": check_evidence_domain,
    "output": check_output_domain,
    "governance": check_governance_domain,
}

ALL_DOMAINS = list(_DOMAIN_VALIDATORS.keys())


def run_checklist(
    domains: Optional[List[str]] = None,
    log_failures: bool = True,
    evaluation: Optional[Dict[str, Any]] = None,
) -> List[DomainResult]:
    """
    Run governance checklist across specified domains (or all).

    Per Section 19.3: Section 19 evidence rigor checks are automatically
    applied during governance checklist execution and cannot be selectively
    bypassed. If an evaluation dict is provided, Section 19 rigor checks
    are run against it and results are appended.

    Args:
        domains: List of domain names to check, or None for all.
        log_failures: If True, log failures to governance failure log.
        evaluation: Optional patient evaluation dict for Section 19 rigor checks.

    Returns:
        List of DomainResult objects.
    """
    if domains is None:
        domains = ALL_DOMAINS

    results: List[DomainResult] = []
    failure_log = FailureLog() if log_failures else None

    for domain in domains:
        validator = _DOMAIN_VALIDATORS.get(domain)
        if validator is None:
            dr = DomainResult(domain=domain, passed=False)
            dr.checks.append(CheckResult(
                name="unknown_domain",
                passed=False,
                errors=[f"Unknown domain: {domain}"],
            ))
            dr.error_count = 1
            results.append(dr)
            continue

        dr = validator()
        results.append(dr)

        # Log failures
        if failure_log and not dr.passed:
            for check in dr.checks:
                for error in check.errors:
                    failure_log.append(FailureEntry(
                        timestamp=datetime.now().isoformat(),
                        section="10.3",
                        category="structural",
                        description=f"[{domain}] {check.name}: {error}",
                        command="governance checklist",
                        detection_source="governance_checklist",
                    ))

    # Section 19: Evidence rigor checks (per 19.3 — runs automatically)
    if evaluation is not None:
        rigor_results = _run_section19(evaluation, failure_log)
        results.extend(rigor_results)

    return results


def _run_section19(
    evaluation: Dict[str, Any],
    failure_log: Optional[FailureLog] = None,
) -> List[DomainResult]:
    """
    Run Section 19 evidence rigor checks and convert to DomainResult format.

    Per Section 19.2: diagnostic-only, non-corrective, non-blocking.
    Per Section 19.6: failures logged, artifacts retained, no rewriting.
    """
    from cerebralos.governance.evidence_rigor import run_section19_for_evaluation

    rigor_results = run_section19_for_evaluation(evaluation)
    domain_results: List[DomainResult] = []

    for rr in rigor_results:
        dr = DomainResult(
            domain=f"section19_{rr.domain}",
            passed=rr.passed,
        )
        for rc in rr.checks:
            cr = CheckResult(
                name=f"s19_{rc.name}",
                passed=rc.passed,
                errors=rc.failures if not rc.passed else [],
            )
            dr.checks.append(cr)

        dr.error_count = sum(len(c.errors) for c in dr.checks)
        dr.warning_count = sum(len(c.warnings) for c in dr.checks)
        domain_results.append(dr)

        # Log Section 19 failures
        if failure_log and not dr.passed:
            patient_id = evaluation.get("patient_id", "")
            for check in dr.checks:
                for error in check.errors:
                    failure_log.append(FailureEntry(
                        timestamp=datetime.now().isoformat(),
                        section="19",
                        category="rule",
                        description=f"[{rr.domain}] {check.name}: {error}",
                        command="governance checklist",
                        detection_source="governance_checklist",
                        patient_id=patient_id,
                    ))

    return domain_results


def format_checklist_report(results: List[DomainResult]) -> str:
    """Format checklist results as a human-readable report."""
    lines: List[str] = []
    lines.append("=" * 60)
    lines.append("CEREBRAL OS — GOVERNANCE CHECKLIST")
    lines.append(f"Version: {GOVERNANCE_VERSION}  Engine: {ENGINE_VERSION}")
    lines.append("=" * 60)
    lines.append("")

    total_errors = 0
    total_warnings = 0
    all_passed = True

    for dr in results:
        status = "PASS" if dr.passed else "FAIL"
        lines.append(f"[{status}] Domain: {dr.domain}")

        if not dr.passed:
            all_passed = False

        for check in dr.checks:
            check_status = "PASS" if check.passed else "FAIL"
            lines.append(f"  [{check_status}] {check.name}")
            for error in check.errors:
                lines.append(f"    ERROR: {error}")
                total_errors += 1
            for warning in check.warnings:
                lines.append(f"    WARN:  {warning}")
                total_warnings += 1

        lines.append("")

    lines.append("-" * 60)
    overall = "PASS" if all_passed else "FAIL"
    lines.append(f"Overall: {overall}  Errors: {total_errors}  Warnings: {total_warnings}")
    lines.append(f"Checked: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 60)

    return "\n".join(lines)
