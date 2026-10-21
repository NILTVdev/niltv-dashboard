/**
 * Dashboard session token: one per signed-in account.
 *
 *   base64url(JSON {uid, email, name, role, exp, chk}) + "." + hex(HMAC-SHA256)
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
 * The role in the token decides which pages and links the browser is shown,
 * so it must not go stale either: refreshSession() re-reads the account from
 * the backend when the last check (chk) is older than RECHECK_SECONDS, and the
 * middleware swaps in a re-signed cookie (same expiry) or ends the session.
 *
 * uid 0 is the shared env login (DASHBOARD_USERNAME / DASHBOARD_PASSWORD),
 * accepted only until the first admin account exists (bootstrap). It sends
 * no X-Dashboard-User, i.e. acts as a service caller, and stops working on
 * both sides (middleware and backend) as soon as an admin exists.
 */
import type { Role, SessionUser } from "./access";
import { API_KEY, authDisabled, BACKEND_URL } from "./serverEnv";

export const SESSION_COOKIE = "auth_token";
export const SESSION_DAYS = 7;
const BOOTSTRAP_HOURS = 1;
/** How old the last account check may be before a request re-reads the account. */
export const RECHECK_SECONDS = 30;

const enc = new TextEncoder();
const ROLES: Role[] = ["admin", "general", "demo"];

export interface Session extends SessionUser {
  exp: number; // unix seconds
  chk?: number; // unix seconds of the last account check (absent on older cookies)
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

const nowSeconds = () => Math.floor(Date.now() / 1000);

/** A signed token for this account. ``exp`` keeps an existing session's expiry when re-signing. */
export async function makeSessionToken(user: SessionUser, exp?: number): Promise<{ token: string; maxAge: number }> {
  const now = nowSeconds();
  const expires = exp ?? now + (user.uid === 0 ? BOOTSTRAP_HOURS * 3600 : SESSION_DAYS * 86400);
  const session: Session = { uid: user.uid, email: user.email, name: user.name, role: user.role, exp: expires, chk: now };
  const body = b64urlEncode(JSON.stringify(session));
  return { token: `${body}.${await hmacHex(secret(), body)}`, maxAge: Math.max(expires - now, 0) };
}

/** Cookie settings for the session token (sign-in and every re-sign). */
export function sessionCookieOptions(maxAge: number) {
  return {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    maxAge,
    path: "/",
    sameSite: "lax" as const,
  };
}

export type Refresh =
  | { kind: "current" } // checked recently, or the check could not run: keep the cookie
  | { kind: "ended" } // the account is gone or disabled
  | { kind: "renewed"; session: Session; token: string; maxAge: number };

/**
 * Re-read a personal account from the backend when the cookie's last check is
 * older than RECHECK_SECONDS. A changed role or name comes back as a re-signed
 * token with the same expiry; a disabled or deleted account ends the session.
 * If the backend can't be reached the cookie is kept: the backend still checks
 * the account on every API call, so this only affects which pages show.
 */
export async function refreshSession(session: Session): Promise<Refresh> {
  if (session.uid === 0 || authDisabled()) return { kind: "current" };
  if (nowSeconds() - (session.chk ?? 0) < RECHECK_SECONDS) return { kind: "current" };
  let res: Response;
  try {
    res = await fetch(`${BACKEND_URL}/api/auth/me`, { headers: backendHeaders(session), cache: "no-store" });
  } catch {
    return { kind: "current" };
  }
  if (res.status === 401) return { kind: "ended" };
  if (!res.ok) return { kind: "current" };
  const u = await res.json().catch(() => null);
  if (!u || u.id !== session.uid || !ROLES.includes(u.role)) return { kind: "current" };
  const fresh: SessionUser = { uid: u.id, email: u.email, name: u.name, role: u.role };
  const { token, maxAge } = await makeSessionToken(fresh, session.exp);
  return { kind: "renewed", session: { ...fresh, exp: session.exp, chk: nowSeconds() }, token, maxAge };
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

/**
 * Headers for a backend call made on behalf of this session. A shared-login
 * session also says so (X-Dashboard-Bootstrap), and the backend refuses it
 * once an admin account exists, even though its cookie is still unexpired.
 */
export function backendHeaders(session: Session | null): Record<string, string> {
  const h: Record<string, string> = { "X-API-Key": API_KEY };
  if (session && session.uid > 0) h["X-Dashboard-User"] = String(session.uid);
  else if (session && session.uid === 0 && !authDisabled()) h["X-Dashboard-Bootstrap"] = "1";
  return h;
}

/** True while no active admin account exists, i.e. the shared env login may still be used. */
export async function bootstrapOpen(): Promise<boolean> {
  const res = await fetch(`${BACKEND_URL}/api/auth/status`, { headers: backendHeaders(null), cache: "no-store" });
  if (!res.ok) return false;
  const { active_admins } = await res.json();
  return active_admins === 0;
}
