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
    LDAEpisode,
    LDA_CONFIDENCE_LEVELS,
    Outcome,
    PatientFacts,
    SourceType,
)
from cerebralos.ntds_logic.rules_loader import load_ruleset
from cerebralos.ntds_logic.build_patientfacts_from_txt import build_patientfacts

REPO_ROOT = Path(__file__).resolve().parents[2]

# ── Feature flag: LDA device-duration gates ────────────────────────
# When False (default), all lda_* gate types no-op to False so existing
# text-pattern gates remain the sole decision path.  Set to True in
# targeted tests or after cohort validation to activate LDA gates.
ENABLE_LDA_GATES: bool = False


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


# ---------------------------------------------------------------------------
# Proximity helpers — sentence-level co-occurrence for exclusion gates
# ---------------------------------------------------------------------------

def _split_sentences(text: str) -> List[str]:
    """Split *text* into sentence-like segments for proximity matching.

    Deterministic heuristic:
      1. Split on newlines.
      2. Within each line, split on sentence-ending punctuation (``.``, ``!``,
         ``?``) followed by whitespace and an uppercase letter.
    Returns at least ``[text]`` when *text* is non-empty so callers always
    get a non-empty list.
    """
    if not text or not text.strip():
        return []
    segments: List[str] = []
    for chunk in text.split("\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = re.split(r"(?<=[.!?])\s+(?=[A-Z])", chunk)
        segments.extend(p.strip() for p in parts if p.strip())
    return segments if segments else [text]


def _sentence_window_matches(
    patient: PatientFacts,
    text: str,
    query_key: str,
    context_keys: List[str],
) -> bool:
    """Return True when *query_key* and any *context_key* co-occur within ±1
    sentence of each other inside *text*.

    Fail-closed: if *text* is empty or produces no sentences, returns False
    (exclusion will not fire).
    """
    sentences = _split_sentences(text)
    if not sentences:
        return False

    qk_patterns = _patterns_for_key(patient, query_key)
    if not qk_patterns:
        return False

    for i, sent in enumerate(sentences):
        if not any(p.search(sent) for p in qk_patterns):
            continue
        # query_key matched sentence *i* — check ±1 window for context_key
        window = sentences[max(0, i - 1) : min(len(sentences), i + 2)]
        for ctx_key in context_keys:
            ctx_patterns = _patterns_for_key(patient, str(ctx_key))
            if not ctx_patterns:
                continue
            if any(p.search(s) for s in window for p in ctx_patterns):
                return True

    return False


def eval_exclude_if_any(gate: Dict[str, Any], patient: PatientFacts, contract: Dict[str, Any]) -> Optional[HardStop]:
    """
    Hard-stop exclusion.

    Supports:
      - query_keys: patterns that indicate the exclusion condition
      - require_context_keys: patterns that MUST ALSO match the same line
        (prevents false positives like POA=Power of Attorney)
      - proximity_mode: optional refinement for require_context_keys matching
            "sentence_window" — query_key and context_key must co-occur
            within the same sentence or ±1 adjacent sentences.
            Absent / unknown values fall back to whole-line matching.
    """
    query_keys = gate.get("query_keys", [])
    if not isinstance(query_keys, list):
        query_keys = []

    require_context_keys = gate.get("require_context_keys", [])
    if require_context_keys is None:
        require_context_keys = []
    if not isinstance(require_context_keys, list):
        require_context_keys = []

    proximity_mode = gate.get("proximity_mode")

    max_items = int(contract.get("evidence", {}).get("max_items_per_gate", 8))

    # For each query_key, collect matching evidence lines.
    # If require_context_keys is present, keep only lines that ALSO match ANY context key.
    # When proximity_mode == "sentence_window", co-occurrence is checked within ±1 sentence.
    for qk in query_keys:
        hits = match_evidence(patient, str(qk), allowed_sources=None, max_hits=50)
        if not hits:
            continue

        filtered: List[Evidence] = []
        if require_context_keys:
            if proximity_mode == "sentence_window":
                for e in hits:
                    if _sentence_window_matches(patient, e.text or "", str(qk), require_context_keys):
                        filtered.append(e)
            else:
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

    # ── exclude_noise_keys enforcement ──────────────────────────────
    # If the gate declares exclude_noise_keys, remove any hit whose text
    # matches ANY of those noise patterns.  This prevents historical /
    # prophylaxis / rule-out language from satisfying a positive-dx gate.
    exclude_keys = gate.get("exclude_noise_keys", []) or []
    if exclude_keys and hits:
        filtered: List[Evidence] = []
        for h in hits:
            txt = h.text or ""
            if any(line_matches_any(patient, txt, str(ek)) for ek in exclude_keys):
                continue  # noise match → drop this hit
            filtered.append(h)
        hits = filtered
    # ────────────────────────────────────────────────────────────────

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


# ── LDA gate evaluation functions ──────────────────────────────────

def _get_lda_episodes(patient: PatientFacts) -> List[Dict[str, Any]]:
    """Extract LDA episodes from patient facts (lda_episodes_v1 key)."""
    facts = patient.facts or {}
    lda_data = facts.get("lda_episodes_v1") or {}
    episodes = lda_data.get("episodes", [])
    if not isinstance(episodes, list):
        return []
    return episodes


def _confidence_meets_min(actual: str, minimum: str) -> bool:
    """Return True if *actual* confidence >= *minimum* in the tier order."""
    try:
        actual_idx = LDA_CONFIDENCE_LEVELS.index(actual)
        min_idx = LDA_CONFIDENCE_LEVELS.index(minimum)
        return actual_idx >= min_idx
    except ValueError:
        return False


def eval_lda_duration(gate: Dict[str, Any], patient: PatientFacts, contract: Dict[str, Any]) -> GateResult:
    """Evaluate whether any LDA episode of the required device_type meets
    a minimum duration threshold.

    Gate parameters:
        device_type: canonical device type string
        days_gte: minimum episode_days (>=)
        min_confidence: minimum source_confidence tier
        outcome_if_missing: EXCLUDED | NO | UNKNOWN (when no LDA data at all)
    """
    gate_id = str(gate.get("gate_id", "lda_duration"))

    if not ENABLE_LDA_GATES:
        return GateResult(gate=gate_id, passed=False,
                          reason="LDA gates disabled (ENABLE_LDA_GATES=False).", evidence=[])

    device_type = str(gate.get("device_type", "")).upper()
    days_gte = int(gate.get("days_gte", 2))
    min_confidence = str(gate.get("min_confidence", "TEXT_APPROXIMATE")).upper()

    episodes = _get_lda_episodes(patient)
    if not episodes:
        outcome_if_missing = str(gate.get("outcome_if_missing", "NO")).upper()
        reason = f"No LDA episodes available (outcome_if_missing={outcome_if_missing})."
        return GateResult(gate=gate_id, passed=False, reason=reason, evidence=[])

    for ep in episodes:
        if not isinstance(ep, dict):
            continue
        if str(ep.get("device_type", "")).upper() != device_type:
            continue
        conf = str(ep.get("source_confidence", "TEXT_APPROXIMATE")).upper()
        if not _confidence_meets_min(conf, min_confidence):
            continue
        ep_days = ep.get("episode_days")
        if ep_days is not None and int(ep_days) >= days_gte:
            return GateResult(gate=gate_id, passed=True,
                              reason=f"LDA episode {device_type} duration {ep_days}d >= {days_gte}d.",
                              evidence=[])

    return GateResult(gate=gate_id, passed=False,
                      reason=f"No {device_type} episode meets duration >= {days_gte}d.",
                      evidence=[])


def eval_lda_present_at(gate: Dict[str, Any], patient: PatientFacts, contract: Dict[str, Any]) -> GateResult:
    """Evaluate whether a device was active on the event date.

    Gate parameters:
        device_type: canonical device type
        reference: currently only "event_date" is supported
        min_confidence: minimum confidence tier
    """
    gate_id = str(gate.get("gate_id", "lda_present_at"))

    if not ENABLE_LDA_GATES:
        return GateResult(gate=gate_id, passed=False,
                          reason="LDA gates disabled (ENABLE_LDA_GATES=False).", evidence=[])

    device_type = str(gate.get("device_type", "")).upper()
    min_confidence = str(gate.get("min_confidence", "TEXT_APPROXIMATE")).upper()

    episodes = _get_lda_episodes(patient)
    for ep in episodes:
        if not isinstance(ep, dict):
            continue
        if str(ep.get("device_type", "")).upper() != device_type:
            continue
        conf = str(ep.get("source_confidence", "TEXT_APPROXIMATE")).upper()
        if not _confidence_meets_min(conf, min_confidence):
            continue
        # If the episode has a start_ts, it was present at some point
        if ep.get("start_ts"):
            return GateResult(gate=gate_id, passed=True,
                              reason=f"LDA {device_type} episode present.",
                              evidence=[])

    return GateResult(gate=gate_id, passed=False,
                      reason=f"No active {device_type} episode found.",
                      evidence=[])


def eval_lda_overlap(gate: Dict[str, Any], patient: PatientFacts, contract: Dict[str, Any]) -> GateResult:
    """Evaluate whether a device episode overlaps with a reference window.

    Gate parameters:
        device_type: canonical device type
        reference: "event_date" — uses patient.facts["event_date"] as the
            centre, extending ±window_days.  Or "admission" — uses
            arrival_time as window start.
        window_days: days of overlap required (default 0 = any overlap)
        min_confidence: minimum source_confidence tier
    """
    gate_id = str(gate.get("gate_id", "lda_overlap"))

    if not ENABLE_LDA_GATES:
        return GateResult(gate=gate_id, passed=False,
                          reason="LDA gates disabled (ENABLE_LDA_GATES=False).", evidence=[])

    device_type = str(gate.get("device_type", "")).upper()
    min_confidence = str(gate.get("min_confidence", "TEXT_APPROXIMATE")).upper()
    window_days = int(gate.get("window_days", 0))
    reference = str(gate.get("reference", "event_date")).lower()

    # ── Determine reference window ──────────────────────────────────
    facts = patient.facts or {}
    ref_ts_str: Optional[str] = None
    if reference == "event_date":
        ref_ts_str = str(facts.get("event_date") or facts.get("arrival_time") or "")
    elif reference == "admission":
        ref_ts_str = str(facts.get("arrival_time") or "")
    else:
        ref_ts_str = str(facts.get(reference) or "")

    ref_dt = parse_ts(ref_ts_str) if ref_ts_str else None
    if ref_dt is None:
        return GateResult(gate=gate_id, passed=False,
                          reason=f"No reference timestamp for overlap check (reference={reference}).",
                          evidence=[])

    from datetime import timedelta

    # ── Build reference window ──────────────────────────────────────
    # "admission" → one-sided: [arrival, arrival + window_days].
    #   The device must overlap with the period *after* arrival.
    # "event_date" → symmetric: [ref − window_days, ref + window_days].
    if reference == "admission":
        window_start = ref_dt
        window_end = ref_dt + timedelta(days=window_days) if window_days else ref_dt
    else:
        window_start = ref_dt - timedelta(days=window_days) if window_days else ref_dt
        window_end = ref_dt + timedelta(days=window_days) if window_days else ref_dt

    # ── Check episodes for overlap ──────────────────────────────────
    episodes = _get_lda_episodes(patient)
    for ep in episodes:
        if not isinstance(ep, dict):
            continue
        if str(ep.get("device_type", "")).upper() != device_type:
            continue
        conf = str(ep.get("source_confidence", "TEXT_APPROXIMATE")).upper()
        if not _confidence_meets_min(conf, min_confidence):
            continue

        ep_start = parse_ts(ep.get("start_ts"))
        ep_stop = parse_ts(ep.get("stop_ts"))

        # If episode has no timestamps at all, skip it for overlap
        if ep_start is None and ep_stop is None:
            continue

        # ── Normalize timezone-awareness: fail-closed ───────────────
        # If one side is tz-aware and the other naive, strip tzinfo
        # so comparison proceeds deterministically rather than raising.
        def _strip_tz(dt):
            return dt.replace(tzinfo=None) if dt and dt.tzinfo else dt

        if ((ep_start and ep_start.tzinfo) or (ep_stop and ep_stop.tzinfo)) != \
           (window_start.tzinfo is not None):
            ep_start = _strip_tz(ep_start)
            ep_stop = _strip_tz(ep_stop)
            window_start = _strip_tz(window_start)
            window_end = _strip_tz(window_end)

        # Build effective episode interval
        # If only start_ts: treat device as still active (open-ended)
        # If only stop_ts: treat device as started at beginning of time
        effective_start = ep_start if ep_start else window_start
        effective_stop = ep_stop if ep_stop else window_end

        # Check interval overlap: [effective_start, effective_stop] ∩ [window_start, window_end]
        if effective_start <= window_end and effective_stop >= window_start:
            return GateResult(gate=gate_id, passed=True,
                              reason=f"LDA {device_type} episode overlaps reference window.",
                              evidence=[])

    return GateResult(gate=gate_id, passed=False,
                      reason=f"No {device_type} episode overlaps the reference window.",
                      evidence=[])


def eval_lda_device_day_count(gate: Dict[str, Any], patient: PatientFacts, contract: Dict[str, Any]) -> GateResult:
    """Evaluate total device-day count for a device type.

    Gate parameters:
        device_type: canonical device type
        count_gte: minimum device-day count
    """
    gate_id = str(gate.get("gate_id", "lda_device_day_count"))

    if not ENABLE_LDA_GATES:
        return GateResult(gate=gate_id, passed=False,
                          reason="LDA gates disabled (ENABLE_LDA_GATES=False).", evidence=[])

    device_type = str(gate.get("device_type", "")).upper()
    count_gte = int(gate.get("count_gte", 1))

    facts = patient.facts or {}
    lda_data = facts.get("lda_episodes_v1") or {}
    counts = lda_data.get("device_day_counts", {})
    actual = int(counts.get(device_type, 0))

    passed = actual >= count_gte
    reason = (f"Device-day count {device_type}: {actual} >= {count_gte}."
              if passed else
              f"Device-day count {device_type}: {actual} < {count_gte}.")
    return GateResult(gate=gate_id, passed=passed, reason=reason, evidence=[])


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
        elif gt == "lda_duration":
            gr = eval_lda_duration(gate, patient, contract)
        elif gt == "lda_present_at":
            gr = eval_lda_present_at(gate, patient, contract)
        elif gt == "lda_overlap":
            gr = eval_lda_overlap(gate, patient, contract)
        elif gt == "lda_device_day_count":
            gr = eval_lda_device_day_count(gate, patient, contract)
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
