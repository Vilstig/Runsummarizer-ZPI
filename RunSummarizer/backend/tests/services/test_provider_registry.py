"""The provider registry and the Strava and Garmin definitions in it."""

from datetime import timedelta

import pytest

from app.domain.enums import Provider
from app.providers.base import IMPORT_MAX_ATTEMPTS
from app.providers.garmin.budget import GARMIN_BUDGET_POLICY
from app.providers.garmin.importer import GarminImporter
from app.providers.garmin.oauth import GarminOAuth, GarminTokenRefresher
from app.providers.garmin.webhook import GarminWebhookParser
from app.providers.registry import PROVIDERS
from app.providers.strava.budget import STRAVA_BUDGET_POLICY
from app.providers.strava.oauth import StravaOAuth, StravaTokenRefresher
from app.providers.strava.syncer import StravaSyncer
from tests.helpers import configure_garmin, configure_strava


def test_every_definition_is_registered_under_its_provider():
    assert PROVIDERS
    for provider, definition in PROVIDERS.items():
        assert definition.provider is provider


def test_strava_authorizes_and_refreshes_through_its_oauth():
    assert isinstance(PROVIDERS[Provider.STRAVA].oauth, StravaOAuth)
    assert isinstance(PROVIDERS[Provider.STRAVA].token_refresher, StravaTokenRefresher)


def test_strava_importer_imports_strava_items():
    importer = PROVIDERS[Provider.STRAVA].importer()

    assert importer.provider is Provider.STRAVA


def test_strava_items_are_fetched_again_on_retry_with_the_shared_max_attempts():
    importer = PROVIDERS[Provider.STRAVA].importer()

    assert importer.single_use_fetch is False
    assert importer.max_attempts == IMPORT_MAX_ATTEMPTS


def test_strava_syncs_through_the_strava_syncer():
    assert isinstance(PROVIDERS[Provider.STRAVA].syncer(), StravaSyncer)


def test_strava_calls_are_budgeted_by_the_strava_policy():
    assert PROVIDERS[Provider.STRAVA].budget_policy is STRAVA_BUDGET_POLICY


@pytest.mark.parametrize(
    ("client_id", "client_secret", "configured"),
    [
        ("client-id", "client-secret", True),
        ("client-id", "", False),
        ("", "client-secret", False),
        ("", "", False),
    ],
)
def test_strava_is_configured_with_a_client_id_and_secret(
    monkeypatch, client_id, client_secret, configured
):
    configure_strava(monkeypatch, client_id=client_id, client_secret=client_secret)

    assert PROVIDERS[Provider.STRAVA].is_configured() is configured


def test_garmin_is_registered_after_strava():
    assert list(PROVIDERS)[:2] == [Provider.STRAVA, Provider.GARMIN]


def test_garmin_authorizes_and_refreshes_through_its_oauth():
    assert isinstance(PROVIDERS[Provider.GARMIN].oauth, GarminOAuth)
    assert isinstance(PROVIDERS[Provider.GARMIN].token_refresher, GarminTokenRefresher)


def test_garmin_items_are_downloaded_once_with_a_day_of_attempts():
    importer = PROVIDERS[Provider.GARMIN].importer()

    assert isinstance(importer, GarminImporter)
    assert importer.provider is Provider.GARMIN
    assert importer.single_use_fetch is True
    assert importer.max_attempts == 30


def test_garmin_only_sends_activities_by_webhook():
    assert PROVIDERS[Provider.GARMIN].syncer is None
    assert isinstance(PROVIDERS[Provider.GARMIN].webhook, GarminWebhookParser)


def test_garmin_calls_are_budgeted_by_the_garmin_policy():
    assert PROVIDERS[Provider.GARMIN].budget_policy is GARMIN_BUDGET_POLICY


@pytest.mark.parametrize(
    ("client_id", "client_secret", "configured"),
    [
        ("client-id", "client-secret", True),
        ("client-id", "", False),
        ("", "client-secret", False),
        ("", "", False),
    ],
)
def test_garmin_is_configured_with_a_client_id_and_secret(
    monkeypatch, client_id, client_secret, configured
):
    configure_garmin(monkeypatch, client_id=client_id, client_secret=client_secret)

    assert PROVIDERS[Provider.GARMIN].is_configured() is configured


def test_unused_garmin_tokens_are_refreshed_30_days_after_they_expired():
    assert PROVIDERS[Provider.GARMIN].refresh_idle_after == timedelta(days=30)


def test_unused_strava_tokens_are_never_refreshed():
    assert PROVIDERS[Provider.STRAVA].refresh_idle_after is None
