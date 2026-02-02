#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from cerebralos.ntds_logic.model import (
    Evidence,
    EvidencePointer,
    EventResult,
    GateResult,
    HardStop,
    Outcome,
    PatientFacts,
    SourceType,
)
from cerebralos.ntds_logic.rules_loader import load_ruleset
from cerebralos.ntds_logic.build_patientfacts_from_txt import build_patientfacts

REPO_ROOT = Path(__file__).resolve().parents[2]


_TS_PATTERNS = [
    ("%Y-%m-%dT%H:%M:%SZ", True),
    ("%Y-%m-%dT%H:%M:%S", False),
    ("%Y-%m-%d %H:%M:%S", False),
    ("%Y-%m-%d %H:%M", False),
    ("%m/%d/%y %H%M", False),
    ("%m/%d/%Y %H%M", False),
    ("%m/%d/%Y %H:%M", False),
    ("%m/%d/%y %H:%M", False),
]


def parse_ts(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    s = ts.strip()
    for fmt, is_utc_z in _TS_PATTERNS:
        try:
            dt = datetime.strptime(s, fmt)
            if is_utc_z:
                return dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            continue
    return None


def is_after(arrival: Optional[str], ev_ts: Optional[str]) -> Optional[bool]:
    a = parse_ts(arrival)
    b = parse_ts(ev_ts)
    if not a or not b:
        return None
    if (a.tzinfo is None) != (b.tzinfo is None):
        return None
    return b > a


def _compile_patterns(patterns: List[str]) -> List[re.Pattern[str]]:
    out: List[re.Pattern[str]] = []
    for p in patterns:
        try:
            out.append(re.compile(p, re.IGNORECASE))
        except re.error:
            out.append(re.compile(re.escape(p), re.IGNORECASE))
    return out


def _patterns_for_key(patient: PatientFacts, query_key: str) -> List[re.Pattern[str]]:
    patterns_map = (patient.facts or {}).get("query_patterns", {}) or {}
    pats = patterns_map.get(query_key, [])
    if not isinstance(pats, list) or not pats:
        return []
    return _compile_patterns([str(x) for x in pats])


def match_evidence(
    patient: PatientFacts,
    query_key: str,
    allowed_sources: Optional[List[str]] = None,
    max_hits: int = 8,
) -> List[Evidence]:
    compiled = _patterns_for_key(patient, query_key)
    if not compiled:
        return []

    allowed_set = None
    if allowed_sources:
        allowed_set = {s for s in allowed_sources}

    hits: List[Evidence] = []
    for e in patient.evidence:
        if allowed_set and e.source_type.name not in allowed_set:
            continue
        txt = e.text or ""
        if any(p.search(txt) for p in compiled):
            hits.append(e)
            if len(hits) >= max_hits:
                break
    return hits


def line_matches_any(patient: PatientFacts, text: str, query_key: str) -> bool:
    compiled = _patterns_for_key(patient, query_key)
    if not compiled:
        return False
    t = text or ""
    return any(p.search(t) for p in compiled)


def eval_exclude_if_any(gate: Dict[str, Any], patient: PatientFacts, contract: Dict[str, Any]) -> Optional[HardStop]:
    """
    Hard-stop exclusion.

    Supports:
      - query_keys: patterns that indicate the exclusion condition
      - require_context_keys: patterns that MUST ALSO match the same line
        (prevents false positives like POA=Power of Attorney)
    """
    query_keys = gate.get("query_keys", [])
    if not isinstance(query_keys, list):
        query_keys = []

    require_context_keys = gate.get("require_context_keys", [])
    if require_context_keys is None:
        require_context_keys = []
    if not isinstance(require_context_keys, list):
        require_context_keys = []

    max_items = int(contract.get("evidence", {}).get("max_items_per_gate", 8))

    # For each query_key, collect matching evidence lines.
    # If require_context_keys is present, keep only lines that ALSO match ANY context key.
    for qk in query_keys:
        hits = match_evidence(patient, str(qk), allowed_sources=None, max_hits=50)
        if not hits:
            continue

        filtered: List[Evidence] = []
        if require_context_keys:
            for e in hits:
                if any(line_matches_any(patient, e.text or "", str(ctx)) for ctx in require_context_keys):
                    filtered.append(e)
        else:
            filtered = hits

        if filtered:
            rule_id = str(gate.get("rule_id") or gate.get("gate_id") or "EXCLUSION")
            reason = str(gate.get("reason") or "Excluded per NTDS rule")
            return HardStop(rule_id=rule_id, reason=reason, evidence=filtered[:max_items])

    return None


def eval_evidence_any(gate: Dict[str, Any], patient: PatientFacts, contract: Dict[str, Any]) -> GateResult:
    qks = gate.get("query_keys", [])
    if not isinstance(qks, list):
        qks = []
    min_count = int(gate.get("min_count", 1))
    allowed_sources = gate.get("allowed_sources", None)

    hits: List[Evidence] = []
    for qk in qks:
        hits.extend(match_evidence(patient, str(qk), allowed_sources=allowed_sources, max_hits=8))

    passed = len(hits) >= min_count
    reason = "Evidence found." if passed else str(gate.get("fail_reason") or "Required evidence not found.")
    max_items = int(contract.get("evidence", {}).get("max_items_per_gate", 8))

    return GateResult(gate=str(gate.get("gate_id")), passed=passed, reason=reason, evidence=hits[:max_items])


def eval_timing_after_arrival(gate: Dict[str, Any], patient: PatientFacts, contract: Dict[str, Any]) -> GateResult:
    qk = str(gate.get("query_key") or "")
    allowed_sources = gate.get("allowed_sources", None)
    timestamp_required = bool(gate.get("timestamp_required", True))
    arrival_field = str(gate.get("arrival_field") or "arrival_time")
    arrival_time = (patient.facts or {}).get(arrival_field)

    hits = match_evidence(patient, qk, allowed_sources=allowed_sources, max_hits=8)
    if not hits:
        return GateResult(gate=str(gate.get("gate_id")), passed=False, reason="No onset evidence found.", evidence=[])

    after: List[Evidence] = []
    unknown: List[Evidence] = []
    for e in hits:
        comp = is_after(str(arrival_time) if arrival_time else None, e.timestamp)
        if comp is True:
            after.append(e)
        else:
            unknown.append(e)

    max_items = int(contract.get("evidence", {}).get("max_items_per_gate", 8))

    if after:
        return GateResult(
            gate=str(gate.get("gate_id")),
            passed=True,
            reason="Onset evidence timestamped after arrival.",
            evidence=after[:max_items],
        )

    if timestamp_required:
        return GateResult(
            gate=str(gate.get("gate_id")),
            passed=False,
            reason=str(gate.get("fail_reason") or "Cannot prove timing after arrival."),
            evidence=unknown[:max_items],
        )

    return GateResult(
        gate=str(gate.get("gate_id")),
        passed=False,
        reason="Timing not proven after arrival.",
        evidence=unknown[:max_items],
    )


def eval_requires_treatment_any(gate: Dict[str, Any], patient: PatientFacts, contract: Dict[str, Any]) -> GateResult:
    qks = gate.get("query_keys", [])
    if not isinstance(qks, list):
        qks = []
    min_count = int(gate.get("min_count", 1))
    allowed_sources = gate.get("allowed_sources", None)

    hits: List[Evidence] = []
    for qk in qks:
        hits.extend(match_evidence(patient, str(qk), allowed_sources=allowed_sources, max_hits=8))

    passed = len(hits) >= min_count
    reason = "Treatment evidence found." if passed else str(gate.get("fail_reason") or "Required treatment not found.")
    max_items = int(contract.get("evidence", {}).get("max_items_per_gate", 8))

    return GateResult(gate=str(gate.get("gate_id")), passed=passed, reason=reason, evidence=hits[:max_items])


def evaluate_event(event_rules: Dict[str, Any], contract: Dict[str, Any], patient: PatientFacts) -> EventResult:
    meta = event_rules.get("meta", {})
    event_id = int(meta.get("event_id"))
    name = str(meta.get("canonical_name"))
    year = int(meta.get("ntds_year"))

    r = EventResult(event_id=event_id, canonical_name=name, ntds_year=year, outcome=Outcome.UNABLE_TO_DETERMINE)

    # Exclusions hard-stop
    for ex in event_rules.get("exclusions", []) or []:
        if str(ex.get("gate_type")) != "exclude_if_any":
            continue
        hs = eval_exclude_if_any(ex, patient, contract)
        if hs:
            r.outcome = Outcome.EXCLUDED
            r.hard_stop = hs
            return r

    # Gates in order
    for gate in event_rules.get("gates", []) or []:
        gt = str(gate.get("gate_type", ""))
        if gt == "evidence_any":
            gr = eval_evidence_any(gate, patient, contract)
        elif gt == "timing_after_arrival":
            gr = eval_timing_after_arrival(gate, patient, contract)
        elif gt == "requires_treatment_any":
            gr = eval_requires_treatment_any(gate, patient, contract)
        else:
            gr = GateResult(gate=str(gate.get("gate_id")), passed=False, reason=f"Unknown gate_type: {gt}", evidence=[])

        r.gate_trace.append(gr)

        # If this gate defines a `pass_outcome` and it passed, terminate early
        # with the provided outcome. This supports use-cases like "imaging
        # explicitly negative for PE" where a positive match should short-
        # circuit evaluation to NO (or other outcome) without treating it as
        # an exclusion.
        try:
            pass_outcome = gate.get("pass_outcome", None)
            if pass_outcome and gr.passed:
                pass_outcome_up = str(pass_outcome).upper()
                allowed = set(contract.get("outcomes", {}).get("allowed", []))
                if pass_outcome_up not in allowed:
                    pass_outcome_up = contract.get("outcomes", {}).get("defaults", {}).get(
                        "missing_required_data", "UNABLE_TO_DETERMINE"
                    )
                r.outcome = Outcome(pass_outcome_up)
                # Attach a HardStop-like object for evidence/reason to aid
                # downstream auditing (does not imply EXCLUDED outcome).
                try:
                    pr = str(gate.get("pass_reason") or f"Gate {gate.get('gate_id')} passed with pass_outcome={pass_outcome_up}")
                    r.hard_stop = HardStop(rule_id=str(gate.get("gate_id") or "PASS_OUTCOME"), reason=pr, evidence=gr.evidence)
                except Exception:
                    pass
                return r
        except Exception:
            # If anything goes wrong here, continue with normal flow.
            pass

        required = bool(gate.get("required", True))
        if required and not gr.passed:
            fail_outcome = str(gate.get("fail_outcome", "UNABLE_TO_DETERMINE")).upper()
            allowed = set(contract.get("outcomes", {}).get("allowed", []))
            if fail_outcome not in allowed:
                fail_outcome = contract.get("outcomes", {}).get("defaults", {}).get(
                    "missing_required_data", "UNABLE_TO_DETERMINE"
                )
            r.outcome = Outcome(fail_outcome)
            return r

    r.outcome = Outcome.YES
    return r


def load_mapper() -> Dict[str, Any]:
    p = REPO_ROOT / "rules" / "mappers" / "epic_deaconess_mapper_v1.json"
    return json.loads(p.read_text(encoding="utf-8"))


def write_output(result: EventResult, out_path: Path, patient: Optional[PatientFacts] = None, event_rules: Optional[Dict[str, Any]] = None) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    def ev_to_dict(e: Evidence) -> Dict[str, Any]:
        return {
            "source_type": e.source_type.value,
            "timestamp": e.timestamp,
            "text": e.text,
            "pointers": e.pointer.ref,
        }

    payload: Dict[str, Any] = {
        "event_id": result.event_id,
        "canonical_name": result.canonical_name,
        "ntds_year": result.ntds_year,
        "outcome": result.outcome.value,
        "hard_stop": None,
        "gate_trace": [],
        # optional: near-miss evidence when a gate fails with NO/UNABLE
        "near_miss_evidence": [],
        # concise human-readable summary
        "summary": "",
        # what query patterns were searched for per evaluated gate
        "searched_for": [],
        "warnings": result.warnings,
    }

    if result.hard_stop:
        payload["hard_stop"] = {
            "rule_id": result.hard_stop.rule_id,
            "reason": result.hard_stop.reason,
            "evidence": [ev_to_dict(x) for x in result.hard_stop.evidence],
        }

    for g in result.gate_trace:
        payload["gate_trace"].append(
            {
                "gate": g.gate,
                "passed": g.passed,
                "reason": g.reason,
                "evidence": [ev_to_dict(x) for x in g.evidence],
            }
        )

    # Build `searched_for` array: one entry per evaluated gate
    try:
        searched: List[Dict[str, Any]] = []
        for g in result.gate_trace:
            entry: Dict[str, Any] = {"gate_id": g.gate}
            # Lookup gate definition to report the query keys and exclude keys used
            gate_def = None
            if event_rules:
                for gd in (event_rules.get("gates") or []):
                    if str(gd.get("gate_id")) == g.gate:
                        gate_def = gd
                        break

            qks = []
            eks = []
            if gate_def is not None:
                # Prefer an explicit list of query_keys when provided.
                if isinstance(gate_def.get("query_keys", None), list) and gate_def.get("query_keys"):
                    qks = gate_def.get("query_keys", []) or []
                else:
                    # Some gates (eg. timing_after_arrival) use a singular "query_key".
                    qk_single = gate_def.get("query_key", None)
                    if qk_single:
                        qks = [qk_single]

                eks = gate_def.get("exclude_noise_keys", []) or []

            entry["query_keys"] = list(qks)
            # Always include `exclude_keys` as a stable list for schema consistency
            entry["exclude_keys"] = list(eks)
            searched.append(entry)

        payload["searched_for"] = searched
    except Exception:
        payload["searched_for"] = []

    # If outcome is NO due to a required gate failing with a fail_outcome of NO,
    # gather up to 8 'near miss' evidence lines that matched the event's query keys
    # before any noise-filtering. This is for readability only and does not
    # affect pass/fail logic.
    try:
        # Compute summary first
        if result.outcome == Outcome.YES:
            payload["summary"] = "YES — all required gates passed"
        elif result.outcome == Outcome.EXCLUDED:
            if result.hard_stop:
                payload["summary"] = f"EXCLUDED — {result.hard_stop.rule_id}"
            else:
                payload["summary"] = "EXCLUDED"
        else:
            # NO or UNABLE_TO_DETERMINE: find first failed required gate (cause of termination)
            failed_gate_id = None
            for g in result.gate_trace:
                if not g.passed:
                    gate_def_tmp = None
                    for gd in (event_rules.get("gates") or []):
                        if str(gd.get("gate_id")) == g.gate:
                            gate_def_tmp = gd
                            break
                    if gate_def_tmp is None or bool(gate_def_tmp.get("required", True)):
                        failed_gate_id = g.gate
                        break

            if result.outcome == Outcome.NO:
                # Custom wording for failed DVT diagnosis gate
                if failed_gate_id == "dvt_dx":
                    payload["summary"] = "NO — DVT not documented during hospitalization"
                else:
                    payload["summary"] = f"NO — failed gate: {failed_gate_id or 'unknown'}"
            elif result.outcome == Outcome.UNABLE_TO_DETERMINE:
                payload["summary"] = f"UNABLE — failed gate: {failed_gate_id or 'unknown'}"

        if result.outcome.value in (Outcome.NO.value, Outcome.UNABLE_TO_DETERMINE.value) and patient and event_rules:
            # find the first failed gate in trace that is REQUIRED (this is the gate
            # that caused termination). If none marked required, fall back to the
            # first failed gate.
            failed_gate_id = None
            for g in result.gate_trace:
                if not g.passed:
                    # locate gate definition to check 'required'
                    gate_def_tmp = None
                    for gd in (event_rules.get("gates") or []):
                        if str(gd.get("gate_id")) == g.gate:
                            gate_def_tmp = gd
                            break
                    if gate_def_tmp is None or bool(gate_def_tmp.get("required", True)):
                        failed_gate_id = g.gate
                        break

            if failed_gate_id:
                # find gate definition
                gate_def = None
                for gd in (event_rules.get("gates") or []):
                    if str(gd.get("gate_id")) == failed_gate_id:
                        gate_def = gd
                        break

                if gate_def:
                    qks = gate_def.get("query_keys", []) or []
                    noise_keys = gate_def.get("exclude_noise_keys", []) or []
                    # Prefer prophylaxis/noise lines first (they're often the most
                    # clinically suggestive near-miss indicators), then other query keys.
                    gather_keys: List[str] = []
                    for k in noise_keys:
                        ks = str(k)
                        if ks not in gather_keys:
                            gather_keys.append(ks)
                    for k in qks:
                        ks = str(k)
                        if ks not in gather_keys:
                            gather_keys.append(ks)

                    seen = set()
                    near: List[Dict[str, Any]] = []
                    # Only include evidence lines that match this gate's own
                    # query keys or its exclude_noise_keys. Scan all patient
                    # evidence and test per-key patterns to ensure same-line
                    # relevance (avoid unrelated prophylaxis lines).
                    for qk in gather_keys:
                        for evi in patient.evidence:
                            txt = evi.text or ""
                            if not line_matches_any(patient, txt, str(qk)):
                                continue
                            ref = json.dumps(evi.pointer.ref, sort_keys=True)
                            if ref in seen:
                                continue
                            seen.add(ref)
                            near.append(ev_to_dict(evi))
                            if len(near) >= 8:
                                break
                        if len(near) >= 8:
                            break

                    payload["near_miss_evidence"] = near
    except Exception:
        # Never break output generation for near-miss collection
        payload["near_miss_evidence"] = []

    # PE-specific summary override: if this is the PE event and the final
    # outcome is NO, but there is imaging explicitly negative for PE, prefer
    # a clearer summary indicating imaging is negative.
    try:
        if result.event_id == 14 and result.outcome == Outcome.NO and patient:
            neg_hits = match_evidence(patient, "pe_dx_negative", allowed_sources=["IMAGING"], max_hits=1)
            if neg_hits:
                payload["summary"] = "NO — Imaging negative for pulmonary embolism"
    except Exception:
        pass

    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True, choices=[2025, 2026])
    ap.add_argument("--event", type=int, required=True)
    ap.add_argument("--patient", required=True, help="Path to Epic TXT export")
    ap.add_argument("--arrival", default=None, help="Optional arrival_time override (ISO preferred)")
    args = ap.parse_args()

    # Validate that a rules file exists for the requested year/event to avoid
    # silent failures later when loading. This keeps the CLI flexible while
    # providing a clear error for unknown event IDs.
    rules_dir = REPO_ROOT / "rules" / "ntds" / "logic" / str(args.year)
    pattern = f"{int(args.event):02d}_*.json"
    matches = list(rules_dir.glob(pattern)) if rules_dir.exists() else []
    if not matches:
        raise SystemExit(f"Unknown NTDS event_id {args.event} for year {args.year}.")

    rs = load_ruleset(args.year, args.event)
    contract = rs.contract
    event_rules = rs.event

    mapper = load_mapper()
    qp = mapper.get("query_patterns", {})

    p = Path(args.patient)
    patient = build_patientfacts(p, qp, arrival_time=args.arrival)

    result = evaluate_event(event_rules, contract, patient)

    print(f"\nNTDS EVENT RESULT — {result.ntds_year} — {result.event_id} {result.canonical_name}")
    print("Outcome:", result.outcome.value)

    out_path = REPO_ROOT / "outputs" / "ntds" / p.stem / f"ntds_event_{args.event:02d}_{args.year}_v1.json"
    write_output(result, out_path, patient=patient, event_rules=event_rules)
    print("Wrote:", out_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
