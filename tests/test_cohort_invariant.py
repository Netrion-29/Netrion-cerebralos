"""
Tests for the cohort invariant gate: check_invariant() in audit_cohort_counts.py.

Covers:
  - PASS when counts match and no extra/missing slugs
  - FAIL when adjusted != canonical
  - FAIL when extra slugs present
  - FAIL when missing slugs present
  - Multiple failures reported together
  - --check flag integration (exit codes)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure scripts/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from audit_cohort_counts import check_invariant, _collect


# ── check_invariant unit tests ───────────────────────────────────────


class TestCheckInvariant:
    def test_pass_when_consistent(self):
        report = {
            "canonical_count": 33,
            "true_patient_dirs_after_dedup_count": 33,
            "extra_slugs": [],
            "missing_slugs": [],
        }
        ok, messages = check_invariant(report)
        assert ok is True
        assert len(messages) == 1
        assert "PASS" in messages[0]

    def test_fail_count_mismatch(self):
        report = {
            "canonical_count": 33,
            "true_patient_dirs_after_dedup_count": 31,
            "extra_slugs": [],
            "missing_slugs": [],
        }
        ok, messages = check_invariant(report)
        assert ok is False
        assert any("adjusted output count (31) != canonical count (33)" in m for m in messages)

    def test_fail_extra_slugs(self):
        report = {
            "canonical_count": 33,
            "true_patient_dirs_after_dedup_count": 34,
            "extra_slugs": ["Unknown_Patient"],
            "missing_slugs": [],
        }
        ok, messages = check_invariant(report)
        assert ok is False
        assert any("extra slugs" in m for m in messages)

    def test_fail_missing_slugs(self):
        report = {
            "canonical_count": 33,
            "true_patient_dirs_after_dedup_count": 32,
            "extra_slugs": [],
            "missing_slugs": ["Anna_Dennis"],
        }
        ok, messages = check_invariant(report)
        assert ok is False
        assert any("missing slugs" in m for m in messages)

    def test_multiple_failures_all_reported(self):
        report = {
            "canonical_count": 33,
            "true_patient_dirs_after_dedup_count": 30,
            "extra_slugs": ["Stale_Patient"],
            "missing_slugs": ["Anna_Dennis", "Robert_Sauer"],
        }
        ok, messages = check_invariant(report)
        assert ok is False
        # Should report all three failure conditions
        assert len(messages) == 3


# ── Integration: _collect on real repo ───────────────────────────────


class TestCollectIntegration:
    def test_collect_returns_required_keys(self):
        repo_root = Path(__file__).resolve().parents[1]
        report = _collect(repo_root)
        assert "canonical_count" in report
        assert "true_patient_dirs_after_dedup_count" in report
        assert "extra_slugs" in report
        assert "missing_slugs" in report

    def test_invariant_on_live_repo(self):
        """The live repo cohort should be consistent (adjusted == canonical)."""
        repo_root = Path(__file__).resolve().parents[1]
        report = _collect(repo_root)
        ok, messages = check_invariant(report)
        assert ok is True, f"Cohort invariant failed on live repo: {messages}"


# ── Synthetic filesystem tests ───────────────────────────────────────


class TestCollectSynthetic:
    def _make_tree(self, tmp_path: Path, raw_names: list[str], ntds_names: list[str]) -> Path:
        """Create a minimal repo-like structure."""
        (tmp_path / "data_raw").mkdir()
        for n in raw_names:
            (tmp_path / "data_raw" / f"{n}.txt").touch()
        ntds = tmp_path / "outputs" / "ntds"
        ntds.mkdir(parents=True)
        for n in ntds_names:
            (ntds / n).mkdir()
        return tmp_path

    def test_clean_match(self, tmp_path: Path):
        repo = self._make_tree(
            tmp_path,
            ["Anna_Dennis", "Robert_Sauer"],
            ["Anna_Dennis", "Robert_Sauer"],
        )
        report = _collect(repo)
        ok, _ = check_invariant(report)
        assert ok is True

    def test_missing_output(self, tmp_path: Path):
        repo = self._make_tree(
            tmp_path,
            ["Anna_Dennis", "Robert_Sauer"],
            ["Anna_Dennis"],
        )
        report = _collect(repo)
        ok, messages = check_invariant(report)
        assert ok is False
        assert any("missing" in m.lower() for m in messages)

    def test_extra_output(self, tmp_path: Path):
        repo = self._make_tree(
            tmp_path,
            ["Anna_Dennis"],
            ["Anna_Dennis", "Stale_Patient"],
        )
        report = _collect(repo)
        ok, messages = check_invariant(report)
        assert ok is False
        assert any("extra" in m.lower() for m in messages)

    def test_fixture_dirs_ignored(self, tmp_path: Path):
        repo = self._make_tree(
            tmp_path,
            ["Anna_Dennis"],
            ["Anna_Dennis", "08_dvt_no", "14_pe_yes"],
        )
        report = _collect(repo)
        ok, _ = check_invariant(report)
        assert ok is True
        assert report["fixture_dirs"] == ["08_dvt_no", "14_pe_yes"]

    def test_space_variant_deduped(self, tmp_path: Path):
        repo = self._make_tree(
            tmp_path,
            ["Charlotte Howlett"],
            ["Charlotte Howlett", "Charlotte_Howlett"],
        )
        report = _collect(repo)
        ok, _ = check_invariant(report)
        assert ok is True
        assert report["space_variant_duplicates"] != []
