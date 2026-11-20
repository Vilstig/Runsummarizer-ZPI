"""GET and POST /webhooks/{provider}/{token}: subscription checks and pushed events, for
every provider whose definition has a ``webhook`` parser.
"""

import hmac

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from fastapi.responses import JSONResponse

from app.api.schemas.errors import ErrorResponse
from app.domain.enums import Provider
from app.domain.errors import ProviderNotSupportedError
from app.providers.base import ProviderDefinition
from app.providers.registry import PROVIDERS
from app.services.webhook_ingest import ingest_webhook

router = APIRouter()


def _webhook(provider: str = Path(...), token: str = Path(...)) -> ProviderDefinition:
    """The definition of a provider with a webhook parser, once the path secret is checked.

    404 for an unknown provider or one without webhooks; 403 for a wrong path secret.
    """
    try:
        definition = PROVIDERS.get(Provider(provider))
    except ValueError:
        definition = None
    if definition is None or definition.webhook is None:
        raise ProviderNotSupportedError("Unknown webhook")
    expected = definition.webhook.path_secret()
    if not expected or not hmac.compare_digest(token.encode(), expected.encode()):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid webhook token")
    return definition


@router.get(
    "/{provider}/{token}",
    responses={
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
async def provider_webhook_validate(
    request: Request, definition: ProviderDefinition = Depends(_webhook)
):
    """A provider's subscription check: 400 when the query isn't one, 403 when the
    provider didn't send it.
    """
    response = definition.webhook.verify_subscription(request.query_params)
    if response is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid subscription validation request",
        )
    return JSONResponse(content=response)


@router.post(
    "/{provider}/{token}",
    responses={
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"description": "The event wasn't handled"},
    },
)
async def provider_webhook_event(
    request: Request, definition: ProviderDefinition = Depends(_webhook)
):
    """Apply a provider's pushed event, then acknowledge it: 422 for a body that isn't
    an event.
    """
    commands = definition.webhook.parse(await request.body(), request.headers)
    await ingest_webhook(definition.provider, commands)
    return {"ok": True}
