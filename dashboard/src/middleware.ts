import { NextResponse } from "next/server"
import type { NextRequest } from "next/server"

// Paths that never require auth
const PUBLIC_PREFIXES = ["/login", "/api/auth", "/_next", "/favicon.ico"]

/**
 * Constant-time string comparison safe for Edge Runtime (no Node crypto).
 * Prevents timing side-channel leakage of token values.
 */
function constantTimeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false
  let mismatch = 0
  for (let i = 0; i < a.length; i++) {
    mismatch |= a.charCodeAt(i) ^ b.charCodeAt(i)
  }
  return mismatch === 0
}

async function computeToken(password: string): Promise<string> {
  const encoder = new TextEncoder()
  const data = encoder.encode(password + ":cerebralos-dashboard")
  const hash = await crypto.subtle.digest("SHA-256", data)
  return Array.from(new Uint8Array(hash))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("")
}

export async function middleware(request: NextRequest) {
  const password = process.env.DASHBOARD_PASSWORD

  // Production: require DASHBOARD_PASSWORD — fail closed to prevent PHI exposure
  if (!password) {
    if (process.env.NODE_ENV === "production") {
      return NextResponse.json(
        { error: "DASHBOARD_PASSWORD not configured" },
        { status: 503 }
      )
    }
    // Dev: auth disabled when no password configured
    return NextResponse.next()
  }

  const { pathname } = request.nextUrl
  if (PUBLIC_PREFIXES.some((p) => pathname.startsWith(p))) {
    return NextResponse.next()
  }

  const cookie = request.cookies.get("__Host-cerebralos_auth")?.value
  const expected = await computeToken(password)

  // Constant-time comparison — prevent timing side-channel on auth token
  if (!cookie || !constantTimeEqual(cookie, expected)) {
    const loginUrl = new URL("/login", request.url)
    loginUrl.searchParams.set("next", pathname)
    return NextResponse.redirect(loginUrl)
  }

  return NextResponse.next()
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
}
