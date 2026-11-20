import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from svix.webhooks import Webhook, WebhookVerificationError

from app.api.deps import get_account_deletion_service, get_user_service
from app.config.settings import CLERK_WEBHOOK_SECRET
from app.domain.errors import FetchError, WebhookPayloadError, WebhookRejectedError
from app.services.accounts.deletion import AccountDeletionService
from app.services.user_service import UserService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/clerk",
    responses={500: {"description": "The provider authorization couldn't be revoked yet"}},
)
async def clerk_webhook(
    request: Request,
    service: UserService = Depends(get_user_service),
    deletion: AccountDeletionService = Depends(get_account_deletion_service),
):
    """Apply a Clerk user event. ``user.deleted`` revokes the user's provider
    authorization, then deletes the user; a provider that fails answers 500, so Clerk
    delivers the event again later.
    """
    body = await request.body()
    headers = dict(request.headers)

    try:
        Webhook(CLERK_WEBHOOK_SECRET).verify(body, headers)
    except WebhookVerificationError as exc:
        raise WebhookRejectedError("invalid signature") from exc

    try:
        event = json.loads(body)
        event_type = event["type"]
        user_id = event["data"]["id"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise WebhookPayloadError("Invalid webhook event") from exc

    if event_type == "user.created":
        logger.info("clerk webhook: user %s created", user_id)
        await service.ensure_user_exists(user_id)
    elif event_type == "user.deleted":
        try:
            await deletion.delete(user_id)
        except FetchError as exc:
            logger.warning(
                "clerk webhook: user %s not deleted: revoking their provider authorization failed",
                user_id,
                exc_info=exc,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="The provider authorization couldn't be revoked. Try again later.",
            ) from exc
        logger.info("clerk webhook: user %s deleted", user_id)
    else:
        logger.debug("clerk webhook: ignoring a %s event", event_type)

    return {"ok": True}
