# Mechanism of Injury + Body Region Extraction v1 — Contract

| Field   | Value                                              |
|---------|----------------------------------------------------|
| Module  | `cerebralos/features/mechanism_region_v1.py`        |
| Version | v1                                                 |
| Date    | 2026-02-22                                         |
| Roadmap | Extractor coverage — mechanism/body region support |

---

## Purpose

Deterministic extraction of:

1. **Injury mechanism** — canonical label(s) describing how the trauma
   occurred (e.g., fall, MVC, GSW, stab, crush, industrial).
2. **Body region** — anatomical region labels relevant to trauma
   protocols (e.g., head, neck, chest, abdomen, pelvis, spine, extremity).

This feature enables future protocol evaluation by providing structured
mechanism and region data from arrival documentation.

---

## Output Key

`features.mechanism_region_v1` in `patient_features_v1.json`.

---

## Output Schema

```json
{
  "mechanism_present": "yes | no | DATA NOT AVAILABLE",
  "mechanism_primary": "<canonical label> | null",
  "mechanism_labels": ["fall", "..."],
  "penetrating_mechanism": true | false | null,
  "body_region_present": "yes | no | DATA NOT AVAILABLE",
  "body_region_labels": ["head", "chest", "..."],
  "source_rule_id": "trauma_hp_hpi | ed_note_hpi | physician_note_hpi | consult_note_hpi | no_qualifying_source",
  "evidence": [
    {
      "raw_line_id": "<sha256[:16]>",
      "source": "TRAUMA_HP | ED_NOTE | ...",
      "ts": "<ISO datetime | null>",
      "snippet": "<context text>",
      "role": "mechanism | body_region",
      "label": "<canonical label>"
    }
  ],
  "notes": ["..."],
  "warnings": ["..."]
}
```

---

## Source Precedence

Sources are prioritized in this order (first with matches wins):

1. **TRAUMA_HP** — HPI section for mechanism; HPI + Secondary Survey for body regions.
2. **ED_NOTE** — fallback if TRAUMA_HP absent.
3. **PHYSICIAN_NOTE** — fallback.
4. **CONSULT_NOTE** — lowest priority.

Within each source type, the earliest timestamp wins.

---

## Mechanism Labels (Canonical)

| Label              | Example Patterns                                    | Penetrating |
|--------------------|-----------------------------------------------------|-------------|
| `fall`             | "presents after a fall", "fell at home", "found down" | No          |
| `mvc`              | MVC, MVA, motor vehicle crash, rollover, head-on    | No          |
| `mcc`              | MCC, motorcycle crash                               | No          |
| `bicycle`          | bicycle crash, bike accident                        | No          |
| `pedestrian_struck`| pedestrian struck, struck by vehicle                | No          |
| `atv`              | ATV crash, ATV rollover                             | No          |
| `gsw`              | GSW, gunshot wound                                  | Yes         |
| `stab`             | stab wound, stabbing                                | Yes         |
| `impalement`       | impaled, impalement                                 | Yes         |
| `crush`            | crush injury, trapped between                       | No          |
| `industrial`       | auger, grain bin, mining accident, machinery        | No          |
| `burn`             | burn, thermal injury, scald                         | No          |
| `assault`          | assault, attacked, altercation, beaten              | No          |
| `blast`            | blast injury, explosion                             | No          |
| `animal`           | horse kick                                          | No          |
| `hanging`          | hanging                                             | No          |
| `strangulation`    | strangulation                                       | No          |
| `drowning`         | drowning, submersion                                | No          |

---

## Body Region Labels (Canonical)

| Label       | Example Patterns                                          |
|-------------|-----------------------------------------------------------|
| `head`      | head, skull, TBI, subdural, forehead, cranial             |
| `face`      | face, facial, mandible, orbit, Le Fort                    |
| `neck`      | neck, cervical, c-spine                                   |
| `chest`     | chest, thorax, rib, sternum, pneumothorax, hemothorax     |
| `abdomen`   | abdomen, spleen, liver, kidney, bowel, flank              |
| `pelvis`    | pelvis, acetabulum, pubic, sacrum, iliac                  |
| `spine`     | spine, vertebra, t-spine, l-spine, thoracolumbar          |
| `extremity` | extremity, femur, tibia, humerus, shoulder, hip, RLE, LUE |

---

## Fail-Closed Behavior

| Condition                                            | Result                                    |
|------------------------------------------------------|-------------------------------------------|
| No qualifying source items                           | `mechanism_present = "DATA NOT AVAILABLE"` |
| Source exists, no mechanism pattern matched           | `mechanism_present = "no"`                 |
| History/chronic context detected around match         | Match excluded + note added               |
| Source exists, no body region text matched            | `body_region_present = "no"`              |

---

## History Exclusion

Mechanism matches in history/chronic context are excluded to avoid
overmatching:

- "history of fall" / "h/o MVC" / "PMH of previous fall"
- "previous SDH from fall"

These are logged as notes (not errors) for audit visibility.

---

## Evidence Traceability

Every evidence entry includes:

- `raw_line_id` — SHA-256 hash (16-char prefix) of source coordinates
- `source` — item type (TRAUMA_HP, ED_NOTE, etc.)
- `ts` — item timestamp
- `snippet` — context text around the match
- `role` — "mechanism" or "body_region"
- `label` — canonical label matched

---

## Design Constraints

- Deterministic, fail-closed.
- No LLM, no ML, no clinical inference.
- This is NOT radiology findings extraction.
- This is NOT injury severity scoring.
- This is NOT protocol regex dictionary implementation.
