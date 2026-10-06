import { NextRequest, NextResponse } from "next/server";
import { API_KEY, authDisabled, BACKEND_URL as BACKEND } from "@/lib/serverEnv";
import { getSessionUser } from "@/lib/serverSession";
import { SESSION_COOKIE } from "@/lib/session";

/**
 * Sign in with an individual dashboard account. The backend checks the
 * password against dashboard_users and returns a signed session token, which
 * is kept in the httpOnly auth_token cookie and forwarded on backend calls.
 */
export async function POST(request: NextRequest) {
  // LOCAL environment: middleware already lets every page through as the
  // local admin; this keeps the login page itself working.
  if (authDisabled()) return NextResponse.json({ ok: true });

  const { username, password } = await request.json();
  const res = await fetch(`${BACKEND}/api/auth/login`, {
    method: "POST",
    headers: { "X-API-Key": API_KEY, "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) {
    const error =
      res.status === 429
        ? "Too many failed sign-ins. Try again in 15 minutes."
        : res.status === 401
          ? "Invalid username or password."
          : "Sign-in is unavailable right now.";
    return NextResponse.json({ error }, { status: res.status === 429 ? 429 : 401 });
  }

  const { token, max_age, user } = await res.json();
  const response = NextResponse.json({ ok: true, user });
  response.cookies.set(SESSION_COOKIE, token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    maxAge: max_age,
    path: "/",
    sameSite: "lax",
  });
  return response;
}

/** The signed-in user ({username, role}), or 401. */
export async function GET() {
  const user = await getSessionUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  return NextResponse.json(user);
}

export async function DELETE() {
  const response = NextResponse.json({ ok: true });
  response.cookies.delete(SESSION_COOKIE);
  return response;
}
