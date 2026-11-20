from datetime import timedelta

import anyio
import pytest

from app.domain.enums import Provider
from app.providers.base import ProviderDefinition
from app.providers.strava.budget import STRAVA_BUDGET_POLICY
from app.worker import __main__ as worker_main
from app.worker.token_maintenance import TokenMaintenance
from tests.helpers import unconfigure_garmin

STRAVA = Provider.STRAVA
GARMIN = Provider.GARMIN


class StubImporter:
    def __init__(self, provider: Provider):
        self.provider = provider


def definition(
    provider: Provider,
    *,
    configured: bool = True,
    token_refresher: object = None,
    refresh_idle_after: timedelta | None = None,
) -> ProviderDefinition:
    return ProviderDefinition(
        provider=provider,
        is_configured=lambda: configured,
        oauth=None,
        token_refresher=token_refresher,
        importer=lambda: StubImporter(provider),
        syncer=None,
        budget_policy=STRAVA_BUDGET_POLICY,
        refresh_idle_after=refresh_idle_after,
    )


@pytest.fixture
def registry(monkeypatch):
    """Replace the registry with ``{provider: definition}``; returns a setter."""

    def use(*definitions: ProviderDefinition) -> None:
        providers = {d.provider: d for d in definitions}
        monkeypatch.setattr(worker_main, "PROVIDERS", providers)

    return use


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setattr(worker_main, "POSTGRES_DSN", "postgresql+asyncpg://localhost/db")
    monkeypatch.setattr(worker_main, "TOKEN_ENCRYPTION_KEY", "key")
    monkeypatch.setattr(worker_main, "configure_logging", lambda: None)


@pytest.fixture
def ran(monkeypatch) -> list[list[Provider]]:
    """The providers of each ``run_worker`` call, which runs nothing."""
    calls: list[list[Provider]] = []

    async def run_worker(definitions) -> None:
        calls.append([d.provider for d in definitions])

    monkeypatch.setattr(worker_main, "run_worker", run_worker)
    return calls


# ---------- select_providers ----------


def test_every_configured_provider_runs_and_the_others_are_skipped(registry):
    registry(definition(STRAVA), definition(GARMIN, configured=False))

    running, skipped = worker_main.select_providers()

    assert [d.provider for d in running] == [STRAVA]
    assert skipped == {GARMIN: "not configured"}


def test_the_registered_garmin_is_skipped_while_its_settings_are_unset(monkeypatch):
    unconfigure_garmin(monkeypatch)

    _, skipped = worker_main.select_providers()

    assert skipped[GARMIN] == "not configured"


def test_only_the_provider_asked_for_runs(registry):
    registry(definition(STRAVA), definition(GARMIN))

    running, skipped = worker_main.select_providers(GARMIN)

    assert [d.provider for d in running] == [GARMIN]
    assert skipped == {STRAVA: "not selected"}


def test_a_provider_asked_for_that_is_not_configured_raises(registry):
    registry(definition(STRAVA), definition(GARMIN, configured=False))

    with pytest.raises(worker_main.ProviderNotConfiguredError):
        worker_main.select_providers(GARMIN)


# ---------- main ----------


def test_main_runs_the_configured_providers(registry, settings, ran, caplog):
    registry(definition(STRAVA), definition(GARMIN, configured=False))
    caplog.set_level("INFO", logger="app.worker")

    assert worker_main.main([]) == 0

    assert ran == [[STRAVA]]
    assert "skipping garmin (not configured)" in caplog.text
    assert "started for strava" in caplog.text


def test_main_runs_only_the_provider_flag(registry, settings, ran, caplog):
    registry(definition(STRAVA), definition(GARMIN))
    caplog.set_level("INFO", logger="app.worker")

    assert worker_main.main(["--provider", "garmin"]) == 0

    assert ran == [[GARMIN]]
    assert "skipping strava (not selected)" in caplog.text


def test_main_refuses_a_provider_flag_that_is_not_registered(registry, settings, ran):
    registry(definition(STRAVA))

    with pytest.raises(SystemExit):
        worker_main.main(["--provider", "garmin"])

    assert ran == []


def test_main_refuses_a_provider_flag_that_is_not_configured(registry, settings, ran):
    registry(definition(STRAVA, configured=False))

    assert worker_main.main(["--provider", "strava"]) == 1

    assert ran == []


@pytest.mark.parametrize("name", ["POSTGRES_DSN", "TOKEN_ENCRYPTION_KEY"])
def test_main_needs_the_database_and_encryption_settings(
    registry, settings, ran, monkeypatch, caplog, name
):
    registry(definition(STRAVA))
    monkeypatch.setattr(worker_main, name, None)

    assert worker_main.main([]) == 1

    assert ran == []
    assert name in caplog.text


def test_main_needs_a_configured_provider(registry, settings, ran, caplog):
    registry(definition(STRAVA, configured=False))

    assert worker_main.main([]) == 1

    assert ran == []
    assert "no provider is configured" in caplog.text


# ---------- run_worker ----------


class FakeWorker:
    """An import loop that records its provider, and stops every loop once ``expected``
    of them started."""

    started: list[Provider]
    expected = 2

    def __init__(self, importer, *, budget_policy, token_refresher):
        self._provider = importer.provider

    async def run(self, stop: anyio.Event) -> None:
        self.started.append(self._provider)
        if len(self.started) == self.expected:
            stop.set()
        await stop.wait()


class StalledMaintenance(TokenMaintenance):
    """A token maintenance whose ``run`` never returns: it hangs, as on a stalled call."""

    runs: list[list[Provider]]

    async def run(self, stop: anyio.Event) -> None:
        self.runs.append(self.providers)
        await anyio.sleep_forever()


@pytest.fixture
def loops(monkeypatch) -> tuple[list[Provider], list[list[Provider]]]:
    """Fake import loops and maintenance: the providers of the started import loops, and
    the providers of each maintenance run."""
    started: list[Provider] = []
    runs: list[list[Provider]] = []
    monkeypatch.setattr(FakeWorker, "started", started, raising=False)
    monkeypatch.setattr(StalledMaintenance, "runs", runs, raising=False)

    async def dispose_engine() -> None:
        pass

    monkeypatch.setattr(worker_main, "ImportWorker", FakeWorker)
    monkeypatch.setattr(worker_main, "TokenMaintenance", StalledMaintenance)
    monkeypatch.setattr(worker_main, "dispose_engine", dispose_engine)
    return started, runs


@pytest.mark.anyio
async def test_run_worker_runs_one_worker_per_provider_until_all_stop(loops):
    started, _ = loops

    with anyio.fail_after(5):
        await worker_main.run_worker([definition(STRAVA), definition(GARMIN)])

    assert sorted(started) == [GARMIN, STRAVA]


@pytest.mark.anyio
async def test_run_worker_maintains_tokens_in_a_task_that_never_holds_up_the_import_loops(loops):
    started, runs = loops
    maintained = definition(GARMIN, token_refresher=object(), refresh_idle_after=timedelta(30))

    with anyio.fail_after(5):
        await worker_main.run_worker([definition(STRAVA), maintained])

    assert sorted(started) == [GARMIN, STRAVA]
    assert runs == [[GARMIN]]


@pytest.mark.anyio
async def test_run_worker_starts_no_maintenance_without_a_provider_to_maintain(loops):
    started, runs = loops
    no_refresher = definition(GARMIN, refresh_idle_after=timedelta(30))

    with anyio.fail_after(5):
        await worker_main.run_worker([definition(STRAVA), no_refresher])

    assert sorted(started) == [GARMIN, STRAVA]
    assert runs == []
