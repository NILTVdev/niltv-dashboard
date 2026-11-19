import {
  getNetworkScreenSummary, getNetworkScreenTopPosts, getYoutubeAnalytics, getYoutubeSummary, getYoutubeVideos,
} from "@/lib/api";
import NetworkScreenView from "@/components/NetworkScreenView";

export const dynamic = "force-dynamic";

interface Props {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function NiltvChannelsPage({ searchParams }: Props) {
  const raw = (await searchParams).platform;
  const platform = Array.isArray(raw) ? raw[0] : raw;
  const [monthSummary, mtdSummary, rolling30Summary, prevMonthSummary, topPosts, ytSummary, ytVideos, ytAnalytics] =
    await Promise.all([
      getNetworkScreenSummary("month").catch(() => null),
      getNetworkScreenSummary("mtd").catch(() => null),
      getNetworkScreenSummary("rolling30").catch(() => null),
      getNetworkScreenSummary("prevmonth").catch(() => null),
      getNetworkScreenTopPosts(20).catch(() => []),
      getYoutubeSummary().catch(() => null),
      getYoutubeVideos(500).catch(() => null),
      getYoutubeAnalytics().catch(() => null),
    ]);

  return (
    <NetworkScreenView
      summaries={{ month: monthSummary, mtd: mtdSummary, rolling30: rolling30Summary, prevmonth: prevMonthSummary }}
      topPosts={topPosts}
      youtube={{ summary: ytSummary, videos: ytVideos, analytics: ytAnalytics }}
      initialPlatform={platform}
    />
  );
}
