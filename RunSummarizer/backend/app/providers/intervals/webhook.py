"""Intervals.icu's webhook requests: pushed events carrying a body secret."""

import hmac
import logging
from collections.abc import Mapping

from pydantic import BaseModel, ValidationError, field_validator

from app.config import settings
from app.domain.errors import WebhookPayloadError, WebhookRejectedError
from app.providers.base import ActivityChanged, WebhookCommand
from app.providers.intervals.activity_keys import intervals_activity_key
from app.providers.intervals.normalizer import RUN_TYPES

logger = logging.getLogger(__name__)

# Events that mean an activity was created or changed. ACTIVITY_UPDATED is handled if
# Intervals.icu sends it; ACTIVITY_ANALYZED is ignored (it follows every upload).
_ACTIVITY_CHANGED_TYPES = frozenset({"ACTIVITY_UPLOADED", "ACTIVITY_UPDATED"})


class IntervalsWebhookActivity(BaseModel):
    """The activity object Intervals.icu attaches to an activity event."""

    id: str
    type: str | None = None

    @field_validator("id", mode="before")
    @classmethod
    def _id_as_str(cls, value: object) -> object:
        return str(value) if isinstance(value, int) else value


class IntervalsWebhookEvent(BaseModel):
    """One event in a webhook POST."""

    athlete_id: str
    type: str
    timestamp: str | None = None
    activity: IntervalsWebhookActivity | None = None

    @field_validator("athlete_id", mode="before")
    @classmethod
    def _athlete_id_as_str(cls, value: object) -> object:
        return str(value) if isinstance(value, int) else value


class IntervalsWebhookEnvelope(BaseModel):
    """A webhook POST, as Intervals.icu sends it."""

    secret: str
    events: list[IntervalsWebhookEvent]


def _matches(given: str | None, expected: str) -> bool:
    if not expected or not given:
        return False
    return hmac.compare_digest(given.encode(), expected.encode())


def _command_for(event: IntervalsWebhookEvent) -> WebhookCommand | None:
    if event.type not in _ACTIVITY_CHANGED_TYPES:
        return None
    if event.activity is None:
        return None
    # Missing type: still queue; fetch skips non-runs. A known non-run is ignored here.
    if event.activity.type is not None and event.activity.type not in RUN_TYPES:
        return None
    return ActivityChanged(
        str(event.athlete_id),
        intervals_activity_key(event.activity.id),
    )


class IntervalsWebhookParser:
    """``WebhookParser`` for Intervals.icu.

    Events read: ``ACTIVITY_UPLOADED``, and ``ACTIVITY_UPDATED`` when Intervals.icu
    sends it. Other events change nothing. There is no subscription check.
    """

    def __init__(
        self,
        *,
        path_secret: str | None = None,
        webhook_secret: str | None = None,
    ):
        """``path_secret`` and ``webhook_secret`` default to the Intervals.icu
        settings', read when they are used."""
        self._path_secret = path_secret
        self._webhook_secret = webhook_secret

    def path_secret(self) -> str:
        if self._path_secret is None:
            return settings.INTERVALS.webhook_path_secret
        return self._path_secret

    def _expected_webhook_secret(self) -> str:
        if self._webhook_secret is None:
            return settings.INTERVALS.webhook_secret
        return self._webhook_secret

    def verify_subscription(self, query: Mapping[str, str]) -> dict | None:  # noqa: ARG002
        """Always ``None``: Intervals.icu sends no subscription check."""
        return None

    def parse(self, body: bytes, headers: Mapping[str, str]) -> list[WebhookCommand]:  # noqa: ARG002
        try:
            envelope = IntervalsWebhookEnvelope.model_validate_json(body)
        except ValidationError as exc:
            raise WebhookPayloadError(str(exc)) from exc
        if not _matches(envelope.secret, self._expected_webhook_secret()):
            raise WebhookRejectedError("Invalid webhook secret")
        commands: list[WebhookCommand] = []
        for event in envelope.events:
            command = _command_for(event)
            if command is None:
                logger.debug("intervals webhook: ignoring a %s event", event.type)
                continue
            commands.append(command)
        return commands
