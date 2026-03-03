"""
End-to-end integration tests for PROTOCOL SIGNAL SUMMARY runtime wiring.

Verifies:
  - Protocol results from evaluate_patient() render PROTOCOL SIGNAL SUMMARY
    in v5 output via _generate_v5_report()
  - v5 omits PROTOCOL SIGNAL SUMMARY when protocol results are absent/empty
  - Section ordering: PROTOCOL SIGNAL SUMMARY appears after NTDS (when present)
    and before PER-DAY CLINICAL STATUS
  - Deterministic output across two runs
  - CEREBRAL_PROTOCOLS=1 via run_patient.sh includes PROTOCOL SIGNAL SUMMARY
  - CEREBRAL_PROTOCOLS=0 or unset via run_patient.sh omits the section

These tests run the real evaluation + rendering pipeline against a real
patient file (Anna_Dennis).  Each test takes ~2-5 seconds.

Runtime paths exercised:
  1. Python API: evaluate_patient() → _generate_v5_report(protocol_results=...)
  2. Shell pipeline: CEREBRAL_PROTOCOLS=1 ./run_patient.sh Anna_Dennis
"""

from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path

# Repo root — two levels up from tests/
REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_PATIENT = REPO_ROOT / "run_patient.sh"
V5_OUTPUT = REPO_ROOT / "outputs" / "reporting" / "Anna_Dennis" / "TRAUMA_DAILY_NOTES_v5.txt"
PATIENT_FILE = REPO_ROOT / "data_raw" / "Anna_Dennis.txt"

# Skip the entire module if the patient data file is missing
# (e.g. CI environment without full data_raw checkout).
_HAS_PATIENT_DATA = PATIENT_FILE.is_file()


def _get_protocol_results():
    """
    Run the real evaluation pipeline and return protocol results.

    Returns the evaluation["results"] list — the same data that
    cmd_run() and batch_eval pass as protocol_results to v5.
    """
    from cerebralos.ingestion.batch_eval import _load_resources, evaluate_patient

    resources = _load_resources()
    evaluation = evaluate_patient(PATIENT_FILE, resources)
    return evaluation["results"]


def _render_v5_with_protocols(protocol_results=None, ntds_results=None):
    """
    Run the full evidence → timeline → features → render_v5 pipeline
    with the given protocol results.  Returns the rendered v5 text.
    """
    from cerebralos.ingestion.batch_eval import _generate_v5_report

    return _generate_v5_report(
        PATIENT_FILE,
        ntds_results if ntds_results is not None else [],
        output_path=None,
        protocol_results=protocol_results,
    )


# ════════════════════════════════════════════════════════════════════
# Module-level cache for expensive pipeline results
# ════════════════════════════════════════════════════════════════════

_cached_protocol_results = None
_cached_v5_with_protocols = None
_cached_v5_without_protocols = None


def _ensure_cached():
    """Lazy-load and cache protocol results and v5 texts.

    Running evaluate_patient + _generate_v5_report is expensive (~3-5s each).
    We cache the results once per module to avoid repeating the heavy work
    in every test method while still exercising the real pipeline.
    """
    global _cached_protocol_results, _cached_v5_with_protocols
    global _cached_v5_without_protocols

    if _cached_protocol_results is None:
        _cached_protocol_results = _get_protocol_results()
    if _cached_v5_with_protocols is None:
        _cached_v5_with_protocols = _render_v5_with_protocols(
            protocol_results=_cached_protocol_results,
        )
    if _cached_v5_without_protocols is None:
        _cached_v5_without_protocols = _render_v5_with_protocols(
            protocol_results=None,
        )


@unittest.skipUnless(_HAS_PATIENT_DATA, "requires data_raw/Anna_Dennis.txt")
class TestProtocolRuntimeWireE2E(unittest.TestCase):
    """End-to-end tests for PROTOCOL SIGNAL SUMMARY runtime wiring."""

    @classmethod
    def setUpClass(cls):
        """Run the heavy pipeline once for all tests in this class."""
        _ensure_cached()

    # ── Section presence ──────────────────────────────────────────

    def test_protocol_section_present_when_results_provided(self):
        """Real protocol results → v5 must contain PROTOCOL SIGNAL SUMMARY."""
        self.assertIn("PROTOCOL SIGNAL SUMMARY", _cached_v5_with_protocols)

    def test_protocol_section_has_counts(self):
        """Protocol section must show 'Protocols evaluated:' count line."""
        self.assertIn("Protocols evaluated:", _cached_v5_with_protocols)

    def test_protocol_section_has_triggered_count(self):
        """Protocol section must show 'Triggered:' count line."""
        self.assertIn("Triggered:", _cached_v5_with_protocols)

    def test_protocol_section_has_actionable_line(self):
        """Protocol section must include 'Actionable Protocols:' line."""
        self.assertIn("Actionable Protocols:", _cached_v5_with_protocols)

    def test_protocol_results_non_empty(self):
        """Sanity: evaluate_patient must return at least one protocol result."""
        self.assertGreater(len(_cached_protocol_results), 0)

    def test_evaluated_count_matches_results(self):
        """Protocols evaluated count in v5 matches actual results length."""
        expected = f"Protocols evaluated:    {len(_cached_protocol_results)}"
        self.assertIn(expected, _cached_v5_with_protocols)

    # ── Section absence ───────────────────────────────────────────

    def test_protocol_section_omitted_when_none(self):
        """protocol_results=None → v5 must NOT contain PROTOCOL SIGNAL SUMMARY."""
        self.assertNotIn("PROTOCOL SIGNAL SUMMARY", _cached_v5_without_protocols)

    def test_protocol_section_omitted_when_empty(self):
        """Empty protocol_results → v5 must NOT contain PROTOCOL SIGNAL SUMMARY."""
        text = _render_v5_with_protocols(protocol_results=[])
        self.assertNotIn("PROTOCOL SIGNAL SUMMARY", text)

    def test_standard_sections_present_without_protocols(self):
        """Without protocol results, v5 still renders all standard sections."""
        self.assertIn("PATIENT SUMMARY", _cached_v5_without_protocols)
        self.assertIn("PER-DAY CLINICAL STATUS", _cached_v5_without_protocols)
        self.assertIn("END OF PI DAILY NOTES (v5)", _cached_v5_without_protocols)

    # ── Section ordering ──────────────────────────────────────────

    def test_protocol_section_before_per_day(self):
        """PROTOCOL SIGNAL SUMMARY must appear before PER-DAY CLINICAL STATUS."""
        proto_pos = _cached_v5_with_protocols.index("PROTOCOL SIGNAL SUMMARY")
        perday_pos = _cached_v5_with_protocols.index("PER-DAY CLINICAL STATUS")
        self.assertLess(proto_pos, perday_pos)

    def test_protocol_section_after_patient_summary(self):
        """PROTOCOL SIGNAL SUMMARY must appear after PATIENT SUMMARY."""
        summary_pos = _cached_v5_with_protocols.index("PATIENT SUMMARY")
        proto_pos = _cached_v5_with_protocols.index("PROTOCOL SIGNAL SUMMARY")
        self.assertLess(summary_pos, proto_pos)

    def test_protocol_after_ntds_when_both_present(self):
        """When both NTDS and protocol results exist, protocol comes after NTDS."""
        # Run with both NTDS and protocol results via the real pipeline
        from cerebralos.ingestion.batch_eval import _load_resources, evaluate_patient

        resources = _load_resources()
        evaluation = evaluate_patient(PATIENT_FILE, resources)
        ntds_results = evaluation.get("ntds_results", [])
        protocol_results = evaluation["results"]

        text = _render_v5_with_protocols(
            protocol_results=protocol_results,
            ntds_results=ntds_results,
        )
        # Only assert ordering if NTDS section is present (needs NTDS results)
        if "NTDS SIGNAL SUMMARY" in text:
            ntds_pos = text.index("NTDS SIGNAL SUMMARY")
            proto_pos = text.index("PROTOCOL SIGNAL SUMMARY")
            self.assertLess(ntds_pos, proto_pos)
        else:
            # NTDS section not present (no ntds rulesets configured) — skip assertion
            self.assertIn("PROTOCOL SIGNAL SUMMARY", text)

    # ── Determinism ───────────────────────────────────────────────

    def test_deterministic_with_protocols(self):
        """Two renders with same protocol results produce identical v5 output."""
        text1 = _render_v5_with_protocols(protocol_results=_cached_protocol_results)
        text2 = _render_v5_with_protocols(protocol_results=_cached_protocol_results)
        self.assertEqual(text1, text2)

    def test_deterministic_without_protocols(self):
        """Two renders without protocol results produce identical v5 output."""
        text1 = _render_v5_with_protocols(protocol_results=None)
        text2 = _render_v5_with_protocols(protocol_results=None)
        self.assertEqual(text1, text2)

    # ── Pipeline integrity ────────────────────────────────────────

    def test_v5_header_present(self):
        """V5 output contains PI DAILY NOTES (v5) header."""
        self.assertIn("PI DAILY NOTES (v5)", _cached_v5_with_protocols)

    def test_v5_footer_present(self):
        """V5 output contains END OF PI DAILY NOTES (v5) footer."""
        self.assertIn("END OF PI DAILY NOTES (v5)", _cached_v5_with_protocols)

    def test_adding_protocols_preserves_per_day(self):
        """Adding protocol results must not alter PER-DAY section content."""
        with_perday = _cached_v5_with_protocols[
            _cached_v5_with_protocols.index("PER-DAY CLINICAL STATUS"):
        ]
        without_perday = _cached_v5_without_protocols[
            _cached_v5_without_protocols.index("PER-DAY CLINICAL STATUS"):
        ]
        self.assertEqual(with_perday, without_perday)


# ════════════════════════════════════════════════════════════════════
# Shell pipeline tests (run_patient.sh with CEREBRAL_PROTOCOLS env var)
# ════════════════════════════════════════════════════════════════════

def _run_shell_pipeline(
    cerebral_protocols: str | None = None,
    cerebral_ntds: str | None = None,
) -> subprocess.CompletedProcess:
    """Run run_patient.sh for Anna_Dennis with specified env vars."""
    env = os.environ.copy()
    # Explicitly clear both flags first so tests are isolated
    env.pop("CEREBRAL_PROTOCOLS", None)
    env.pop("CEREBRAL_NTDS", None)
    if cerebral_protocols is not None:
        env["CEREBRAL_PROTOCOLS"] = cerebral_protocols
    if cerebral_ntds is not None:
        env["CEREBRAL_NTDS"] = cerebral_ntds
    env["PYTHONPATH"] = str(REPO_ROOT)
    return subprocess.run(
        ["bash", str(RUN_PATIENT), "Anna_Dennis"],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _read_v5() -> str:
    """Read the v5 output file."""
    return V5_OUTPUT.read_text(encoding="utf-8")


@unittest.skipUnless(_HAS_PATIENT_DATA, "requires data_raw/Anna_Dennis.txt")
class TestProtocolShellPipelineE2E(unittest.TestCase):
    """End-to-end tests for CEREBRAL_PROTOCOLS wiring in run_patient.sh."""

    # ── PROTOCOLS=1 tests ─────────────────────────────────────────

    def test_protocols_on_produces_signal_summary(self):
        """CEREBRAL_PROTOCOLS=1 → v5 output must contain PROTOCOL SIGNAL SUMMARY."""
        result = _run_shell_pipeline(cerebral_protocols="1")
        self.assertEqual(result.returncode, 0, f"Pipeline failed:\n{result.stderr[-500:]}")
        text = _read_v5()
        self.assertIn("PROTOCOL SIGNAL SUMMARY", text)

    def test_protocols_on_has_evaluated_count(self):
        """Protocol section must show 'Protocols evaluated:' count line."""
        _run_shell_pipeline(cerebral_protocols="1")
        text = _read_v5()
        self.assertIn("Protocols evaluated:", text)

    def test_protocols_on_has_triggered_count(self):
        """Protocol section must show 'Triggered:' count line."""
        _run_shell_pipeline(cerebral_protocols="1")
        text = _read_v5()
        self.assertIn("Triggered:", text)

    def test_protocols_on_has_actionable_line(self):
        """Protocol section must include 'Actionable Protocols:' line."""
        _run_shell_pipeline(cerebral_protocols="1")
        text = _read_v5()
        self.assertIn("Actionable Protocols:", text)

    def test_protocols_on_section_before_perday(self):
        """PROTOCOL SIGNAL SUMMARY must appear before PER-DAY CLINICAL STATUS."""
        _run_shell_pipeline(cerebral_protocols="1")
        text = _read_v5()
        proto_pos = text.index("PROTOCOL SIGNAL SUMMARY")
        perday_pos = text.index("PER-DAY CLINICAL STATUS")
        self.assertLess(proto_pos, perday_pos)

    # ── PROTOCOLS=0 tests ─────────────────────────────────────────

    def test_protocols_off_omits_signal_summary(self):
        """CEREBRAL_PROTOCOLS=0 → v5 must NOT contain PROTOCOL SIGNAL SUMMARY."""
        result = _run_shell_pipeline(cerebral_protocols="0")
        self.assertEqual(result.returncode, 0, f"Pipeline failed:\n{result.stderr[-500:]}")
        text = _read_v5()
        self.assertNotIn("PROTOCOL SIGNAL SUMMARY", text)

    def test_protocols_off_still_has_standard_sections(self):
        """Without protocols, v5 still renders all standard sections."""
        _run_shell_pipeline(cerebral_protocols="0")
        text = _read_v5()
        self.assertIn("PATIENT SUMMARY", text)
        self.assertIn("PER-DAY CLINICAL STATUS", text)
        self.assertIn("END OF PI DAILY NOTES (v5)", text)

    # ── Unset env var tests ───────────────────────────────────────

    def test_protocols_unset_omits_signal_summary(self):
        """CEREBRAL_PROTOCOLS not set → v5 must NOT contain PROTOCOL SIGNAL SUMMARY."""
        result = _run_shell_pipeline()  # no cerebral_protocols arg
        self.assertEqual(result.returncode, 0)
        text = _read_v5()
        self.assertNotIn("PROTOCOL SIGNAL SUMMARY", text)

    # ── Determinism ───────────────────────────────────────────────

    def test_protocols_on_deterministic(self):
        """Two consecutive PROTOCOLS=1 runs produce identical v5 output."""
        _run_shell_pipeline(cerebral_protocols="1")
        text1 = _read_v5()
        _run_shell_pipeline(cerebral_protocols="1")
        text2 = _read_v5()
        self.assertEqual(text1, text2)

    # ── Pipeline exit code ────────────────────────────────────────

    def test_protocols_on_exit_zero(self):
        """Pipeline with CEREBRAL_PROTOCOLS=1 must exit 0."""
        result = _run_shell_pipeline(cerebral_protocols="1")
        self.assertEqual(result.returncode, 0)

    def test_protocols_off_exit_zero(self):
        """Pipeline with CEREBRAL_PROTOCOLS=0 must exit 0."""
        result = _run_shell_pipeline(cerebral_protocols="0")
        self.assertEqual(result.returncode, 0)

    # ── NTDS coexistence ──────────────────────────────────────────

    def test_both_ntds_and_protocols_on(self):
        """CEREBRAL_NTDS=1 + CEREBRAL_PROTOCOLS=1 → both sections in v5."""
        result = _run_shell_pipeline(cerebral_protocols="1", cerebral_ntds="1")
        self.assertEqual(result.returncode, 0, f"Pipeline failed:\n{result.stderr[-500:]}")
        text = _read_v5()
        self.assertIn("NTDS SIGNAL SUMMARY", text)
        self.assertIn("PROTOCOL SIGNAL SUMMARY", text)
        # Ordering: NTDS before protocol
        ntds_pos = text.index("NTDS SIGNAL SUMMARY")
        proto_pos = text.index("PROTOCOL SIGNAL SUMMARY")
        self.assertLess(ntds_pos, proto_pos)

    def test_ntds_on_protocols_off(self):
        """CEREBRAL_NTDS=1 + CEREBRAL_PROTOCOLS=0 → only NTDS in v5."""
        result = _run_shell_pipeline(cerebral_protocols="0", cerebral_ntds="1")
        self.assertEqual(result.returncode, 0)
        text = _read_v5()
        self.assertIn("NTDS SIGNAL SUMMARY", text)
        self.assertNotIn("PROTOCOL SIGNAL SUMMARY", text)


if __name__ == "__main__":
    unittest.main()
