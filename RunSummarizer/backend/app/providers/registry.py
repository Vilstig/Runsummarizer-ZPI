"""The providers the app can import activities from.

Code outside a provider's own modules reaches the provider through ``PROVIDERS``.
"""

from app.domain.enums import Provider
from app.providers.base import ProviderDefinition
from app.providers.garmin.definition import GARMIN
from app.providers.intervals.definition import INTERVALS
from app.providers.strava.definition import STRAVA

PROVIDERS: dict[Provider, ProviderDefinition] = {
    Provider.STRAVA: STRAVA,
    Provider.GARMIN: GARMIN,
    Provider.INTERVALS: INTERVALS,
}
