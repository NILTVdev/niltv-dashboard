from sqlalchemy import (
    Column, Index, Integer, Text, Boolean, Numeric, BigInteger,
    TIMESTAMP, ForeignKey, JSON,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from backend.database import Base


class Athlete(Base):
    __tablename__ = "athletes"
    __table_args__ = (
        Index("idx_athletes_active_name", "active", "name"),
    )

    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False)
    sport = Column(Text)
    year = Column(Text)
    ig_handle = Column(Text, unique=True)
    ig_user_id = Column(Text)
    ig_accessible = Column(Boolean, default=True)       # False = personal account (Business Discovery fails)
    ig_checked_at = Column(TIMESTAMP(timezone=True))     # when ig_accessible was last verified
    tiktok_handle = Column(Text)
    x_handle = Column(Text)
    active = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
    # Precomputed cache (updated after each cron job, not on every request)
    cached_ig_followers = Column(Integer)
    cached_ig_posts = Column(Integer)
    cached_ig_bio = Column(Text)
    cached_ig_engagement = Column(Integer)       # sum(likes + comments) from athlete_posts
    cached_attributed_eng = Column(Integer)      # engagement from Zoomph mentions
    cached_social_valuation = Column(Integer)    # ig_engagement + attributed_engagement
    cached_last_pulled = Column(TIMESTAMP(timezone=True))

    snapshots = relationship("AthleteSnapshot", back_populates="athlete", cascade="all, delete-orphan")
    posts = relationship("AthletePost", back_populates="athlete", cascade="all, delete-orphan")


class AthleteSnapshot(Base):
    """One row per athlete per data pull — stores point-in-time follower counts."""
    __tablename__ = "athlete_snapshots"
    __table_args__ = (
        Index("idx_athlete_snap_athlete_pulled", "athlete_id", "pulled_at"),
    )

    id = Column(Integer, primary_key=True)
    athlete_id = Column(Integer, ForeignKey("athletes.id", ondelete="CASCADE"), nullable=False)
    pulled_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    ig_followers = Column(Integer)
    ig_posts = Column(Integer)
    ig_bio = Column(Text)
    tiktok_followers = Column(Integer)
    tiktok_likes = Column(BigInteger)
    x_followers = Column(Integer)
    x_posts = Column(Integer)

    athlete = relationship("Athlete", back_populates="snapshots")


class AthletePost(Base):
    """Individual Instagram posts for each athlete (up to 25 most recent per pull)."""
    __tablename__ = "athlete_posts"

    id = Column(Integer, primary_key=True)
    athlete_id = Column(Integer, ForeignKey("athletes.id", ondelete="CASCADE"), nullable=False)
    pulled_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    ig_post_id = Column(Text, unique=True)
    posted_at = Column(TIMESTAMP(timezone=True))
    media_type = Column(Text)
    like_count = Column(Integer)
    comment_count = Column(Integer)
    permalink = Column(Text)
    caption = Column(Text)
    media_url = Column(Text)

    athlete = relationship("Athlete", back_populates="posts")
    snapshots = relationship("AthletePostSnapshot", back_populates="post", cascade="all, delete-orphan")


class AthletePostSnapshot(Base):
    """Point-in-time engagement snapshot for an athlete post."""
    __tablename__ = "athlete_post_snapshots"
    __table_args__ = (
        Index("idx_post_snap_post_captured", "post_id", "captured_at"),
    )

    id = Column(Integer, primary_key=True)
    post_id = Column(Integer, ForeignKey("athlete_posts.id", ondelete="CASCADE"), nullable=False)
    captured_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    like_count = Column(Integer)
    comment_count = Column(Integer)

    post = relationship("AthletePost", back_populates="snapshots")


class ZoomphPost(Base):
    """Posts from Duke-owned accounts pulled via the Zoomph Partner Mention API."""
    __tablename__ = "zoomph_posts"
    __table_args__ = (
        Index("idx_zoomph_posts_author", "author"),
        Index("idx_zoomph_posts_posted_at", "posted_at"),
        Index("idx_zoomph_posts_url", "url"),
    )

    id = Column(Integer, primary_key=True)
    pulled_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True))
    post_id = Column(Text, unique=True)
    partner = Column(Text)
    platform = Column(Text)       # e.g. "Instagram", "Twitter", "YouTube"
    content_type = Column(Text)
    author = Column(Text)
    url = Column(Text)
    message = Column(Text)
    posted_at = Column(TIMESTAMP(timezone=True))
    partner_mention_type = Column(Text)
    # Engagement
    engagement = Column(Integer)
    like_count = Column(Integer)
    comment_count = Column(Integer)
    save_count = Column(Integer)
    share_count = Column(Integer)
    reply_count = Column(Integer)
    # Reach / rates
    impressions = Column(Integer)
    reach = Column(Integer)
    projected_impressions = Column(BigInteger)
    follower_count = Column(Integer)
    engagement_rate = Column(Numeric)
    follower_interaction_rate = Column(Numeric)
    # Value
    brand_exposure_value = Column(Numeric)
    post_value = Column(Numeric)
    brand_exposure_value_us = Column(Numeric)
    # Sentiment / context
    sentiment = Column(Text)
    hashtags = Column(Text)
    mentions = Column(Text)
    language = Column(Text)
    # Video / streaming
    vod_views = Column(Integer)
    view_count = Column(Integer)
    live_views = Column(Integer)
    avg_concurrent_viewers = Column(Integer)
    peak_live_viewer_count = Column(Integer)
    hours_watched = Column(BigInteger)
    # Logo AI
    logo_total_seconds = Column(Numeric)
    logo_avg_size = Column(Numeric)
    logo_avg_clarity = Column(Numeric)
    logo_impressions = Column(Integer)
    logo_location = Column(Text)

    snapshots = relationship("ZoomphPostSnapshot", back_populates="post", cascade="all, delete-orphan")


class ZoomphPostSnapshot(Base):
    """Point-in-time engagement metrics for a Zoomph post, captured each pull."""
    __tablename__ = "zoomph_post_snapshots"
    __table_args__ = (
        Index("idx_zoomph_snap_post_captured", "zoomph_post_id", "captured_at"),
    )

    id = Column(Integer, primary_key=True)
    zoomph_post_id = Column(Integer, ForeignKey("zoomph_posts.id", ondelete="CASCADE"), nullable=False)
    captured_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    # Engagement
    engagement = Column(Integer)
    like_count = Column(Integer)
    comment_count = Column(Integer)
    save_count = Column(Integer)
    share_count = Column(Integer)
    reply_count = Column(Integer)
    # Reach / rates
    impressions = Column(Integer)
    reach = Column(Integer)
    projected_impressions = Column(BigInteger)
    follower_count = Column(Integer)
    engagement_rate = Column(Numeric)
    follower_interaction_rate = Column(Numeric)
    # Value
    brand_exposure_value = Column(Numeric)
    post_value = Column(Numeric)
    brand_exposure_value_us = Column(Numeric)
    # Video / streaming
    vod_views = Column(Integer)
    view_count = Column(Integer)
    live_views = Column(Integer)
    hours_watched = Column(BigInteger)

    post = relationship("ZoomphPost", back_populates="snapshots")


class GA4DailySnapshot(Base):
    """Daily aggregate Google Analytics 4 metrics broken down by source/medium."""
    __tablename__ = "ga4_daily_snapshots"
    __table_args__ = (
        Index("idx_ga4_date", "date"),
    )

    id = Column(Integer, primary_key=True)
    site = Column(Text, nullable=False, server_default="truebluetv")
    date = Column(TIMESTAMP(timezone=True), nullable=False)
    pulled_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    sessions = Column(Integer)
    total_users = Column(Integer)
    pageviews = Column(Integer)
    bounce_rate = Column(Numeric)
    engagement_rate = Column(Numeric)
    source = Column(Text)
    medium = Column(Text)


class GSCDailyTotal(Base):
    """Accurate daily totals from GSC — queried with date-only dimension (no anonymization)."""
    __tablename__ = "gsc_daily_totals"
    __table_args__ = (
        Index("idx_gsc_daily_date", "date"),
    )

    id = Column(Integer, primary_key=True)
    site = Column(Text, nullable=False, server_default="truebluetv")
    date = Column(TIMESTAMP(timezone=True), nullable=False)
    pulled_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    clicks = Column(Integer)
    impressions = Column(Integer)
    ctr = Column(Numeric)
    position = Column(Numeric)


class GSCQuerySnapshot(Base):
    """Per-query GSC metrics (date + query dimension). Subject to anonymization."""
    __tablename__ = "gsc_query_snapshots"
    __table_args__ = (
        Index("idx_gsc_query_date", "date"),
    )

    id = Column(Integer, primary_key=True)
    site = Column(Text, nullable=False, server_default="truebluetv")
    date = Column(TIMESTAMP(timezone=True), nullable=False)
    pulled_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    query = Column(Text, nullable=False)
    clicks = Column(Integer)
    impressions = Column(Integer)
    ctr = Column(Numeric)
    position = Column(Numeric)


class GSCPageSnapshot(Base):
    """Per-page GSC metrics (date + page dimension). Subject to anonymization."""
    __tablename__ = "gsc_page_snapshots"
    __table_args__ = (
        Index("idx_gsc_page_date", "date"),
    )

    id = Column(Integer, primary_key=True)
    site = Column(Text, nullable=False, server_default="truebluetv")
    date = Column(TIMESTAMP(timezone=True), nullable=False)
    pulled_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    page = Column(Text, nullable=False)
    clicks = Column(Integer)
    impressions = Column(Integer)
    ctr = Column(Numeric)
    position = Column(Numeric)


class GSCDailySnapshot(Base):
    """DEPRECATED — Legacy table. Kept for backward compatibility during migration."""
    __tablename__ = "gsc_daily_snapshots"

    id = Column(Integer, primary_key=True)
    date = Column(TIMESTAMP(timezone=True), nullable=False)
    pulled_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    query = Column(Text)
    page = Column(Text)
    clicks = Column(Integer)
    impressions = Column(Integer)
    ctr = Column(Numeric)
    position = Column(Numeric)


class BrandAccount(Base):
    """Registry of owned brand IG accounts the nightly jobs pull (campus
    channels). Overrides/extends the legacy .env account list — see
    backend/brand_registry.py. Onboard via scripts/add_brand_account.py."""
    __tablename__ = "brand_accounts"
    __table_args__ = (
        Index("idx_brand_accounts_active", "active"),
    )

    id = Column(Integer, primary_key=True)
    account = Column(Text, unique=True, nullable=False)  # matches brand_posts.account
    username = Column(Text)
    ig_user_id = Column(Text, nullable=False)            # "me" for Instagram-Login tokens
    access_token = Column(Text)                          # NULL = falls back to BRAND_IG_ACCESS_TOKEN
    api = Column(Text, nullable=False, server_default="fb")   # 'fb' | 'ig' (host-locked tokens)
    post_limit = Column(Integer, nullable=False, server_default="25")
    campus = Column(Text)                                # school/node grouping, e.g. 'duke'
    network_pull = Column(Boolean, nullable=False, server_default="false")
    active = Column(Boolean, nullable=False, server_default="true")
    token_expires_at = Column(TIMESTAMP(timezone=True))
    token_refreshed_at = Column(TIMESTAMP(timezone=True))
    notes = Column(Text)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True))


class BrandSnapshot(Base):
    """Point-in-time profile data for an owned brand Instagram account (direct API)."""
    __tablename__ = "brand_snapshots"
    __table_args__ = (
        Index("idx_brand_snap_pulled", "pulled_at"),
        Index("idx_brand_snap_account", "account"),
    )

    id = Column(Integer, primary_key=True)
    account = Column(Text, nullable=False, server_default="niltv")
    pulled_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    username = Column(Text)
    followers = Column(Integer)
    post_count = Column(Integer)
    bio = Column(Text)


class BrandPost(Base):
    """Individual Instagram posts for an owned brand account, including insights."""
    __tablename__ = "brand_posts"
    __table_args__ = (
        Index("idx_brand_posts_posted", "posted_at"),
        Index("idx_brand_posts_account", "account"),
    )

    id = Column(Integer, primary_key=True)
    account = Column(Text, nullable=False, server_default="niltv")
    ig_post_id = Column(Text, unique=True, nullable=False)
    posted_at = Column(TIMESTAMP(timezone=True))
    media_type = Column(Text)
    caption = Column(Text)
    like_count = Column(Integer)
    comment_count = Column(Integer)
    permalink = Column(Text)
    media_url = Column(Text)
    thumbnail_url = Column(Text)   # poster frame for videos (media_url is the mp4)
    impressions = Column(Integer)
    reach = Column(Integer)
    saves = Column(Integer)
    views = Column(Integer)
    shares = Column(Integer)
    pulled_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True))


class TrueBlueSnapshot(Base):
    """Point-in-time profile data for the trueblue_tv Instagram account."""
    __tablename__ = "trueblue_snapshots"
    __table_args__ = (
        Index("idx_trueblue_snap_pulled", "pulled_at"),
    )

    id = Column(Integer, primary_key=True)
    pulled_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    followers = Column(Integer)
    following = Column(Integer)
    post_count = Column(Integer)
    bio = Column(Text)


class TrueBluePost(Base):
    """Individual Instagram posts for the trueblue_tv account."""
    __tablename__ = "trueblue_posts"
    __table_args__ = (
        Index("idx_trueblue_posts_posted", "posted_at"),
    )

    id = Column(Integer, primary_key=True)
    shortcode = Column(Text, unique=True, nullable=False)
    posted_at = Column(TIMESTAMP(timezone=True))
    media_type = Column(Text)
    caption = Column(Text)
    like_count = Column(Integer)
    comment_count = Column(Integer)
    permalink = Column(Text)
    media_url = Column(Text)
    is_video = Column(Boolean, default=False)
    video_view_count = Column(Integer)
    pulled_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True))


class Ambassador(Base):
    """Registry of NILTV ambassadors. Discovered from "welcome our new
    ambassador @x" posts on @niltv (backend/jobs/ambassadors.py) or added by
    hand via the admin endpoints. Collab content is attributed through
    ambassador_id on the network post tables — their own post history is
    never copied."""
    __tablename__ = "ambassadors"
    __table_args__ = (
        Index("idx_ambassadors_status", "status"),
        Index("idx_ambassadors_campus", "campus"),
    )

    id = Column(Integer, primary_key=True)
    ig_username = Column(Text, unique=True)    # lowercased; NULL until known for sheet-only rows
    display_name = Column(Text)
    previous_usernames = Column(Text)          # comma list; trail across handle renames
    campus = Column(Text)                      # matches brand_accounts.campus (OUR channel node)
    school = Column(Text)                      # their university, free text from the sheet
    sport = Column(Text)
    year = Column(Text)
    gender = Column(Text)                      # 'M' | 'F' as reported
    cohort = Column(Text)                      # survey round, e.g. 'F26'
    profile_pic_url = Column(Text)             # IG CDN URL, refreshed nightly (expires)
    website = Column(Text)
    campus_source = Column(Text, nullable=False, server_default="inferred")  # 'inferred' | 'manual'
    status = Column(Text, nullable=False, server_default="candidate")  # 'candidate' | 'confirmed' | 'removed'
    source = Column(Text)                      # 'welcome_post' | 'admin'
    welcome_post_id = Column(Text)             # brand_posts.ig_post_id of the announcement
    announced_at = Column(TIMESTAMP(timezone=True))
    athlete_id = Column(Integer, ForeignKey("athletes.id", ondelete="SET NULL"))
    # Business Discovery enrichment (profile fields only)
    ig_user_id = Column(Text)
    ig_accessible = Column(Boolean, default=True)
    ig_checked_at = Column(TIMESTAMP(timezone=True))
    # Precomputed cache (updated after each cron job, not on every request)
    cached_followers = Column(Integer)
    cached_bio = Column(Text)
    cached_collab_posts = Column(Integer)
    cached_collab_views = Column(Integer)
    cached_collab_engagement = Column(Integer)  # likes + comments + shares + saves
    cached_last_pulled = Column(TIMESTAMP(timezone=True))
    active = Column(Boolean, nullable=False, server_default="true")
    notes = Column(Text)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True))

    snapshots = relationship("AmbassadorSnapshot", back_populates="ambassador", cascade="all, delete-orphan")


class AmbassadorSnapshot(Base):
    """Point-in-time profile data for an ambassador (Business Discovery,
    profile fields only). Athlete-linked ambassadors are not written here —
    their trendline lives in athlete_snapshots."""
    __tablename__ = "ambassador_snapshots"
    __table_args__ = (
        Index("idx_ambassador_snap_amb_pulled", "ambassador_id", "pulled_at"),
    )

    id = Column(Integer, primary_key=True)
    ambassador_id = Column(Integer, ForeignKey("ambassadors.id", ondelete="CASCADE"), nullable=False)
    pulled_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    followers = Column(Integer)                # Instagram
    post_count = Column(Integer)
    bio = Column(Text)
    tiktok_followers = Column(Integer)         # self-reported (no pull pipeline)
    youtube_subscribers = Column(Integer)      # self-reported (no pull pipeline)
    source = Column(Text, nullable=False, server_default="business_discovery")  # | 'reported'

    ambassador = relationship("Ambassador", back_populates="snapshots")


class NiltvNetworkPost(Base):
    """Owned + collaborative posts for the NILTV-side channels, pulled nightly from
    the Instagram Graph API (backend/jobs/run_niltv_network.py). A Meta Business
    Suite CSV upload can backfill shares/saves/reach on collaborator-owned posts,
    which the API cannot expose. Since migration 026 this is the ONE table for
    every network post: TrueBlueTV rows (Business Suite export, grid snapshot
    CSV, Business Discovery) land here tagged collab_accounts=truebluetv.
    Zoomph feeds only zoomph_posts and never writes here.

    account_username is the ORIGINAL poster's IG handle ('niltv' for our own posts,
    the athlete's handle for collabs). collab_accounts is the comma list of OUR
    internal account keys whose edges surfaced the post. Filter our own channel's
    posts on collab_accounts, not on account_username."""
    __tablename__ = "niltv_network_posts"
    __table_args__ = (
        Index("idx_niltv_network_posts_publish", "publish_time"),
        Index("idx_niltv_network_posts_ambassador", "ambassador_id"),
    )

    id = Column(Integer, primary_key=True)
    post_id = Column(Text, unique=True, nullable=False)
    account_username = Column(Text)
    account_name = Column(Text)
    description = Column(Text)
    duration_sec = Column(Integer)
    publish_time = Column(TIMESTAMP(timezone=True))
    permalink = Column(Text)
    post_type = Column(Text)
    media_url = Column(Text)        # refreshed each pull (IG CDN URLs expire)
    thumbnail_url = Column(Text)
    collab_accounts = Column(Text)  # comma list of OUR accounts whose edges carry this post
    views = Column(Integer)
    likes = Column(Integer)
    shares = Column(Integer)
    comments = Column(Integer)
    saves = Column(Integer)
    reach = Column(Integer)
    projected_reach = Column(Integer)
    follows = Column(Integer)
    # Who last wrote `views`: graph > export > bd/public (import_niltv_network.VIEWS_RANK).
    # A lower-ranked source fills a NULL but never overwrites a higher-ranked value.
    views_source = Column(Text)
    ambassador_id = Column(Integer, ForeignKey("ambassadors.id", ondelete="SET NULL"))  # stamped by the attribution pass
    imported_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True))

    snapshots = relationship("NiltvNetworkPostSnapshot", back_populates="post", cascade="all, delete-orphan")


class NiltvNetworkPostSnapshot(Base):
    """Point-in-time metric snapshots for NILTV network posts."""
    __tablename__ = "niltv_network_post_snapshots"
    __table_args__ = (
        Index("idx_niltv_network_snap_post_captured", "network_post_id", "captured_at"),
    )

    id = Column(Integer, primary_key=True)
    network_post_id = Column(Integer, ForeignKey("niltv_network_posts.id", ondelete="CASCADE"), nullable=False)
    captured_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    views = Column(Integer)
    likes = Column(Integer)
    shares = Column(Integer)
    comments = Column(Integer)
    saves = Column(Integer)
    reach = Column(Integer)
    projected_reach = Column(Integer)
    follows = Column(Integer)

    post = relationship("NiltvNetworkPost", back_populates="snapshots")


# trueblue_network_posts / trueblue_network_post_snapshots were merged into
# niltv_network_posts (collab_accounts=truebluetv) by migration 026; the old
# tables survive as *_legacy and nothing reads them.


class Application(Base):
    """Athlete application + onboarding state (migration 025).

    One row per applicant, keyed by email. Holds the form answers, the consent
    record, and the pipeline state applicant -> approved -> agreement_sent ->
    signed -> stripe_pending -> accepted (or declined). Personal data stays in
    this table; the public site never reads it.
    """
    __tablename__ = "applications"
    __table_args__ = (
        Index("idx_applications_status", "status"),
        Index("idx_applications_stripe", "stripe_account_id"),
        Index("idx_applications_envelope", "docusign_envelope_id"),
        Index("idx_applications_school", "university", "sport"),
    )

    id = Column(Integer, primary_key=True)
    ambassador_id = Column(Integer, ForeignKey("ambassadors.id", ondelete="SET NULL"))

    email = Column(Text, nullable=False, unique=True)
    college_email = Column(Text)
    phone = Column(Text)
    first_name = Column(Text)
    last_name = Column(Text)

    university = Column(Text)
    sport = Column(Text)
    year = Column(Text)
    campus_channel = Column(Text)
    roster_link = Column(Text)
    international = Column(Boolean)

    instagram = Column(Text)
    instagram_followers = Column(Text)
    tiktok = Column(Text)
    tiktok_followers = Column(Text)
    youtube = Column(Text)
    youtube_subscribers = Column(Text)
    other_followers = Column(Text)

    nil_deals_done = Column(Text)
    nil_deals_wanted = Column(Text)
    purpose = Column(Text)
    content_type = Column(Text)
    description = Column(Text)
    answers = Column(JSON)

    confirm_age = Column(Boolean, nullable=False, server_default="false")
    consent_terms = Column(Boolean, nullable=False, server_default="false")
    consent_program_email = Column(Boolean, nullable=False, server_default="false")
    consent_sms = Column(Boolean, nullable=False, server_default="false")
    consent_marketing = Column(Boolean, nullable=False, server_default="false")
    consent_partners = Column(Boolean, nullable=False, server_default="false")
    consent_version = Column(Text)
    consent_at = Column(TIMESTAMP(timezone=True))

    source = Column(Text, nullable=False, server_default="athlete-signup")
    user_agent = Column(Text)
    ip = Column(Text)
    submit_count = Column(Integer, nullable=False, server_default="1")

    status = Column(Text, nullable=False, server_default="applicant")
    decline_reason = Column(Text)
    reviewed_at = Column(TIMESTAMP(timezone=True))
    reviewed_by = Column(Text)

    docusign_envelope_id = Column(Text)
    docusign_status = Column(Text)
    agreement_sent_at = Column(TIMESTAMP(timezone=True))
    agreement_reminded_at = Column(TIMESTAMP(timezone=True))   # last resend of the same envelope
    signed_at = Column(TIMESTAMP(timezone=True))

    stripe_account_id = Column(Text)
    stripe_payouts_enabled = Column(Boolean)
    stripe_requirements_due = Column(JSON)
    stripe_disabled_reason = Column(Text)
    stripe_link_sent_at = Column(TIMESTAMP(timezone=True))
    stripe_checked_at = Column(TIMESTAMP(timezone=True))

    accepted_at = Column(TIMESTAMP(timezone=True))
    notes = Column(Text)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True))

    events = relationship(
        "ApplicationEvent",
        back_populates="application",
        cascade="all, delete-orphan",
        # Insertion order = audit order. 'signed' is stamped with DocuSign's
        # completion time, which can predate the webhook that recorded it.
        order_by="ApplicationEvent.id",
    )


class ApplicationEvent(Base):
    """Timeline row for an application: transitions, emails, webhooks, staff
    actions. Drives the 'what do they still need' view and the audit trail."""
    __tablename__ = "application_events"
    __table_args__ = (
        Index("idx_application_events_app", "application_id", "at"),
    )

    id = Column(Integer, primary_key=True)
    application_id = Column(Integer, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False)
    at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    kind = Column(Text, nullable=False)
    actor = Column(Text)
    detail = Column(JSON)

    application = relationship("Application", back_populates="events")
