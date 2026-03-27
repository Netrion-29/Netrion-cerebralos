# Contributing to CerebralOS

## Ground Rules

1. **One PR = one goal.** Do not bundle unrelated changes.
2. **Deterministic, fail-closed logic only.** Missing data must produce
   `INDETERMINATE` or `NOT_EVALUATED` — never a guess.
3. **No clinical inference.** The system reports evidence; it does not
   diagnose or recommend.

## Protected Code

Do not modify the following without explicit instruction:

- `cerebralos/ntds_logic/engine.py`
- `cerebralos/protocol_engine/engine.py`
- Renderer outputs (v3/v4)

## Schema Changes

If a PR changes any schema (JSON structure, top-level keys, file naming):

- Update docs, validators, and all consumers in the **same PR**.
- Do not make silent schema changes.

## Evidence Contract

Every stored evidence item must include `raw_line_id` linking back to the
source line in the patient record.

## PHI / Patient Data

- **Never commit PHI.** Raw patient files (`data_raw/`), generated outputs
  (`outputs/`), and any patient-identifying content must stay local.
- Do not reference real patient names in code, comments, commit messages,
  PR descriptions, or issue text.
- Local scratch files (`_tmp_*`, one-off scripts) must remain untracked.
- Pre-commit hooks block staging of local-only PHI paths and scan staged
  content for obvious PHI markers (MRN, SSN, phone numbers, etc.). If a
  hook fires on a false positive, review the flagged lines and use
  `git commit --no-verify` to override.

## Before You Submit

Run the completion gate and confirm it passes:

```bash
./scripts/gate_pr.sh
```

A PR is not ready until the gate passes cleanly.
