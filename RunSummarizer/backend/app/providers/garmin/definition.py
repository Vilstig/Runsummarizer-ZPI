from datetime import timedelta

from app.config import settings
from app.domain.enums import Provider
from app.providers.base import ProviderDefinition
from app.providers.garmin.budget import GARMIN_BUDGET_POLICY
from app.providers.garmin.importer import GarminImporter
from app.providers.garmin.oauth import GarminOAuth, GarminTokenRefresher
from app.providers.garmin.webhook import GarminWebhookParser


def is_configured() -> bool:
    """Whether the Garmin application's client ID and secret are set."""
    return settings.GARMIN.is_configured()


GARMIN = ProviderDefinition(
    provider=Provider.GARMIN,
    is_configured=is_configured,
    oauth=GarminOAuth(),
    token_refresher=GarminTokenRefresher(),
    importer=GarminImporter,
    syncer=None,
    budget_policy=GARMIN_BUDGET_POLICY,
    webhook=GarminWebhookParser(),
    refresh_idle_after=timedelta(days=30),
)
