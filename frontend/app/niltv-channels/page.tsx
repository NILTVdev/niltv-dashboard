import { getNetworkScreenSummary, getNetworkScreenTopPosts } from "@/lib/api";
import NetworkScreenView from "@/components/NetworkScreenView";

export const dynamic = "force-dynamic";

export default async function NiltvChannelsPage() {
  const [monthSummary, mtdSummary, rolling30Summary, prevMonthSummary, topPosts] = await Promise.all([
    getNetworkScreenSummary("month").catch(() => null),
    getNetworkScreenSummary("mtd").catch(() => null),
    getNetworkScreenSummary("rolling30").catch(() => null),
    getNetworkScreenSummary("prevmonth").catch(() => null),
    getNetworkScreenTopPosts(20).catch(() => []),
  ]);

  return (
    <NetworkScreenView
      summaries={{ month: monthSummary, mtd: mtdSummary, rolling30: rolling30Summary, prevmonth: prevMonthSummary }}
      topPosts={topPosts}
    />
  );
}
