import {
  getTrueBlueProfile,
  getTrueBluePosts,
  getTrueBlueSummary,
  getTrueBlueNetworkSummary,
  getTrueBlueTopAccounts,
  getTrueBlueNetworkPosts,
  getNetworkMetricsOverTime,
} from "@/lib/api";
import TrueBlueView from "@/components/TrueBlueView";

export const dynamic = "force-dynamic";

export default async function TrueBluePage() {
  const [profile, posts, summary, networkSummary, topAccounts, networkPosts, metricsOverTime] = await Promise.all([
    getTrueBlueProfile(),
    getTrueBluePosts(500),
    getTrueBlueSummary(),
    getTrueBlueNetworkSummary().catch(() => null),
    getTrueBlueTopAccounts().catch(() => []),
    getTrueBlueNetworkPosts(500).catch(() => []),
    getNetworkMetricsOverTime().catch(() => []),
  ]);

  return (
    <TrueBlueView
      profile={profile}
      posts={posts}
      summary={summary}
      networkSummary={networkSummary}
      topAccounts={topAccounts}
      networkPosts={networkPosts}
      metricsOverTime={metricsOverTime}
    />
  );
}
