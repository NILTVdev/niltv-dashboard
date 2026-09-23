import { getBrandProfile, getNiltvNetworkPosts, getNiltvNetworkSummary } from "@/lib/api";
import NiltvView from "@/components/NiltvView";

export const dynamic = "force-dynamic";

export default async function NiltvPage() {
  const [profile, networkPosts, networkSummary] = await Promise.all([
    getBrandProfile().catch(() => null),
    getNiltvNetworkPosts(1000).catch(() => []),
    getNiltvNetworkSummary().catch(() => null),
  ]);

  return (
    <NiltvView
      profile={profile}
      networkPosts={networkPosts}
      networkSummary={networkSummary}
    />
  );
}
