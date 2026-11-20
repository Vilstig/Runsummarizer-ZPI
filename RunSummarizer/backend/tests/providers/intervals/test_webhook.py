"""IntervalsWebhookParser: body-secret checks, and the commands in each pushed event."""

import json

import pytest

from app.domain.errors import WebhookPayloadError, WebhookRejectedError
from app.providers.base import ActivityChanged
from app.providers.intervals.webhook import IntervalsWebhookParser
from tests.helpers import configure_intervals

PATH_SECRET = "path-secret"
WEBHOOK_SECRET = "body-secret"

parser = IntervalsWebhookParser(path_secret=PATH_SECRET, webhook_secret=WEBHOOK_SECRET)


def envelope(*events: dict, secret: str = WEBHOOK_SECRET) -> dict:
    return {"secret": secret, "events": list(events)}


def activity_event(
    event_type: str = "ACTIVITY_UPLOADED",
    *,
    athlete_id: str | int = "2049151",
    activity_id: str | int = "i55751783",
    activity_type: str | None = "Run",
) -> dict:
    activity: dict = {"id": activity_id}
    if activity_type is not None:
        activity["type"] = activity_type
    return {
        "athlete_id": athlete_id,
        "type": event_type,
        "timestamp": "2024-12-06T06:40:47.011+00:00",
        "activity": activity,
    }


def parse(payload: dict) -> list:
    return parser.parse(json.dumps(payload).encode(), {})


# ---------- path secret and subscription ----------


def test_the_path_secret_is_the_configured_one():
    assert parser.path_secret() == PATH_SECRET


def test_a_subscription_check_is_always_none():
    assert parser.verify_subscription({"anything": "goes"}) is None


# ---------- events ----------


@pytest.mark.parametrize("event_type", ["ACTIVITY_UPLOADED", "ACTIVITY_UPDATED"])
def test_an_activity_event_changes_the_activity(event_type):
    assert parse(envelope(activity_event(event_type))) == [
        ActivityChanged("2049151", "intervals_i55751783")
    ]


def test_a_missing_activity_type_is_still_queued():
    assert parse(envelope(activity_event(activity_type=None))) == [
        ActivityChanged("2049151", "intervals_i55751783")
    ]


def test_a_trail_run_is_queued():
    assert parse(envelope(activity_event(activity_type="TrailRun"))) == [
        ActivityChanged("2049151", "intervals_i55751783")
    ]


@pytest.mark.parametrize(
    "event",
    [
        activity_event("ACTIVITY_ANALYZED"),
        activity_event("ACTIVITY_DELETED"),
        activity_event(activity_type="Ride"),
        {**activity_event(), "activity": None},
        {"athlete_id": "2049151", "type": "CALENDAR_UPDATED", "timestamp": "2024-12-06T06:40:47Z"},
        {"athlete_id": "2049151", "type": "WELLNESS_UPDATED", "timestamp": "2024-12-06T06:40:47Z"},
    ],
    ids=[
        "analyzed",
        "deleted",
        "non-run",
        "no-activity",
        "calendar",
        "wellness",
    ],
)
def test_other_events_change_nothing(event):
    assert parse(envelope(event)) == []


def test_several_events_become_several_commands():
    payload = envelope(
        activity_event(athlete_id="1", activity_id="i1"),
        activity_event("ACTIVITY_ANALYZED", athlete_id="1", activity_id="i1"),
        activity_event(athlete_id="2", activity_id="i2", activity_type="TrailRun"),
    )

    assert parse(payload) == [
        ActivityChanged("1", "intervals_i1"),
        ActivityChanged("2", "intervals_i2"),
    ]


def test_numeric_ids_are_stringified():
    assert parse(envelope(activity_event(athlete_id=2049151, activity_id=55751783))) == [
        ActivityChanged("2049151", "intervals_55751783")
    ]


# ---------- rejection ----------


def test_a_wrong_body_secret_is_rejected():
    with pytest.raises(WebhookRejectedError):
        parse(envelope(activity_event(), secret="wrong-secret"))


def test_without_a_configured_webhook_secret_every_body_is_rejected():
    unconfigured = IntervalsWebhookParser(path_secret=PATH_SECRET, webhook_secret="")

    with pytest.raises(WebhookRejectedError):
        unconfigured.parse(json.dumps(envelope(activity_event(), secret="")).encode(), {})


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"[]",
        json.dumps({"secret": WEBHOOK_SECRET}).encode(),
        json.dumps({"secret": WEBHOOK_SECRET, "events": "nope"}).encode(),
    ],
    ids=["not-json", "not-an-object", "missing-events", "events-not-a-list"],
)
def test_a_body_that_is_not_an_envelope_is_rejected(body):
    with pytest.raises(WebhookPayloadError):
        parser.parse(body, {})


def test_without_overrides_the_secrets_are_read_from_the_settings_when_used(monkeypatch):
    from_settings = IntervalsWebhookParser()
    configure_intervals(
        monkeypatch,
        webhook_path_secret="settings-path",
        webhook_secret="settings-body",
    )

    assert from_settings.path_secret() == "settings-path"
    assert parse_with(from_settings, envelope(activity_event(), secret="settings-body")) == [
        ActivityChanged("2049151", "intervals_i55751783")
    ]
    with pytest.raises(WebhookRejectedError):
        parse_with(from_settings, envelope(activity_event(), secret=WEBHOOK_SECRET))


def parse_with(instance: IntervalsWebhookParser, payload: dict) -> list:
    return instance.parse(json.dumps(payload).encode(), {})
