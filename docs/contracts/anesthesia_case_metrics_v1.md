# Anesthesia Case Metrics v1 — Output Contract

## Feature Key
`anesthesia_case_metrics_v1`

## Source Rule ID
`anesthesia_case_metrics_v1`

## Purpose
Deterministic extraction of per-case anesthesia physiologic metrics,
airway details, temperature readings, EBL, and OR hypothermia flag
from anesthesia-record-style timeline items.

## Consumed Item Kinds

| Kind                        | Data Extracted                                      |
|-----------------------------|-----------------------------------------------------|
| `ANESTHESIA_PREPROCEDURE`   | ASA, Mallampati, anesthesia plan, diagnosis, temp   |
| `ANESTHESIA_PROCEDURE`      | Airway device/size/difficulty/attempts/verification |
| `ANESTHESIA_POSTPROCEDURE`  | Anesthesia type, post-op temp, condition            |
| `ANESTHESIA_FOLLOWUP`       | PACU temp, consciousness, pain, complications       |
| `ANESTHESIA_CONSULT`        | Consult details (e.g. nerve block request)          |
| `OP_NOTE`                   | EBL (cross-referenced by day)                       |

## Output Shape

```json
{
  "cases": [
    {
      "case_index": 1,
      "case_day": "2026-01-10",
      "case_label": "Metatarsal fracture",
      "anesthesia_type": "General",
      "asa_status": "3",
      "mallampati": "II",
      "preop_diagnosis": "Metatarsal fracture",
      "start_ts": "2026-01-10T08:00:00",
      "stop_ts": "2026-01-10T10:30:00",
      "airway": {
        "device": "LMA",
        "size": "5",
        "difficulty": "Easy",
        "atraumatic": "Yes",
        "attempts": "1",
        "placement_verification": "Auscultation and Capnometry"
      },
      "temps": [
        {"value_f": 98.4, "source_phase": "postprocedure", "raw_line_id": "..."},
        {"value_f": 98.6, "source_phase": "followup", "raw_line_id": "..."}
      ],
      "min_temp_f": 98.4,
      "or_hypothermia_flag": false,
      "ebl_ml": null,
      "ebl_raw": "DATA NOT AVAILABLE",
      "evidence": [...]
    }
  ],
  "case_count": 1,
  "or_hypothermia_any": false,
  "flags": [],
  "warnings": [],
  "notes": [],
  "evidence": [...],
  "source_rule_id": "anesthesia_case_metrics_v1"
}
```

## OR Hypothermia Flag

| Field                   | Description                                              |
|-------------------------|----------------------------------------------------------|
| `or_hypothermia_flag`   | Per-case: `true` if any periop temp < 96.8 °F (36.0 °C) |
| `or_hypothermia_any`    | Top-level: `true` if ANY case flagged hypothermic        |

**Threshold:** < 96.8 °F (< 36.0 °C) — standard perioperative hypothermia
definition per ASPAN/ASA guidelines.

**Temp sources:** Only POSTPROCEDURE and FOLLOWUP temps are considered
for hypothermia flag (pre-procedure is baseline).

**Fail-closed:** When no temps available, flag is `null` (not false).

## Case Grouping

ANESTHESIA items are grouped by calendar day.  All items on the same day
belong to the same logical case.

## Overlap with `procedure_operatives_v1`

| Field             | procedure_operatives_v1  | anesthesia_case_metrics_v1  |
|-------------------|--------------------------|-----------------------------|
| `anesthesia_type` | Event metadata           | Case-level detail           |
| `asa_status`      | Event metadata           | Case-level detail           |
| Airway details    | Not extracted            | Full airway struct          |
| Temperatures      | Not extracted            | All periop temps            |
| EBL               | Not extracted            | Numeric + raw               |
| Hypothermia flag  | Not extracted            | Deterministic bool/null     |
| Mallampati        | Not extracted            | Extracted                   |

**Precedence:** `procedure_operatives_v1` is the event-timeline source
of truth for anesthesia_type and asa_status as event metadata.
`anesthesia_case_metrics_v1` provides case-level metrics detail.
Both are additive — downstream consumers should prefer whichever shape
matches their need.

## Fields Not Extracted (Fail-Closed)

| Field           | Reason                                                  |
|-----------------|---------------------------------------------------------|
| `urine_ml`      | Not present as structured field in current anesthesia data |
| `intraop_meds`  | PREPROCEDURE lists outpatient meds, not intra-op drugs  |
| `case_duration`  | No explicit start/stop fields; `start_ts`/`stop_ts` are item-level timestamps |

## Evidence Requirements

Every evidence entry must have `raw_line_id` (enforced by validator).
