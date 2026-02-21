#!/usr/bin/env python3
"""
GREEN CARD v1 – H&P-centric field extractor (spec items 1–6).

Extracts:
  1. Primary Survey  (Airway, Breathing, Circulation, Disability/GCS/Pupils, Exposure, FAST)
  2. Admitting MD    (signer / cosigner from chosen TRAUMA_HP)
  3. Anticoag Status (YES/NO/UNKNOWN + hold/resume tracking)
  4. ETOH level      (from labs or raw text)
  5. UDS panel       (per-component positive/negative)
  6. Base Deficit    (value + category-I warning)
  7. INR             (value + range)
  8. Impression/Plan drift timeline

Design:
- Deterministic regex, fail-closed. No LLM, no ML, no inference.
- H&P-first, source-priority: TRAUMA_HP > ED > PROGRESS > CONSULT/OP > IMAGING > DISCHARGE
- Discharge is "landmine": never overwrite H&P-derived truths.
- Every extracted value carries evidence trail.

Usage (called by extract_green_card_v1):
    from cerebralos.green_card.extract_green_card_hp_v1 import extract_hp_fields
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime as _dt
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── paths ───────────────────────────────────────────────────────────
_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent.parent
_HP_RULES_PATH = (
    _REPO_ROOT / "rules" / "green_card" / "green_card_hp_patterns_v1.json"
)

# ── doc-type priority (mirrors extract_green_card_v1) ───────────────
_DEFAULT_PRIORITY = {
    "trauma_hp": 1,
    "ed_note": 2,
    "trauma_progress": 3,
    "consult_note": 4,
    "op_note": 4,
    "imaging": 5,
    "other": 8,
    "discharge_summary": 9,
}


# ── helpers ─────────────────────────────────────────────────────────

def _load_hp_config() -> Dict[str, Any]:
    if not _HP_RULES_PATH.is_file():
        print(
            f"FATAL: HP patterns not found: {_HP_RULES_PATH}",
            file=sys.stderr,
        )
        sys.exit(1)
    with open(_HP_RULES_PATH, encoding="utf-8") as f:
        return json.load(f)


def _get_priority(doc_type: str) -> int:
    return _DEFAULT_PRIORITY.get(doc_type, 8)


def _line_preview(text: str, match: re.Match, context: int = 60) -> str:
    start = max(0, match.start() - context)
    end = min(len(text), match.end() + context)
    return text[start:end].replace("\n", " ").strip()[:250]


def _make_source(doc_type: str, priority: int, item_idx: int,
                 line_id: str, preview: str) -> Dict[str, Any]:
    return {
        "source_type": doc_type.upper(),
        "priority": priority,
        "item_id": item_idx,
        "source_line_id": line_id,
        "preview": preview[:200],
    }


def _try_iso(item: Dict[str, Any]) -> Optional[str]:
    dt = item.get("datetime") or item.get("ts") or item.get("date")
    if dt and isinstance(dt, str):
        return dt
    return None


def _search_any(patterns: List[str], text: str) -> Optional[re.Match]:
    for pat_str in patterns:
        try:
            m = re.search(pat_str, text)
            if m:
                return m
        except re.error:
            continue
    return None


def _search_all(patterns: List[str], text: str) -> List[re.Match]:
    results = []
    for pat_str in patterns:
        try:
            m = re.search(pat_str, text)
            if m:
                results.append(m)
        except re.error:
            continue
    return results


# ═════════════════════════════════════════════════════════════════════
#  1. PRIMARY SURVEY
# ═════════════════════════════════════════════════════════════════════

def _extract_primary_survey(
    hp_text: str,
    cfg: Dict[str, Any],
    item_idx: int,
    line_id: str,
) -> Dict[str, Any]:
    """Extract Primary Survey block from the chosen TRAUMA_HP text.

    Returns dict with keys: airway, breathing, circulation, disability,
    exposure, gcs, pupils, fast_performed, fast_result, sources, warnings.
    """
    ps_cfg = cfg.get("primary_survey", {})
    result: Dict[str, Any] = {
        "airway": None,
        "breathing": None,
        "circulation": None,
        "disability": None,
        "exposure": None,
        "gcs": None,
        "gcs_intubated": False,
        "pupils": None,
        "fast_performed": "UNKNOWN",
        "fast_result": "UNKNOWN",
        "raw_block": None,
        "sources": [],
        "warnings": [],
    }

    # ── Find Primary Survey section ──────────────────────────────
    header_pats = ps_cfg.get("header_patterns", [])
    stop_pats = ps_cfg.get("stop_patterns", [])
    lines = hp_text.split("\n")

    start_idx: Optional[int] = None
    for i, line in enumerate(lines):
        for pat_str in header_pats:
            try:
                if re.search(pat_str, line):
                    start_idx = i
                    break
            except re.error:
                continue
        if start_idx is not None:
            break

    if start_idx is None:
        result["warnings"].append("primary_survey_section_not_found")
        return result

    # Collect body lines until stop pattern or 50 lines
    body_lines: List[str] = []
    stop_res = []
    for sp in stop_pats:
        try:
            stop_res.append(re.compile(sp))
        except re.error:
            continue

    for j in range(start_idx + 1, min(start_idx + 51, len(lines))):
        ln = lines[j]
        hit_stop = False
        for sre in stop_res:
            if sre.search(ln):
                hit_stop = True
                break
        if hit_stop and body_lines:
            break
        body_lines.append(ln)

    block_text = "\n".join(body_lines).strip()
    if not block_text:
        result["warnings"].append("primary_survey_section_empty")
        return result

    result["raw_block"] = block_text
    result["sources"].append(
        _make_source("trauma_hp", 1, item_idx, line_id,
                     block_text[:200])
    )

    # ── Extract ABCDE (line-by-line for multiline blocks) ──────
    abcde = ps_cfg.get("abcde_patterns", {})
    for field_key, pat_str in abcde.items():
        try:
            pat_re = re.compile(pat_str)
            for bline in body_lines:
                m = pat_re.search(bline)
                if m:
                    result[field_key] = m.group("val").strip()
                    break
        except (re.error, IndexError):
            continue

    # ── Extract GCS (line-by-line for multiline blocks) ────────────
    gcs_pats = ps_cfg.get("gcs_patterns", [])
    # Search in disability line first, then full block
    gcs_search_texts = []
    if result.get("disability"):
        gcs_search_texts.append(result["disability"])
    gcs_search_texts.extend(body_lines)

    for search_text in gcs_search_texts:
        if result["gcs"] is not None:
            break
        for pat_str in gcs_pats:
            try:
                m = re.search(pat_str, search_text)
                if m:
                    gcs_val = m.group("gcs")
                    try:
                        gcs_int = int(gcs_val)
                        if 3 <= gcs_int <= 15:
                            result["gcs"] = gcs_int
                            # Check for intubated "T" suffix
                            try:
                                if m.group("intubated"):
                                    result["gcs_intubated"] = True
                            except IndexError:
                                pass
                            break
                    except (ValueError, TypeError):
                        continue
            except re.error:
                continue

    # ── Extract Pupils (line-by-line) ───────────────────────────
    pupils_pats = ps_cfg.get("pupils_patterns", [])
    pupils_search_texts = []
    if result.get("disability"):
        pupils_search_texts.append(result["disability"])
    pupils_search_texts.extend(body_lines)

    for search_text in pupils_search_texts:
        if result["pupils"] is not None:
            break
        for pat_str in pupils_pats:
            try:
                m = re.search(pat_str, search_text)
                if m:
                    try:
                        result["pupils"] = m.group("val").strip()
                    except IndexError:
                        result["pupils"] = m.group(0).strip()
                    break
            except re.error:
                continue

    # ── Extract FAST (line-by-line) ──────────────────────────────
    fast_line_pat = ps_cfg.get("fast_line_pattern")
    if fast_line_pat:
        try:
            fast_m = None
            fast_re = re.compile(fast_line_pat)
            for bline in body_lines:
                fast_m = fast_re.search(bline)
                if fast_m:
                    break
            if fast_m:
                fast_val = fast_m.group("val").strip()

                # Check performed
                performed_no = ps_cfg.get("fast_performed_no_patterns", [])
                performed_yes = ps_cfg.get("fast_performed_yes_patterns", [])
                positive_pats = ps_cfg.get("fast_positive_patterns", [])
                negative_pats = ps_cfg.get("fast_negative_patterns", [])

                # Check "not performed" first
                if _search_any(performed_no, fast_val):
                    result["fast_performed"] = "NO"
                    result["fast_result"] = "N/A"
                elif _search_any(performed_yes, fast_val):
                    result["fast_performed"] = "YES"
                    if _search_any(positive_pats, fast_val):
                        result["fast_result"] = "POSITIVE"
                    elif _search_any(negative_pats, fast_val):
                        result["fast_result"] = "NEGATIVE"
                    else:
                        result["fast_result"] = "UNKNOWN"
                else:
                    # Bare text — try to infer
                    if fast_val.strip():
                        result["fast_performed"] = "YES"
                        if _search_any(positive_pats, fast_val):
                            result["fast_result"] = "POSITIVE"
                        elif _search_any(negative_pats, fast_val):
                            result["fast_result"] = "NEGATIVE"
                        else:
                            result["fast_result"] = "UNKNOWN"
        except re.error:
            pass

    return result


# ═════════════════════════════════════════════════════════════════════
#  2. ADMITTING MD
# ═════════════════════════════════════════════════════════════════════

def _extract_admitting_md(
    hp_texts: List[Tuple[str, int, str]],
    cfg: Dict[str, Any],
) -> Dict[str, Any]:
    """Extract signing/cosigning physician from ALL TRAUMA_HP items.

    Searches every TRAUMA_HP item for cosigner/signer/author, picks best
    by role_priority (COSIGNER > SIGNER > CONFIRMING_MD > AUTHOR).

    Args:
        hp_texts: List of (text, item_idx, line_id) for each TRAUMA_HP item.
        cfg: Loaded HP config.

    Returns dict with: name, credential, role, sources, warnings.
    """
    md_cfg = cfg.get("admitting_md", {})
    result: Dict[str, Any] = {
        "name": None,
        "credential": None,
        "role": "UNKNOWN",
        "sources": [],
        "warnings": [],
    }

    signer_pats = md_cfg.get("signer_patterns", [])
    role_priority = md_cfg.get("role_priority", ["COSIGNER", "SIGNER", "AUTHOR", "UNKNOWN"])

    best_match: Optional[Dict[str, Any]] = None
    best_role_idx = len(role_priority)
    best_src_item_idx = -1
    best_src_line_id = ""

    for hp_text, item_idx, line_id in hp_texts:
        for spec in signer_pats:
            role = spec.get("role", "UNKNOWN")
            pat_str = spec.get("pattern", "")
            try:
                m = re.search(pat_str, hp_text)
                if m:
                    name_raw = m.group("name").strip()
                    # Try to get credential from named group first
                    credential = None
                    try:
                        credential = m.group("cred")
                    except IndexError:
                        pass
                    # Fallback: parse credential from name string
                    name_clean = name_raw
                    if not credential:
                        cred_match = re.search(
                            r",\s*(MD|DO|PA(?:-C)?|NP|APRN|AGACNP|ACNP|FNP|DNP)\s*$",
                            name_raw,
                        )
                        if cred_match:
                            credential = cred_match.group(1)
                            name_clean = name_raw[:cred_match.start()].strip().rstrip(",")
                    else:
                        # Remove credential from name if it leaked in
                        cred_match = re.search(
                            r",?\s*(?:MD|DO|PA(?:-C)?|NP|APRN|AGACNP|ACNP|FNP|DNP)\s*$",
                            name_raw,
                        )
                        if cred_match:
                            name_clean = name_raw[:cred_match.start()].strip().rstrip(",")

                    role_idx = role_priority.index(role) if role in role_priority else len(role_priority) - 1

                    if role_idx < best_role_idx:
                        best_role_idx = role_idx
                        best_match = {
                            "name": name_clean,
                            "credential": credential,
                            "role": role,
                            "preview": _line_preview(hp_text, m, context=40),
                        }
                        best_src_item_idx = item_idx
                        best_src_line_id = line_id
            except (re.error, IndexError):
                continue

    if best_match:
        result["name"] = best_match["name"]
        result["credential"] = best_match["credential"]
        result["role"] = best_match["role"]
        result["sources"].append(
            _make_source("trauma_hp", 1, best_src_item_idx, best_src_line_id,
                         best_match["preview"])
        )
    else:
        # Try bottom-of-note MD / top author fallbacks on each HP text
        for hp_text, item_idx, line_id in hp_texts:
            bottom_pat = md_cfg.get("bottom_md_pattern")
            if bottom_pat:
                try:
                    # Use finditer and take LAST match (closest to end of note)
                    matches = list(re.finditer(bottom_pat, hp_text))
                    if matches:
                        m = matches[-1]
                        result["name"] = m.group("name").strip()
                        result["credential"] = m.group("cred").strip()
                        result["role"] = "CONFIRMING_MD"
                        result["sources"].append(
                            _make_source("trauma_hp", 1, item_idx, line_id,
                                         m.group(0).strip()[:200])
                        )
                        break
                except (re.error, IndexError):
                    pass

        # Try top author (e.g. "Trauma H & P\nRachel N Bertram, NP")
        if result["name"] is None:
            for hp_text, item_idx, line_id in hp_texts:
                top_pat = md_cfg.get("top_author_pattern")
                if top_pat:
                    try:
                        m = re.search(top_pat, hp_text)
                        if m:
                            result["name"] = m.group("name").strip()
                            result["credential"] = m.group("cred").strip()
                            result["role"] = "AUTHOR"
                            result["sources"].append(
                                _make_source("trauma_hp", 1, item_idx, line_id,
                                             m.group(0).strip()[:200])
                            )
                            break
                    except (re.error, IndexError):
                        pass

        if result["name"] is None:
            result["warnings"].append("admitting_md_not_found_in_hp")

    return result


# ═════════════════════════════════════════════════════════════════════
#  3. ANTICOAG STATUS
# ═════════════════════════════════════════════════════════════════════

def _extract_anticoag_status(
    classified_items: List[Tuple[Dict, str, int]],
    cfg: Dict[str, Any],
    existing_anticoag_list: Optional[List[str]],
) -> Dict[str, Any]:
    """Determine anticoagulation status: YES / NO / UNKNOWN.

    Uses the existing home_anticoagulants list from the main extractor,
    plus explicit yes/no phrases from H&P text, plus hold/resume tracking.

    Returns dict with: status, agents, hold_resume_events, sources, warnings.
    """
    ac_cfg = cfg.get("anticoag_status", {})
    result: Dict[str, Any] = {
        "status": "UNKNOWN",
        "agents": [],
        "hold_resume_events": [],
        "sources": [],
        "warnings": [],
    }

    # If existing extraction already found anticoagulants
    if existing_anticoag_list:
        real_agents = [
            a for a in existing_anticoag_list
            if "unknown" not in a.lower() and "none identified" not in a.lower()
        ]
        if real_agents:
            result["status"] = "YES"
            result["agents"] = real_agents

    explicit_yes_pats = ac_cfg.get("explicit_yes_phrases", [])
    explicit_no_pats = ac_cfg.get("explicit_no_phrases", [])
    hold_resume_pats = ac_cfg.get("hold_resume_patterns", [])

    # Scan items in priority order (classified is pre-sorted)
    for item, doc_type, prio in classified_items:
        text = item.get("text", "") or ""
        item_idx = item.get("idx", -1)
        line_id = f"L{item.get('line_start', 0)}-L{item.get('line_end', 0)}"
        is_discharge = doc_type == "discharge_summary"

        # Skip discharge for status determination (landmine rule)
        if is_discharge:
            continue

        # Explicit NO phrase overrides unknown
        if result["status"] == "UNKNOWN":
            m = _search_any(explicit_no_pats, text[:3000])
            if m:
                result["status"] = "NO"
                result["sources"].append(
                    _make_source(doc_type, prio, item_idx, line_id,
                                 _line_preview(text, m))
                )

        # Explicit YES phrase
        if result["status"] in ("UNKNOWN", "NO"):
            m = _search_any(explicit_yes_pats, text[:3000])
            if m:
                result["status"] = "YES"
                result["sources"].append(
                    _make_source(doc_type, prio, item_idx, line_id,
                                 _line_preview(text, m))
                )

        # Hold/resume events (any doc type)
        for pat_str in hold_resume_pats:
            try:
                for m in re.finditer(pat_str, text):
                    agent = m.group("agent").strip().lower()
                    event_text = m.group(0).strip()

                    action = "UNKNOWN"
                    if re.search(r"(?i)\b(?:hold|held|stop|stopped|discontinue|dc|d/c)\b", event_text):
                        action = "HOLD"
                    elif re.search(r"(?i)\b(?:resume|restart|restarted|resumed)\b", event_text):
                        action = "RESUME"

                    result["hold_resume_events"].append({
                        "agent": agent,
                        "action": action,
                        "text": event_text[:200],
                        "doc_type": doc_type,
                        "item_idx": item_idx,
                    })
                    # If we find an agent mentioned in hold/resume, status is YES
                    if result["status"] == "UNKNOWN":
                        result["status"] = "YES"
                    if agent not in [a.lower() for a in result["agents"]]:
                        result["agents"].append(agent)
            except (re.error, IndexError):
                continue

    return result


# ═════════════════════════════════════════════════════════════════════
#  4. ETOH (Alcohol Level)
# ═════════════════════════════════════════════════════════════════════

def _extract_etoh(
    classified_items: List[Tuple[Dict, str, int]],
    cfg: Dict[str, Any],
    features_data: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Extract alcohol level from labs (features JSON) or raw text.

    Returns dict with: value, units, date, source_method, sources, warnings.
    """
    etoh_cfg = cfg.get("etoh", {})
    result: Dict[str, Any] = {
        "value": None,
        "value_numeric": None,
        "units": None,
        "date": None,
        "source_method": None,
        "sources": [],
        "warnings": [],
    }

    # ── Try features data first (structured labs) ─────────────
    component_names = [n.lower() for n in etoh_cfg.get("lab_component_names", [])]
    if features_data:
        labs_latest = features_data.get("labs", {}).get("latest", [])
        for lab in labs_latest:
            comp = (lab.get("component") or "").lower()
            if any(cn in comp for cn in component_names):
                result["value"] = lab.get("value_raw")
                result["value_numeric"] = lab.get("value_num")
                result["units"] = lab.get("unit")
                result["date"] = lab.get("observed_dt")
                result["source_method"] = "features_json"
                result["sources"].append({
                    "source_type": "FEATURES_JSON",
                    "priority": 0,
                    "item_id": None,
                    "source_line_id": "labs.latest",
                    "preview": f"{lab.get('component')}: {lab.get('value_raw')} {lab.get('unit', '')}",
                })
                return result

    # ── Fallback: raw text scan ───────────────────────────────
    text_pats = etoh_cfg.get("text_patterns", [])
    for item, doc_type, prio in classified_items:
        text = item.get("text", "") or ""
        item_idx = item.get("idx", -1)
        line_id = f"L{item.get('line_start', 0)}-L{item.get('line_end', 0)}"

        for pat_str in text_pats:
            try:
                m = re.search(pat_str, text)
                if m:
                    val_raw = m.group("val").strip()
                    # Parse numeric
                    val_num = None
                    clean = re.sub(r"[<>\s]", "", val_raw)
                    try:
                        val_num = float(clean)
                    except ValueError:
                        pass

                    result["value"] = val_raw
                    result["value_numeric"] = val_num
                    try:
                        result["units"] = m.group("units")
                    except IndexError:
                        result["units"] = "MG/DL"
                    try:
                        result["date"] = m.group("date")
                    except IndexError:
                        result["date"] = _try_iso(item)
                    result["source_method"] = "text_regex"
                    result["sources"].append(
                        _make_source(doc_type, prio, item_idx, line_id,
                                     _line_preview(text, m))
                    )
                    return result
            except (re.error, IndexError):
                continue

    if result["value"] is None:
        result["warnings"].append("etoh_not_found")

    return result


# ═════════════════════════════════════════════════════════════════════
#  5. UDS (Urine Drug Screen)
# ═════════════════════════════════════════════════════════════════════

def _extract_uds(
    classified_items: List[Tuple[Dict, str, int]],
    cfg: Dict[str, Any],
    features_data: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Extract UDS panel results.

    Returns dict with: performed (bool), date, components (dict of name→result),
    positive_flags (list), sources, warnings.
    """
    uds_cfg = cfg.get("uds", {})
    result: Dict[str, Any] = {
        "performed": False,
        "date": None,
        "components": {},
        "positive_flags": [],
        "sources": [],
        "warnings": [],
    }

    panel = uds_cfg.get("panel_components", {})

    # ── Try features data first ───────────────────────────────
    if features_data:
        labs_latest = features_data.get("labs", {}).get("latest", [])
        for comp_key, comp_def in panel.items():
            comp_names = [n.lower() for n in comp_def.get("names", [])]
            for lab in labs_latest:
                lab_comp = (lab.get("component") or "").lower()
                if any(cn in lab_comp for cn in comp_names):
                    val_raw = (lab.get("value_raw") or "").upper()
                    lab_result = "UNKNOWN"
                    if "POS" in val_raw:
                        lab_result = "POSITIVE"
                    elif "NEG" in val_raw:
                        lab_result = "NEGATIVE"
                    else:
                        lab_result = val_raw or "UNKNOWN"

                    result["components"][comp_key] = lab_result
                    result["performed"] = True
                    if not result["date"]:
                        result["date"] = lab.get("observed_dt")

                    if lab_result == "POSITIVE":
                        result["positive_flags"].append(comp_key)

                    result["sources"].append({
                        "source_type": "FEATURES_JSON",
                        "priority": 0,
                        "item_id": None,
                        "source_line_id": "labs.latest",
                        "preview": f"{lab.get('component')}: {val_raw}",
                    })
                    break  # found this component, move to next

    # ── Fallback: raw text scan ───────────────────────────────
    if not result["performed"]:
        date_pat_str = uds_cfg.get("date_pattern", "")
        for item, doc_type, prio in classified_items:
            text = item.get("text", "") or ""
            item_idx = item.get("idx", -1)
            line_id = f"L{item.get('line_start', 0)}-L{item.get('line_end', 0)}"

            for comp_key, comp_def in panel.items():
                if comp_key in result["components"]:
                    continue  # already found

                for pat_str in comp_def.get("patterns", []):
                    try:
                        m = re.search(pat_str, text)
                        if m:
                            comp_result = m.group("result").upper()
                            if comp_result in ("POS", "POSITIVE"):
                                comp_result = "POSITIVE"
                            elif comp_result in ("NEG", "NEGATIVE"):
                                comp_result = "NEGATIVE"

                            result["components"][comp_key] = comp_result
                            result["performed"] = True
                            if comp_result == "POSITIVE":
                                result["positive_flags"].append(comp_key)

                            # Try date
                            if not result["date"] and date_pat_str:
                                try:
                                    # Look near the match
                                    nearby = text[max(0, m.start()-50):m.end()+50]
                                    dm = re.search(date_pat_str, nearby)
                                    if dm:
                                        result["date"] = dm.group("date")
                                except re.error:
                                    pass
                            if not result["date"]:
                                result["date"] = _try_iso(item)

                            result["sources"].append(
                                _make_source(doc_type, prio, item_idx, line_id,
                                             _line_preview(text, m))
                            )
                            break
                    except (re.error, IndexError):
                        continue

    if not result["performed"]:
        result["warnings"].append("uds_not_found")

    return result


# ═════════════════════════════════════════════════════════════════════
#  6. BASE DEFICIT
# ═════════════════════════════════════════════════════════════════════

def _extract_base_deficit(
    classified_items: List[Tuple[Dict, str, int]],
    cfg: Dict[str, Any],
    features_data: Optional[Dict[str, Any]],
    trauma_category: Optional[str],
) -> Dict[str, Any]:
    """Extract base deficit value.

    Returns dict with: value, value_numeric, date, is_category_1,
    source_method, sources, warnings.
    """
    bd_cfg = cfg.get("base_deficit", {})
    result: Dict[str, Any] = {
        "value": None,
        "value_numeric": None,
        "units": None,
        "date": None,
        "is_category_1": False,
        "source_method": None,
        "sources": [],
        "warnings": [],
    }

    # ── Check trauma category ─────────────────────────────────
    cat_pats = bd_cfg.get("trauma_category_patterns", [])
    if trauma_category and re.search(r"(?i)\b(?:1|I)\b", str(trauma_category)):
        result["is_category_1"] = True
    else:
        # Scan text for category 1 mentions
        for item, doc_type, prio in classified_items:
            text = item.get("text", "") or ""
            m = _search_any(cat_pats, text[:2000])
            if m:
                result["is_category_1"] = True
                break

    # ── Try features data first ───────────────────────────────
    component_names = [n.lower() for n in bd_cfg.get("lab_component_names", [])]
    if features_data:
        labs_latest = features_data.get("labs", {}).get("latest", [])
        for lab in labs_latest:
            comp = (lab.get("component") or "").lower()
            if any(cn in comp for cn in component_names):
                val_num = lab.get("value_num")
                # Sanity: base deficit should be -5 to 35 mmol/L
                if val_num is not None and (val_num < -5 or val_num > 35):
                    continue
                result["value"] = lab.get("value_raw")
                result["value_numeric"] = val_num
                result["units"] = lab.get("unit")
                result["date"] = lab.get("observed_dt")
                result["source_method"] = "features_json"
                result["sources"].append({
                    "source_type": "FEATURES_JSON",
                    "priority": 0,
                    "item_id": None,
                    "source_line_id": "labs.latest",
                    "preview": f"{lab.get('component')}: {lab.get('value_raw')} {lab.get('unit', '')}",
                })
                break

    # ── Fallback: raw text scan ───────────────────────────────
    if result["value"] is None:
        text_pats = bd_cfg.get("text_patterns", [])
        for item, doc_type, prio in classified_items:
            text = item.get("text", "") or ""
            item_idx = item.get("idx", -1)
            line_id = f"L{item.get('line_start', 0)}-L{item.get('line_end', 0)}"

            for pat_str in text_pats:
                try:
                    m = re.search(pat_str, text)
                    if m:
                        val_raw = m.group("val").strip()
                        val_num = None
                        try:
                            val_num = float(val_raw)
                        except ValueError:
                            pass

                        # Sanity: base deficit should be -5 to 35 mmol/L
                        if val_num is not None and (val_num < -5 or val_num > 35):
                            continue

                        result["value"] = val_raw
                        result["value_numeric"] = val_num
                        try:
                            result["date"] = m.group("date")
                        except IndexError:
                            result["date"] = _try_iso(item)
                        result["source_method"] = "text_regex"
                        result["sources"].append(
                            _make_source(doc_type, prio, item_idx, line_id,
                                         _line_preview(text, m))
                        )
                        break
                except (re.error, IndexError):
                    continue
            if result["value"] is not None:
                break

    # ── Category 1 warning if missing ─────────────────────────
    if result["is_category_1"] and result["value"] is None:
        result["warnings"].append("base_deficit_missing_category_1")

    if result["value"] is None:
        result["warnings"].append("base_deficit_not_found")

    return result


# ═════════════════════════════════════════════════════════════════════
#  7. INR
# ═════════════════════════════════════════════════════════════════════

def _extract_inr(
    classified_items: List[Tuple[Dict, str, int]],
    cfg: Dict[str, Any],
    features_data: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Extract INR value.

    Returns dict with: value, value_numeric, range, date,
    source_method, sources, warnings.
    """
    inr_cfg = cfg.get("inr", {})
    result: Dict[str, Any] = {
        "value": None,
        "value_numeric": None,
        "range": None,
        "date": None,
        "source_method": None,
        "sources": [],
        "warnings": [],
    }

    # ── Try features data first ───────────────────────────────
    component_names = [n.lower() for n in inr_cfg.get("lab_component_names", [])]
    if features_data:
        labs_latest = features_data.get("labs", {}).get("latest", [])
        for lab in labs_latest:
            comp = (lab.get("component") or "").lower()
            if any(cn in comp for cn in component_names):
                val_num = lab.get("value_num")
                # Sanity check: INR should be between 0.5 and 20
                if val_num is not None and (val_num < 0.5 or val_num > 20):
                    continue
                result["value"] = lab.get("value_raw")
                result["value_numeric"] = lab.get("value_num")
                result["units"] = lab.get("unit")
                result["date"] = lab.get("observed_dt")
                result["source_method"] = "features_json"
                result["sources"].append({
                    "source_type": "FEATURES_JSON",
                    "priority": 0,
                    "item_id": None,
                    "source_line_id": "labs.latest",
                    "preview": f"{lab.get('component')}: {lab.get('value_raw')} {lab.get('unit', '')}",
                })
                return result

    # ── Fallback: raw text scan ───────────────────────────────
    text_pats = inr_cfg.get("text_patterns", [])
    for item, doc_type, prio in classified_items:
        text = item.get("text", "") or ""
        item_idx = item.get("idx", -1)
        line_id = f"L{item.get('line_start', 0)}-L{item.get('line_end', 0)}"

        for pat_str in text_pats:
            try:
                m = re.search(pat_str, text)
                if m:
                    val_raw = m.group("val").strip()
                    val_num = None
                    try:
                        val_num = float(val_raw)
                    except ValueError:
                        pass

                    # Sanity check: INR should be between 0.5 and 20
                    if val_num is not None and (val_num < 0.5 or val_num > 20):
                        continue  # Skip unreasonable values

                    result["value"] = val_raw
                    result["value_numeric"] = val_num
                    try:
                        result["range"] = m.group("range")
                    except IndexError:
                        pass
                    try:
                        result["date"] = m.group("date")
                    except IndexError:
                        result["date"] = _try_iso(item)
                    result["source_method"] = "text_regex"
                    result["sources"].append(
                        _make_source(doc_type, prio, item_idx, line_id,
                                     _line_preview(text, m))
                    )
                    return result
            except (re.error, IndexError):
                continue

    if result["value"] is None:
        result["warnings"].append("inr_not_found")

    return result


# ═════════════════════════════════════════════════════════════════════
#  8. IMPRESSION / PLAN DRIFT TIMELINE
# ═════════════════════════════════════════════════════════════════════

def _extract_impression_plan(
    classified_items: List[Tuple[Dict, str, int]],
    cfg: Dict[str, Any],
) -> Dict[str, Any]:
    """Extract Impression/Plan sections from H&P and progress notes.

    Builds a day-by-day timeline for drift tracking.

    Returns dict with: entries (list of {date, doc_type, impression, plan}),
    sources, warnings.
    """
    ip_cfg = cfg.get("impression_plan", {})
    result: Dict[str, Any] = {
        "entries": [],
        "drift_flags": [],
        "sources": [],
        "warnings": [],
    }

    impression_pats = ip_cfg.get("impression_headers", [])
    plan_pats = ip_cfg.get("plan_headers", [])
    stop_pats = ip_cfg.get("stop_headers", [])
    relevant_types = set(ip_cfg.get("relevant_doc_types", ["trauma_hp", "trauma_progress"]))

    stop_res = []
    for sp in stop_pats:
        try:
            stop_res.append(re.compile(sp))
        except re.error:
            continue

    for item, doc_type, prio in classified_items:
        if doc_type not in relevant_types:
            continue

        text = item.get("text", "") or ""
        item_idx = item.get("idx", -1)
        line_id = f"L{item.get('line_start', 0)}-L{item.get('line_end', 0)}"
        item_date = _try_iso(item)
        lines = text.split("\n")

        # Extract impression section — find the LAST occurrence in the note
        # to get the physician's final assessment, not embedded radiology
        impression_text: Optional[str] = None
        for pat_str in impression_pats:
            try:
                imp_re = re.compile(pat_str)
                last_imp_idx = None
                for i, line in enumerate(lines):
                    if imp_re.search(line):
                        last_imp_idx = i
                if last_imp_idx is not None:
                    body: List[str] = []
                    for j in range(last_imp_idx + 1, min(last_imp_idx + 40, len(lines))):
                        ln = lines[j]
                        hit_stop = False
                        for sre in stop_res:
                            if sre.search(ln):
                                hit_stop = True
                                break
                        # Also stop at Plan header
                        for pp in plan_pats:
                            try:
                                if re.search(pp, ln):
                                    hit_stop = True
                                    break
                            except re.error:
                                pass
                        if hit_stop and body:
                            break
                        if ln.strip():
                            body.append(ln.strip())
                    if body:
                        impression_text = "\n".join(body)
                    break
                if impression_text:
                    break
            except re.error:
                continue

        # Extract plan section — find the LAST occurrence
        plan_text: Optional[str] = None
        for pat_str in plan_pats:
            try:
                plan_re = re.compile(pat_str)
                last_plan_idx = None
                for i, line in enumerate(lines):
                    if plan_re.search(line):
                        last_plan_idx = i
                if last_plan_idx is not None:
                    body = []
                    for j in range(last_plan_idx + 1, min(last_plan_idx + 60, len(lines))):
                        ln = lines[j]
                        hit_stop = False
                        for sre in stop_res:
                            if sre.search(ln):
                                hit_stop = True
                                break
                        if hit_stop and body:
                            break
                        if ln.strip():
                            body.append(ln.strip())
                    if body:
                        plan_text = "\n".join(body)
                    break
                if plan_text:
                    break
            except re.error:
                continue

        if impression_text or plan_text:
            entry = {
                "date": item_date,
                "doc_type": doc_type,
                "item_idx": item_idx,
                "impression": impression_text,
                "plan": plan_text,
            }
            result["entries"].append(entry)
            result["sources"].append(
                _make_source(doc_type, prio, item_idx, line_id,
                             (impression_text or plan_text or "")[:200])
            )

    # ── Drift detection ───────────────────────────────────────
    # Compare first entry (H&P) to subsequent entries
    if len(result["entries"]) >= 2:
        hp_entry = result["entries"][0]
        hp_impression = (hp_entry.get("impression") or "").lower()
        hp_plan = (hp_entry.get("plan") or "").lower()

        ac_agents = [a.lower() for a in ip_cfg.get("anticoag_agents_for_diff", [])]

        for entry in result["entries"][1:]:
            entry_impression = (entry.get("impression") or "").lower()
            entry_plan = (entry.get("plan") or "").lower()

            # Check for new anticoagulant mentions not in H&P
            for agent in ac_agents:
                if agent in entry_plan and agent not in hp_plan:
                    result["drift_flags"].append({
                        "type": "new_anticoag_in_plan",
                        "agent": agent,
                        "date": entry.get("date"),
                        "doc_type": entry.get("doc_type"),
                    })

            # Check for new diagnoses/injuries mentioned in later impressions
            # that are NOT in the H&P impression
            if entry_impression and hp_impression:
                # Simple word-based diff: look for diagnostic keywords
                _DX_WORDS = re.compile(
                    r"\b(?:fracture|hemorrhage|pneumothorax|hematoma|"
                    r"laceration|contusion|effusion|edema|DVT|PE|"
                    r"infection|sepsis)\b",
                    re.IGNORECASE,
                )
                hp_dx = set(m.group(0).lower() for m in _DX_WORDS.finditer(hp_impression))
                entry_dx = set(m.group(0).lower() for m in _DX_WORDS.finditer(entry_impression))

                new_dx = entry_dx - hp_dx
                if new_dx:
                    result["drift_flags"].append({
                        "type": "new_diagnosis_in_progress",
                        "new_terms": sorted(new_dx),
                        "date": entry.get("date"),
                        "doc_type": entry.get("doc_type"),
                    })

    if not result["entries"]:
        result["warnings"].append("no_impression_plan_found")

    return result


# ═════════════════════════════════════════════════════════════════════
#  PUBLIC API
# ═════════════════════════════════════════════════════════════════════

def extract_hp_fields(
    classified_items: List[Tuple[Dict, str, int]],
    chosen_trauma_hp_item_id: Optional[int],
    all_items: List[Dict[str, Any]],
    features_data: Optional[Dict[str, Any]] = None,
    existing_anticoag_list: Optional[List[str]] = None,
    trauma_category: Optional[str] = None,
) -> Dict[str, Any]:
    """Extract all H&P-centric fields (spec items 1-6).

    Args:
        classified_items: List of (item, doc_type, priority) sorted by priority.
        chosen_trauma_hp_item_id: The idx of the chosen TRAUMA_HP item.
        all_items: All evidence items.
        features_data: Parsed patient_features_v1.json (optional).
        existing_anticoag_list: Already-extracted home_anticoagulant list.
        trauma_category: Meta trauma_category string.

    Returns:
        Dict with keys: primary_survey, admitting_md, anticoag_status,
        etoh, uds, base_deficit, inr, impression_plan.
    """
    cfg = _load_hp_config()

    # Find the chosen TRAUMA_HP item text
    hp_text = ""
    hp_item_idx = -1
    hp_line_id = ""
    if chosen_trauma_hp_item_id is not None:
        for item in all_items:
            if item.get("idx") == chosen_trauma_hp_item_id:
                hp_text = item.get("text", "") or ""
                hp_item_idx = item.get("idx", -1)
                hp_line_id = f"L{item.get('line_start', 0)}-L{item.get('line_end', 0)}"
                break

    # Collect ALL TRAUMA_HP items (for admitting_md search across cosig stubs)
    all_hp_texts: List[Tuple[str, int, str]] = []
    for item in all_items:
        kind = (item.get("kind", "") or "").upper()
        if kind == "TRAUMA_HP":
            txt = item.get("text", "") or ""
            idx = item.get("idx", -1)
            lid = f"L{item.get('line_start', 0)}-L{item.get('line_end', 0)}"
            all_hp_texts.append((txt, idx, lid))
    # Ensure chosen HP is first (highest search priority)
    if hp_item_idx >= 0:
        all_hp_texts.sort(key=lambda x: (0 if x[1] == hp_item_idx else 1))

    # 1. Primary Survey (TRAUMA_HP only)
    primary_survey = _extract_primary_survey(
        hp_text, cfg, hp_item_idx, hp_line_id,
    )

    # 2. Admitting MD (ALL TRAUMA_HP items — finds cosigner across stubs)
    admitting_md = _extract_admitting_md(
        all_hp_texts, cfg,
    )

    # 3. Anticoag Status (all items)
    anticoag_status = _extract_anticoag_status(
        classified_items, cfg, existing_anticoag_list,
    )

    # 4. ETOH
    etoh = _extract_etoh(
        classified_items, cfg, features_data,
    )

    # 5. UDS
    uds = _extract_uds(
        classified_items, cfg, features_data,
    )

    # 6. Base Deficit
    base_deficit = _extract_base_deficit(
        classified_items, cfg, features_data, trauma_category,
    )

    # 7. INR
    inr = _extract_inr(
        classified_items, cfg, features_data,
    )

    # 8. Impression/Plan drift
    impression_plan = _extract_impression_plan(
        classified_items, cfg,
    )

    return {
        "primary_survey": primary_survey,
        "admitting_md": admitting_md,
        "anticoag_status": anticoag_status,
        "etoh": etoh,
        "uds": uds,
        "base_deficit": base_deficit,
        "inr": inr,
        "impression_plan": impression_plan,
    }
