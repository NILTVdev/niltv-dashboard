import { NextRequest, NextResponse } from "next/server";
import { PHOTO_MAX_BYTES, photoProblem } from "@/lib/communityStar";
import { positiveId, sameOrigin } from "@/lib/requestGuards";
import { backendHeaders, getSession, SESSION_COOKIE } from "@/lib/session";

import { BACKEND_URL as BACKEND } from "@/lib/serverEnv";

// The multipart wrapper adds a little on top of the file itself.
const MAX_REQUEST_BYTES = PHOTO_MAX_BYTES + 64 * 1024;

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const session = await getSession(request.cookies.get(SESSION_COOKIE)?.value);
  if (!session) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  if (session.role !== "admin") {
    return NextResponse.json({ error: "Admins only" }, { status: 403 });
  }
  if (!sameOrigin(request.headers.get("origin"), request.headers.get("host"))) {
    return NextResponse.json({ error: "Cross-site request refused" }, { status: 403 });
  }

  const { id } = await params;
  if (!positiveId(id)) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }
  if (Number(request.headers.get("content-length") ?? 0) > MAX_REQUEST_BYTES) {
    return NextResponse.json({ error: "Photos must be 5 MB or smaller" }, { status: 413 });
  }

  const formData = await request.formData().catch(() => null);
  const file = formData?.get("file");
  if (!file || !(file instanceof File)) {
    return NextResponse.json({ error: "No file provided" }, { status: 400 });
  }
  const problem = photoProblem(file);
  if (problem) {
    return NextResponse.json({ error: problem }, { status: 400 });
  }

  const backendForm = new FormData();
  backendForm.append("file", file);

  const res = await fetch(`${BACKEND}/api/community-star/applications/${id}/photo`, {
    method: "POST",
    headers: backendHeaders(session),
    body: backendForm,
    redirect: "manual",
  });

  const data = await res.json().catch(() => undefined);
  if (data === undefined) {
    return NextResponse.json({ error: "Unexpected response from the API" }, { status: 502 });
  }
  if (!res.ok) {
    return NextResponse.json({ error: data.detail ?? "Upload failed" }, { status: res.status });
  }

  return NextResponse.json(data);
}
