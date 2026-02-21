#!/usr/bin/env python3
"""
Batch: outputs/timeline/<PAT>/patient_days_v1.json
   -> outputs/reporting/<PAT>/TRAUMA_DAILY_NOTES_v3.txt

- Continues on errors.
- Writes a run log to outputs/reporting/_batch_render_log.txt
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from datetime import datetime

REPO_ROOT = Path(__file__).resolve().parents[2]

def run_cmd(cmd: list[str]) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
    out = (p.stdout or "") + (p.stderr or "")
    return p.returncode, out

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeline-root", default="outputs/timeline", help="Timeline root (default: outputs/timeline)")
    ap.add_argument("--renderer", default="cerebralos/reporting/render_trauma_daily_notes_v3.py")
    ap.add_argument("--limit", type=int, default=0, help="Optional limit for quick tests (0 = no limit)")
    args = ap.parse_args()

    timeline_root = (REPO_ROOT / args.timeline_root).resolve()
    renderer = (REPO_ROOT / args.renderer).resolve()

    patients = sorted([p for p in timeline_root.iterdir() if p.is_dir() and not p.name.startswith("_")])

    if args.limit and args.limit > 0:
        patients = patients[: args.limit]

    log_path = REPO_ROOT / "outputs" / "reporting" / "_batch_render_log.txt"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    lines = []
    lines.append(f"Batch daily-notes render @ {ts} UTC")
    lines.append(f"Repo: {REPO_ROOT}")
    lines.append(f"Renderer: {renderer}")
    lines.append(f"Patients: {len(patients)}")
    lines.append("")

    ok = 0
    fail = 0

    for pdir in patients:
        pat = pdir.name
        in_path = pdir / "patient_days_v1.json"
        out_dir = REPO_ROOT / "outputs" / "reporting" / pat
        out_path = out_dir / "TRAUMA_DAILY_NOTES_v3.txt"

        lines.append(f"=== {pat} ===")
        if not in_path.exists():
            fail += 1
            lines.append("RESULT: FAIL ❌ (missing patient_days_v1.json)")
            lines.append("")
            continue

        out_dir.mkdir(parents=True, exist_ok=True)
        cmd = [
            "python3", str(renderer),
            "--in", str(in_path),
            "--out", str(out_path),
        ]
        rc, out = run_cmd(cmd)
        lines.append(f"rc={rc}")
        if out.strip():
            lines.append(out.strip())

        if rc == 0 and out_path.exists():
            ok += 1
            lines.append("RESULT: OK ✅")
        else:
            fail += 1
            lines.append("RESULT: FAIL ❌ (render)")

        lines.append("")

    lines.append(f"SUMMARY: OK={ok} FAIL={fail}")
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"OK ✅ Batch complete. OK={ok} FAIL={fail}")
    print(f"Log: {log_path}")
    return 0 if fail == 0 else 2

if __name__ == "__main__":
    raise SystemExit(main())
