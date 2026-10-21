import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getSession, makeSessionToken, RECHECK_SECONDS, refreshSession, type Session } from "./session";

const ADMIN = { uid: 7, email: "staff@niltv.com", name: "Staff", role: "admin" as const };

function me(body: unknown, status = 200) {
  return vi.fn(async () => new Response(JSON.stringify(body), { status }));
}

async function sessionCheckedSecondsAgo(seconds: number): Promise<Session> {
  const { token } = await makeSessionToken(ADMIN);
  const s = (await getSession(token))!;
  return { ...s, chk: (s.chk ?? 0) - seconds };
}

beforeEach(() => {
  process.env.DASHBOARD_SESSION_SECRET = "test-secret";
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("refreshSession", () => {
  it("leaves a recently checked session alone without calling the backend", async () => {
    const fetchMock = me({});
    vi.stubGlobal("fetch", fetchMock);
    const r = await refreshSession(await sessionCheckedSecondsAgo(1));
    expect(r.kind).toBe("current");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("picks up a role change and keeps the original expiry", async () => {
    vi.stubGlobal("fetch", me({ id: 7, email: "staff@niltv.com", name: "Staff", role: "general" }));
    const old = await sessionCheckedSecondsAgo(RECHECK_SECONDS + 5);
    const r = await refreshSession(old);
    expect(r.kind).toBe("renewed");
    if (r.kind !== "renewed") return;
    expect(r.session.role).toBe("general");
    const reread = await getSession(r.token);
    expect(reread?.role).toBe("general");
    expect(reread?.exp).toBe(old.exp);
  });

  it("ends the session when the account is disabled or gone", async () => {
    vi.stubGlobal("fetch", me({ detail: "Account not found or disabled" }, 401));
    const r = await refreshSession(await sessionCheckedSecondsAgo(RECHECK_SECONDS + 5));
    expect(r.kind).toBe("ended");
  });

  it("keeps the cookie when the backend can't be reached", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("offline"); }));
    expect((await refreshSession(await sessionCheckedSecondsAgo(RECHECK_SECONDS + 5))).kind).toBe("current");
    vi.stubGlobal("fetch", me({}, 502));
    expect((await refreshSession(await sessionCheckedSecondsAgo(RECHECK_SECONDS + 5))).kind).toBe("current");
  });

  it("re-checks cookies issued before the check time existed", async () => {
    const fetchMock = me({ id: 7, email: "staff@niltv.com", name: "Staff", role: "admin" });
    vi.stubGlobal("fetch", fetchMock);
    const { chk: _drop, ...legacy } = await sessionCheckedSecondsAgo(0);
    void _drop;
    const r = await refreshSession(legacy as Session);
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(r.kind).toBe("renewed");
  });

  it("never re-checks the shared login", async () => {
    const fetchMock = me({});
    vi.stubGlobal("fetch", fetchMock);
    const { token } = await makeSessionToken({ uid: 0, email: "shared login", name: "Shared login", role: "admin" });
    const s = (await getSession(token))!;
    expect((await refreshSession({ ...s, chk: 0 })).kind).toBe("current");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
