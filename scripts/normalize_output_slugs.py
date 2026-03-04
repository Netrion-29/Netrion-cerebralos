#!/usr/bin/env python3
"""
normalize_output_slugs.py — Safe, deterministic slug normalization for outputs/ntds.

Scans outputs/ntds/ for directories with spaces in their names and plans
renames to underscore-normalized equivalents.

Modes:
  dry-run (default): prints the rename plan only; exits 0 if clean, 1 if
                     collisions detected.
  --apply:           performs renames; exits 0 on success, 1 on collision.

Safety:
  - Fixture directories (matching ^\\d{2}_) are always skipped.
  - If a normalized target already exists, the script reports the collision
    and exits non-zero *without* performing any renames.
  - Processing order is deterministic (sorted by directory name).

Usage:
  python3 scripts/normalize_output_slugs.py              # dry-run
  python3 scripts/normalize_output_slugs.py --apply       # perform renames
  python3 scripts/normalize_output_slugs.py --target-dir outputs/ntds  # custom dir
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

RE_FIXTURE_DIR = re.compile(r"^\d{2}_")


def _slugify(name: str) -> str:
    """Normalize spaces to underscores."""
    return name.replace(" ", "_")


def build_rename_plan(target_dir: Path) -> list[dict]:
    """
    Scan *target_dir* for directories with spaces in their names.
    Return a sorted list of rename plan entries.

    Each entry:
      {"source": str, "target": str, "collision": bool}
    """
    if not target_dir.is_dir():
        return []

    entries = sorted(target_dir.iterdir())
    existing_names: set[str] = {e.name for e in entries if e.is_dir()}

    plan: list[dict] = []
    for entry in entries:
        if not entry.is_dir():
            continue
        name = entry.name
        # Skip fixture directories (e.g. 08_dvt_no, 14_pe_yes)
        if RE_FIXTURE_DIR.match(name):
            continue
        # Only process directories that contain spaces
        if " " not in name:
            continue

        normalized = _slugify(name)
        collision = normalized in existing_names
        plan.append({
            "source": name,
            "target": normalized,
            "collision": collision,
        })

    return plan


def print_plan(plan: list[dict], *, apply_mode: bool) -> None:
    """Pretty-print the rename plan."""
    if not plan:
        print("normalize_output_slugs: no directories need renaming.")
        return

    mode_label = "APPLY" if apply_mode else "DRY-RUN"
    print(f"normalize_output_slugs [{mode_label}]: {len(plan)} rename(s) planned\n")
    for entry in plan:
        collision_tag = " *** COLLISION ***" if entry["collision"] else ""
        print(f"  {entry['source']!r}  →  {entry['target']!r}{collision_tag}")
    print()


def apply_renames(target_dir: Path, plan: list[dict]) -> None:
    """Execute renames. Caller must verify no collisions first."""
    for entry in plan:
        src = target_dir / entry["source"]
        dst = target_dir / entry["target"]
        src.rename(dst)
        print(f"  renamed: {entry['source']!r} → {entry['target']!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Safe slug normalization for NTDS output directories."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Perform renames (default is dry-run).",
    )
    parser.add_argument(
        "--target-dir",
        type=Path,
        default=Path("outputs/ntds"),
        help="Directory to scan (default: outputs/ntds).",
    )
    args = parser.parse_args(argv)

    target_dir = args.target_dir
    if not target_dir.is_dir():
        print(f"normalize_output_slugs: target directory not found: {target_dir}")
        return 1

    plan = build_rename_plan(target_dir)
    print_plan(plan, apply_mode=args.apply)

    # Check for collisions
    collisions = [e for e in plan if e["collision"]]
    if collisions:
        print(f"ERROR: {len(collisions)} collision(s) detected. No renames performed.")
        for c in collisions:
            print(f"  {c['source']!r} would collide with existing {c['target']!r}")
        return 1

    if not plan:
        return 0

    if not args.apply:
        print("(dry-run mode — use --apply to perform renames)")
        return 0

    apply_renames(target_dir, plan)
    print(f"normalize_output_slugs: {len(plan)} rename(s) completed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
