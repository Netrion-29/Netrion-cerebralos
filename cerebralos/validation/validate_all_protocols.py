#!/usr/bin/env python3
"""
Validate Protocol Engine: definitions, patterns, and test fixtures.

Checks:
1. Protocol JSON structure validity
2. Pattern keys exist in mapper
3. acceptable_evidence uses valid SourceType names
4. Test fixtures produce expected outcomes
5. Summary report across all protocols

Usage:
    PYTHONPATH=. python3 cerebralos/validation/validate_all_protocols.py
    PYTHONPATH=. python3 cerebralos/validation/validate_all_protocols.py --run-fixtures
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))


@dataclass
class ProtocolValidationResult:
    """Result of validating a single protocol."""
    protocol_id: str
    protocol_name: str
    evaluation_mode: str
    passed: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    requirement_count: int = 0
    pattern_keys_used: List[str] = field(default_factory=list)
    pattern_keys_missing: List[str] = field(default_factory=list)


@dataclass
class FixtureResult:
    """Result of running a test fixture."""
    fixture_path: str
    protocol_id: str
    expected_outcome: Optional[str]
    actual_outcome: str
    passed: bool
    reason: str = ""


VALID_SOURCE_TYPES = {
    "TRAUMA_HP", "ED_NOTE", "PHYSICIAN_NOTE", "CONSULT_NOTE",
    "NURSING_NOTE", "IMAGING", "LAB", "MAR",
    "OPERATIVE_NOTE", "PROCEDURE", "DISCHARGE", "RADIOLOGY",
}

VALID_REQUIREMENT_TYPES = {"MANDATORY", "CONDITIONAL", "CONTRAINDICATED"}

REQUIRED_REQUIREMENT_FIELDS = {"id", "requirement_type", "trigger_conditions", "acceptable_evidence"}


class ProtocolValidator:
    """Validator for Deaconess trauma protocol definitions."""

    def __init__(self):
        self.protocols_path = REPO_ROOT / "rules" / "deaconess" / "protocols_deaconess_structured_v1.json"
        self.mapper_path = REPO_ROOT / "rules" / "mappers" / "epic_deaconess_mapper_v1.json"
        self.shared_path = REPO_ROOT / "rules" / "protocols" / "protocol_shared_v1.json"
        self.fixtures_dir = REPO_ROOT / "tests" / "fixtures" / "protocols"

        self.mapper_patterns: Dict[str, Any] = {}
        self.shared_patterns: Dict[str, Any] = {}
        self.protocols: List[Dict[str, Any]] = []
        self.results: List[ProtocolValidationResult] = []
        self.fixture_results: List[FixtureResult] = []

    def load_mapper(self) -> bool:
        """Load mapper pattern keys."""
        try:
            data = json.loads(self.mapper_path.read_text(encoding="utf-8"))
            self.mapper_patterns = data.get("query_patterns", {})
            print(f"  Mapper: {len(self.mapper_patterns)} pattern keys loaded")
            return True
        except Exception as e:
            print(f"  CRITICAL: Failed to load mapper: {e}")
            return False

    def load_shared(self) -> bool:
        """Load shared pattern buckets."""
        try:
            data = json.loads(self.shared_path.read_text(encoding="utf-8"))
            self.shared_patterns = data.get("action_buckets", {})
            print(f"  Shared: {len(self.shared_patterns)} action buckets loaded")
            return True
        except Exception as e:
            print(f"  WARNING: Failed to load shared patterns: {e}")
            return True  # Non-fatal

    def load_protocols(self) -> bool:
        """Load protocol definitions."""
        try:
            data = json.loads(self.protocols_path.read_text(encoding="utf-8"))
            self.protocols = data.get("protocols", [])
            print(f"  Protocols: {len(self.protocols)} definitions loaded")
            return True
        except Exception as e:
            print(f"  CRITICAL: Failed to load protocols: {e}")
            return False

    def _strip_source_suffix(self, key: str) -> str:
        """Strip @SOURCE_TYPE suffix from pattern key."""
        if "@" in key:
            return key.split("@", 1)[0].strip()
        return key

    def _is_numeric_threshold(self, key: str) -> bool:
        """Check if condition is a numeric threshold (parameter:operator:threshold)."""
        parts = key.split(":")
        return len(parts) == 3 and parts[1].strip() in ["<", "<=", ">", ">=", "==", "!="]

    def validate_protocol(self, protocol: Dict[str, Any]) -> ProtocolValidationResult:
        """Validate a single protocol definition."""
        pid = protocol.get("protocol_id", "UNKNOWN")
        pname = protocol.get("name", "Unknown")
        eval_mode = protocol.get("evaluation_mode", "UNKNOWN")
        requirements = protocol.get("requirements", [])

        result = ProtocolValidationResult(
            protocol_id=pid,
            protocol_name=pname,
            evaluation_mode=eval_mode,
            passed=True,
            requirement_count=len(requirements),
        )

        # Skip validation for non-evaluable protocols
        if eval_mode != "EVALUABLE":
            result.warnings.append(f"Skipped: evaluation_mode={eval_mode}")
            return result

        # Check for empty requirements
        if not requirements:
            result.warnings.append("No requirements defined (EVALUABLE but empty)")
            return result

        # Validate each requirement
        all_pattern_keys = set(self.mapper_patterns.keys()) | set(self.shared_patterns.keys())

        for req in requirements:
            req_id = req.get("id", "UNKNOWN")

            # Check required fields
            missing_fields = REQUIRED_REQUIREMENT_FIELDS - set(req.keys())
            if missing_fields:
                result.errors.append(f"{req_id}: Missing fields: {missing_fields}")
                result.passed = False

            # Check requirement_type
            req_type = req.get("requirement_type", "")
            if req_type not in VALID_REQUIREMENT_TYPES:
                result.errors.append(f"{req_id}: Invalid requirement_type: {req_type}")
                result.passed = False

            # Check acceptable_evidence source types
            for src in req.get("acceptable_evidence", []):
                if src not in VALID_SOURCE_TYPES:
                    result.warnings.append(f"{req_id}: acceptable_evidence '{src}' not a SourceType enum name")

            # Check trigger_conditions for pattern keys
            for condition in req.get("trigger_conditions", []):
                condition_str = str(condition).strip()

                # Skip numeric thresholds
                if self._is_numeric_threshold(condition_str):
                    result.pattern_keys_used.append(f"{condition_str} (numeric)")
                    continue

                # Strip source suffix for lookup
                pattern_key = self._strip_source_suffix(condition_str)

                if pattern_key in all_pattern_keys:
                    result.pattern_keys_used.append(condition_str)
                else:
                    # It's a descriptive string (keyword matching fallback)
                    result.warnings.append(
                        f"{req_id}: '{condition_str[:60]}' is not a pattern key (uses keyword fallback)"
                    )

        return result

    def run_fixture(self, fixture_path: Path, protocol_id: str, expected_outcome: Optional[str]) -> FixtureResult:
        """Run a test fixture and check outcome."""
        try:
            from cerebralos.protocol_engine.engine import evaluate_protocol, write_protocol_output
            from cerebralos.protocol_engine.rules_loader import load_protocol_ruleset
            from cerebralos.protocol_engine.build_protocolfacts import build_protocolfacts

            rs = load_protocol_ruleset(protocol_id)

            # Build action patterns
            action_patterns = {}
            action_patterns.update(rs.shared.get("action_buckets", {}))
            mapper_data = json.loads(self.mapper_path.read_text(encoding="utf-8"))
            action_patterns.update(mapper_data.get("query_patterns", {}))

            patient = build_protocolfacts(fixture_path, action_patterns)
            result = evaluate_protocol(rs.protocol, rs.contract, patient)

            actual = result.outcome.value
            passed = (expected_outcome is None) or (actual == expected_outcome)

            return FixtureResult(
                fixture_path=str(fixture_path.name),
                protocol_id=protocol_id,
                expected_outcome=expected_outcome,
                actual_outcome=actual,
                passed=passed,
                reason="" if passed else f"Expected {expected_outcome}, got {actual}",
            )
        except Exception as e:
            return FixtureResult(
                fixture_path=str(fixture_path.name),
                protocol_id=protocol_id,
                expected_outcome=expected_outcome,
                actual_outcome="ERROR",
                passed=False,
                reason=str(e),
            )

    def discover_fixtures(self) -> List[tuple[Path, str, Optional[str]]]:
        """Discover test fixtures and infer expected outcomes from filenames.

        Convention: <protocol_stem>_<outcome>.txt
        Example: tbi_compliant.txt → TRAUMATIC_BRAIN_INJURY_MANAGEMENT, COMPLIANT
        """
        fixtures = []
        if not self.fixtures_dir.exists():
            return fixtures

        # Map fixture prefixes to protocol IDs
        prefix_map = {
            "tbi": "TRAUMATIC_BRAIN_INJURY_MANAGEMENT",
            "rib": "RIB_FRACTURE_MANAGEMENT",
            "blunt_abd": "BLUNT_ABDOMINAL_TRAUMA",
            "blunt_chest": "BLUNT_CHEST_TRAUMA",
            "penetrating_chest": "PENETRATING_CHEST_INJURY",
            "lab_studies": "LABORATORY_STUDIES_NEEDED_IN_TRAUMA_RESUSCITATION",
            "rotem": "ROTEM_GUIDELINE",
            "hypothermia": "HYPOTHERMIA_PREVENTION_AND_TREATMENT",
            "base_deficit": "MONITORING_BASE_DEFICIT",
            "vascular": "VASCULAR_INTERVENTION_GUIDELINE",
            "hanging": "SUSPECTED_HANGING_GUIDELINE",
            "blood_transfusion": "BLOOD_AND_BLOOD_PRODUCT_TRANSFUSION",
            "ob_trauma": "MANAGEMENT_AND_TRIAGE_OF_THE_OBSTETRICAL_TRAUMA_PATIENT",
            "autopsy": "AUTOPSY_IN_THE_TRAUMA_PATIENT",
            "nat": "NONACCIDENTAL_TRAUMA_NAT_IN_THE_PEDIATRIC_PATIENT",
            "role_trauma": "ROLE_OF_TRAUMA_SERVICES_IN_THE_ADMISSION_OR_CONSULTATION_OF_TRAUMA_PATIENTS",
            "transmed_gsw": "MANAGEMENT_OF_TRANSMEDIASTINAL_GUNSHOT_WOUNDS",
            "pen_abd": "PENETRATING_ABDOMINAL_TRAUMA",
            "pen_neck": "PENETRATING_NECK_INJURY",
            "periph_vasc": "PERIPHERAL_VASCULAR_TRAUMA",
            "bcvi": "BLUNT_CEREBROVASCULAR_INJURY_BCVI",
            "ert": "EMERGENCY_RESUSCITATIVE_THORACOTOMY",
            "traumatic_arrest": "TRAUMATIC_ARREST",
            "drowning": "DROWNING",
            "burns": "MANAGEMENT_AND_TRIAGE_OF_BURNED_PATIENTS",
            "solid_organ": "MANAGEMENT_OF_SOLID_ORGAN_INJURIES",
            "rib2": "RIB_FRACTURE_MANAGEMENT__2",
            "dvt_adult": "DVT_PROPHYLAXIS_ADULT_TRAUMA_PATIENT",
            "dvt_peds": "DVT_PROPHYLAXIS_PEDIATRIC_TRAUMA_PATIENT",
            "geriatric_hip": "GERIATRIC_HIP_FRACTURE_GUIDELINE",
            "geriatric": "GERIATRIC_TRAUMA_GUIDELINE",
            "sbirt": "SCREENING_OF_THE_TRAUMA_PATIENT_FOR_ALCOHOL_ANDOR_DRUG_USE_SBIRT",
            "mental_health": "MENTAL_HEALTH_SCREENING_FOR_THE_TRAUMA_PATIENT",
            "msk": "MANAGEMENT_OF_SEVERE_MUSCULOSKELETAL_INJURIES",
            "neurosurg": "MANAGEMENT_OF_NEUROSURGICAL_EMERGENCIES",
            "spinal": "SPINAL_CLEARANCE_AND_SPINAL_INJURY_MANAGEMENT",
            "pelvic": "MANAGEMENT_AND_STABILIZATION_OF_PELVIC_FRACTURES",
        }

        outcome_map = {
            "compliant": "COMPLIANT",
            "noncompliant": "NON_COMPLIANT",
            "not_triggered": "NOT_TRIGGERED",
            "indeterminate": "INDETERMINATE",
        }

        for txt_file in sorted(self.fixtures_dir.glob("*.txt")):
            stem = txt_file.stem
            protocol_id = None
            expected = None

            # Try to match prefix and outcome (longest prefix first to avoid ambiguity)
            for prefix, pid in sorted(prefix_map.items(), key=lambda x: -len(x[0])):
                if stem.startswith(prefix):
                    protocol_id = pid
                    remainder = stem[len(prefix):].lstrip("_")
                    for suffix, outcome in outcome_map.items():
                        if remainder == suffix:
                            expected = outcome
                            break
                    break

            if protocol_id:
                fixtures.append((txt_file, protocol_id, expected))
            else:
                # Unknown fixture - run against TBI as default
                fixtures.append((txt_file, "TRAUMATIC_BRAIN_INJURY_MANAGEMENT", None))

        return fixtures

    def run(self, run_fixtures: bool = False) -> int:
        """Run full validation suite."""
        print("=" * 70)
        print("PROTOCOL VALIDATION SUITE")
        print("=" * 70)

        # Load resources
        print("\n--- Loading Resources ---")
        if not self.load_mapper():
            return 1
        self.load_shared()
        if not self.load_protocols():
            return 1

        # Validate all protocols
        print("\n--- Validating Protocol Definitions ---")
        evaluable_count = 0
        evaluable_with_reqs = 0
        pattern_key_protocols = 0
        keyword_only_protocols = 0

        for protocol in self.protocols:
            result = self.validate_protocol(protocol)
            self.results.append(result)

            if result.evaluation_mode == "EVALUABLE":
                evaluable_count += 1
                if result.requirement_count > 0:
                    evaluable_with_reqs += 1
                if result.pattern_keys_used:
                    pattern_key_protocols += 1
                else:
                    keyword_only_protocols += 1

        # Print protocol summary
        errors_total = sum(len(r.errors) for r in self.results)
        warnings_total = sum(len(r.warnings) for r in self.results)
        failed_count = sum(1 for r in self.results if not r.passed)

        print(f"\n  Total protocols: {len(self.protocols)}")
        print(f"  EVALUABLE: {evaluable_count} ({evaluable_with_reqs} with requirements)")
        print(f"  Using pattern keys: {pattern_key_protocols}")
        print(f"  Using keyword fallback only: {keyword_only_protocols}")
        print(f"  Errors: {errors_total}")
        print(f"  Warnings: {warnings_total}")

        # Print errors
        if errors_total > 0:
            print("\n--- Errors ---")
            for r in self.results:
                for err in r.errors:
                    print(f"  [FAIL] {r.protocol_id}: {err}")

        # Print warnings for protocols with keyword fallback
        keyword_warnings = [
            r for r in self.results
            if any("not a pattern key" in w for w in r.warnings)
        ]
        if keyword_warnings:
            print(f"\n--- Protocols Using Keyword Fallback ({len(keyword_warnings)}) ---")
            for r in keyword_warnings:
                kw_warnings = [w for w in r.warnings if "not a pattern key" in w]
                print(f"  {r.protocol_id}: {len(kw_warnings)} conditions using fallback")

        # Print acceptable_evidence warnings
        ae_warnings = [
            r for r in self.results
            if any("not a SourceType" in w for w in r.warnings)
        ]
        if ae_warnings:
            print(f"\n--- Protocols With Non-Enum acceptable_evidence ({len(ae_warnings)}) ---")
            for r in ae_warnings:
                for w in r.warnings:
                    if "not a SourceType" in w:
                        print(f"  {r.protocol_id}: {w}")

        # Run test fixtures
        if run_fixtures:
            print("\n--- Running Test Fixtures ---")
            fixtures = self.discover_fixtures()
            if not fixtures:
                print("  No test fixtures found")
            else:
                print(f"  Found {len(fixtures)} test fixtures")
                for fixture_path, protocol_id, expected in fixtures:
                    fr = self.run_fixture(fixture_path, protocol_id, expected)
                    self.fixture_results.append(fr)

                    status = "PASS" if fr.passed else "FAIL"
                    expected_str = fr.expected_outcome or "any"
                    print(f"  [{status}] {fr.fixture_path}: {fr.actual_outcome} (expected: {expected_str})")
                    if not fr.passed:
                        print(f"         {fr.reason}")

                fixture_pass = sum(1 for fr in self.fixture_results if fr.passed)
                fixture_total = len(self.fixture_results)
                print(f"\n  Fixtures: {fixture_pass}/{fixture_total} passed")

        # Final summary
        print("\n" + "=" * 70)
        overall_pass = (failed_count == 0)
        if run_fixtures:
            fixture_failures = sum(1 for fr in self.fixture_results if not fr.passed)
            overall_pass = overall_pass and (fixture_failures == 0)

        if overall_pass:
            print("RESULT: ALL CHECKS PASSED")
        else:
            print(f"RESULT: {failed_count} protocol(s) failed validation")
            if run_fixtures:
                fixture_failures = sum(1 for fr in self.fixture_results if not fr.passed)
                if fixture_failures:
                    print(f"        {fixture_failures} fixture(s) failed")

        print("=" * 70)
        return 0 if overall_pass else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate protocol definitions and test fixtures")
    parser.add_argument("--run-fixtures", action="store_true", help="Run test fixtures and check outcomes")
    args = parser.parse_args()

    validator = ProtocolValidator()
    return validator.run(run_fixtures=args.run_fixtures)


if __name__ == "__main__":
    sys.exit(main())
