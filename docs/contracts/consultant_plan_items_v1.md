# consultant_plan_items_v1 — Contract

## Feature key
`consultant_plan_items_v1`

## Purpose
Extract explicit consultant plan/recommendation items from consultant
note text within the patient timeline.  Captures what consultants
actually recommended — not just their presence (which is covered by
`consultant_events_v1`).

## Source data
- `consultant_events_v1` (identifies consultant services and timestamps)
- `note_index_events_v1` (maps timestamps to services/authors/raw_line_ids)
- Timeline items in `patient_days_v1.json` (CONSULT_NOTE and PHYSICIAN_NOTE
  items from `days[date].items[]`)

## Detection strategy

### Matching timeline items to consultant services
1. Extract (date_raw, time_raw, service) from `note_index_events_v1` entries.
2. For each consultant service in `consultant_events_v1`, collect the
   timestamps from evidence snippets.
3. Find timeline items (CONSULT_NOTE or PHYSICIAN_NOTE) whose ISO dt
   matches the (month, day, hour, minute) of a note_index entry.
4. Service attribution comes from the note_index entry, not text inference.

### Plan section detection (explicit headers only)
The following headers are used to identify plan/recommendation sections:

| Header pattern | Example |
|---|---|
| `Assessment and Plan` | `Assessment and Plan:` |
| `Assessment & Plan` | `Assessment & Plan` |
| `Assessment/Plan` | `Assessment/Plan:  This is a…` |
| `A/P` | `A/P: This is a 88 y.o. female…` |
| `Plan` | `Plan:` |
| `Recommendations` / `Recommendation` | `Recommendations` |

Headers are matched case-insensitively.  Optional trailing colon or
period is consumed.  Inline content after the header on the same line
is captured.

### Plan section termination
Extraction stops at:
- Next major section header (Subjective, Objective, Physical Exam,
  ROS, HPI, Chief Complaint, PMH, Medications, Allergies, Social
  History, Family History, Vital Signs, Labs, Imaging, Follow up,
  Disposition, Revision/Routing History, Physician Attestation,
  Reason for Admission/Hospitalization)
- Separator lines (`___`, `---`, `===`, 3+ chars)
- Electronic signature markers (`Electronically signed`, `Signed by`,
  `Authenticated by`)
- Addendum markers (`Addendum:`)

### Noise filtering (lines excluded from plan items)
| Category | Examples |
|---|---|
| Attestation blocks | "I have seen and examined patient…" |
| Credential/signature lines | "Roberto C Iglesias, MD" |
| Date-only lines | "1/1/2026" |
| Time-only lines | "6:00 PM" |
| Seen-at lines | "Seen at 0540" |
| MyChart / disclaimer paragraphs | Contains "MyChart" or "Disclaimer" |
| MDM complexity grids | "Diagnoses and Treatment Options Considered" |
| "untitled image" markers | |
| Courtesy/thanks lines | "Thank you for allowing us…" |
| Pager/office phone | "Pager: 812-428-1792" |
| Order references | "Order: 466673714" |
| Service/title standalone lines | "Deaconess Clinic", "Available on Haiku" |
| Code status lines | "Code, full", "Full code status" |
| Lines ≤ 2 chars | |

### Item type classification (deterministic, keyword-based)
| Type | Trigger keywords |
|---|---|
| `medication` | start, continue, resume, d/c, titrate, specific drug names |
| `imaging` | CT, MRI, X-ray, XR, ECHO, TTE, ultrasound |
| `procedure` | surgery, operative, ORIF, debridement, chest tube |
| `follow-up` | follow-up, f/u, return to clinic, outpatient |
| `activity` | weight-bearing, NWB, WBAT, mobilize, PT eval, OT eval, sling, brace |
| `discharge` | discharge, d/c from, disposition, SNF, rehab facility |
| `recommendation` | Default when no keyword matches |

### Deduplication
Identical (service, item_text_normalized_lowercase) pairs are
deduplicated.  Duplicates are logged as warnings.

## Output schema
```json
{
  "items": [
    {
      "service": "Otolaryngology",
      "ts": "2026-01-01T10:20:00",
      "author_name": "Chacko, Chris E",
      "item_text": "Nonoperative management of nasal fracture",
      "item_type": "recommendation",
      "evidence": [
        {
          "role": "consultant_plan_item",
          "snippet": "[Otolaryngology] Assessment and Plan:: Non...",
          "raw_line_id": "<sha256>"
        }
      ]
    }
  ],
  "item_count": 5,
  "services_with_plan_items": ["Internal Medicine", "Otolaryngology"],
  "source_rule_id": "consultant_plan_from_note_text"
                   | "no_consultant_events"
                   | "no_plan_sections_found",
  "warnings": [],
  "notes": []
}
```

## Fail-closed rules
| Condition | consultant plan output |
|---|---|
| No `consultant_events_v1` or consultant_present ≠ "yes" | items=[], source_rule_id="no_consultant_events" |
| Consultant events present but no plan sections found | items=[], source_rule_id="no_plan_sections_found" |
| Plan sections found and items parsed | source_rule_id="consultant_plan_from_note_text" |

## Validation patients
| Patient | Expected |
|---|---|
| Roscella_Weatherly | 2 consult notes (Hospitalist + ENT), plan items from both |
| Lee_Woodard | 3 consult notes (Ortho + Wound/Ostomy + Hospitalist), rich plan content |
| Margaret_Rudd | 3 consult notes (Hospitalist + Neurosurgery + Orthopedics) |
| Anna_Dennis | DNA (no note_index_events, older format) |

## Relationship to `consultant_events_v1`
- `consultant_events_v1` answers: *which* consultant services were involved?
- `consultant_plan_items_v1` answers: *what* did those consultants recommend?
- This feature consumes `consultant_events_v1` for service identification.
- Service names and timestamps are aligned between both features.

## Intentional exclusions
- Does not extract plan items from non-consultant notes (ED Notes,
  Trauma H&P, Discharge Summary — those are handled by `note_sections_v1`
  and `impression_plan_drift_v1`)
- Does not infer recommendations from narrative text without explicit
  plan section headers
- Does not classify plan items by clinical urgency or priority
- Does not extract structured medication details (dose, route, frequency)
