import logging
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse

from app.api.deps import (
    get_provider_account_service,
    get_provider_connection_service,
    require_user,
)
from app.api.schemas.auth import ConnectResponse, OAuthCallbackError, ProviderStatusResponse
from app.api.schemas.errors import ErrorResponse
from app.config.settings import FRONTEND_URL
from app.domain.enums import Provider
from app.domain.errors import (
    AnotherProviderConnectedError,
    DomainError,
    FetchError,
    OAuthStateMismatchError,
    ProviderAccountTakenError,
    ProviderAuthorizationError,
)
from app.services.accounts.connection import ProviderConnectionService
from app.services.accounts.oauth_state import (
    OAUTH_SECRETS_COOKIE,
    OAUTH_STATE_COOKIE,
    OAUTH_STATE_EXPIRE_MINUTES,
)
from app.services.accounts.provider_account_service import (
    ConnectStart,
    ProviderAccountService,
)
from app.services.sync import provider_statuses

logger = logging.getLogger(__name__)

router = APIRouter(tags=["providers"])
# Mounted under /api, outside /v1, so the redirect URI registered with each provider
# stays stable across API versions.
callback_router = APIRouter(tags=["providers"])


def _oauth_cookie_secure(redirect_uri: str) -> bool:
    return redirect_uri.lower().startswith("https://")


def _callback_path(provider: Provider) -> str:
    return f"/api/providers/{provider}/callback"


def _set_oauth_cookie(
    *, response: Response, key: str, value: str, redirect_uri: str, provider: Provider
) -> None:
    response.set_cookie(
        key=key,
        value=value,
        max_age=OAUTH_STATE_EXPIRE_MINUTES * 60,
        httponly=True,
        secure=_oauth_cookie_secure(redirect_uri),
        samesite="lax",
        # Scoped to the callback route, the only reader.
        path=_callback_path(provider),
    )


def _clear_oauth_cookies(response: Response, provider: Provider) -> None:
    # Clear with both secure flags so either redirect URI mode can expire them.
    for key in (OAUTH_STATE_COOKIE, OAUTH_SECRETS_COOKIE):
        for secure in (True, False):
            response.delete_cookie(
                key=key,
                path=_callback_path(provider),
                secure=secure,
                httponly=True,
                samesite="lax",
            )


@router.get(
    "/providers",
    response_model=list[ProviderStatusResponse],
    summary="List providers",
    description=(
        "Every provider the app supports: whether it is configured, whether a sync can be "
        "started, whether the user is connected to it, and the user's sync status with it. "
        "A user is connected to one provider at most."
    ),
)
async def list_providers(user_id: str = Depends(require_user)):
    return [
        ProviderStatusResponse(
            provider=status.provider,
            configured=status.configured,
            can_sync=status.can_sync,
            connected=status.connected,
            sync_state=status.sync_state,
        )
        for status in await provider_statuses(user_id)
    ]


@router.get(
    "/providers/{provider}/connect",
    response_model=ConnectResponse,
    summary="Start provider OAuth (SPA)",
    responses={
        404: {"model": ErrorResponse, "description": "Provider not supported or not configured"},
        409: {"model": ErrorResponse, "description": "The user is connected to another provider"},
        502: {"model": ErrorResponse, "description": "The provider failed"},
    },
    description=(
        "Returns the provider's authorize URL for its configured redirect URI. "
        "The frontend should redirect the browser there. "
        "CSRF state is bound to an HttpOnly `oauth_state` cookie, to the "
        "signed-in Clerk user and to the provider. Values the callback needs that must not "
        "travel through the provider go into an encrypted HttpOnly `oauth_secrets` cookie."
    ),
)
async def connect(
    response: Response,
    provider: Provider,
    user_id: str = Depends(require_user),
    service: ProviderAccountService = Depends(get_provider_account_service),
):
    start: ConnectStart = await service.build_connect_url(user_id=user_id)

    _set_oauth_cookie(
        response=response,
        key=OAUTH_STATE_COOKIE,
        value=start.state,
        redirect_uri=start.redirect_uri,
        provider=provider,
    )
    if start.sealed_secrets is not None:
        _set_oauth_cookie(
            response=response,
            key=OAUTH_SECRETS_COOKIE,
            value=start.sealed_secrets,
            redirect_uri=start.redirect_uri,
            provider=provider,
        )

    return ConnectResponse(authorize_url=start.authorize_url)


@router.delete(
    "/providers/{provider}/connection",
    status_code=204,
    response_model=None,
    responses={
        404: {"model": ErrorResponse, "description": "Provider not supported or not configured"},
        502: {
            "model": ErrorResponse,
            "description": "The provider failed to revoke the authorization",
        },
    },
    summary="Disconnect a provider",
    description=(
        "Revokes the app's authorization with the provider, clears the stored tokens and "
        "the connection, and deletes the user's queued imports for it. Imported activities "
        "are kept. Returns 204 also if the user isn't connected"
    ),
)
async def disconnect(
    provider: Provider,  # noqa: ARG001 - required to bind and validate the path segment
    user_id: str = Depends(require_user),
    connection: ProviderConnectionService = Depends(get_provider_connection_service),
):
    await connection.disconnect(user_id)


@callback_router.get(
    "/providers/{provider}/callback",
    status_code=302,
    response_class=RedirectResponse,
    summary="Provider OAuth callback",
    responses={
        404: {"model": ErrorResponse, "description": "Provider not supported or not configured"}
    },
    description=(
        "Reads the provider's callback parameters (e.g. `code` and `state`), exchanges the "
        "grant for the provider's tokens (server-side secret), links them to the Clerk user "
        "bound into the OAuth state, and queues the user's imports blocked by a revoked "
        "authorization again.\n\n"
        "Always redirects to the frontend's `/oauth/callback?provider=<provider>`, with an "
        "`error` parameter when the connect failed: "
        + ", ".join(f"`{error.value}`" for error in OAuthCallbackError)
        + "."
    ),
)
async def callback(
    request: Request,
    provider: Provider,
    connection: ProviderConnectionService = Depends(get_provider_connection_service),
):
    try:
        await connection.complete(
            dict(request.query_params),
            request.cookies.get(OAUTH_STATE_COOKIE),
            request.cookies.get(OAUTH_SECRETS_COOKIE),
        )
    except ProviderAuthorizationError as exc:
        declined = request.query_params.get("error") == "access_denied"
        error = OAuthCallbackError.DECLINED if declined else OAuthCallbackError.AUTHORIZATION_FAILED
        raise OAuthCallbackFailedError(provider, error) from exc
    except DomainError as exc:
        raise OAuthCallbackFailedError(provider, _callback_error(exc)) from exc
    except Exception as exc:
        raise OAuthCallbackFailedError(provider, OAuthCallbackError.FAILED) from exc

    return _frontend_callback(provider)


class OAuthCallbackFailedError(Exception):
    """A provider callback that didn't connect the user. Raised rather than returned, so
    the request's session rolls back; ``oauth_callback_failed`` turns it into the
    redirect.
    """

    def __init__(self, provider: Provider, error: OAuthCallbackError):
        super().__init__(f"{provider} callback failed: {error}")
        self.provider = provider
        self.error = error


async def oauth_callback_failed(
    _request: Request, exc: OAuthCallbackFailedError
) -> RedirectResponse:
    cause = exc.__cause__
    if cause is None or isinstance(cause, DomainError):
        logger.warning("%s callback failed: %s (%s)", exc.provider, exc.error, type(cause).__name__)
    else:
        logger.error("%s callback failed: %s", exc.provider, exc.error, exc_info=cause)
    return _frontend_callback(exc.provider, exc.error)


def _frontend_callback(
    provider: Provider, error: OAuthCallbackError | None = None
) -> RedirectResponse:
    """A redirect to the frontend's callback page, clearing the OAuth cookies."""
    query = {"provider": provider.value}
    if error is not None:
        query["error"] = error.value
    redirect = RedirectResponse(f"{FRONTEND_URL}/oauth/callback?{urlencode(query)}", 302)
    _clear_oauth_cookies(redirect, provider)
    return redirect


def _callback_error(exc: DomainError) -> OAuthCallbackError:
    """The frontend's error code for a domain error from completing a connect."""
    if isinstance(exc, FetchError):
        return OAuthCallbackError.PROVIDER_UNAVAILABLE
    if isinstance(exc, OAuthStateMismatchError):
        return OAuthCallbackError.STATE_MISMATCH
    if isinstance(exc, AnotherProviderConnectedError):
        return OAuthCallbackError.ANOTHER_PROVIDER_CONNECTED
    if isinstance(exc, ProviderAccountTakenError):
        return OAuthCallbackError.ACCOUNT_TAKEN
    return OAuthCallbackError.FAILED
