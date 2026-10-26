import type { NextConfig } from "next";

// The TrueBlueTV pages moved under Campus Channels (lib/channels.ts); old
// bookmarks land on their new home. Not permanent, so browsers don't cache them.
const TRUEBLUETV = "/niltv-campus-channels/truebluetv";

// Browser protections on every response. The dashboard is never meant to be
// framed (clickjacking on admin buttons), so framing is refused outright.
const SECURITY_HEADERS = [
  { key: "Strict-Transport-Security", value: "max-age=31536000" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Content-Security-Policy", value: "frame-ancestors 'none'" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
];

const nextConfig: NextConfig = {
  poweredByHeader: false,
  async headers() {
    return [{ source: "/:path*", headers: SECURITY_HEADERS }];
  },
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
