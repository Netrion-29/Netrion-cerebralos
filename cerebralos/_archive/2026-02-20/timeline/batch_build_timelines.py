#!/usr/bin/env python3
"""
Batch: data_raw/*.txt -> outputs/evidence/<PAT>/patient_evidence_v1.json
                    -> outputs/timeline/<PAT>/patient_days_v1.json

- Continues on errors.
- Writes a run log to outputs/timeline/_batch_build_log.txt
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
    ap.add_argument("--src-dir", default="data_raw", help="Folder with patient .txt files (default: data_raw)")
    ap.add_argument("--pattern", default="*.txt", help="Glob pattern (default: *.txt)")
    ap.add_argument("--limit", type=int, default=0, help="Optional limit for quick tests (0 = no limit)")
    args = ap.parse_args()

    src_dir = (REPO_ROOT / args.src_dir).resolve()
    files = sorted(src_dir.glob(args.pattern))

    if args.limit and args.limit > 0:
        files = files[: args.limit]

    log_path = REPO_ROOT / "outputs" / "timeline" / "_batch_build_log.txt"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    lines = []
    lines.append(f"Batch timeline build @ {ts} UTC")
    lines.append(f"Repo: {REPO_ROOT}")
    lines.append(f"Source: {src_dir} ({len(files)} files)")
    lines.append("")

    ok = 0
    fail = 0

    for f in files:
        patient = f.stem  # assumes filename is already Patient_Slug.txt
        lines.append(f"=== {patient} ===")

        # 1) Evidence
        cmd1 = ["python3", "cerebralos/ingest/parse_patient_txt.py", "--in", str(f)]
        rc1, out1 = run_cmd(cmd1)
        lines.append(f"[evidence] rc={rc1}")
        if out1.strip():
            lines.append(out1.strip())

        # expected evidence path
        ev_path = REPO_ROOT / "outputs" / "evidence" / patient / "patient_evidence_v1.json"

        # 2) Timeline
        if rc1 == 0 and ev_path.exists():
            out_dir = REPO_ROOT / "outputs" / "timeline" / patient
            out_dir.mkdir(parents=True, exist_ok=True)
            out_json = out_dir / "patient_days_v1.json"
            cmd2 = [
                "python3", "cerebralos/timeline/build_patient_days.py",
                "--in", str(ev_path),
                "--out", str(out_json),
            ]
            rc2, out2 = run_cmd(cmd2)
            lines.append(f"[timeline] rc={rc2}")
            if out2.strip():
                lines.append(out2.strip())

            if rc2 == 0 and out_json.exists():
                ok += 1
                lines.append("RESULT: OK ✅")
            else:
                fail += 1
                lines.append("RESULT: FAIL ❌ (timeline)")
        else:
            fail += 1
            lines.append("RESULT: FAIL ❌ (evidence)")

        lines.append("")

    lines.append(f"SUMMARY: OK={ok} FAIL={fail}")
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"OK ✅ Batch complete. OK={ok} FAIL={fail}")
    print(f"Log: {log_path}")
    return 0 if fail == 0 else 2

if __name__ == "__main__":
    raise SystemExit(main())
