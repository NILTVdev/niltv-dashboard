/**
 * Dashboard session token: one per signed-in account.
 *
 *   base64url(JSON {uid, email, name, role, exp}) + "." + hex(HMAC-SHA256)
 *
 * Signed with DASHBOARD_SESSION_SECRET (falls back to a value derived from
 * the API key, so no new setting is required). Implemented with Web Crypto
 * so the same code runs in the Edge middleware and in Node route handlers.
 *
 * The token only says who is signed in and with which role. The backend
 * re-checks the account (exists, active, role) on every API call through
 * X-Dashboard-User, so disabling someone takes effect on their next request
 * even while their cookie is still valid.
 *
 * uid 0 is the shared env login (DASHBOARD_USERNAME / DASHBOARD_PASSWORD),
 * accepted only until the first admin account exists (bootstrap). It sends
 * no X-Dashboard-User, i.e. acts as a service caller.
 */
import type { Role, SessionUser } from "@/lib/access";
import { API_KEY, authDisabled } from "@/lib/serverEnv";

export const SESSION_COOKIE = "auth_token";
export const SESSION_DAYS = 7;
const BOOTSTRAP_HOURS = 1;

const enc = new TextEncoder();
const ROLES: Role[] = ["admin", "general", "demo"];

export interface Session extends SessionUser {
  exp: number; // unix seconds
}

function secret(): string {
  return process.env.DASHBOARD_SESSION_SECRET || `dashboard-session:${API_KEY}`;
}

export async function hmacHex(key: string, data: string): Promise<string> {
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

function b64urlEncode(s: string): string {
  const bytes = enc.encode(s);
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function b64urlDecode(s: string): string {
  const bin = atob(s.replace(/-/g, "+").replace(/_/g, "/"));
  return new TextDecoder().decode(Uint8Array.from(bin, (c) => c.charCodeAt(0)));
}

function equalHex(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

export async function makeSessionToken(user: SessionUser): Promise<{ token: string; maxAge: number }> {
  const maxAge = user.uid === 0 ? BOOTSTRAP_HOURS * 3600 : SESSION_DAYS * 86400;
  const session: Session = { ...user, exp: Math.floor(Date.now() / 1000) + maxAge };
  const body = b64urlEncode(JSON.stringify(session));
  return { token: `${body}.${await hmacHex(secret(), body)}`, maxAge };
}

const LOCAL: Session = { uid: 0, email: "local", name: "Local", role: "admin", exp: Number.MAX_SAFE_INTEGER };

/** The session in the cookie, or null when missing, tampered with or expired. */
export async function getSession(token: string | undefined | null): Promise<Session | null> {
  if (authDisabled()) return LOCAL;
  if (!token) return null;
  const dot = token.lastIndexOf(".");
  if (dot <= 0) return null;
  const body = token.slice(0, dot);
  if (!equalHex(token.slice(dot + 1), await hmacHex(secret(), body))) return null;
  try {
    const s = JSON.parse(b64urlDecode(body)) as Session;
    if (!ROLES.includes(s.role) || typeof s.uid !== "number" || s.exp < Date.now() / 1000) return null;
    return s;
  } catch {
    return null;
  }
}

/** Headers for a backend call made on behalf of this session. */
export function backendHeaders(session: Session | null): Record<string, string> {
  const h: Record<string, string> = { "X-API-Key": API_KEY };
  if (session && session.uid > 0) h["X-Dashboard-User"] = String(session.uid);
  return h;
}
