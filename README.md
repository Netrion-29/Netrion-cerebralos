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
