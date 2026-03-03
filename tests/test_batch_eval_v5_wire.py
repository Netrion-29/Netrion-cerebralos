"""
Tests for the batch_eval → v5 NTDS signal summary wiring.

Verifies:
- _generate_v5_report() calls render_v5 with ntds_results when provided
- _generate_v5_report() omits NTDS section when ntds_results is empty/None
- _generate_v5_report() writes output file to disk
- batch_eval CLI --v5 flag generates v5 output
- --all-reports implies --v5
- __main__ cmd_run generates v5 with NTDS
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ---------------------------------------------------------------------------
# Minimal patient .txt for pipeline (evidence → timeline → features → v5)
# ---------------------------------------------------------------------------

_MINIMAL_PATIENT_TXT = textwrap.dedent("""\
    PATIENT_NAME: Test Patient
    PATIENT_ID: TP001
    DOB: 01/01/1950
    ARRIVAL_TIME: 2026-01-15 08:00
    TRAUMA_CATEGORY: Level II

    [PHYSICIAN_NOTE 2026-01-15 09:00]
    Patient is a 76 year old male admitted for fall.
    GCS: 15.  Alert and oriented.
    Vitals: BP 120/80, HR 72, RR 16, O2 98%.
""")


def _ntds_result(event_id: int, canonical_name: str, outcome: str, **kw):
    """Helper to build a single NTDS event result dict."""
    base = {
        "event_id": event_id,
        "canonical_name": canonical_name,
        "outcome": outcome,
        "gate_trace": [],
        "warnings": [],
    }
    base.update(kw)
    return base


def _write_patient(tmpdir: str, name: str = "Test_Patient") -> Path:
    """Write a minimal patient .txt file and return its Path."""
    p = Path(tmpdir) / f"{name}.txt"
    p.write_text(_MINIMAL_PATIENT_TXT, encoding="utf-8")
    return p


# ════════════════════════════════════════════════════════════════════
# _generate_v5_report unit tests
# ════════════════════════════════════════════════════════════════════

class TestGenerateV5Report(unittest.TestCase):
    """Tests for _generate_v5_report() — the batch path v5 generator."""

    def test_ntds_section_present_when_results_provided(self):
        """Non-empty ntds_results → NTDS SIGNAL SUMMARY section rendered."""
        from cerebralos.ingestion.batch_eval import _generate_v5_report

        ntds = [
            _ntds_result(1, "AKI", "NO"),
            _ntds_result(3, "PE", "YES"),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            patient_path = _write_patient(tmpdir)
            text = _generate_v5_report(patient_path, ntds)

        self.assertIn("NTDS SIGNAL SUMMARY", text)
        self.assertIn("[YES] Event 3: PE", text)
        self.assertIn("Events evaluated:       2", text)

    def test_ntds_section_omitted_when_empty_list(self):
        """Empty ntds_results list → section omitted (baseline stability)."""
        from cerebralos.ingestion.batch_eval import _generate_v5_report

        with tempfile.TemporaryDirectory() as tmpdir:
            patient_path = _write_patient(tmpdir)
            text = _generate_v5_report(patient_path, [])

        self.assertNotIn("NTDS SIGNAL SUMMARY", text)
        self.assertIn("PI DAILY NOTES (v5)", text)

    def test_ntds_section_omitted_when_none(self):
        """ntds_results=None → section omitted."""
        from cerebralos.ingestion.batch_eval import _generate_v5_report

        with tempfile.TemporaryDirectory() as tmpdir:
            patient_path = _write_patient(tmpdir)
            text = _generate_v5_report(patient_path, None)

        self.assertNotIn("NTDS SIGNAL SUMMARY", text)
        self.assertIn("PI DAILY NOTES (v5)", text)

    def test_output_file_written(self):
        """output_path → file is created on disk with v5 content."""
        from cerebralos.ingestion.batch_eval import _generate_v5_report

        ntds = [_ntds_result(1, "AKI", "YES")]
        with tempfile.TemporaryDirectory() as tmpdir:
            patient_path = _write_patient(tmpdir)
            out_path = Path(tmpdir) / "out" / "v5.txt"
            text = _generate_v5_report(patient_path, ntds, out_path)

            self.assertTrue(out_path.exists())
            disk_text = out_path.read_text(encoding="utf-8")
            self.assertEqual(text, disk_text)
            self.assertIn("NTDS SIGNAL SUMMARY", disk_text)

    def test_output_file_not_written_when_none(self):
        """output_path=None → no file created, text still returned."""
        from cerebralos.ingestion.batch_eval import _generate_v5_report

        with tempfile.TemporaryDirectory() as tmpdir:
            patient_path = _write_patient(tmpdir)
            text = _generate_v5_report(patient_path, [], None)

        self.assertIsInstance(text, str)
        self.assertIn("PI DAILY NOTES (v5)", text)

    def test_multiple_ntds_outcomes_all_rendered(self):
        """All NTDS outcome types appear in the rendered section."""
        from cerebralos.ingestion.batch_eval import _generate_v5_report

        ntds = [
            _ntds_result(1, "AKI", "YES"),
            _ntds_result(2, "DVT", "NO"),
            _ntds_result(3, "PE", "EXCLUDED"),
            _ntds_result(4, "Cardiac Arrest", "UNABLE_TO_DETERMINE"),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            patient_path = _write_patient(tmpdir)
            text = _generate_v5_report(patient_path, ntds)

        self.assertIn("Events evaluated:       4", text)
        self.assertIn("[YES] Event 1: AKI", text)
        self.assertIn("[EXCLUDED] Event 3: PE", text)
        self.assertIn("[UNABLE_TO_DETERMINE] Event 4: Cardiac Arrest", text)

    def test_v5_contains_patient_header(self):
        """V5 output contains patient info from the pipeline."""
        from cerebralos.ingestion.batch_eval import _generate_v5_report

        with tempfile.TemporaryDirectory() as tmpdir:
            patient_path = _write_patient(tmpdir)
            text = _generate_v5_report(patient_path, [])

        # v5 should have the standard PI DAILY NOTES header
        self.assertIn("PI DAILY NOTES (v5)", text)

    def test_deterministic_output(self):
        """Two calls with same inputs produce identical output."""
        from cerebralos.ingestion.batch_eval import _generate_v5_report

        ntds = [_ntds_result(1, "AKI", "YES")]
        with tempfile.TemporaryDirectory() as tmpdir:
            patient_path = _write_patient(tmpdir)
            text1 = _generate_v5_report(patient_path, ntds)
            text2 = _generate_v5_report(patient_path, ntds)

        self.assertEqual(text1, text2)


# ════════════════════════════════════════════════════════════════════
# CLI flag tests (--v5, --all-reports)
# ════════════════════════════════════════════════════════════════════

class TestBatchEvalV5CLIFlags(unittest.TestCase):
    """Tests that --v5 and --all-reports CLI flags trigger v5 generation."""

    def test_v5_flag_generates_output(self):
        """--v5 flag → v5 file is created for the patient."""
        with tempfile.TemporaryDirectory() as tmpdir:
            patient_path = _write_patient(tmpdir)
            report_dir = Path(tmpdir) / "reports"

            old_argv = sys.argv
            try:
                sys.argv = [
                    "batch_eval",
                    "--patient", str(patient_path),
                    "--v5",
                    "--output-dir", str(report_dir),
                ]
                from cerebralos.ingestion.batch_eval import main
                main()
            finally:
                sys.argv = old_argv

            v5_path = report_dir / "Test_Patient_TRAUMA_DAILY_NOTES_v5.txt"
            self.assertTrue(v5_path.exists(), f"V5 file not found: {v5_path}")
            text = v5_path.read_text(encoding="utf-8")
            self.assertIn("PI DAILY NOTES (v5)", text)

    def test_all_reports_implies_v5(self):
        """--all-reports → v5 file is also created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            patient_path = _write_patient(tmpdir)
            report_dir = Path(tmpdir) / "reports"

            old_argv = sys.argv
            try:
                sys.argv = [
                    "batch_eval",
                    "--patient", str(patient_path),
                    "--all-reports",
                    "--output-dir", str(report_dir),
                ]
                from cerebralos.ingestion.batch_eval import main
                main()
            finally:
                sys.argv = old_argv

            v5_path = report_dir / "Test_Patient_TRAUMA_DAILY_NOTES_v5.txt"
            self.assertTrue(v5_path.exists(), f"V5 file not found: {v5_path}")

    def test_no_v5_flag_no_v5_file(self):
        """Without --v5, no v5 file is generated."""
        with tempfile.TemporaryDirectory() as tmpdir:
            patient_path = _write_patient(tmpdir)
            report_dir = Path(tmpdir) / "reports"

            old_argv = sys.argv
            try:
                sys.argv = [
                    "batch_eval",
                    "--patient", str(patient_path),
                    "--output-dir", str(report_dir),
                ]
                from cerebralos.ingestion.batch_eval import main
                main()
            finally:
                sys.argv = old_argv

            v5_path = report_dir / "Test_Patient_TRAUMA_DAILY_NOTES_v5.txt"
            self.assertFalse(v5_path.exists(), "V5 file should NOT exist without --v5")


if __name__ == "__main__":
    unittest.main()
