import { fmt } from "@/lib/utils";
import type { GA4Summary, GSCSummary } from "@/lib/types";
import {
  Users, Eye, MousePointerClick, ArrowUpDown,
  TrendingUp, Search,
} from "lucide-react";

interface Props {
  ga4: GA4Summary;
  gsc: GSCSummary;
}

export default function WebAnalyticsKPIs({ ga4, gsc }: Props) {
  const cards = [
    { label: "Clicks", value: fmt(gsc.total_clicks), icon: Search },
    { label: "Impressions", value: fmt(gsc.total_impressions), icon: Eye },
    { label: "Avg CTR", value: `${(gsc.avg_ctr * 100).toFixed(2)}%`, icon: TrendingUp },
    { label: "Avg Position", value: gsc.avg_position.toFixed(1), icon: ArrowUpDown },
    { label: "Sessions", value: fmt(ga4.total_sessions), icon: Eye },
    { label: "Users", value: fmt(ga4.total_users), icon: Users },
    { label: "Pageviews", value: fmt(ga4.total_pageviews), icon: MousePointerClick },
    { label: "Bounce Rate", value: `${(ga4.avg_bounce_rate * 100).toFixed(1)}%`, icon: ArrowUpDown },
  ];

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
      {cards.map((c) => (
        <div
          key={c.label}
          className="bg-white rounded-xl border border-[#e2e8f0] shadow-sm p-4"
        >
          <div className="flex items-center gap-2 text-[#64748b] mb-2">
            <c.icon size={14} />
            <p className="text-xs">{c.label}</p>
          </div>
          <p className="text-2xl font-bold text-[var(--brand)]">{c.value}</p>
        </div>
      ))}
    </div>
  );
}
