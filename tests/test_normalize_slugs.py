"""
Tests for scripts/normalize_output_slugs.py

Covers:
  - build_rename_plan: fixture-dir skipping, space detection, collision detection
  - main(): dry-run vs --apply behavior, exit codes
  - deterministic ordering
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure scripts/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from normalize_output_slugs import build_rename_plan, main


@pytest.fixture
def ntds_tree(tmp_path: Path) -> Path:
    """Create a realistic outputs/ntds layout with fixture dirs, clean dirs,
    and space-named duplicates."""
    d = tmp_path / "outputs" / "ntds"
    d.mkdir(parents=True)
    # Fixture dirs — must be skipped
    (d / "08_dvt_no").mkdir()
    (d / "14_pe_yes").mkdir()
    # Clean patient dirs (already underscore-normalized)
    (d / "Anna_Dennis").mkdir()
    (d / "Charlotte_Howlett").mkdir()
    (d / "William_Simmons").mkdir()
    # Space-named duplicates
    (d / "Charlotte Howlett").mkdir()
    (d / "William Simmons").mkdir()
    return d


@pytest.fixture
def clean_tree(tmp_path: Path) -> Path:
    """Create an outputs/ntds layout with no spaces — nothing to rename."""
    d = tmp_path / "outputs" / "ntds"
    d.mkdir(parents=True)
    (d / "08_dvt_no").mkdir()
    (d / "Anna_Dennis").mkdir()
    (d / "Robert_Sauer").mkdir()
    return d


@pytest.fixture
def no_collision_tree(tmp_path: Path) -> Path:
    """Space-named dir but no underscore sibling — rename is safe."""
    d = tmp_path / "outputs" / "ntds"
    d.mkdir(parents=True)
    (d / "Charlotte Howlett").mkdir()
    # No Charlotte_Howlett — safe to rename
    return d


# ── build_rename_plan tests ─────────────────────────────────────────


class TestBuildRenamePlan:
    def test_detects_space_dirs(self, ntds_tree: Path):
        plan = build_rename_plan(ntds_tree)
        sources = [e["source"] for e in plan]
        assert "Charlotte Howlett" in sources
        assert "William Simmons" in sources

    def test_skips_fixture_dirs(self, ntds_tree: Path):
        plan = build_rename_plan(ntds_tree)
        sources = [e["source"] for e in plan]
        assert "08_dvt_no" not in sources
        assert "14_pe_yes" not in sources

    def test_skips_already_normalized(self, ntds_tree: Path):
        plan = build_rename_plan(ntds_tree)
        sources = [e["source"] for e in plan]
        assert "Anna_Dennis" not in sources
        assert "Charlotte_Howlett" not in sources

    def test_collision_flagged(self, ntds_tree: Path):
        plan = build_rename_plan(ntds_tree)
        collisions = {e["source"]: e["collision"] for e in plan}
        # Charlotte Howlett → Charlotte_Howlett already exists
        assert collisions["Charlotte Howlett"] is True
        assert collisions["William Simmons"] is True

    def test_no_collision_when_target_absent(self, no_collision_tree: Path):
        plan = build_rename_plan(no_collision_tree)
        assert len(plan) == 1
        assert plan[0]["source"] == "Charlotte Howlett"
        assert plan[0]["collision"] is False

    def test_empty_on_clean_tree(self, clean_tree: Path):
        plan = build_rename_plan(clean_tree)
        assert plan == []

    def test_deterministic_order(self, ntds_tree: Path):
        plan1 = build_rename_plan(ntds_tree)
        plan2 = build_rename_plan(ntds_tree)
        assert plan1 == plan2
        # Sorted by source name
        sources = [e["source"] for e in plan1]
        assert sources == sorted(sources)

    def test_nonexistent_dir(self, tmp_path: Path):
        plan = build_rename_plan(tmp_path / "nonexistent")
        assert plan == []


# ── main() integration tests ────────────────────────────────────────


class TestMain:
    def test_dry_run_exits_zero_clean(self, clean_tree: Path):
        rc = main(["--target-dir", str(clean_tree)])
        assert rc == 0

    def test_dry_run_exits_one_on_collision(self, ntds_tree: Path):
        rc = main(["--target-dir", str(ntds_tree)])
        assert rc == 1

    def test_apply_exits_one_on_collision(self, ntds_tree: Path):
        rc = main(["--apply", "--target-dir", str(ntds_tree)])
        assert rc == 1
        # Verify no renames happened
        assert (ntds_tree / "Charlotte Howlett").is_dir()
        assert (ntds_tree / "William Simmons").is_dir()

    def test_apply_renames_when_safe(self, no_collision_tree: Path):
        rc = main(["--apply", "--target-dir", str(no_collision_tree)])
        assert rc == 0
        # Space dir should be gone, underscore dir should exist
        assert not (no_collision_tree / "Charlotte Howlett").is_dir()
        assert (no_collision_tree / "Charlotte_Howlett").is_dir()

    def test_dry_run_does_not_rename(self, no_collision_tree: Path):
        rc = main(["--target-dir", str(no_collision_tree)])
        assert rc == 0
        # Space dir should still exist (dry-run)
        assert (no_collision_tree / "Charlotte Howlett").is_dir()
        assert not (no_collision_tree / "Charlotte_Howlett").is_dir()

    def test_nonexistent_target_exits_one(self, tmp_path: Path):
        rc = main(["--target-dir", str(tmp_path / "nonexistent")])
        assert rc == 1
