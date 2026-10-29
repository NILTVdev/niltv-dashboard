import { describe, it, expect } from "vitest";
import { isJson, proxyTarget, sameBackendRedirect, sameOrigin } from "./requestGuards";

const BACKEND = "https://api.niltv.com";

describe("proxyTarget", () => {
  it("maps plain /api paths onto the backend, query included", () => {
    expect(proxyTarget(["api", "zoomph", "summary"], "?author=foo", BACKEND)?.href)
      .toBe("https://api.niltv.com/api/zoomph/summary?author=foo");
    expect(proxyTarget(["api", "applications", "12", "approve"], "", BACKEND)?.href)
      .toBe("https://api.niltv.com/api/applications/12/approve");
  });

  it("refuses segments that could leave the backend or climb the path", () => {
    // Next hands the handler decoded segments: %2F -> "/", %5C -> "\".
    for (const segments of [
      ["/attacker.example", "x"],
      ["\\attacker.example"],
      ["api", "/attacker.example"],
      ["api", ".."],
      ["api", "."],
      ["api", ""],
      ["api", "a b"],
      ["api", "x%2Fy"],
    ]) {
      expect(proxyTarget(segments, "", BACKEND)).toBeNull();
    }
  });

  it("only proxies the /api tree", () => {
    expect(proxyTarget(["docs"], "", BACKEND)).toBeNull();
    expect(proxyTarget([], "", BACKEND)).toBeNull();
  });
});

describe("sameBackendRedirect", () => {
  const from = new URL("https://api.niltv.com/api/users");

  it("follows FastAPI's trailing-slash redirect over the backend's own scheme", () => {
    expect(sameBackendRedirect("http://api.niltv.com/api/users/", from)?.href).toBe("https://api.niltv.com/api/users/");
    expect(sameBackendRedirect("/api/users/?limit=5", from)?.href).toBe("https://api.niltv.com/api/users/?limit=5");
  });

  it("never follows to another host or outside /api", () => {
    expect(sameBackendRedirect("https://attacker.example/api/users/", from)).toBeNull();
    expect(sameBackendRedirect("//attacker.example/api/", from)).toBeNull();
    expect(sameBackendRedirect("/docs", from)).toBeNull();
    expect(sameBackendRedirect(null, from)).toBeNull();
  });
});

describe("sameOrigin", () => {
  it("accepts the dashboard's own origin only", () => {
    expect(sameOrigin("https://dashboard.niltv.com", "dashboard.niltv.com")).toBe(true);
    expect(sameOrigin("http://localhost:3000", "localhost:3000")).toBe(true);
    expect(sameOrigin("https://niltv.com", "dashboard.niltv.com")).toBe(false);
    expect(sameOrigin("https://dashboard-dev.niltv.com", "dashboard.niltv.com")).toBe(false);
    expect(sameOrigin(null, "dashboard.niltv.com")).toBe(false);
    expect(sameOrigin("null", "dashboard.niltv.com")).toBe(false);
  });
});

describe("isJson", () => {
  it("accepts application/json with or without a charset, nothing else", () => {
    expect(isJson("application/json")).toBe(true);
    expect(isJson("application/json; charset=utf-8")).toBe(true);
    expect(isJson("text/plain")).toBe(false);
    expect(isJson("application/x-www-form-urlencoded")).toBe(false);
    expect(isJson(null)).toBe(false);
  });
});
