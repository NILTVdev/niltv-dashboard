import { describe, it, expect } from "vitest";
import {
  NO_FILTERS,
  activeFilterCount,
  athleteHref,
  athleteLabel,
  effectiveSort,
  filtersFromParams,
  fmtDuration,
  libraryHrefForAthlete,
  libraryQuery,
  pageQuery,
  staffAdminUrl,
  needsTagging,
  qcLabel,
  relativeTime,
  syncStatusLine,
  tagChips,
} from "./library";
import type { LibraryItem, LibraryStatus, LibrarySyncRun } from "./types";

const NOW = new Date("2026-11-18T15:00:00Z");

function item(over: Partial<LibraryItem> = {}): LibraryItem {
  return {
    content_id: "ig-1", stage: "dev", ig_post_id: "1", channel_id: "ch-niltv", channel_name: "NIL TV",
    title: "Sample clip", caption: null, summary: null, keywords: [], sport: null, school: null,
    content_type: null, content_types: [], categories: [], sponsor: null, athletes: [],
    unresolved_handles: [], status: "published", qc_state: "ready", poster_url: null, video_url: null,
    duration_sec: null, posted_at: null, updated_at: null, removed: false,
    first_seen_at: "2026-11-01T00:00:00Z", last_synced_at: "2026-11-18T14:00:00Z",
    performance: { matched: false, views: null, likes: null, comments: null, shares: null, saves: null,
                   reach: null, interactions: null, permalink: null },
    ...over,
  };
}

function run(over: Partial<LibrarySyncRun>): LibrarySyncRun {
  return { id: 1, received_at: "2026-11-18T13:00:00Z", stage: "dev", generated_at: null,
           received: 3, upserted: 3, removed: 0, ok: true, error: null, ...over };
}

describe("libraryQuery", () => {
  it("is empty with no filters", () => {
    expect(libraryQuery(NO_FILTERS)).toBe("");
  });

  it("sends search, facets and quick filters, trimmed", () => {
    const qs = libraryQuery(
      { q: "  duke hoops ", facets: { sport: "Basketball", category: "", qc_state: "needs-review",
        athlete: "jsample_hoops" },
        needsTagging: true, hasVideo: true, postedFrom: "2026-10-01", postedTo: "2026-10-31" },
      { sort: "views", limit: 48, offset: 96 },
    );
    const p = new URLSearchParams(qs);
    expect(p.get("q")).toBe("duke hoops");
    expect(p.get("sport")).toBe("Basketball");
    expect(p.has("category")).toBe(false);
    expect(p.get("qc_state")).toBe("needs-review");
    expect(p.get("needs_tagging")).toBe("true");
    expect(p.get("has_video")).toBe("true");
    expect(p.get("athlete")).toBe("jsample_hoops");
    expect(p.get("posted_from")).toBe("2026-10-01");
    expect(p.get("posted_to")).toBe("2026-10-31");
    expect(p.get("sort")).toBe("views");
    expect(p.get("limit")).toBe("48");
    expect(p.get("offset")).toBe("96");
  });

  it("falls back from best match to newest without a search", () => {
    expect(effectiveSort(NO_FILTERS, "relevance")).toBe("newest");
    expect(effectiveSort({ ...NO_FILTERS, q: "camp" }, "relevance")).toBe("relevance");
    expect(new URLSearchParams(libraryQuery(NO_FILTERS, { sort: "relevance" })).get("sort")).toBe("newest");
  });

  it("counts active filters, not the search", () => {
    expect(activeFilterCount({ ...NO_FILTERS, q: "x", facets: { sport: "Soccer", school: "" }, needsTagging: true })).toBe(2);
    expect(activeFilterCount({ ...NO_FILTERS, postedFrom: "2026-10-01", postedTo: "2026-10-31" })).toBe(2);
  });
});

describe("page URL", () => {
  const params = (q: string) => new URLSearchParams(q);

  it("reads filters and sort from the URL", () => {
    const { filters, sort } = filtersFromParams(params(
      "athlete=jsample_hoops&q=camp&sport=Basketball&needs_tagging=true&has_video=true"
      + "&posted_from=2026-10-01&posted_to=2026-10-31&sort=views"));
    expect(filters).toEqual({
      q: "camp", facets: { athlete: "jsample_hoops", sport: "Basketball" }, needsTagging: true, hasVideo: true,
      postedFrom: "2026-10-01", postedTo: "2026-10-31",
    });
    expect(sort).toBe("views");
  });

  it("drops unknown sorts and malformed dates", () => {
    const { filters, sort } = filtersFromParams(params("sort=random&posted_from=last-week&posted_to=2026-13-45&bogus=1"));
    expect(filters).toEqual(NO_FILTERS);
    expect(sort).toBe("relevance");
  });

  it("round-trips, and leaves the default sort out", () => {
    const filters = { ...NO_FILTERS, q: "hoops", facets: { school: "Sample State" }, postedFrom: "2026-09-01" };
    expect(pageQuery(NO_FILTERS, "relevance")).toBe("");
    const qs = pageQuery(filters, "newest");
    expect(params(qs).get("sort")).toBe("newest");
    expect(filtersFromParams(params(qs))).toEqual({ filters, sort: "newest" });
  });

  it("links an athlete's clips by bare lowercase handle", () => {
    expect(libraryHrefForAthlete("@JSample_Hoops")).toBe("/library?athlete=jsample_hoops");
  });
});

describe("staffAdminUrl", () => {
  it("is null when unset or not a web address", () => {
    expect(staffAdminUrl(undefined)).toBeNull();
    expect(staffAdminUrl("  ")).toBeNull();
    expect(staffAdminUrl("javascript:alert(1)")).toBeNull();
    expect(staffAdminUrl("not a url")).toBeNull();
  });

  it("keeps an http(s) address", () => {
    expect(staffAdminUrl("https://admin.example.com")).toBe("https://admin.example.com/");
    expect(staffAdminUrl(" http://localhost:5180 ")).toBe("http://localhost:5180/");
  });
});

describe("labels", () => {
  it("names QC states", () => {
    expect(qcLabel("needs-review")).toBe("Needs review");
    expect(qcLabel("needs_tagging")).toBe("Needs tagging");
    expect(qcLabel("ready")).toBe("Ready");
    expect(qcLabel(null)).toBe("Not checked");
  });

  it("treats anything but ready as needing tags", () => {
    expect(needsTagging({ qc_state: "ready" })).toBe(false);
    expect(needsTagging({ qc_state: "needs-review" })).toBe(true);
    expect(needsTagging({ qc_state: null })).toBe(true);
  });

  it("builds tag chips in order without repeats", () => {
    expect(tagChips(item({ sport: "Basketball", school: "Sample Tech", content_type: "highlight",
                           content_types: ["highlight", "Feature"], categories: ["Game Day", "feature"],
                           sponsor: " " }))).toEqual(["Basketball", "Sample Tech", "highlight", "Feature", "Game Day"]);
    expect(tagChips(item({ content_type: "interview" }))).toEqual(["interview"]);
    expect(tagChips(item())).toEqual([]);
  });

  it("labels athletes by name, then handle, then id", () => {
    expect(athleteLabel({ id: "a1", name: "Jordan Sample", handle: "js" })).toBe("Jordan Sample");
    expect(athleteLabel({ id: "a1", name: null, handle: "@js" })).toBe("@js");
    expect(athleteLabel({ id: "a1", name: null, handle: null })).toBe("a1");
  });

  it("formats durations", () => {
    expect(fmtDuration(24.5)).toBe("0:25");
    expect(fmtDuration(125)).toBe("2:05");
    expect(fmtDuration(null)).toBeNull();
    expect(fmtDuration(-1)).toBeNull();
  });
});

describe("sync status line", () => {
  const status = (over: Partial<LibraryStatus>): LibraryStatus => ({
    last_run: null, last_ok_run: null, items: 0, removed: 0, needs_tagging: 0, by_qc_state: [], ...over,
  });

  it("is null before the first good sync", () => {
    expect(syncStatusLine(null, NOW)).toBeNull();
    expect(syncStatusLine(status({ last_run: run({ ok: false }) }), NOW)).toBeNull();
  });

  it("says when and how many", () => {
    const ok = run({});
    expect(syncStatusLine(status({ last_run: ok, last_ok_run: ok, items: 698 }), NOW))
      .toBe("Last synced 2 hours ago. 698 clips.");
    expect(syncStatusLine(status({ last_run: ok, last_ok_run: ok, items: 1 }), NOW))
      .toBe("Last synced 2 hours ago. 1 clip.");
  });

  it("flags a failed sync after the last good one", () => {
    const ok = run({});
    const bad = run({ id: 2, ok: false, received_at: "2026-11-18T14:30:00Z" });
    expect(syncStatusLine(status({ last_run: bad, last_ok_run: ok, items: 5 }), NOW))
      .toBe("Last synced 2 hours ago. 5 clips. The latest sync failed 30 minutes ago.");
  });

  it("words relative times", () => {
    expect(relativeTime("2026-11-18T14:59:40Z", NOW)).toBe("just now");
    expect(relativeTime("2026-11-18T14:59:00Z", NOW)).toBe("1 minute ago");
    expect(relativeTime("2026-11-16T15:00:00Z", NOW)).toBe("2 days ago");
  });
});

describe("athleteHref", () => {
  it("links an athlete the directory knows to their page", () => {
    expect(athleteHref({ id: "a1", name: "Sample", handle: "sample", directory_key: "amb-12" })).toBe("/athletes/amb-12");
  });
  it("gives no link when the directory has no match", () => {
    expect(athleteHref({ id: "a1", name: "Sample", handle: "sample", directory_key: null })).toBeNull();
    expect(athleteHref({ id: "a1", name: "Sample", handle: "sample" })).toBeNull();
  });
});
