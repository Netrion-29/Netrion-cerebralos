import type { GateEvidence } from "@/types"

interface Props {
  evidence: GateEvidence
  index?: number
}

export function EvidenceSnippet({ evidence, index }: Props) {
  const ts = evidence.timestamp
    ? new Date(evidence.timestamp).toLocaleString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : evidence.timestamp

  const pointer = evidence.pointers ?? evidence.pointer
  const lineInfo = pointer
    ? "line" in pointer && pointer.line != null
      ? `L${pointer.line}`
      : "line_start" in pointer && pointer.line_start != null
      ? `L${pointer.line_start}–${pointer.line_end}`
      : null
    : null

  return (
    <div className="border border-slate-200 rounded bg-slate-50 p-3 text-sm space-y-1">
      <div className="flex items-center gap-2 text-xs text-slate-500">
        {index != null && <span className="font-mono">#{index + 1}</span>}
        <span className="font-semibold text-slate-700 uppercase tracking-wide">
          {evidence.source_type}
        </span>
        {ts && <span>{ts}</span>}
        {lineInfo && (
          <span className="font-mono text-slate-400">{lineInfo}</span>
        )}
      </div>
      <p className="text-slate-800 leading-relaxed line-clamp-6">{evidence.text}</p>
    </div>
  )
}
