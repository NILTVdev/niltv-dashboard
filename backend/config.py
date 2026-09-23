import os
from functools import lru_cache
from typing import ClassVar
from pathlib import Path

from dotenv import dotenv_values
from pydantic_settings import BaseSettings

ENV_PATH = Path(__file__).parent.parent / ".env"


def _raw_env() -> dict:
    """Merged view of .env file values and the process environment, so
    dynamically-named per-account vars resolve both under systemd (env_file)
    and cron (run_job.sh exports .env)."""
    values = {k: v for k, v in dotenv_values(ENV_PATH).items() if v is not None}
    values.update(os.environ)
    return values


class Settings(BaseSettings):
    # Database
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "niltv_db"
    db_user: str = "niltv_user"
    db_pass: str

    # Instagram Graph API (athlete Business Discovery)
    ig_access_token: str
    ig_app_id: str = ""       # Only needed for refresh_ig_token.py
    ig_app_secret: str = ""   # Only needed for refresh_ig_token.py
    ig_business_id: str  # Your own IG Business account ID (for Business Discovery)

    # Brand Instagram Graph API (owned accounts — direct access + insights)
    # @niltv keeps its original BRAND_IG_* vars and token, unchanged.
    brand_ig_access_token: str = ""
    brand_ig_app_id: str = ""
    brand_ig_app_secret: str = ""
    brand_ig_user_id: str = ""   # Numeric Instagram User ID for @niltv

    # @nilstar — its own token and IG user id. If the token is left empty it
    # falls back to BRAND_IG_ACCESS_TOKEN (works when one token was granted
    # for both accounts in the same portfolio).
    nilstar_ig_access_token: str = ""
    nilstar_ig_user_id: str = ""

    # LEGACY fallback — new accounts belong in the brand_accounts DB registry
    # (scripts/add_brand_account.py; merged view in backend/brand_registry.py).
    # Env path still works: list the names here
    # (comma-separated, e.g. "amel,truebluetv") and add for each NAME:
    #   <NAME>_IG_USER_ID=...
    #   <NAME>_IG_ACCESS_TOKEN=...   (optional — falls back to BRAND_IG_ACCESS_TOKEN
    #                                 when the account is in the same portfolio grant)
    # in .env. The name (lowercased) becomes the DB `account` discriminator.
    # scripts/list_ig_accounts.py prints ready-to-paste lines for every IG
    # account the brand token can see.
    brand_ig_extra_accounts: str = ""

    # Media valuation rate card as a JSON object keyed by platform
    # ({"Instagram": {"cpm": .., "cpe": .., "cpv": ..}, ..., "youtube_live_cpv": ..}).
    # Kept out of the repo; empty means "report the source-provided value only".
    valuation_rates: str = ""

    # ── Environment helpers ─────────────────────────────────────────────
    ENVIRONMENTS: ClassVar[tuple[str, ...]] = ("local", "dev", "production")
    LOCAL_DB_HOSTS: ClassVar[tuple[str, ...]] = (
        "localhost", "127.0.0.1", "::1", "db", "postgres", "host.docker.internal")

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def auth_disabled(self) -> bool:
        """Only a LOCAL environment runs without X-API-Key, and only when the
        database is on this machine (see validate_environment)."""
        return self.environment == "local"

    @property
    def side_effects_enabled(self) -> bool:
        """S3 backups, SNS alerts, CloudWatch streams. Always on in production,
        opt-in on dev, never on local."""
        if self.environment == "production":
            return True
        if self.environment == "dev":
            return self.allow_side_effects
        return False

    @property
    def api_key(self) -> str:
        return self.dashboard_api_key or self.dashboard_password

    def validate_environment(self) -> None:
        """Refuse configurations that would be dangerous rather than merely wrong.

        * unknown ENVIRONMENT values;
        * ENVIRONMENT=local against a database that is not on this machine —
          the auth bypass must never sit in front of the dev or prod database.
        """
        aliases = {"prod": "production", "development": "dev", "staging": "dev"}
        self.environment = aliases.get(self.environment.strip().lower(), self.environment.strip().lower())
        if self.environment not in self.ENVIRONMENTS:
            raise RuntimeError(
                f"ENVIRONMENT={self.environment!r} is not one of {self.ENVIRONMENTS}")
        if self.environment == "local" and self.db_host.strip().lower() not in self.LOCAL_DB_HOSTS:
            raise RuntimeError(
                f"ENVIRONMENT=local disables API auth, so DB_HOST must be a local database "
                f"({', '.join(self.LOCAL_DB_HOSTS)}), not {self.db_host!r}. "
                f"Use ENVIRONMENT=dev to point at a shared database.")

    def brand_ig_targets(self) -> list[dict]:
        """Owned brand IG accounts to pull. Each entry carries the DB
        `account` discriminator, the numeric IG user id, that account's
        access token, the .env var name holding the token (so the refresh
        job can write back to the right place), the API flavor ("fb" =
        graph.facebook.com via Facebook Login, "ig" = graph.instagram.com
        via Instagram Login), and a media fetch limit. @nilstar's higher
        limit keeps all 20 finalist announcement posts in the nightly
        insights refresh."""
        targets = [{
            "account": "niltv",
            "ig_user_id": self.brand_ig_user_id,
            "access_token": self.brand_ig_access_token,
            "token_env_var": "BRAND_IG_ACCESS_TOKEN",
            "api": "fb",
            "limit": 25,
        }]
        if self.nilstar_ig_user_id:
            targets.append({
                "account": "nilstar",
                "ig_user_id": self.nilstar_ig_user_id,
                "access_token": self.nilstar_ig_access_token or self.brand_ig_access_token,
                "token_env_var": (
                    "NILSTAR_IG_ACCESS_TOKEN" if self.nilstar_ig_access_token
                    else "BRAND_IG_ACCESS_TOKEN"
                ),
                "api": "fb",
                "limit": 50,
            })
        raw = _raw_env()
        for name in (n.strip() for n in self.brand_ig_extra_accounts.split(",")):
            if not name:
                continue
            token_var = f"{name.upper()}_IG_ACCESS_TOKEN"
            token = raw.get(token_var, "")
            user_id = raw.get(f"{name.upper()}_IG_USER_ID", "")
            if not token:
                # Same-portfolio accounts share the @niltv token grant.
                token, token_var = self.brand_ig_access_token, "BRAND_IG_ACCESS_TOKEN"
            # Instagram Login tokens start with "IG" (Facebook Login: "EAA").
            # They are host-locked to graph.instagram.com and can address the
            # account as "me", so the user id var is optional for them.
            api = "ig" if token.startswith("IG") else "fb"
            if api == "ig" and not user_id:
                user_id = "me"
            if token and user_id:
                targets.append({
                    "account": name.lower(),
                    "ig_user_id": user_id,
                    "access_token": token,
                    "token_env_var": token_var,
                    "api": api,
                    "limit": 25,
                })
        return targets

    # Zoomph
    zoomph_api_key: str
    zoomph_feed_id: str

    # Google Analytics 4 — primary site (truebluetv.com)
    ga4_property_id: str = ""           # e.g. "properties/123456789"
    ga4_credentials_json: str = ""      # path to service account JSON

    # Google Search Console — primary site (truebluetv.com)
    gsc_site_url: str = ""              # e.g. "sc-domain:truebluetv.com"
    gsc_credentials_json: str = ""      # path; falls back to ga4_credentials_json if empty

    # Second site (niltv.com) — same service account, different property/site
    ga4_property_id_2: str = ""         # e.g. "properties/987654321"
    gsc_site_url_2: str = ""            # e.g. "sc-domain:niltv.com"

    def web_analytics_targets(self) -> list[dict]:
        """Sites to pull web analytics for. Each has a `site` key (the DB
        discriminator), a GA4 property id, and a GSC site url. The second site
        is only included when its env vars are configured."""
        targets = [{
            "site": "truebluetv",
            "ga4_property_id": self.ga4_property_id,
            "gsc_site_url": self.gsc_site_url,
        }]
        if self.ga4_property_id_2 or self.gsc_site_url_2:
            targets.append({
                "site": "niltv",
                "ga4_property_id": self.ga4_property_id_2,
                "gsc_site_url": self.gsc_site_url_2,
            })
        return targets

    # AWS
    aws_s3_bucket: str
    aws_sns_topic_arn: str = ""
    aws_region: str = "us-east-1"

    # App
    dashboard_username: str = ""
    dashboard_password: str
    # API key the frontend sends as X-API-Key. Empty = the dashboard password
    # (the historical single-secret setup). Splitting them lets a developer's
    # .env.local carry a login without holding the key that unlocks the
    # upload/approve routes on a shared backend.
    dashboard_api_key: str = ""
    # local | dev | production — see README "Environments".
    #   local:      auth bypassed, no S3/SNS/CloudWatch side effects, docs on;
    #               refuses to start unless the database is on this machine.
    #   dev:        real auth, docs on, side effects off unless ALLOW_SIDE_EFFECTS=1.
    #   production: real auth, docs off, side effects on.
    environment: str = "production"
    # dev only: let the nightly jobs write S3 backups / SNS alerts / CloudWatch.
    allow_side_effects: bool = False

    # ── Athlete onboarding (applications router) ────────────────────────
    # Browser origins allowed to POST /api/applications/ (the public signup
    # form on niltv.com). Comma-separated. The dashboard origin is always on.
    public_cors_origins: str = (
        "https://niltv.com,https://www.niltv.com,https://dev.dkdfgvugisb3v.amplifyapp.com"
    )
    # Where the athlete-facing links point (payout link, site pages).
    site_base: str = "https://niltv.com"
    # Where staff-facing links point (new-applicant email, staff sheet).
    dashboard_base_url: str = "https://dashboard.niltv.com"
    # Transactional email (SES v2, same identity/config set as the niltv.com
    # newsletter sender). Empty from_email disables sending (tests/dev).
    from_email: str = "no-reply@niltv.com"
    ses_configuration_set: str = "niltv-transactional"
    # Replies to the no-reply sender land here (Reply-To header). Empty = none.
    reply_to_email: str = "contact@niltv.com"
    # Logo in the branded email header; empty = <site_base>/assets/img/niltv-logo-email.png
    email_logo_url: str = ""
    # Staff inbox told about each new applicant. Empty = no notification.
    applications_notify_email: str = ""
    # Google Sheets: the staff mirror of the applications table (export job,
    # every 15 min) and the service-account json (falls back to the GA4 one).
    # Share the sheet with the account's client_email as an editor.
    applications_sheet_id: str = ""
    google_credentials_json: str = ""
    # NIL TV site accounts (Cognito) that the public signup form signs in with.
    # "<poolId>:<clientId>,<poolId>:<clientId>"; several pools can be valid at
    # once. Empty = no account check.
    cognito_user_pools: str = ""

    # DocuSign eSignature — JWT grant (integration key + RSA private key, one
    # consented user). Empty integration key = DocuSign disabled: approve
    # still works and falls back to emailing docusign_powerform_url if set.
    docusign_integration_key: str = ""
    docusign_user_id: str = ""            # API Username (GUID) of the consented user
    docusign_account_id: str = ""         # API Account ID (GUID)
    docusign_base_uri: str = ""           # empty = resolved from /oauth/userinfo; or e.g. https://na4.docusign.net
    docusign_oauth_host: str = "account.docusign.com"     # demo = account-d.docusign.com
    docusign_private_key_path: str = ""   # PEM file path (chmod 600), e.g. /path/to/docusign.pem
    docusign_template_id: str = ""        # ambassador agreement + W-9 template
    docusign_template_role: str = "Athlete"   # signer role name on the template
    docusign_connect_secret: str = ""     # HMAC key from the Connect configuration
    docusign_powerform_url: str = ""      # fallback when the API is not configured
    # Reply-To shown on DocuSign's own notification emails (the sender name is
    # the consented user's DocuSign profile name). Empty email = DocuSign default.
    docusign_reply_email: str = "contact@niltv.com"
    docusign_reply_name: str = "NIL TV"
    # Brand (logo, colours, company name) applied to API-sent envelopes.
    # Empty = the account's default brand.
    docusign_brand_id: str = ""

    # Stripe Connect (Express). Restricted key: Connect -> Accounts: Write
    # (the only Stripe calls here are POST/GET /v1/accounts). Webhook secret
    # from the Connect endpoint posting account.updated to
    # /api/applications/webhooks/stripe.
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    # Must equal LINK_SIGNING_SECRET on the payouts-start Lambda so the
    # permanent /payouts/start/?t= link we email resolves there.
    link_signing_secret: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        # Dynamically-named per-account vars (<NAME>_IG_ACCESS_TOKEN etc.)
        # live in the same .env but are not declared fields.
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    settings = Settings()
    settings.validate_environment()
    return settings
