/**
 * Checks for the route handlers that call the backend with the API key
 * (the proxy, the CSV uploads, sign-in). Pure functions with no env or Next
 * imports, so vitest covers them directly.
 */

// Path segments the backend actually uses. Anything else (an encoded slash or
// backslash, a dot segment, an empty segment) could point the proxied URL at
// another host or route, so it never reaches fetch.
const SEGMENT = /^[A-Za-z0-9_~-][A-Za-z0-9._~-]*$/;

/** The backend URL for a proxied path, or null unless it is a plain /api/... path on the backend. */
export function proxyTarget(segments: string[], search: string, backend: string): URL | null {
  if (segments[0] !== "api" || !segments.every((s) => SEGMENT.test(s))) return null;
  const origin = new URL(backend).origin;
  const url = new URL(`/${segments.join("/")}`, origin);
  url.search = search;
  return url.origin === origin ? url : null;
}

/**
 * Where to follow a backend redirect (FastAPI sends /api/x to /api/x/): the
 * same /api/ path on the backend the request went to, over its own scheme.
 * Null for anything else, so the API key never follows a redirect elsewhere.
 */
export function sameBackendRedirect(location: string | null, from: URL): URL | null {
  if (!location) return null;
  let next: URL;
  try {
    next = new URL(location, from);
  } catch {
    return null;
  }
  if (next.hostname !== from.hostname || !next.pathname.startsWith("/api/")) return null;
  const url = new URL(next.pathname, from.origin);
  url.search = next.search;
  return url;
}

/**
 * True when a state-changing request came from a dashboard page. The session
 * cookie is SameSite=Lax, which other *.niltv.com sites still send, so the
 * cookie alone doesn't prove it. Browsers send Origin on every fetch POST.
 */
export function sameOrigin(origin: string | null, host: string | null): boolean {
  if (!origin || !host) return false;
  try {
    return new URL(origin).host === host;
  } catch {
    return false;
  }
}

/** A cross-site form can't send application/json without a CORS preflight, which never passes. */
export function isJson(contentType: string | null): boolean {
  return (contentType ?? "").split(";")[0].trim().toLowerCase() === "application/json";
}
