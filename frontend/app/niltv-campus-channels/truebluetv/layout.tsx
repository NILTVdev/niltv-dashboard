import ChannelSubNav from "@/components/ChannelSubNav";
import { viewerSession } from "@/lib/api";
import { TRUEBLUETV, TRUEBLUETV_TABS } from "@/lib/channels";

export default async function TrueBlueTVLayout({ children }: { children: React.ReactNode }) {
  // The middleware already sent anyone without a session to /login.
  const session = await viewerSession();

  return (
    <>
      <ChannelSubNav
        channel="TrueBlueTV"
        tabs={TRUEBLUETV_TABS}
        role={session?.role ?? "demo"}
        nested={{ [`${TRUEBLUETV}/athletes`]: `${TRUEBLUETV}/roster` }}
      />
      {children}
    </>
  );
}
