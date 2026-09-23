/**
 * Server-side environment for the Next.js layer (never imported by client
 * components). One place decides:
 *   - where the backend is (INTERNAL_API_URL),
 *   - which key the server attaches as X-API-Key (DASHBOARD_API_KEY, falling
 *     back to DASHBOARD_PASSWORD — the historical single-secret setup),
 *   - whether login is bypassed (AUTH_DISABLED=true, honoured only outside a
 *     production build, so an Amplify deploy can never run open).
 */
export const BACKEND_URL =
  process.env.INTERNAL_API_URL ?? "https://api.niltv.com";

export const API_KEY =
  process.env.DASHBOARD_API_KEY ?? process.env.DASHBOARD_PASSWORD ?? "";

export function authDisabled(): boolean {
  return (
    process.env.NODE_ENV !== "production" &&
    (process.env.AUTH_DISABLED ?? "").toLowerCase() === "true"
  );
}
