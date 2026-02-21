#!/usr/bin/env python3
"""
Render TRAUMA DAILY NOTES from patient_days_v1.json

Deterministic:
- One section per calendar day (sorted)
- Items listed in order stored (already sorted by timeline engine)
- No inference. If something isn't explicitly present, it won't be added.
"""

from __future__ import annotations
import argparse, json
from pathlib import Path
from typing import Any, Dict, List

def main() -> int:
    ap = argparse.ArgumentParser(description="Render TRAUMA DAILY NOTES from patient_days_v1.json")
    ap.add_argument("--in", dest="in_path", required=True)
    ap.add_argument("--out", dest="out_path", required=True)
    args = ap.parse_args()

    inp = Path(args.in_path).expanduser().resolve()
    outp = Path(args.out_path).expanduser().resolve()

    obj = json.loads(inp.read_text(encoding="utf-8"))
    meta: Dict[str, Any] = obj.get("meta") or {}
    days: Dict[str, Any] = obj.get("days") or {}

    day_keys = sorted([k for k in days.keys() if k != "UNDATED"])
    if "UNDATED" in days:
        day_keys.append("UNDATED")

    lines: List[str] = []
    lines.append("TRAUMA DAILY NOTES")
    lines.append(f"Patient ID: {meta.get('patient_id','DATA NOT AVAILABLE')}")
    lines.append(f"Arrival: {meta.get('arrival_datetime','DATA NOT AVAILABLE')}")
    lines.append(f"Timezone: {meta.get('timezone','DATA NOT AVAILABLE')}")
    lines.append("")

    def emit_bucket(title: str, items: List[Dict[str, Any]]) -> None:
        lines.append(f"{title}:")
        if not items:
            lines.append("DATA NOT AVAILABLE")
            lines.append("")
            return
        for it in items:
            dt = it.get("dt") or "TIME DATA NOT AVAILABLE"
            typ = it.get("type") or "TYPE DATA NOT AVAILABLE"
            sid = it.get("source_id") or "SOURCE DATA NOT AVAILABLE"
            txt = ((it.get("payload") or {}).get("text") or "").strip().replace("\n", " ")
            if len(txt) > 500:
                txt = txt[:500] + "…"
            lines.append(f"- {dt} [{typ}] ({sid}) {txt}")
        lines.append("")

    for day in day_keys:
        day_obj = days.get(day) or {}
        items = day_obj.get("items") or []

        lines.append(f"===== {day} =====")
        if not items:
            lines.append("DATA NOT AVAILABLE")
            lines.append("")
            continue

        # Very conservative first-pass bucketing by type string
        heme = [i for i in items if str(i.get("type","")).upper() in ("NURSING_NOTE","PROGRESS_NOTE","ED_NOTE","TRAUMA_HP")]
        resp = heme
        neuro = heme
        procs = [i for i in items if "PROCED" in str(i.get("type","")).upper() or "OP" in str(i.get("type","")).upper()]
        imaging = [i for i in items if "RAD" in str(i.get("type","")).upper() or "IMAG" in str(i.get("type","")).upper()]
        labs = [i for i in items if "LAB" in str(i.get("type","")).upper()]
        consults = [i for i in items if "CONSULT" in str(i.get("type","")).upper()]
        events = [i for i in items if str(i.get("type","")).upper() in ("NURSING_NOTE", "ED_NOTE")]

        emit_bucket("Hemodynamic status", heme)
        emit_bucket("Respiratory status", resp)
        emit_bucket("Neuro status", neuro)
        emit_bucket("Procedures performed", procs)
        emit_bucket("Imaging", imaging)
        emit_bucket("Labs (significant only)", labs)
        emit_bucket("Consults", consults)
        emit_bucket("Complications / Events", events)

    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"OK ✅ Wrote daily notes: {outp}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
