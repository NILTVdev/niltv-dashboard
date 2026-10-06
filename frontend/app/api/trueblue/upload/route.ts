import { NextRequest, NextResponse } from "next/server";
import { hasRole } from "@/lib/roles";
import { backendHeaders } from "@/lib/serverSession";
import { readSession, SESSION_COOKIE } from "@/lib/session";

import { BACKEND_URL as BACKEND } from "@/lib/serverEnv";

export async function POST(request: NextRequest) {
  // Admin only; the backend checks the role again.
  const token = request.cookies.get(SESSION_COOKIE)?.value;
  const session = await readSession(token);
  if (!session) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  if (!hasRole(session.role, "admin")) {
    return NextResponse.json({ error: "Requires the admin role" }, { status: 403 });
  }

  // Forward the multipart form data to the backend
  const formData = await request.formData();
  const file = formData.get("file");
  if (!file || !(file instanceof File)) {
    return NextResponse.json({ error: "No file provided" }, { status: 400 });
  }

  const backendForm = new FormData();
  backendForm.append("file", file);

  const res = await fetch(`${BACKEND}/api/trueblue/network/upload-csv`, {
    method: "POST",
    headers: backendHeaders(token),
    body: backendForm,
  });

  const data = await res.json();

  if (!res.ok) {
    return NextResponse.json(
      { error: data.detail ?? "Import failed" },
      { status: res.status },
    );
  }

  return NextResponse.json(data);
}
