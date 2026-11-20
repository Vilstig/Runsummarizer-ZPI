"""A test-only provider, registered in the registry, connected, synced, sent a webhook and
imported through the generic routes, services and worker, against Postgres. Nothing in
it is Strava's: it checks that a provider takes part through its definition alone.

The provider can also send data with its webhook, fetch it from a single-use link, and
go without a syncer.
"""

import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from functools import partial
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import pytest
from sqlalchemy import select

from app.api.deps import get_session, require_user
from app.api.routes import providers as provider_routes
from app.api.routes import sync as sync_routes
from app.api.routes.webhooks import providers as webhook_routes
from app.db.models import Activity as ActivityRow
from app.db.models import ActivityRawPayload
from app.db.protocols.import_queue import Claim, QueuedItem
from app.domain.enums import ImportPriority, Provider, WindowKind
from app.domain.errors import ProviderActivityNotFoundError
from app.domain.models import (
    BudgetPolicy,
    BudgetWindow,
    ProviderCredentials,
    RateLimitUsage,
    WindowUsage,
    ZoneTimes,
)
from app.main import app
from app.providers.base import (
    IMPORT_MAX_ATTEMPTS,
    AccountRevoked,
    ActivityChanged,
    AuthorizationStart,
    LinkResult,
    Listed,
    ListedActivity,
    NormalizedActivity,
    ProviderDefinition,
    Requested,
    ResponseObserver,
    SyncStart,
    SyncWindow,
    WebhookCommand,
)
from app.providers.registry import PROVIDERS
from app.services import activity_pipeline, sync
from app.services.activity_import import LEASE
from app.services.webhook_ingest import ingest_webhook
from app.worker.__main__ import select_providers
from app.worker.loop import ImportWorker
from tests.db.builders import make_run
from tests.helpers import stub_classifier

pytestmark = pytest.mark.anyio

# The fake provider is registered in place of Garmin's definition.
PROVIDER = Provider.GARMIN
NAME = PROVIDER.value
USER_ID = "fake-provider-user"
ACCOUNT = "fake-account-1"  # the user's account at the provider
PATH_SECRET = "fake-path-secret"
NOW = datetime(2026, 11, 11, 9, 0, tzinfo=UTC)
LIMIT = 500  # calls per hour, as the fake provider reports it

HOUR = BudgetWindow(
    name="hour",
    length=timedelta(hours=1),
    kind=WindowKind.ROLLING,
    bucket=timedelta(minutes=1),
    default_limit=100,
)


def observe(response: httpx.Response) -> RateLimitUsage | None:
    """The hourly usage the fake provider reports in its ``X-Used`` and ``X-Limit`` headers."""
    if "X-Used" not in response.headers:
        return None
    return RateLimitUsage(
        {HOUR.name: WindowUsage(int(response.headers["X-Used"]), int(response.headers["X-Limit"]))}
    )


POLICY = BudgetPolicy(
    windows=(HOUR,),
    ceilings={ImportPriority.SYNC: {HOUR.name: 80}},
    observe=observe,
)


class WorkerDiedError(BaseException):
    """Ends an import the way a killed worker does: nothing after it is written."""


class FakeProviderAPI:
    """The fake provider's side: the user's activities, and what the app asked of it."""

    def __init__(self):
        self.activities: dict[str, datetime] = {}  # activity key -> start time
        self.requests_data = False  # whether a sync asks for a webhook instead of a listing
        self.exchanged: list[tuple[dict, dict]] = []  # (callback params, secrets)
        self.refreshes = 0
        self.fetched: list[tuple[str, str]] = []  # (activity key, access token)
        self.single_use = False  # whether a fetch spends the link the webhook sent
        self.links: dict[str, str] = {}  # activity key -> the link its webhook sent
        self.spent: set[str] = set()  # links already downloaded

    def response(self) -> httpx.Response:
        return httpx.Response(200, headers={"X-Used": "1", "X-Limit": str(LIMIT)})


class FakeOAuth:
    """OAuth 2 with a PKCE-like verifier that has to survive until the callback."""

    def __init__(self, api: FakeProviderAPI):
        self._api = api

    def default_redirect_uri(self) -> str:
        return f"http://test/api/providers/{NAME}/callback"

    async def start_authorization(self, state: str, redirect_uri: str) -> AuthorizationStart:
        query = urlencode({"state": state, "redirect_uri": redirect_uri})
        return AuthorizationStart(
            url=f"https://fake.example/authorize?{query}", secrets={"verifier": "verifier-1"}
        )

    async def exchange(self, params: Mapping[str, str], secrets: dict[str, str]) -> LinkResult:
        self._api.exchanged.append((dict(params), secrets))
        # expires within the refresh margin, so the first use refreshes it
        expires_at = int((NOW + timedelta(seconds=60)).timestamp())
        return LinkResult(ACCOUNT, ProviderCredentials("access-1", "refresh-1", expires_at))

    async def revoke(self, credentials: ProviderCredentials) -> None:
        return None


class FakeRefresher:
    def __init__(self, api: FakeProviderAPI):
        self._api = api

    async def refresh(self, credentials: ProviderCredentials) -> ProviderCredentials:
        self._api.refreshes += 1
        expires_at = int((NOW + timedelta(days=1)).timestamp())
        return ProviderCredentials("access-2", "refresh-2", expires_at)


class FakeSyncer:
    def __init__(self, api: FakeProviderAPI):
        self._api = api

    async def start(
        self,
        credentials: ProviderCredentials,
        window: SyncWindow | None,
        limit: int | None,
        on_response: ResponseObserver,
    ) -> SyncStart:
        await on_response(self._api.response(), NOW)
        if self._api.requests_data:
            return Requested()
        return Listed([ListedActivity(key, start) for key, start in self._api.activities.items()])


class FakeImporter:
    provider = PROVIDER
    max_attempts = IMPORT_MAX_ATTEMPTS

    def __init__(self, api: FakeProviderAPI):
        self._api = api

    @property
    def single_use_fetch(self) -> bool:
        return self._api.single_use

    def cost(self, item: QueuedItem) -> int:
        return 1

    async def fetch(
        self, claim: Claim, credentials: ProviderCredentials, on_response: ResponseObserver
    ) -> dict | None:
        self._api.fetched.append((claim.activity_key, credentials.access_token))
        await on_response(self._api.response(), NOW)
        if self._api.single_use:
            link = (claim.sent_data or {}).get("link")
            if link is None or link in self._api.spent:
                raise ProviderActivityNotFoundError(f"{link} is gone")
            self._api.spent.add(link)
        start = self._api.activities[claim.activity_key]
        return {"format": "fake_v1", "key": claim.activity_key, "start": start.isoformat()}

    def normalize(self, payload: dict) -> NormalizedActivity | None:
        activity = make_run(payload["key"], source=NAME, start_time_local=payload["start"])
        activity = replace(activity, zone_times=ZoneTimes(), zone_bounds=None)
        return NormalizedActivity(
            activity=activity, streams={}, payload_kind="fake_activity", stored_payload=payload
        )


class FakeWebhookParser:
    """Events are JSON: ``{"account", "activity"}``, with an optional ``"link"`` sent with it,
    or ``{"account", "revoked": true}``."""

    def path_secret(self) -> str:
        return PATH_SECRET

    def verify_subscription(self, query: Mapping[str, str]) -> dict | None:
        return {"challenge": query["challenge"]} if "challenge" in query else None

    def parse(self, body: bytes, headers: Mapping[str, str]) -> list[WebhookCommand]:
        event = json.loads(body)
        if event.get("revoked"):
            return [AccountRevoked(event["account"])]
        sent_data = {"link": event["link"]} if "link" in event else None
        return [ActivityChanged(event["account"], event["activity"], sent_data)]


@pytest.fixture
def api(monkeypatch) -> FakeProviderAPI:
    """The fake provider's API, its definition registered under ``PROVIDER``."""
    fake = FakeProviderAPI()
    definition = ProviderDefinition(
        provider=PROVIDER,
        is_configured=lambda: True,
        oauth=FakeOAuth(fake),
        token_refresher=FakeRefresher(fake),
        importer=partial(FakeImporter, fake),
        syncer=partial(FakeSyncer, fake),
        budget_policy=POLICY,
        webhook=FakeWebhookParser(),
    )
    monkeypatch.setitem(PROVIDERS, PROVIDER, definition)
    return fake


@pytest.fixture(autouse=True)
def classifier(monkeypatch):
    stub_classifier(monkeypatch)


@pytest.fixture
async def client(monkeypatch, db_session, rolled_back_transaction, api):
    """The API, signed in as ``USER_ID``, over the test's transaction at ``NOW``."""

    async def session():
        yield db_session

    services = {"transaction": rolled_back_transaction, "clock": lambda: NOW}
    monkeypatch.setattr(sync_routes, "start_sync", partial(sync.start_sync, **services))
    monkeypatch.setattr(sync_routes, "sync_status", partial(sync.sync_status, **services))
    monkeypatch.setattr(
        provider_routes, "provider_statuses", partial(sync.provider_statuses, **services)
    )
    monkeypatch.setattr(webhook_routes, "ingest_webhook", partial(ingest_webhook, **services))
    monkeypatch.setattr("app.services.accounts.oauth_state.OAUTH_STATE_SECRET", "test-secret")
    app.dependency_overrides[get_session] = session
    app.dependency_overrides[require_user] = lambda: USER_ID
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(require_user, None)


@pytest.fixture
def worker(rolled_back_transaction) -> ImportWorker:
    """The import worker for ``PROVIDER``, as ``python -m app.worker --provider`` builds it."""
    [definition], _ = select_providers(PROVIDER)
    return ImportWorker(
        definition.importer(),
        budget_policy=definition.budget_policy,
        token_refresher=definition.token_refresher,
        transaction=rolled_back_transaction,
        clock=lambda: NOW,
    )


async def connect(client: httpx.AsyncClient) -> None:
    started = await client.get(f"/api/v1/providers/{NAME}/connect")
    assert started.status_code == 200
    state = parse_qs(urlsplit(started.json()["authorize_url"]).query)["state"][0]
    linked = await client.get(
        f"/api/providers/{NAME}/callback", params={"code": "code-1", "state": state}
    )
    assert linked.status_code == 302


async def import_all(worker: ImportWorker) -> None:
    while await worker.run_once():
        pass


async def sync_state(client: httpx.AsyncClient) -> str:
    return (await client.get(f"/api/v1/sync/{NAME}/status")).json()["state"]


async def provider_status(client: httpx.AsyncClient) -> dict:
    statuses = (await client.get("/api/v1/providers")).json()
    return next(status for status in statuses if status["provider"] == NAME)


async def payload_kinds(db_session, activity_key: str) -> list[str]:
    """The kinds of the raw payloads stored with the user's activity."""
    query = (
        select(ActivityRawPayload.payload_kind)
        .join(ActivityRow, ActivityRow.id == ActivityRawPayload.activity_id)
        .where(ActivityRow.user_id == USER_ID, ActivityRow.activity_key == activity_key)
    )
    return list((await db_session.execute(query)).scalars())


async def test_a_listed_sync_is_imported(client, worker, api, activity_repo, budget, db_session):
    api.activities = {
        "fake_1": datetime(2026, 11, 9, 7, 0, tzinfo=UTC),
        "fake_2": datetime(2026, 11, 10, 7, 0, tzinfo=UTC),
    }

    await connect(client)
    status = await provider_status(client)
    synced = await client.post(f"/api/v1/sync/{NAME}")
    state_while_queued = await sync_state(client)
    await import_all(worker)

    [(params, secrets)] = api.exchanged
    assert (params["code"], secrets) == ("code-1", {"verifier": "verifier-1"})
    assert (status["configured"], status["can_sync"], status["connected"]) == (True, True, True)
    assert synced.status_code == 202
    assert synced.json() == {"queued": 2, "requested": False}
    assert synced.headers["Location"] == f"/api/v1/sync/{NAME}/status"
    assert state_while_queued == "syncing"
    # newest first, with the token refreshed once and saved
    assert api.fetched == [("fake_2", "access-2"), ("fake_1", "access-2")]
    assert api.refreshes == 1
    for key in api.activities:
        record = await activity_repo.get_by_id(key, user_id=USER_ID)
        assert record.activity.source is PROVIDER
        assert (await activity_repo.get_raw_payload(key, user_id=USER_ID))["key"] == key
        assert await payload_kinds(db_session, key) == ["fake_activity"]
    assert await sync_state(client) == "idle"
    usage = await budget.get_usage(PROVIDER, policy=POLICY, now=NOW)
    assert usage.windows[HOUR.name] == WindowUsage(used=2, limit=LIMIT)


async def test_a_requested_sync_is_imported_from_the_webhook(client, worker, api, activity_repo):
    api.requests_data = True
    api.activities = {"fake_3": datetime(2026, 11, 10, 7, 0, tzinfo=UTC)}

    await connect(client)
    synced = await client.post(f"/api/v1/sync/{NAME}")
    state_while_requested = await sync_state(client)
    check = await client.get(f"/api/webhooks/{NAME}/{PATH_SECRET}", params={"challenge": "c-1"})
    event = await client.post(
        f"/api/webhooks/{NAME}/{PATH_SECRET}", json={"account": ACCOUNT, "activity": "fake_3"}
    )
    await import_all(worker)

    assert synced.status_code == 202
    assert synced.json() == {"queued": 0, "requested": True}
    assert state_while_requested == "syncing"
    assert (check.status_code, check.json()) == (200, {"challenge": "c-1"})
    assert event.status_code == 200
    assert api.fetched == [("fake_3", "access-2")]
    assert await activity_repo.is_stored(USER_ID, "fake_3")
    assert await sync_state(client) == "idle"


async def test_a_revocation_by_webhook_disconnects_the_user(client, api):
    await connect(client)

    event = await client.post(
        f"/api/webhooks/{NAME}/{PATH_SECRET}", json={"account": ACCOUNT, "revoked": True}
    )
    status = await provider_status(client)
    synced = await client.post(f"/api/v1/sync/{NAME}")

    assert event.status_code == 200
    assert status["connected"] is False
    assert synced.status_code == 409


async def test_a_single_use_fetch_survives_a_worker_lost_after_the_download(
    client, worker, api, activity_repo, rolled_back_transaction, monkeypatch
):
    api.single_use = True
    api.activities = {"fake_5": datetime(2026, 11, 10, 7, 0, tzinfo=UTC)}
    [definition], _ = select_providers(PROVIDER)
    importer = definition.importer()
    build_import = activity_pipeline.build_import
    deaths: list[str] = []

    def die_once(normalized, *args):
        if not deaths:
            deaths.append(normalized.activity.key)
            raise WorkerDiedError
        return build_import(normalized, *args)

    monkeypatch.setattr(activity_pipeline, "build_import", die_once)
    after_lease = NOW + LEASE + timedelta(seconds=1)
    restarted = ImportWorker(
        importer,
        budget_policy=POLICY,
        token_refresher=definition.token_refresher,
        transaction=rolled_back_transaction,
        clock=lambda: after_lease,
    )

    await connect(client)
    event = await client.post(
        f"/api/webhooks/{NAME}/{PATH_SECRET}",
        json={"account": ACCOUNT, "activity": "fake_5", "link": "https://fake.example/f/5"},
    )
    with pytest.raises(WorkerDiedError):
        await worker.run_once()
    state_after_the_crash = await sync_state(client)
    await restarted.sweep()
    await import_all(restarted)

    assert event.status_code == 200
    assert importer.single_use_fetch is True
    assert deaths == ["fake_5"]
    assert state_after_the_crash == "syncing"
    assert api.fetched == [("fake_5", "access-2")]
    assert api.spent == {"https://fake.example/f/5"}
    assert await activity_repo.is_stored(USER_ID, "fake_5")
    assert await sync_state(client) == "idle"


async def test_a_provider_without_a_syncer_is_not_synced(client, api, monkeypatch):
    monkeypatch.setitem(PROVIDERS, PROVIDER, replace(PROVIDERS[PROVIDER], syncer=None))

    await connect(client)
    status = await provider_status(client)
    synced = await client.post(f"/api/v1/sync/{NAME}")

    assert (status["connected"], status["can_sync"]) == (True, False)
    assert synced.status_code == 409
    assert synced.json()["code"] == "sync_not_supported"
    assert api.fetched == []
    assert await sync_state(client) == "idle"
