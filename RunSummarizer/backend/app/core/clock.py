import time
from datetime import UTC, datetime


def utc_now() -> datetime:
    """The current time, in UTC."""
    return datetime.now(UTC)


def elapsed_ms(started: float) -> float:
    """Milliseconds since ``started``, a ``time.perf_counter()`` reading."""
    return (time.perf_counter() - started) * 1000
