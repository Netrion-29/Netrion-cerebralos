"use client"

import { useState } from "react"
import { ProtocolCard } from "./ProtocolCard"
import type { ProtocolResult } from "@/types"

interface Props {
  protocols: ProtocolResult[]
}

export function ProtocolList({ protocols }: Props) {
  const [showNotTriggered, setShowNotTriggered] = useState(false)

  const triggered = protocols.filter((p) => p.outcome !== "NOT_TRIGGERED")
  const notTriggered = protocols.filter((p) => p.outcome === "NOT_TRIGGERED")

  return (
    <div className="space-y-3">
      {triggered.length === 0 && notTriggered.length === 0 && (
        <p className="text-sm text-slate-500 italic">No protocol data available.</p>
      )}

      {triggered.map((p) => (
        <ProtocolCard key={p.protocol_id} protocol={p} />
      ))}

      {notTriggered.length > 0 && (
        <div>
          <button
            onClick={() => setShowNotTriggered((v) => !v)}
            className="text-xs text-slate-400 hover:text-slate-600 underline"
          >
            {showNotTriggered ? "Hide" : "Show"} {notTriggered.length} not-triggered protocol
            {notTriggered.length !== 1 ? "s" : ""}
          </button>
          {showNotTriggered && (
            <div className="mt-2 space-y-2">
              {notTriggered.map((p) => (
                <ProtocolCard key={p.protocol_id} protocol={p} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
