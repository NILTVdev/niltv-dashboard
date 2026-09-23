import { NextRequest, NextResponse } from "next/server";
import { authDisabled } from "@/lib/serverEnv";
import { makeSessionToken } from "@/lib/session";

export async function POST(request: NextRequest) {
  const { username, password } = await request.json();
  const expectedUser = process.env.DASHBOARD_USERNAME;
  const expectedPass = process.env.DASHBOARD_PASSWORD;

  // LOCAL environment: any credentials log in (middleware already lets every
  // page through; this keeps the login page itself working).
  const bypass = authDisabled();

  if (
    !bypass &&
    (!expectedUser ||
      !expectedPass ||
      username !== expectedUser ||
      password !== expectedPass)
  ) {
    return NextResponse.json(
      { error: "Invalid username or password" },
      { status: 401 },
    );
  }

  const token = bypass
    ? await makeSessionToken(expectedUser ?? "local", expectedPass ?? "local")
    : await makeSessionToken(username, password);
  const response = NextResponse.json({ ok: true });
  response.cookies.set("auth_token", token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    maxAge: 60 * 60 * 24 * 7, // 7 days
    path: "/",
    sameSite: "lax",
  });
  return response;
}

export async function DELETE() {
  const response = NextResponse.json({ ok: true });
  response.cookies.delete("auth_token");
  return response;
}

