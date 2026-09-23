-- 025: Athlete applications + onboarding pipeline.
--
-- One row per athlete who applied through niltv.com/athlete-signup/ (or a
-- later inlet: Google Form webhook, sheet import, admin add). The row carries
-- the application answers, the consent record, and the onboarding state:
--
--   applicant -> approved -> agreement_sent -> signed -> stripe_pending -> accepted
--             \-> declined
--
-- Staff approve/decline in the dashboard; approval creates the DocuSign
-- envelope; the DocuSign Connect webhook marks it signed and creates the
-- Stripe Express account + sends the permanent payout link; the Stripe
-- account.updated webhook flips it to accepted once payouts are enabled.
--
-- Personal data (email, phone, answers) lives ONLY here. Nothing in this
-- table is served to the public website. The ambassadors row (registry +
-- tracking) is linked, not merged: ambassadors.status is the tracking axis
-- (candidate/confirmed/removed), applications.status is the onboarding axis.
--
-- Apply by hand (same as all migrations here):
--   psql -h localhost -U niltv_user -d niltv_db -f backend/migrations/025_applications.sql

CREATE TABLE IF NOT EXISTS applications (
    id                      SERIAL PRIMARY KEY,
    ambassador_id           INTEGER REFERENCES ambassadors(id) ON DELETE SET NULL,

    -- identity (email is the upsert key, always lowercased)
    email                   TEXT NOT NULL UNIQUE,
    college_email           TEXT,
    phone                   TEXT,
    first_name              TEXT,
    last_name               TEXT,

    -- school + sport
    university              TEXT,
    sport                   TEXT,
    year                    TEXT,
    campus_channel          TEXT,                 -- which campus channel they picked on the form
    roster_link             TEXT,
    international           BOOLEAN,              -- TRUE = participate, don't pay (skips Stripe)

    -- socials (handles normalized: lowercase, no @)
    instagram               TEXT,
    instagram_followers     TEXT,
    tiktok                  TEXT,
    tiktok_followers        TEXT,
    youtube                 TEXT,
    youtube_subscribers     TEXT,
    other_followers         TEXT,

    -- application answers
    nil_deals_done          TEXT,
    nil_deals_wanted        TEXT,
    purpose                 TEXT,
    content_type            TEXT,
    description             TEXT,
    answers                 JSONB,                -- full raw payload (anything unmapped lands here)

    -- consent record
    confirm_age             BOOLEAN NOT NULL DEFAULT FALSE,
    consent_terms           BOOLEAN NOT NULL DEFAULT FALSE,
    consent_program_email   BOOLEAN NOT NULL DEFAULT FALSE,
    consent_sms             BOOLEAN NOT NULL DEFAULT FALSE,
    consent_marketing       BOOLEAN NOT NULL DEFAULT FALSE,
    consent_partners        BOOLEAN NOT NULL DEFAULT FALSE,
    consent_version         TEXT,
    consent_at              TIMESTAMPTZ,

    -- provenance
    source                  TEXT NOT NULL DEFAULT 'athlete-signup',  -- athlete-signup | google-form | sheet | admin
    user_agent              TEXT,
    ip                      TEXT,
    submit_count            INTEGER NOT NULL DEFAULT 1,   -- re-submissions update the row, never duplicate it

    -- onboarding state
    status                  TEXT NOT NULL DEFAULT 'applicant'
                            CHECK (status IN ('applicant', 'approved', 'declined', 'agreement_sent',
                                              'signed', 'stripe_pending', 'accepted')),
    decline_reason          TEXT,
    reviewed_at             TIMESTAMPTZ,
    reviewed_by             TEXT,

    -- DocuSign
    docusign_envelope_id    TEXT,
    docusign_status         TEXT,                 -- sent | delivered | completed | declined | voided
    agreement_sent_at       TIMESTAMPTZ,
    signed_at               TIMESTAMPTZ,

    -- Stripe Connect (Express)
    stripe_account_id       TEXT,
    stripe_payouts_enabled  BOOLEAN,
    stripe_requirements_due JSONB,                -- requirements.currently_due at last check
    stripe_disabled_reason  TEXT,
    stripe_link_sent_at     TIMESTAMPTZ,
    stripe_checked_at       TIMESTAMPTZ,

    accepted_at             TIMESTAMPTZ,
    notes                   TEXT,
    created_at              TIMESTAMPTZ DEFAULT now(),
    updated_at              TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_applications_status   ON applications(status);
CREATE INDEX IF NOT EXISTS idx_applications_stripe   ON applications(stripe_account_id);
CREATE INDEX IF NOT EXISTS idx_applications_envelope ON applications(docusign_envelope_id);
CREATE INDEX IF NOT EXISTS idx_applications_school   ON applications(university, sport);

-- Timeline: every transition, email, webhook, and staff action, for the
-- "what do they still need" view and for audit.
CREATE TABLE IF NOT EXISTS application_events (
    id              SERIAL PRIMARY KEY,
    application_id  INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    kind            TEXT NOT NULL,     -- applied | resubmitted | approved | declined | agreement_sent |
                                       -- envelope_<status> | stripe_account_created | stripe_link_sent |
                                       -- stripe_updated | accepted | note | error
    actor           TEXT,              -- 'athlete' | 'staff' | 'docusign' | 'stripe' | 'system'
    detail          JSONB
);

CREATE INDEX IF NOT EXISTS idx_application_events_app ON application_events(application_id, at);
