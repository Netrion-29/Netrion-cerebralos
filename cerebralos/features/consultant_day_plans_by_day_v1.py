#!/usr/bin/env python3
"""
consultant_day_plans_by_day_v1 — Per-Day Consultant Plan Reorganisation
=======================================================================

Reorganises ``consultant_plan_items_v1`` items into a per-day,
per-service structure that parallels ``trauma_daily_plan_by_day_v1``.

This is a **feature-first consumer**: it reads only from the
already-assembled ``consultant_plan_items_v1`` feature output
(and ``consultant_events_v1`` for service metadata).  It performs
no raw-text extraction of its own.

Strategy
--------
1. Read ``consultant_plan_items_v1.items[]`` from the assembled
   features dict.
2. Group items by calendar day (from ``ts[:10]``) and by service.
3. Within each day+service group, preserve chronological order and
   include author, timestamp, item_text, item_type, and evidence.
4. Attach per-service note_count from ``consultant_events_v1``
   when available.

Output key: ``consultant_day_plans_by_day_v1``

Output schema::

    {
        "days": {
            "<ISO-date>": {
                "services": {
                    "<service-name>": {
                        "items": [
                            {
                                "ts": "<ISO datetime>",
                                "author_name": "<name>",
                                "item_text": "<plan text>",
                                "item_type": "<type tag>",
                                "evidence": [...]
                            }, ...
                        ],
                        "item_count": <int>,
                        "authors": ["<name>", ...],
                    },
                    ...
                },
                "service_count": <int>,
                "item_count": <int>,
            },
            ...
        },
        "total_days": <int>,
        "total_items": <int>,
        "total_services": <int>,
        "services_seen": ["<service>", ...],
        "source_rule_id": "consultant_day_plans_from_plan_items"
                        | "no_plan_items"
                        | "no_consultant_events",
        "warnings": [...],
        "notes": [],
    }

Fail-closed behaviour:
  - No ``consultant_plan_items_v1`` or consultant_events_v1.consultant_present
    != "yes" → empty days, source_rule_id="no_consultant_events"
  - Consultant events present but plan_items.item_count == 0
    → empty days, source_rule_id="no_plan_items"
  - Items grouped successfully
    → source_rule_id="consultant_day_plans_from_plan_items"

Design:
  - Deterministic, fail-closed.
  - Feature-first: reads only from assembled features dict.
  - No LLM, no ML, no clinical inference.
  - Evidence preserved via passthrough from ``consultant_plan_items_v1``.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Set


def extract_consultant_day_plans_by_day(
    features: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Reorganise consultant plan items into per-day, per-service buckets.

    Parameters
    ----------
    features : dict
        The assembled ``features`` dict from ``build_patient_features``.
        Must already contain ``consultant_events_v1`` and
        ``consultant_plan_items_v1``.

    Returns
    -------
    Dict with per-day/per-service consultant plan items.
    """
    warnings: List[str] = []
    notes: List[str] = []

    # ── Read upstream features ──────────────────────────────────
    ce = features.get("consultant_events_v1", {})
    cpi = features.get("consultant_plan_items_v1", {})

    consultant_present = ce.get("consultant_present", "DATA NOT AVAILABLE")

    # Fail-closed: no consultant events at all
    if consultant_present != "yes":
        return {
            "days": {},
            "total_days": 0,
            "total_items": 0,
            "total_services": 0,
            "services_seen": [],
            "source_rule_id": "no_consultant_events",
            "warnings": warnings,
            "notes": ["No consultant events present in upstream features."],
        }

    items = cpi.get("items", [])
    if not items or cpi.get("item_count", 0) == 0:
        return {
            "days": {},
            "total_days": 0,
            "total_items": 0,
            "total_services": 0,
            "services_seen": [],
            "source_rule_id": "no_plan_items",
            "warnings": warnings,
            "notes": [
                "Consultant services present but no plan items extracted. "
                "Notes may lack explicit plan/recommendation sections."
            ],
        }

    # ── Group items by day → service ────────────────────────────
    # day_iso → service → list of items
    day_service_items: Dict[str, Dict[str, List[Dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    all_services: Set[str] = set()

    for item in items:
        ts = item.get("ts", "")
        if not ts or len(ts) < 10:
            warnings.append(
                f"Consultant plan item missing valid ts: "
                f"service={item.get('service', '?')}, "
                f"text={str(item.get('item_text', ''))[:40]}"
            )
            continue

        day_iso = ts[:10]
        service = item.get("service", "UNKNOWN")
        all_services.add(service)

        day_service_items[day_iso][service].append({
            "ts": ts,
            "author_name": item.get("author_name", "DATA NOT AVAILABLE"),
            "item_text": item.get("item_text", ""),
            "item_type": item.get("item_type", "recommendation"),
            "evidence": item.get("evidence", []),
        })

    # ── Build output structure ──────────────────────────────────
    days_result: Dict[str, Dict[str, Any]] = {}
    total_items = 0

    for day_iso in sorted(day_service_items.keys()):
        service_map = day_service_items[day_iso]
        services_out: Dict[str, Dict[str, Any]] = {}
        day_item_count = 0

        for svc_name in sorted(service_map.keys()):
            svc_items = service_map[svc_name]
            # Sort by ts for determinism
            svc_items.sort(key=lambda x: x.get("ts", ""))

            # Collect unique authors
            authors_seen: List[str] = []
            for si in svc_items:
                a = si.get("author_name", "")
                if a and a != "DATA NOT AVAILABLE" and a not in authors_seen:
                    authors_seen.append(a)

            services_out[svc_name] = {
                "items": svc_items,
                "item_count": len(svc_items),
                "authors": authors_seen,
            }
            day_item_count += len(svc_items)

        days_result[day_iso] = {
            "services": services_out,
            "service_count": len(services_out),
            "item_count": day_item_count,
        }
        total_items += day_item_count

    return {
        "days": days_result,
        "total_days": len(days_result),
        "total_items": total_items,
        "total_services": len(all_services),
        "services_seen": sorted(all_services),
        "source_rule_id": "consultant_day_plans_from_plan_items",
        "warnings": warnings,
        "notes": notes,
    }
