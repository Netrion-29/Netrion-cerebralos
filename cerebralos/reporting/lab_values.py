#!/usr/bin/env python3
"""
Lab value extraction and grouping for trauma reports.

Extracts actual lab VALUES with abnormal flags, grouped by day,
filtered for protocol-relevant tests.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime


# Protocol-relevant lab tests for trauma
_TRAUMA_RELEVANT_LABS = {
    # Hematology (bleeding, anemia, coagulopathy)
    "hemoglobin": {"abbrev": ["hgb", "hb"], "critical": True},
    "hematocrit": {"abbrev": ["hct"], "critical": True},
    "platelet count": {"abbrev": ["plt", "platelets"], "critical": True},
    "white blood cell count": {"abbrev": ["wbc"], "critical": False},
    "inr": {"abbrev": ["inr"], "critical": True},

    # Chemistry (renal, electrolytes)
    "creatinine": {"abbrev": ["cr", "creat"], "critical": True},
    "sodium": {"abbrev": ["na"], "critical": True},
    "potassium": {"abbrev": ["k"], "critical": True},
    "chloride": {"abbrev": ["cl"], "critical": False},
    "bun": {"abbrev": ["bun"], "critical": False},

    # Liver (if significant injury or abnormal on admission)
    "ast": {"abbrev": ["sgot", "aspartate"], "critical": False},
    "alt": {"abbrev": ["sgpt", "alanine"], "critical": False},
    "alkaline phosphatase": {"abbrev": ["alkphos", "alk phos", "alp"], "critical": False},
    "bilirubin": {"abbrev": ["bili", "labbili", "tbili"], "critical": False},

    # Lactate (shock, tissue perfusion)
    "lactate": {"abbrev": ["lactic acid"], "critical": True},
}


def _normalize_lab_name(component: str) -> Optional[str]:
    """
    Normalize lab component name to canonical form.

    Returns canonical name or None if not relevant for trauma.
    """
    lower = component.lower().strip()

    # Check exact matches
    if lower in _TRAUMA_RELEVANT_LABS:
        return lower

    # Check abbreviations
    for canonical, info in _TRAUMA_RELEVANT_LABS.items():
        for abbrev in info["abbrev"]:
            if abbrev in lower or lower in abbrev:
                return canonical

    return None


def _parse_detailed_lab_table(lab_text: str) -> List[Dict[str, Any]]:
    """
    Parse detailed lab table format.

    Format:
    Component   Date   Value   Ref Range   Status
    • White Blood Cell Count   12/17/2025   7.1    3.4 - 10.8 THOUS/uL   Final
    """
    results = []

    # Find lines that look like lab results (start with bullet or whitespace + component name)
    lines = lab_text.split("\n")

    current_date = None
    for line in lines:
        # Extract date from admission header
        date_match = re.search(r"Admission on (\d{1,2}/\d{1,2}/\d{4})", line)
        if date_match:
            current_date = date_match.group(1)

        # Skip header lines
        if "Component" in line and "Date" in line:
            continue

        # Parse result lines (start with bullet or tabs)
        if not re.match(r"^[•\t\s]+\w", line):
            continue

        # Split by tabs
        parts = re.split(r"\t+", line.strip())
        if len(parts) < 5:  # Need at least bullet, component, date, value, ref range
            continue

        # Parts: [bullet, component, date, value, ref_range, status]
        component = parts[1].strip() if len(parts) > 1 else ""
        date_str = parts[2].strip() if len(parts) > 2 else ""
        value_raw = parts[3].strip() if len(parts) > 3 else ""
        ref_range = parts[4].strip() if len(parts) > 4 else ""

        # Skip if no value
        if not value_raw or value_raw == "--":
            continue

        # Check if relevant
        canonical = _normalize_lab_name(component)
        if not canonical:
            continue

        # Parse value and check for abnormal flag
        value = value_raw
        is_abnormal = False

        # Check for (L) or (H) indicators
        if "(L)" in value or "(H)" in value:
            is_abnormal = True
            value = re.sub(r"\s*\([LH]\)", "", value).strip()

        # Extract numeric value
        value_match = re.match(r"([\d.]+)", value)
        if value_match:
            numeric_value = float(value_match.group(1))
        else:
            numeric_value = None

        results.append({
            "component": canonical,
            "date": date_str or current_date,
            "value": value,
            "numeric_value": numeric_value,
            "ref_range": ref_range,
            "is_abnormal": is_abnormal,
            "critical": _TRAUMA_RELEVANT_LABS[canonical]["critical"],
        })

    return results


def _parse_trends_lab_table(lab_text: str) -> List[Dict[str, Any]]:
    """
    Parse trends lab table format.

    Format:
     	12/17/25 1439   12/17/25 1621   12/18/25 0405
    WBC	7.1             --              10.0
    HGB	14.3            --              12.3*
    """
    results = []

    lines = lab_text.split("\n")

    # Find the header line with dates
    date_line_idx = None
    dates = []
    for i, line in enumerate(lines):
        if re.search(r"\d{1,2}/\d{1,2}/\d{2}", line):
            # Extract all dates from this line
            date_matches = re.findall(r"(\d{1,2}/\d{1,2}/\d{2,4}(?:\s+\d{4})?)", line)
            if len(date_matches) >= 2:  # Must have at least 2 date columns
                dates = date_matches
                date_line_idx = i
                break

    if not dates:
        return []

    # Parse data lines after header
    for line in lines[date_line_idx + 1:]:
        if not line.strip():
            continue

        # Skip if this looks like another header
        if "Component" in line or "Recent Labs" in line:
            continue

        parts = re.split(r"\t+", line.strip())
        if len(parts) < 2:
            continue

        component = parts[0].strip().upper()

        # Check if relevant
        canonical = _normalize_lab_name(component)
        if not canonical:
            continue

        # Parse values for each date column
        for col_idx, date in enumerate(dates):
            value_idx = col_idx + 1
            if value_idx >= len(parts):
                continue

            value_raw = parts[value_idx].strip()

            # Skip empty or "--"
            if not value_raw or value_raw == "--":
                continue

            # Check for abnormal flag (*)
            is_abnormal = "*" in value_raw
            value = value_raw.replace("*", "").strip()

            # Extract numeric value
            value_match = re.match(r"([\d.]+)", value)
            if value_match:
                numeric_value = float(value_match.group(1))
            else:
                numeric_value = None

            results.append({
                "component": canonical,
                "date": date.split()[0],  # Remove time if present
                "value": value,
                "numeric_value": numeric_value,
                "ref_range": "",
                "is_abnormal": is_abnormal,
                "critical": _TRAUMA_RELEVANT_LABS[canonical]["critical"],
            })

    return results


def extract_lab_values(evaluation: Dict) -> List[Dict[str, Any]]:
    """
    Extract trauma-relevant lab values from all LAB evidence blocks.

    Returns list of lab results sorted by date.
    """
    all_results = []

    for snippet in evaluation.get("all_evidence_snippets", []):
        if snippet.get("source_type") != "LAB":
            continue

        text = snippet.get("text", "")

        # Try both parsers
        detailed = _parse_detailed_lab_table(text)
        trends = _parse_trends_lab_table(text)

        all_results.extend(detailed)
        all_results.extend(trends)

    # Deduplicate by (component, date, value)
    seen = set()
    unique_results = []
    for r in all_results:
        key = (r["component"], r["date"], r["value"])
        if key not in seen:
            seen.add(key)
            unique_results.append(r)

    # Sort by date, then by component
    def parse_date(date_str):
        try:
            return datetime.strptime(date_str.split()[0], "%m/%d/%Y")
        except:
            try:
                return datetime.strptime(date_str.split()[0], "%m/%d/%y")
            except:
                return datetime.min

    unique_results.sort(key=lambda r: (parse_date(r["date"]), r["component"]))

    return unique_results


def group_labs_by_day(lab_values: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Group lab values by date.

    Returns dict mapping date string to list of lab results.
    """
    by_day: Dict[str, List[Dict[str, Any]]] = {}

    for lab in lab_values:
        date_key = lab["date"].split()[0]  # Remove time component
        if date_key not in by_day:
            by_day[date_key] = []
        by_day[date_key].append(lab)

    return by_day


def format_lab_report(lab_values: List[Dict[str, Any]]) -> str:
    """
    Format lab values as human-readable report.

    Shows VALUES with abnormal flags, grouped by day.
    """
    if not lab_values:
        return "No protocol-relevant lab values found."

    lines = []
    lines.append("🧪 PROTOCOL-RELEVANT LAB VALUES")
    lines.append("")

    # Group by day
    by_day = group_labs_by_day(lab_values)

    for date in sorted(by_day.keys()):
        labs = by_day[date]

        lines.append(f"📅 {date}")

        # Separate critical from non-critical
        critical = [l for l in labs if l["critical"]]
        noncritical = [l for l in labs if not l["critical"]]

        if critical:
            lines.append("  Critical values:")
            for lab in critical:
                flag = " ⚠️ ABNORMAL" if lab["is_abnormal"] else ""
                ref = f" (ref: {lab['ref_range']})" if lab['ref_range'] else ""
                lines.append(f"    • {lab['component'].title()}: {lab['value']}{ref}{flag}")

        if noncritical:
            lines.append("  Other values:")
            for lab in noncritical:
                flag = " ⚠️" if lab["is_abnormal"] else ""
                ref = f" (ref: {lab['ref_range']})" if lab['ref_range'] else ""
                lines.append(f"    • {lab['component'].title()}: {lab['value']}{ref}{flag}")

        lines.append("")

    return "\n".join(lines)
