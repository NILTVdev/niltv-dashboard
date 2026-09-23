import { NextResponse } from "next/server";
import { API_KEY, BACKEND_URL } from "@/lib/serverEnv";

/**
 * Deploy health for this build. Public (see middleware.ts) and cheap.
 *
 * Makes the same server-side, keyed backend call every page makes and
 * reports whether it worked, plus the commit Amplify built (BUILD_COMMIT,
 * stamped by amplify.yml). The postBuild step in amplify.yml makes the same
 * call before a build is published; this route exposes the result afterwards
 * for operators. A key or URL mismatch between this build and its backend
 * shows here as a 503 with a reason instead of as a 500 on every page.
 */
export const dynamic = "force-dynamic";

export async function GET() {
  const commit = process.env.BUILD_COMMIT ?? null;
  const branch = process.env.BUILD_BRANCH ?? null;
  const base = { commit, branch, backend: BACKEND_URL };
  try {
    const res = await fetch(`${BACKEND_URL}/api/health/auth`, {
      headers: { "X-API-Key": API_KEY },
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });
    if (!res.ok) {
      return NextResponse.json(
        { ok: false, ...base, reason: `backend answered ${res.status}` },
        { status: 503 },
      );
    }
    const backend = (await res.json()) as { environment?: string };
    return NextResponse.json({ ok: true, ...base, backendEnvironment: backend.environment ?? null });
  } catch (e) {
    const reason = e instanceof Error ? e.message : "backend unreachable";
    return NextResponse.json({ ok: false, ...base, reason }, { status: 503 });
  }
}
