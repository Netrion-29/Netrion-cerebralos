import { NextResponse } from "next/server"
import { createHash, timingSafeEqual } from "crypto"

function computeToken(password: string): string {
  return createHash("sha256")
    .update(password + ":cerebralos-dashboard")
    .digest("hex")
}

// ---------------------------------------------------------------------------
// Rate-limit policy: 10 failed attempts per IP per 15-minute sliding window.
// After the limit is reached, all attempts from that IP return 429 until the
// window expires.  Successful login clears the failure record for that IP.
// In-memory store — resets on process restart, which is acceptable for this
// internal dashboard (attacker must re-probe after cold start anyway).
// ---------------------------------------------------------------------------
const RATE_LIMIT_MAX = 10
const RATE_LIMIT_WINDOW_MS = 15 * 60 * 1000 // 15 minutes

interface FailureRecord {
  count: number
  firstFailure: number
}

const failuresByIp = new Map<string, FailureRecord>()

/** Extract a client key from the request — prefer x-forwarded-for, fall back to a fixed key. */
function clientKey(req: Request): string {
  const forwarded = req.headers.get("x-forwarded-for")
  if (forwarded) {
    // First IP in the comma-separated list is the original client
    const ip = forwarded.split(",")[0].trim()
    if (ip) return ip
  }
  return "unknown-ip"
}

/** Returns true (and the current count) if the IP has exceeded the rate limit. */
function isRateLimited(key: string): { limited: boolean; count: number } {
  const now = Date.now()
  const record = failuresByIp.get(key)
  if (!record) return { limited: false, count: 0 }

  // Window expired — clear record
  if (now - record.firstFailure > RATE_LIMIT_WINDOW_MS) {
    failuresByIp.delete(key)
    return { limited: false, count: 0 }
  }

  return { limited: record.count >= RATE_LIMIT_MAX, count: record.count }
}

/** Record a failed login attempt for this IP. */
function recordFailure(key: string): void {
  const now = Date.now()
  const record = failuresByIp.get(key)
  if (!record || now - record.firstFailure > RATE_LIMIT_WINDOW_MS) {
    failuresByIp.set(key, { count: 1, firstFailure: now })
  } else {
    record.count++
  }
}

/** Clear failure history on successful login. */
function clearFailures(key: string): void {
  failuresByIp.delete(key)
}

// POST /api/auth — validate password, set cookie
export async function POST(req: Request) {
  const ip = clientKey(req)

  // Enforce rate limit before any credential work
  const { limited } = isRateLimited(ip)
  if (limited) {
    return NextResponse.json(
      { error: "Too many login attempts. Try again later." },
      { status: 429 }
    )
  }

  const body = await req.json().catch(() => ({}))
  const { password } = body as { password?: string }

  const expected = process.env.DASHBOARD_PASSWORD
  if (!expected || !password) {
    recordFailure(ip)
    return NextResponse.json({ error: "Invalid password" }, { status: 401 })
  }

  // Timing-safe comparison — prevent side-channel password extraction
  const a = Buffer.from(password, "utf8")
  const b = Buffer.from(expected, "utf8")
  if (a.length !== b.length || !timingSafeEqual(a, b)) {
    recordFailure(ip)
    return NextResponse.json({ error: "Invalid password" }, { status: 401 })
  }

  // Success — clear failure record for this IP
  clearFailures(ip)

  const token = computeToken(password)
  const res = NextResponse.json({ ok: true })
  res.cookies.set("__Host-cerebralos_auth", token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 60 * 24, // 24 hours
  })
  return res
}

// DELETE /api/auth — clear cookie (logout)
export async function DELETE() {
  const res = NextResponse.json({ ok: true })
  res.cookies.delete("__Host-cerebralos_auth")
  return res
}
