# spine_clearance_v1 — Feature Layer Contract

**Feature key:** `spine_clearance_v1`
**Source rule ID:** `spine_clearance_v1`
**Module:** `cerebralos/features/spine_clearance_v1.py`

## Output Shape

```json
{
  "clearance_status": "YES | NO | DATA NOT AVAILABLE",
  "clearance_ts": "<ISO timestamp or null>",
  "method": "ORDER | CLINICAL | DATA NOT AVAILABLE",
  "regions": [
    {
      "name": "cervical | thoracolumbar",
      "clearance": "YES | NO | UNKNOWN",
      "ordered_on": "<ISO timestamp or null>"
    }
  ],
  "collar_status": "PRESENT | REMOVED | DATA NOT AVAILABLE",
  "order_count": 0,
  "cleared_phrase_count": 0,
  "not_cleared_phrase_count": 0,
  "evidence": [
    {
      "role": "order_question_block | cleared_phrase | not_cleared_phrase",
      "snippet": "<text excerpt>",
      "raw_line_id": "<traceability id>"
    }
  ],
  "warnings": [],
  "notes": [],
  "source_rule_id": "spine_clearance_v1"
}
```

## Extraction Strategies

### Strategy A: Order Questions (precedence)
- Parses Epic "Order Questions" blocks for `Cervical Spine Clearance` and
  `Thoracic/Spine Lumbar Clearance` answers (YES/NO).
- Also detects inline format: `Spine Clearance Cervical Spine Clearance: Yes; Thoracic/Spine Lumbar Clearance: No`.
- Latest timestamp per region wins when multiple orders exist.
- Both regions YES → `clearance_status=YES`.
- Any region NO → `clearance_status=NO`.

### Strategy B: Phrase-based clinical text (fallback)
- 12 cleared phrases (e.g., "spine cleared", "collar cleared", "remove collar").
- 9 not-cleared phrases (e.g., "continue collar", "spine not cleared").
- When conflicting signals exist, latest timestamp wins; ties → fail-closed to NO.

## Precedence Rules
1. Order-based results take full precedence over phrase-based.
2. Negative imaging alone NEVER produces clearance.
3. T/L clearance only from Order Questions or explicit T/L phrases.
4. Ambiguous or conflicting signals → fail-closed to NO.

## Collar Status (independent)
- `PRESENT`: collar in place / applied / on.
- `REMOVED`: collar removed / discontinued.
- `DATA NOT AVAILABLE`: no collar documentation.

## Green-Card Overlap Note
This feature-layer module is **independent** from the green-card spine
clearance logic in `extract_green_card_adjuncts_v1.py`. Both use similar
regex patterns but operate on different data streams:
- Green card: `green_card.spine_clearance` (from classified evidence items)
- Feature layer: `features.spine_clearance_v1` (from timeline items)
