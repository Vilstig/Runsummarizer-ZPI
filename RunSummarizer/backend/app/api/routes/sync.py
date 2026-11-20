from datetime import date

from fastapi import APIRouter, Depends, Query, Request, Response

from app.api.deps import get_configured_provider, require_user
from app.api.schemas.errors import ErrorResponse
from app.api.schemas.sync import SyncStartedResponse, SyncStatusResponse
from app.domain.enums import Provider
from app.domain.errors import ProviderNotSupportedError
from app.providers.registry import PROVIDERS
from app.services.sync import SYNC_WINDOW, start_sync, sync_status

router = APIRouter(prefix="/sync", tags=["sync"])


def _registered(provider: Provider) -> Provider:
    """``provider``, once it is known to be registered: 404 otherwise."""
    if provider not in PROVIDERS:
        raise ProviderNotSupportedError("Provider not supported")
    return provider


def _configured(provider: Provider) -> Provider:
    """``provider``, once it is known to be registered and configured: 404 otherwise."""
    get_configured_provider(provider)
    return provider


@router.post(
    "/{provider}",
    status_code=202,
    response_model=SyncStartedResponse,
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Invalid window, or a limit given with a window",
        },
        404: {"model": ErrorResponse, "description": "Provider not supported or not configured"},
        409: {
            "model": ErrorResponse,
            "description": (
                "The provider isn't the user's connected one, the authorization was revoked, "
                "or the provider can't be synced"
            ),
        },
        502: {"model": ErrorResponse, "description": "The provider failed"},
        503: {
            "model": ErrorResponse,
            "description": "The provider's rate limit is used up; see Retry-After",
        },
    },
)
async def start_provider_sync(
    request: Request,
    response: Response,
    user_id: str = Depends(require_user),
    provider: Provider = Depends(_configured),
    after: date | None = Query(
        default=None,
        description=(
            "Start of the window (start of the day, UTC). "
            f"Defaults to {SYNC_WINDOW.days} days before its end."
        ),
        openapi_examples={
            "start": {
                "summary": "Start of year",
                "value": "2026-01-01",
            },
        },
    ),
    before: date | None = Query(
        default=None,
        description="End of the window (start of the day, UTC). Defaults to now.",
        openapi_examples={
            "end": {
                "summary": "Mid year",
                "value": "2026-06-01",
            },
        },
    ),
    limit: int | None = Query(
        default=None,
        description=(
            "Sync the newest runs, at most this many, regardless of date. "
            "Can't be combined with 'after' or 'before'."
        ),
        le=500,
        ge=1,
    ),
):
    """Start a sync of the authenticated user's runs in the window from ``provider``.

    Runs already imported or queued are skipped. The runs are imported in the
    background; ``Location`` is the sync status to poll. ``requested`` when the
    provider sends the runs later, by webhook, instead of listing them now.
    """
    started = await start_sync(provider, user_id, after, before, limit)

    response.headers["Location"] = request.app.url_path_for(
        "provider_sync_status", provider=provider.value
    )
    return SyncStartedResponse(queued=started.queued, requested=started.requested)


@router.get(
    "/{provider}/status",
    name="provider_sync_status",
    response_model=SyncStatusResponse,
    responses={404: {"model": ErrorResponse, "description": "Provider not supported"}},
)
async def provider_sync_status(
    user_id: str = Depends(require_user), provider: Provider = Depends(_registered)
):
    """Whether the authenticated user's runs from ``provider`` are being imported.

    ``needs_reconnect`` when the provider has to be connected again before the
    remaining runs can be imported, else ``syncing`` while some are waiting or being
    imported, or the provider was asked to send them, else ``idle``. Poll it while it
    is ``syncing``.
    """
    state = await sync_status(provider, user_id)
    return SyncStatusResponse(state=state)
