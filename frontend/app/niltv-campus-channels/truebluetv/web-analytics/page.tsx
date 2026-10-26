import { getGA4Snapshots, getGSCTotals, getGSCQueries, getGSCPages } from "@/lib/api";
import WebAnalyticsView from "@/components/WebAnalyticsView";

export const dynamic = "force-dynamic";

export default async function WebAnalyticsPage() {
  const [ga4Snapshots, gscTotals, gscQueries, gscPages] = await Promise.all([
    getGA4Snapshots(90),
    getGSCTotals(90),
    getGSCQueries(90),
    getGSCPages(90),
  ]);

  return (
    <WebAnalyticsView
      ga4Snapshots={ga4Snapshots}
      gscTotals={gscTotals}
      gscQueries={gscQueries}
      gscPages={gscPages}
      title="TrueBlue TV — Web Analytics"
      subtitle="truebluetv.com performance across Google Analytics and Search Console."
    />
  );
}
