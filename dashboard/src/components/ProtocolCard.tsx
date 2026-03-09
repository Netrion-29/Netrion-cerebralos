"use client"

import { useState } from "react"
import { clsx } from "clsx"
import { OutcomeBadge } from "./OutcomeBadge"
import { EvidenceSnippet } from "./EvidenceSnippet"
import type { ProtocolResult } from "@/types"

interface Props {
  protocol: ProtocolResult
}

export function ProtocolCard({ protocol }: Props) {
  const [open, setOpen] = useState(false)

  return (
    <div className="border border-slate-200 rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-4 py-3 bg-slate-50 hover:bg-slate-100 transition-colors text-left"
      >
        <div className="flex items-center gap-3">
          <span className="font-semibold text-slate-800 text-sm">
            {protocol.protocol_name}
          </span>
          <OutcomeBadge outcome={protocol.outcome} size="sm" />
        </div>
        <span className="text-slate-400">{open ? "▲" : "▼"}</span>
      </button>

      {open && (
        <div className="p-4 space-y-4">
          {protocol.warnings && protocol.warnings.length > 0 && (
            <div className="bg-yellow-50 border border-yellow-200 rounded p-3">
              {protocol.warnings.map((w, i) => (
                <p key={i} className="text-xs text-yellow-800">{w}</p>
              ))}
            </div>
          )}

          {protocol.step_trace.map((step, i) => (
            <StepRow key={i} step={step} />
          ))}
        </div>
      )}
    </div>
  )
}

function StepRow({ step }: { step: ProtocolResult["step_trace"][0] }) {
  const [open, setOpen] = useState(false)

  return (
    <div className={clsx(
      "border rounded text-sm",
      step.passed ? "border-green-200 bg-green-50" : "border-red-200 bg-red-50"
    )}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-3 py-2 text-left"
      >
        <span className={clsx(
          "text-base leading-none",
          step.passed ? "text-green-600" : "text-red-500"
        )}>
          {step.passed ? "✓" : "✗"}
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-mono text-xs text-slate-500">{step.requirement_id}</span>
            {step.requirement_type && (
              <span className="text-xs text-slate-400 italic">{step.requirement_type}</span>
            )}
          </div>
          <p className="text-slate-700 mt-0.5">{step.reason}</p>
        </div>
        {step.evidence.length > 0 && (
          <span className="text-xs text-slate-400 shrink-0">
            {step.evidence.length} ev. {open ? "▲" : "▼"}
          </span>
        )}
      </button>

      {open && (
        <div className="border-t border-slate-200 px-3 pb-3 pt-2 space-y-3">
          {step.missing_data.length > 0 && (
            <div className="text-xs text-red-700">
              <span className="font-semibold">Missing: </span>
              {step.missing_data.join(", ")}
            </div>
          )}
          {step.evidence.map((ev, i) => (
            <EvidenceSnippet key={i} evidence={ev} index={i} />
          ))}
        </div>
      )}
    </div>
  )
}
