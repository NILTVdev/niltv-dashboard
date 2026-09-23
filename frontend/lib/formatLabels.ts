/**
 * Post format labels for the canonical post_type vocabulary every ingest path
 * writes (backend/jobs/import_niltv_network.normalize_post_type):
 * REELS / IMAGE / CAROUSEL_ALBUM / VIDEO. FEED is the legacy Graph label for
 * "not a reel" that the nightly pull upgrades; OTHER is the untyped bucket.
 */
export const FORMAT_LABELS: Record<string, string> = {
  REELS: "Reels",
  IMAGE: "Images",
  CAROUSEL_ALBUM: "Carousels",
  VIDEO: "Video",
  FEED: "Feed",
  OTHER: "Untyped",
};

/** Human label for a post_type; unknown/legacy labels render as-is. */
export function formatLabel(postType: string | null | undefined): string {
  if (!postType) return "—";
  return FORMAT_LABELS[postType] ?? postType;
}
