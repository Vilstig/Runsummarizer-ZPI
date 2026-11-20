"""Clerk session-token verification, shared by the rate limiter and ``require_user``."""

from clerk_backend_api import AuthenticateRequestOptions, authenticate_request
from clerk_backend_api.security.types import RequestState
from starlette.requests import HTTPConnection

from app.config.settings import CLERK_AUTHORIZED_PARTIES, CLERK_JWT_KEY, CLERK_SECRET_KEY

# request.state key holding the RequestState for the current request
_STATE_KEY = "clerk_auth"


def authenticate_clerk_request(request: HTTPConnection) -> RequestState:
    """Verify the request's Clerk session token, at most once per request.

    Verification is local against ``CLERK_JWT_KEY``. The result is cached on
    ``request.state``, which every ``Request`` built from the same scope shares.
    """
    if _STATE_KEY in request.state:
        return request.state[_STATE_KEY]

    state = authenticate_request(
        request,
        AuthenticateRequestOptions(
            secret_key=CLERK_SECRET_KEY,
            jwt_key=CLERK_JWT_KEY,
            authorized_parties=CLERK_AUTHORIZED_PARTIES,
            accepts_token=["session_token"],
        ),
    )
    request.state[_STATE_KEY] = state
    return state
