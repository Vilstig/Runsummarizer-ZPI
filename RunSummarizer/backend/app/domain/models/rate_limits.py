from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from app.domain.enums import ImportPriority, WindowKind

if TYPE_CHECKING:
    import httpx

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class WindowUsage:
    """The calls used in one rate-limit window, and the window's limit."""

    used: int
    limit: int


@dataclass(frozen=True)
class RateLimitUsage:
    """A provider's rate-limit usage, by window name (e.g. ``'15m'``, ``'day'``)."""

    windows: Mapping[str, WindowUsage]


@dataclass(frozen=True)
class BudgetWindow:
    """One of a provider's rate-limit windows.

    Calls are counted in buckets of ``bucket`` aligned to the Unix epoch. A FIXED window
    is a single bucket, so its ``bucket`` equals its ``length``; a ROLLING window counts
    every bucket overlapping the last ``length``.
    """

    name: str  # e.g. '15m', 'day'; provider_budget_usage.window
    length: timedelta
    kind: WindowKind
    bucket: timedelta
    default_limit: int  # calls per window until a response reports the limit

    def __post_init__(self) -> None:
        if self.kind is WindowKind.FIXED and self.bucket != self.length:
            raise ValueError(f"fixed window {self.name!r}: bucket must equal length")

    def bucket_start(self, at: datetime) -> datetime:
        """The start of the bucket containing ``at`` (timezone-aware), in UTC."""
        return _EPOCH + (at - _EPOCH) // self.bucket * self.bucket


@dataclass(frozen=True)
class BudgetPolicy:
    """How a provider's calls are budgeted."""

    windows: tuple[BudgetWindow, ...]
    # the percent of each window's limit that reservations of a priority may fill, by
    # window name; a window left out may be filled to its limit
    ceilings: Mapping[ImportPriority, Mapping[str, int]]
    # the usage a response reports, e.g. from rate-limit headers; None when it reports none
    observe: Callable[[httpx.Response], RateLimitUsage | None] | None = None

    def ceiling(self, priority: ImportPriority, window: BudgetWindow) -> int:
        """The percent of ``window``'s limit that reservations of ``priority`` may fill."""
        return self.ceilings.get(priority, {}).get(window.name, 100)

    @property
    def longest_reach(self) -> timedelta:
        """How far back the oldest bucket any window still counts can start."""
        return max((window.length + window.bucket for window in self.windows), default=timedelta())
