"""What a provider supplies to take part in connecting accounts, syncing, importing
activities and receiving webhooks, and the errors its calls raise.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

import httpx

from app.config.loader import CONFIG
from app.db.protocols.import_queue import Claim, QueuedItem
from app.domain.enums import Provider
from app.domain.models import Activity, BudgetPolicy, ProviderCredentials

# Receives every response of a provider's API and when its request was sent, e.g. to
# record the rate-limit usage it reports.
type ResponseObserver = Callable[[httpx.Response, datetime], Awaitable[None]]

# Attempts an item gets before ``ProviderUnavailableError`` makes it dead, for an importer
# that takes the shared setting.
IMPORT_MAX_ATTEMPTS: int = CONFIG.get("IMPORT_MAX_ATTEMPTS", 5)


def describe_error(exc: BaseException) -> str:
    """The error text stored on an import item for ``exc``."""
    return f"{type(exc).__name__}: {exc}"


@dataclass(frozen=True)
class AuthorizationStart:
    """Where to send the user to authorize the app, and what the callback needs back."""

    url: str
    # values the callback needs that must not travel through the provider, e.g. a PKCE
    # verifier or an OAuth 1 request-token secret
    secrets: dict[str, str]


@dataclass(frozen=True)
class LinkResult:
    """The provider account an authorization was granted for, and its tokens."""

    provider_user_id: str  # as in provider_accounts.provider_user_id
    credentials: ProviderCredentials


class ProviderOAuth(Protocol):
    """One provider's authorization of the app: HTTP calls only."""

    def default_redirect_uri(self) -> str:
        """The callback URL registered with the provider."""

    async def start_authorization(self, state: str, redirect_uri: str) -> AuthorizationStart:
        """The authorize URL carrying the CSRF ``state``, which the provider sends back
        to ``redirect_uri``.

        Raises ``ProviderUnavailableError`` when a call it needs fails.
        """

    async def exchange(self, params: Mapping[str, str], secrets: dict[str, str]) -> LinkResult:
        """The account and tokens of the authorization the callback's query ``params``
        report, with the ``secrets`` of ``start_authorization``.

        Raises ``ProviderAuthorizationError`` when the user declined or the provider
        rejects the grant, ``ProviderResponseError`` for an unusable response, and
        ``ProviderUnavailableError`` when the provider fails or can't be reached.
        """

    async def revoke(self, credentials: ProviderCredentials) -> None:
        """Revoke the authorization behind ``credentials``. An authorization the
        provider already rejects counts as revoked.

        Raises ``ProviderUnavailableError`` when the provider fails or can't be reached.
        """


class TokenRefresher(Protocol):
    """Renews a provider's expiring access tokens: HTTP calls only."""

    async def refresh(self, credentials: ProviderCredentials) -> ProviderCredentials:
        """New credentials in place of ``credentials``.

        Raises ``ProviderAuthorizationError`` when the provider rejects the refresh,
        ``RateLimitedError`` when its rate limit is used up, and
        ``ProviderUnavailableError`` when it fails or can't be reached.
        """


@dataclass(frozen=True)
class SyncWindow:
    """The span a sync lists the activities of: those starting in [start, end)."""

    start: datetime
    end: datetime


@dataclass(frozen=True)
class ListedActivity:
    """An activity a provider listed for a sync."""

    activity_key: str  # as in activities.activity_key
    start_time: datetime


@dataclass(frozen=True)
class Listed:
    """The provider listed the activities to queue."""

    activities: list[ListedActivity]


@dataclass(frozen=True)
class Requested:
    """The provider was asked to send the activities later, by webhook."""


SyncStart = Listed | Requested


class ProviderSyncer(Protocol):
    """One provider's part in syncing a user's activities."""

    async def start(
        self,
        credentials: ProviderCredentials,
        window: SyncWindow | None,
        limit: int | None,
        on_response: ResponseObserver,
    ) -> SyncStart:
        """Start a sync, with the user's ``credentials``, of their activities in
        ``window``, or without a window of their newest ``limit`` activities. Every
        response of the provider's API is passed to ``on_response``.

        Raises ``RateLimitedError`` when the provider's rate limit is used up,
        ``ProviderAuthorizationError`` when the authorization no longer works, and
        ``ProviderUnavailableError`` when the provider fails or can't be reached.
        """


@dataclass(frozen=True)
class NormalizedActivity:
    """A provider's activity in the app's terms, before the import pipeline runs."""

    activity: Activity  # laps not classified, HR-zone times zero
    streams: dict  # {StreamType: samples}
    payload_kind: str  # activity_raw_payloads.payload_kind, e.g. 'strava_detail'
    stored_payload: dict  # what activity_raw_payloads keeps


class ProviderImporter(Protocol):
    """One provider's part in importing its queued items."""

    provider: Provider
    # whether a second ``fetch`` of the same item can't succeed, e.g. a single-use
    # download link; the fetched payload is then saved on the item before processing
    single_use_fetch: bool
    # attempts an item gets before ``ProviderUnavailableError``, or a worker lost
    # mid-import, makes it dead
    max_attempts: int

    def cost(self, item: QueuedItem) -> int:
        """The provider calls that fetching ``item`` takes."""

    async def fetch(
        self, claim: Claim, credentials: ProviderCredentials, on_response: ResponseObserver
    ) -> dict | None:
        """The claimed item's payload, fetched with the user's ``credentials``: plain JSON
        that ``normalize`` takes, tagged with its ``"format"``. None when the activity is
        not one to import. Every response of the provider's API is passed to
        ``on_response``.

        Raises ``RateLimitedError`` when the provider's rate limit is used up, another
        ``FetchError`` for a failure the queue handles; any other error propagates.
        """

    def normalize(self, payload: dict) -> NormalizedActivity | None:
        """The activity in ``payload``, a ``fetch`` payload, without calling the provider.
        None when it is not one to import.

        Synchronous: it runs in a worker thread. Any error is a processing failure.
        """


@dataclass(frozen=True)
class ActivityChanged:
    """An activity was created or changed at the provider."""

    provider_user_id: str  # as in provider_accounts.provider_user_id
    activity_key: str  # as in activities.activity_key
    # what the provider sent with the event, kept on the import item for ``fetch``; may
    # hold a download token, so it is left out of the repr and never logged; left out of
    # the hash, so the command stays hashable
    sent_data: dict | None = field(default=None, repr=False, hash=False)


@dataclass(frozen=True)
class AccountRevoked:
    """The user revoked the app's access at the provider."""

    provider_user_id: str


WebhookCommand = ActivityChanged | AccountRevoked


class WebhookParser(Protocol):
    """One provider's webhook requests, read without side effects."""

    def path_secret(self) -> str:
        """The secret the webhook URL ends with; empty when none is configured."""

    def verify_subscription(self, query: Mapping[str, str]) -> dict | None:
        """The JSON response to a subscription check with ``query``, or None when the
        query isn't one. Raises ``WebhookRejectedError`` for a check the provider
        didn't send.
        """

    def parse(self, body: bytes, headers: Mapping[str, str]) -> list[WebhookCommand]:
        """The commands in a pushed event; empty for an event that changes nothing.
        Raises ``WebhookPayloadError`` for a body that isn't an event, and
        ``WebhookRejectedError`` for an event the provider didn't send (e.g. a wrong
        signature).
        """


@dataclass(frozen=True)
class ProviderDefinition:
    """One provider's parts, as the registry holds them."""

    provider: Provider
    is_configured: Callable[[], bool]  # whether the app has the provider's credentials
    oauth: ProviderOAuth  # authorize, link and revoke
    token_refresher: TokenRefresher | None  # None when the provider's tokens don't expire
    importer: Callable[[], ProviderImporter]  # imports the provider's queued items
    # starts syncs of a user's activities; None when the provider only sends activities
    # by itself, through its webhook
    syncer: Callable[[], ProviderSyncer] | None
    budget_policy: BudgetPolicy  # the provider's rate-limit windows and ceilings
    webhook: WebhookParser | None = None  # None when the provider sends no webhooks
    # how long after its access token expired a connection nothing uses has its tokens
    # refreshed by the worker; None when unused tokens are never refreshed
    refresh_idle_after: timedelta | None = None
