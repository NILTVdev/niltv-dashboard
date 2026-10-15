import type { NextConfig } from "next";

// The TrueBlueTV pages moved under Campus Channels (lib/channels.ts); old
// bookmarks land on their new home. Not permanent, so browsers don't cache them.
const TRUEBLUETV = "/niltv-campus-channels/truebluetv";

const nextConfig: NextConfig = {
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "**.cdninstagram.com" },
      { protocol: "https", hostname: "**.fbcdn.net" },
    ],
  },
  async redirects() {
    return [
      { source: "/", destination: "/niltv", permanent: false },
      { source: "/player-details", destination: `${TRUEBLUETV}/player-details`, permanent: false },
      { source: "/zoomph", destination: `${TRUEBLUETV}/duke-owned`, permanent: false },
      { source: "/trueblue", destination: `${TRUEBLUETV}/trueblue-tv`, permanent: false },
      { source: "/web-analytics", destination: `${TRUEBLUETV}/web-analytics`, permanent: false },
      { source: "/athletes/:id", destination: `${TRUEBLUETV}/athletes/:id`, permanent: false },
    ];
  },
};

export default nextConfig;
