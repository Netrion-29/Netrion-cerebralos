"use client"

import { useState, useMemo } from "react"
import { PatientCard } from "@/components/PatientCard"
import type { PatientListItem } from "@/types"

type SortKey = "name" | "yes" | "utd"

interface Props {
  patients: PatientListItem[]
}

export function PatientListClient({ patients }: Props) {
  const [filter, setFilter] = useState("")
  const [sort, setSort] = useState<SortKey>("name")

  const displayed = useMemo(() => {
    const q = filter.toLowerCase()
    const filtered = q
      ? patients.filter((p) => p.display_name.toLowerCase().includes(q))
      : patients

    return [...filtered].sort((a, b) => {
      if (sort === "name") return a.display_name.localeCompare(b.display_name)
      if (sort === "yes") return b.yes_count - a.yes_count || b.utd_count - a.utd_count
      if (sort === "utd") return b.utd_count - a.utd_count || b.yes_count - a.yes_count
      return 0
    })
  }, [patients, filter, sort])

  return (
    <div>
      <div className="flex items-center gap-3 mb-4">
        <input
          type="search"
          placeholder="Filter by name…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="border border-slate-300 rounded px-3 py-1.5 text-sm w-56 focus:outline-none focus:ring-2 focus:ring-blue-300"
        />
        <div className="flex items-center gap-1 text-xs text-slate-500">
          Sort:
          {(["name", "yes", "utd"] as SortKey[]).map((k) => (
            <button
              key={k}
              onClick={() => setSort(k)}
              className={`px-2 py-1 rounded border transition-colors ${
                sort === k
                  ? "bg-slate-800 text-white border-slate-800"
                  : "border-slate-300 hover:bg-slate-100"
              }`}
            >
              {k === "name" ? "Name" : k === "yes" ? "YES↑" : "UTD↑"}
            </button>
          ))}
        </div>
        <span className="text-xs text-slate-400 ml-auto">{displayed.length} shown</span>
      </div>

      <div className="space-y-2">
        {displayed.map((p) => (
          <PatientCard key={p.slug} patient={p} />
        ))}
      </div>
    </div>
  )
}
