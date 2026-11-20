import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class StravaSettings:
    """The Strava API application's settings."""

    client_id: str
    client_secret: str
    # OAuth callback registered with the Strava application
    redirect_uri: str
    # hub.verify_token Strava echoes in webhook subscription checks
    webhook_verify_token: str
    # last segment of the webhook URL: /api/webhooks/strava/<path secret>
    webhook_path_secret: str
    # full public HTTPS webhook URL registered with Strava, path secret included, e.g.
    # https://….ngrok-free.app/api/webhooks/strava/<path secret>
    webhook_callback_url: str

    def is_configured(self) -> bool:
        """Whether the application's client ID and secret are set."""
        return bool(self.client_id and self.client_secret)


STRAVA = StravaSettings(
    client_id=os.getenv("STRAVA_CLIENT_ID", ""),
    client_secret=os.getenv("STRAVA_CLIENT_SECRET", ""),
    redirect_uri=os.getenv(
        "STRAVA_REDIRECT_URI", "http://localhost:8000/api/providers/strava/callback"
    ),
    webhook_verify_token=os.getenv("STRAVA_WEBHOOK_VERIFY_TOKEN", ""),
    webhook_path_secret=os.getenv("STRAVA_WEBHOOK_PATH_SECRET", ""),
    webhook_callback_url=os.getenv("STRAVA_WEBHOOK_CALLBACK_URL", ""),
)


@dataclass(frozen=True)
class GarminSettings:
    """The Garmin Connect Developer Program application's settings."""

    client_id: str
    client_secret: str
    # OAuth callback registered on the Garmin application page
    redirect_uri: str
    # last segment of the webhook URL: /api/webhooks/garmin/<path secret>
    webhook_path_secret: str

    def is_configured(self) -> bool:
        """Whether the application's client ID and secret are set."""
        return bool(self.client_id and self.client_secret)


GARMIN = GarminSettings(
    client_id=os.getenv("GARMIN_CLIENT_ID", ""),
    client_secret=os.getenv("GARMIN_CLIENT_SECRET", ""),
    redirect_uri=os.getenv(
        "GARMIN_REDIRECT_URI", "http://localhost:8000/api/providers/garmin/callback"
    ),
    webhook_path_secret=os.getenv("GARMIN_WEBHOOK_PATH_SECRET", ""),
)


@dataclass(frozen=True)
class IntervalsSettings:
    """The Intervals.icu OAuth application's settings."""

    client_id: str
    client_secret: str
    # OAuth callback registered with the Intervals.icu application
    redirect_uri: str
    # last segment of the webhook URL: /api/webhooks/intervals/<path secret>
    webhook_path_secret: str
    # secret Intervals.icu puts in the webhook body
    webhook_secret: str

    def is_configured(self) -> bool:
        """Whether the application's client ID and secret are set."""
        return bool(self.client_id and self.client_secret)


INTERVALS = IntervalsSettings(
    client_id=os.getenv("INTERVALS_CLIENT_ID", ""),
    client_secret=os.getenv("INTERVALS_CLIENT_SECRET", ""),
    redirect_uri=os.getenv(
        "INTERVALS_REDIRECT_URI", "http://localhost:8000/api/providers/intervals/callback"
    ),
    webhook_path_secret=os.getenv("INTERVALS_WEBHOOK_PATH_SECRET", ""),
    webhook_secret=os.getenv("INTERVALS_WEBHOOK_SECRET", ""),
)

OAUTH_STATE_SECRET = os.getenv("OAUTH_STATE_SECRET", "")

# Required for encrypting provider tokens at rest.
TOKEN_ENCRYPTION_KEY = os.getenv("TOKEN_ENCRYPTION_KEY", "")
FRONTEND_URL = os.getenv("FRONTEND_URL", "")

# Async SQLAlchemy DSN for the Postgres backend (asyncpg driver), e.g.
# postgresql+asyncpg://user:password@localhost:5432/runsummarizer
# Alembic reads this to run migrations.
POSTGRES_DSN = os.getenv("POSTGRES_DSN", "")
# Separate database the repository contract suite (tests/db) writes to, e.g.
# postgresql+asyncpg://user:password@localhost:5432/runsummarizer_test
POSTGRES_DSN_TEST = os.getenv("POSTGRES_DSN_TEST", "")

# Only enable when behind a trusted reverse proxy that sets X-Forwarded-For.
TRUST_PROXY_HEADERS = os.getenv("TRUST_PROXY_HEADERS", "false").lower() == "true"
# Number of trusted proxies that append to X-Forwarded-For (1: ALB; 2: Cloudflare + ALB).
TRUSTED_PROXY_HOPS = max(1, int(os.getenv("TRUSTED_PROXY_HOPS", "1")))

# Clerk Backend API secret (sk_test_ / sk_live_). Server-side only.
CLERK_SECRET_KEY = os.getenv("CLERK_SECRET_KEY", "")
# PEM public key for networkless session-token verification. Newlines may be \n.
CLERK_JWT_KEY = os.getenv("CLERK_JWT_KEY", "").replace("\\n", "\n").strip()
# Frontend origins matched against the session token azp claim.
CLERK_AUTHORIZED_PARTIES = [
    origin.strip()
    for origin in os.getenv("CLERK_AUTHORIZED_PARTIES", "").split(",")
    if origin.strip()
]

CLERK_WEBHOOK_SECRET = os.getenv("CLERK_WEBHOOK_SECRET", "")
