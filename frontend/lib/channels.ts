/**
 * Campus channels that have their own pages inside the Campus Channels
 * section. Client-safe (no env): the role table, the section sub-nav, the
 * section's landing redirect and the campus channels table all read it.
 */

export const CAMPUS_CHANNELS = "/niltv-campus-channels";

export const TRUEBLUETV = `${CAMPUS_CHANNELS}/truebluetv`;

export interface ChannelTab {
  href: string;
  label: string;
}

/** TrueBlueTV sub-nav, in display order. The first one a role can see is where the channel opens. */
export const TRUEBLUETV_TABS: ChannelTab[] = [
  { href: `${TRUEBLUETV}/roster`, label: "Roster" },
  { href: `${TRUEBLUETV}/player-details`, label: "Player Details" },
  { href: `${TRUEBLUETV}/duke-owned`, label: "Duke Owned" },
  { href: `${TRUEBLUETV}/trueblue-tv`, label: "TrueBlue TV" },
  { href: `${TRUEBLUETV}/web-analytics`, label: "Web Analytics" },
];

/** Channel key (as the campus channels summary reports it) -> its section page. */
export const CHANNEL_PAGES: Record<string, string> = {
  truebluetv: TRUEBLUETV,
};

export const athletePath = (id: number | string) => `${TRUEBLUETV}/athletes/${id}`;
