#!/usr/bin/env python3
"""
CerebralOS Dashboard Generator — Elle Woods on a Trauma Committee.

Generates a self-contained HTML dashboard index page that aggregates
results from multiple patient evaluations into a sortable, interactive
overview with links to individual patient reports.
"""
from __future__ import annotations

import html as _html
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def _e(text: str) -> str:
    return _html.escape(str(text)) if text else ""


def _build_dashboard_css() -> str:
    return """
:root {
    --pink-50: #fdf2f8; --pink-100: #fce7f3; --pink-200: #fbcfe8;
    --pink-300: #f9a8d4; --pink-400: #f472b6; --pink-500: #ec4899;
    --pink-600: #db2777; --pink-700: #be185d;
    --gold-light: #fbbf24; --gold: #d4a843; --gold-dark: #b8860b; --gold-shimmer: #f59e0b;
    --emerald: #059669; --emerald-light: #d1fae5;
    --amber: #d97706; --amber-light: #fef3c7;
    --gray: #9ca3af; --gray-light: #f3f4f6;
    --text-primary: #1e1b4b; --text-secondary: #4c1d95;
    --bg: var(--pink-50); --card-bg: #ffffff;
    --card-shadow: rgba(236,72,153,0.08); --card-radius: 12px;
}
*, *::before, *::after { box-sizing: border-box; }
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    background: var(--bg); color: var(--text-primary); margin: 0; padding: 16px;
    line-height: 1.5; -webkit-font-smoothing: antialiased;
}
h1, h2, h3 { font-family: Georgia, "Times New Roman", Times, serif; font-weight: 700; }
.container { max-width: 1100px; margin: 0 auto; }
.header {
    background: linear-gradient(135deg, var(--pink-600), var(--gold), var(--pink-500), var(--gold-shimmer), var(--pink-600));
    background-size: 300% 300%; animation: shimmer 8s ease infinite;
    color: white; padding: 28px 32px; border-radius: var(--card-radius); margin-bottom: 20px;
    text-shadow: 0 1px 3px rgba(0,0,0,0.15);
}
.header h1 { margin: 0 0 4px 0; font-size: 1.6em; }
.header .subtitle { opacity: 0.92; font-size: 0.95em; }
@keyframes shimmer {
    0% { background-position: 0% 50%; }
    50% { background-position: 100% 50%; }
    100% { background-position: 0% 50%; }
}
.stats-row {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 12px; margin-bottom: 24px;
}
.stat-card {
    background: var(--card-bg); border-radius: var(--card-radius);
    padding: 16px; text-align: center; box-shadow: 0 2px 8px var(--card-shadow);
}
.stat-card .stat-num { font-size: 2em; font-weight: 800; line-height: 1.1; }
.stat-card .stat-label { font-size: 0.72em; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-secondary); margin-top: 4px; }
.stat-patients { border-top: 4px solid var(--pink-400); }
.stat-patients .stat-num { color: var(--pink-500); }
.stat-nc { border-top: 4px solid var(--pink-500); }
.stat-nc .stat-num { color: var(--pink-600); }
.stat-ind { border-top: 4px solid var(--gold); }
.stat-ind .stat-num { color: var(--amber); }
.stat-comp { border-top: 4px solid var(--emerald); }
.stat-comp .stat-num { color: var(--emerald); }
.stat-yes { border-top: 4px solid var(--pink-500); }
.stat-yes .stat-num { color: var(--pink-600); }

.section-heading {
    font-size: 1.15em; margin: 24px 0 12px; padding-bottom: 6px;
    border-bottom: 2px solid var(--gold); color: var(--text-secondary);
}

/* Patient table */
table.patient-table {
    width: 100%; border-collapse: collapse; background: var(--card-bg);
    border-radius: var(--card-radius); overflow: hidden;
    box-shadow: 0 2px 8px var(--card-shadow); font-size: 0.88em;
}
table.patient-table th {
    background: var(--pink-600); color: white; padding: 10px 12px;
    text-align: left; font-size: 0.78em; text-transform: uppercase;
    letter-spacing: 0.04em; cursor: pointer; user-select: none;
    white-space: nowrap;
}
table.patient-table th:hover { background: var(--pink-700); }
table.patient-table th .sort-arrow { font-size: 0.7em; margin-left: 4px; opacity: 0.6; }
table.patient-table td {
    padding: 8px 12px; border-bottom: 1px solid var(--pink-100);
}
table.patient-table tr:last-child td { border-bottom: none; }
table.patient-table tr:hover { background: var(--pink-50); }
.cell-nc { color: var(--pink-600); font-weight: 700; }
.cell-ind { color: var(--amber); font-weight: 700; }
.cell-comp { color: var(--emerald); font-weight: 600; }
.cell-zero { color: var(--gray); }
.cell-yes { color: var(--pink-600); font-weight: 700; }
.cell-live {
    display: inline-block; width: 8px; height: 8px; background: var(--pink-500);
    border-radius: 50%; animation: pulse-live 2s ease-in-out infinite; margin-right: 4px;
}
@keyframes pulse-live { 0%,100% { opacity: 1; } 50% { opacity: 0.3; } }
a.patient-link { color: var(--text-secondary); text-decoration: none; font-weight: 600; }
a.patient-link:hover { text-decoration: underline; color: var(--pink-600); }

/* NTDS summary */
.ntds-summary {
    background: var(--card-bg); border-radius: var(--card-radius);
    padding: 16px 20px; box-shadow: 0 2px 8px var(--card-shadow);
    margin-bottom: 16px;
}
.ntds-row { display: flex; align-items: center; gap: 8px; padding: 4px 0; font-size: 0.9em; }
.ntds-bar {
    height: 18px; background: var(--pink-400); border-radius: 4px; min-width: 2px;
    transition: width 0.3s;
}
.footer {
    text-align: center; padding: 20px 0 8px; color: var(--gray); font-size: 0.78em;
    border-top: 2px solid var(--gold); margin-top: 32px;
}
@media (max-width: 600px) {
    body { padding: 8px; }
    .header { padding: 18px 16px; }
    .header h1 { font-size: 1.25em; }
    .stats-row { grid-template-columns: repeat(2, 1fr); gap: 8px; }
    table.patient-table { font-size: 0.8em; }
    table.patient-table th, table.patient-table td { padding: 6px 8px; }
}
"""


def _build_sort_js() -> str:
    return """
<script>
function sortTable(colIdx, type) {
    var table = document.getElementById('ptable');
    var tbody = table.tBodies[0];
    var rows = Array.from(tbody.rows);
    var asc = table.getAttribute('data-sort-col') != colIdx || table.getAttribute('data-sort-dir') != 'asc';
    rows.sort(function(a, b) {
        var av = a.cells[colIdx].getAttribute('data-val') || a.cells[colIdx].textContent.trim();
        var bv = b.cells[colIdx].getAttribute('data-val') || b.cells[colIdx].textContent.trim();
        if (type === 'num') { av = parseFloat(av) || 0; bv = parseFloat(bv) || 0; }
        if (av < bv) return asc ? -1 : 1;
        if (av > bv) return asc ? 1 : -1;
        return 0;
    });
    rows.forEach(function(r) { tbody.appendChild(r); });
    table.setAttribute('data-sort-col', colIdx);
    table.setAttribute('data-sort-dir', asc ? 'asc' : 'desc');
}
</script>
"""


def generate_dashboard(
    evaluations: List[Dict[str, Any]],
    output_dir: Path,
) -> Path:
    """
    Generate dashboard index.html from multiple patient evaluations.

    Args:
        evaluations: List of evaluation dicts from batch_eval.evaluate_patient()
        output_dir: Directory to write index.html into

    Returns:
        Path to generated index.html
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    n_patients = len(evaluations)

    # Aggregate counts
    total_nc = 0
    total_ind = 0
    total_comp = 0
    total_ntds_yes = 0
    total_ntds_unable = 0
    live_count = 0

    for ev in evaluations:
        for r in ev.get("results", []):
            o = r.get("outcome", "")
            if o == "NON_COMPLIANT": total_nc += 1
            elif o == "INDETERMINATE": total_ind += 1
            elif o == "COMPLIANT": total_comp += 1
        for r in ev.get("ntds_results", []):
            o = r.get("outcome", "")
            if o == "YES": total_ntds_yes += 1
            elif o == "UNABLE_TO_DETERMINE": total_ntds_unable += 1
        if ev.get("is_live"): live_count += 1

    # NTDS event summary across patients
    ntds_event_yes: Dict[str, int] = {}
    for ev in evaluations:
        for r in ev.get("ntds_results", []):
            if r.get("outcome") == "YES":
                name = r.get("canonical_name", "Unknown")
                ntds_event_yes[name] = ntds_event_yes.get(name, 0) + 1

    parts = []
    parts.append('<!DOCTYPE html>')
    parts.append('<html lang="en">')
    parts.append('<head>')
    parts.append('<meta charset="UTF-8">')
    parts.append('<meta name="viewport" content="width=device-width, initial-scale=1.0">')
    parts.append('<title>CerebralOS &mdash; Dashboard</title>')
    parts.append(f'<style>{_build_dashboard_css()}</style>')
    parts.append('</head>')
    parts.append('<body>')
    parts.append('<div class="container">')

    # Header
    parts.append('<div class="header">')
    parts.append('<h1>CerebralOS Governance Dashboard</h1>')
    live_text = f" &mdash; {live_count} live" if live_count else ""
    parts.append(f'<div class="subtitle">{n_patients} patients{live_text} &mdash; {_e(now)}</div>')
    parts.append('</div>')

    # Stat cards
    parts.append('<div class="stats-row">')
    parts.append(f'<div class="stat-card stat-patients"><div class="stat-num">{n_patients}</div><div class="stat-label">Patients</div></div>')
    parts.append(f'<div class="stat-card stat-nc"><div class="stat-num">{total_nc}</div><div class="stat-label">Non-Compliant</div></div>')
    parts.append(f'<div class="stat-card stat-ind"><div class="stat-num">{total_ind}</div><div class="stat-label">Indeterminate</div></div>')
    parts.append(f'<div class="stat-card stat-comp"><div class="stat-num">{total_comp}</div><div class="stat-label">Compliant</div></div>')
    parts.append(f'<div class="stat-card stat-yes"><div class="stat-num">{total_ntds_yes}</div><div class="stat-label">NTDS Yes</div></div>')
    parts.append('</div>')

    # Patient table
    parts.append('<h2 class="section-heading">Patient Overview</h2>')
    parts.append('<table class="patient-table" id="ptable">')
    parts.append('<thead><tr>')
    cols = [
        ("Patient", "str", 0), ("Arrival", "str", 1), ("Cat", "str", 2),
        ("NC", "num", 3), ("IND", "num", 4), ("COMP", "num", 5),
        ("Triggered", "num", 6), ("NTDS Yes", "num", 7), ("Status", "str", 8),
    ]
    for col_name, col_type, idx in cols:
        parts.append(f'<th onclick="sortTable({idx},\'{col_type}\')">{_e(col_name)}<span class="sort-arrow">&#x25B4;&#x25BE;</span></th>')
    parts.append('</tr></thead>')
    parts.append('<tbody>')

    for ev in evaluations:
        name = ev.get("patient_name") or ev.get("patient_id") or "Unknown"
        arrival = ev.get("arrival_time") or ""
        cat = ev.get("trauma_category") or ""
        is_live = ev.get("is_live", False)

        nc = sum(1 for r in ev.get("results", []) if r["outcome"] == "NON_COMPLIANT")
        ind = sum(1 for r in ev.get("results", []) if r["outcome"] == "INDETERMINATE")
        comp = sum(1 for r in ev.get("results", []) if r["outcome"] == "COMPLIANT")
        triggered = nc + ind + comp
        ntds_yes = sum(1 for r in ev.get("ntds_results", []) if r["outcome"] == "YES")

        # Link to individual HTML report
        stem = Path(ev.get("source_file", "")).stem
        report_file = f"{stem}_report.html"

        live_dot = '<span class="cell-live"></span>' if is_live else ""
        status = "LIVE" if is_live else "Discharged"

        def _cell_cls(val: int, cls: str) -> str:
            return f'class="{cls}"' if val > 0 else 'class="cell-zero"'

        parts.append('<tr>')
        parts.append(f'<td><a class="patient-link" href="{_e(report_file)}">{live_dot}{_e(name)}</a></td>')
        parts.append(f'<td>{_e(arrival)}</td>')
        parts.append(f'<td>{_e(cat)}</td>')
        parts.append(f'<td {_cell_cls(nc, "cell-nc")} data-val="{nc}">{nc}</td>')
        parts.append(f'<td {_cell_cls(ind, "cell-ind")} data-val="{ind}">{ind}</td>')
        parts.append(f'<td {_cell_cls(comp, "cell-comp")} data-val="{comp}">{comp}</td>')
        parts.append(f'<td data-val="{triggered}">{triggered}</td>')
        parts.append(f'<td {_cell_cls(ntds_yes, "cell-yes")} data-val="{ntds_yes}">{ntds_yes}</td>')
        parts.append(f'<td>{_e(status)}</td>')
        parts.append('</tr>')

    parts.append('</tbody></table>')

    # NTDS events detected across patients
    if ntds_event_yes:
        parts.append('<h2 class="section-heading">NTDS Events Detected Across Patients</h2>')
        parts.append('<div class="ntds-summary">')
        max_count = max(ntds_event_yes.values()) if ntds_event_yes else 1
        for event_name, count in sorted(ntds_event_yes.items(), key=lambda x: -x[1]):
            bar_pct = (count / max_count) * 100
            parts.append('<div class="ntds-row">')
            parts.append(f'<span style="min-width:180px;">{_e(event_name)}</span>')
            parts.append(f'<div class="ntds-bar" style="width:{bar_pct:.0f}%;"></div>')
            parts.append(f'<span style="font-weight:700;color:var(--pink-600);">{count}/{n_patients}</span>')
            parts.append('</div>')
        parts.append('</div>')

    # Footer
    parts.append(f'<div class="footer">Generated: {_e(now)} &mdash; CerebralOS Governance Engine v2026.01</div>')

    parts.append('</div>')
    parts.append(_build_sort_js())
    parts.append('</body></html>')

    result = "\n".join(parts)
    out_path = output_dir / "index.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(result, encoding="utf-8")

    return out_path
