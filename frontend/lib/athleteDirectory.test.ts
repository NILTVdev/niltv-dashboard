import { describe, it, expect } from "vitest";
import {
  EMPTY_FILTERS, PAGE_SIZE, activeFilterCount, answerRows, clipsTitle, filtersFromParams, filtersToApiQuery,
  filtersToPageQuery, followerLabel, humanize, initials, personPath, resultRange, socialUrl, toGridPost,
} from "./athleteDirectory";
import type { DirectoryPost } from "./types";

const params = (q: string) => new URLSearchParams(q);

describe("filters <-> query strings", () => {
  it("reads known values and drops unknown ones", () => {
    const f = filtersFromParams(params("q=sam&sport=Golf&status=roster&sort=name&page=2&partner_consent=true&followers=1k-10k"));
    expect(f).toEqual({ ...EMPTY_FILTERS, q: "sam", sport: "Golf", status: "roster", sort: "name", page: 2,
      partner_consent: "true", followers: "1k-10k" });
    const bad = filtersFromParams(params("status=boss&sort=random&page=-3&partner_consent=maybe&followers=lots"));
    expect(bad).toEqual(EMPTY_FILTERS);
  });

  it("keeps the page URL short", () => {
    expect(filtersToPageQuery(EMPTY_FILTERS)).toBe("");
    expect(filtersToPageQuery({ ...EMPTY_FILTERS, q: " sam ", sort: "newest", page: 1 })).toBe("q=sam&sort=newest&page=1");
  });

  it("round-trips through the page URL", () => {
    const f = { ...EMPTY_FILTERS, school: "Sample State", campus: "samplestate", status: "applicant" as const, page: 3 };
    expect(filtersFromParams(params(filtersToPageQuery(f)))).toEqual(f);
  });

  it("turns the follower bucket into bounds and pages by PAGE_SIZE", () => {
    const api = params(filtersToApiQuery({ ...EMPTY_FILTERS, followers: "10k-100k", page: 2 }));
    expect(api.get("min_followers")).toBe("10000");
    expect(api.get("max_followers")).toBe("99999");
    expect(api.get("offset")).toBe(String(2 * PAGE_SIZE));
    expect(api.get("limit")).toBe(String(PAGE_SIZE));
    expect(api.get("sort")).toBe("followers");
    const open = params(filtersToApiQuery({ ...EMPTY_FILTERS, followers: "100k+" }, false));
    expect(open.get("min_followers")).toBe("100000");
    expect(open.has("max_followers")).toBe(false);
    expect(open.has("limit")).toBe(false);
  });

  it("counts active filters, not search or sort", () => {
    expect(activeFilterCount({ ...EMPTY_FILTERS, q: "x", sort: "name" })).toBe(0);
    expect(activeFilterCount({ ...EMPTY_FILTERS, sport: "Golf", partner_consent: "false" })).toBe(2);
  });
});

describe("labels", () => {
  it("makes initials", () => {
    expect(initials("Sam Q Sample")).toBe("SS");
    expect(initials("@handle")).toBe("HA");
    expect(initials("  ")).toBe("?");
  });

  it("marks self-reported follower counts", () => {
    expect(followerLabel({ followers: 12500, followers_self_reported: true })).toEqual({ text: "12.5K", selfReported: true });
    expect(followerLabel({ followers: null, followers_self_reported: false }).text).toBe("—");
  });

  it("describes the result range", () => {
    expect(resultRange(0, 0, 0)).toBe("0 athletes");
    expect(resultRange(1, 0, 1)).toBe("1 athlete");
    expect(resultRange(30, 0, 30)).toBe("30 athletes");
    expect(resultRange(120, 1, 50)).toBe("51 to 100 of 120 athletes");
  });

  it("encodes person keys in links", () => {
    expect(personPath("amb-12")).toBe("/athletes/amb-12");
  });

  it("builds social links from handles or full URLs", () => {
    expect(socialUrl("instagram", "@sam")).toBe("https://instagram.com/sam");
    expect(socialUrl("tiktok", "sam")).toBe("https://www.tiktok.com/@sam");
    expect(socialUrl("youtube", "https://youtube.com/c/sam")).toBe("https://youtube.com/c/sam");
    expect(socialUrl("x", null)).toBeNull();
  });

  it("humanizes answer keys and skips nested answers", () => {
    expect(humanize("nilDealsWanted")).toBe("Nil deals wanted");
    expect(answerRows({ favoriteSport: "Golf", count: 3, ok: true, list: ["a", "b"], nested: { a: 1 }, blank: " " }))
      .toEqual([
        { label: "Favorite sport", value: "Golf" },
        { label: "Count", value: "3" },
        { label: "Ok", value: "Yes" },
        { label: "List", value: "a, b" },
      ]);
    expect(answerRows(null)).toEqual([]);
    expect(answerRows(["x"])).toEqual([]);
  });
});

describe("toGridPost", () => {
  const base: DirectoryPost = {
    post_id: "p1", account_username: "sam", description: "Caption", publish_time: "2026-09-01T00:00:00Z",
    permalink: "https://instagram.com/p/x", post_type: "VIDEO", media_url: "https://cdn.example.com/v.mp4",
    thumbnail_url: null, views: 10, likes: 2, comments: 1, shares: null, saves: null,
  };

  it("never uses a video file as an image", () => {
    expect(toGridPost(base, 0).media_url).toBeNull();
    expect(toGridPost({ ...base, thumbnail_url: "https://cdn.example.com/t.jpg" }, 0).media_url)
      .toBe("https://cdn.example.com/t.jpg");
    expect(toGridPost({ ...base, post_type: "IMAGE", media_url: "https://cdn.example.com/i.jpg" }, 0).media_url)
      .toBe("https://cdn.example.com/i.jpg");
  });

  it("maps counts and ids", () => {
    const p = toGridPost(base, 4);
    expect(p).toMatchObject({ id: 4, ig_post_id: "p1", like_count: 2, comment_count: 1, caption: "Caption" });
  });
});

describe("clipsTitle", () => {
  it("names the count, and says when only the newest are shown", () => {
    expect(clipsTitle(0, 0)).toBe("Library clips");
    expect(clipsTitle(3, 3)).toBe("Library clips (3)");
    expect(clipsTitle(24, 1500)).toBe("Library clips (newest 24 of 1.5K)");
  });
});
