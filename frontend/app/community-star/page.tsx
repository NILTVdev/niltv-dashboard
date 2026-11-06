import {
  getCommunityStarApplications, getCommunityStarProgram, getCommunityStarSummary, getCommunityStarVoteSummary,
} from "@/lib/api";
import CommunityStarView from "@/components/CommunityStarView";

export const dynamic = "force-dynamic";

export default async function CommunityStarPage() {
  const [applications, summary, program, votes] = await Promise.all([
    getCommunityStarApplications().catch(() => []),
    getCommunityStarSummary().catch(() => null),
    getCommunityStarProgram().catch(() => null),
    getCommunityStarVoteSummary().catch(() => null),
  ]);
  return <CommunityStarView initial={applications} summary={summary} program={program} votes={votes} />;
}
