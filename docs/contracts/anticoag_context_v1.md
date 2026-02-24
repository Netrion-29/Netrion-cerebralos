# Contract: `anticoag_context_v1`

**Feature key**: `anticoag_context_v1`
**Source rule id**: `anticoag_context_v1`
**Module**: `cerebralos.features.anticoag_context_v1`
**Added**: 2025-06

---

## Purpose

Deterministic extraction of **home/outpatient anticoagulant and antiplatelet
medications** from the "Current Outpatient Medications on File Prior to
Encounter" section of trauma-relevant notes.

This feature supports downstream protocol interpretation (e.g. INR
normalization urgency, TBI anticoag reversal protocols) and daily notes
v5 medication context without performing full med reconciliation.

---

## Output shape

```jsonc
{
  "anticoag_present": "yes" | "no" | "DATA NOT AVAILABLE",
  "antiplatelet_present": "yes" | "no" | "DATA NOT AVAILABLE",
  "home_anticoagulants": [
    {
      "name": "apixaban (ELIQUIS) 5 MG tablet",
      "normalized_name": "apixaban",
      "class": "DOAC",             // DOAC | VKA
      "context": "home_outpatient",
      "discontinued": false,
      "raw_line_id": "<sha256_16>",
      "source_type": "TRAUMA_HP",
      "ts": "2025-01-15T14:30:00",
      "dose": "5 MG",             // optional, only if trivially explicit
      "indication": "Atrial Fibrillation"  // optional, only if in raw text
    }
  ],
  "home_antiplatelets": [
    {
      "name": "aspirin EC (HALFPRIN) 81 MG tablet",
      "normalized_name": "aspirin",
      "class": "antiplatelet",
      "context": "home_outpatient",
      "discontinued": false,
      "raw_line_id": "<sha256_16>",
      "source_type": "TRAUMA_HP",
      "ts": "2025-01-15T14:30:00",
      "dose": "81 MG"            // optional
    }
  ],
  "anticoag_count": 1,
  "antiplatelet_count": 1,
  "source_rule_id": "anticoag_context_v1",
  "evidence": [
    {
      "role": "home_anticoagulant" | "home_antiplatelet",
      "label": "home_apixaban",
      "source_type": "TRAUMA_HP",
      "source_id": "<item_id>",
      "ts": "2025-01-15T14:30:00",
      "raw_line_id": "<sha256_16>",
      "snippet": "• apixaban (ELIQUIS) 5 MG tablet  Take 1 tablet..."
    }
  ],
  "notes": [],
  "warnings": []
}
```

---

## Presence logic

| Condition | `anticoag_present` | `antiplatelet_present` |
|-----------|-------------------|----------------------|
| ≥1 active (non-discontinued) anticoag found | `"yes"` | — |
| Only discontinued anticoag found | `"no"` | — |
| No anticoag med lines matched | `"DATA NOT AVAILABLE"` | — |
| Same logic applies for antiplatelets | — | (symmetric) |

---

## Covered drugs

### Anticoagulants
| Generic | Brand | Class |
|---------|-------|-------|
| apixaban | ELIQUIS | DOAC |
| rivaroxaban | XARELTO | DOAC |
| dabigatran | PRADAXA | DOAC |
| edoxaban | SAVAYSA | DOAC |
| warfarin | COUMADIN | VKA |

### Antiplatelets
| Generic | Brand | Class |
|---------|-------|-------|
| aspirin | HALFPRIN, ASPIRIN LOW DOSE | antiplatelet |
| clopidogrel | PLAVIX | antiplatelet |
| ticagrelor | BRILINTA | antiplatelet |
| prasugrel | EFFIENT | antiplatelet |

---

## Source types scanned

- `TRAUMA_HP`
- `PHYSICIAN_NOTE`
- `ED_NOTE`
- `CONSULT_NOTE`
- `NURSING_NOTE`

---

## Section detection

The extractor looks for sections matching:
```
Current Outpatient Medications on File Prior to Encounter
```

Within that section, medication lines starting with `•` (bullet) are
parsed for known anticoag/antiplatelet drug names.

Section boundary ends at the next clinical header (Allergies, Social Hx,
Surgical Hx, ROS, Physical Exam, etc.).

---

## Edge cases

| Scenario | Behaviour |
|----------|----------|
| `[DISCONTINUED]` prefix on med line | Captured with `discontinued: true`; does NOT count toward `anticoag_present: "yes"` |
| Inpatient-administered meds (not in outpatient section) | Not captured — scope is home/outpatient only |
| Clinical text mentioning "on anticoagulation" | Not captured — only explicit med list entries |
| Duplicate med lines across multiple notes | Deduplicated by `(normalized_name, discontinued)` |
| No outpatient medications section found | `DATA NOT AVAILABLE` for both flags |

---

## Fail-closed guarantees

- Only explicit outpatient medication table entries in known section are captured.
- No NLP, no ML, no clinical inference.
- No dose normalization beyond trivially explicit values.
- Diagnosis mentions alone never trigger extraction.
- Every evidence entry and drug entry carries `raw_line_id`.

---

## Validator checks

- `anticoag_context_v1` registered in `KNOWN_FEATURE_KEYS`
- `evidence[]` entries checked for `raw_line_id`
- `home_anticoagulants[]` entries checked for `raw_line_id`
- `home_antiplatelets[]` entries checked for `raw_line_id`

---

## QA reporter section

```
ANTICOAG CONTEXT v1 QA:
  anticoag_present: yes
  antiplatelet_present: yes
  home_anticoagulants: 1
  home_antiplatelets: 1
  source_rule_id: anticoag_context_v1
    anticoag: apixaban (DOAC) dose=5 MG
    antiplatelet: aspirin (antiplatelet) dose=81 MG
  evidence_count: 2
    [home_anticoagulant] • apixaban (ELIQUIS) 5 MG tablet ...
    [home_antiplatelet] • aspirin EC (HALFPRIN) 81 MG tablet ...
```
