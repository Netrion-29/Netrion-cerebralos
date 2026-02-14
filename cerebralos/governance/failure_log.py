#!/usr/bin/env python3
"""
CerebralOS Governance Failure Log — append-only observational record.

Records governance violations, data quality issues, and structural anomalies
detected during engine execution. Never modifies execution behavior — purely
observational.

Storage: JSON Lines format (one JSON object per line) at outputs/failure_log.jsonl

Categories:
- rule: A governance rule was violated (e.g., unanchored evidence, missing required element)
- drift: Output deviated from expected format or structure
- structural: File or configuration structural issue

Detection sources:
- execution: Detected during normal engine run
- diagnostic: Detected during diagnostic/validation pass
- governance_checklist: Detected during governance checklist validation
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class FailureEntry:
    """A single governance failure record."""
    timestamp: str           # ISO 8601 timestamp
    section: str             # Governance section that was violated (e.g., "19A", "evidence_anchor")
    category: str            # "rule", "drift", "structural"
    description: str         # Factual, non-interpretive description
    command: str             # Triggering command or context (e.g., "batch_eval Dallas_Clark")
    detection_source: str    # "execution", "diagnostic", "governance_checklist"
    patient_id: Optional[str] = None   # Patient identifier if applicable
    protocol_id: Optional[str] = None  # Protocol identifier if applicable
    metadata: Optional[Dict[str, Any]] = None  # Additional structured data


_DEFAULT_LOG_PATH = Path("outputs") / "failure_log.jsonl"


class FailureLog:
    """
    Append-only governance failure log.

    Thread-safe for single-process usage (file append is atomic on most OSes).
    """

    def __init__(self, log_path: Optional[Path] = None):
        self._path = log_path or _DEFAULT_LOG_PATH

    @property
    def path(self) -> Path:
        return self._path

    def append(self, entry: FailureEntry) -> None:
        """Append a failure entry to the log file."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        record = asdict(entry)
        # Remove None values for cleaner output
        record = {k: v for k, v in record.items() if v is not None}
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")

    def read_all(self) -> List[FailureEntry]:
        """Read all failure entries from the log file."""
        if not self._path.exists():
            return []

        entries: List[FailureEntry] = []
        with open(self._path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    entries.append(FailureEntry(
                        timestamp=data.get("timestamp", ""),
                        section=data.get("section", ""),
                        category=data.get("category", ""),
                        description=data.get("description", ""),
                        command=data.get("command", ""),
                        detection_source=data.get("detection_source", ""),
                        patient_id=data.get("patient_id"),
                        protocol_id=data.get("protocol_id"),
                        metadata=data.get("metadata"),
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

    def summary(self) -> Dict[str, int]:
        """Return counts by category."""
        counts: Dict[str, int] = {}
        for entry in self.read_all():
            counts[entry.category] = counts.get(entry.category, 0) + 1
        return counts


# ---------------------------------------------------------------------------
# Convenience functions for common failure types
# ---------------------------------------------------------------------------

def log_unanchored_evidence(
    log: FailureLog,
    patient_id: str,
    protocol_id: str,
    requirement_id: str,
    command: str = "",
) -> None:
    """Log a failure where evidence was used without proper anchoring."""
    log.append(FailureEntry(
        timestamp=datetime.now().isoformat(),
        section="evidence_anchor",
        category="rule",
        description=f"Evidence used for {requirement_id} lacks proper source anchoring",
        command=command,
        detection_source="execution",
        patient_id=patient_id,
        protocol_id=protocol_id,
    ))


def log_missing_required_element(
    log: FailureLog,
    patient_id: str,
    element_name: str,
    section: str = "19A",
    command: str = "",
) -> None:
    """Log a failure where a required data element was missing."""
    log.append(FailureEntry(
        timestamp=datetime.now().isoformat(),
        section=section,
        category="rule",
        description=f"Required element '{element_name}' not documented",
        command=command,
        detection_source="execution",
        patient_id=patient_id,
    ))


def log_negation_miss(
    log: FailureLog,
    patient_id: str,
    protocol_id: str,
    pattern_key: str,
    matched_text: str,
    command: str = "",
) -> None:
    """Log a case where negation detection may have missed a negated finding."""
    log.append(FailureEntry(
        timestamp=datetime.now().isoformat(),
        section="negation_detection",
        category="rule",
        description=f"Potential negation miss: '{matched_text}' matched on {pattern_key}",
        command=command,
        detection_source="execution",
        patient_id=patient_id,
        protocol_id=protocol_id,
        metadata={"pattern_key": pattern_key, "matched_text": matched_text},
    ))


def log_historical_false_trigger(
    log: FailureLog,
    patient_id: str,
    protocol_id: str,
    matched_text: str,
    command: str = "",
) -> None:
    """Log a case where historical data may have caused a false trigger."""
    log.append(FailureEntry(
        timestamp=datetime.now().isoformat(),
        section="historical_filtering",
        category="rule",
        description=f"Potential historical false trigger: '{matched_text}'",
        command=command,
        detection_source="execution",
        patient_id=patient_id,
        protocol_id=protocol_id,
        metadata={"matched_text": matched_text},
    ))
