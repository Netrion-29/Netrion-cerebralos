"""
Package initializer for cerebralos.
"""

__version__ = "1.0.0"

# Governance version metadata — included in all output artifacts
GOVERNANCE_VERSION = "v2026.01"
ENGINE_VERSION = __version__
RULES_VERSIONS = {
    "ntds": "2026_v1",
    "protocols": "deaconess_v1.1.0",
}

__all__ = ["__version__", "GOVERNANCE_VERSION", "ENGINE_VERSION", "RULES_VERSIONS"]
