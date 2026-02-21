#!/usr/bin/env python3
"""
Config loader for CerebralOS feature extraction.

Loads JSON config files from REPO_ROOT/rules/features/.
Fails closed with clear exceptions if files are missing or malformed.

Design:
- Deterministic, fail-closed.
- No LLM, no ML, no clinical inference.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

# Repo root: walk up from this file to netrion-cerebralos/
_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent.parent  # cerebralos/features -> cerebralos -> repo
_RULES_DIR = _REPO_ROOT / "rules" / "features"


class ConfigLoadError(Exception):
    """Raised when a required config file is missing or malformed."""


def _load_json(filename: str) -> Dict[str, Any]:
    """Load a JSON file from rules/features/, fail-closed on missing/malformed."""
    path = _RULES_DIR / filename
    if not path.is_file():
        raise ConfigLoadError(
            f"Required config file not found: {path}  "
            f"(REPO_ROOT={_REPO_ROOT}, RULES_DIR={_RULES_DIR})"
        )
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise ConfigLoadError(
            f"Malformed JSON in config file {path}: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise ConfigLoadError(
            f"Config file {path} must contain a JSON object at top level, "
            f"got {type(data).__name__}"
        )
    return data


def load_labs_thresholds() -> Dict[str, Any]:
    """Load rules/features/labs_thresholds_v1.json."""
    return _load_json("labs_thresholds_v1.json")


def load_devices_patterns() -> Dict[str, Any]:
    """Load rules/features/devices_patterns_v1.json."""
    return _load_json("devices_patterns_v1.json")


def load_services_patterns() -> Dict[str, Any]:
    """Load rules/features/services_patterns_v1.json."""
    return _load_json("services_patterns_v1.json")


def load_vitals_patterns() -> Dict[str, Any]:
    """Load rules/features/vitals_patterns_v1.json."""
    return _load_json("vitals_patterns_v1.json")
