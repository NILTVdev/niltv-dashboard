import { getAthletes } from "@/lib/api";
import PlayerDetailView from "@/components/PlayerDetailView";

export const dynamic = "force-dynamic";

export default async function PlayerDetailsPage() {
  const allAthletes = await getAthletes();
  const athletes = allAthletes.filter((a) => a.ig_followers != null);
  const sports = [...new Set(athletes.map((a) => a.sport).filter(Boolean) as string[])].sort();

  return (
    <div>
      <h1 className="text-xl font-bold text-[#0f172a] mb-1">Player Details</h1>
      <p className="text-sm text-[#64748b] mb-5">
        Select a sport and player to view their Instagram analytics.
      </p>
      <PlayerDetailView athletes={athletes} sports={sports} />
    </div>
  );
}
