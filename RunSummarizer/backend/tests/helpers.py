"""Request builders, Clerk stand-ins, rate-limit resets, settings overrides and the
classifier stand-in shared by the tests."""

from dataclasses import replace

from clerk_backend_api.security.types import (
    AuthStatus,
    RequestState,
    TokenVerificationErrorReason,
)
from starlette.requests import Request

from app.config import settings
from app.domain.enums import LapType
from app.domain.models import Activity
from app.services import activity_pipeline


def make_request(
    *,
    path: str = "/",
    headers: list[tuple[bytes, bytes]] | None = None,
    client_host: str = "127.0.0.1",
) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": headers or [],
        "client": (client_host, 12345),
        "server": ("testserver", 80),
        "scheme": "http",
        "query_string": b"",
        "root_path": "",
    }
    return Request(scope)


class EmptyActivityService:
    """Activity service stand-in whose list is empty."""

    async def list_activities(self, **_kwargs) -> list:
        return []


def install_fake_clerk(monkeypatch, users: dict[str, str] | None = None) -> None:
    """Verify bearer tokens locally.

    ``users`` maps a bearer token to the Clerk user id it signs in. Any other
    token, including a missing one, is signed out.
    """
    known = dict(users or {})

    def authenticate(request: Request, _options: object) -> RequestState:
        token = _bearer_token(request)
        user_id = known.get(token) if token else None
        if user_id is None:
            return RequestState(
                status=AuthStatus.SIGNED_OUT,
                reason=TokenVerificationErrorReason.TOKEN_INVALID,
            )
        return RequestState(
            status=AuthStatus.SIGNED_IN,
            token=token,
            payload={"sub": user_id},
        )

    monkeypatch.setattr("app.core.clerk_auth.authenticate_request", authenticate)


def _bearer_token(request: Request) -> str | None:
    authorization = request.headers.get("Authorization")
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token


def reset_rate_limit_buckets(monkeypatch) -> None:
    """Give the rate limiter full buckets for the rest of the test."""
    from app import ratelimiter

    auth_store, public_store = ratelimiter._create_stores()
    monkeypatch.setattr(ratelimiter, "_auth_store", auth_store)
    monkeypatch.setattr(ratelimiter, "_public_store", public_store)


def configure_strava(monkeypatch, **fields: str) -> None:
    """Replace ``fields`` of the Strava settings for the rest of the test, e.g.
    ``client_id="client-id"``.
    """
    monkeypatch.setattr(settings, "STRAVA", replace(settings.STRAVA, **fields))


def configure_garmin(monkeypatch, **fields: str) -> None:
    """Replace ``fields`` of the Garmin settings for the rest of the test, e.g.
    ``client_id="client-id"``.
    """
    monkeypatch.setattr(settings, "GARMIN", replace(settings.GARMIN, **fields))


def unconfigure_garmin(monkeypatch) -> None:
    """Leave Garmin without its client ID and secret for the rest of the test, whatever
    the developer's ``.env`` holds."""
    configure_garmin(monkeypatch, client_id="", client_secret="")


def configure_intervals(monkeypatch, **fields: str) -> None:
    """Replace ``fields`` of the Intervals.icu settings for the rest of the test, e.g.
    ``client_id="client-id"``.
    """
    monkeypatch.setattr(settings, "INTERVALS", replace(settings.INTERVALS, **fields))


def stub_classifier(monkeypatch) -> None:
    """Stand in for the ML model, which is not in the repository: every lap is a run."""

    def classify(activity: Activity) -> Activity:
        return replace(activity, laps=[replace(lap, type=LapType.RUN) for lap in activity.laps])

    monkeypatch.setattr(activity_pipeline, "classify_laps", classify)
