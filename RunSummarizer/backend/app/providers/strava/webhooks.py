"""Strava push subscription (webhook) API helpers.

``transport`` replaces the network, e.g. with ``httpx.MockTransport``.
"""

from __future__ import annotations

import httpx

from app.providers.strava.oauth import STRAVA_API_BASE, STRAVA_TIMEOUT

PUSH_SUBSCRIPTIONS_URL = f"{STRAVA_API_BASE}/push_subscriptions"


def create_subscription(
    *,
    client_id: str,
    client_secret: str,
    callback_url: str,
    verify_token: str,
    transport: httpx.BaseTransport | None = None,
) -> dict:
    with httpx.Client(timeout=STRAVA_TIMEOUT, transport=transport) as client:
        resp = client.post(
            PUSH_SUBSCRIPTIONS_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "callback_url": callback_url,
                "verify_token": verify_token,
            },
        )
        resp.raise_for_status()
        return resp.json()


def list_subscriptions(
    *,
    client_id: str,
    client_secret: str,
    transport: httpx.BaseTransport | None = None,
) -> list[dict]:
    with httpx.Client(timeout=STRAVA_TIMEOUT, transport=transport) as client:
        resp = client.get(
            PUSH_SUBSCRIPTIONS_URL,
            params={"client_id": client_id, "client_secret": client_secret},
        )
        resp.raise_for_status()
        data = resp.json()
    if isinstance(data, list):
        return data
    return []


def delete_subscription(
    *,
    subscription_id: int,
    client_id: str,
    client_secret: str,
    transport: httpx.BaseTransport | None = None,
) -> None:
    with httpx.Client(timeout=STRAVA_TIMEOUT, transport=transport) as client:
        resp = client.delete(
            f"{PUSH_SUBSCRIPTIONS_URL}/{subscription_id}",
            params={"client_id": client_id, "client_secret": client_secret},
        )
        resp.raise_for_status()
