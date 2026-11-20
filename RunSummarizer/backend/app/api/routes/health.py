"""Liveness and readiness probes."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.config.settings import OAUTH_STATE_SECRET, TOKEN_ENCRYPTION_KEY
from app.db.client import get_engine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["system"])

# Upper bound for a single dependency check, including connection setup.
CHECK_TIMEOUT_S = 2.0
# How long a readiness result is reused. The endpoint is unauthenticated and
# every check is real I/O, so without reuse a caller could turn request volume
# into database load.
CACHE_TTL_S = 5.0


async def _check_postgres() -> None:
    """Round-trip a query over the pool the application itself uses."""
    engine = get_engine()
    async with asyncio.timeout(CHECK_TIMEOUT_S), engine.connect() as connection:
        await connection.execute(text("SELECT 1"))


async def _check_secrets() -> None:
    """Verify the key material every authenticated request depends on is present."""
    missing = []
    if not OAUTH_STATE_SECRET:
        missing.append("OAUTH_STATE_SECRET")
    if not TOKEN_ENCRYPTION_KEY:
        missing.append("TOKEN_ENCRYPTION_KEY")
    if missing:
        raise RuntimeError(f"unset settings: {', '.join(missing)}")


# Dependencies the app cannot serve requests without. The activity providers' APIs
# are deliberately absent: their outages must not mark this app unready.
CHECKS: dict[str, Callable[[], Awaitable[None]]] = {
    "postgres": _check_postgres,
    "secrets": _check_secrets,
}


async def _run_check(name: str, check: Callable[[], Awaitable[None]]) -> dict:
    started = time.monotonic()
    try:
        await check()
        outcome, error = "ok", None
    except Exception as exc:
        logger.warning("Health check %r failed", name, exc_info=True)
        # Exception type only; messages can carry hostnames or credentials.
        outcome, error = "error", type(exc).__name__

    result = {
        "name": name,
        "status": outcome,  # 'ok' | 'error'
        "latency_ms": round((time.monotonic() - started) * 1000, 1),
    }
    if error is not None:
        result["error"] = error
    return result


_cache_lock = asyncio.Lock()
# (monotonic expiry, checks) for the last completed run, or None before the first.
_cached_checks: tuple[float, list[dict]] | None = None


async def _run_checks() -> list[dict]:
    """Run every check, or reuse a result younger than ``CACHE_TTL_S``."""
    global _cached_checks

    # Held across the checks so concurrent callers share one run rather than
    # each opening their own connection.
    async with _cache_lock:
        if _cached_checks is not None and time.monotonic() < _cached_checks[0]:
            return _cached_checks[1]

        checks = list(
            await asyncio.gather(*(_run_check(name, check) for name, check in CHECKS.items()))
        )
        _cached_checks = (time.monotonic() + CACHE_TTL_S, checks)
        return checks


@router.get("", summary="Liveness probe")
async def liveness() -> dict[str, str]:
    """Report that the process is running. Touches no dependency."""
    return {"status": "ok"}


@router.get("/ready", summary="Readiness probe")
async def readiness(response: Response) -> dict:
    """Report whether this app can serve traffic. 503 when any dependency fails."""
    checks = await _run_checks()
    ready = all(check["status"] == "ok" for check in checks)

    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "ok" if ready else "unavailable",
        "checks": checks,
    }
