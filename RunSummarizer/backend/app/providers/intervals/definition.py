from app.config import settings
from app.domain.enums import Provider
from app.providers.base import ProviderDefinition
from app.providers.intervals.budget import INTERVALS_BUDGET_POLICY
from app.providers.intervals.importer import IntervalsImporter
from app.providers.intervals.oauth import IntervalsOAuth
from app.providers.intervals.syncer import IntervalsSyncer
from app.providers.intervals.webhook import IntervalsWebhookParser


def is_configured() -> bool:
    """Whether the Intervals.icu application's client ID and secret are set."""
    return settings.INTERVALS.is_configured()


INTERVALS = ProviderDefinition(
    provider=Provider.INTERVALS,
    is_configured=is_configured,
    oauth=IntervalsOAuth(),
    token_refresher=None,  # Intervals.icu tokens don't expire and carry no refresh token
    importer=IntervalsImporter,
    syncer=IntervalsSyncer,
    budget_policy=INTERVALS_BUDGET_POLICY,
    webhook=IntervalsWebhookParser(),
)
