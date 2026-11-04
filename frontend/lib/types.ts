export interface Athlete {
  id: number;
  name: string;
  sport: string | null;
  year: string | null;
  ig_handle: string | null;
  tiktok_handle: string | null;
  x_handle: string | null;
  active: boolean;
  ig_followers: number | null;
  ig_posts: number | null;
  tiktok_followers: number | null;
  x_followers: number | null;
  last_pulled: string | null;
  social_valuation: number | null;
  ig_engagement: number | null;
  attributed_engagement: number | null;
}

export interface Snapshot {
  id: number;
  athlete_id: number;
  pulled_at: string;
  ig_followers: number | null;
  ig_posts: number | null;
  ig_bio: string | null;
  tiktok_followers: number | null;
  tiktok_likes: number | null;
  x_followers: number | null;
  x_posts: number | null;
}

export interface Post {
  id: number;
  athlete_id: number;
  ig_post_id: string;
  posted_at: string | null;
  media_type: string | null;
  like_count: number | null;
  comment_count: number | null;
  permalink: string | null;
  caption: string | null;
  media_url: string | null;
}

export interface ZoomphPost {
  id: number;
  pulled_at: string;
  post_id: string;
  partner: string | null;
  platform: string | null;
  content_type: string | null;
  author: string | null;
  url: string | null;
  message: string | null;
  engagement: number | null;
  like_count: number | null;
  impressions: number | null;
  brand_exposure_value: number | null;
  /** Server-side CPM/CPE/CPV valuation; null when the API has no rate card configured. */
  valuation: number | null;
  vod_views: number | null;
  live_views: number | null;
  posted_at: string | null;
}

export interface ZoomphSummary {
  platform: string | null;
  post_count: number;
  total_engagement: number;
  total_impressions: number;
  total_likes: number;
  total_bev: number;
}

export interface ZoomphDailyImpressions {
  date: string;
  impressions: number;
}

// ── NILTV Brand Instagram ──────────────────────────────

export interface BrandSnapshot {
  id: number;
  pulled_at: string;
  username: string | null;
  followers: number | null;
  post_count: number | null;
  bio: string | null;
}

export interface BrandPost {
  id: number;
  account: string;
  ig_post_id: string;
  posted_at: string | null;
  media_type: string | null;
  caption: string | null;
  like_count: number | null;
  comment_count: number | null;
  permalink: string | null;
  media_url: string | null;
  impressions: number | null;
  reach: number | null;
  saves: number | null;
  views: number | null;
  shares: number | null;
  pulled_at: string | null;
}

export interface BrandSummary {
  total_posts: number;
  total_likes: number;
  total_comments: number;
  total_impressions: number;
  total_reach: number;
  total_saves: number;
  total_views: number;
  avg_likes: number;
  avg_comments: number;
  avg_impressions: number;
}

// ── NILTV Network Posts ────────────────────────────────

export interface NiltvNetworkPost {
  id: number;
  post_id: string;
  /** who last wrote views: graph | export | bd | public (see backend VIEWS_RANK) */
  views_source?: string | null;
  account_username: string | null;
  account_name: string | null;
  description: string | null;
  duration_sec: number | null;
  publish_time: string | null;
  permalink: string | null;
  post_type: string | null;
  views: number | null;
  likes: number | null;
  shares: number | null;
  comments: number | null;
  saves: number | null;
  reach: number | null;
  projected_reach: number | null;
  follows: number | null;
}

export interface NiltvNetworkSummary {
  total_posts: number;
  total_views: number;
  total_likes: number;
  total_comments: number;
  total_shares: number;
  total_saves: number;
  total_reach: number;
  unique_accounts: number;
  avg_likes: number;
}

// ── TrueBlue TV ────────────────────────────────────────

export interface TrueBlueSnapshot {
  id: number;
  pulled_at: string;
  followers: number | null;
  following: number | null;
  post_count: number | null;
  bio: string | null;
}

export interface TrueBluePost {
  id: number;
  shortcode: string;
  posted_at: string | null;
  media_type: string | null;
  caption: string | null;
  like_count: number | null;
  comment_count: number | null;
  permalink: string | null;
  media_url: string | null;
  is_video: boolean | null;
  video_view_count: number | null;
  pulled_at: string | null;
}

export interface TrueBlueSummary {
  total_posts: number;
  total_likes: number;
  total_comments: number;
  total_video_views: number;
  avg_likes: number;
  avg_comments: number;
}

export interface TrueBlueNetworkSummary {
  total_posts: number;
  total_views: number;
  total_likes: number;
  total_comments: number;
  total_shares: number;
  total_saves: number;
  total_follows: number;
  total_reach: number;
  total_projected_reach: number;
  unique_accounts: number;
  avg_likes: number;
}

export interface TrueBlueTopAccount {
  account_username: string;
  account_name: string;
  post_count: number;
  total_views: number;
  total_likes: number;
  total_comments: number;
}

export interface TrueBlueNetworkPost {
  id: number;
  post_id: string;
  account_username: string | null;
  account_name: string | null;
  description: string | null;
  duration_sec: number | null;
  publish_time: string | null;
  permalink: string | null;
  post_type: string | null;
  views: number | null;
  likes: number | null;
  shares: number | null;
  comments: number | null;
  saves: number | null;
  reach: number | null;
  follows: number | null;
  projected_reach: number | null;
}

export interface TrueBlueNetworkPostSnapshot {
  id: number;
  network_post_id: number;
  captured_at: string;
  views: number | null;
  likes: number | null;
  shares: number | null;
  comments: number | null;
  saves: number | null;
  reach: number | null;
  projected_reach: number | null;
  follows: number | null;
}

export interface NetworkMetricsOverTime {
  date: string;
  total_views: number;
  total_likes: number;
  total_comments: number;
  total_shares: number;
  total_saves: number;
  total_reach: number;
  total_projected_reach: number;
}

// ── Web Analytics ──────────────────────────────────────

export interface GA4Snapshot {
  id: number;
  date: string;
  pulled_at: string;
  sessions: number | null;
  total_users: number | null;
  pageviews: number | null;
  bounce_rate: number | null;
  engagement_rate: number | null;
  source: string | null;
  medium: string | null;
}

/** Accurate daily totals from date-only dimension (no anonymization). */
export interface GSCDailyTotal {
  id: number;
  date: string;
  clicks: number | null;
  impressions: number | null;
  ctr: number | null;
  position: number | null;
}

/** Per-query GSC snapshot (subject to anonymization for low-volume queries). */
export interface GSCQuerySnapshot {
  id: number;
  date: string;
  query: string;
  clicks: number | null;
  impressions: number | null;
  ctr: number | null;
  position: number | null;
}

/** Per-page GSC snapshot (subject to anonymization for low-volume pages). */
export interface GSCPageSnapshot {
  id: number;
  date: string;
  page: string;
  clicks: number | null;
  impressions: number | null;
  ctr: number | null;
  position: number | null;
}

export interface GA4Summary {
  total_sessions: number;
  total_users: number;
  total_pageviews: number;
  avg_bounce_rate: number;
  avg_engagement_rate: number;
  traffic_sources: {
    source: string;
    medium: string;
    sessions: number;
    users: number;
  }[];
}

export interface GSCSummary {
  total_clicks: number;
  total_impressions: number;
  avg_ctr: number;
  avg_position: number;
  top_queries: {
    query: string;
    clicks: number;
    impressions: number;
    avg_ctr: number;
    avg_position: number;
  }[];
  top_pages: {
    page: string;
    clicks: number;
    impressions: number;
    avg_ctr: number;
    avg_position: number;
  }[];
}

// ── Network Screen (Channel Insights) ─────────────────────────────────────────

export interface NetworkScreenFormatStats {
  posts: number;
  posts_with_views: number;
  total_views: number;
  avg_views: number;
  engagement_rate: number | null;
}

export interface NetworkScreenMonthStats {
  followers: number | null;
  new_followers_monthly: number | null;
  new_followers_weekly: number | null;
  posts_monthly: number;
  posts_weekly: number;
  avg_posts_per_week: number;
  total_views_monthly: number;
  total_views_weekly: number;
  posts_with_views_monthly: number;
  avg_views_per_post: number | null;
  format_breakdown: Record<string, NetworkScreenFormatStats>;
  engagement_rate_overall: number | null;
  collabs_published_monthly: number;
  collab_data_warning: boolean;
}

export interface NetworkScreenRatios {
  weekly_views_to_followers: number | null;
  views_per_post_to_followers: number | null;
  avg_views_per_reel: number | null;
  engagement_rate_reels: number | null;
}

export interface NetworkScreenPlatform {
  platform: string;
  available: boolean;
  current_month: NetworkScreenMonthStats | null;
  prior_month: NetworkScreenMonthStats | null;
  ratios: NetworkScreenRatios | null;
}

export interface NetworkScreenAggregate {
  total_followers: number;
  total_views_monthly: number;
  total_posts_monthly: number;
  platforms_live: number;
  platforms_total: number;
}

export interface NetworkScreenWeeklyStats {
  start: string;
  end: string;
  posts: number;
  views: number;
  new_followers: number | null;
}

export interface NetworkScreenWeeklyComparison {
  current: NetworkScreenWeeklyStats;
  previous: NetworkScreenWeeklyStats;
}

export interface NetworkScreenSummary {
  platforms: NetworkScreenPlatform[];
  aggregate: NetworkScreenAggregate;
  weekly_comparison?: NetworkScreenWeeklyComparison;
}

export interface NetworkScreenTopPost {
  id: number;
  post_id: string;
  publish_time: string | null;
  post_type: string | null;
  views: number | null;
  likes: number | null;
  comments: number | null;
  shares: number | null;
  saves: number | null;
  reach: number | null;
  permalink: string | null;
  thumbnail_url: string | null;
  description: string | null;
}


// ── Campus Channels ──────────────────────────────────────────────────────────

export interface CampusChannelWindowStats {
  posts: number;
  /** null when the window holds no view data at all (distinct from zero views). */
  views: number | null;
  posts_with_views: number;
}

export interface CampusChannelSummary {
  channel: string;
  label: string;
  last_month: CampusChannelWindowStats;
  current_month: CampusChannelWindowStats;
  last_30_days: CampusChannelWindowStats;
  all_time: CampusChannelWindowStats;
  /** Post count per views_source: graph | export | bd | public | unknown. */
  views_by_source: Record<string, number>;
  latest_post_at: string | null;
  bd_only: boolean;
  monthly_growth?: CampusChannelViewGrowth[];
  last_30_days_growth?: CampusChannelViewGrowth;
  last_7_days_growth?: CampusChannelViewGrowth;
}

export interface CampusChannelViewGrowth {
  start: string;
  end: string;
  views_gained: number | null;
  posts_measured: number;
  posts_missing_baseline: number;
  regressed_posts: number;
  coverage_pct: number;
}

export interface CampusChannelWindowRange {
  start: string;
  end: string;
}

export interface CampusChannelsSummary {
  generated_at: string;
  windows: Record<string, CampusChannelWindowRange>;
  channels: CampusChannelSummary[];
}


// ── Athlete onboarding (applications) ────────────────────────────────────────

export type ApplicationStatus =
  | "applicant" | "approved" | "declined" | "agreement_sent"
  | "signed" | "stripe_pending" | "accepted";

export interface ApplicationStep {
  key: "applied" | "reviewed" | "agreement" | "stripe" | "accepted";
  label: string;
  state: "done" | "current" | "todo" | "skipped" | "blocked";
  detail: string | null;
  at: string | null;
}

export interface ApplicationEvent {
  at: string | null;
  kind: string;
  actor: string | null;
  detail: Record<string, unknown> | null;
}

export interface Application {
  id: number;
  ambassador_id: number | null;
  email: string;
  college_email: string | null;
  phone: string | null;
  first_name: string | null;
  last_name: string | null;
  university: string | null;
  sport: string | null;
  year: string | null;
  campus_channel: string | null;
  roster_link: string | null;
  international: boolean | null;
  instagram: string | null;
  instagram_followers: string | null;
  tiktok: string | null;
  tiktok_followers: string | null;
  youtube: string | null;
  youtube_subscribers: string | null;
  other_followers: string | null;
  nil_deals_done: string | null;
  nil_deals_wanted: string | null;
  purpose: string | null;
  content_type: string | null;
  description: string | null;
  confirm_age: boolean;
  consent_terms: boolean;
  consent_program_email: boolean;
  consent_sms: boolean;
  consent_marketing: boolean;
  consent_partners: boolean;
  consent_version: string | null;
  consent_at: string | null;
  source: string;
  submit_count: number;
  status: ApplicationStatus;
  decline_reason: string | null;
  reviewed_at: string | null;
  reviewed_by: string | null;
  docusign_envelope_id: string | null;
  docusign_status: string | null;
  agreement_sent_at: string | null;
  agreement_reminded_at?: string | null;
  signed_at: string | null;
  stripe_account_id: string | null;
  stripe_payouts_enabled: boolean | null;
  stripe_requirements_due: string[] | null;
  stripe_disabled_reason: string | null;
  stripe_link_sent_at: string | null;
  stripe_checked_at: string | null;
  accepted_at: string | null;
  notes: string | null;
  created_at: string | null;
  updated_at: string | null;
  progress: ApplicationStep[];
  payout_link: string | null;
  missing_for_approval: string[];
  campus_channel_label: string | null;
  // detail only
  answers?: Record<string, unknown> | null;
  events?: ApplicationEvent[];
}

export interface ApplicationsSummary {
  total: number;
  by_status: Record<ApplicationStatus, number>;
  in_progress: number;
  by_school: Record<string, number>;
  by_sport: Record<string, number>;
  by_channel: Record<string, { label: string; count: number }>;
  applied_this_month: number;
  schools: string[];
  sports: string[];
  integrations: {
    docusign: boolean;
    docusign_powerform: boolean;
    stripe: boolean;
    payout_links: boolean;
    email: boolean;
  };
}

export interface ReconcileChange {
  id: number;
  name: string;
  source: "docusign" | "stripe";
  from: string;
  to: string;
}

/** One "Refresh all" / nightly re-check of every open application. */
export interface ReconcileRun {
  id: number;
  trigger: "nightly" | "staff";
  triggered_by: string | null;
  started_at: string;
  finished_at: string | null;
  error: string | null;
  stats: {
    scope?: "all" | "open" | "agreement_sent" | "stripe_pending" | "accepted";
    rows?: number;
    docusign_checked?: number;
    stripe_checked?: number;
    changed?: number;
    signed?: number;
    accepted?: number;
    signed_no_stripe?: number;
    errors?: number;
    changes?: ReconcileChange[];
  };
}

// ── Community Star (backend/routers/community_star.py) ───────────────────────

export type CommunityStarStage = "applied" | "shortlist" | "finalist" | "top5" | "winner" | "disqualified";

export interface CommunityStarApplication {
  id: number;
  season: string;
  created_at: string;
  full_name: string;
  email: string;
  phone: string;
  school: string;
  school_state: string | null;
  school_matched: boolean;
  sport: string;
  class_year: string;
  instagram: string;
  post_url: string;
  community: string;
  work: string;
  organization: string | null;
  consent_email: boolean;
  consent_sms: boolean;
  consent_partners: boolean;
  confirmation_sent: boolean;
  utm: Record<string, string> | null;
  collab_accepted: boolean;
  stage: CommunityStarStage;
  notes: string | null;
  photo_url: string | null;
  cause: string | null;
  youtube_id: string | null;
  card_name: string | null;
  card_school: string | null;
  card_sport: string | null;
  card_community: string | null;
  reviewed_at: string | null;
  reviewed_by: string | null;
}

export interface CommunityStarSummary {
  season: string;
  total: number;
  schools: number;
  collab_accepted: number;
  by_stage: Record<CommunityStarStage, number>;
  last_at: string | null;
  window: { opens: string; closes: string; open: boolean };
}

export type CommunityStarPhase = "coming" | "open" | "closed" | "finalists" | "voting" | "top5" | "winners";
export type CommunityStarPublishable = "finalists" | "top5" | "winners";

export interface CommunityStarSettings {
  confirm_grace_minutes: number;
  allow_pending_change: boolean;
  leaderboard_visible: boolean;
  board_min_votes: number;
  card_order: "alphabetical" | "shuffled";
  voting_paused: boolean;
}

export interface CommunityStarReadiness {
  key: string;
  label: string;
  ok: boolean;
  detail?: string | null;
}

export interface CommunityStarProgram {
  season: string;
  stage: CommunityStarPhase;
  server_time: string;
  production: boolean;
  times: { opens: string; closes: string; finalists: string; vote_opens: string; vote_closes: string };
  finalists_published_at: string | null;
  top5_published_at: string | null;
  winners_published_at: string | null;
  published_by: string | null;
  frozen_at: string | null;
  dev_now: string | null;
  settings: CommunityStarSettings;
  counts: { finalists: number; missing_photo: number; missing_cause: number; missing_youtube: number };
  readiness: CommunityStarReadiness[];
}

export type CommunityStarVoteStatus = "pending" | "confirmed" | "void";
export type CommunityStarMailStatus = "queued" | "sent" | "failed";

export interface CommunityStarVote {
  id: number;
  finalist_id: number;
  finalist_name: string;
  email: string;
  status: CommunityStarVoteStatus;
  void_reason: string | null;
  voided_by: string | null;
  voided_at: string | null;
  created_at: string;
  confirmed_at: string | null;
  mail_status: CommunityStarMailStatus;
  mail_attempts: number;
  mail_last_error: string | null;
  sends: number;
}

export interface CommunityStarVoteFlag {
  kind: string;
  label: string;
  vote_ids: number[];
}

export interface CommunityStarVoteSummary {
  finalists: { id: number; name: string; confirmed: number; pending: number; void: number }[];
  totals: { confirmed: number; pending: number; void: number };
  mail: { queued: number; sent: number; failed: number };
  flags: CommunityStarVoteFlag[];
}
