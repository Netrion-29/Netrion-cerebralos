"use client"

import { useState, useEffect } from "react"
import { OutcomeBadge } from "./OutcomeBadge"
import { EvidenceSnippet } from "./EvidenceSnippet"
import { clsx } from "clsx"
import type { NtdsEventDetail } from "@/types"

interface Props {
  slug: string
  eventId: number
  canonicalName: string
  onClose?: () => void
}

export function NtdsEventCard({ slug, eventId, canonicalName, onClose }: Props) {
  const [data, setData] = useState<NtdsEventDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    fetch(`/api/patients/${slug}/events/${eventId}`)
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status}`)
        return r.json()
      })
      .then((d: NtdsEventDetail) => {
        setData(d)
        setLoading(false)
      })
      .catch((e: Error) => {
        setError(e.message)
        setLoading(false)
      })
  }, [slug, eventId])

  return (
    <div className="border border-slate-300 rounded-lg bg-white shadow-sm mt-3">
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200 bg-slate-50 rounded-t-lg">
        <div className="flex items-center gap-3">
          <span className="text-xs font-mono text-slate-500">E{String(eventId).padStart(2, "0")}</span>
          <span className="font-semibold text-slate-800">{canonicalName}</span>
          {data && <OutcomeBadge outcome={data.outcome} size="sm" />}
        </div>
        {onClose && (
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-700 text-lg leading-none"
            aria-label="Close"
          >
            ×
          </button>
        )}
      </div>

      <div className="p-4">
        {loading && <p className="text-slate-500 text-sm">Loading event detail…</p>}
        {error && <p className="text-red-600 text-sm">Error: {error}</p>}
        {data && (
          <div className="space-y-5">
            {/* Summary */}
            {data.summary && (
              <p className="text-sm text-slate-700 italic">{data.summary}</p>
            )}

            {/* Hard stop */}
            {data.hard_stop && (
              <div className="bg-red-50 border border-red-200 rounded p-3 text-sm text-red-800">
                <span className="font-semibold">Hard stop:</span> {data.hard_stop}
              </div>
            )}

            {/* Gate trace */}
            {data.gate_trace.length > 0 && (
              <div>
                <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-2">
                  Gate Trace
                </h4>
                <div className="space-y-2">
                  {data.gate_trace.map((gate, i) => (
                    <GateRow key={i} gate={gate} />
                  ))}
                </div>
              </div>
            )}

            {/* Near-miss evidence */}
            {data.near_miss_evidence.length > 0 && (
              <div>
                <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-2">
                  Near-Miss Evidence ({data.near_miss_evidence.length})
                </h4>
                <div className="space-y-2">
                  {data.near_miss_evidence.slice(0, 5).map((ev, i) => (
                    <EvidenceSnippet key={i} evidence={ev} index={i} />
                  ))}
                  {data.near_miss_evidence.length > 5 && (
                    <p className="text-xs text-slate-400">
                      +{data.near_miss_evidence.length - 5} more snippets
                    </p>
                  )}
                </div>
              </div>
            )}

            {/* Warnings */}
            {data.warnings && data.warnings.length > 0 && (
              <div className="bg-yellow-50 border border-yellow-200 rounded p-3 space-y-1">
                {data.warnings.map((w, i) => (
                  <p key={i} className="text-xs text-yellow-800">{w}</p>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function GateRow({ gate }: { gate: NtdsEventDetail["gate_trace"][0] }) {
  const [open, setOpen] = useState(false)

  return (
    <div className={clsx(
      "border rounded text-sm",
      gate.passed ? "border-green-200 bg-green-50" : "border-red-200 bg-red-50"
    )}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-3 py-2 text-left"
      >
        <span className={clsx(
          "text-base leading-none",
          gate.passed ? "text-green-600" : "text-red-500"
        )}>
          {gate.passed ? "✓" : "✗"}
        </span>
        <span className="font-mono text-xs text-slate-500 w-32 shrink-0">{gate.gate}</span>
        <span className="text-slate-700 flex-1">{gate.reason}</span>
        {gate.evidence.length > 0 && (
          <span className="text-xs text-slate-400">{gate.evidence.length} ev.</span>
        )}
        {gate.evidence.length > 0 && (
          <span className="text-slate-400 ml-1">{open ? "▲" : "▼"}</span>
        )}
      </button>
      {open && gate.evidence.length > 0 && (
        <div className="px-3 pb-3 space-y-2 border-t border-slate-200 pt-2">
          {gate.evidence.map((ev, i) => (
            <EvidenceSnippet key={i} evidence={ev} index={i} />
          ))}
        </div>
      )}
    </div>
  )
}
