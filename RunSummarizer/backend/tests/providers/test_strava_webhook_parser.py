"""StravaWebhookParser: subscription checks, and the commands in each pushed event."""

import json

import pytest

from app.domain.errors import WebhookPayloadError, WebhookRejectedError
from app.providers.base import AccountRevoked, ActivityChanged
from app.providers.strava.webhook import StravaWebhookParser
from tests.helpers import configure_strava

PATH_SECRET = "path-secret"
VERIFY_TOKEN = "verify-token"
CHALLENGE = "challenge-from-strava"

parser = StravaWebhookParser(path_secret=PATH_SECRET, verify_token=VERIFY_TOKEN)


def activity_event(aspect_type: str = "create") -> dict:
    return {
        "object_type": "activity",
        "object_id": 7,
        "aspect_type": aspect_type,
        "owner_id": 101,
        "subscription_id": 1,
        "event_time": 1_791_700_000,  # Unix timestamp
        "updates": {},
    }


def deauthorization() -> dict:
    return {
        "object_type": "athlete",
        "object_id": 101,
        "aspect_type": "update",
        "owner_id": 101,
        "subscription_id": 1,
        "event_time": 1_791_700_000,
        "updates": {"authorized": "false"},
    }


def parse(event: dict) -> list:
    return parser.parse(json.dumps(event).encode(), {})


def subscription_check(**overrides: str | None) -> dict[str, str]:
    """A subscription check's query; an override of None leaves the parameter out."""
    query = {"hub.mode": "subscribe", "hub.challenge": CHALLENGE, "hub.verify_token": VERIFY_TOKEN}
    query.update(overrides)
    return {key: value for key, value in query.items() if value is not None}


# ---------- path secret and subscription checks ----------


def test_the_path_secret_is_the_configured_one():
    assert parser.path_secret() == PATH_SECRET


def test_a_subscription_check_gets_the_challenge_back():
    assert parser.verify_subscription(subscription_check()) == {"hub.challenge": CHALLENGE}


@pytest.mark.parametrize(
    "query",
    [
        subscription_check(**{"hub.mode": "unsubscribe"}),
        subscription_check(**{"hub.challenge": None}),
    ],
    ids=["not-subscribe", "no-challenge"],
)
def test_a_query_that_is_not_a_subscription_check_is_none(query):
    assert parser.verify_subscription(query) is None


@pytest.mark.parametrize("token", ["wrong-token", None, "zażółć"])
def test_a_subscription_check_with_another_verify_token_is_rejected(token):
    with pytest.raises(WebhookRejectedError):
        parser.verify_subscription(subscription_check(**{"hub.verify_token": token}))


def test_without_a_configured_verify_token_every_subscription_check_is_rejected():
    unconfigured = StravaWebhookParser(path_secret=PATH_SECRET, verify_token="")

    with pytest.raises(WebhookRejectedError):
        unconfigured.verify_subscription(subscription_check(**{"hub.verify_token": ""}))


# ---------- events ----------


@pytest.mark.parametrize("aspect_type", ["create", "update"])
def test_an_activity_event_changes_the_activity(aspect_type):
    assert parse(activity_event(aspect_type)) == [ActivityChanged("101", "strava_7")]


def test_a_deauthorization_revokes_the_account():
    assert parse(deauthorization()) == [AccountRevoked("101")]


@pytest.mark.parametrize(
    "event",
    [
        activity_event("delete"),
        {**deauthorization(), "updates": {}},
        {**deauthorization(), "updates": None},
        {**activity_event(), "object_type": "route"},
    ],
    ids=["activity-delete", "athlete-update", "athlete-update-without-updates", "other-object"],
)
def test_other_events_change_nothing(event):
    assert parse(event) == []


@pytest.mark.parametrize(
    "body",
    [b"not json", b"[]", json.dumps({"object_type": "activity"}).encode()],
    ids=["not-json", "not-an-object", "missing-fields"],
)
def test_a_body_that_is_not_an_event_is_rejected(body):
    with pytest.raises(WebhookPayloadError):
        parser.parse(body, {})


def test_without_overrides_the_secrets_are_read_from_the_settings_when_used(monkeypatch):
    from_settings = StravaWebhookParser()
    configure_strava(
        monkeypatch, webhook_path_secret="settings-secret", webhook_verify_token="settings-token"
    )
    check = {"hub.mode": "subscribe", "hub.challenge": CHALLENGE}

    assert from_settings.path_secret() == "settings-secret"
    assert from_settings.verify_subscription({**check, "hub.verify_token": "settings-token"}) == {
        "hub.challenge": CHALLENGE
    }
    with pytest.raises(WebhookRejectedError):
        from_settings.verify_subscription({**check, "hub.verify_token": VERIFY_TOKEN})
