import { NextRequest, NextResponse } from "next/server";

import { HOME, type Role } from "@/lib/access";
import { authDisabled, BACKEND_URL } from "@/lib/serverEnv";
import { isJson, sameOrigin } from "@/lib/requestGuards";
import {
  backendHeaders, bootstrapOpen, getSession, makeSessionToken, refreshSession, SESSION_COOKIE, sessionCookieOptions,
  type SessionClaims,
} from "@/lib/session";

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
  // Only the login page signs in, so another site can't sign a browser into an account.
  if (!sameOrigin(request.headers.get("origin"), request.headers.get("host")) || !isJson(request.headers.get("content-type"))) {
    return NextResponse.json({ error: "Sign in from the dashboard login page" }, { status: 403 });
  }
  // A sign-in body is two short fields; anything large is refused before parsing.
  if (Number(request.headers.get("content-length") ?? 0) > 4096) {
    return NextResponse.json({ error: "Invalid email or password" }, { status: 400 });
  }
  const body = await request.json().catch(() => ({}));
  const email = String(body.email ?? body.username ?? "").trim();
  const password = String(body.password ?? "");
  if (email.length > 254 || password.length > 1024) {
    return NextResponse.json({ error: "Invalid email or password" }, { status: 400 });
  }

  let user: SessionClaims | null = null;
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
      user = { uid: u.id, email: u.email, name: u.name, role: u.role as Role, sv: u.session_version };
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
  const response = NextResponse.json({ ok: true, home: HOME });
  response.cookies.set(SESSION_COOKIE, token, sessionCookieOptions(maxAge));
  return response;
}

/** The old shared credentials, only while there is no active admin account. */
async function sharedLoginAllowed(username: string, password: string): Promise<boolean> {
  const expectedUser = process.env.DASHBOARD_USERNAME;
  const expectedPass = process.env.DASHBOARD_PASSWORD;
  if (!expectedUser || !expectedPass || username !== expectedUser || password !== expectedPass) return false;
  return bootstrapOpen();
}

export async function GET(request: NextRequest) {
  const s = await getSession(request.cookies.get(SESSION_COOKIE)?.value);
  if (!s) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  // /api/auth skips the middleware, so the nav's role badge refreshes here.
  const r = await refreshSession(s);
  if (r.kind === "ended") {
    const res = NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    res.cookies.delete(SESSION_COOKIE);
    return res;
  }
  const cur = r.kind === "renewed" ? r.session : s;
  const res = NextResponse.json({ uid: cur.uid, email: cur.email, name: cur.name, role: cur.role });
  if (r.kind === "renewed") res.cookies.set(SESSION_COOKIE, r.token, sessionCookieOptions(r.maxAge));
  return res;
}

export async function DELETE(request: NextRequest) {
  if (!sameOrigin(request.headers.get("origin"), request.headers.get("host"))) {
    return NextResponse.json({ error: "Cross-site request refused" }, { status: 403 });
  }
  const response = NextResponse.json({ ok: true });
  response.cookies.delete(SESSION_COOKIE);
  return response;
}
