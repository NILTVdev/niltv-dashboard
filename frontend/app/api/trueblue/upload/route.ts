import { NextRequest, NextResponse } from "next/server";
import { backendHeaders, getSession, SESSION_COOKIE } from "@/lib/session";

import { BACKEND_URL as BACKEND } from "@/lib/serverEnv";

export async function POST(request: NextRequest) {
  // Auth check — validate hashed cookie token
  const session = await getSession(request.cookies.get(SESSION_COOKIE)?.value);
  if (!session) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  if (session.role !== "admin") {
    return NextResponse.json({ error: "Admins only" }, { status: 403 });
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
    headers: backendHeaders(session),
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
