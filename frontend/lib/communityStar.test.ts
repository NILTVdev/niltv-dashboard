import { describe, it, expect } from "vitest";
import {
  PHOTO_MAX_BYTES,
  cardValue,
  changedSettings,
  errorText,
  fmtET,
  localInputToIso,
  photoProblem,
  publishBlocker,
  unpublishBlocker,
  votesQuery,
} from "./communityStar";
import type { CommunityStarSettings } from "./types";

const times = {
  opens: "2026-11-02T14:00:00Z",
  closes: "2026-11-24T08:00:00Z",
  finalists: "2026-11-25T23:00:00Z",
  vote_opens: "2026-12-11T14:00:00Z",
  vote_closes: "2026-12-14T08:00:00Z",
};
const during = {
  server_time: "2026-12-12T12:00:00Z",
  times,
  finalists_published_at: "2026-11-24T15:00:00Z",
  top5_published_at: null,
  winners_published_at: null,
};
const after = { ...during, server_time: "2026-12-14T08:00:00Z" };
const marked = { finalists: 25, top5: 5, winners: 2 };

describe("publishBlocker", () => {
  it("needs a marked finalist before finalists can publish", () => {
    expect(publishBlocker("finalists", during, { ...marked, finalists: 0 })).toMatch(/finalist/);
    expect(publishBlocker("finalists", during, marked)).toBeNull();
  });

  it("holds the top 5 until the vote close, which is exclusive", () => {
    expect(publishBlocker("top5", during, marked)).toMatch(/Dec 14, 3:00 AM ET/);
    expect(publishBlocker("top5", after, marked)).toBeNull();
  });

  it("needs published finalists and marked rows before the top 5", () => {
    expect(publishBlocker("top5", { ...after, finalists_published_at: null }, marked)).toMatch(/finalists first/);
    expect(publishBlocker("top5", after, { ...marked, top5: 0 })).toMatch(/top 5 first/);
  });

  it("needs the top 5 published and a marked winner before winners", () => {
    expect(publishBlocker("winners", after, marked)).toMatch(/top 5/);
    const top5Out = { ...after, top5_published_at: "2026-12-14T15:00:00Z" };
    expect(publishBlocker("winners", top5Out, { ...marked, winners: 0 })).toMatch(/winner/);
    expect(publishBlocker("winners", top5Out, marked)).toBeNull();
  });
});

describe("unpublishBlocker", () => {
  it("takes stages down in reverse order", () => {
    const all = { ...after, top5_published_at: "2026-12-14T15:00:00Z", winners_published_at: "2026-12-18T15:00:00Z" };
    expect(unpublishBlocker("winners", all)).toBeNull();
    expect(unpublishBlocker("top5", all)).toMatch(/winners/);
    expect(unpublishBlocker("finalists", all)).toMatch(/top 5/);
    expect(unpublishBlocker("finalists", after)).toBeNull();
  });
});

describe("changedSettings", () => {
  const saved: CommunityStarSettings = {
    confirm_grace_minutes: 0,
    allow_pending_change: true,
    leaderboard_visible: true,
    board_min_votes: 1,
    card_order: "alphabetical",
    voting_paused: false,
  };

  it("sends nothing when nothing changed", () => {
    expect(changedSettings(saved, { ...saved })).toEqual({});
  });

  it("sends only the keys staff touched", () => {
    expect(changedSettings(saved, { ...saved, voting_paused: true, card_order: "shuffled" }))
      .toEqual({ voting_paused: true, card_order: "shuffled" });
  });
});

describe("photoProblem", () => {
  it("takes images up to the cap", () => {
    expect(photoProblem({ type: "image/jpeg", size: PHOTO_MAX_BYTES })).toBeNull();
    expect(photoProblem({ type: "image/heic", size: 10 })).toBeNull();
  });

  it("refuses other files and anything over the cap", () => {
    expect(photoProblem({ type: "application/pdf", size: 10 })).toMatch(/image/);
    expect(photoProblem({ type: "", size: 10 })).toMatch(/image/);
    expect(photoProblem({ type: "image/png", size: PHOTO_MAX_BYTES + 1 })).toMatch(/5 MB/);
  });
});

describe("votesQuery", () => {
  it("leaves out the filters that aren't set", () => {
    expect(votesQuery("all", null)).toBe("limit=500");
    expect(votesQuery("void", 12, 50)).toBe("limit=50&status=void&finalist_id=12");
  });
});

describe("errorText", () => {
  it("reads the backend's detail, then the route's error, then the status", () => {
    expect(errorText({ detail: "refused" }, 409)).toBe("refused");
    expect(errorText({ error: "Admins only" }, 403)).toBe("Admins only");
    expect(errorText({ detail: [{ loc: ["body"] }] }, 422)).toBe("HTTP 422");
    expect(errorText(null, 413)).toBe("HTTP 413");
  });
});

describe("times", () => {
  it("shows program times in Eastern whatever the viewer's zone", () => {
    expect(fmtET(times.finalists)).toBe("Nov 25, 6:00 PM ET");
    expect(fmtET(null)).toBe("");
    expect(fmtET("not a date")).toBe("");
  });

  it("turns a blank or broken clock input into null", () => {
    expect(localInputToIso("")).toBeNull();
    expect(localInputToIso("nope")).toBeNull();
    expect(localInputToIso("2026-12-12T09:30")).toMatch(/^2026-12-1[23]T\d\d:30:00\.000Z$/);
  });
});

describe("cardValue", () => {
  it("prefers a real override and falls back to the application", () => {
    expect(cardValue("Short Name", "Application Name")).toBe("Short Name");
    expect(cardValue("  ", "Application Name")).toBe("Application Name");
    expect(cardValue(null, "Application Name")).toBe("Application Name");
  });
});
