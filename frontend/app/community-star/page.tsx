import { getCommunityStarApplications, getCommunityStarSummary } from "@/lib/api";
import CommunityStarView from "@/components/CommunityStarView";

export const dynamic = "force-dynamic";

export default async function CommunityStarPage() {
  const [applications, summary] = await Promise.all([
    getCommunityStarApplications().catch(() => []),
    getCommunityStarSummary().catch(() => null),
  ]);
  return <CommunityStarView initial={applications} summary={summary} />;
}
