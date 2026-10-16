import { getZoomphPosts, getZoomphSummary, getZoomphAuthors, getZoomphImpressionsByDay } from "@/lib/api";
import ZoomphPageClient from "@/components/ZoomphPageClient";

export const dynamic = "force-dynamic";

export default async function ZoomphPage() {
  const [posts, summary, authors, impressionsByDay] = await Promise.all([
    getZoomphPosts(500),
    getZoomphSummary(),
    getZoomphAuthors(),
    getZoomphImpressionsByDay(),
  ]);

  return (
    <ZoomphPageClient
      posts={posts}
      summary={summary}
      authors={authors}
      impressionsByDay={impressionsByDay}
    />
  );
}
