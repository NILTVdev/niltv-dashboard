import { getYoutubeAnalytics, getYoutubeStatus, getYoutubeSummary, getYoutubeVideos } from "@/lib/api";
import YoutubeView from "@/components/YoutubeView";

export const dynamic = "force-dynamic";

export default async function NiltvYoutubePage() {
  const [summary, videos, status, analytics] = await Promise.all([
    getYoutubeSummary().catch(() => null),
    getYoutubeVideos(500).catch(() => null),
    getYoutubeStatus().catch(() => null),
    getYoutubeAnalytics().catch(() => null),
  ]);

  return <YoutubeView summary={summary} videos={videos} status={status} analytics={analytics} />;
}
