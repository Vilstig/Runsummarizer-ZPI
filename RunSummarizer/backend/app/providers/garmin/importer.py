"""Garmin's part in importing queued activities: downloading the file a notification
links to, and building the activity from it.
"""

import base64
import binascii
import logging
from collections.abc import Callable
from datetime import datetime

import httpx

from app.core.clock import utc_now
from app.db.protocols.import_queue import Claim, QueuedItem
from app.domain.enums import Provider
from app.domain.errors import (
    ProviderActivityNotFoundError,
    ProviderAuthorizationError,
    ProviderUnavailableError,
    RateLimitedError,
)
from app.domain.models import ProviderCredentials
from app.providers.base import (
    NormalizedActivity,
    ProviderImporter,
    ResponseObserver,
    describe_error,
)
from app.providers.fit.decode import decode_fit
from app.providers.garmin.archive import fit_from_zip
from app.providers.garmin.budget import rate_limited_until
from app.providers.garmin.download import download_activity_file, is_activity_file_url
from app.providers.garmin.errors import (
    GarminFileGoneError,
    GarminFileTooLargeError,
    GarminRateLimitedError,
    GarminUnauthorizedError,
    GarminUnsupportedFileError,
)
from app.providers.garmin.normalizer import normalize_garmin_activity, normalize_garmin_streams
from app.providers.garmin.webhook import NOTIFICATION_FORMAT

logger = logging.getLogger(__name__)

ITEM_COST = 1  # Garmin calls that fetching an item takes: the file download
MAX_ATTEMPTS = 30  # attempts an item gets before ProviderUnavailableError makes it dead

PAYLOAD_FORMAT = "garmin_file_v1"  # payload["format"] of a fetched activity file
PAYLOAD_KIND = "garmin_activity_file"  # activity_raw_payloads.payload_kind

ZIP_MAGIC = b"PK\x03\x04"
FIT_MAGIC = b".FIT"  # bytes 8-11 of a FIT file


class GarminImporter(ProviderImporter):
    """``ProviderImporter`` for Garmin. Files without a running session are skipped.

    ``transport`` replaces the network, e.g. with ``httpx.MockTransport``; ``clock``
    gives the current time.
    """

    provider = Provider.GARMIN
    single_use_fetch = True
    max_attempts = MAX_ATTEMPTS

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], datetime] = utc_now,
    ):
        self._transport = transport
        self._clock = clock

    def cost(self, item: QueuedItem) -> int:  # noqa: ARG002 - every Garmin item costs the same
        return ITEM_COST

    async def fetch(
        self, claim: Claim, credentials: ProviderCredentials, on_response: ResponseObserver
    ) -> dict:
        """The activity file the claim's notification links to, downloaded with the
        user's ``credentials``: ``{"format": PAYLOAD_FORMAT, "notification": <the entry
        without its callbackURL>, "file": <base64 of the download>}``.

        No notification, a link that isn't Garmin's file endpoint, a 404, 410 or other
        4xx, an empty body or a file over the size cap raise
        ``ProviderActivityNotFoundError``; a 401, 403 or 412 ``ProviderAuthorizationError``;
        a 429 ``RateLimitedError`` until ``rate_limited_until``; a 5xx, a timeout or a
        connection error ``ProviderUnavailableError``.
        """
        notification = _notification(claim.sent_data)
        url = notification.get("callbackURL") if notification is not None else None
        if not is_activity_file_url(url):
            raise self._file_lost(claim, "the item has no link to Garmin's activity file")
        try:
            content = await download_activity_file(
                url,
                credentials.access_token,
                on_response=on_response,
                transport=self._transport,
                clock=self._clock,
            )
        except GarminRateLimitedError as exc:
            until = rate_limited_until(self._clock(), exc.retry_after)
            raise RateLimitedError(describe_error(exc), until=until) from exc
        except GarminUnauthorizedError as exc:
            raise ProviderAuthorizationError(describe_error(exc)) from exc
        except (GarminFileGoneError, GarminFileTooLargeError) as exc:
            raise self._file_lost(claim, describe_error(exc)) from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(describe_error(exc)) from exc
        return {
            "format": PAYLOAD_FORMAT,
            "notification": {
                key: value for key, value in notification.items() if key != "callbackURL"
            },
            "file": base64.b64encode(content).decode("ascii"),
        }

    def normalize(self, payload: dict) -> NormalizedActivity | None:
        """The activity of a ``fetch`` payload; None when its file has no running session.

        A ZIP download is read through ``fit_from_zip``. Any other format raises
        ``ValueError``; a file that is neither FIT nor ZIP ``GarminUnsupportedFileError``;
        a broken FIT file ``InvalidFitFileError``. The payload, file included, is kept as
        the stored payload, under ``PAYLOAD_KIND``.
        """
        payload_format = payload.get("format")
        if payload_format != PAYLOAD_FORMAT:
            raise ValueError(f"unknown Garmin payload format: {payload_format!r}")
        notification = payload["notification"]
        messages = decode_fit(fit_bytes(payload["file"]))
        activity = normalize_garmin_activity(
            notification["activityId"],
            messages,
            name=_text(notification.get("activityName")),
            device_name=_text(notification.get("deviceName")),
        )
        if activity is None:
            return None
        return NormalizedActivity(
            activity=activity,
            streams=normalize_garmin_streams(messages),
            payload_kind=PAYLOAD_KIND,
            stored_payload=payload,
        )

    def _file_lost(self, claim: Claim, reason: str) -> ProviderActivityNotFoundError:
        logger.warning(
            "garmin item %s for user %s: the activity file can't be downloaded: %s",
            claim.activity_key,
            claim.user_id,
            reason,
        )
        return ProviderActivityNotFoundError(reason)


def fit_bytes(encoded: str) -> bytes:
    """The FIT file in ``encoded``, the base64 of a download: a FIT file, or a ZIP holding
    one.

    Raises ``ValueError`` for invalid base64, ``GarminUnsupportedFileError`` for a file
    that is neither, and what ``fit_from_zip`` raises for a ZIP.
    """
    try:
        content = base64.b64decode(encoded, validate=True)
    except (binascii.Error, TypeError) as exc:
        raise ValueError("The activity file isn't valid base64") from exc
    if content.startswith(ZIP_MAGIC):
        content = fit_from_zip(content)
    if content[8:12] != FIT_MAGIC:
        raise GarminUnsupportedFileError("The activity file isn't a FIT file", files=[])
    return content


def _notification(sent_data: dict | None) -> dict | None:
    if not isinstance(sent_data, dict) or sent_data.get("format") != NOTIFICATION_FORMAT:
        return None
    notification = sent_data.get("notification")
    return notification if isinstance(notification, dict) else None


def _text(value: object) -> str | None:
    """``value`` stripped, when it is a non-blank string; else None."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
