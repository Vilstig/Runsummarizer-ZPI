"""GarminWebhookParser: each kind of notification entry, mixed batches, the client-ID
header and the download link check.
"""

import json
import logging

import pytest

from app.domain.errors import WebhookPayloadError, WebhookRejectedError
from app.providers.base import AccountRevoked, ActivityChanged
from app.providers.garmin.webhook import NOTIFICATION_FORMAT, GarminWebhookParser

CLIENT_ID = "client-id"
CALLBACK_URL = "https://apis.garmin.com/wellness-api/rest/activityFile?id=901&token=secret-token"
HEADERS = {"garmin-client-id": CLIENT_ID}


def file_entry(**fields) -> dict:
    return {
        "userId": "user-7",
        "summaryId": "901",
        "fileType": "FIT",
        "callbackURL": CALLBACK_URL,
        "startTimeInSeconds": 1_763_190_000,
        "activityId": 901,
        "activityName": "Morning Run",
        "activityType": "RUNNING",
        "deviceName": "Forerunner 965",
        **fields,
    }


def parse(body: dict | list | bytes, headers: dict | None = None) -> list:
    parser = GarminWebhookParser(path_secret="path-secret", client_id=CLIENT_ID)
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    return parser.parse(raw, HEADERS if headers is None else headers)


def ids(commands: list) -> list:
    """``commands`` with their ``sent_data`` dropped, to compare by ids."""
    return [
        ActivityChanged(c.provider_user_id, c.activity_key) if isinstance(c, ActivityChanged) else c
        for c in commands
    ]


def test_the_path_secret_is_the_configured_one():
    assert GarminWebhookParser(path_secret="s-1", client_id=CLIENT_ID).path_secret() == "s-1"


def test_garmin_sends_no_subscription_checks():
    parser = GarminWebhookParser(path_secret="s", client_id=CLIENT_ID)

    assert parser.verify_subscription({"hub.challenge": "c"}) is None


# ---------- activityFiles ----------


def test_a_running_fit_file_queues_the_activity_with_the_entry_as_sent():
    entry = file_entry()

    [command] = parse({"activityFiles": [entry]})

    assert ids([command]) == [ActivityChanged("user-7", "garmin_901")]
    assert command.sent_data == {"format": NOTIFICATION_FORMAT, "notification": entry}


@pytest.mark.parametrize(
    "activity_type",
    [
        "RUNNING",
        "INDOOR_RUNNING",
        "OBSTACLE_RUN",
        "STREET_RUNNING",
        "TRACK_RUNNING",
        "TRAIL_RUNNING",
        "TREADMILL_RUNNING",
        "ULTRA_RUN",
        "VIRTUAL_RUN",
    ],
)
def test_every_running_type_is_queued(activity_type):
    assert ids(parse({"activityFiles": [file_entry(activityType=activity_type)]})) == [
        ActivityChanged("user-7", "garmin_901")
    ]


def test_an_untyped_file_is_queued_for_the_fit_file_to_decide():
    entry = file_entry()
    del entry["activityType"]

    assert ids(parse({"activityFiles": [entry]})) == [ActivityChanged("user-7", "garmin_901")]


def test_an_activity_id_sent_as_text_is_read():
    assert ids(parse({"activityFiles": [file_entry(activityId="901")]})) == [
        ActivityChanged("user-7", "garmin_901")
    ]


@pytest.mark.parametrize("file_type", ["TCX", "GPX", "fit", None])
def test_a_file_that_isnt_fit_is_not_queued(file_type):
    assert parse({"activityFiles": [file_entry(fileType=file_type)]}) == []


@pytest.mark.parametrize("activity_type", ["CYCLING", "LAP_SWIMMING", "MULTI_SPORT", "WALKING"])
def test_a_non_running_activity_is_not_queued(activity_type):
    assert parse({"activityFiles": [file_entry(activityType=activity_type)]}) == []


@pytest.mark.parametrize(
    "fields",
    [
        {"userId": None},
        {"userId": ""},
        {"activityId": None},
        {"activityId": True},
        {"activityId": "abc"},
        {"activityId": -1},
        {"callbackURL": None},
    ],
    ids=[
        "no user",
        "blank user",
        "no activity",
        "bool activity",
        "text activity",
        "negative",
        "no url",
    ],
)
def test_an_entry_without_its_ids_or_link_is_skipped(fields, caplog):
    entry = {key: value for key, value in file_entry(**fields).items() if value is not None}

    with caplog.at_level(logging.WARNING):
        assert parse({"activityFiles": [entry]}) == []

    assert "skipped" in caplog.text


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/wellness-api/rest/activityFile?id=901",
        "http://apis.garmin.com/wellness-api/rest/activityFile?id=901",
        "https://apis.garmin.com:8443/wellness-api/rest/activityFile?id=901",
        "https://apis.garmin.com/wellness-api/rest/activityDetails?id=901",
        "https://apis.garmin.com.evil.example/wellness-api/rest/activityFile?id=901",
        "https://user:pass@apis.garmin.com/wellness-api/rest/activityFile?id=901",
        "not a url",
    ],
)
def test_a_link_that_isnt_garmins_file_endpoint_is_skipped(url):
    assert parse({"activityFiles": [file_entry(callbackURL=url)]}) == []


def test_a_skipped_entry_is_logged_without_its_download_token(caplog):
    with caplog.at_level(logging.DEBUG):
        parse({"activityFiles": [file_entry(fileType="GPX"), file_entry(activityId=None)]})

    assert "secret-token" not in caplog.text


# ---------- deregistrations and permission changes ----------


def test_a_deregistration_revokes_the_account():
    assert parse({"deregistrations": [{"userId": "user-7"}]}) == [AccountRevoked("user-7")]


def test_a_permission_change_without_activity_export_revokes_the_account():
    entry = {"userId": "user-7", "permissions": ["WORKOUT_IMPORT"], "changeTimeInSeconds": 1}

    assert parse({"userPermissionsChange": [entry]}) == [AccountRevoked("user-7")]


def test_a_permission_change_keeping_activity_export_changes_nothing():
    entry = {"userId": "user-7", "permissions": ["ACTIVITY_EXPORT", "WORKOUT_IMPORT"]}

    assert parse({"userPermissionsChange": [entry]}) == []


@pytest.mark.parametrize(
    ("key", "entry"),
    [
        ("deregistrations", {}),
        ("deregistrations", "user-7"),
        ("userPermissionsChange", {"userId": "user-7"}),
        ("userPermissionsChange", {"permissions": []}),
    ],
)
def test_an_unreadable_revocation_entry_is_skipped(key, entry):
    assert parse({key: [entry]}) == []


# ---------- the notification ----------


def test_other_keys_change_nothing():
    assert parse({"activities": [{"userId": "user-7"}], "dailies": "x"}) == []


def test_one_bad_entry_doesnt_fail_a_mixed_batch():
    body = {
        "activityFiles": [
            file_entry(activityId=1),
            "garbage",
            file_entry(activityId=2, callbackURL="https://evil.example/x"),
            file_entry(activityId=3, activityType="CYCLING"),
            file_entry(activityId=4, userId="user-8"),
        ],
        "deregistrations": [{"userId": "user-9"}, {}],
        "userPermissionsChange": [{"userId": "user-10", "permissions": []}],
        "activityDetails": [{"userId": "user-7"}],
    }

    assert ids(parse(body)) == [
        ActivityChanged("user-7", "garmin_1"),
        ActivityChanged("user-8", "garmin_4"),
        AccountRevoked("user-9"),
        AccountRevoked("user-10"),
    ]


def test_a_key_that_isnt_a_list_is_skipped():
    assert parse({"activityFiles": {"userId": "user-7"}, "deregistrations": [{"userId": "u"}]}) == [
        AccountRevoked("u")
    ]


@pytest.mark.parametrize("body", [b"not json", b"[]", b'"text"', b""])
def test_a_body_that_isnt_a_json_object_is_a_payload_error(body):
    with pytest.raises(WebhookPayloadError):
        parse(body)


def test_another_apps_client_id_is_rejected():
    with pytest.raises(WebhookRejectedError):
        parse({"deregistrations": [{"userId": "user-7"}]}, {"garmin-client-id": "other-app"})


def test_the_client_id_header_is_matched_whatever_its_case():
    body = {"deregistrations": [{"userId": "user-7"}]}

    assert parse(body, {"Garmin-Client-Id": CLIENT_ID}) == [AccountRevoked("user-7")]
    with pytest.raises(WebhookRejectedError):
        parse(body, {"Garmin-Client-Id": "other-app"})


def test_a_notification_without_the_client_id_header_is_rejected():
    with pytest.raises(WebhookRejectedError):
        parse({"deregistrations": [{"userId": "user-7"}]}, {})


def test_a_client_id_header_is_rejected_while_none_is_configured():
    parser = GarminWebhookParser(path_secret="s", client_id="")

    with pytest.raises(WebhookRejectedError):
        parser.parse(b"{}", {"garmin-client-id": ""})


def test_the_notification_shape_is_logged(caplog):
    with caplog.at_level(logging.INFO):
        parse({"activityFiles": [file_entry()], "deregistrations": []})

    assert "activityFiles" in caplog.text
    assert "garmin-client-id" in caplog.text
    assert "secret-token" not in caplog.text
