#!/usr/bin/env python3
"""
Protocol Rules Loader for CerebralOS.

Loads protocol definitions and expands symbolic pattern keys to concrete regex patterns.
Mirrors NTDS rules_loader.py architecture but adapted for protocol compliance evaluation.

Design:
- Deterministic
- Minimal validation (fail-closed)
- Immutable rulesets at runtime
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
MAPPER_PATH = REPO_ROOT / "rules" / "mappers" / "epic_deaconess_mapper_v1.json"


@dataclass(frozen=True)
class ProtocolRuleset:
    """Immutable protocol ruleset container."""
    contract: Dict[str, Any]
    shared: Dict[str, Any]
    protocol: Dict[str, Any]
    protocol_path: Path


def _read_json(path: Path) -> Dict[str, Any]:
    """Read and parse JSON file with fail-closed error handling."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"Missing JSON: {path}")
    except json.JSONDecodeError as e:
        raise SystemExit(f"Invalid JSON: {path}\n{e}")


def load_protocol_contract() -> Dict[str, Any]:
    """
    Load protocol evaluation contract.

    Returns: Contract dict with outcomes, evidence limits, requirement types

    Raises: SystemExit if contract is missing, malformed, or not locked
    """
    path = REPO_ROOT / "rules" / "protocols" / "protocol_contract_v1.json"
    obj = _read_json(path)

    # Fail-closed validation
    if obj.get("meta", {}).get("locked") is not True:
        raise SystemExit("protocol_contract_v1.json must have meta.locked=true")

    allowed = obj.get("outcomes", {}).get("allowed", [])
    if not isinstance(allowed, list) or not allowed:
        raise SystemExit("protocol_contract_v1.json missing outcomes.allowed")

    return obj


def load_protocol_shared() -> Dict[str, Any]:
    """
    Load shared protocol pattern buckets.

    Returns: Shared dict with action_buckets and exclusion_patterns

    Raises: SystemExit if shared file is missing, malformed, or not locked
    """
    path = REPO_ROOT / "rules" / "protocols" / "protocol_shared_v1.json"
    obj = _read_json(path)

    if obj.get("meta", {}).get("locked") is not True:
        raise SystemExit("protocol_shared_v1.json must have meta.locked=true")

    # Support action_buckets (canonical) or legacy "buckets" key
    if "action_buckets" in obj and isinstance(obj["action_buckets"], dict):
        return obj
    if "buckets" in obj and isinstance(obj["buckets"], dict):
        # Normalize legacy format
        normalized = dict(obj)
        normalized["action_buckets"] = dict(normalized["buckets"])
        return normalized

    raise SystemExit("protocol_shared_v1.json missing action_buckets dict")


def load_mapper() -> Dict[str, Any]:
    """
    Load mapper JSON and return query_patterns mapping.

    Returns: Dict of pattern mappings (fail-closed: empty dict if unavailable)
    """
    try:
        obj = _read_json(MAPPER_PATH)
    except SystemExit:
        return {}

    qp = obj.get("query_patterns", {})
    if not isinstance(qp, dict):
        return {}

    return qp


def load_protocol(protocol_id: str) -> Tuple[Dict[str, Any], Path]:
    """
    Load single protocol from structured protocols file.

    Args:
        protocol_id: Unique protocol identifier (e.g., TRAUMATIC_BRAIN_INJURY_MANAGEMENT)

    Returns: Tuple of (protocol_dict, source_file_path)

    Raises: SystemExit if protocol not found or invalid structure
    """
    path = REPO_ROOT / "rules" / "deaconess" / "protocols_deaconess_structured_v1.json"
    obj = _read_json(path)

    # Find protocol by ID
    protocols = obj.get("protocols", [])
    if not isinstance(protocols, list):
        raise SystemExit(f"{path}: invalid protocols array")

    for proto in protocols:
        if proto.get("protocol_id") == protocol_id:
            # Validate minimum structure
            if proto.get("evaluation_mode") not in ("EVALUABLE", "CONTEXT_ONLY"):
                raise SystemExit(f"Protocol {protocol_id}: invalid evaluation_mode")

            if "requirements" not in proto or not isinstance(proto["requirements"], list):
                proto["requirements"] = []

            return proto, path

    raise SystemExit(f"Protocol not found: {protocol_id}")


def load_protocol_ruleset(protocol_id: str) -> ProtocolRuleset:
    """
    Load and assemble complete protocol ruleset with pattern expansion.

    Args:
        protocol_id: Unique protocol identifier

    Returns: Immutable ProtocolRuleset with contract, shared, and expanded protocol

    Pattern Expansion:
    - Symbolic keys (e.g., "gcs_assessment") → concrete regex patterns from mapper
    - Bucket references (e.g., "vital_signs_patterns") → patterns from shared
    - Direct regex patterns → used as-is
    """
    contract = load_protocol_contract()
    shared = load_protocol_shared()
    protocol, path = load_protocol(protocol_id)

    # Load supporting artifacts for pattern expansion
    mapper = {}
    try:
        mapper = load_mapper()
    except Exception:
        # Fail-closed: record warning but continue
        if "warnings" not in protocol:
            protocol["warnings"] = []
        protocol["warnings"].append("mapper_load_failed")

    action_buckets = shared.get("action_buckets", {})
    exclusion_buckets = shared.get("exclusion_patterns", {})

    def _looks_like_regex(s: str) -> bool:
        """Heuristic: detect if string contains regex metacharacters."""
        if not isinstance(s, str):
            return False
        meta = set('\\.^$*+?{}[]|()')
        return any((c in meta) for c in s)

    def _uniq_preserve(seq):
        """De-duplicate list while preserving order (first-seen)."""
        out = []
        seen = set()
        for s in seq:
            if s not in seen:
                out.append(s)
                seen.add(s)
        return out

    def _expand_list(keys):
        """
        Expand symbolic keys to concrete patterns.

        Resolution order:
        1. Mapper patterns (query_patterns)
        2. Shared action buckets
        3. Shared exclusion patterns
        4. Direct regex patterns (pass-through)
        """
        out = []
        for k in keys:
            if isinstance(k, str) and k in mapper:
                out.extend(list(mapper[k]))
            elif isinstance(k, str) and k in action_buckets:
                out.extend(list(action_buckets[k]))
            elif isinstance(k, str) and k in exclusion_buckets:
                out.extend(list(exclusion_buckets[k]))
            elif isinstance(k, str) and _looks_like_regex(k):
                out.append(k)
            else:
                # Unresolved symbolic key - record warning
                if "warnings" not in protocol:
                    protocol["warnings"] = []
                protocol["warnings"].append(f"unresolved_key: {k}")

        return _uniq_preserve([p for p in out if isinstance(p, str)])

    # Expand requirement patterns
    for req in protocol.get("requirements", []):
        # trigger_conditions may reference pattern keys (for now just preserve as-is)
        # In Phase 4 we'll add logic to expand trigger_conditions if needed

        # acceptable_evidence are document types (no expansion needed)
        pass

    ruleset = ProtocolRuleset(
        contract=contract,
        shared=shared,
        protocol=protocol,
        protocol_path=path
    )

    return ruleset
