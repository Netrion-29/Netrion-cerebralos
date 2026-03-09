"use client"

import { useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"

export function LoginForm() {
  const [password, setPassword] = useState("")
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(false)
  const router = useRouter()
  const searchParams = useSearchParams()

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setLoading(true)
    setError("")

    const res = await fetch("/api/auth", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    })

    if (res.ok) {
      const next = searchParams.get("next") || "/"
      router.push(next)
      router.refresh()
    } else {
      setError("Incorrect password.")
      setLoading(false)
    }
  }

  return (
    <div className="bg-white rounded-lg border border-slate-200 shadow-sm p-8 w-full max-w-sm space-y-6">
      <div>
        <h1 className="text-xl font-bold text-slate-900">CerebralOS Dashboard</h1>
        <p className="text-sm text-slate-500 mt-1">Enter your access password to continue.</p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">
            Password
          </label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            autoFocus
            className="w-full border border-slate-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300"
          />
        </div>
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button
          type="submit"
          disabled={loading}
          className="w-full bg-slate-800 text-white rounded py-2 text-sm font-semibold hover:bg-slate-700 disabled:opacity-50 transition-colors"
        >
          {loading ? "Logging in…" : "Log in"}
        </button>
      </form>

      <p className="text-xs text-slate-400 text-center">
        ⚠ PHI — authorized access only
      </p>
    </div>
  )
}
