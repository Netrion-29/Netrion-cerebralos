import fs from "fs"
import path from "path"
import { getProtocolsDir } from "./paths"
import type { ProtocolResult, ProtocolStepTrace, GateEvidence } from "@/types"

// ─── Old format (protocol_results_v1.json) ────────────────────────────────────

interface OldEvidenceSnippet {
  source_type: string
  timestamp: string
  text: string
  text_raw?: string
  is_historical?: boolean
  pointer?: { file: string; line_start?: number; line_end?: number; block_id?: number }
}

interface OldStepTrace {
  requirement_id: string
  passed: boolean
  reason: string
  missing_data?: string[]
  evidence_count?: number
  evidence_snippets?: OldEvidenceSnippet[]
}

interface OldProtocolResult {
  protocol_id: string
  protocol_name: string
  outcome: string
  step_trace: OldStepTrace[]
  warnings?: string[]
}

function normalizeOldEvidence(snippets: OldEvidenceSnippet[] | undefined): GateEvidence[] {
  if (!snippets) return []
  return snippets.map((s) => ({
    source_type: s.source_type,
    timestamp: s.timestamp,
    text: s.text,
    text_raw: s.text_raw,
    is_historical: s.is_historical,
    pointer: s.pointer,
  }))
}

function normalizeOldProtocol(raw: OldProtocolResult): ProtocolResult {
  return {
    protocol_id: raw.protocol_id,
    protocol_name: raw.protocol_name,
    outcome: raw.outcome as ProtocolResult["outcome"],
    warnings: raw.warnings,
    step_trace: (raw.step_trace ?? []).map((s): ProtocolStepTrace => ({
      requirement_id: s.requirement_id,
      requirement_type: undefined,
      passed: s.passed,
      reason: s.reason,
      missing_data: s.missing_data ?? [],
      evidence: normalizeOldEvidence(s.evidence_snippets),
    })),
  }
}

// ─── New format (one file per protocol) ──────────────────────────────────────

interface NewStepTrace {
  requirement_id: string
  requirement_type?: string
  passed: boolean
  reason: string
  missing_data?: string[]
  evidence?: GateEvidence[]
}

interface NewProtocolResult {
  protocol_id: string
  protocol_name: string
  outcome: string
  step_trace: NewStepTrace[]
  warnings?: string[]
}

function normalizeNewProtocol(raw: NewProtocolResult): ProtocolResult {
  return {
    protocol_id: raw.protocol_id,
    protocol_name: raw.protocol_name,
    outcome: raw.outcome as ProtocolResult["outcome"],
    warnings: raw.warnings,
    step_trace: (raw.step_trace ?? []).map((s): ProtocolStepTrace => ({
      requirement_id: s.requirement_id,
      requirement_type: s.requirement_type,
      passed: s.passed,
      reason: s.reason,
      missing_data: s.missing_data ?? [],
      evidence: s.evidence ?? [],
    })),
  }
}

// ─── Public API ──────────────────────────────────────────────────────────────

export function readProtocols(slug: string): ProtocolResult[] {
  const dir = getProtocolsDir(slug)
  if (!fs.existsSync(dir)) return []

  // Old format: single protocol_results_v1.json array file
  const oldFile = path.join(dir, "protocol_results_v1.json")
  if (fs.existsSync(oldFile)) {
    const raw: OldProtocolResult[] = JSON.parse(fs.readFileSync(oldFile, "utf-8"))
    return raw.map(normalizeOldProtocol)
  }

  // New format: individual JSON files per protocol
  const files = fs.readdirSync(dir).filter((f) => f.endsWith(".json"))
  return files
    .map((fname) => {
      const raw: NewProtocolResult = JSON.parse(
        fs.readFileSync(path.join(dir, fname), "utf-8")
      )
      return normalizeNewProtocol(raw)
    })
    .sort((a, b) => a.protocol_name.localeCompare(b.protocol_name))
}
