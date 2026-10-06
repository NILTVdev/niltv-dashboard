/**
 * Session helpers for server components and route handlers (they read the
 * request cookies, so not for the Edge middleware; that uses lib/session).
 */
import { cookies } from "next/headers";

import type { SessionUser } from "@/lib/roles";
import { API_KEY } from "@/lib/serverEnv";
import { readSession, SESSION_COOKIE, SESSION_HEADER, type Session } from "@/lib/session";

export async function sessionToken(): Promise<string | undefined> {
  return (await cookies()).get(SESSION_COOKIE)?.value;
}

export async function getSession(): Promise<Session | null> {
  return readSession(await sessionToken());
}

export async function getSessionUser(): Promise<SessionUser | null> {
  const s = await getSession();
  return s ? { username: s.username, role: s.role } : null;
}

/** Headers for a backend call: the server-held API key plus the user's session. */
export function backendHeaders(token: string | undefined): Record<string, string> {
  const headers: Record<string, string> = { "X-API-Key": API_KEY };
  if (token) headers[SESSION_HEADER] = token;
  return headers;
}
