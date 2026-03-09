// ─── NTDS ────────────────────────────────────────────────────────────────────

export type NtdsOutcome = "YES" | "NO" | "UNABLE_TO_DETERMINE" | "EXCLUDED"

export interface NtdsSummaryItem {
  event_id: number
  canonical_name: string
  outcome: NtdsOutcome
  hard_stop_reason?: string
}

export interface GateEvidence {
  source_type: string
  timestamp: string
  text: string
  text_raw?: string
  is_historical?: boolean
  // NTDS events use `pointers`; old protocol snippets use `pointer`
  pointers?: { file: string; line?: number; line_start?: number; line_end?: number; block_id?: number }
  pointer?: { file: string; line_start?: number; line_end?: number; block_id?: number }
}

export interface GateTraceEntry {
  gate: string
  passed: boolean
  reason: string
  evidence: GateEvidence[]
}

export interface NtdsEventDetail {
  event_id: number
  canonical_name: string
  ntds_year: number
  outcome: NtdsOutcome
  hard_stop: string | null
  gate_trace: GateTraceEntry[]
  near_miss_evidence: GateEvidence[]
  summary?: string
  searched_for?: Array<{ gate_id: string; query_keys: string[]; exclude_keys: string[] }>
  warnings?: string[]
}

// ─── Protocols ───────────────────────────────────────────────────────────────

export type ProtocolOutcome = "COMPLIANT" | "NON_COMPLIANT" | "NOT_TRIGGERED" | "INDETERMINATE"

export interface ProtocolStepTrace {
  requirement_id: string
  requirement_type?: string
  passed: boolean
  reason: string
  missing_data: string[]
  evidence: GateEvidence[]
}

export interface ProtocolResult {
  protocol_id: string
  protocol_name: string
  outcome: ProtocolOutcome
  step_trace: ProtocolStepTrace[]
  warnings?: string[]
}

// ─── API shapes ──────────────────────────────────────────────────────────────

export interface PatientListItem {
  slug: string
  display_name: string
  ntds_summary: NtdsSummaryItem[]
  yes_count: number
  no_count: number
  utd_count: number
  excluded_count: number
  has_protocols: boolean
  protocol_compliant_count: number
  protocol_noncompliant_count: number
  protocol_triggered_count: number
}

export interface PatientDetail {
  slug: string
  display_name: string
  ntds_summary: NtdsSummaryItem[]
  ntds_year: number
  protocols: ProtocolResult[]
  has_protocols: boolean
}
