"""
End-to-end integration tests for NTDS runtime wiring in run_patient.sh.

Verifies:
  - CEREBRAL_NTDS=1 → v5 output includes NTDS SIGNAL SUMMARY section
  - CEREBRAL_NTDS=0 (or unset) → v5 output omits NTDS SIGNAL SUMMARY
  - NTDS section content is deterministic across repeated runs
  - NTDS section appears before PER-DAY CLINICAL STATUS

These tests execute the real run_patient.sh pipeline end-to-end against
a small real patient file (Anna_Dennis).  Each test takes ~2-3 seconds.
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


def _run_pipeline(cerebral_ntds: str) -> subprocess.CompletedProcess:
    """Run run_patient.sh for Anna_Dennis with the specified CEREBRAL_NTDS value."""
    env = os.environ.copy()
    env["CEREBRAL_NTDS"] = cerebral_ntds
    env["PYTHONPATH"] = str(REPO_ROOT)
    return subprocess.run(
        ["bash", str(RUN_PATIENT), "Anna_Dennis"],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _read_v5() -> str:
    """Read the v5 output file."""
    return V5_OUTPUT.read_text(encoding="utf-8")


@unittest.skipUnless(_HAS_PATIENT_DATA, "requires data_raw/Anna_Dennis.txt")
class TestNTDSRuntimeWireE2E(unittest.TestCase):
    """End-to-end tests for NTDS wiring through run_patient.sh → v5 output."""

    # ── NTDS=1 tests ──

    def test_ntds_on_produces_signal_summary(self):
        """CEREBRAL_NTDS=1 → v5 output must contain NTDS SIGNAL SUMMARY section."""
        result = _run_pipeline("1")
        self.assertEqual(result.returncode, 0, f"Pipeline failed:\n{result.stderr[-500:]}")
        text = _read_v5()
        self.assertIn("NTDS SIGNAL SUMMARY", text)

    def test_ntds_on_has_event_counts(self):
        """NTDS section must show event counts when NTDS is enabled."""
        _run_pipeline("1")
        text = _read_v5()
        self.assertIn("Events evaluated:", text)

    def test_ntds_on_section_before_perday(self):
        """NTDS SIGNAL SUMMARY must appear before PER-DAY CLINICAL STATUS."""
        _run_pipeline("1")
        text = _read_v5()
        ntds_pos = text.index("NTDS SIGNAL SUMMARY")
        perday_pos = text.index("PER-DAY CLINICAL STATUS")
        self.assertLess(ntds_pos, perday_pos)

    def test_ntds_on_produces_non_no_line(self):
        """NTDS section must include Non-NO Events line."""
        _run_pipeline("1")
        text = _read_v5()
        self.assertIn("Non-NO Events:", text)

    # ── NTDS=0 tests ──

    def test_ntds_off_omits_signal_summary(self):
        """CEREBRAL_NTDS=0 → v5 output must NOT contain NTDS SIGNAL SUMMARY."""
        result = _run_pipeline("0")
        self.assertEqual(result.returncode, 0, f"Pipeline failed:\n{result.stderr[-500:]}")
        text = _read_v5()
        self.assertNotIn("NTDS SIGNAL SUMMARY", text)

    def test_ntds_off_still_has_patient_summary(self):
        """Without NTDS, v5 still renders all standard sections."""
        _run_pipeline("0")
        text = _read_v5()
        self.assertIn("PATIENT SUMMARY", text)
        self.assertIn("PER-DAY CLINICAL STATUS", text)
        self.assertIn("END OF PI DAILY NOTES (v5)", text)

    # ── Unset env var tests ──

    def test_ntds_unset_omits_signal_summary(self):
        """CEREBRAL_NTDS not set → v5 output must NOT contain NTDS SIGNAL SUMMARY."""
        env = os.environ.copy()
        env.pop("CEREBRAL_NTDS", None)
        env["PYTHONPATH"] = str(REPO_ROOT)
        result = subprocess.run(
            ["bash", str(RUN_PATIENT), "Anna_Dennis"],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0)
        text = _read_v5()
        self.assertNotIn("NTDS SIGNAL SUMMARY", text)

    # ── Determinism ──

    def test_ntds_on_deterministic(self):
        """Two consecutive NTDS=1 runs produce identical v5 output."""
        _run_pipeline("1")
        text1 = _read_v5()
        _run_pipeline("1")
        text2 = _read_v5()
        self.assertEqual(text1, text2)

    # ── Pipeline exit code ──

    def test_ntds_on_exit_zero(self):
        """Pipeline with CEREBRAL_NTDS=1 must exit 0 for Anna_Dennis."""
        result = _run_pipeline("1")
        self.assertEqual(result.returncode, 0)

    def test_ntds_off_exit_zero(self):
        """Pipeline with CEREBRAL_NTDS=0 must exit 0."""
        result = _run_pipeline("0")
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
