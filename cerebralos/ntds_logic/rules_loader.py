#!/usr/bin/env python3
"""
CerebralOS — NTDS Logic Rules Loader (v1)

Loads:
- rules/ntds/logic/contract_v1.json
- rules/ntds/logic/shared_v1.json
- rules/ntds/logic/<year>/<event>.json

Design:
- Deterministic
- Minimal validation (fail-closed)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Ruleset:
    contract: Dict[str, Any]
    shared: Dict[str, Any]
    event: Dict[str, Any]
    event_path: Path


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"Missing JSON: {path}")
    except json.JSONDecodeError as e:
        raise SystemExit(f"Invalid JSON: {path}\n{e}")


def load_contract() -> Dict[str, Any]:
    path = REPO_ROOT / "rules" / "ntds" / "logic" / "contract_v1.json"
    obj = _read_json(path)

    # Minimal fail-closed checks
    if obj.get("meta", {}).get("locked") is not True:
        raise SystemExit("contract_v1.json must have meta.locked=true")
    allowed = obj.get("outcomes", {}).get("allowed", [])
    if not isinstance(allowed, list) or not allowed:
        raise SystemExit("contract_v1.json missing outcomes.allowed")
    return obj


def load_shared() -> Dict[str, Any]:
    path = REPO_ROOT / "rules" / "ntds" / "logic" / "shared_v1.json"
    obj = _read_json(path)

    if obj.get("meta", {}).get("locked") is not True:
        raise SystemExit("shared_v1.json must have meta.locked=true")
    # Support either legacy "buckets" key or canonical "noise_buckets".
    # Normalize to `noise_buckets` internally.
    if "noise_buckets" in obj and isinstance(obj["noise_buckets"], dict):
        # already canonical
        return obj
    if "buckets" in obj and isinstance(obj["buckets"], dict):
        # normalize: copy buckets -> noise_buckets and keep other top-level keys
        normalized = dict(obj)
        normalized["noise_buckets"] = dict(normalized["buckets"])
        return normalized
    raise SystemExit("shared_v1.json missing noise_buckets (or legacy buckets) dict")


def print_shared_debug(ruleset: Ruleset) -> None:
    """Print a compact debug summary of shared buckets and event expansions.

    Usage: import rules_loader as rl; rs = rl.load_ruleset(...); rl.print_shared_debug(rs)
    """
    s = ruleset.shared.get("noise_buckets", {})
    print("Shared noise buckets loaded:")
    for name, patterns in s.items():
        print(f" - {name}: {len(patterns)} patterns")
    ev = ruleset.event
    includes = ev.get("include_noise_buckets", [])
    print(f"Event includes: {includes}")
    # counts of expanded patterns
    total_q = sum(len(g.get("query_patterns", [])) for g in ev.get("gates", []))
    total_ex = sum(len(g.get("exclude_patterns", [])) for g in ev.get("gates", [])) + sum(
        len(ex.get("exclude_patterns", [])) for ex in ev.get("exclusions", [])
    )
    print(f"Total query patterns: {total_q}")
    print(f"Total exclude patterns: {total_ex}")


def event_path(year: int, event_id: int) -> Path:
    return REPO_ROOT / "rules" / "ntds" / "logic" / str(year) / f"{event_id:02d}_{_event_slug(event_id)}.json"


def _event_slug(event_id: int) -> str:
    """
    For now we only need DVT (08) in this sprint.
    Extend later for the other 20 events.
    """
    mapping = {
        1: "aki",
        2: "ards",
        3: "alcohol_withdrawal",
        4: "cardiac_arrest_cpr",
        5: "cauti",
        6: "clabsi",
        7: "deep_ssi",
        8: "dvt",
        9: "delirium",
        10: "mi",
        11: "organ_space_ssi",
        12: "osteomyelitis",
        13: "pressure_ulcer",
        14: "pe",
        15: "severe_sepsis",
        16: "stroke_cva",
        17: "superficial_ssi",
        18: "unplanned_icu_admission",
        19: "unplanned_intubation",
        20: "or_return",
        21: "vap"
    }
    # Additional events
    mapping[20] = "or_return"
    mapping[14] = "pe"
    if event_id not in mapping:
        raise SystemExit(
            f"Event slug unknown for event_id={event_id}. Add it to rules_loader._event_slug()."
        )
    return mapping[event_id]


def load_event(year: int, event_id: int) -> Tuple[Dict[str, Any], Path]:
    path = event_path(year, event_id)
    obj = _read_json(path)

    meta = obj.get("meta", {})
    if int(meta.get("event_id", -1)) != int(event_id):
        raise SystemExit(f"{path} meta.event_id mismatch")
    if int(meta.get("ntds_year", -1)) != int(year):
        raise SystemExit(f"{path} meta.ntds_year mismatch")

    if "gates" not in obj or not isinstance(obj["gates"], list) or not obj["gates"]:
        raise SystemExit(f"{path} missing gates[]")
    return obj, path


def load_ruleset(year: int, event_id: int) -> Ruleset:
    contract = load_contract()
    shared = load_shared()
    event, path = load_event(year, event_id)
    # Normalize event-level include keys to `include_noise_buckets`.
    include_keys = []
    for k in ("include_shared", "include_noise_buckets", "include_buckets"):
        if isinstance(event.get(k), list):
            include_keys.extend(event.get(k))
            # remove legacy keys to avoid confusion
            if k != "include_noise_buckets":
                event.pop(k, None)
    if include_keys:
        # preserve order, first-seen
        seen = set()
        deduped = []
        for v in include_keys:
            if v not in seen:
                deduped.append(v)
                seen.add(v)
        event["include_noise_buckets"] = deduped

    # Helper: preserve order and deduplicate first-seen
    def _uniq_preserve(seq):
        out = []
        seen = set()
        for s in seq:
            if s not in seen:
                out.append(s)
                seen.add(s)
        return out

    # Helper: expand a list that may contain bucket names into concrete patterns
    def _expand_items_with_noise_buckets(lst, expand_if_included_only=False):
        out = []
        noise = shared.get("noise_buckets", {})
        include_list = event.get("include_noise_buckets", []) if expand_if_included_only else None
        for item in lst:
            if isinstance(item, str) and item in noise:
                # only expand if not restricted, or explicitly included
                if include_list is None or item in include_list:
                    out.extend(list(noise[item]))
                else:
                    # keep symbolic name if not included
                    out.append(item)
            else:
                out.append(item)
        return _uniq_preserve(out)

    # For each gate/exclusion produce query_patterns and exclude_patterns arrays
    for g in event.get("gates", []):
        # original lists (may contain bucket names)
        qkeys = g.get("query_keys", []) if isinstance(g.get("query_keys"), list) else []
        ex_keys = g.get("exclude_keys", []) if isinstance(g.get("exclude_keys"), list) else []
        ex_noise = g.get("exclude_noise_keys", []) if isinstance(g.get("exclude_noise_keys"), list) else []

        # expand exclude lists always (exclude_keys and exclude_noise_keys)
        expanded_ex = _expand_items_with_noise_buckets(ex_keys, expand_if_included_only=False)
        expanded_ex_noise = _expand_items_with_noise_buckets(ex_noise, expand_if_included_only=False)

        # For query_keys expand only when the key matches a noise bucket AND
        # is included via event.include_noise_buckets (explicit intent).
        expanded_q = _expand_items_with_noise_buckets(qkeys, expand_if_included_only=True)

        # Compose final patterns, preserving order and de-duplicating first-seen
        g["query_patterns"] = _uniq_preserve([p for p in expanded_q if isinstance(p, str)])
        g["exclude_patterns"] = _uniq_preserve(
            [p for p in expanded_ex if isinstance(p, str)] + [p for p in expanded_ex_noise if isinstance(p, str)]
        )

    for ex in event.get("exclusions", []):
        ex_keys = ex.get("exclude_keys", []) if isinstance(ex.get("exclude_keys"), list) else []
        expanded_ex = _expand_items_with_noise_buckets(ex_keys, expand_if_included_only=False)
        ex["exclude_patterns"] = _uniq_preserve([p for p in expanded_ex if isinstance(p, str)])

    # Attach normalized shared (ensure only noise_buckets is used going forward)
    normalized_shared = dict(shared)
    if "buckets" in normalized_shared:
        normalized_shared.pop("buckets", None)

    ruleset = Ruleset(contract=contract, shared=normalized_shared, event=event, event_path=path)
    return ruleset


def load_event_rules(year: int, event_id: int) -> dict:
    """Load and return a fully-normalized rule dict for debugging.

    The returned dict contains:
      - meta: top-level meta for the event
      - gates: list of gates where each gate includes `query_patterns` and `exclude_patterns`
      - exclusions: list of exclusions where each includes `exclude_patterns`

    This is a thin wrapper around `load_ruleset` that exposes the expanded
    event structure as plain dict for debugging and downstream inspection.
    """
    ruleset = load_ruleset(year, event_id)
    ev = ruleset.event

    # Build sanitized output
    out = {
        "meta": ev.get("meta", {}),
        "gates": [],
        "exclusions": [],
    }

    for g in ev.get("gates", []):
        gate_copy = dict(g)
        # Ensure arrays exist
        gate_copy["query_patterns"] = gate_copy.get("query_patterns", [])
        gate_copy["exclude_patterns"] = gate_copy.get("exclude_patterns", [])
        out["gates"].append(gate_copy)

    for ex in ev.get("exclusions", []):
        ex_copy = dict(ex)
        ex_copy["exclude_patterns"] = ex_copy.get("exclude_patterns", [])
        out["exclusions"].append(ex_copy)

    return out
