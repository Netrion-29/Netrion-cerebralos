"""
Tests for ``python -m cerebralos run`` (cmd_run) v5 + NTDS wiring.

Verifies:
- cmd_run generates a v5 file in the output directory
- v5 file contains NTDS SIGNAL SUMMARY when ntds_results are present
- v5 file omits NTDS section when ntds_results are empty
- cmd_run returns 0 on success
- cmd_run returns 1 when called with no arguments
- v5 generation error is caught gracefully (cmd_run still returns 0)
- v5 passes ntds_results from the evaluation dict through to _generate_v5_report
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
# Minimal patient .txt for pipeline
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


def _fake_evaluation(ntds_results=None, protocol_results=None):
    """Return a minimal evaluation dict matching evaluate_patient() shape."""
    return {
        "patient_id": "TP001",
        "patient_name": "Test Patient",
        "dob": "01/01/1950",
        "trauma_category": "Level II",
        "arrival_time": "2026-01-15 08:00",
        "source_file": "Test_Patient.txt",
        "evidence_blocks": 1,
        "has_discharge": False,
        "is_live": True,
        "all_evidence_snippets": [],
        "protocols_evaluated": 0,
        "results": protocol_results if protocol_results is not None else [],
        "ntds_results": ntds_results if ntds_results is not None else [],
        "governance_version": "test",
        "engine_version": "test",
        "rules_versions": {},
    }


# ════════════════════════════════════════════════════════════════════
# cmd_run v5 + NTDS wiring tests
# ════════════════════════════════════════════════════════════════════

class TestCmdRunV5NTDSWiring(unittest.TestCase):
    """Tests that cmd_run() correctly wires v5 + NTDS in __main__.py."""

    def _run_cmd_run(self, tmpdir, patient_path, ntds_results=None,
                    protocol_results=None):
        """
        Invoke cmd_run() with mocked output dir and evaluate_patient.

        Returns (return_code, output_dir_path).
        """
        import cerebralos.__main__ as main_mod
        from cerebralos.ingestion import batch_eval as be_mod

        out_dir = Path(tmpdir) / "pi_reports"

        eval_dict = _fake_evaluation(ntds_results, protocol_results)

        with patch.object(main_mod, '_OUTPUT_DIR', out_dir), \
             patch.object(main_mod, '_open_file', lambda p: None), \
             patch.object(main_mod, '_resolve_patient_file', return_value=patient_path), \
             patch.object(be_mod, 'evaluate_patient', return_value=eval_dict), \
             patch.object(be_mod, '_load_resources', return_value={
                 "protocols": {"protocols": []},
                 "action_patterns": {},
                 "contract": {},
                 "ntds_rulesets": {},
                 "query_patterns": {},
             }):
            rc = main_mod.cmd_run([str(patient_path)])

        return rc, out_dir

    # ── Core wiring ─────────────────────────────────────────────

    def test_v5_file_created(self):
        """cmd_run generates a v5 file in the output directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            patient_path = Path(tmpdir) / "Test_Patient.txt"
            patient_path.write_text(_MINIMAL_PATIENT_TXT, encoding="utf-8")

            rc, out_dir = self._run_cmd_run(tmpdir, patient_path, ntds_results=[])

            v5_path = out_dir / "Test_Patient_TRAUMA_DAILY_NOTES_v5.txt"
            self.assertEqual(rc, 0)
            self.assertTrue(v5_path.exists(), f"V5 file not created: {v5_path}")

    def test_v5_contains_ntds_when_results_present(self):
        """When evaluation has ntds_results, v5 output includes NTDS SIGNAL SUMMARY."""
        ntds = [
            _ntds_result(1, "AKI", "NO"),
            _ntds_result(3, "PE", "YES"),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            patient_path = Path(tmpdir) / "Test_Patient.txt"
            patient_path.write_text(_MINIMAL_PATIENT_TXT, encoding="utf-8")

            rc, out_dir = self._run_cmd_run(tmpdir, patient_path, ntds_results=ntds)

            v5_path = out_dir / "Test_Patient_TRAUMA_DAILY_NOTES_v5.txt"
            self.assertTrue(v5_path.exists())
            text = v5_path.read_text(encoding="utf-8")
            self.assertIn("NTDS SIGNAL SUMMARY", text)
            self.assertIn("[YES] Event 3: PE", text)
            self.assertIn("Events evaluated:       2", text)

    def test_v5_omits_ntds_when_results_empty(self):
        """When evaluation has empty ntds_results, v5 omits NTDS section."""
        with tempfile.TemporaryDirectory() as tmpdir:
            patient_path = Path(tmpdir) / "Test_Patient.txt"
            patient_path.write_text(_MINIMAL_PATIENT_TXT, encoding="utf-8")

            rc, out_dir = self._run_cmd_run(tmpdir, patient_path, ntds_results=[])

            v5_path = out_dir / "Test_Patient_TRAUMA_DAILY_NOTES_v5.txt"
            self.assertTrue(v5_path.exists())
            text = v5_path.read_text(encoding="utf-8")
            self.assertNotIn("NTDS SIGNAL SUMMARY", text)
            self.assertIn("PI DAILY NOTES (v5)", text)

    def test_v5_has_patient_header(self):
        """V5 output contains the PI DAILY NOTES (v5) header."""
        with tempfile.TemporaryDirectory() as tmpdir:
            patient_path = Path(tmpdir) / "Test_Patient.txt"
            patient_path.write_text(_MINIMAL_PATIENT_TXT, encoding="utf-8")

            rc, out_dir = self._run_cmd_run(tmpdir, patient_path)

            v5_path = out_dir / "Test_Patient_TRAUMA_DAILY_NOTES_v5.txt"
            text = v5_path.read_text(encoding="utf-8")
            self.assertIn("PI DAILY NOTES (v5)", text)

    # ── Return codes ────────────────────────────────────────────

    def test_cmd_run_returns_zero(self):
        """cmd_run returns 0 on successful execution."""
        with tempfile.TemporaryDirectory() as tmpdir:
            patient_path = Path(tmpdir) / "Test_Patient.txt"
            patient_path.write_text(_MINIMAL_PATIENT_TXT, encoding="utf-8")

            rc, _ = self._run_cmd_run(tmpdir, patient_path)
            self.assertEqual(rc, 0)

    def test_cmd_run_returns_one_no_args(self):
        """cmd_run returns 1 when called with no arguments."""
        import cerebralos.__main__ as main_mod
        rc = main_mod.cmd_run([])
        self.assertEqual(rc, 1)

    # ── Error resilience ────────────────────────────────────────

    def test_v5_error_does_not_crash_cmd_run(self):
        """If _generate_v5_report raises, cmd_run catches it and returns 0."""
        import cerebralos.__main__ as main_mod
        from cerebralos.ingestion import batch_eval as be_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            patient_path = Path(tmpdir) / "Test_Patient.txt"
            patient_path.write_text(_MINIMAL_PATIENT_TXT, encoding="utf-8")
            out_dir = Path(tmpdir) / "pi_reports"

            eval_dict = _fake_evaluation([])

            def _exploding_v5(*args, **kwargs):
                raise RuntimeError("v5 pipeline failure")

            with patch.object(main_mod, '_OUTPUT_DIR', out_dir), \
                 patch.object(main_mod, '_open_file', lambda p: None), \
                 patch.object(main_mod, '_resolve_patient_file', return_value=patient_path), \
                 patch.object(be_mod, 'evaluate_patient', return_value=eval_dict), \
                 patch.object(be_mod, '_load_resources', return_value={
                     "protocols": {"protocols": []},
                     "action_patterns": {},
                     "contract": {},
                     "ntds_rulesets": {},
                     "query_patterns": {},
                 }), \
                 patch.object(be_mod, '_generate_v5_report', side_effect=_exploding_v5):
                rc = main_mod.cmd_run([str(patient_path)])

            self.assertEqual(rc, 0)
            v5_path = out_dir / "Test_Patient_TRAUMA_DAILY_NOTES_v5.txt"
            self.assertFalse(v5_path.exists(), "V5 file should NOT exist after error")

    # ── NTDS passthrough fidelity ───────────────────────────────

    def test_all_ntds_outcome_types_reach_v5(self):
        """All NTDS outcome types (YES/NO/EXCLUDED/UTD) propagate to v5 output."""
        ntds = [
            _ntds_result(1, "AKI", "YES"),
            _ntds_result(2, "DVT", "NO"),
            _ntds_result(5, "PE", "EXCLUDED"),
            _ntds_result(9, "Cardiac Arrest", "UNABLE_TO_DETERMINE"),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            patient_path = Path(tmpdir) / "Test_Patient.txt"
            patient_path.write_text(_MINIMAL_PATIENT_TXT, encoding="utf-8")

            rc, out_dir = self._run_cmd_run(tmpdir, patient_path, ntds_results=ntds)

            v5_path = out_dir / "Test_Patient_TRAUMA_DAILY_NOTES_v5.txt"
            text = v5_path.read_text(encoding="utf-8")
            self.assertIn("Events evaluated:       4", text)
            self.assertIn("[YES] Event 1: AKI", text)
            self.assertIn("[EXCLUDED] Event 5: PE", text)
            self.assertIn("[UNABLE_TO_DETERMINE] Event 9: Cardiac Arrest", text)

    def test_v5_deterministic_across_cmd_run_calls(self):
        """Two cmd_run calls with same inputs produce identical v5 output."""
        ntds = [_ntds_result(1, "AKI", "YES")]
        with tempfile.TemporaryDirectory() as tmpdir:
            patient_path = Path(tmpdir) / "Test_Patient.txt"
            patient_path.write_text(_MINIMAL_PATIENT_TXT, encoding="utf-8")

            _, out1 = self._run_cmd_run(tmpdir, patient_path, ntds_results=ntds)
            v5_text_1 = (out1 / "Test_Patient_TRAUMA_DAILY_NOTES_v5.txt").read_text(encoding="utf-8")

            _, out2 = self._run_cmd_run(tmpdir, patient_path, ntds_results=ntds)
            v5_text_2 = (out2 / "Test_Patient_TRAUMA_DAILY_NOTES_v5.txt").read_text(encoding="utf-8")

        self.assertEqual(v5_text_1, v5_text_2)

    # ── Other reports still generated alongside v5 ──────────────

    def test_text_and_json_reports_also_created(self):
        """cmd_run still generates text PI report and JSON alongside v5."""
        with tempfile.TemporaryDirectory() as tmpdir:
            patient_path = Path(tmpdir) / "Test_Patient.txt"
            patient_path.write_text(_MINIMAL_PATIENT_TXT, encoding="utf-8")

            rc, out_dir = self._run_cmd_run(tmpdir, patient_path, ntds_results=[])

            self.assertTrue((out_dir / "Test_Patient_pi_report.txt").exists())
            self.assertTrue((out_dir / "Test_Patient_results.json").exists())
            self.assertTrue((out_dir / "Test_Patient_TRAUMA_DAILY_NOTES_v5.txt").exists())

    # ── Protocol results passthrough ─────────────────────────────────────────

    def test_v5_contains_protocol_section_when_results_present(self):
        """When evaluation has protocol results and CEREBRAL_PROTOCOLS=1, v5 includes PROTOCOL SIGNAL SUMMARY."""
        protos = [
            _protocol_result("P001", "DVT Prophylaxis", "COMPLIANT"),
            _protocol_result("P002", "TBI Protocol", "NON_COMPLIANT"),
        ]
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.dict(os.environ, {"CEREBRAL_PROTOCOLS": "1"}):
            patient_path = Path(tmpdir) / "Test_Patient.txt"
            patient_path.write_text(_MINIMAL_PATIENT_TXT, encoding="utf-8")

            rc, out_dir = self._run_cmd_run(
                tmpdir, patient_path, ntds_results=[], protocol_results=protos,
            )

            v5_path = out_dir / "Test_Patient_TRAUMA_DAILY_NOTES_v5.txt"
            text = v5_path.read_text(encoding="utf-8")
            self.assertIn("PROTOCOL SIGNAL SUMMARY", text)
            self.assertIn("[NON-COMPLIANT] P002: TBI Protocol", text)
            self.assertIn("Protocols evaluated:    2", text)

    def test_v5_omits_protocol_section_when_results_empty(self):
        """When evaluation has empty results, v5 omits protocol section."""
        with tempfile.TemporaryDirectory() as tmpdir:
            patient_path = Path(tmpdir) / "Test_Patient.txt"
            patient_path.write_text(_MINIMAL_PATIENT_TXT, encoding="utf-8")

            rc, out_dir = self._run_cmd_run(
                tmpdir, patient_path, ntds_results=[], protocol_results=[],
            )

            v5_path = out_dir / "Test_Patient_TRAUMA_DAILY_NOTES_v5.txt"
            text = v5_path.read_text(encoding="utf-8")
            self.assertNotIn("PROTOCOL SIGNAL SUMMARY", text)

    def test_both_ntds_and_protocol_sections_rendered(self):
        """When both NTDS and protocol results present and CEREBRAL_PROTOCOLS=1, both sections render."""
        ntds = [_ntds_result(1, "AKI", "YES")]
        protos = [_protocol_result("P001", "DVT Prophylaxis", "COMPLIANT")]
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.dict(os.environ, {"CEREBRAL_PROTOCOLS": "1"}):
            patient_path = Path(tmpdir) / "Test_Patient.txt"
            patient_path.write_text(_MINIMAL_PATIENT_TXT, encoding="utf-8")

            rc, out_dir = self._run_cmd_run(
                tmpdir, patient_path, ntds_results=ntds, protocol_results=protos,
            )

            v5_path = out_dir / "Test_Patient_TRAUMA_DAILY_NOTES_v5.txt"
            text = v5_path.read_text(encoding="utf-8")
            self.assertIn("NTDS SIGNAL SUMMARY", text)
            self.assertIn("PROTOCOL SIGNAL SUMMARY", text)


# ════════════════════════════════════════════════════════════════════
# cmd_run CEREBRAL_PROTOCOLS env-var gating tests
# ════════════════════════════════════════════════════════════════════

class TestCmdRunProtocolEnvVarGating(unittest.TestCase):
    """Tests that cmd_run gates PROTOCOL SIGNAL SUMMARY on CEREBRAL_PROTOCOLS env var."""

    def _run_cmd_run(self, tmpdir, patient_path, ntds_results=None,
                    protocol_results=None):
        """Invoke cmd_run() with mocked output dir and evaluate_patient."""
        import cerebralos.__main__ as main_mod
        from cerebralos.ingestion import batch_eval as be_mod

        out_dir = Path(tmpdir) / "pi_reports"
        eval_dict = _fake_evaluation(ntds_results, protocol_results)

        with patch.object(main_mod, '_OUTPUT_DIR', out_dir), \
             patch.object(main_mod, '_open_file', lambda p: None), \
             patch.object(main_mod, '_resolve_patient_file', return_value=patient_path), \
             patch.object(be_mod, 'evaluate_patient', return_value=eval_dict), \
             patch.object(be_mod, '_load_resources', return_value={
                 "protocols": {"protocols": []},
                 "action_patterns": {},
                 "contract": {},
                 "ntds_rulesets": {},
                 "query_patterns": {},
             }):
            rc = main_mod.cmd_run([str(patient_path)])

        return rc, out_dir

    def _read_v5(self, out_dir):
        return (out_dir / "Test_Patient_TRAUMA_DAILY_NOTES_v5.txt").read_text(encoding="utf-8")

    # ── CEREBRAL_PROTOCOLS=1 ────────────────────────────────────

    def test_protocol_section_present_when_env_1(self):
        """CEREBRAL_PROTOCOLS=1 → protocol section rendered in v5."""
        protos = [
            _protocol_result("P001", "DVT Prophylaxis", "COMPLIANT"),
            _protocol_result("P002", "TBI Protocol", "NON_COMPLIANT"),
        ]
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.dict(os.environ, {"CEREBRAL_PROTOCOLS": "1"}):
            patient_path = Path(tmpdir) / "Test_Patient.txt"
            patient_path.write_text(_MINIMAL_PATIENT_TXT, encoding="utf-8")
            rc, out_dir = self._run_cmd_run(tmpdir, patient_path, protocol_results=protos)
            text = self._read_v5(out_dir)

        self.assertEqual(rc, 0)
        self.assertIn("PROTOCOL SIGNAL SUMMARY", text)
        self.assertIn("Protocols evaluated:    2", text)

    # ── CEREBRAL_PROTOCOLS=0 ────────────────────────────────────

    def test_protocol_section_absent_when_env_0(self):
        """CEREBRAL_PROTOCOLS=0 → protocol section omitted even with results."""
        protos = [
            _protocol_result("P001", "DVT Prophylaxis", "COMPLIANT"),
        ]
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.dict(os.environ, {"CEREBRAL_PROTOCOLS": "0"}):
            patient_path = Path(tmpdir) / "Test_Patient.txt"
            patient_path.write_text(_MINIMAL_PATIENT_TXT, encoding="utf-8")
            rc, out_dir = self._run_cmd_run(tmpdir, patient_path, protocol_results=protos)
            text = self._read_v5(out_dir)

        self.assertEqual(rc, 0)
        self.assertNotIn("PROTOCOL SIGNAL SUMMARY", text)
        self.assertIn("PI DAILY NOTES (v5)", text)

    # ── CEREBRAL_PROTOCOLS unset ────────────────────────────────

    def test_protocol_section_absent_when_env_unset(self):
        """CEREBRAL_PROTOCOLS unset → protocol section omitted."""
        protos = [
            _protocol_result("P001", "DVT Prophylaxis", "COMPLIANT"),
        ]
        env = os.environ.copy()
        env.pop("CEREBRAL_PROTOCOLS", None)
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.dict(os.environ, env, clear=True):
            patient_path = Path(tmpdir) / "Test_Patient.txt"
            patient_path.write_text(_MINIMAL_PATIENT_TXT, encoding="utf-8")
            rc, out_dir = self._run_cmd_run(tmpdir, patient_path, protocol_results=protos)
            text = self._read_v5(out_dir)

        self.assertEqual(rc, 0)
        self.assertNotIn("PROTOCOL SIGNAL SUMMARY", text)

    # ── NTDS unaffected ─────────────────────────────────────────

    def test_ntds_section_unaffected_by_protocol_env_off(self):
        """CEREBRAL_PROTOCOLS=0 does not suppress NTDS section."""
        ntds = [_ntds_result(1, "AKI", "YES")]
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.dict(os.environ, {"CEREBRAL_PROTOCOLS": "0"}):
            patient_path = Path(tmpdir) / "Test_Patient.txt"
            patient_path.write_text(_MINIMAL_PATIENT_TXT, encoding="utf-8")
            rc, out_dir = self._run_cmd_run(tmpdir, patient_path, ntds_results=ntds)
            text = self._read_v5(out_dir)

        self.assertIn("NTDS SIGNAL SUMMARY", text)
        self.assertIn("[YES] Event 1: AKI", text)
        self.assertNotIn("PROTOCOL SIGNAL SUMMARY", text)

    def test_ntds_section_unaffected_by_protocol_env_unset(self):
        """CEREBRAL_PROTOCOLS unset does not suppress NTDS section."""
        ntds = [_ntds_result(1, "AKI", "YES")]
        env = os.environ.copy()
        env.pop("CEREBRAL_PROTOCOLS", None)
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.dict(os.environ, env, clear=True):
            patient_path = Path(tmpdir) / "Test_Patient.txt"
            patient_path.write_text(_MINIMAL_PATIENT_TXT, encoding="utf-8")
            rc, out_dir = self._run_cmd_run(tmpdir, patient_path, ntds_results=ntds)
            text = self._read_v5(out_dir)

        self.assertIn("NTDS SIGNAL SUMMARY", text)
        self.assertNotIn("PROTOCOL SIGNAL SUMMARY", text)

    # ── Standard sections stable ────────────────────────────────

    def test_standard_sections_stable_when_protocol_env_off(self):
        """V5 standard sections present regardless of CEREBRAL_PROTOCOLS=0."""
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.dict(os.environ, {"CEREBRAL_PROTOCOLS": "0"}):
            patient_path = Path(tmpdir) / "Test_Patient.txt"
            patient_path.write_text(_MINIMAL_PATIENT_TXT, encoding="utf-8")
            rc, out_dir = self._run_cmd_run(tmpdir, patient_path)
            text = self._read_v5(out_dir)

        self.assertEqual(rc, 0)
        self.assertIn("PI DAILY NOTES (v5)", text)
        self.assertIn("PER-DAY", text)

    # ── Exit code ───────────────────────────────────────────────

    def test_exit_code_zero_with_protocol_env_on(self):
        """cmd_run returns 0 when CEREBRAL_PROTOCOLS=1."""
        protos = [_protocol_result("P001", "DVT Prophylaxis", "COMPLIANT")]
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.dict(os.environ, {"CEREBRAL_PROTOCOLS": "1"}):
            patient_path = Path(tmpdir) / "Test_Patient.txt"
            patient_path.write_text(_MINIMAL_PATIENT_TXT, encoding="utf-8")
            rc, _ = self._run_cmd_run(tmpdir, patient_path, protocol_results=protos)

        self.assertEqual(rc, 0)


# ════════════════════════════════════════════════════════════════════
# cmd_run --protocols CLI flag tests
# ════════════════════════════════════════════════════════════════════

class TestCmdRunProtocolsCLIFlag(unittest.TestCase):
    """Tests for --protocols CLI flag as alternative to CEREBRAL_PROTOCOLS env var."""

    def _run_cmd_run(self, tmpdir, patient_path, ntds_results=None,
                    protocol_results=None, use_flag=False):
        """Invoke cmd_run() with mocked output dir and evaluate_patient."""
        import cerebralos.__main__ as main_mod
        from cerebralos.ingestion import batch_eval as be_mod

        out_dir = Path(tmpdir) / "pi_reports"
        eval_dict = _fake_evaluation(ntds_results, protocol_results)

        cmd_args = ["--protocols", str(patient_path)] if use_flag else [str(patient_path)]

        with patch.object(main_mod, '_OUTPUT_DIR', out_dir), \
             patch.object(main_mod, '_open_file', lambda p: None), \
             patch.object(main_mod, '_resolve_patient_file', return_value=patient_path), \
             patch.object(be_mod, 'evaluate_patient', return_value=eval_dict), \
             patch.object(be_mod, '_load_resources', return_value={
                 "protocols": {"protocols": []},
                 "action_patterns": {},
                 "contract": {},
                 "ntds_rulesets": {},
                 "query_patterns": {},
             }):
            rc = main_mod.cmd_run(cmd_args)

        return rc, out_dir

    def _read_v5(self, out_dir):
        return (out_dir / "Test_Patient_TRAUMA_DAILY_NOTES_v5.txt").read_text(encoding="utf-8")

    # ── --protocols flag only (no env var) ────────────────────────

    def test_flag_enables_section(self):
        """--protocols flag → PROTOCOL SIGNAL SUMMARY present (no env var)."""
        protos = [
            _protocol_result("P001", "DVT Prophylaxis", "COMPLIANT"),
            _protocol_result("P002", "TBI Protocol", "NON_COMPLIANT"),
        ]
        env = os.environ.copy()
        env.pop("CEREBRAL_PROTOCOLS", None)
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.dict(os.environ, env, clear=True):
            patient_path = Path(tmpdir) / "Test_Patient.txt"
            patient_path.write_text(_MINIMAL_PATIENT_TXT, encoding="utf-8")
            rc, out_dir = self._run_cmd_run(
                tmpdir, patient_path, protocol_results=protos, use_flag=True,
            )
            text = self._read_v5(out_dir)

        self.assertEqual(rc, 0)
        self.assertIn("PROTOCOL SIGNAL SUMMARY", text)
        self.assertIn("Protocols evaluated:    2", text)

    def test_flag_has_triggered_count(self):
        """--protocols flag → triggered count rendered."""
        protos = [
            _protocol_result("P001", "DVT Prophylaxis", "COMPLIANT"),
        ]
        env = os.environ.copy()
        env.pop("CEREBRAL_PROTOCOLS", None)
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.dict(os.environ, env, clear=True):
            patient_path = Path(tmpdir) / "Test_Patient.txt"
            patient_path.write_text(_MINIMAL_PATIENT_TXT, encoding="utf-8")
            rc, out_dir = self._run_cmd_run(
                tmpdir, patient_path, protocol_results=protos, use_flag=True,
            )
            text = self._read_v5(out_dir)

        self.assertIn("Triggered:", text)

    # ── flag overrides env=0 ──────────────────────────────────────

    def test_flag_overrides_env_0(self):
        """--protocols flag enables section even when CEREBRAL_PROTOCOLS=0."""
        protos = [
            _protocol_result("P001", "DVT Prophylaxis", "COMPLIANT"),
        ]
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.dict(os.environ, {"CEREBRAL_PROTOCOLS": "0"}):
            patient_path = Path(tmpdir) / "Test_Patient.txt"
            patient_path.write_text(_MINIMAL_PATIENT_TXT, encoding="utf-8")
            rc, out_dir = self._run_cmd_run(
                tmpdir, patient_path, protocol_results=protos, use_flag=True,
            )
            text = self._read_v5(out_dir)

        self.assertEqual(rc, 0)
        self.assertIn("PROTOCOL SIGNAL SUMMARY", text)

    # ── env var only (no flag) ────────────────────────────────────

    def test_env_var_only_still_works(self):
        """CEREBRAL_PROTOCOLS=1 without --protocols flag → section present."""
        protos = [
            _protocol_result("P001", "DVT Prophylaxis", "COMPLIANT"),
        ]
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.dict(os.environ, {"CEREBRAL_PROTOCOLS": "1"}):
            patient_path = Path(tmpdir) / "Test_Patient.txt"
            patient_path.write_text(_MINIMAL_PATIENT_TXT, encoding="utf-8")
            rc, out_dir = self._run_cmd_run(
                tmpdir, patient_path, protocol_results=protos, use_flag=False,
            )
            text = self._read_v5(out_dir)

        self.assertIn("PROTOCOL SIGNAL SUMMARY", text)

    # ── neither flag nor env ──────────────────────────────────────

    def test_neither_flag_nor_env(self):
        """No --protocols and no env var → section omitted."""
        protos = [
            _protocol_result("P001", "DVT Prophylaxis", "COMPLIANT"),
        ]
        env = os.environ.copy()
        env.pop("CEREBRAL_PROTOCOLS", None)
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.dict(os.environ, env, clear=True):
            patient_path = Path(tmpdir) / "Test_Patient.txt"
            patient_path.write_text(_MINIMAL_PATIENT_TXT, encoding="utf-8")
            rc, out_dir = self._run_cmd_run(
                tmpdir, patient_path, protocol_results=protos, use_flag=False,
            )
            text = self._read_v5(out_dir)

        self.assertEqual(rc, 0)
        self.assertNotIn("PROTOCOL SIGNAL SUMMARY", text)
        self.assertIn("PI DAILY NOTES (v5)", text)

    # ── both flag + env var ───────────────────────────────────────

    def test_both_flag_and_env_var(self):
        """--protocols + CEREBRAL_PROTOCOLS=1 → section present (no conflict)."""
        protos = [
            _protocol_result("P001", "DVT Prophylaxis", "COMPLIANT"),
        ]
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.dict(os.environ, {"CEREBRAL_PROTOCOLS": "1"}):
            patient_path = Path(tmpdir) / "Test_Patient.txt"
            patient_path.write_text(_MINIMAL_PATIENT_TXT, encoding="utf-8")
            rc, out_dir = self._run_cmd_run(
                tmpdir, patient_path, protocol_results=protos, use_flag=True,
            )
            text = self._read_v5(out_dir)

        self.assertIn("PROTOCOL SIGNAL SUMMARY", text)

    # ── NTDS unaffected by --protocols flag ───────────────────────

    def test_ntds_unaffected_by_protocols_flag(self):
        """--protocols flag does not interfere with NTDS section."""
        ntds = [_ntds_result(1, "AKI", "YES")]
        env = os.environ.copy()
        env.pop("CEREBRAL_PROTOCOLS", None)
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.dict(os.environ, env, clear=True):
            patient_path = Path(tmpdir) / "Test_Patient.txt"
            patient_path.write_text(_MINIMAL_PATIENT_TXT, encoding="utf-8")
            rc, out_dir = self._run_cmd_run(
                tmpdir, patient_path, ntds_results=ntds, use_flag=True,
            )
            text = self._read_v5(out_dir)

        self.assertIn("NTDS SIGNAL SUMMARY", text)
        self.assertIn("[YES] Event 1: AKI", text)

    # ── Standard sections stable ──────────────────────────────────

    def test_standard_sections_with_flag(self):
        """V5 standard sections present when --protocols is used."""
        protos = [_protocol_result("P001", "DVT Prophylaxis", "COMPLIANT")]
        env = os.environ.copy()
        env.pop("CEREBRAL_PROTOCOLS", None)
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.dict(os.environ, env, clear=True):
            patient_path = Path(tmpdir) / "Test_Patient.txt"
            patient_path.write_text(_MINIMAL_PATIENT_TXT, encoding="utf-8")
            rc, out_dir = self._run_cmd_run(
                tmpdir, patient_path, protocol_results=protos, use_flag=True,
            )
            text = self._read_v5(out_dir)

        self.assertIn("PI DAILY NOTES (v5)", text)
        self.assertIn("PER-DAY", text)
        self.assertIn("PROTOCOL SIGNAL SUMMARY", text)

    # ── Exit code ─────────────────────────────────────────────────

    def test_exit_code_zero_with_flag(self):
        """cmd_run returns 0 when --protocols flag is used."""
        protos = [_protocol_result("P001", "DVT Prophylaxis", "COMPLIANT")]
        env = os.environ.copy()
        env.pop("CEREBRAL_PROTOCOLS", None)
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.dict(os.environ, env, clear=True):
            patient_path = Path(tmpdir) / "Test_Patient.txt"
            patient_path.write_text(_MINIMAL_PATIENT_TXT, encoding="utf-8")
            rc, _ = self._run_cmd_run(
                tmpdir, patient_path, protocol_results=protos, use_flag=True,
            )

        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
