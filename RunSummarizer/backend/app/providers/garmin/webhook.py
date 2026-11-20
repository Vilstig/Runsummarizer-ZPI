"""Garmin's push notifications: activity files, deregistrations and permission changes."""

import hmac
import json
import logging
from collections.abc import Mapping

from app.config import settings
from app.domain.errors import WebhookPayloadError, WebhookRejectedError
from app.providers.base import AccountRevoked, ActivityChanged, WebhookCommand
from app.providers.garmin.activity_keys import garmin_activity_key
from app.providers.garmin.constants import (
    ACTIVITY_EXPORT_PERMISSION,
    ACTIVITY_FILES,
    CLIENT_ID_HEADER,
    DEREGISTRATIONS,
    RUNNING_ACTIVITY_TYPES,
    USER_PERMISSIONS_CHANGE,
)
from app.providers.garmin.download import is_activity_file_url

logger = logging.getLogger(__name__)

# sent_data["format"] of an activity file notification entry
NOTIFICATION_FORMAT = "garmin_file_notification_v1"


class InvalidEntryError(ValueError):
    """A notification entry the app can't act on."""


class GarminWebhookParser:
    """``WebhookParser`` for Garmin.

    Read: ``activityFiles`` entries of FIT files of runs (or of no activity type), each
    queued with the entry as Garmin sent it in ``sent_data``; ``deregistrations``; and
    ``userPermissionsChange`` entries without ``ACTIVITY_EXPORT``, both as revocations.
    Other entries and keys change nothing. An entry that can't be read is logged and
    skipped, never failing the rest of the notification.
    """

    def __init__(self, *, path_secret: str | None = None, client_id: str | None = None):
        """``path_secret`` and ``client_id`` default to the Garmin settings', read when
        they are used."""
        self._path_secret = path_secret
        self._client_id = client_id

    def path_secret(self) -> str:
        if self._path_secret is None:
            return settings.GARMIN.webhook_path_secret
        return self._path_secret

    def _expected_client_id(self) -> str:
        if self._client_id is None:
            return settings.GARMIN.client_id
        return self._client_id

    def verify_subscription(self, query: Mapping[str, str]) -> dict | None:  # noqa: ARG002
        """Always None: Garmin sends no subscription checks."""
        return None

    def parse(self, body: bytes, headers: Mapping[str, str]) -> list[WebhookCommand]:
        """The commands of a notification.

        A missing ``garmin-client-id`` header, or one that isn't the app's client ID,
        raises ``WebhookRejectedError``. A body that isn't a JSON object raises
        ``WebhookPayloadError``.
        """
        lowered = {name.lower(): value for name, value in headers.items()}
        given = lowered.get(CLIENT_ID_HEADER)
        if given is None:
            raise WebhookRejectedError("No Garmin client ID")
        if not _matches(given, self._expected_client_id()):
            raise WebhookRejectedError("Invalid Garmin client ID")
        try:
            data = json.loads(body)
        except ValueError as exc:
            raise WebhookPayloadError("The notification isn't JSON") from exc
        if not isinstance(data, dict):
            raise WebhookPayloadError("The notification isn't a JSON object")
        logger.info(
            "garmin webhook: headers %s, entries %s",
            sorted(lowered),
            {key: len(value) if isinstance(value, list) else None for key, value in data.items()},
        )

        commands: list[WebhookCommand] = []
        for key, entries in data.items():
            read = _READERS.get(key)
            if read is None:
                continue
            if not isinstance(entries, list):
                logger.warning("garmin webhook: %s isn't a list; skipped", key)
                continue
            for entry in entries:
                try:
                    command = read(entry)
                except InvalidEntryError as exc:
                    logger.warning("garmin webhook: a %s entry skipped: %s", key, exc)
                    continue
                if command is not None:
                    commands.append(command)
        return commands


def _matches(given: str, expected: str) -> bool:
    if not expected:
        return False
    return hmac.compare_digest(given.encode(), expected.encode())


def _user_id(entry: object) -> str:
    """The entry's ``userId``. Raises ``InvalidEntryError`` when it has none."""
    if not isinstance(entry, dict):
        raise InvalidEntryError("not a JSON object")
    user_id = entry.get("userId")
    if not isinstance(user_id, str) or not user_id:
        raise InvalidEntryError("no userId")
    return user_id


def _activity_id(entry: dict) -> int:
    activity_id = entry.get("activityId")
    if isinstance(activity_id, bool):
        raise InvalidEntryError("no activityId")
    if isinstance(activity_id, int) and activity_id > 0:
        return activity_id
    if isinstance(activity_id, str) and activity_id.isdecimal():
        return int(activity_id)
    raise InvalidEntryError("no activityId")


def _activity_file(entry: object) -> ActivityChanged | None:
    """An activity file to import; None for a file the app doesn't import."""
    user_id = _user_id(entry)
    activity_id = _activity_id(entry)
    if not is_activity_file_url(entry.get("callbackURL")):
        raise InvalidEntryError(f"activity {activity_id}: no link to Garmin's file endpoint")
    file_type = entry.get("fileType")
    if file_type != "FIT":
        logger.info(
            "garmin webhook: activity %s is a %s file; not imported", activity_id, file_type
        )
        return None
    activity_type = entry.get("activityType")
    if activity_type is not None and activity_type not in RUNNING_ACTIVITY_TYPES:
        logger.info("garmin webhook: activity %s is a %s; not imported", activity_id, activity_type)
        return None
    return ActivityChanged(
        user_id,
        garmin_activity_key(activity_id),
        sent_data={"format": NOTIFICATION_FORMAT, "notification": entry},
    )


def _deregistration(entry: object) -> AccountRevoked:
    return AccountRevoked(_user_id(entry))


def _permissions_change(entry: object) -> AccountRevoked | None:
    """A revocation when the user no longer grants ``ACTIVITY_EXPORT``."""
    user_id = _user_id(entry)
    permissions = entry.get("permissions")
    if not isinstance(permissions, list):
        raise InvalidEntryError("no permissions list")
    if ACTIVITY_EXPORT_PERMISSION in permissions:
        return None
    return AccountRevoked(user_id)


_READERS = {
    ACTIVITY_FILES: _activity_file,
    DEREGISTRATIONS: _deregistration,
    USER_PERMISSIONS_CHANGE: _permissions_change,
}
