"""Every route handler is ``async def``.

FastAPI awaits ``async def`` handlers on the event loop and runs plain ``def``
handlers in a worker threadpool. The app's I/O goes through async clients
(SQLAlchemy over asyncpg, ``httpx``), and the blocking call that remains (the
ML classifier) is awaited in a worker thread, so a handler has no reason to be
``def``.

The reverse is not checked: an ``async def`` handler that calls something
blocking directly stalls every concurrent request in the process. Await
blocking work through ``anyio.to_thread.run_sync``.

``SYNC_HANDLERS`` lists any handler allowed to stay ``def``, so an exemption is
deliberate rather than accidental.
"""

import inspect

from app.main import app

SYNC_HANDLERS: set[str] = set()


def _api_routes():
    """Routes this app defines, excluding FastAPI's built-in /docs and /openapi.json."""
    return [
        r
        for r in app.routes
        if getattr(r, "endpoint", None)
        and hasattr(r, "methods")
        and getattr(r.endpoint, "__module__", "").startswith("app.api.routes")
    ]


def test_every_handler_is_a_coroutine():
    offenders = [
        f"{sorted(r.methods)} {r.path} -> {r.endpoint.__name__}"
        for r in _api_routes()
        if not inspect.iscoroutinefunction(r.endpoint) and r.endpoint.__name__ not in SYNC_HANDLERS
    ]
    assert not offenders, (
        "These handlers are plain `def`. Make them `async def` and await their "
        "I/O, or add them to SYNC_HANDLERS:\n  " + "\n  ".join(offenders)
    )


def test_exemptions_still_exist():
    """Stop SYNC_HANDLERS from silently accumulating dead entries."""
    names = {r.endpoint.__name__ for r in _api_routes()}
    stale = SYNC_HANDLERS - names
    assert not stale, f"SYNC_HANDLERS lists handlers that no longer exist: {sorted(stale)}"
