import { getHubAsks, getHubQueue } from "@/lib/api";
import ContentHubView from "@/components/ContentHubView";

export const dynamic = "force-dynamic";

export default async function ContentHubPage() {
  const [asks, queue] = await Promise.all([
    getHubAsks("all").catch(() => null),
    getHubQueue().catch(() => null),
  ]);
  return <ContentHubView initialAsks={asks ?? []} initialQueue={queue ?? []} loadFailed={asks === null || queue === null} />;
}
