# CerebralOS

CerebralOS is a deterministic trauma governance system built for
single-user PI (Performance Improvement) workflows from raw Epic text
exports.

## Core Principles

- **Fail-closed:** missing required data → INDETERMINATE / NOT_EVALUATED (never guessed).
- **No invented data.** No smoothing, no inference.
- **Evidence receipts:** every YES includes source, timestamp/line, and excerpt.
- **PHI must never be committed to Git.**

## Repository Layout

| Directory | Contents |
|-----------|----------|
| `cerebralos/` | Core engine, extraction, reporting modules |
| `rules/` | Versioned protocol and NTDS rule definitions (JSON) |
| `scripts/` | Pipeline runners, validation gates, audit utilities |
| `tests/` | Unit and precision tests |
| `data_raw/` | Raw Epic `.txt` exports (PHI — **never committed**, `.gitignore`'d) |
| `outputs/` | Generated artifacts (`.gitignore`'d) |

## Quick Start

### Single Patient — PI RN Casefile

```bash
# Run the full pipeline for one patient and open the HTML casefile
./scripts/run_casefile_v1.sh "Patient Name"
```

Or run interactively (prompts for patient name):

```bash
./scripts/run_casefile_v1.sh
```

**VS Code**: Run the task `PI RN Casefile — Run Patient` (Ctrl+Shift+P → Tasks: Run Task).

The casefile is written to `outputs/casefile/<Slug>/casefile_v1.html` and opens
automatically in the default browser. Set `CEREBRAL_NO_OPEN=1` to suppress auto-open.

### Patient Hub

Generate a local patient index that links to all processed casefiles:

```bash
./scripts/run_casefile_hub_v1.sh
```

The hub is written to `outputs/casefile/hub_v1.html` and opens automatically.
Run the casefile pipeline for one or more patients first.

## Requirements

- Python 3.9+
- `pip install openpyxl` (for Excel dashboard)
- Optional: `fswatch` (for watch mode)
