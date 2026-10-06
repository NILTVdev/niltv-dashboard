import { beforeAll, describe, expect, it, vi } from "vitest";
import { hasRole } from "./roles";

// Tokens signed by backend/auth.py make_session_token with DASHBOARD_API_KEY=test-key
// for {uid: 7, u: "jane", r: "onboarding", v: 3}: one expiring in 2096, one in 2001.
const VALID =
  "eyJ1aWQiOjcsInUiOiJqYW5lIiwiciI6Im9uYm9hcmRpbmciLCJ2IjozLCJleHAiOjQwMDA2MDQ4MDB9." +
  "b35894c86bb1b51bffa51f69a1439b769c8f56ca3391c29eb9b993a457a8b8e6";
const EXPIRED =
  "eyJ1aWQiOjcsInUiOiJqYW5lIiwiciI6Im9uYm9hcmRpbmciLCJ2IjozLCJleHAiOjEwMDA2MDQ4MDB9." +
  "910f71ff1852a6e2e0d2256720154b0768a12df6c7796585230e7a868ea371c8";

let readSession: typeof import("./session").readSession;

beforeAll(async () => {
  // serverEnv reads the key at import time.
  vi.stubEnv("DASHBOARD_API_KEY", "test-key");
  vi.stubEnv("AUTH_DISABLED", "");
  ({ readSession } = await import("./session"));
});

describe("readSession", () => {
  it("accepts a token the backend signed", async () => {
    expect(await readSession(VALID)).toEqual({ uid: 7, username: "jane", role: "onboarding", exp: 4000604800 });
  });

  it("rejects expired, tampered and malformed tokens", async () => {
    expect(await readSession(EXPIRED)).toBeNull();
    const [body, sig] = VALID.split(".");
    expect(await readSession(`${body}.${sig.replace(/^./, sig[0] === "0" ? "1" : "0")}`)).toBeNull();
    // Same signature over a payload claiming admin.
    const forged = btoa(JSON.stringify({ uid: 7, u: "jane", r: "admin", v: 3, exp: 4000604800 }))
      .replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_");
    expect(await readSession(`${forged}.${sig}`)).toBeNull();
    expect(await readSession("nonsense")).toBeNull();
    expect(await readSession(undefined)).toBeNull();
  });
});

describe("hasRole", () => {
  it("orders viewer < onboarding < admin", () => {
    expect(hasRole("admin", "onboarding")).toBe(true);
    expect(hasRole("onboarding", "onboarding")).toBe(true);
    expect(hasRole("viewer", "onboarding")).toBe(false);
    expect(hasRole("onboarding", "admin")).toBe(false);
    expect(hasRole(null, "viewer")).toBe(false);
  });
});
