import { NextRequest, NextResponse } from "next/server";
import { isValidSession } from "@/lib/session";

import { API_KEY, BACKEND_URL as BACKEND } from "@/lib/serverEnv";

export async function POST(request: NextRequest) {
  const token = request.cookies.get("auth_token")?.value;
  if (!(await isValidSession(token))) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const formData = await request.formData();
  const file = formData.get("file");
  if (!file || !(file instanceof File)) {
    return NextResponse.json({ error: "No file provided" }, { status: 400 });
  }

  const backendForm = new FormData();
  backendForm.append("file", file);

  const res = await fetch(`${BACKEND}/api/brand/network/upload-csv`, {
    method: "POST",
    headers: { "X-API-Key": API_KEY },
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
