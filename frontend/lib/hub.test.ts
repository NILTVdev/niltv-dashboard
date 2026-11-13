import { describe, it, expect } from "vitest";
import { askBody, EMPTY_ASK, fmtDay, safeHref, spotsLabel } from "./hub";

describe("askBody", () => {
  it("cleans the form into the API body", () => {
    const r = askBody({
      ...EMPTY_ASK,
      title: "  Training Table Trivia ",
      category: "Trivia",
      format: " Reel ",
      tags: "Football, lifestyle , football,,",
      summary: "",
      steps: "Film vertical\n\n  Post as a collab  \n",
      due_on: "2026-11-14",
      slots: "3",
    });
    expect(r).toEqual({
      body: {
        title: "Training Table Trivia",
        category: "Trivia",
        format: "Reel",
        tags: ["football", "lifestyle"],
        summary: null,
        steps: ["Film vertical", "Post as a collab"],
        due_on: "2026-11-14",
        slots: 3,
        status: "open",
      },
    });
  });

  it("leaves spots empty as open to all and the due date empty as none", () => {
    const r = askBody({ ...EMPTY_ASK, title: "Podcast pitch" });
    expect("body" in r && r.body.slots).toBe(null);
    expect("body" in r && r.body.due_on).toBe(null);
  });

  it("refuses a blank title and bad spots", () => {
    expect(askBody({ ...EMPTY_ASK, title: "   " })).toHaveProperty("error");
    for (const slots of ["0", "-2", "1.5", "two"]) {
      expect(askBody({ ...EMPTY_ASK, title: "x", slots })).toHaveProperty("error");
    }
  });
});

describe("labels", () => {
  it("describes spots", () => {
    expect(spotsLabel({ slots: null, spots_left: null })).toBe("Open to all");
    expect(spotsLabel({ slots: 5, spots_left: 3 })).toBe("3 of 5 left");
    expect(spotsLabel({ slots: 2, spots_left: 0 })).toBe("Full");
  });

  it("reads a due date as a calendar day", () => {
    expect(fmtDay("2026-11-14")).toBe("Nov 14");
    expect(fmtDay(null)).toBe("");
  });

  it("only links http(s) addresses", () => {
    expect(safeHref("https://instagram.com/reel/a")).toBe("https://instagram.com/reel/a");
    expect(safeHref("javascript:alert(1)")).toBe(null);
    expect(safeHref("not a link")).toBe(null);
    expect(safeHref(null)).toBe(null);
  });
});
