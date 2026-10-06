/**
 * Dashboard session: the auth_token cookie holds the token the backend issued
 * at login (POST /api/auth/login, see backend/auth.py):
 *
 *   base64url(json {uid, u, r, v, exp}) + "." + hex(HMAC-SHA256(key = API key,
 *   data = "dashboard-session." + payload))
 *
 * Verified here with Web Crypto so the Edge middleware can gate pages by role
 * without a backend round trip. The backend re-checks the token against
 * dashboard_users on every role-gated route, so a removed user or a changed
 * role is enforced there immediately; the role read here only picks pages.
 */
import { ROLES, type Role } from "./roles";
import { API_KEY, authDisabled } from "./serverEnv";

export const SESSION_COOKIE = "auth_token";
export const SESSION_HEADER = "X-Dashboard-Session";

export interface Session {
  uid: number | null;
  username: string;
  role: Role;
  exp: number;
}

// AUTH_DISABLED (local only): everyone is the local admin, like the backend's
// ENVIRONMENT=local.
const LOCAL_SESSION: Session = { uid: null, username: "local", role: "admin", exp: Infinity };

const enc = new TextEncoder();

async function hmacHex(key: string, data: string): Promise<string> {
  const k = await crypto.subtle.importKey(
    "raw",
    enc.encode(key),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const sig = await crypto.subtle.sign("HMAC", k, enc.encode(data));
  return Array.from(new Uint8Array(sig))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

function equalHex(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

function decodeB64url(text: string): string {
  const b64 = text.replace(/-/g, "+").replace(/_/g, "/");
  return atob(b64 + "=".repeat((4 - (b64.length % 4)) % 4));
}

/** The session in a correctly signed, unexpired token, else null. */
export async function readSession(token: string | undefined | null): Promise<Session | null> {
  if (authDisabled()) return LOCAL_SESSION;
  if (!token || !API_KEY) return null;
  const [body, sig, extra] = token.split(".");
  if (!body || !sig || extra !== undefined) return null;
  if (!equalHex(sig, await hmacHex(API_KEY, `dashboard-session.${body}`))) return null;
  try {
    const p = JSON.parse(decodeB64url(body));
    if (typeof p.exp !== "number" || p.exp * 1000 < Date.now()) return null;
    if (!ROLES.includes(p.r)) return null;
    return { uid: p.uid ?? null, username: String(p.u), role: p.r, exp: p.exp };
  } catch {
    return null;
  }
}
