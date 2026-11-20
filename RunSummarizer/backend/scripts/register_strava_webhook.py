"""Register (or replace) the Strava push webhook subscription.

Requires in .env:
  STRAVA_CLIENT_ID
  STRAVA_CLIENT_SECRET
  STRAVA_WEBHOOK_VERIFY_TOKEN
  STRAVA_WEBHOOK_PATH_SECRET
  STRAVA_WEBHOOK_CALLBACK_URL  (public HTTPS URL ending with /api/webhooks/strava/<PATH_SECRET>)

Local development: expose the API with a tunnel, set STRAVA_WEBHOOK_CALLBACK_URL
to the HTTPS forwarding URL + /api/webhooks/strava/<PATH_SECRET>, start uvicorn,
then run this script:

  python -m scripts.register_strava_webhook

Tunnel options:
  hookdeck-cli: hookdeck listen 8000 strava

Use the Hookdeck CLI, not a Hookdeck dashboard Source URL: a dashboard Source
answers Strava's validation GET with its own static response, not this app's
real {"hub.challenge": ...} body, so the subscription handshake fails. The CLI
tunnels like ngrok and relays this app's actual response back to Strava.
"""

from __future__ import annotations

import sys

import httpx

from app.config import settings
from app.core.logging import redact_callback_url
from app.providers.strava.webhooks import (
    create_subscription,
    delete_subscription,
    list_subscriptions,
)


def main() -> int:
    strava = settings.STRAVA
    if not strava.is_configured():
        print("Missing STRAVA_CLIENT_ID / STRAVA_CLIENT_SECRET", file=sys.stderr)
        return 1
    if not strava.webhook_verify_token:
        print("Missing STRAVA_WEBHOOK_VERIFY_TOKEN", file=sys.stderr)
        return 1
    if not strava.webhook_path_secret:
        print("Missing STRAVA_WEBHOOK_PATH_SECRET", file=sys.stderr)
        return 1
    if not strava.webhook_callback_url:
        print("Missing STRAVA_WEBHOOK_CALLBACK_URL", file=sys.stderr)
        return 1
    if not strava.webhook_callback_url.lower().startswith("https://"):
        print(
            "STRAVA_WEBHOOK_CALLBACK_URL must be HTTPS (use ngrok for local dev).",
            file=sys.stderr,
        )
        return 1
    expected_suffix = f"/api/webhooks/strava/{strava.webhook_path_secret}"
    if not strava.webhook_callback_url.rstrip("/").endswith(expected_suffix):
        print(
            "STRAVA_WEBHOOK_CALLBACK_URL must end with "
            f"{expected_suffix} (path secret, not ?token= query).",
            file=sys.stderr,
        )
        return 1

    try:
        existing = list_subscriptions(
            client_id=strava.client_id,
            client_secret=strava.client_secret,
        )
    except httpx.HTTPStatusError as exc:
        print(f"Failed to list subscriptions: {exc}", file=sys.stderr)
        print(exc.response.text, file=sys.stderr)
        return 1

    for sub in existing:
        sub_id = sub.get("id")
        print(
            f"Deleting existing subscription id={sub_id} "
            f"callback={redact_callback_url(str(sub.get('callback_url') or ''))}"
        )
        try:
            delete_subscription(
                subscription_id=int(sub_id),
                client_id=strava.client_id,
                client_secret=strava.client_secret,
            )
        except httpx.HTTPStatusError as exc:
            print(f"Failed to delete subscription {sub_id}: {exc}", file=sys.stderr)
            print(exc.response.text, file=sys.stderr)
            return 1

    print(f"Creating subscription callback_url={redact_callback_url(strava.webhook_callback_url)}")
    try:
        created = create_subscription(
            client_id=strava.client_id,
            client_secret=strava.client_secret,
            callback_url=strava.webhook_callback_url,
            verify_token=strava.webhook_verify_token,
        )
    except httpx.HTTPStatusError as exc:
        print(f"Failed to create subscription: {exc}", file=sys.stderr)
        print(exc.response.text, file=sys.stderr)
        print(
            "Ensure the API and ngrok are running, then retry. "
            'GET challenge must return {"hub.challenge": ...} within 2s.',
            file=sys.stderr,
        )
        return 1

    print(f"Subscription created: {created}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
