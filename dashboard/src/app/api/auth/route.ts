import { NextResponse } from "next/server"
import { createHash, timingSafeEqual } from "crypto"

function computeToken(password: string): string {
  return createHash("sha256")
    .update(password + ":cerebralos-dashboard")
    .digest("hex")
}

// POST /api/auth — validate password, set cookie
export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}))
  const { password } = body as { password?: string }

  const expected = process.env.DASHBOARD_PASSWORD
  if (!expected || !password) {
    return NextResponse.json({ error: "Invalid password" }, { status: 401 })
  }

  // Timing-safe comparison — prevent side-channel password extraction
  const a = Buffer.from(password, "utf8")
  const b = Buffer.from(expected, "utf8")
  if (a.length !== b.length || !timingSafeEqual(a, b)) {
    return NextResponse.json({ error: "Invalid password" }, { status: 401 })
  }

  const token = computeToken(password)
  const res = NextResponse.json({ ok: true })
  res.cookies.set("cerebralos_auth", token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 60 * 24 * 7, // 7 days
  })
  return res
}

// DELETE /api/auth — clear cookie (logout)
export async function DELETE() {
  const res = NextResponse.json({ ok: true })
  res.cookies.delete("cerebralos_auth")
  return res
}
