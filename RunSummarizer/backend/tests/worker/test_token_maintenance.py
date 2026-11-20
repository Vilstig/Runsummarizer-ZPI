"""TokenMaintenance: unused provider tokens refreshed once per interval, per provider that
has an idle time and a token refresher, each refresh cut off after a timeout."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import anyio
import pytest

from app.core.request_context import log_context_var
from app.domain.enums import Provider
from app.domain.errors import ProviderUnavailableError
from app.domain.models import ProviderCredentials
from app.providers.base import ProviderDefinition
from app.providers.registry import PROVIDERS
from app.providers.strava.budget import STRAVA_BUDGET_POLICY
from app.services import credentials as credentials_service
from app.worker import token_maintenance
from app.worker.token_maintenance import USERS_PER_PASS, TokenMaintenance, maintained

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 11, 17, 12, tzinfo=UTC)
IDLE = timedelta(days=30)
GARMIN = Provider.GARMIN
STRAVA = Provider.STRAVA
EXPIRED = int((NOW - timedelta(days=40)).timestamp())  # an access token unused past IDLE


class Refresher:
    """Counts refreshes; raises ``error`` when it is set, or hangs while ``hang`` is set."""

    def __init__(self):
        self.calls = 0
        self.error: Exception | None = None
        self.hang = False

    async def refresh(self, credentials: ProviderCredentials) -> ProviderCredentials:
        self.calls += 1
        if self.hang:
            await anyio.sleep_forever()
        if self.error is not None:
            raise self.error
        return ProviderCredentials("access-2", "refresh-2", int(NOW.timestamp()) + 86_400)


def definition(
    provider: Provider,
    refresher: Refresher | None,
    *,
    refresh_idle_after: timedelta | None = IDLE,
) -> ProviderDefinition:
    return ProviderDefinition(
        provider=provider,
        is_configured=lambda: True,
        oauth=None,
        token_refresher=refresher,
        importer=lambda: None,
        syncer=None,
        budget_policy=STRAVA_BUDGET_POLICY,
        refresh_idle_after=refresh_idle_after,
    )


def connect(db, provider: Provider, user_id: str) -> None:
    """Connect the user to ``provider`` with an access token unused past ``IDLE``."""
    credentials = ProviderCredentials("access-1", "refresh-1", EXPIRED)
    if provider == STRAVA:
        db.add_strava_user(user_id, 101, "refresh-1")
        db.credentials[user_id] = credentials
    else:
        db.provider_credentials[provider, user_id] = credentials


def maintenance(db, *definitions: ProviderDefinition, **options) -> TokenMaintenance:
    return TokenMaintenance(definitions, transaction=db.transaction, clock=lambda: NOW, **options)


# ---------- provider selection ----------


def test_only_providers_with_an_idle_time_and_a_refresher_are_maintained():
    with_both = definition(GARMIN, Refresher())
    no_idle_time = definition(STRAVA, Refresher(), refresh_idle_after=None)
    no_refresher = definition(Provider.GARMIN, None)

    assert maintained([with_both, no_idle_time, no_refresher]) == [with_both]
    assert TokenMaintenance([with_both, no_idle_time]).providers == [GARMIN]


def test_of_the_registered_providers_only_garmin_is_maintained():
    assert [d.provider for d in maintained(list(PROVIDERS.values()))] == [Provider.GARMIN]


async def test_a_pass_refreshes_the_maintained_providers_only(db):
    garmin, strava = Refresher(), Refresher()
    connect(db, GARMIN, "user-g")
    connect(db, STRAVA, "user-s")

    await maintenance(
        db, definition(GARMIN, garmin), definition(STRAVA, strava, refresh_idle_after=None)
    ).run_once()

    assert (garmin.calls, strava.calls) == (1, 0)
    assert db.provider_credentials[GARMIN, "user-g"].access_token == "access-2"
    assert db.credentials["user-s"].access_token == "access-1"


async def test_each_providers_pass_runs_under_its_own_log_context(db):
    seen = []

    class ContextRefresher(Refresher):
        async def refresh(self, credentials: ProviderCredentials) -> ProviderCredentials:
            seen.append(log_context_var.get())
            return await super().refresh(credentials)

    connect(db, GARMIN, "user-g")
    connect(db, STRAVA, "user-s")

    await maintenance(
        db, definition(GARMIN, ContextRefresher()), definition(STRAVA, ContextRefresher())
    ).run_once()

    assert seen == ["token-maintenance:garmin", "token-maintenance:strava"]
    assert log_context_var.get() == "-"


async def test_a_pass_refreshes_at_most_the_users_per_pass_of_each_provider(db):
    refresher = Refresher()
    for n in range(5):
        connect(db, GARMIN, f"user-{n}")

    await maintenance(db, definition(GARMIN, refresher), users_per_pass=3).run_once()

    assert refresher.calls == 3


async def test_a_pass_refreshes_100_users_a_provider_by_default(db):
    refresher = Refresher()
    for n in range(USERS_PER_PASS + 5):
        connect(db, GARMIN, f"user-{n}")

    await maintenance(db, definition(GARMIN, refresher)).run_once()

    assert USERS_PER_PASS == 100
    assert refresher.calls == 100


# ---------- interval ----------


async def test_run_makes_a_pass_at_once_then_one_per_interval_until_stopped(db, monkeypatch):
    passes: list[Provider] = []

    async def refresh_idle_credentials(provider, *args, **kwargs):
        passes.append(provider)
        if len(passes) == 3:
            stop.set()
        return credentials_service.IdleRefresh()

    monkeypatch.setattr(token_maintenance, "refresh_idle_credentials", refresh_idle_credentials)
    stop = anyio.Event()
    loop = maintenance(db, definition(GARMIN, Refresher()), interval=timedelta(milliseconds=10))

    with anyio.fail_after(5):
        await loop.run(stop)

    assert passes == [GARMIN, GARMIN, GARMIN]


async def test_run_waits_the_interval_between_passes(db, monkeypatch):
    passes: list[Provider] = []

    async def refresh_idle_credentials(provider, *args, **kwargs):
        passes.append(provider)
        return credentials_service.IdleRefresh()

    monkeypatch.setattr(token_maintenance, "refresh_idle_credentials", refresh_idle_credentials)
    stop = anyio.Event()
    loop = maintenance(db, definition(GARMIN, Refresher()), interval=timedelta(hours=1))

    async with anyio.create_task_group() as tasks:
        tasks.start_soon(loop.run, stop)
        await anyio.sleep(0.05)
        stop.set()

    assert passes == [GARMIN]


async def test_run_returns_without_a_pass_once_stopped(db):
    refresher = Refresher()
    connect(db, GARMIN, "user-g")
    stop = anyio.Event()
    stop.set()

    await maintenance(db, definition(GARMIN, refresher)).run(stop)

    assert refresher.calls == 0


# ---------- errors and the timeout ----------


async def test_a_failed_pass_is_logged_and_the_other_providers_still_run(db, monkeypatch, caplog):
    passes: list[Provider] = []

    async def refresh_idle_credentials(provider, *args, **kwargs):
        passes.append(provider)
        if provider == GARMIN:
            raise RuntimeError("database down")
        return credentials_service.IdleRefresh()

    monkeypatch.setattr(token_maintenance, "refresh_idle_credentials", refresh_idle_credentials)

    await maintenance(
        db, definition(GARMIN, Refresher()), definition(STRAVA, Refresher())
    ).run_once()

    assert passes == [GARMIN, STRAVA]
    assert "garmin token maintenance: pass failed" in caplog.text


async def test_a_failed_pass_is_tried_again_at_the_next_interval(db, monkeypatch):
    passes = 0

    async def refresh_idle_credentials(provider, *args, **kwargs):
        nonlocal passes
        passes += 1
        if passes == 2:
            stop.set()
        raise RuntimeError("database down")

    monkeypatch.setattr(token_maintenance, "refresh_idle_credentials", refresh_idle_credentials)
    stop = anyio.Event()

    with anyio.fail_after(5):
        await maintenance(
            db, definition(GARMIN, Refresher()), interval=timedelta(milliseconds=10)
        ).run(stop)

    assert passes == 2


async def test_a_failed_refresh_leaves_the_users_tokens_for_the_next_pass(db):
    refresher = Refresher()
    refresher.error = ProviderUnavailableError("down")
    connect(db, GARMIN, "user-g")

    await maintenance(db, definition(GARMIN, refresher)).run_once()

    assert db.provider_credentials[GARMIN, "user-g"].access_token == "access-1"


async def test_a_hanging_refresh_is_cut_off_and_the_pass_goes_on(db, caplog):
    hanging, working = Refresher(), Refresher()
    hanging.hang = True
    connect(db, GARMIN, "user-g")
    connect(db, STRAVA, "user-s")

    with anyio.fail_after(5):
        await maintenance(
            db,
            definition(GARMIN, hanging),
            definition(STRAVA, working),
            refresh_timeout=timedelta(milliseconds=20),
        ).run_once()

    assert db.provider_credentials[GARMIN, "user-g"].access_token == "access-1"
    assert db.credentials["user-s"].access_token == "access-2"
    assert "took longer than" in caplog.text


async def test_the_configured_timeout_is_handed_to_each_pass(db, monkeypatch):
    seen: list[timedelta] = []

    async def refresh_idle_credentials(provider, refresher, idle, limit, **kwargs):
        seen.append(kwargs["refresh_timeout"])
        return credentials_service.IdleRefresh()

    monkeypatch.setattr(token_maintenance, "refresh_idle_credentials", refresh_idle_credentials)
    garmin = definition(GARMIN, Refresher())

    await maintenance(db, garmin, refresh_timeout=timedelta(seconds=7)).run_once()
    await maintenance(db, replace(garmin)).run_once()

    assert seen == [timedelta(seconds=7), token_maintenance.REFRESH_TIMEOUT]
