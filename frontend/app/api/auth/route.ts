import { NextRequest, NextResponse } from "next/server";

import { homeFor, type Role, type SessionUser } from "@/lib/access";
import { authDisabled, BACKEND_URL } from "@/lib/serverEnv";
import { backendHeaders, getSession, makeSessionToken, SESSION_COOKIE } from "@/lib/session";

/**
 * POST   sign in: {email, password} -> session cookie
 * GET    who is signed in (for the nav and account pages)
 * DELETE sign out
 *
 * Accounts live in the backend (POST /api/auth/login). The shared env login
 * (DASHBOARD_USERNAME / DASHBOARD_PASSWORD) still works as an admin while no
 * admin account exists, so the first admin can be created from the Users page.
 */
export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => ({}));
  const email = String(body.email ?? body.username ?? "").trim();
  const password = String(body.password ?? "");

  let user: SessionUser | null = null;
  if (authDisabled()) {
    user = { uid: 0, email: "local", name: "Local", role: "admin" };
  } else {
    const res = await fetch(`${BACKEND_URL}/api/auth/login`, {
      method: "POST",
      headers: { ...backendHeaders(null), "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
      cache: "no-store",
    });
    if (res.ok) {
      const u = await res.json();
      user = { uid: u.id, email: u.email, name: u.name, role: u.role as Role };
    } else if (res.status === 429) {
      return NextResponse.json({ error: "Too many failed attempts. Try again in 15 minutes." }, { status: 429 });
    } else if (await sharedLoginAllowed(email, password)) {
      user = { uid: 0, email: "shared login", name: "Shared login", role: "admin" };
    }
  }

  if (!user) {
    return NextResponse.json({ error: "Invalid email or password" }, { status: 401 });
  }

  const { token, maxAge } = await makeSessionToken(user);
  const response = NextResponse.json({ ok: true, home: homeFor(user.role) });
  response.cookies.set(SESSION_COOKIE, token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    maxAge,
    path: "/",
    sameSite: "lax",
  });
  return response;
}

/** The old shared credentials, only while there is no active admin account. */
async function sharedLoginAllowed(username: string, password: string): Promise<boolean> {
  const expectedUser = process.env.DASHBOARD_USERNAME;
  const expectedPass = process.env.DASHBOARD_PASSWORD;
  if (!expectedUser || !expectedPass || username !== expectedUser || password !== expectedPass) return false;
  const res = await fetch(`${BACKEND_URL}/api/auth/status`, { headers: backendHeaders(null), cache: "no-store" });
  if (!res.ok) return false;
  const { active_admins } = await res.json();
  return active_admins === 0;
}

export async function GET(request: NextRequest) {
  const s = await getSession(request.cookies.get(SESSION_COOKIE)?.value);
  if (!s) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  return NextResponse.json({ uid: s.uid, email: s.email, name: s.name, role: s.role });
}

export async function DELETE() {
  const response = NextResponse.json({ ok: true });
  response.cookies.delete(SESSION_COOKIE);
  return response;
}
