#!/usr/bin/env python3
"""
CerebralOS Governance Change Log — Section 26A.9 / 26B.

Append-only record of intentional, approved governance evolution.
Separate from the Failure Log (which records detected violations/drift).

Per Section 26B.3, each entry must include:
- Timestamp (system time standard)
- Governance Version Identifier
- Change Classification (Clarification | Enhancement | Correction | Retirement)
- Affected Section(s)
- Scope Declaration (Additive | Replacement | Superseding)
- Concise, factual description of the change

Per Section 26B.4: descriptions record what changed, not why.
Per Section 26B.5: entries are never edited, deleted, merged, or reordered.

Storage: JSON Lines format at outputs/governance_change_log.jsonl
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


# Valid classifications per Section 26B.3
VALID_CLASSIFICATIONS = frozenset({
    "Clarification",
    "Enhancement",
    "Correction",
    "Retirement",
})

# Valid scopes per Section 26B.3
VALID_SCOPES = frozenset({
    "Additive",
    "Replacement",
    "Superseding",
})


@dataclass
class ChangeEntry:
    """A single governance change log entry per Section 26B.3."""
    timestamp: str                # ISO 8601 timestamp
    governance_version: str       # e.g., "v2026.01"
    change_classification: str    # Clarification | Enhancement | Correction | Retirement
    affected_sections: List[str]  # e.g., ["10.2", "19.4.1"]
    scope: str                    # Additive | Replacement | Superseding
    description: str              # Factual, concise — what changed, not why


_DEFAULT_LOG_PATH = Path("outputs") / "governance_change_log.jsonl"


class ChangeLog:
    """
    Append-only governance change log per Section 26B.

    Per Section 26B.5:
    - Entries are never edited after creation
    - Entries are never deleted
    - Entries are never merged or summarized
    - Corrections require a new entry referencing the prior one
    """

    def __init__(self, log_path: Optional[Path] = None):
        self._path = log_path or _DEFAULT_LOG_PATH

    @property
    def path(self) -> Path:
        return self._path

    def append(self, entry: ChangeEntry) -> None:
        """
        Append a change entry to the log file.

        Validates mandatory fields per Section 26B.3 before writing.
        Raises ValueError if any field is invalid.
        """
        # Validate classification
        if entry.change_classification not in VALID_CLASSIFICATIONS:
            raise ValueError(
                f"Invalid change_classification: '{entry.change_classification}'. "
                f"Must be one of: {sorted(VALID_CLASSIFICATIONS)}"
            )

        # Validate scope
        if entry.scope not in VALID_SCOPES:
            raise ValueError(
                f"Invalid scope: '{entry.scope}'. "
                f"Must be one of: {sorted(VALID_SCOPES)}"
            )

        # Validate no field is empty (per 26B.3: no field may be omitted)
        if not entry.timestamp:
            raise ValueError("timestamp is required")
        if not entry.governance_version:
            raise ValueError("governance_version is required")
        if not entry.affected_sections:
            raise ValueError("affected_sections is required (at least one section)")
        if not entry.description:
            raise ValueError("description is required")

        self._path.parent.mkdir(parents=True, exist_ok=True)
        record = asdict(entry)
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")

    def read_all(self) -> List[ChangeEntry]:
        """Read all change entries from the log file in order."""
        if not self._path.exists():
            return []

        entries: List[ChangeEntry] = []
        with open(self._path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    entries.append(ChangeEntry(
                        timestamp=data.get("timestamp", ""),
                        governance_version=data.get("governance_version", ""),
                        change_classification=data.get("change_classification", ""),
                        affected_sections=data.get("affected_sections", []),
                        scope=data.get("scope", ""),
                        description=data.get("description", ""),
                    ))
                except json.JSONDecodeError:
                    continue  # Skip malformed lines
        return entries

    def count(self) -> int:
        """Count total entries without loading all into memory."""
        if not self._path.exists():
            return 0
        count = 0
        with open(self._path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    count += 1
        return count

    def format_report(self) -> str:
        """Format the change log as a human-readable report."""
        entries = self.read_all()
        lines: List[str] = []

        lines.append("=" * 60)
        lines.append("CEREBRAL OS — GOVERNANCE CHANGE LOG")
        lines.append("=" * 60)
        lines.append("")

        if not entries:
            lines.append("(No entries recorded)")
            lines.append("")
            return "\n".join(lines)

        lines.append(f"Total entries: {len(entries)}")
        lines.append("")

        for i, e in enumerate(entries, 1):
            ts_short = e.timestamp[:19] if len(e.timestamp) > 19 else e.timestamp
            sections = ", ".join(e.affected_sections)
            lines.append(f"[{i}] {ts_short}")
            lines.append(f"    Version:        {e.governance_version}")
            lines.append(f"    Classification: {e.change_classification}")
            lines.append(f"    Scope:          {e.scope}")
            lines.append(f"    Sections:       {sections}")
            lines.append(f"    Description:    {e.description}")
            lines.append("")

        lines.append("=" * 60)
        return "\n".join(lines)


def log_change(
    governance_version: str,
    classification: str,
    affected_sections: List[str],
    scope: str,
    description: str,
    log_path: Optional[Path] = None,
) -> None:
    """
    Convenience function to append a governance change log entry.

    Args:
        governance_version: Version identifier (e.g., "v2026.01")
        classification: Clarification | Enhancement | Correction | Retirement
        affected_sections: List of section numbers affected
        scope: Additive | Replacement | Superseding
        description: Factual description of what changed
        log_path: Optional custom log file path
    """
    log = ChangeLog(log_path)
    log.append(ChangeEntry(
        timestamp=datetime.now().isoformat(),
        governance_version=governance_version,
        change_classification=classification,
        affected_sections=affected_sections,
        scope=scope,
        description=description,
    ))
