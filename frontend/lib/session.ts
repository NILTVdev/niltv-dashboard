/**
 * Dashboard session token: hex(HMAC-SHA256(key = DASHBOARD_PASSWORD,
 * data = DASHBOARD_USERNAME)). Implemented with Web Crypto so the same code
 * runs in the Edge middleware and in Node route handlers. The value is
 * identical to what Node's createHmac produced before, so existing cookies
 * stay valid.
 */
import { authDisabled } from "@/lib/serverEnv";

const enc = new TextEncoder();

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

export function makeSessionToken(username: string, password: string): Promise<string> {
  return hmacHex(password, username);
}

function equalHex(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

/** True when the cookie value is the current session token (always true when auth is disabled locally). */
export async function isValidSession(token: string | undefined | null): Promise<boolean> {
  if (authDisabled()) return true;
  const user = process.env.DASHBOARD_USERNAME;
  const pass = process.env.DASHBOARD_PASSWORD;
  if (!token || !user || !pass) return false;
  return equalHex(token, await makeSessionToken(user, pass));
}
