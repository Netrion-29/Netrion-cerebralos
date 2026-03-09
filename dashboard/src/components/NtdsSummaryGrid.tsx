"use client"

import { clsx } from "clsx"
import type { NtdsSummaryItem, NtdsOutcome } from "@/types"

const DOT_CLASSES: Record<NtdsOutcome, string> = {
  YES: "bg-red-500 hover:bg-red-600",
  NO: "bg-green-500 hover:bg-green-600",
  UNABLE_TO_DETERMINE: "bg-yellow-400 hover:bg-yellow-500",
  EXCLUDED: "bg-slate-300 hover:bg-slate-400",
}

interface Props {
  summary: NtdsSummaryItem[]
  selectedId?: number | null
  onSelect?: (id: number) => void
}

export function NtdsSummaryGrid({ summary, selectedId, onSelect }: Props) {
  return (
    <div className="flex flex-wrap gap-1.5" title="NTDS event outcomes — click to expand">
      {summary.map((item) => (
        <button
          key={item.event_id}
          onClick={() => onSelect?.(item.event_id)}
          title={`E${item.event_id}: ${item.canonical_name} — ${item.outcome}`}
          className={clsx(
            "w-4 h-4 rounded-full transition-all ring-offset-1",
            DOT_CLASSES[item.outcome],
            selectedId === item.event_id && "ring-2 ring-slate-800 scale-125"
          )}
          aria-label={`${item.canonical_name}: ${item.outcome}`}
        />
      ))}
    </div>
  )
}
