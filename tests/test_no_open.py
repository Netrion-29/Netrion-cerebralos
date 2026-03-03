#!/usr/bin/env python3
"""
Tests for CEREBRAL_NO_OPEN=1 support in CLI entry points.

Covers:
  - __main__._open_file skips when CEREBRAL_NO_OPEN=1
  - __main__._open_file proceeds when env var absent
  - batch_eval._open_file skips when CEREBRAL_NO_OPEN=1
  - batch_eval._open_file proceeds when env var absent
  - run_patient.sh exports CEREBRAL_NO_OPEN=1
"""
from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock


class TestMainOpenFile(unittest.TestCase):
    """cerebralos/__main__.py _open_file env-var gating."""

    def _import_open_file(self):
        import cerebralos.__main__ as mod
        return mod._open_file

    def test_skips_when_no_open_set(self):
        """CEREBRAL_NO_OPEN=1 → subprocess.run never called."""
        fn = self._import_open_file()
        with patch.dict(os.environ, {"CEREBRAL_NO_OPEN": "1"}), \
             patch("subprocess.run") as mock_run:
            fn(Path("/tmp/fake_report.html"))
            mock_run.assert_not_called()

    def test_proceeds_when_no_open_unset(self):
        """No CEREBRAL_NO_OPEN → subprocess.run called (on Darwin)."""
        fn = self._import_open_file()
        env = os.environ.copy()
        env.pop("CEREBRAL_NO_OPEN", None)
        with patch.dict(os.environ, env, clear=True), \
             patch("platform.system", return_value="Darwin"), \
             patch("subprocess.run") as mock_run:
            fn(Path("/tmp/fake_report.html"))
            mock_run.assert_called_once()

    def test_proceeds_when_no_open_zero(self):
        """CEREBRAL_NO_OPEN=0 (not '1') → proceeds normally."""
        fn = self._import_open_file()
        with patch.dict(os.environ, {"CEREBRAL_NO_OPEN": "0"}), \
             patch("platform.system", return_value="Darwin"), \
             patch("subprocess.run") as mock_run:
            fn(Path("/tmp/fake_report.html"))
            mock_run.assert_called_once()


class TestBatchEvalOpenFile(unittest.TestCase):
    """cerebralos/ingestion/batch_eval.py _open_file env-var gating."""

    def _import_open_file(self):
        from cerebralos.ingestion.batch_eval import _open_file
        return _open_file

    def test_skips_when_no_open_set(self):
        """CEREBRAL_NO_OPEN=1 → subprocess.run never called."""
        fn = self._import_open_file()
        with patch.dict(os.environ, {"CEREBRAL_NO_OPEN": "1"}), \
             patch("subprocess.run") as mock_run:
            fn(Path("/tmp/fake_report.html"))
            mock_run.assert_not_called()

    def test_proceeds_when_no_open_unset(self):
        """No CEREBRAL_NO_OPEN → subprocess.run called."""
        fn = self._import_open_file()
        env = os.environ.copy()
        env.pop("CEREBRAL_NO_OPEN", None)
        with patch.dict(os.environ, env, clear=True), \
             patch("platform.system", return_value="Darwin"), \
             patch("subprocess.run") as mock_run:
            fn(Path("/tmp/fake_report.html"))
            mock_run.assert_called_once()


class TestRunPatientShExport(unittest.TestCase):
    """run_patient.sh must export CEREBRAL_NO_OPEN=1."""

    def test_run_patient_sh_exports_no_open(self):
        sh_path = Path(__file__).resolve().parents[1] / "run_patient.sh"
        content = sh_path.read_text()
        self.assertIn(
            "export CEREBRAL_NO_OPEN=1",
            content,
            "run_patient.sh must export CEREBRAL_NO_OPEN=1",
        )


if __name__ == "__main__":
    unittest.main()
