# N4-P1 AKI (Event 01) UTD Reduction Audit — v1

| Field     | Value                                                    |
|-----------|----------------------------------------------------------|
| Date      | 2026-03-04                                               |
| Branch    | `tier2/n4-p1-aki-utd-reduction-v1`                       |
| Baseline  | `1156d7d` (main, after PR #140)                          |
| Scope     | Event 01 (AKI) UTD reduction — mapper-only, fail-closed  |
| Result    | **doc-note-only** — no safe mapper changes identified    |

---

## 1. Baseline Distribution (post-N3, fresh run)

| Outcome             | Count |
|---------------------|-------|
| YES                 | 0     |
| NO                  | 29    |
| UNABLE_TO_DETERMINE | 4     |
| Total               | 33    |

> Note: roadmap doc estimated UTD=5 after N3-P6 (PR #138); fresh run shows UTD=4.
> The discrepancy is likely from a re-run after intermediate mapper state.

---

## 2. UTD Patient Analysis

### Barbara_Burgdorf

**Evidence:** PHYSICIAN_NOTE L910 / L911 (identical content in multiple note copies):
```
L910: • Acute kidney injury   08/15/2021
L911:    hospital stay due to dehydration, acute kidney injury after chemotherapy, also had UTI
```

**Candidate pattern:** `\bacute\s+kidney\s+injury\s+after\b` (hits L911)

**Verdict: UNSAFE — do not add.**

L910/L911 appear in an Epic problem list / "Diagnosis Date" section. The date
`08/15/2021` is the first-diagnosed date for this AKI episode. The phrase
"hospital stay due to dehydration, acute kidney injury after chemotherapy"
is a narrative description of a *past* hospitalization event. If the current
admission is a different year, adding this pattern would yield a false positive
(historical AKI incorrectly classified as hospital-acquired).

**UTD is the correct outcome.** The engine cannot distinguish whether this is
POA or hospital-acquired without explicit current-admission temporal language.

---

### Carlton_Van_Ness

**Evidence:** Multiple LAB entries:
```
L4196: Acute kidney injury        (no context / standalone)
L7968: Acute kidney injury
L7969:   Improved. Continue to monitor intake and output and renal profile.
L8607: Acute kidney injury
L8608:   Improved. Continue to monitor intake and output and renal profile.
```

Historical PMH entry: `L5788: Acute kidney injury  11/30/2019`

**Candidate patterns evaluated:** None viable.

The monitoring language ("Improved. Continue to monitor...") confirms active
management of AKI during this admission but does not establish that it
*developed* after arrival vs. being present on arrival and now improving.
No phrase like "developed", "new AKI", "AKI onset", or "hospital-acquired" is
present in any AKI context window.

**UTD is the correct outcome.** Genuine clinical ambiguity — AKI is active
but temporal onset vs. arrival is undocumented in accessible note text.

---

### David_Gross

**Evidence:** CONSULT_NOTE (Pulmonology) L17548:
```
AKI m/l 2/2 to volume/hypoperfusion related to above
```
Context: Assessment/Impression section of a pulmonology consult note,
timestamp `2025-12-17T20:58:00` (arrival: `2025-12-17T00:00:00`).

**Candidate pattern:** `\bAKI\s+(m/?l\s+)?2/2\s+to\b`

**Why it's unreachable — section detection issue:**

The `build_patientfacts_from_txt.py` `_detect_source_type` function fires on
any line containing the word "IMAGING" (pattern `r"IMAGING"` matches as
substring). Earlier in the same consult note, the HPI contains:

> "Imaging performed - CTH no acute process/bleed, CTPE - no acute PE..."

This line causes `_detect_source_type` to switch the current source type to
`SourceType.IMAGING` mid-note. All subsequent lines — including the
Assessment/Impression section with "AKI m/l 2/2 to volume/hypoperfusion" —
are tagged as `IMAGING` evidence.

The `aki_after_arrival` gate has `allowed_sources: ["PHYSICIAN_NOTE", "LAB"]`.
`IMAGING` is excluded, so the pattern match is never reached.

**Pattern scan result:** `aki_2/2_to` hits only David_Gross in the full
33-patient cohort (zero FP risk from the pattern itself), but the match is in
IMAGING source type → gate never sees it.

**UTD is the current outcome (system limitation, not clinical ambiguity).**

**Deferred fix required (separate PR):** Tighten `_detect_source_type` to
require section-header context (e.g., line is mostly uppercase, matches a
known Epic section format like `[SECTION_TYPE]` or `SECTION_TYPE:` at
line start) rather than free-text substring match. This would prevent
"Imaging performed" in a sentence from resetting the source type.

After fixing detection: adding `\bAKI\s+(m/?l\s+)?2/2\s+to\b` to `aki_onset`
AND `CONSULT_NOTE` to `aki_after_arrival.allowed_sources` would convert
David_Gross from UTD to YES with no FP risk (zero other cohort hits).

---

### Gary_Linder

**Evidence:** Only PMH-tier mentions:
```
L22:  PMH of AKI, COPD, GERD, HLD, HTN and back pain who prese...
L713: PMH of AKI, COPD, GERD, HLD, HTN and back pain who presents...
L731: AKI (acute kidney injury)   11/07/2021
L1949: AKI (acute kidney injury)  11/07/2021
```

The L22/L713 lines are filtered by `aki_negation_noise` (`\bPMH\b.*\bAKI\b`
and `\bpast\s+(medical\s+)?history\b.*\bAKI\b`). However, L731 and L1949 are
in LAB and DISCHARGE sections, and pass `aki_dx` because they match `\bAKI\b`.

The LAB/DISCHARGE "AKI (acute kidney injury)" entries lack any temporal or
contextual language on the same line or in the surrounding window that could
confirm onset after arrival. These entries appear to be problem-list style
entries added to lab/discharge records — the same AKI episode documented
across multiple note types.

**UTD is the correct outcome.** Previously documented as a known deferred
residual in the N3 phase. The underlying limitation is that NTDS detection
cannot distinguish a "problem list imported into lab/discharge" entry from an
active in-progress event without contextual sentences.

---

## 3. Safety Gate

| Patient          | Safe pattern available? | Evidence source accessible? | Action |
|------------------|-------------------------|-----------------------------|--------|
| Barbara_Burgdorf | Pattern exists BUT FP risk (historical PMH list entry) | PHYSICIAN_NOTE (accessible) | **Deferred — POA ambiguity** |
| Carlton_Van_Ness | No viable temporal pattern | LAB (accessible) | **Deferred — no temporal language** |
| David_Gross      | Pattern exists, zero FP | CONSULT_NOTE (inaccessible — misclassified as IMAGING) | **Deferred — section detection fix needed** |
| Gary_Linder      | No viable temporal pattern | LAB/DISCHARGE (accessible) | **Deferred — problem list only** |

**Safety gate verdict: BLOCKED.** No changes that satisfy all conditions:
- Mapper-only (no engine modifications)
- Fail-closed
- No YES inflation risk

---

## 4. Deferred Items

| Item | Blocker | Priority |
|------|---------|----------|
| Fix `_detect_source_type` to require line-start / header-format context | `build_patientfacts_from_txt.py` change | **High** — enables David_Gross fix safely |
| After detection fix: add `\bAKI\s+(m/?l\s+)?2/2\s+to\b` to `aki_onset` | Depends on detection fix | High |
| After detection fix: add `CONSULT_NOTE` to `aki_after_arrival.allowed_sources` | Depends on detection fix | High |
| Investigate Barbara_Burgdorf — determine if 08/15/2021 is current-admission date | Clinical review | Low |
| Investigate Carlton_Van_Ness — retrieve note with explicit AKI timing language | Clinical review | Low |
| Gary_Linder — evaluate PMH context separation in LAB/DISCHARGE entries | Rule design | Low |

---

## 5. N4-P1 Classification

```
classification: doc-note-only
reason: No mapper-only change available that is safe, fail-closed, and
        does not require engine-subsystem modifications.
        Residuals are correctly classified as UTD.
        Primary actionable item is a build_patientfacts_from_txt.py
        section-detection fix (separate PR, not in scope here).
```

_End of audit._
