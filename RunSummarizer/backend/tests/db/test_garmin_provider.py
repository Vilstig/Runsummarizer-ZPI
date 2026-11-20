"""Garmin end to end against Postgres: connecting, an ``activityFiles`` notification, the
import by the worker, and the deregistration, through the generic routes, services and
worker, with Garmin's definition talking to a fake Garmin over ``httpx.MockTransport``.
"""

import base64
from dataclasses import replace
from datetime import UTC, datetime
from functools import partial
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import Depends
from sqlalchemy import select

from app.api.deps import (
    get_async_provider_repository,
    get_async_user_repository,
    get_configured_provider,
    get_provider_account_service,
    get_session,
    require_user,
)
from app.api.routes import providers as provider_routes
from app.api.routes import sync as sync_routes
from app.api.routes.webhooks import providers as webhook_routes
from app.db.models import Activity as ActivityRow
from app.db.models import ActivityRawPayload
from app.domain.enums import ImportErrorCode, ImportStatus, Provider, StreamType
from app.main import app
from app.providers.garmin.constants import (
    GARMIN_TOKEN_URL,
    GARMIN_USER_ID_URL,
    GARMIN_USER_PERMISSIONS_URL,
    GARMIN_USER_REGISTRATION_URL,
)
from app.providers.garmin.definition import GARMIN
from app.providers.garmin.importer import GarminImporter
from app.providers.garmin.oauth import GarminOAuth, GarminTokenRefresher
from app.providers.registry import PROVIDERS
from app.services import sync
from app.services.accounts.provider_account_service import ProviderAccountService
from app.services.credentials import fresh_credentials
from app.services.webhook_ingest import ingest_webhook
from app.worker.__main__ import select_providers
from app.worker.loop import ImportWorker
from tests.helpers import configure_garmin, stub_classifier
from tests.providers.fit.fit_builder import running_fit

pytestmark = pytest.mark.anyio

USER_ID = "garmin-e2e-user"
ACCOUNT = "garmin-user-7"  # the user's Garmin user id
CLIENT_ID = "garmin-client-id"
PATH_SECRET = "garmin-path-secret"
WEBHOOK = f"/api/webhooks/garmin/{PATH_SECRET}"
NOW = datetime(2026, 11, 15, 9, 0, tzinfo=UTC)
FILE_URL = "https://apis.garmin.com/wellness-api/rest/activityFile"


class FakeGarmin:
    """Garmin's OAuth, user and activity file endpoints. Each file can be downloaded once."""

    def __init__(self):
        self.files: dict[str, bytes] = {}  # file id -> FIT file
        self.downloaded: list[str] = []  # file ids, in download order
        self.deregistered: list[str] = []  # access tokens

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url.copy_with(query=None))
        if (request.method, url) == ("POST", GARMIN_TOKEN_URL):
            return httpx.Response(
                200,
                json={
                    "access_token": "access-1",
                    "refresh_token": "refresh-1",
                    "expires_in": 86400,
                },
            )
        if (request.method, url) == ("GET", GARMIN_USER_ID_URL):
            return httpx.Response(200, json={"userId": ACCOUNT})
        if (request.method, url) == ("GET", GARMIN_USER_PERMISSIONS_URL):
            return httpx.Response(200, json={"permissions": ["ACTIVITY_EXPORT"]})
        if (request.method, url) == ("DELETE", GARMIN_USER_REGISTRATION_URL):
            self.deregistered.append(request.headers["Authorization"].removeprefix("Bearer "))
            return httpx.Response(204)
        if (request.method, url) == ("GET", FILE_URL):
            assert request.headers["Authorization"] == "Bearer access-1"
            file_id = request.url.params["id"]
            if file_id in self.downloaded or file_id not in self.files:
                return httpx.Response(410)
            self.downloaded.append(file_id)
            return httpx.Response(200, content=self.files[file_id])
        return httpx.Response(404)


async def no_wait(_seconds: float) -> None:
    """A sleep that returns at once."""


@pytest.fixture
def garmin(monkeypatch) -> FakeGarmin:
    """The fake Garmin, with Garmin's definition registered to call it."""
    configure_garmin(
        monkeypatch,
        client_id=CLIENT_ID,
        client_secret="client-secret",
        redirect_uri="http://test/api/providers/garmin/callback",
        webhook_path_secret=PATH_SECRET,
    )
    fake = FakeGarmin()
    transport = fake.transport()
    definition = replace(
        GARMIN,
        oauth=GarminOAuth(transport=transport, clock=lambda: NOW, sleep=no_wait),
        token_refresher=GarminTokenRefresher(transport=transport, clock=lambda: NOW),
        importer=partial(GarminImporter, transport=transport, clock=lambda: NOW),
    )
    monkeypatch.setitem(PROVIDERS, Provider.GARMIN, definition)
    return fake


@pytest.fixture(autouse=True)
def classifier(monkeypatch):
    stub_classifier(monkeypatch)


@pytest.fixture
async def client(monkeypatch, db_session, rolled_back_transaction, garmin):
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
def worker(rolled_back_transaction, garmin) -> ImportWorker:
    """The Garmin import worker, as ``python -m app.worker --provider garmin`` builds it."""
    [definition], _ = select_providers(Provider.GARMIN)
    return ImportWorker(
        definition.importer(),
        budget_policy=definition.budget_policy,
        token_refresher=definition.token_refresher,
        transaction=rolled_back_transaction,
        clock=lambda: NOW,
    )


def file_entry(activity_id: int, **fields) -> dict:
    return {
        "userId": ACCOUNT,
        "summaryId": str(activity_id),
        "fileType": "FIT",
        "callbackURL": f"{FILE_URL}?id={activity_id}&token=download-token",
        "startTimeInSeconds": int(NOW.timestamp()),
        "activityId": activity_id,
        "activityName": "Morning Run",
        "activityType": "RUNNING",
        "deviceName": "Forerunner 965",
        **fields,
    }


async def connect(client: httpx.AsyncClient) -> None:
    started = await client.get("/api/v1/providers/garmin/connect")
    assert started.status_code == 200
    query = parse_qs(urlsplit(started.json()["authorize_url"]).query)
    assert query["code_challenge_method"] == ["S256"]
    linked = await client.get(
        "/api/providers/garmin/callback", params={"code": "code-1", "state": query["state"][0]}
    )
    assert linked.status_code == 302
    assert "error" not in parse_qs(urlsplit(linked.headers["Location"]).query)


async def notify(client: httpx.AsyncClient, body: dict) -> httpx.Response:
    return await client.post(WEBHOOK, json=body, headers={"garmin-client-id": CLIENT_ID})


async def import_all(worker: ImportWorker) -> None:
    while await worker.run_once():
        pass


async def provider_status(client: httpx.AsyncClient) -> dict:
    statuses = (await client.get("/api/v1/providers")).json()
    return next(status for status in statuses if status["provider"] == "garmin")


async def payload_kinds(db_session, activity_key: str) -> list[str]:
    query = (
        select(ActivityRawPayload.payload_kind)
        .join(ActivityRow, ActivityRow.id == ActivityRawPayload.activity_id)
        .where(ActivityRow.user_id == USER_ID, ActivityRow.activity_key == activity_key)
    )
    return list((await db_session.execute(query)).scalars())


async def test_a_run_notified_by_garmin_is_imported_until_the_user_deregisters(
    client, worker, garmin, activity_repo, queue, db_session
):
    fit = running_fit()
    garmin.files["901"] = fit

    await connect(client)
    status = await provider_status(client)
    synced = await client.post("/api/v1/sync/garmin")
    notified = await notify(client, {"activityFiles": [file_entry(901)]})
    await import_all(worker)

    assert (status["configured"], status["connected"], status["can_sync"]) == (True, True, False)
    assert synced.status_code == 409
    assert notified.status_code == 200
    assert garmin.downloaded == ["901"]
    record = await activity_repo.get_by_id("garmin_901", user_id=USER_ID)
    activity = record.activity
    assert activity.source is Provider.GARMIN
    assert activity.name == "Morning Run"
    assert activity.device_name == "Forerunner 965"
    assert [lap.avg_hr for lap in activity.laps] == [148, 156]
    assert all(lap.type is not None for lap in activity.laps)
    streams = await activity_repo.get_streams("garmin_901", user_id=USER_ID)
    assert streams[StreamType.HEARTRATE.value][0] == 140
    assert await payload_kinds(db_session, "garmin_901") == ["garmin_activity_file"]
    stored = await activity_repo.get_raw_payload("garmin_901", user_id=USER_ID)
    assert base64.b64decode(stored["file"]) == fit
    assert "callbackURL" not in stored["notification"]
    assert await queue.recent_failures(USER_ID, Provider.GARMIN) == []

    deregistered = await notify(client, {"deregistrations": [{"userId": ACCOUNT}]})
    status_after = await provider_status(client)

    assert deregistered.status_code == 200
    assert status_after["connected"] is False
    assert await activity_repo.is_stored(USER_ID, "garmin_901")


async def test_runs_only_are_queued_and_a_spent_link_leaves_the_item_dead(
    client, worker, garmin, activity_repo, queue
):
    garmin.files["902"] = running_fit()
    await connect(client)

    await notify(
        client,
        {
            "activityFiles": [
                file_entry(902),
                file_entry(903, activityType="CYCLING"),
                file_entry(904, callbackURL="https://evil.example/file?id=904"),
            ]
        },
    )
    garmin.downloaded.append("902")  # the link was spent elsewhere
    await import_all(worker)

    assert not await activity_repo.is_stored(USER_ID, "garmin_902")
    [failure] = await queue.recent_failures(USER_ID, Provider.GARMIN)
    assert (failure.activity_key, failure.error_code) == ("garmin_902", ImportErrorCode.NOT_FOUND)
    counts = await queue.count_by_status(USER_ID, Provider.GARMIN)
    assert {status: n for status, n in counts.items() if n} == {ImportStatus.DEAD: 1}


async def test_a_disconnect_deregisters_the_user_at_garmin(client, garmin, rolled_back_transaction):
    def accounts(
        definition=Depends(get_configured_provider),
        user_repo=Depends(get_async_user_repository),
        provider_repo=Depends(get_async_provider_repository),
    ) -> ProviderAccountService:
        credentials = partial(
            fresh_credentials, transaction=rolled_back_transaction, clock=lambda: NOW
        )
        return ProviderAccountService(
            definition, user_repo, provider_repo, fresh_credentials=credentials
        )

    await connect(client)
    app.dependency_overrides[get_provider_account_service] = accounts
    try:
        disconnected = await client.delete("/api/v1/providers/garmin/connection")
    finally:
        app.dependency_overrides.pop(get_provider_account_service, None)
    status = await provider_status(client)

    assert disconnected.status_code == 204
    assert garmin.deregistered == ["access-1"]
    assert status["connected"] is False


@pytest.mark.parametrize(
    "headers", [{"garmin-client-id": "another-app"}, {}], ids=["another app", "no client id"]
)
async def test_a_notification_not_for_this_app_is_rejected(client, garmin, headers):
    await connect(client)

    response = await client.post(
        WEBHOOK, json={"deregistrations": [{"userId": ACCOUNT}]}, headers=headers
    )

    assert response.status_code == 403
    assert (await provider_status(client))["connected"] is True


async def test_a_notification_with_a_wrong_path_secret_is_refused(client, garmin):
    response = await client.post(
        "/api/webhooks/garmin/wrong", json={"deregistrations": [{"userId": ACCOUNT}]}
    )

    assert response.status_code == 403
