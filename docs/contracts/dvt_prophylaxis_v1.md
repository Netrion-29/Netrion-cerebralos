# CerebralOS Contract
# DVT Prophylaxis Schema v1

Status: ACTIVE
Phase: Tier 1 Metric #1
Owner: CerebralOS DVT Prophylaxis Engine

------------------------------------------------------------
1. Purpose
------------------------------------------------------------

Measure time to first *chemical* (pharmacologic) DVT prophylaxis
from hospital arrival.  Mechanical prophylaxis (SCDs) is tracked
for clinical context but does NOT satisfy the compliance metric.

Key invariants:
- `dvt_first_ts` = `pharm_first_ts` (chemical prophylaxis only).
- `delay_hours` and `delay_flag_24h` computed from `pharm_first_ts`.
- Mechanical prophylaxis never sets `dvt_first_ts`.
- Lines matching drug keywords but lacking admin/dispense evidence
  are classified as AMBIGUOUS_NON_ADMIN_MENTION (not counted).

------------------------------------------------------------
2. Output Contract Object
------------------------------------------------------------

{
  "pharm_first_ts":  ISO-8601 | null,   # PRIMARY — first confirmed chemical admin
  "mech_first_ts":   ISO-8601 | null,   # SECONDARY — first confirmed mechanical (informational)
  "first_ts":        ISO-8601 | null,   # DEPRECATED — equals pharm_first_ts

  "delay_hours":     float | null,       # hours from arrival to pharm_first_ts
  "delay_flag_24h":  bool  | null,       # delay_hours > 24

  "excluded_reason": string | null,
  # Possible values:
  #   THERAPEUTIC_ANTICOAG                — therapeutic anticoag present
  #   CHEM_PROPHY_HELD_CONTRAINDICATION   — chemical prophylaxis held or contraindicated
  #   NO_CHEMICAL_PROPHYLAXIS_EVIDENCE    — no confirmed chemical admin found
  #   null                                — timing computed normally

  "orders_only_count":              int,  # SCD orders without admin confirmation
  "pharm_admin_evidence_count":     int,  # confirmed chemical admin lines
  "pharm_ambiguous_mention_count":  int,  # drug mentions that failed admin gating
  "mech_admin_evidence_count":      int,  # confirmed mechanical evidence lines

  "evidence": {
    "pharm": [
      { "ts": ISO-8601, "raw_line_id": string, "snippet": string }
    ],
    "mech": [
      { "ts": ISO-8601, "raw_line_id": string, "snippet": string }
    ],
    "exclusion": [
      { "ts": ISO-8601, "raw_line_id": string, "snippet": string, "reason": string }
    ]
  }
}

------------------------------------------------------------
3. Pharmacologic Admin Gating
------------------------------------------------------------

A line must match BOTH:
  a) A drug keyword (enoxaparin, lovenox, fondaparinux, heparin)
  b) An admin/dispense confirmation signal

Admin CONFIRM signals (any one sufficient):
  - "Given", "Administered", "Medication Administration"
  - "Dose given", "Last dose", "Scheduled dose administered"
  - "Dispense", "Dispensed", "Dispensing"
  - item_type = "MAR" (without exclude signals)

Admin EXCLUDE signals (block unless confirm signal also present):
  - "monitor", "monitoring"
  - "plan"
  - "recommend", "consider", "discuss"
  - "will start", "to start"

Heparin additional rules:
  - SQ dosing ≤ 5000 units → prophylactic
  - > 5000 units or drip/infusion/titration → excluded (THERAPEUTIC_DOSE)
  - flush/lock/heplock → excluded (AMBIGUOUS_HEPARIN_CONTEXT)

Enoxaparin / fondaparinux:
  - Common prophylactic doses (30 mg q12, 40 mg daily) accepted
  - Dose not inferred if absent

Lines matching drug keyword but failing admin gating →
  AMBIGUOUS_NON_ADMIN_MENTION (routed to exclusion evidence).

------------------------------------------------------------
4. Exclusion Priority
------------------------------------------------------------

1. THERAPEUTIC_ANTICOAG (highest — all timing fields null)
2. CHEM_PROPHY_HELD_CONTRAINDICATION (hold/contraindication documented)
3. NO_CHEMICAL_PROPHYLAXIS_EVIDENCE (no confirmed chemical admin found)

------------------------------------------------------------
5. Mechanical Prophylaxis (Informational)
------------------------------------------------------------

SCDs / sequential compression tracked in mech_first_ts for clinical
context.  Does NOT affect dvt_first_ts, delay_hours, or compliance.

Confirmed sources: MAR, nursing notes, flowsheets, explicit
"SCDs on/applied/in place" language.

Orders-only entries (Order ###, [NUR###]) → orders_only_count, routed
to exclusion evidence for traceability.

------------------------------------------------------------
6. Determinism
------------------------------------------------------------

- All outputs are deterministic given the same input.
- raw_line_id = SHA-256[:16] of (source_id|dt|snippet).
- v4 hashes must remain unchanged across runs.
- No randomness, no LLM, no ML.
