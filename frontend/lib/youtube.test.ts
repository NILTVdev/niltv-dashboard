import { describe, it, expect } from "vitest";
import { filterVideos, fmtChange, fmtDuration, fmtHours, fmtPercent, sortVideos, viewsPerDay } from "./youtube";
import type { YoutubeVideo } from "./types";

const NOW = Date.parse("2026-11-18T12:00:00Z");
const daysAgo = (n: number) => new Date(NOW - n * 86_400_000).toISOString();

const video = (p: Partial<YoutubeVideo>): YoutubeVideo => ({
  video_id: "x", channel_id: "UCsample", title: "Sample", published_at: daysAgo(10),
  duration_sec: 600, is_short: false, thumbnail_url: null, views: 0, likes: 0, comments: 0,
  views_per_day: null, url: "https://www.youtube.com/watch?v=x", ...p,
});

const rows = [
  video({ video_id: "long_old", title: "Season recap", views: 10_000, published_at: daysAgo(100) }),
  video({ video_id: "short_new", title: "Game day hype", is_short: true, views: 2_000, published_at: daysAgo(2) }),
  video({ video_id: "unknown", title: "Practice", is_short: null, views: null, published_at: null }),
];

describe("fmtDuration", () => {
  it("formats seconds, minutes and hours", () => {
    expect(fmtDuration(45)).toBe("45s");
    expect(fmtDuration(185)).toBe("3:05");
    expect(fmtDuration(3723)).toBe("1:02:03");
    expect(fmtDuration(null)).toBe("—");
  });
});

describe("number formats", () => {
  it("formats hours, percentages and changes", () => {
    expect(fmtHours(12.34)).toBe("12.3");
    expect(fmtHours(1234.6)).toBe("1,235");
    expect(fmtPercent(55)).toBe("55.0%");
    expect(fmtPercent(null)).toBe("—");
    expect(fmtChange(12)).toBe("+12");
    expect(fmtChange(-3)).toBe("-3");
    expect(fmtChange(0)).toBe("0");
    expect(fmtChange(null)).toBe("—");
  });
});

describe("viewsPerDay", () => {
  it("divides by days since publish, at least one", () => {
    expect(viewsPerDay({ views: 1000, published_at: daysAgo(10) }, NOW)).toBeCloseTo(100);
    expect(viewsPerDay({ views: 500, published_at: daysAgo(0.25) }, NOW)).toBe(500);
    expect(viewsPerDay({ views: null, published_at: daysAgo(1) }, NOW)).toBeNull();
  });
});

describe("filterVideos", () => {
  it("splits Shorts from long-form; unknown length counts as long-form", () => {
    expect(filterVideos(rows, "shorts").map((v) => v.video_id)).toEqual(["short_new"]);
    expect(filterVideos(rows, "long").map((v) => v.video_id)).toEqual(["long_old", "unknown"]);
    expect(filterVideos(rows, "all")).toHaveLength(3);
  });

  it("searches titles without case", () => {
    expect(filterVideos(rows, "all", "  RECAP ").map((v) => v.video_id)).toEqual(["long_old"]);
  });
});

describe("sortVideos", () => {
  it("sorts highest first with unknown values last", () => {
    expect(sortVideos(rows, "views", NOW).map((v) => v.video_id)).toEqual(["long_old", "short_new", "unknown"]);
    expect(sortVideos(rows, "views_per_day", NOW).map((v) => v.video_id)).toEqual(["short_new", "long_old", "unknown"]);
    expect(sortVideos(rows, "published", NOW).map((v) => v.video_id)).toEqual(["short_new", "long_old", "unknown"]);
  });

  it("does not change the input", () => {
    const copy = [...rows];
    sortVideos(rows, "views_per_day", NOW);
    expect(rows).toEqual(copy);
  });
});
