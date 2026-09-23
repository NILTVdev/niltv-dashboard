import { getApplications, getApplicationsSummary } from "@/lib/api";
import OnboardingView from "@/components/OnboardingView";

export const dynamic = "force-dynamic";

export default async function NiltvOnboardingPage() {
  const [applications, summary] = await Promise.all([
    getApplications("all").catch(() => []),
    getApplicationsSummary().catch(() => null),
  ]);
  return <OnboardingView initial={applications} summary={summary} />;
}
