# CerebralOS

Deterministic evidence extraction and case-review generation for trauma
performance improvement (PI) workflows.

## The Problem

Trauma PI review starts with messy, exported chart records — thousands
of lines of unstructured text per patient. The PI reviewer must
manually locate relevant clinical events, reconstruct a day-by-day
timeline, check protocol compliance, and evaluate NTDS reportable
events. This is slow, error-prone, and hard to hand off mid-review.

AI assistants can help with one-shot questions, but they lose context
across sessions. When a review spans days or weeks, prior work
disappears and the reviewer starts over — re-explaining the patient,
re-finding the same evidence, re-answering the same questions. This
makes AI tooling unreliable for the structured, long-running workflows
that PI review actually requires.

## What CerebralOS Does

CerebralOS takes a raw patient text export and produces a structured,
review-ready casefile — deterministically, with no clinical inference.

The pipeline runs in stages, each producing a durable intermediate
artifact:

| Stage | Output | Purpose |
|-------|--------|---------|
| **Ingest** | `patient_evidence_v1.json` | Extract structured evidence from raw text. Every item links to a source line. |
| **Timeline** | `patient_days_v1.json` | Reconstruct hospital days from admission through discharge. |
| **Features** | `patient_features_v1.json` | Generate clinical feature modules (labs, vitals, procedures, meds, SBIRT, etc.). |
| **NTDS** | `ntds_summary_2026_v1.json` | Evaluate 21 NTDS reportable events against extracted evidence. |
| **Protocols** | `protocol_results_v1.json` | Check protocol compliance against institutional rule definitions. |
| **Casefile** | `casefile_v1.html` | Render a single-patient review document combining all layers. |

Every output is deterministic: same input produces same output. Missing
data produces `INDETERMINATE` or `NOT_EVALUATED` — never a guess.

## Why It Works for Long-Running Workflows

CerebralOS was built around a practical constraint: AI context resets
between sessions, but PI review workflows run for days or weeks.

The solution is **durable intermediate artifacts**. Each pipeline stage
writes a versioned JSON file that captures the full extraction state.
When a session ends, nothing is lost. The next session picks up from
the artifacts — not from memory, not from re-prompting, and not from
re-running prior work.

This approach received recognition for solving a real problem: making AI
tooling reliable for structured clinical workflows where context
continuity matters more than single-query intelligence.

## Example Workflow

**Without CerebralOS:**

```text
1. Open 2,000-line raw text export
2. Ctrl-F for keywords, scroll through noise
3. Manually track what happened each hospital day
4. Check NTDS events from memory / spreadsheet
5. Repeat from scratch if interrupted or context is lost
```

**With CerebralOS:**

```text
1. Run one command
2. Open the rendered casefile
3. Review structured timeline, flagged non-compliance, and evidence trails
4. Resume anytime — all intermediate artifacts persist
```

## Quick Start

### Prerequisites

- Python 3.9+
- `pip install openpyxl` (for Excel dashboard export)

### Run one patient

```bash
./scripts/run_casefile_v1.sh "Patient Name"
```

This runs the full pipeline and opens the HTML casefile in your browser.
Set `CEREBRAL_NO_OPEN=1` to suppress auto-open.

Or run interactively (prompts for patient name):

```bash
./scripts/run_casefile_v1.sh
```

### Patient hub

Generate a local index linking all processed casefiles:

```bash
./scripts/run_casefile_hub_v1.sh
```

> **Note:** CerebralOS processes real patient data locally. The repo
> does not include sample PHI. To try the pipeline, you need your own
> `.txt` exports placed in `data_raw/`.

## Use Cases

- **PI case review** — structured, single-patient chart review for
  trauma performance improvement.
- **Long-running deterministic review** — multi-session analysis where
  intermediate artifacts preserve continuity without session memory.
- **Structured analysis of messy source text** — extract evidence,
  timelines, and features from unstructured clinical text exports.

## Architecture

```text
data_raw/*.txt
    │
    ▼
┌──────────┐    ┌──────────┐    ┌──────────┐
│  Ingest  │───▶│ Timeline │───▶│ Features │
│ (Layer 0)│    │ (Layer 1)│    │ (Layer 2)│
└──────────┘    └──────────┘    └──────────┘
    │                               │
    ▼                               ▼
evidence.json              features.json
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
              ┌──────────┐   ┌──────────┐   ┌──────────┐
              │   NTDS   │   │ Protocol │   │ Casefile │
              │ (Layer 3)│   │ (Layer 4)│   │ Renderer │
              └──────────┘   └──────────┘   └──────────┘
                    │               │               │
                    ▼               ▼               ▼
              ntds.json      protocols.json   casefile.html
```

Each layer reads from prior artifacts and writes its own versioned
output. Layers can be re-run independently.

## Repository Layout

| Directory | Contents |
|-----------|----------|
| `cerebralos/` | Core engine: ingest, timeline, features, NTDS, protocols, reporting |
| `rules/` | Versioned protocol and NTDS rule definitions (JSON) |
| `scripts/` | Pipeline runners, validation gates, audit utilities |
| `tests/` | Unit and precision tests |
| `docs/` | Architecture docs, roadmaps, audit logs |
| `data_raw/` | Raw `.txt` exports — **local only**, `.gitignore`'d |
| `outputs/` | Generated artifacts — **local only**, `.gitignore`'d |

## Safety and Trust

- **Fail-closed.** Missing data → `INDETERMINATE` / `NOT_EVALUATED`.
  The system never guesses.
- **No invented data.** No smoothing, no inference, no hallucination.
  Every YES includes source line, timestamp, and excerpt.
- **PHI stays local.** Patient data and generated outputs are
  `.gitignore`'d and never leave the local machine.
- **Not a medical device.** CerebralOS is a documentation and
  governance tool. It surfaces evidence from existing records for
  PI review. All clinical decisions are made by qualified clinicians
  using primary sources.

See [CONTRIBUTING.md](CONTRIBUTING.md) for development rules and
[SECURITY.md](SECURITY.md) for vulnerability reporting and PHI policy.

## License

[MIT](LICENSE)
