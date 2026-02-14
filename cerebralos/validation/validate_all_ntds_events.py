#!/usr/bin/env python3
"""
Validate NTDS 2026 event logic files and mapper patterns.

Checks:
1. JSON syntax validity
2. Required fields present
3. Query_keys exist in mapper
4. No duplicate gate IDs
5. Required gates have fail_outcome
6. Proper structure and references
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple
from dataclasses import dataclass


@dataclass
class ValidationResult:
    """Result of validation check."""
    passed: bool
    errors: List[str]
    warnings: List[str]
    event_id: int = None
    event_name: str = None


class NTDSValidator:
    """Validator for NTDS event logic files."""

    def __init__(self, rules_dir: Path, mapper_path: Path):
        self.rules_dir = rules_dir
        self.mapper_path = mapper_path
        self.mapper_patterns: Dict[str, List[str]] = {}
        self.results: List[ValidationResult] = []

    def load_mapper(self) -> bool:
        """Load mapper patterns."""
        try:
            with open(self.mapper_path, 'r') as f:
                mapper_data = json.load(f)
                self.mapper_patterns = mapper_data.get('query_patterns', {})
                print(f"✓ Loaded mapper v{mapper_data.get('meta', {}).get('version', 'unknown')} with {len(self.mapper_patterns)} pattern keys")
                return True
        except json.JSONDecodeError as e:
            print(f"✗ CRITICAL: Mapper JSON syntax error: {e}")
            return False
        except Exception as e:
            print(f"✗ CRITICAL: Failed to load mapper: {e}")
            return False

    def validate_event_file(self, event_path: Path) -> ValidationResult:
        """Validate a single event logic file."""
        errors = []
        warnings = []
        event_id = None
        event_name = None

        # Check 1: JSON syntax
        try:
            with open(event_path, 'r') as f:
                event_data = json.load(f)
        except json.JSONDecodeError as e:
            return ValidationResult(
                passed=False,
                errors=[f"JSON syntax error: {e}"],
                warnings=[],
                event_id=None,
                event_name=str(event_path.name)
            )
        except Exception as e:
            return ValidationResult(
                passed=False,
                errors=[f"Failed to read file: {e}"],
                warnings=[],
                event_id=None,
                event_name=str(event_path.name)
            )

        # Extract metadata
        meta = event_data.get('meta', {})
        event_id = meta.get('event_id')
        event_name = meta.get('canonical_name', str(event_path.name))

        # Check 2: Required top-level fields
        required_fields = ['meta', 'gates', 'reporting']
        for field in required_fields:
            if field not in event_data:
                errors.append(f"Missing required field: {field}")

        # Check 3: Required meta fields
        required_meta = ['event_id', 'canonical_name', 'ntds_year', 'version']
        for field in required_meta:
            if field not in meta:
                errors.append(f"Missing required meta field: {field}")

        # Check 4: Validate gates
        gates = event_data.get('gates', [])
        if not gates:
            errors.append("No gates defined")

        gate_ids = set()
        for i, gate in enumerate(gates):
            # Check for duplicate gate IDs
            gate_id = gate.get('gate_id')
            if gate_id:
                if gate_id in gate_ids:
                    errors.append(f"Duplicate gate_id: {gate_id}")
                gate_ids.add(gate_id)
            else:
                errors.append(f"Gate {i} missing gate_id")

            # Check required gate fields
            if not gate.get('gate_name'):
                errors.append(f"Gate {gate_id or i} missing gate_name")
            if not gate.get('gate_type'):
                errors.append(f"Gate {gate_id or i} missing gate_type")

            # Check required gates have fail_outcome OR pass_outcome (for early-exit patterns)
            if gate.get('required', False):
                if not gate.get('fail_outcome') and not gate.get('pass_outcome'):
                    errors.append(f"Required gate {gate_id} missing fail_outcome or pass_outcome")

            # Check query_keys exist in mapper
            query_keys = gate.get('query_keys', [])
            if isinstance(query_keys, list):
                for key in query_keys:
                    if key not in self.mapper_patterns:
                        errors.append(f"Gate {gate_id}: query_key '{key}' not found in mapper")
            elif isinstance(query_keys, str):
                if query_keys not in self.mapper_patterns:
                    errors.append(f"Gate {gate_id}: query_key '{query_keys}' not found in mapper")

            # Check exclude_noise_keys exist in mapper or shared
            exclude_keys = gate.get('exclude_noise_keys', [])
            for key in exclude_keys:
                if key not in self.mapper_patterns and not key.endswith('_noise'):
                    warnings.append(f"Gate {gate_id}: exclude_noise_key '{key}' not found in mapper (may be in shared)")

        # Check 5: Validate exclusions
        exclusions = event_data.get('exclusions', [])
        for i, exclusion in enumerate(exclusions):
            excl_id = exclusion.get('gate_id', f"exclusion_{i}")

            # Check required exclusion fields
            if not exclusion.get('gate_type'):
                errors.append(f"Exclusion {excl_id} missing gate_type")
            if not exclusion.get('reason'):
                warnings.append(f"Exclusion {excl_id} missing reason")

            # Check query_keys exist in mapper
            query_keys = exclusion.get('query_keys', [])
            for key in query_keys:
                if key not in self.mapper_patterns:
                    errors.append(f"Exclusion {excl_id}: query_key '{key}' not found in mapper")

        # Check 6: Validate reporting section
        reporting = event_data.get('reporting', {})
        if not reporting:
            warnings.append("Empty reporting section")

        passed = len(errors) == 0
        return ValidationResult(
            passed=passed,
            errors=errors,
            warnings=warnings,
            event_id=event_id,
            event_name=event_name
        )

    def validate_all_events(self) -> Tuple[int, int]:
        """Validate all event files in the rules directory."""
        event_files = sorted(self.rules_dir.glob('*.json'))

        # Filter out non-event files
        event_files = [f for f in event_files if f.name[0].isdigit()]

        print(f"\n{'='*80}")
        print(f"Validating {len(event_files)} NTDS 2026 Event Files")
        print(f"{'='*80}\n")

        passed_count = 0
        failed_count = 0

        for event_file in event_files:
            result = self.validate_event_file(event_file)
            self.results.append(result)

            if result.passed:
                passed_count += 1
                status = "✓ PASS"
                color = ""
            else:
                failed_count += 1
                status = "✗ FAIL"
                color = ""

            print(f"{status} Event {result.event_id:2d}: {result.event_name}")

            if result.errors:
                for error in result.errors:
                    print(f"    ERROR: {error}")

            if result.warnings:
                for warning in result.warnings:
                    print(f"    WARNING: {warning}")

            if not result.errors and not result.warnings:
                print(f"    All checks passed")

            print()

        return passed_count, failed_count

    def print_summary(self, passed: int, failed: int):
        """Print validation summary."""
        total = passed + failed
        success_rate = (passed / total * 100) if total > 0 else 0

        print(f"\n{'='*80}")
        print(f"VALIDATION SUMMARY")
        print(f"{'='*80}")
        print(f"Total Events:   {total}")
        print(f"Passed:         {passed} ({success_rate:.1f}%)")
        print(f"Failed:         {failed}")
        print(f"{'='*80}\n")

        if failed == 0:
            print("🎉 ALL EVENTS PASSED VALIDATION!")
        else:
            print(f"⚠️  {failed} event(s) failed validation. Review errors above.")


def main():
    """Main validation entry point."""
    # Determine paths
    repo_root = Path(__file__).parent.parent.parent
    rules_dir = repo_root / 'rules' / 'ntds' / 'logic' / '2026'
    mapper_path = repo_root / 'rules' / 'mappers' / 'epic_deaconess_mapper_v1.json'

    print(f"Repository root: {repo_root}")
    print(f"Rules directory: {rules_dir}")
    print(f"Mapper file: {mapper_path}")
    print()

    # Validate paths exist
    if not rules_dir.exists():
        print(f"✗ CRITICAL: Rules directory not found: {rules_dir}")
        return 1

    if not mapper_path.exists():
        print(f"✗ CRITICAL: Mapper file not found: {mapper_path}")
        return 1

    # Create validator and run
    validator = NTDSValidator(rules_dir, mapper_path)

    # Load mapper first
    if not validator.load_mapper():
        return 1

    # Validate all events
    passed, failed = validator.validate_all_events()

    # Print summary
    validator.print_summary(passed, failed)

    return 0 if failed == 0 else 1


if __name__ == '__main__':
    exit(main())
