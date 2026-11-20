"""GarminImporter: fetching the file a notification links to, and normalizing FIT and ZIP
payloads built with ``fit_builder``.
"""

import base64
import logging
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.db.protocols.import_queue import Claim
from app.domain.enums import Provider, StreamType
from app.domain.errors import (
    ProviderActivityNotFoundError,
    ProviderAuthorizationError,
    ProviderUnavailableError,
    RateLimitedError,
)
from app.domain.models import ProviderCredentials
from app.providers.fit.errors import InvalidFitFileError
from app.providers.garmin.constants import MAX_FILE_BYTES
from app.providers.garmin.errors import (
    GarminInvalidResponseError,
    GarminUnsupportedFileError,
)
from app.providers.garmin.importer import (
    MAX_ATTEMPTS,
    PAYLOAD_FORMAT,
    PAYLOAD_KIND,
    GarminImporter,
)
from app.providers.garmin.webhook import NOTIFICATION_FORMAT
from tests.providers.fit.fit_builder import START, build_zip, running_fit

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
URL = "https://apis.garmin.com/wellness-api/rest/activityFile?id=901&token=t-1"
CREDENTIALS = ProviderCredentials("access-1", "refresh-1", None)
NOTIFICATION = {
    "userId": "user-7",
    "summaryId": "901",
    "fileType": "FIT",
    "callbackURL": URL,
    "activityId": 901,
    "activityName": "Morning Run",
    "activityType": "RUNNING",
    "deviceName": "Forerunner 965",
}


def claim(sent_data: dict | None) -> Claim:
    return Claim(
        user_id="clerk-user",
        provider="garmin",
        activity_key="garmin_901",
        generation=1,
        attempts=1,
        lease_token=uuid.uuid4(),
        sent_data=sent_data,
    )


def sent(notification: dict | None = None) -> dict:
    return {"format": NOTIFICATION_FORMAT, "notification": notification or NOTIFICATION}


def importer(response: httpx.Response | Exception, requests: list | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(request)
        if isinstance(response, Exception):
            raise response
        return response

    return GarminImporter(transport=httpx.MockTransport(handler), clock=lambda: NOW)


async def ignore(response, sent_at) -> None:
    return None


async def fetch(response: httpx.Response | Exception, sent_data: dict | None = None) -> dict:
    return await importer(response).fetch(
        claim(sent() if sent_data is None else sent_data), CREDENTIALS, ignore
    )


def payload(file: bytes, **notification) -> dict:
    entry = {key: value for key, value in NOTIFICATION.items() if key != "callbackURL"}
    return {
        "format": PAYLOAD_FORMAT,
        "notification": {**entry, **notification},
        "file": base64.b64encode(file).decode(),
    }


def test_garmin_items_are_single_use_and_get_a_day_of_attempts():
    assert GarminImporter.provider is Provider.GARMIN
    assert GarminImporter.single_use_fetch is True
    assert GarminImporter.max_attempts == MAX_ATTEMPTS == 30


def test_an_item_costs_one_download():
    assert GarminImporter().cost(None) == 1


# ---------- fetch ----------


async def test_the_file_is_fetched_from_the_notifications_link():
    requests = []
    fit = running_fit()

    fetched = await importer(httpx.Response(200, content=fit), requests).fetch(
        claim(sent()), CREDENTIALS, ignore
    )

    [request] = requests
    assert str(request.url) == URL
    assert request.headers["Authorization"] == "Bearer access-1"
    assert fetched["format"] == PAYLOAD_FORMAT
    assert "callbackURL" not in fetched["notification"]
    assert fetched["notification"]["deviceName"] == "Forerunner 965"
    assert base64.b64decode(fetched["file"]) == fit


@pytest.mark.parametrize(
    "sent_data",
    [
        {},
        {"format": "other", "notification": NOTIFICATION},
        {"format": NOTIFICATION_FORMAT},
        {"format": NOTIFICATION_FORMAT, "notification": "x"},
        sent({**NOTIFICATION, "callbackURL": None}),
        sent({**NOTIFICATION, "callbackURL": "https://evil.example/f?id=901"}),
    ],
    ids=["empty", "other format", "no notification", "bad notification", "no url", "other host"],
)
async def test_an_item_without_a_garmin_link_is_not_found(sent_data, caplog):
    requests = []
    imp = importer(httpx.Response(200, content=b"x"), requests)

    with caplog.at_level(logging.WARNING), pytest.raises(ProviderActivityNotFoundError):
        await imp.fetch(claim(sent_data), CREDENTIALS, ignore)

    assert requests == []
    assert "garmin_901" in caplog.text
    assert "clerk-user" in caplog.text


async def test_an_item_without_sent_data_is_not_found():
    with pytest.raises(ProviderActivityNotFoundError):
        await importer(httpx.Response(200)).fetch(claim(None), CREDENTIALS, ignore)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b""),
        httpx.Response(404),
        httpx.Response(410),
        httpx.Response(400),
    ],
    ids=["empty", "404", "410", "400"],
)
async def test_a_spent_or_missing_file_is_not_found_and_logged(response, caplog):
    with caplog.at_level(logging.WARNING), pytest.raises(ProviderActivityNotFoundError):
        await fetch(response)

    assert "garmin_901" in caplog.text
    assert "clerk-user" in caplog.text
    assert "t-1" not in caplog.text


async def test_a_file_over_the_cap_is_not_found():
    big = httpx.Response(200, headers={"Content-Length": str(MAX_FILE_BYTES + 1)}, content=b"x")

    with pytest.raises(ProviderActivityNotFoundError):
        await fetch(big)


@pytest.mark.parametrize("status", [401, 403, 412])
async def test_a_rejected_token_is_an_authorization_error(status):
    with pytest.raises(ProviderAuthorizationError):
        await fetch(httpx.Response(status))


async def test_a_429_rate_limits_until_retry_after():
    with pytest.raises(RateLimitedError) as raised:
        await fetch(httpx.Response(429, headers={"Retry-After": "90"}))

    assert raised.value.until == NOW + timedelta(seconds=90)


async def test_a_429_without_retry_after_rate_limits_for_a_minute():
    with pytest.raises(RateLimitedError) as raised:
        await fetch(httpx.Response(429))

    assert raised.value.until == NOW + timedelta(seconds=60)


@pytest.mark.parametrize(
    "failure",
    [httpx.Response(500), httpx.Response(502), httpx.ConnectError("down"), httpx.ReadTimeout("t")],
    ids=["500", "502", "connection", "timeout"],
)
async def test_a_server_error_or_network_failure_is_unavailable(failure):
    with pytest.raises(ProviderUnavailableError):
        await fetch(failure)


# ---------- normalize ----------


def test_a_fit_payload_becomes_the_activity():
    fetched = payload(running_fit())

    normalized = GarminImporter().normalize(fetched)

    activity = normalized.activity
    assert activity.key == "garmin_901"
    assert activity.source is Provider.GARMIN
    assert activity.name == "Morning Run"
    assert activity.device_name == "Forerunner 965"
    assert activity.start_time_utc == START
    assert [lap.avg_hr for lap in activity.laps] == [148, 156]
    assert normalized.streams[StreamType.HEARTRATE][0] == 140
    assert normalized.payload_kind == PAYLOAD_KIND
    assert normalized.stored_payload is fetched


def test_a_zip_payload_is_read_through_its_fit_file():
    normalized = GarminImporter().normalize(payload(build_zip({"901_ACTIVITY.fit": running_fit()})))

    assert normalized.activity.key == "garmin_901"
    assert len(normalized.activity.laps) == 2


def test_the_device_falls_back_to_the_fit_files_product_name():
    fit = running_fit(file_id={"product_name": "Forerunner 265"})

    normalized = GarminImporter().normalize(payload(fit, deviceName=None))

    assert normalized.activity.device_name == "Forerunner 265"


@pytest.mark.parametrize("device_name", [None, "", "  "])
def test_the_device_is_unknown_without_a_name_anywhere(device_name):
    normalized = GarminImporter().normalize(payload(running_fit(), deviceName=device_name))

    assert normalized.activity.device_name is None


def test_a_file_without_a_running_session_is_skipped():
    fit = running_fit(sport="cycling", sub_sport="road")

    assert GarminImporter().normalize(payload(fit)) is None


def test_a_corrupt_fit_file_fails():
    fit = bytearray(running_fit())
    fit[20] ^= 0xFF

    with pytest.raises(InvalidFitFileError):
        GarminImporter().normalize(payload(bytes(fit)))


def test_a_file_that_is_neither_fit_nor_zip_is_unsupported():
    with pytest.raises(GarminUnsupportedFileError):
        GarminImporter().normalize(payload(b"<gpx></gpx> padding padding"))


def test_a_zip_without_one_fit_file_fails():
    with pytest.raises(GarminUnsupportedFileError):
        GarminImporter().normalize(payload(build_zip({"run.gpx": b"<gpx/>"})))
    with pytest.raises(GarminInvalidResponseError):
        GarminImporter().normalize(payload(build_zip({"a.fit": b"1", "b.fit": b"2"})))


def test_a_file_that_isnt_base64_fails():
    with pytest.raises(ValueError, match="base64"):
        GarminImporter().normalize({**payload(b""), "file": "not base64!"})


@pytest.mark.parametrize("payload_format", [None, "garmin_file_v2", "strava_detail_v1"])
def test_an_unknown_format_fails(payload_format):
    with pytest.raises(ValueError, match="format"):
        GarminImporter().normalize({**payload(running_fit()), "format": payload_format})
