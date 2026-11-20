from app.config import settings
from app.domain.enums import Provider
from app.providers.base import ProviderDefinition
from app.providers.strava.budget import STRAVA_BUDGET_POLICY
from app.providers.strava.importer import StravaImporter
from app.providers.strava.oauth import StravaOAuth, StravaTokenRefresher
from app.providers.strava.syncer import StravaSyncer
from app.providers.strava.webhook import StravaWebhookParser


def is_configured() -> bool:
    """Whether the Strava application's client ID and secret are set."""
    return settings.STRAVA.is_configured()


STRAVA = ProviderDefinition(
    provider=Provider.STRAVA,
    is_configured=is_configured,
    oauth=StravaOAuth(),
    token_refresher=StravaTokenRefresher(),
    importer=StravaImporter,
    syncer=StravaSyncer,
    budget_policy=STRAVA_BUDGET_POLICY,
    webhook=StravaWebhookParser(),
    refresh_idle_after=None,
)
