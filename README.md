# Netrion Systems — CerebralOS
# Netrion Systems — The Vision of Trauma Excellence
## CerebralOS

CerebralOS is a deterministic trauma governance system built for single-user PI workflows from raw Epic text exports.

Core rules:
- Fail-closed: missing required data → INDETERMINATE / NOT_EVALUATED (never guessed).
- No invented data. No smoothing.
- Outputs must include evidence receipts (source, timestamp/line, excerpt).
- PHI must never be committed to Git.

Folder rules:
- data_raw/ contains raw Epic .txt (PHI) — NEVER commit
- rules/ contains versioned Deaconess protocols + NTDS definitions
- outputs/ contains generated artifacts (prefer de-identified)
cat > docs/build_plan_locked_v1.json << 'EOF'
{
  "meta": {
    "system": "Netrion Systems",
    "product": "CerebralOS",
    "version": "1.0.0",
    "python": "3.14.2",
    "git": "2.39.2 (Apple Git-143)"
  },
  "principles": [
    "Deterministic code is the authority",
    "Fail-closed; never infer missing facts",
    "Every YES requires evidence receipts",
    "Rules live in versioned JSON",
    "ChatGPT and Copilot assist but are not sources of truth"
  ],
  "execution_order": [
    "Define schemas (protocols + NTDS)",
    "Build validators",
    "Extract Deaconess protocols into JSON",
    "Implement protocol engine",
    "Port/finish NTDS engine",
    "Build packet outputs (green card + daily notes + timeline)"
  ]
}
EOF

## PI RN Casefile — Quick Start

Generate a single-patient HTML casefile (the primary PI RN review artifact):

```bash
# One command — runs full pipeline + opens casefile in browser
./scripts/run_casefile_v1.sh "Betty Roll"
```

Or run interactively (prompts for patient name):

```bash
./scripts/run_casefile_v1.sh
```

**VS Code**: Run the task `PI RN Casefile — Run Patient` (Ctrl+Shift+P → Tasks: Run Task).

The casefile is written to `outputs/casefile/<Slug>/casefile_v1.html` and opens
automatically in the default browser. Set `CEREBRAL_NO_OPEN=1` to suppress auto-open.

## Patient Hub — Quick Start

Generate a local patient index that links to all processed casefiles:

```bash
./scripts/run_casefile_hub_v1.sh
```

The hub is written to `outputs/casefile/hub_v1.html` and opens automatically.
It reads existing `patient_bundle_v1.json` files — run the casefile pipeline for
one or more patients first.

## Local Scratch Policy

To keep PRs auditable and deterministic:

- Never stage or commit local scratch files such as `_tmp_*.py`, `_validate_*.py`, or `docs/handoffs/`.
- Keep exploratory local tests untracked unless they are promoted to a real CI-backed test.
- Before commit, verify staged scope with:
  - `git diff --name-only`
  - `git diff --stat`
  - `git diff --check`
  - `git status --short`
