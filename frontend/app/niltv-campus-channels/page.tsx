import { getCampusChannelsSummary } from "@/lib/api";
import CampusChannelsView from "@/components/CampusChannelsView";

export const dynamic = "force-dynamic";

export default async function NiltvCampusChannelsPage() {
  const summary = await getCampusChannelsSummary().catch(() => null);

  return <CampusChannelsView summary={summary} />;
}
