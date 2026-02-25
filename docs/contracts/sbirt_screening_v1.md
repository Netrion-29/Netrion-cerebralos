# Contract: sbirt_screening_v1

**Module**: `cerebralos/features/sbirt_screening_v1.py`
**Feature key**: `sbirt_screening_v1`
**Replaces**: `sbirt_scores_v1` (score-only extraction, renamed this PR)
**Branch**: `tier1/sbirt-scores-v1`
**Status**: Active

---

## Purpose

Deterministic extraction of structured SBIRT screening data from patient
timeline items. Captures explicit numeric scores, question-level Yes/No
responses, and screening metadata (refusal, substance use admission,
completion status). Protocol-ready output for the Deaconess SBIRT
protocol (`SCREENING_OF_THE_TRAUMA_PATIENT_FOR_ALCOHOL_ANDOR_DRUG_USE_SBIRT`).

---

## Input

| Param | Type | Description |
|-------|------|-------------|
| `pat_features` | `Dict[str, Any]` | Partial patient features (API compat) |
| `days_data` | `Dict[str, Any]` | Full `patient_days_v1.json` dict |

### Scanned source types

`NURSING_NOTE`, `PHYSICIAN_NOTE`, `ED_NOTE`, `CARE_TEAM`, `SOCIAL_WORK`

---

## Output Schema

```jsonc
{
  "sbirt_screening_present": "yes" | "no" | "refused" | "DATA NOT AVAILABLE",
  "instruments_detected": ["audit_c", "dast_10", "sbirt_flowsheet", ...],

  "audit_c": {
    "explicit_score": {                // null if not documented
      "value": 4,                      // integer 0–12
      "ts": "2025-01-15T14:30:00",
      "source_rule_id": "sbirt_section_audit_c" | "flowsheet_audit_c",
      "evidence": [{ "raw_line_id": "...", "source": "...", "ts": "...", "snippet": "...", "role": "score" }]
    },
    "responses_present": true,
    "responses": [
      {
        "question_id": "audit_c_q1",   // q1/q2/q3
        "question_text": "How often do you have a drink containing alcohol?",
        "answer": "4 or more times a week",
        "instrument": "audit_c",
        "raw_line_id": "abc123..."
      }
    ],
    "completion_status": "score_documented" | "responses_complete" | "responses_only" | "not_performed"
  },

  "dast_10": {
    "explicit_score": null,            // only if explicit summary; NEVER summed
    "responses_present": false,
    "responses": [],
    "completion_status": "not_performed" | "score_documented" | "responses_only"
  },

  "cage": {
    "explicit_score": null,
    "responses_present": false,
    "responses": [],
    "completion_status": "not_performed" | "score_documented"
  },

  "flowsheet_responses": [             // sbirt_flowsheet instrument responses
    {
      "question_id": "injury",
      "question_text": "Does the patient have an injury?",
      "answer": "Yes",
      "instrument": "sbirt_flowsheet",
      "flowsheet_row_ts": "12/18/25 1445",
      "raw_line_id": "def456..."
    }
  ],

  "refusal_documented": false,
  "refusal_evidence": [],

  "substance_use_admission_documented": false,
  "substance_use_admission_evidence": [],

  "evidence": [                        // all evidence entries (scores + responses + refusal + admission)
    {
      "raw_line_id": "...",            // REQUIRED — sha256[:16] of source coordinates
      "source": "CARE_TEAM",
      "ts": "2025-01-15T14:30:00",
      "snippet": "...",
      "role": "score" | "response" | "refusal" | "admission",
      "label": "audit_c" | "audit_c_q1" | "injury" | ...
    }
  ],

  "notes": [],
  "warnings": []
}
```

---

## Fail-Closed Rules

| Rule | Description |
|------|-------------|
| **No score inference** | Scores come only from explicit `Score: N` patterns |
| **No DAST-10 summation** | Individual DAST-10 answers are NEVER summed to produce a score |
| **No qualitative scores** | "positive screen", "high risk" text → NOT a numeric score |
| **Blank flowsheet cells** | `—`, `-`, `--`, `N/A`, empty → skipped, not treated as answers |
| **Nurse markers stripped** | Trailing single letter in flowsheet values ("Yes A" → "Yes") |
| **No clinical inference** | No LLM, no ML, no probabilistic methods |
| **First-found-wins** | Timeline-ordered; first reliable score per instrument wins |
| **Evidence traceability** | Every extracted datum has a `raw_line_id` |

---

## Data Patterns

### Pattern A — Narrative Consult Note (inline Q&A)

Found in `CARE_TEAM` or `SOCIAL_WORK` items with SBIRT consult sections.
Single-line format: `Question?: Answer`

Example:
```
How often do you have a drink containing alcohol?: 4 or more times a week
How many standard drinks containing alcohol do you have on a typical day?: 0 to 2 drinks
How often do you have six or more drinks on one occasion?: Never
Audit-C Score: 4
```

**Patients**: Barbara_Burgdorf (score=4), Robert_Sauer (score=6), Susan_Barker (score=0)

### Pattern B — Flowsheet (tab-delimited)

Found in `NURSING_NOTE` items with tab-delimited table format.
- **Short form** (4 columns): injury, drug_use, alcohol_testing, alcohol_history
- **Long form** (8 columns): adds audit_c_q1, audit_c_q2, audit_c_q3, audit_c_score

Columns are identified by pattern matching, not position (handles reordering).

**Patients**: Larry_Corne, Timothy_Cowan, William_Simmons (short form); Valerie_Parker (long form)

### Pattern B2 — Dos-format Flowsheet History (v2 addition)

Same tab-delimited structure as Pattern B but found in **dos-format**
patient files inside standalone "Flowsheet History" sections that were
previously not captured by the ingestion pipeline.

Key differences from standard Pattern B:
- **Parenthetical question variants**: e.g. `"Have you used drugs other
  than those required for medical reasons? (Or did the paient test
  positive for un-prescribed drug use?)"` — the prefix match still
  works because `_FLOWSHEET_Q_PATTERNS` use `re.search` against
  the full column header.
- **Em-dash blanks (U+2014)**: AUDIT-C columns may contain `—` instead
  of standard dash `–` or hyphen `-`. The `_is_flowsheet_blank()`
  helper already handles this character.
- **Nurse marker suffix**: Values like `"Yes A"`, `"No A"` — trailing
  single-letter marker stripped during extraction (unchanged logic).

**Ingestion change**: Added a `SBIRT_FLOWSHEET` handler to
`_parse_supplemental_dos()` in `cerebralos/ingest/parse_patient_txt.py`.
This handler scans for "Flowsheet History" headings, detects
tab-delimited header rows containing SBIRT question signatures, and
emits evidence items as `kind="NURSING_NOTE"` so the existing SBIRT
feature extractor can process them without modification.

**Patients**: Lee_Woodard (long form, AUDIT-C columns blank/em-dash)

---

## Completion Status Values

| Status | Meaning |
|--------|---------|
| `not_performed` | No data found for this instrument |
| `score_documented` | Explicit numeric score found |
| `responses_complete` | All expected questions answered (AUDIT-C: 3/3) |
| `responses_only` | Some responses but no explicit score; partial if < expected count |

---

## Validation

- `KNOWN_FEATURE_KEYS` includes `"sbirt_screening_v1"`
- All `evidence[]` entries must have `raw_line_id`
- QA report section: `SBIRT SCREENING v1 QA`

---

## Test Coverage

- Regex patterns for all 3 score types
- Narrative Q&A extraction (Pattern A)
- Flowsheet Q&A extraction (Pattern B)
- Nurse marker stripping
- Refusal/admission detection
- Completion status logic
- Real-patient validation (4+ SBIRT patients + 1 negative control)
- Dos-format variant (Pattern B2): parenthetical phrasing, em-dash blanks,
  nurse markers — 6 unit tests + 5 real-patient regression tests (Lee Woodard)
