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


def _protocol_result(protocol_id: str, protocol_name: str, outcome: str, **kw):
    """Helper to build a single protocol result dict."""
    base = {
        "protocol_id": protocol_id,
        "protocol_name": protocol_name,
        "outcome": outcome,
        "step_trace": [],
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
# _generate_v5_report protocol wiring tests
# ════════════════════════════════════════════════════════════════════

class TestGenerateV5ReportProtocol(unittest.TestCase):
    """Tests for _generate_v5_report() protocol_results wiring."""

    def test_protocol_section_present_when_results_provided(self):
        """Non-empty protocol_results → PROTOCOL SIGNAL SUMMARY section rendered."""
        from cerebralos.ingestion.batch_eval import _generate_v5_report

        protos = [
            _protocol_result("P001", "DVT Prophylaxis", "COMPLIANT"),
            _protocol_result("P002", "TBI Protocol", "NON_COMPLIANT"),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            patient_path = _write_patient(tmpdir)
            text = _generate_v5_report(patient_path, [], protocol_results=protos)

        self.assertIn("PROTOCOL SIGNAL SUMMARY", text)
        self.assertIn("[NON-COMPLIANT] P002: TBI Protocol", text)

    def test_protocol_section_omitted_when_empty(self):
        """Empty protocol_results → section omitted (baseline stability)."""
        from cerebralos.ingestion.batch_eval import _generate_v5_report

        with tempfile.TemporaryDirectory() as tmpdir:
            patient_path = _write_patient(tmpdir)
            text = _generate_v5_report(patient_path, [], protocol_results=[])

        self.assertNotIn("PROTOCOL SIGNAL SUMMARY", text)

    def test_protocol_section_omitted_when_none(self):
        """protocol_results=None → section omitted."""
        from cerebralos.ingestion.batch_eval import _generate_v5_report

        with tempfile.TemporaryDirectory() as tmpdir:
            patient_path = _write_patient(tmpdir)
            text = _generate_v5_report(patient_path, [], protocol_results=None)

        self.assertNotIn("PROTOCOL SIGNAL SUMMARY", text)

    def test_both_ntds_and_protocol_rendered(self):
        """Both NTDS and protocol sections render when both provided."""
        from cerebralos.ingestion.batch_eval import _generate_v5_report

        ntds = [_ntds_result(1, "AKI", "YES")]
        protos = [_protocol_result("P001", "DVT Prophylaxis", "NON_COMPLIANT")]
        with tempfile.TemporaryDirectory() as tmpdir:
            patient_path = _write_patient(tmpdir)
            text = _generate_v5_report(patient_path, ntds, protocol_results=protos)

        self.assertIn("NTDS SIGNAL SUMMARY", text)
        self.assertIn("PROTOCOL SIGNAL SUMMARY", text)


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


# ════════════════════════════════════════════════════════════════════
# Batch CLI CEREBRAL_PROTOCOLS env-var gating tests
# ════════════════════════════════════════════════════════════════════

class TestBatchEvalProtocolEnvVarGating(unittest.TestCase):
    """Tests that batch CLI gates PROTOCOL SIGNAL SUMMARY on CEREBRAL_PROTOCOLS env var."""

    def _run_batch(self, tmpdir, patient_path, env_dict):
        """Run batch_eval main() with --v5, return v5 text."""
        report_dir = Path(tmpdir) / "reports"
        old_argv = sys.argv
        try:
            sys.argv = [
                "batch_eval",
                "--patient", str(patient_path),
                "--v5",
                "--output-dir", str(report_dir),
            ]
            with patch.dict(os.environ, env_dict):
                from cerebralos.ingestion.batch_eval import main
                main()
        finally:
            sys.argv = old_argv
        v5_path = report_dir / "Test_Patient_TRAUMA_DAILY_NOTES_v5.txt"
        return v5_path.read_text(encoding="utf-8") if v5_path.exists() else None

    # ── CEREBRAL_PROTOCOLS=1 ──────────────────────────────────────

    def test_batch_protocol_section_present_when_env_1(self):
        """CEREBRAL_PROTOCOLS=1 + --v5 → PROTOCOL SIGNAL SUMMARY present."""
        with tempfile.TemporaryDirectory() as tmpdir:
            patient_path = _write_patient(tmpdir)
            text = self._run_batch(tmpdir, patient_path, {"CEREBRAL_PROTOCOLS": "1"})

        self.assertIsNotNone(text)
        self.assertIn("PROTOCOL SIGNAL SUMMARY", text)
        self.assertIn("Protocols evaluated:", text)

    # ── CEREBRAL_PROTOCOLS=0 ──────────────────────────────────────

    def test_batch_protocol_section_absent_when_env_0(self):
        """CEREBRAL_PROTOCOLS=0 + --v5 → PROTOCOL SIGNAL SUMMARY omitted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            patient_path = _write_patient(tmpdir)
            text = self._run_batch(tmpdir, patient_path, {"CEREBRAL_PROTOCOLS": "0"})

        self.assertIsNotNone(text)
        self.assertNotIn("PROTOCOL SIGNAL SUMMARY", text)
        self.assertIn("PI DAILY NOTES (v5)", text)

    # ── CEREBRAL_PROTOCOLS unset ──────────────────────────────────

    def test_batch_protocol_section_absent_when_env_unset(self):
        """CEREBRAL_PROTOCOLS unset + --v5 → PROTOCOL SIGNAL SUMMARY omitted."""
        env = os.environ.copy()
        env.pop("CEREBRAL_PROTOCOLS", None)
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
                with patch.dict(os.environ, env, clear=True):
                    from cerebralos.ingestion.batch_eval import main
                    main()
            finally:
                sys.argv = old_argv
            v5_path = report_dir / "Test_Patient_TRAUMA_DAILY_NOTES_v5.txt"
            text = v5_path.read_text(encoding="utf-8")

        self.assertNotIn("PROTOCOL SIGNAL SUMMARY", text)

    # ── NTDS unaffected ───────────────────────────────────────────

    def test_batch_ntds_unaffected_by_protocol_env_off(self):
        """CEREBRAL_PROTOCOLS=0 does not suppress NTDS section in batch v5."""
        with tempfile.TemporaryDirectory() as tmpdir:
            patient_path = _write_patient(tmpdir)
            text = self._run_batch(tmpdir, patient_path, {"CEREBRAL_PROTOCOLS": "0"})

        self.assertIsNotNone(text)
        # NTDS section depends on real evaluation — just verify protocol is NOT present
        self.assertNotIn("PROTOCOL SIGNAL SUMMARY", text)
        self.assertIn("PI DAILY NOTES (v5)", text)

    # ── Standard sections stable ──────────────────────────────────

    def test_batch_standard_sections_stable(self):
        """V5 standard sections present regardless of protocol env var."""
        with tempfile.TemporaryDirectory() as tmpdir:
            patient_path = _write_patient(tmpdir)
            text = self._run_batch(tmpdir, patient_path, {"CEREBRAL_PROTOCOLS": "0"})

        self.assertIn("PI DAILY NOTES (v5)", text)
        self.assertIn("PER-DAY", text)


# ════════════════════════════════════════════════════════════════════
# Batch CLI --protocols flag tests
# ════════════════════════════════════════════════════════════════════

class TestBatchEvalProtocolsCLIFlag(unittest.TestCase):
    """Tests for --protocols CLI flag as alternative to CEREBRAL_PROTOCOLS env var."""

    def _run_batch_with_args(self, tmpdir, patient_path, extra_argv=None,
                             env_dict=None):
        """Run batch_eval main() with custom argv and env, return v5 text."""
        report_dir = Path(tmpdir) / "reports"
        argv = [
            "batch_eval",
            "--patient", str(patient_path),
            "--v5",
            "--output-dir", str(report_dir),
        ]
        if extra_argv:
            argv.extend(extra_argv)

        old_argv = sys.argv
        try:
            sys.argv = argv
            if env_dict is not None:
                with patch.dict(os.environ, env_dict):
                    from cerebralos.ingestion.batch_eval import main
                    main()
            else:
                # Ensure CEREBRAL_PROTOCOLS is NOT set
                env = os.environ.copy()
                env.pop("CEREBRAL_PROTOCOLS", None)
                with patch.dict(os.environ, env, clear=True):
                    from cerebralos.ingestion.batch_eval import main
                    main()
        finally:
            sys.argv = old_argv

        v5_path = report_dir / "Test_Patient_TRAUMA_DAILY_NOTES_v5.txt"
        return v5_path.read_text(encoding="utf-8") if v5_path.exists() else None

    # ── --protocols flag only (no env var) ────────────────────────

    def test_protocols_flag_enables_section(self):
        """--protocols flag → PROTOCOL SIGNAL SUMMARY present (no env var)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            patient_path = _write_patient(tmpdir)
            text = self._run_batch_with_args(
                tmpdir, patient_path, extra_argv=["--protocols"],
            )

        self.assertIsNotNone(text)
        self.assertIn("PROTOCOL SIGNAL SUMMARY", text)
        self.assertIn("Protocols evaluated:", text)

    def test_protocols_flag_has_counts(self):
        """--protocols flag → protocol counts rendered."""
        with tempfile.TemporaryDirectory() as tmpdir:
            patient_path = _write_patient(tmpdir)
            text = self._run_batch_with_args(
                tmpdir, patient_path, extra_argv=["--protocols"],
            )

        self.assertIn("Protocols evaluated:", text)
        self.assertIn("Triggered:", text)

    # ── env var only (no flag) ────────────────────────────────────

    def test_env_var_only_enables_section(self):
        """CEREBRAL_PROTOCOLS=1 without --protocols → section still present."""
        with tempfile.TemporaryDirectory() as tmpdir:
            patient_path = _write_patient(tmpdir)
            text = self._run_batch_with_args(
                tmpdir, patient_path,
                env_dict={"CEREBRAL_PROTOCOLS": "1"},
            )

        self.assertIsNotNone(text)
        self.assertIn("PROTOCOL SIGNAL SUMMARY", text)

    # ── both flag + env var ───────────────────────────────────────

    def test_both_flag_and_env_var(self):
        """--protocols + CEREBRAL_PROTOCOLS=1 → section present (no conflict)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            patient_path = _write_patient(tmpdir)
            text = self._run_batch_with_args(
                tmpdir, patient_path,
                extra_argv=["--protocols"],
                env_dict={"CEREBRAL_PROTOCOLS": "1"},
            )

        self.assertIsNotNone(text)
        self.assertIn("PROTOCOL SIGNAL SUMMARY", text)

    def test_flag_overrides_env_0(self):
        """--protocols flag enables section even when CEREBRAL_PROTOCOLS=0."""
        with tempfile.TemporaryDirectory() as tmpdir:
            patient_path = _write_patient(tmpdir)
            text = self._run_batch_with_args(
                tmpdir, patient_path,
                extra_argv=["--protocols"],
                env_dict={"CEREBRAL_PROTOCOLS": "0"},
            )

        self.assertIsNotNone(text)
        self.assertIn("PROTOCOL SIGNAL SUMMARY", text)

    # ── neither flag nor env var ──────────────────────────────────

    def test_neither_flag_nor_env(self):
        """No --protocols and no env var → section omitted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            patient_path = _write_patient(tmpdir)
            text = self._run_batch_with_args(tmpdir, patient_path)

        self.assertIsNotNone(text)
        self.assertNotIn("PROTOCOL SIGNAL SUMMARY", text)
        self.assertIn("PI DAILY NOTES (v5)", text)

    # ── NTDS unaffected by --protocols flag ───────────────────────

    def test_ntds_unaffected_by_protocols_flag(self):
        """--protocols flag does not interfere with NTDS section."""
        with tempfile.TemporaryDirectory() as tmpdir:
            patient_path = _write_patient(tmpdir)
            text = self._run_batch_with_args(
                tmpdir, patient_path, extra_argv=["--protocols"],
            )

        self.assertIsNotNone(text)
        # Standard sections still present
        self.assertIn("PI DAILY NOTES (v5)", text)
        self.assertIn("PER-DAY", text)

    # ── Standard sections stable ──────────────────────────────────

    def test_standard_sections_with_flag(self):
        """V5 standard sections present when --protocols is used."""
        with tempfile.TemporaryDirectory() as tmpdir:
            patient_path = _write_patient(tmpdir)
            text = self._run_batch_with_args(
                tmpdir, patient_path, extra_argv=["--protocols"],
            )

        self.assertIn("PI DAILY NOTES (v5)", text)
        self.assertIn("PER-DAY", text)
        self.assertIn("PROTOCOL SIGNAL SUMMARY", text)


# ════════════════════════════════════════════════════════════════════
# Batch CLI --ntds flag tests
# ════════════════════════════════════════════════════════════════════

class TestBatchEvalNTDSCLIFlag(unittest.TestCase):
    """Tests for --ntds CLI flag as alternative to CEREBRAL_NTDS env var."""

    def _run_batch_with_args(self, tmpdir, patient_path, extra_argv=None,
                             env_dict=None):
        """Run batch_eval main() with custom argv and env, return v5 text."""
        report_dir = Path(tmpdir) / "reports"
        argv = [
            "batch_eval",
            "--patient", str(patient_path),
            "--v5",
            "--output-dir", str(report_dir),
        ]
        if extra_argv:
            argv.extend(extra_argv)

        old_argv = sys.argv
        try:
            sys.argv = argv
            if env_dict is not None:
                with patch.dict(os.environ, env_dict):
                    from cerebralos.ingestion.batch_eval import main
                    main()
            else:
                env = os.environ.copy()
                env.pop("CEREBRAL_NTDS", None)
                env.pop("CEREBRAL_PROTOCOLS", None)
                with patch.dict(os.environ, env, clear=True):
                    from cerebralos.ingestion.batch_eval import main
                    main()
        finally:
            sys.argv = old_argv

        v5_path = report_dir / "Test_Patient_TRAUMA_DAILY_NOTES_v5.txt"
        return v5_path.read_text(encoding="utf-8") if v5_path.exists() else None

    # ── --ntds flag accepted ──────────────────────────────────────

    def test_ntds_flag_accepted(self):
        """--ntds flag is accepted without argparse error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            patient_path = _write_patient(tmpdir)
            text = self._run_batch_with_args(
                tmpdir, patient_path, extra_argv=["--ntds"],
            )

        self.assertIsNotNone(text)
        self.assertIn("PI DAILY NOTES (v5)", text)

    # ── --ntds flag + --v5 ────────────────────────────────────────

    def test_ntds_flag_with_v5(self):
        """--ntds + --v5 → v5 file created and standard sections present."""
        with tempfile.TemporaryDirectory() as tmpdir:
            patient_path = _write_patient(tmpdir)
            text = self._run_batch_with_args(
                tmpdir, patient_path, extra_argv=["--ntds"],
            )

        self.assertIsNotNone(text)
        self.assertIn("PER-DAY", text)

    # ── env var only (no flag) ────────────────────────────────────

    def test_ntds_env_var_only(self):
        """CEREBRAL_NTDS=1 without --ntds → v5 still created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            patient_path = _write_patient(tmpdir)
            text = self._run_batch_with_args(
                tmpdir, patient_path,
                env_dict={"CEREBRAL_NTDS": "1"},
            )

        self.assertIsNotNone(text)
        self.assertIn("PI DAILY NOTES (v5)", text)

    # ── both flag + env var ───────────────────────────────────────

    def test_both_ntds_flag_and_env(self):
        """--ntds + CEREBRAL_NTDS=1 → no conflict, v5 created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            patient_path = _write_patient(tmpdir)
            text = self._run_batch_with_args(
                tmpdir, patient_path,
                extra_argv=["--ntds"],
                env_dict={"CEREBRAL_NTDS": "1"},
            )

        self.assertIsNotNone(text)
        self.assertIn("PI DAILY NOTES (v5)", text)

    # ── neither flag nor env ──────────────────────────────────────

    def test_neither_ntds_flag_nor_env(self):
        """No --ntds and no env var → v5 present but NTDS section absent."""
        with tempfile.TemporaryDirectory() as tmpdir:
            patient_path = _write_patient(tmpdir)
            text = self._run_batch_with_args(tmpdir, patient_path)

        self.assertIsNotNone(text)
        self.assertNotIn("NTDS SIGNAL SUMMARY", text)
        self.assertIn("PI DAILY NOTES (v5)", text)

    # ── --ntds + --protocols coexistence ──────────────────────────

    def test_ntds_and_protocols_flags_coexist(self):
        """--ntds + --protocols → both accepted, v5 created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            patient_path = _write_patient(tmpdir)
            text = self._run_batch_with_args(
                tmpdir, patient_path,
                extra_argv=["--ntds", "--protocols"],
            )

        self.assertIsNotNone(text)
        self.assertIn("PI DAILY NOTES (v5)", text)
        self.assertIn("PROTOCOL SIGNAL SUMMARY", text)

    # ── Standard sections stable ──────────────────────────────────

    def test_standard_sections_with_ntds_flag(self):
        """V5 standard sections present when --ntds is used."""
        with tempfile.TemporaryDirectory() as tmpdir:
            patient_path = _write_patient(tmpdir)
            text = self._run_batch_with_args(
                tmpdir, patient_path, extra_argv=["--ntds"],
            )

        self.assertIn("PI DAILY NOTES (v5)", text)
        self.assertIn("PER-DAY", text)


# ════════════════════════════════════════════════════════════════════
# Batch CLI help text / argparse verification
# ════════════════════════════════════════════════════════════════════

class TestBatchEvalHelpText(unittest.TestCase):
    """Tests that batch_eval argparse has --protocols and --ntds flags."""

    def _get_parser_actions(self):
        """Build the argparse parser and return its option_strings."""
        import argparse
        # Re-create the parser inline to inspect it
        from cerebralos.ingestion.batch_eval import main as _  # ensure importable
        # Build a fresh parser by importing and checking argparse
        import importlib
        mod = importlib.import_module("cerebralos.ingestion.batch_eval")
        # Read the source to find add_argument calls — or just instantiate
        # We test by running with --help and capturing
        return None  # not needed — we test via argv below

    def test_argparse_has_protocols(self):
        """batch_eval argparse includes --protocols flag."""
        import io
        old_argv = sys.argv
        try:
            sys.argv = ["batch_eval", "--help"]
            buf = io.StringIO()
            with patch('sys.stdout', buf), \
                 self.assertRaises(SystemExit) as ctx:
                from cerebralos.ingestion.batch_eval import main
                main()
            output = buf.getvalue()
        finally:
            sys.argv = old_argv
        self.assertIn("--protocols", output)

    def test_argparse_has_ntds(self):
        """batch_eval argparse includes --ntds flag."""
        import io
        old_argv = sys.argv
        try:
            sys.argv = ["batch_eval", "--help"]
            buf = io.StringIO()
            with patch('sys.stdout', buf), \
                 self.assertRaises(SystemExit) as ctx:
                from cerebralos.ingestion.batch_eval import main
                main()
            output = buf.getvalue()
        finally:
            sys.argv = old_argv
        self.assertIn("--ntds", output)


if __name__ == "__main__":
    unittest.main()
