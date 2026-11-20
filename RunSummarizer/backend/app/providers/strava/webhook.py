"""Strava's push subscription requests: subscription checks and pushed events."""

import hmac
import logging
from collections.abc import Mapping

from pydantic import BaseModel, ValidationError

from app.config import settings
from app.domain.errors import WebhookPayloadError, WebhookRejectedError
from app.providers.base import AccountRevoked, ActivityChanged, WebhookCommand
from app.providers.strava.activity_keys import strava_activity_key

logger = logging.getLogger(__name__)


class StravaWebhookEvent(BaseModel):
    """A pushed event, as Strava sends it."""

    object_type: str  # 'activity' | 'athlete'
    object_id: int
    aspect_type: str  # 'create' | 'update' | 'delete'
    owner_id: int  # athlete id
    subscription_id: int | None = None
    event_time: int | None = None  # Unix timestamp
    updates: dict | None = None


def _matches(given: str | None, expected: str) -> bool:
    if not expected or not given:
        return False
    return hmac.compare_digest(given.encode(), expected.encode())


class StravaWebhookParser:
    """``WebhookParser`` for Strava.

    Events read: an activity ``create`` or ``update`` (which carries the activity id
    only), and an athlete ``update`` with ``{"authorized": "false"}``, sent when the
    athlete revokes the app's access. Other events change nothing.
    """

    def __init__(
        self,
        *,
        path_secret: str | None = None,
        verify_token: str | None = None,
    ):
        """``path_secret`` and ``verify_token`` default to the Strava settings', read
        when they are used."""
        self._path_secret = path_secret
        self._verify_token = verify_token

    def path_secret(self) -> str:
        if self._path_secret is None:
            return settings.STRAVA.webhook_path_secret
        return self._path_secret

    def _expected_verify_token(self) -> str:
        if self._verify_token is None:
            return settings.STRAVA.webhook_verify_token
        return self._verify_token

    def verify_subscription(self, query: Mapping[str, str]) -> dict | None:
        """``{"hub.challenge": ...}`` for a ``hub.mode=subscribe`` check carrying a
        challenge and the configured ``hub.verify_token``.
        """
        challenge = query.get("hub.challenge")
        if query.get("hub.mode") != "subscribe" or not challenge:
            return None
        if not _matches(query.get("hub.verify_token"), self._expected_verify_token()):
            raise WebhookRejectedError("Invalid verify token")
        return {"hub.challenge": challenge}

    def parse(
        self,
        body: bytes,
        headers: Mapping[str, str],  # noqa: ARG002 - Strava doesn't sign its events
    ) -> list[WebhookCommand]:
        try:
            event = StravaWebhookEvent.model_validate_json(body)
        except ValidationError as exc:
            raise WebhookPayloadError(str(exc)) from exc
        athlete_id = str(event.owner_id)
        match event:
            case StravaWebhookEvent(object_type="activity", aspect_type="create" | "update"):
                return [ActivityChanged(athlete_id, strava_activity_key(event.object_id))]
            case StravaWebhookEvent(
                object_type="athlete", aspect_type="update", updates={"authorized": "false"}
            ):
                return [AccountRevoked(athlete_id)]
        logger.debug("strava webhook: ignoring a %s %s event", event.object_type, event.aspect_type)
        return []
