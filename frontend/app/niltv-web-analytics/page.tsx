import { getGA4Snapshots, getGSCTotals, getGSCQueries, getGSCPages } from "@/lib/api";
import WebAnalyticsView from "@/components/WebAnalyticsView";

export const dynamic = "force-dynamic";

export default async function NiltvWebAnalyticsPage() {
  const [ga4Snapshots, gscTotals, gscQueries, gscPages] = await Promise.all([
    getGA4Snapshots(90, "niltv"),
    getGSCTotals(90, "niltv"),
    getGSCQueries(90, "niltv"),
    getGSCPages(90, "niltv"),
  ]);

  return (
    <WebAnalyticsView
      ga4Snapshots={ga4Snapshots}
      gscTotals={gscTotals}
      gscQueries={gscQueries}
      gscPages={gscPages}
      title="NILTV.com — Web Analytics"
      subtitle="niltv.com performance across Google Analytics and Search Console."
    />
  );
}
