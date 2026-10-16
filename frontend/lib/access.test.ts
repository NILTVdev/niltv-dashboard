import { describe, it, expect } from "vitest";
import { canSeePage } from "./access";
import { CAMPUS_CHANNELS, TRUEBLUETV, TRUEBLUETV_TABS, athletePath } from "./channels";

const tab = (label: string) => TRUEBLUETV_TABS.find((t) => t.label === label)!.href;

describe("canSeePage", () => {
  it("lets every role open the campus channels section and its aggregate tabs", () => {
    for (const role of ["admin", "general", "demo"] as const) {
      expect(canSeePage(role, CAMPUS_CHANNELS)).toBe(true);
      expect(canSeePage(role, TRUEBLUETV)).toBe(true);
      expect(canSeePage(role, tab("Duke Owned"))).toBe(true);
      expect(canSeePage(role, tab("TrueBlue TV"))).toBe(true);
      expect(canSeePage(role, tab("Web Analytics"))).toBe(true);
    }
  });

  it("keeps athlete-level pages from demo even though they sit inside campus channels", () => {
    for (const path of [tab("Roster"), tab("Player Details"), athletePath(7)]) {
      expect(canSeePage("demo", path)).toBe(false);
      expect(canSeePage("general", path)).toBe(true);
      expect(canSeePage("admin", path)).toBe(true);
    }
  });

  it("keeps admin pages to admins", () => {
    for (const path of ["/niltv-onboarding", "/users", "/adminpage"]) {
      expect(canSeePage("general", path)).toBe(false);
      expect(canSeePage("demo", path)).toBe(false);
      expect(canSeePage("admin", path)).toBe(true);
    }
  });

  it("does not treat a shared prefix as the same page", () => {
    expect(canSeePage("demo", "/niltv-campus-channels-old")).toBe(false);
  });
});
