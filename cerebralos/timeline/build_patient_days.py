#!/usr/bin/env python3
"""
CerebralOS — Timeline Engine (Layer 1)

Input:
  patient_evidence_v1.json

Output:
  patient_days_v1.json

Purpose:
- Deterministically group evidence items by local calendar day
- Fail-closed (no inferred timestamps)
- Preserve provenance
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None  # type: ignore


DT_QUALITY_EXPLICIT = "EXPLICIT"
DT_QUALITY_DOCUMENT = "DOCUMENT"
DT_QUALITY_DATE_ONLY = "DATE_ONLY"
DT_QUALITY_MISSING = "MISSING"
DT_QUALITY_ANCHOR_DATE = "ANCHOR_DATE"

DEFAULT_TZ = "America/Chicago"

# Regex for extracting date from evidence text header: [TYPE] YYYY-MM-DD ...
_RE_TEXT_HEADER_DATE = re.compile(
    r"^\s*\[[A-Z_]+\]\s+(?P<date>\d{4}-\d{2}-\d{2})"
)


# ----------------------------
# Utilities
# ----------------------------

def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8"
    )


def _parse_iso_dt(s: Any) -> Optional[datetime]:
    if not isinstance(s, str):
        return None
    s = s.strip().replace(" ", "T")
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _parse_date_only(s: str) -> Optional[datetime]:
    try:
        d = datetime.strptime(s.strip(), "%Y-%m-%d").date()
        return datetime.combine(d, time(12, 0, 0))
    except Exception:
        return None


def _to_local_naive(dt: datetime, tz_name: str) -> datetime:
    if ZoneInfo is None:
        return dt if dt.tzinfo is None else dt.replace(tzinfo=None)
    tz = ZoneInfo(tz_name)
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(tz).replace(tzinfo=None)


def _day_key(dt_local: datetime) -> str:
    return dt_local.date().isoformat()


def _stable_sort_key(item: Dict[str, Any]) -> Tuple:
    dt = _parse_iso_dt(item.get("dt")) if item.get("dt") else None
    missing = 1 if dt is None else 0
    return (missing, dt or datetime.max, item.get("source_id", ""))


# ----------------------------
# Core
# ----------------------------

def build_patient_days(evidence: Dict[str, Any]) -> Dict[str, Any]:
    meta_in = evidence.get("meta") if isinstance(evidence.get("meta"), dict) else {}
    items_in = evidence.get("items") if isinstance(evidence.get("items"), list) else []

    tz_name = meta_in.get("timezone") or DEFAULT_TZ
    patient_id = meta_in.get("patient_id") or "DATA_NOT_AVAILABLE"
    arrival_datetime = meta_in.get("arrival_datetime") or "DATA_NOT_AVAILABLE"

    # Compute day0 if possible
    day0_date = "DATA_NOT_AVAILABLE"
    arrival_dt = _parse_iso_dt(arrival_datetime)
    if arrival_dt:
        local = _to_local_naive(arrival_dt, tz_name)
        day0_date = local.date().isoformat()

    out: Dict[str, Any] = {
        "meta": {
            "patient_id": patient_id,
            "timezone": tz_name,
            "arrival_datetime": arrival_datetime,
            "day0_date": day0_date,
        },
        "days": {}
    }

    for raw in items_in:
        if not isinstance(raw, dict):
            continue

        source_id = str(raw.get("idx", raw.get("source_id", "DATA_NOT_AVAILABLE")))
        itype = raw.get("kind") or raw.get("type") or "note"
        payload = {"text": raw.get("text")}

        chosen_dt: Optional[datetime] = None
        dt_quality = DT_QUALITY_MISSING
        time_missing = False

        # Detect time_defaulted_0000 from upstream warnings
        item_warnings_raw = raw.get("warnings")
        has_time_defaulted = (
            isinstance(item_warnings_raw, (list, tuple))
            and "time_defaulted_0000" in item_warnings_raw
        )

        # Support multiple timestamp key names
        for key in ("dt", "datetime"):
            if isinstance(raw.get(key), str):
                parsed = _parse_iso_dt(raw[key])
                if parsed:
                    chosen_dt = parsed
                    dt_quality = DT_QUALITY_EXPLICIT
                    break

        if chosen_dt is None:
            for key in ("document_dt", "document_datetime"):
                if isinstance(raw.get(key), str):
                    parsed = _parse_iso_dt(raw[key])
                    if parsed:
                        chosen_dt = parsed
                        dt_quality = DT_QUALITY_DOCUMENT
                        break

        if chosen_dt is None:
            for key in ("date",):
                if isinstance(raw.get(key), str):
                    parsed = _parse_date_only(raw[key])
                    if parsed:
                        chosen_dt = parsed
                        dt_quality = DT_QUALITY_DATE_ONLY
                        time_missing = True
                        break

        # Downgrade EXPLICIT to DATE_ONLY when time was fabricated
        if has_time_defaulted and dt_quality == DT_QUALITY_EXPLICIT:
            dt_quality = DT_QUALITY_DATE_ONLY
            time_missing = True

        day_bucket = "__UNDATED__"
        dt_out = None

        if chosen_dt:
            local = _to_local_naive(chosen_dt, tz_name)
            if time_missing:
                # Store date-only ISO (no fabricated midnight)
                dt_out = local.date().isoformat()
            else:
                dt_out = local.isoformat(timespec="seconds")
            day_bucket = _day_key(local)

        # Preserve header_dt from evidence for anchoring
        header_dt_raw = raw.get("header_dt")

        item_out: Dict[str, Any] = {
            "type": itype,
            "source_id": source_id,
            "dt_quality": dt_quality,
            "payload": payload,
        }
        if dt_out:
            item_out["dt"] = dt_out
        if time_missing:
            item_out["time_missing"] = True
        if header_dt_raw:
            item_out["header_dt"] = str(header_dt_raw)
        # Preserve warnings from evidence items
        if item_warnings_raw:
            item_out["warnings"] = item_warnings_raw

        day_obj = out["days"].setdefault(day_bucket, {"items": []})
        day_obj["items"].append(item_out)

    # ── Rescue __UNDATED__ items using deterministic date anchors ──
    _rescue_undated_items(out, tz_name)

    # Sort each day deterministically
    for day_key, day_obj in out["days"].items():
        items = day_obj.get("items") or []
        items.sort(key=_stable_sort_key)
        day_obj["items"] = items

    return out


def _rescue_undated_items(out: Dict[str, Any], tz_name: str) -> None:
    """Try to assign date buckets to __UNDATED__ items using deterministic anchors.

    Priority:
      1. Nearest preceding dated evidence item (by source_id) in the timeline
      2. Date extracted from the item's text header [TYPE] YYYY-MM-DD ...
      3. Keep __UNDATED__ if no anchor found
    """
    undated_obj = out["days"].get("__UNDATED__")
    if not undated_obj:
        return
    undated_items = undated_obj.get("items") or []
    if not undated_items:
        return

    # Build ordered list of (source_id_int, day_key) from all dated items
    dated_index: List[tuple] = []  # (sid_int, day_key)
    for day_key, day_obj in out["days"].items():
        if day_key == "__UNDATED__":
            continue
        for item in day_obj.get("items") or []:
            sid = item.get("source_id", "")
            try:
                dated_index.append((int(sid), day_key))
            except (ValueError, TypeError):
                continue
    dated_index.sort(key=lambda x: x[0])

    rescued: List[tuple] = []  # (day_key, item)
    remaining: List[Dict[str, Any]] = []

    for item in undated_items:
        sid_str = item.get("source_id", "")
        try:
            sid_int = int(sid_str)
        except (ValueError, TypeError):
            sid_int = None

        anchor_date: Optional[str] = None
        anchor_method: Optional[str] = None

        # Strategy 1: nearest preceding dated item by source_id
        if sid_int is not None and dated_index:
            for dsid, dday in reversed(dated_index):
                if dsid < sid_int:
                    anchor_date = dday
                    anchor_method = "NEAREST_PRECEDING"
                    break

        # Strategy 2: date from the item's text header
        if anchor_date is None:
            text = (item.get("payload") or {}).get("text", "")
            first_line = text.split("\n", 1)[0] if text else ""
            m = _RE_TEXT_HEADER_DATE.match(first_line)
            if m:
                anchor_date = m.group("date")
                anchor_method = "HEADER_DATE"

        # Strategy 3: header_dt field from evidence
        if anchor_date is None:
            hdt = item.get("header_dt")
            if isinstance(hdt, str) and len(hdt) >= 10:
                anchor_date = hdt[:10]  # YYYY-MM-DD portion
                anchor_method = "HEADER_DT_FIELD"

        if anchor_date:
            item["dt_quality"] = DT_QUALITY_ANCHOR_DATE
            item["anchor_method"] = anchor_method
            item["time_missing"] = True
            item["dt"] = anchor_date  # date-only, no fabricated time
            rescued.append((anchor_date, item))
        else:
            remaining.append(item)

    # Move rescued items to their date buckets
    for day_key, item in rescued:
        day_obj = out["days"].setdefault(day_key, {"items": []})
        day_obj["items"].append(item)

    # Update or remove __UNDATED__
    if remaining:
        out["days"]["__UNDATED__"]["items"] = remaining
    else:
        del out["days"]["__UNDATED__"]


def main() -> int:
    ap = argparse.ArgumentParser(description="Build calendar-day timeline from patient_evidence_v1.json")
    ap.add_argument("--in", dest="in_path", required=True)
    ap.add_argument("--out", dest="out_path", required=True)
    args = ap.parse_args()

    in_path = Path(args.in_path).expanduser().resolve()
    out_path = Path(args.out_path).expanduser().resolve()

    evidence = _read_json(in_path)
    patient_days = build_patient_days(evidence)
    _write_json(out_path, patient_days)

    print(f"OK ✅ Wrote patient_days: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
