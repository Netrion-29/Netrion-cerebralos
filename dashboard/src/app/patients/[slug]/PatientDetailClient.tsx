"use client"

import { useState } from "react"
import { NtdsSummaryGrid } from "@/components/NtdsSummaryGrid"
import { NtdsEventCard } from "@/components/NtdsEventCard"
import type { NtdsSummaryItem } from "@/types"

interface Props {
  slug: string
  summary: NtdsSummaryItem[]
}

export function PatientDetailClient({ slug, summary }: Props) {
  const [selectedId, setSelectedId] = useState<number | null>(null)

  const selectedItem = selectedId != null ? summary.find((e) => e.event_id === selectedId) : null

  function handleSelect(id: number) {
    setSelectedId((prev) => (prev === id ? null : id))
  }

  return (
    <div>
      {/* Summary table */}
      <div className="bg-white border border-slate-200 rounded-lg p-4 space-y-4">
        <NtdsSummaryGrid summary={summary} selectedId={selectedId} onSelect={handleSelect} />

        {/* Event name list */}
        <div className="divide-y divide-slate-100">
          {summary.map((item) => (
            <EventRow
              key={item.event_id}
              item={item}
              selected={selectedId === item.event_id}
              onSelect={handleSelect}
            />
          ))}
        </div>
      </div>

      {/* Inline event detail */}
      {selectedId != null && selectedItem && (
        <NtdsEventCard
          slug={slug}
          eventId={selectedId}
          canonicalName={selectedItem.canonical_name}
          onClose={() => setSelectedId(null)}
        />
      )}
    </div>
  )
}

const OUTCOME_DOT: Record<string, string> = {
  YES: "bg-red-500",
  NO: "bg-green-500",
  UNABLE_TO_DETERMINE: "bg-yellow-400",
  EXCLUDED: "bg-slate-300",
}

function EventRow({
  item,
  selected,
  onSelect,
}: {
  item: NtdsSummaryItem
  selected: boolean
  onSelect: (id: number) => void
}) {
  return (
    <button
      onClick={() => onSelect(item.event_id)}
      className={`w-full flex items-center gap-3 py-2 px-1 text-left hover:bg-slate-50 transition-colors rounded ${
        selected ? "bg-blue-50" : ""
      }`}
    >
      <span className="font-mono text-xs text-slate-400 w-8 shrink-0">
        E{String(item.event_id).padStart(2, "0")}
      </span>
      <span
        className={`w-3 h-3 rounded-full shrink-0 ${OUTCOME_DOT[item.outcome] ?? "bg-slate-300"}`}
      />
      <span className="text-sm text-slate-700 flex-1">{item.canonical_name}</span>
      <span className="text-xs font-mono text-slate-500 shrink-0">{item.outcome}</span>
      {selected && <span className="text-slate-400 text-xs">▲</span>}
    </button>
  )
}
