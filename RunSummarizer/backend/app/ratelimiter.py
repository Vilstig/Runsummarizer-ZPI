"""In-memory token-bucket rate limiting.

Limitations:
- Buckets are per process; multiple uvicorn workers each maintain separate counters.
- Counters reset on application restart.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config.loader import CONFIG
from app.config.settings import TRUST_PROXY_HEADERS, TRUSTED_PROXY_HOPS
from app.core.clerk_auth import authenticate_clerk_request

logger = logging.getLogger(__name__)


class TokenBucket:
    """
    Token Bucket rate limiter.

    Each request consumes a number of tokens, and the bucket is refilled at a fixed rate.
    """

    def __init__(self, max_tokens: int, refill_rate: int, interval: float):
        """
        Initialize the token bucket.

        :param max_tokens: Maximum number of tokens the bucket can hold (burst capacity).
        :param refill_rate: Number of tokens added per refill interval.
        :param interval: Time in seconds between refills.
        """
        if max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        if refill_rate <= 0:
            raise ValueError("refill_rate must be positive")
        if interval <= 0:
            raise ValueError("interval must be positive")

        self.max_tokens = max_tokens
        self.refill_rate = refill_rate
        self.interval = interval

        self.tokens = max_tokens
        self.refilled_at = time.time()
        self.lock = threading.Lock()

    def _refill(self):
        """Add tokens based on elapsed time since the last refill."""
        now = time.time()
        elapsed = now - self.refilled_at

        if elapsed >= self.interval:
            num_refills = int(elapsed // self.interval)
            self.tokens = min(self.max_tokens, self.tokens + num_refills * self.refill_rate)
            # Advance the timestamp by the number of full intervals consumed,
            # not to `now`, so partial intervals aren't lost.
            self.refilled_at += num_refills * self.interval

    def allow_request(self, tokens: int = 1) -> bool:
        """
        Attempt to consume `tokens` from the bucket.

        Returns True if the request is allowed, False if the bucket
        does not have enough tokens.
        """
        with self.lock:
            self._refill()

            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False

    def get_remaining(self) -> int:
        """Return the current number of available tokens."""
        with self.lock:
            self._refill()
            return self.tokens

    def get_reset_time(self) -> float:
        """Return the Unix timestamp when the next refill occurs."""
        with self.lock:
            return self.refilled_at + self.interval


class RateLimiterStore:
    """
    Manages per-client Token Buckets.

    Each unique client key (e.g., IP address or user id) gets its own bucket
    with identical parameters.
    """

    def __init__(
        self, max_tokens: int, refill_rate: int, interval: float, max_buckets: int = 100_000
    ):
        if max_buckets <= 0:
            raise ValueError("max_buckets must be positive")
        self.max_tokens = max_tokens
        self.refill_rate = refill_rate
        self.interval = interval
        self.max_buckets = max_buckets
        # least recently used first
        self._buckets: OrderedDict[str, TokenBucket] = OrderedDict()
        self._lock = threading.Lock()

    def get_bucket(self, key: str) -> TokenBucket:
        """
        Return the TokenBucket for a given client key.
        Creates a new bucket if one does not exist yet; past ``max_buckets`` buckets,
        the least recently used one is dropped.
        """
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is not None:
                self._buckets.move_to_end(key)
                return bucket
            bucket = TokenBucket(
                max_tokens=self.max_tokens,
                refill_rate=self.refill_rate,
                interval=self.interval,
            )
            self._buckets[key] = bucket
            if len(self._buckets) > self.max_buckets:
                self._buckets.popitem(last=False)
            return bucket

    def __len__(self) -> int:
        with self._lock:
            return len(self._buckets)


def _create_stores() -> tuple[RateLimiterStore, RateLimiterStore]:
    auth_store = RateLimiterStore(
        max_tokens=CONFIG.get("RATE_LIMIT_AUTH_MAX_TOKENS", 120),
        refill_rate=CONFIG.get("RATE_LIMIT_AUTH_REFILL_RATE", 60),
        interval=CONFIG.get("RATE_LIMIT_AUTH_INTERVAL", 60),
        max_buckets=CONFIG.get("RATE_LIMIT_MAX_BUCKETS", 100_000),
    )
    public_store = RateLimiterStore(
        max_tokens=CONFIG.get("RATE_LIMIT_PUBLIC_MAX_TOKENS", 30),
        refill_rate=CONFIG.get("RATE_LIMIT_PUBLIC_REFILL_RATE", 30),
        interval=CONFIG.get("RATE_LIMIT_PUBLIC_INTERVAL", 60),
        max_buckets=CONFIG.get("RATE_LIMIT_MAX_BUCKETS", 100_000),
    )
    return auth_store, public_store


_auth_store, _public_store = _create_stores()


def get_client_ip(request: Request, *, trusted_hops: int = TRUSTED_PROXY_HOPS) -> str:
    """Return the client IP for rate limiting.

    With ``TRUST_PROXY_HEADERS``, the client is the address ``trusted_hops`` entries from
    the right of ``X-Forwarded-For``: each trusted proxy appends the address it was
    reached from, and entries left of those are whatever the client sent.
    """
    if TRUST_PROXY_HEADERS:
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            hops = [hop.strip() for hop in forwarded_for.split(",")]
            if len(hops) >= trusted_hops and hops[-trusted_hops]:
                return hops[-trusted_hops]

    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _extract_bearer_token(request: Request) -> str | None:
    authorization = request.headers.get("Authorization")
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token


def resolve_rate_limit_key(request: Request) -> tuple[RateLimiterStore, str]:
    """Return the store and bucket key for the incoming request."""
    if _extract_bearer_token(request):
        state = authenticate_clerk_request(request)
        if state.is_signed_in:
            return _auth_store, f"user:{state.payload['sub']}"

    return _public_store, f"ip:{get_client_ip(request)}"


def _excluded_prefixes() -> list[str]:
    prefixes = CONFIG.get("RATE_LIMIT_EXCLUDED_PREFIXES")
    if prefixes is None:
        return ["/api/health", "/api/webhooks", "/docs", "/redoc", "/openapi.json"]
    return list(prefixes)


def _is_excluded_path(path: str) -> bool:
    return any(path == prefix or path.startswith(f"{prefix}/") for prefix in _excluded_prefixes())


def rate_limit_enabled() -> bool:
    return CONFIG.get("RATE_LIMIT_ENABLED", True)


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if not rate_limit_enabled():
            return await call_next(request)

        if request.method == "OPTIONS":
            return await call_next(request)

        if _is_excluded_path(request.url.path):
            return await call_next(request)

        store, key = resolve_rate_limit_key(request)
        bucket = store.get_bucket(key)

        if not bucket.allow_request():
            retry_after = max(1, int(bucket.get_reset_time() - time.time()))
            logger.warning(
                "rate limit exceeded for %s (limit %d per %gs)",
                key,
                store.max_tokens,
                store.interval,
            )
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Remaining": "0",
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Remaining"] = str(bucket.get_remaining())
        return response
