#!/usr/bin/env python3
"""
Orders Presence Checklist — Section 9.4.

Informational-only domain that checks whether common trauma care orders
appear in patient documentation. Returns YES/NO/NOT_APPLICABLE per item.

Governance boundaries (Section 9.4):
- Values limited to: YES, NO, NOT_APPLICABLE
- Informational only — no compliance semantics
- No timing inference unless explicitly stated in item text
- Must never determine NTDS status or protocol trigger status
- Must never influence Findings
- Must never be treated as evidence of care quality or deficiency

Assembly position (Section 10.8):
- Renders after Protocol Output
- Renders before Opportunity Flags (if enabled)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class OrderItem:
    """A single orders presence checklist item."""
    item_id: str
    label: str
    result: str  # "YES", "NO", "NOT_APPLICABLE"


@dataclass
class OrdersChecklistResult:
    """Result of the Orders Presence Checklist."""
    items: List[OrderItem] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Checklist item definitions
# ---------------------------------------------------------------------------
# Each item: (item_id, label, search_patterns, applicability_patterns)
# - search_patterns: regexes to look for in evidence to determine YES
# - applicability_patterns: if specified, item is NOT_APPLICABLE unless
#   any of these patterns are found in evidence (contextual gating)

_CHECKLIST_ITEMS = [
    {
        "item_id": "dvt_prophylaxis",
        "label": "DVT/VTE Prophylaxis Ordered",
        "search_patterns": [
            r"\bheparin\b",
            r"\benoxaparin\b",
            r"\blovenox\b",
            r"\bfondaparinux\b",
            r"\bSCD\b",
            r"\bsequential\s+compression\b",
            r"\bTED\s+hose\b",
            r"\bDVT\s+(?:ppx|prophylaxis)\b",
            r"\bVTE\s+(?:ppx|prophylaxis)\b",
        ],
        "applicability_patterns": None,  # Always applicable for trauma
    },
    {
        "item_id": "stress_ulcer_prophylaxis",
        "label": "Stress Ulcer Prophylaxis Ordered",
        "search_patterns": [
            r"\bpantoprazole\b",
            r"\bprotonix\b",
            r"\bomeprazole\b",
            r"\bprilosec\b",
            r"\besomeprazole\b",
            r"\bnexium\b",
            r"\branitidine\b",
            r"\bfamotidine\b",
            r"\bpepcid\b",
            r"\bPPI\b",
            r"\bH2\s+blocker\b",
            r"\bstress\s+ulcer\s+(?:ppx|prophylaxis)\b",
        ],
        "applicability_patterns": None,
    },
    {
        "item_id": "pain_management",
        "label": "Pain Management Ordered",
        "search_patterns": [
            r"\bacetaminophen\b",
            r"\btylenol\b",
            r"\bibuprofen\b",
            r"\bketorolac\b",
            r"\btoradol\b",
            r"\bmorphine\b",
            r"\bfentanyl\b",
            r"\bhydromorphone\b",
            r"\bdilaudid\b",
            r"\boxycodone\b",
            r"\bpercocet\b",
            r"\bgabapentin\b",
            r"\blidocaine\b",
            r"\bnerve\s+block\b",
            r"\bPCA\b",
            r"\bpain\s+management\b",
            r"\banalgesi[ac]\b",
        ],
        "applicability_patterns": None,
    },
    {
        "item_id": "tetanus_prophylaxis",
        "label": "Tetanus Prophylaxis Ordered",
        "search_patterns": [
            r"\btetanus\b",
            r"\bTdap\b",
            r"\bTd\s+(?:vaccine|immunization|shot)\b",
            r"\btetanus\s+(?:toxoid|vaccine|immunization|booster|shot)\b",
        ],
        "applicability_patterns": [
            # Applicable when open wounds, lacerations, or penetrating trauma
            r"\blaceration\b",
            r"\bopen\s+(?:wound|fracture)\b",
            r"\bpenetrating\b",
            r"\bstab\b",
            r"\bGSW\b",
            r"\bgunshot\b",
            r"\bbite\b",
            r"\babrasion\b",
            r"\bavulsion\b",
        ],
    },
    {
        "item_id": "antibiotic_prophylaxis",
        "label": "Antibiotic Prophylaxis Ordered",
        "search_patterns": [
            r"\bcefazolin\b",
            r"\bancef\b",
            r"\bceftriaxone\b",
            r"\brocephin\b",
            r"\bvancomycin\b",
            r"\bpiperacillin\b",
            r"\bzosyn\b",
            r"\bciprofloxacin\b",
            r"\bmetronidazole\b",
            r"\bflagyl\b",
            r"\bclindamycin\b",
            r"\bantibiotics?\s+(?:ordered|started|given|administered)\b",
            r"\bperioperative\s+antibiotics?\b",
            r"\bsurgical\s+(?:ppx|prophylaxis)\b",
        ],
        "applicability_patterns": [
            # Applicable for open fractures, surgical patients, penetrating trauma
            r"\bopen\s+fracture\b",
            r"\boperative\b",
            r"\bsurgery\b",
            r"\bsurgical\b",
            r"\bpenetrating\b",
            r"\bstab\b",
            r"\bGSW\b",
            r"\bgunshot\b",
        ],
    },
    {
        "item_id": "blood_products",
        "label": "Blood Products Transfused",
        "search_patterns": [
            r"\bPRBC\b",
            r"\bpacked\s+red\s+(?:blood\s+)?cells?\b",
            r"\btransfus(?:ion|ed)\b",
            r"\bFFP\b",
            r"\bfresh\s+frozen\s+plasma\b",
            r"\bplatelets?\s+(?:transfus|given|ordered|administered)\b",
            r"\bcryoprecipitate\b",
            r"\bmassive\s+transfusion\b",
            r"\bMTP\b",
            r"\bblood\s+products?\b",
            r"\bED\s+blood\s+box\b",
        ],
        "applicability_patterns": [
            r"\bhemorrhag\b",
            r"\bbleeding\b",
            r"\bshock\b",
            r"\bhemoglobin\b.*\b[3-7]\.\d\b",
            r"\btransfus\b",
            r"\bMTP\b",
            r"\bblood\s+product\b",
        ],
    },
    {
        "item_id": "seizure_prophylaxis",
        "label": "Seizure Prophylaxis Ordered",
        "search_patterns": [
            r"\blevetiracetam\b",
            r"\bkeppra\b",
            r"\bphenytoin\b",
            r"\bdilantin\b",
            r"\bseizure\s+(?:ppx|prophylaxis)\b",
            r"\bantiepileptic\b",
            r"\banticonvulsant\b",
        ],
        "applicability_patterns": [
            # Applicable for TBI patients
            r"\bTBI\b",
            r"\btraumatic\s+brain\s+injur\b",
            r"\bintracranial\s+hemorrh\b",
            r"\bsubdural\b",
            r"\bepidural\s+hematoma\b",
            r"\bsubarachnoid\s+hemorrh\b",
            r"\bintraparenchymal\b",
            r"\bGCS\s*:?\s*[3-8]\b",
        ],
    },
]


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def evaluate_orders_checklist(
    evaluation: Dict[str, Any],
) -> OrdersChecklistResult:
    """
    Evaluate the Orders Presence Checklist for a patient.

    Scans all_evidence_snippets from the evaluation dict for order patterns.
    Returns YES/NO/NOT_APPLICABLE per checklist item.

    This is strictly informational — no compliance or quality inference.
    """
    result = OrdersChecklistResult()

    # Collect all evidence text
    all_text_parts: List[str] = []
    for snippet in evaluation.get("all_evidence_snippets", []):
        text = snippet.get("text") or snippet.get("text_raw") or ""
        if text:
            all_text_parts.append(text)
    combined_text = "\n".join(all_text_parts)

    for item_def in _CHECKLIST_ITEMS:
        item_id = item_def["item_id"]
        label = item_def["label"]
        search_patterns = item_def["search_patterns"]
        applicability_patterns = item_def.get("applicability_patterns")

        # Check applicability first
        if applicability_patterns:
            applicable = False
            for pat in applicability_patterns:
                if re.search(pat, combined_text, re.IGNORECASE):
                    applicable = True
                    break
            if not applicable:
                result.items.append(OrderItem(
                    item_id=item_id,
                    label=label,
                    result="NOT_APPLICABLE",
                ))
                continue

        # Search for order presence
        found = False
        for pat in search_patterns:
            if re.search(pat, combined_text, re.IGNORECASE):
                found = True
                break

        result.items.append(OrderItem(
            item_id=item_id,
            label=label,
            result="YES" if found else "NO",
        ))

    return result


def format_orders_text(checklist: OrdersChecklistResult) -> str:
    """Format orders checklist as text for the PI report."""
    lines: List[str] = []
    lines.append("=" * 70)
    lines.append("ORDERS PRESENCE CHECKLIST (informational only)")
    lines.append("=" * 70)

    for item in checklist.items:
        tag = f"[{item.result:>14s}]"
        lines.append(f"  {tag}  {item.label}")

    lines.append("")
    return "\n".join(lines)
