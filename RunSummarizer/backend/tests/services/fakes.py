"""In-memory stand-ins for ``app.db.factory.transaction`` and the Strava API."""

import copy
import re
import uuid
from collections.abc import Iterable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta

import httpx

from app.db.factory import Repositories
from app.db.protocols.import_queue import Claim, FinishOutcome, QueuedItem
from app.db.protocols.provider import LinkedAccount
from app.domain.enums import (
    ImportErrorCode,
    ImportPriority,
    ImportSource,
    ImportStatus,
    LapType,
    Provider,
)
from app.domain.models import (
    Activity,
    ActivityRecord,
    BudgetPolicy,
    HeartRateZones,
    HeartRateZonesRecord,
    Lap,
    ProviderCredentials,
    RateLimitUsage,
    Summary,
    UserProfile,
    WeekTotals,
    WindowUsage,
)
from app.providers.strava.normalizer import normalize_strava_activity
from app.summaries.segmentation import segment_activity

STRAVA_TOKEN = {
    "access_token": "access-2",
    "refresh_token": "refresh-2",
    "expires_at": 4_102_444_800,  # Unix timestamp
}
# STRAVA_TOKEN as stored credentials
REFRESHED = ProviderCredentials(**STRAVA_TOKEN)

QUEUED_AT = datetime(2026, 1, 1, tzinfo=UTC)  # default sort_key and run_after of a queued item


@dataclass(frozen=True)
class TokenUpdate:
    """The arguments of an ``update_provider_tokens`` call."""

    provider: Provider
    user_id: str
    credentials: ProviderCredentials


class _Block:
    """Writes made inside one ``transaction`` block."""

    def __init__(self):
        self.saved: list[SavedActivity] = []
        # activity key -> record after update_activity or update_summary
        self.updates: dict[str, ActivityRecord] = {}
        # activity key -> its edited lap distances after set_lap_distances or reset_lap_distances
        self.lap_distances: dict[str, dict[int, float]] = {}
        self.token_updates: list[TokenUpdate] = []
        self.locked: list[str] = []  # user ids passed to get_and_lock_provider_credentials
        self.locked_activities: list[str] = []  # activity keys passed to get_and_lock_by_id
        # (provider, user id) pairs passed to clear_provider_credentials
        self.cleared: list[tuple[Provider, str]] = []


@dataclass
class SavedActivity:
    """The arguments of a ``save`` call."""

    record: ActivityRecord
    raw_payload: dict | None
    payload_kind: str | None
    streams: dict | None


class FakeActivityRepository:
    def __init__(self, database: "FakeDatabase", block: _Block):
        self._database = database
        self._block = block

    async def list_activities(
        self,
        *,
        user_id: str | None = None,
        source: str | None = None,
        after: date | None = None,
        before: date | None = None,
        limit: int = 50,
        skip: int = 0,
        include_laps: bool = False,
    ) -> list[ActivityRecord]:
        records = [
            self._database.with_edited_laps(record)
            for record in self._database.activities.values()
            if (user_id is None or record.user_id == user_id)
            and (source is None or record.activity.source == source)
            and (after is None or record.activity.start_time_local.date() >= after)
            and (before is None or record.activity.start_time_local.date() < before)
        ]
        records = records[skip : skip + limit]
        if include_laps:
            return records
        return [replace(record, activity=replace(record.activity, laps=[])) for record in records]

    async def weekly_totals(
        self, user_id: str, *, first_week_start: date, weeks: int
    ) -> list[WeekTotals]:
        week_starts = [first_week_start + timedelta(weeks=i) for i in range(weeks)]
        totals = {week_start: WeekTotals(week_start, 0.0, 0.0, 0.0) for week_start in week_starts}
        for record in self._database.activities.values():
            if record.user_id != user_id:
                continue
            local_date = record.activity.start_time_local.date()
            week_start = local_date - timedelta(days=local_date.weekday())
            if week_start not in totals:
                continue
            current = totals[week_start]
            totals[week_start] = replace(
                current,
                distance=current.distance + (record.activity.distance or 0),
                duration=current.duration + (record.activity.duration or 0),
                elevation_gain=current.elevation_gain + (record.activity.elevation_gain or 0),
            )
        return [totals[week_start] for week_start in week_starts]

    async def get_by_id(
        self, activity_id: str, *, user_id: str | None = None
    ) -> ActivityRecord | None:
        return self._find(activity_id, user_id)

    async def get_and_lock_by_id(
        self, activity_id: str, *, user_id: str | None = None
    ) -> ActivityRecord | None:
        self._block.locked_activities.append(activity_id)
        return self._find(activity_id, user_id)

    async def update_activity(
        self,
        activity_id: str,
        activity: Activity,
        *,
        summary: Summary,
        user_id: str | None = None,
    ) -> ActivityRecord | None:
        record = self._find_imported(activity_id, user_id)
        if record is None:
            return None
        types = {lap.index: lap.type for lap in activity.laps}
        imported_laps = [
            replace(lap, type=types.get(lap.index, lap.type)) for lap in record.activity.laps
        ]
        updated = replace(
            record,
            activity=replace(activity, laps=imported_laps, device_name=record.activity.device_name),
            summary=summary,
        )
        self._block.updates[activity_id] = updated
        return self._database.with_edited_laps(updated, self._lap_distances(activity_id))

    async def set_lap_distances(
        self, activity_id: str, distances: Mapping[int, float], *, user_id: str | None = None
    ) -> ActivityRecord | None:
        record = self._find_imported(activity_id, user_id)
        if record is None:
            return None
        _check_lap_indexes(record, distances)
        edited = {**self._lap_distances(activity_id), **distances}
        self._block.lap_distances[activity_id] = edited
        return self._database.with_edited_laps(record, edited)

    async def reset_lap_distances(
        self,
        activity_id: str,
        lap_indexes: Iterable[int] | None = None,
        *,
        user_id: str | None = None,
    ) -> ActivityRecord | None:
        record = self._find_imported(activity_id, user_id)
        if record is None:
            return None
        edited = {}
        if lap_indexes is not None:
            lap_indexes = set(lap_indexes)
            _check_lap_indexes(record, lap_indexes)
            edited = {
                index: distance
                for index, distance in self._lap_distances(activity_id).items()
                if index not in lap_indexes
            }
        self._block.lap_distances[activity_id] = edited
        return self._database.with_edited_laps(record, edited)

    async def update_summary(
        self, activity_id: str, summary: Summary, *, user_id: str | None = None
    ) -> ActivityRecord | None:
        record = self._find(activity_id, user_id)
        if record is None:
            return None
        updated = replace(record, summary=summary)
        self._block.updates[activity_id] = updated
        return updated

    async def is_stored(self, user_id: str, activity_key: str) -> bool:
        record = self._database.activities.get(activity_key)
        return record is not None and record.user_id == user_id

    async def save(
        self,
        record: ActivityRecord,
        *,
        raw_payload: dict | None = None,
        payload_kind: str | None = None,
        streams: dict | None = None,
    ) -> bool:
        if await self.is_stored(record.user_id, record.activity.key):
            return False
        self._block.saved.append(SavedActivity(record, raw_payload, payload_kind, streams))
        return True

    def _find(self, activity_id: str, user_id: str | None) -> ActivityRecord | None:
        """The committed record with its edited laps, when it belongs to ``user_id`` or
        ``user_id`` is None."""
        record = self._find_imported(activity_id, user_id)
        return self._database.with_edited_laps(record) if record is not None else None

    def _find_imported(self, activity_id: str, user_id: str | None) -> ActivityRecord | None:
        """The committed record with its imported laps, when it belongs to ``user_id`` or
        ``user_id`` is None."""
        record = self._database.activities.get(activity_id)
        if record is None or (user_id is not None and record.user_id != user_id):
            return None
        return record

    def _lap_distances(self, activity_id: str) -> dict[int, float]:
        """The activity's edited lap distances, as this block left them."""
        if activity_id in self._block.lap_distances:
            return self._block.lap_distances[activity_id]
        return self._database.lap_distances.get(activity_id, {})


def edited_lap(lap: Lap, distance: float) -> Lap:
    """The version of ``lap`` the user edited to ``distance``."""
    speed = distance / lap.duration if lap.duration else None
    return replace(lap, distance=distance, speed=speed, version=1)


def _check_lap_indexes(record: ActivityRecord, lap_indexes: Iterable[int]) -> None:
    indexes = {lap.index for lap in record.activity.laps}
    unknown = sorted(set(lap_indexes) - indexes)
    if unknown:
        raise ValueError(f"Activity {record.activity.key!r} has no lap {unknown[0]}")


class FakeUserRepository:
    async def ensure_user_exists(self, user_id: str) -> None:
        return None

    async def lock_user(self, user_id: str) -> None:
        return None

    async def delete_user(self, user_id: str) -> None:
        return None

    async def upsert_profile(self, user_id: str, profile: UserProfile) -> None:
        return None

    async def get_profile(self, user_id: str) -> UserProfile | None:
        return None


class FakeHeartRateZonesRepository:
    """Every save adds a record; there are no activities to decide on overwriting."""

    def __init__(self, records: dict[str, list[HeartRateZonesRecord]] | None = None):
        # user id -> newest first
        self.records: dict[str, list[HeartRateZonesRecord]] = {} if records is None else records

    async def save(
        self, user_id: str, zones: HeartRateZones, *, now: datetime
    ) -> HeartRateZonesRecord:
        record = HeartRateZonesRecord(valid_from=now, zones=zones)
        self.records.setdefault(user_id, []).insert(0, record)
        return record

    async def list_history(self, user_id: str) -> list[HeartRateZonesRecord]:
        return list(reversed(self.records.get(user_id, [])))

    async def get_current(self, user_id: str) -> HeartRateZonesRecord | None:
        return next(iter(self.records.get(user_id, [])), None)


class FakeProviderRepository:
    def __init__(
        self,
        database: "FakeDatabase",
        block: _Block,
        sync_requests: dict[tuple[Provider, str], datetime],
    ):
        self._database = database
        self._block = block
        self._sync_requests = sync_requests

    async def get_by_provider_user_id(
        self, provider: Provider, provider_user_id: str
    ) -> str | None:
        if provider != Provider.STRAVA:
            return None
        return self._database.users_by_athlete.get(provider_user_id)

    async def get_connected_user_id(self, provider: Provider, provider_user_id: str) -> str | None:
        user_id = await self.get_by_provider_user_id(provider, provider_user_id)
        if user_id is None or user_id not in self._database.credentials:
            return None
        return user_id

    async def get_connected_provider(self, user_id: str) -> Provider | None:
        if user_id in self._database.credentials:
            return Provider.STRAVA
        for provider, holder in self._database.provider_credentials:
            if holder == user_id:
                return provider
        return None

    async def list_accounts(self, user_id: str) -> list[LinkedAccount]:
        providers = [provider for provider, holder in self._database.provider_credentials]
        if user_id in self._database.users_by_athlete.values():
            providers.append(Provider.STRAVA)
        return [
            LinkedAccount(
                provider=provider,
                connected=await self.get_provider_credentials(provider=provider, user_id=user_id)
                is not None,
                sync_requested_at=self._sync_requests.get((provider, user_id)),
            )
            for provider in sorted(set(providers))
            if self._has_account(provider, user_id)
        ]

    async def get_provider_credentials(
        self, *, provider: Provider, user_id: str
    ) -> ProviderCredentials | None:
        if provider != Provider.STRAVA:
            return self._database.provider_credentials.get((provider, user_id))
        return self._database.credentials.get(user_id)

    async def get_and_lock_provider_credentials(
        self, *, provider: Provider, user_id: str
    ) -> ProviderCredentials | None:
        self._block.locked.append(user_id)
        return await self.get_provider_credentials(provider=provider, user_id=user_id)

    async def list_users_with_expired_tokens(
        self, provider: Provider, *, expired_before: datetime, limit: int
    ) -> list[str]:
        if provider == Provider.STRAVA:
            held = list(self._database.credentials.items())
        else:
            held = [
                (holder, credentials)
                for (held_by, holder), credentials in self._database.provider_credentials.items()
                if held_by == provider
            ]
        expired = sorted(
            (credentials.expires_at, user_id)
            for user_id, credentials in held
            if credentials.expires_at is not None
            and credentials.expires_at < expired_before.timestamp()
        )
        return [user_id for _, user_id in expired[:limit]]

    async def clear_provider_credentials(self, *, provider: Provider, user_id: str) -> bool:
        if not self._has_account(provider, user_id):
            return False
        self._block.cleared.append((provider, user_id))
        self._sync_requests.pop((provider, user_id), None)
        return True

    async def request_sync(self, *, provider: Provider, user_id: str, now: datetime) -> bool:
        if not self._has_account(provider, user_id):
            return False
        self._sync_requests[provider, user_id] = now
        return True

    async def get_sync_requested_at(self, *, provider: Provider, user_id: str) -> datetime | None:
        return self._sync_requests.get((provider, user_id))

    async def clear_sync_request(self, *, provider: Provider, user_id: str) -> None:
        self._sync_requests.pop((provider, user_id), None)

    def _has_account(self, provider: Provider, user_id: str) -> bool:
        if provider == Provider.STRAVA:
            return user_id in self._database.users_by_athlete.values()
        return (provider, user_id) in self._database.provider_credentials

    async def update_provider_tokens(
        self,
        *,
        provider: Provider,
        user_id: str,
        credentials: ProviderCredentials,
    ) -> bool:
        self._block.token_updates.append(TokenUpdate(provider, user_id, credentials))
        return True


@dataclass
class FakeImportItem:
    """An ``import_items`` row."""

    user_id: str
    provider: str  # 'strava' | 'garmin'
    activity_key: str
    source: ImportSource = ImportSource.SYNC
    priority: ImportPriority = ImportPriority.SYNC
    sort_key: datetime = QUEUED_AT
    status: ImportStatus = ImportStatus.QUEUED
    generation: int = 0
    attempts: int = 0
    run_after: datetime = QUEUED_AT
    lease_until: datetime | None = None
    lease_token: uuid.UUID | None = None
    raw_payload: dict | None = None
    sent_data: dict | None = None
    error_code: ImportErrorCode | None = None
    last_error: str | None = None
    # set by the writes that fail, block or expire the item, which the purge reads
    updated_at: datetime = QUEUED_AT

    def release_lease(self) -> None:
        self.lease_until = None
        self.lease_token = None


class FakeImportQueueRepository:
    """The import queue over one block's copy of the items, keyed by
    ``(user_id, provider, activity_key)``, and the committed activities. Rows are not
    locked.
    """

    def __init__(
        self,
        items: dict[tuple[str, str, str], FakeImportItem],
        activities: dict[str, ActivityRecord],
    ):
        self._items = items
        self._activities = activities

    async def enqueue_sync(
        self,
        user_id: str,
        provider: str,
        activity_keys: Sequence[str],
        *,
        spacing: timedelta,
        now: datetime,
    ) -> int:
        queued_sort_keys = [
            item.sort_key
            for item in self._items.values()
            if item.user_id == user_id
            and item.provider == provider
            and item.status == ImportStatus.QUEUED
        ]
        start = max([now, *queued_sort_keys])
        added = 0
        for position, activity_key in enumerate(dict.fromkeys(activity_keys), start=1):
            if (user_id, provider, activity_key) in self._items or self._stored(
                user_id, provider, activity_key
            ):
                continue
            self._items[user_id, provider, activity_key] = FakeImportItem(
                user_id,
                provider,
                activity_key,
                sort_key=start + position * spacing,
                run_after=now,
                updated_at=now,
            )
            added += 1
        return added

    async def enqueue_webhook(
        self,
        user_id: str,
        provider: str,
        activity_key: str,
        *,
        sent_data: dict | None = None,
        now: datetime,
    ) -> None:
        item = self._items.get((user_id, provider, activity_key))
        if item is None:
            self._items[user_id, provider, activity_key] = FakeImportItem(
                user_id,
                provider,
                activity_key,
                source=ImportSource.WEBHOOK,
                priority=ImportPriority.WEBHOOK,
                sort_key=now,
                run_after=now,
                sent_data=copy.deepcopy(sent_data),
            )
            return
        if item.status in (ImportStatus.DEAD, ImportStatus.BLOCKED):
            item.attempts = 0
            item.run_after = now
        if item.status != ImportStatus.RUNNING:
            item.status = ImportStatus.QUEUED
        item.generation += 1
        item.source = ImportSource.WEBHOOK
        item.priority = ImportPriority.WEBHOOK
        item.sort_key = min(item.sort_key, now)
        item.raw_payload = None
        item.sent_data = copy.deepcopy(sent_data)

    async def lock_next(
        self, provider: str, *, now: datetime, saved_payload_only: bool = False
    ) -> QueuedItem | None:
        claimable = [
            item
            for item in self._items.values()
            if item.provider == provider
            and item.status == ImportStatus.QUEUED
            and item.run_after <= now
            and (item.raw_payload is not None or not saved_payload_only)
        ]
        if not claimable:
            return None
        item = min(claimable, key=lambda item: (item.priority, item.sort_key))
        return QueuedItem(
            user_id=item.user_id,
            provider=item.provider,
            activity_key=item.activity_key,
            source=item.source,
            priority=item.priority,
            generation=item.generation,
            raw_payload=copy.deepcopy(item.raw_payload),
            sent_data=copy.deepcopy(item.sent_data),
        )

    async def claim(self, item: QueuedItem, *, lease: timedelta, now: datetime) -> Claim:
        row = self._items[item.user_id, item.provider, item.activity_key]
        row.status = ImportStatus.RUNNING
        row.attempts += 1
        row.lease_until = now + lease
        row.lease_token = uuid.uuid4()
        return Claim(
            user_id=row.user_id,
            provider=row.provider,
            activity_key=row.activity_key,
            generation=row.generation,
            attempts=row.attempts,
            lease_token=row.lease_token,
            sent_data=item.sent_data,
        )

    async def save_payload(self, claim: Claim, raw_payload: dict, *, now: datetime) -> bool:
        item = self._held(claim)
        if item is None:
            return False
        if item.generation == claim.generation:
            item.raw_payload = copy.deepcopy(raw_payload)
        return True

    async def finish(self, claim: Claim, *, now: datetime) -> FinishOutcome:
        item = self._held(claim)
        if item is None:
            return FinishOutcome.LOST
        if item.generation == claim.generation:
            del self._items[claim.user_id, claim.provider, claim.activity_key]
            return FinishOutcome.DONE
        item.status = ImportStatus.QUEUED
        item.attempts = 0
        item.run_after = now
        item.release_lease()
        return FinishOutcome.REQUEUED

    async def retry_later(
        self,
        claim: Claim,
        *,
        run_after: datetime,
        error_code: ImportErrorCode,
        last_error: str,
        raw_payload: dict | None = None,
        now: datetime,
    ) -> bool:
        item = self._fail(claim, ImportStatus.QUEUED, error_code, last_error, raw_payload, now)
        if item is None:
            return False
        item.run_after = run_after
        return True

    async def mark_dead(
        self,
        claim: Claim,
        *,
        error_code: ImportErrorCode,
        last_error: str,
        raw_payload: dict | None = None,
        now: datetime,
    ) -> bool:
        failed = self._fail(claim, ImportStatus.DEAD, error_code, last_error, raw_payload, now)
        return failed is not None

    async def release(self, claim: Claim, *, run_after: datetime, now: datetime) -> bool:
        item = self._held(claim)
        if item is None:
            return False
        item.status = ImportStatus.QUEUED
        item.attempts -= 1
        item.run_after = run_after
        item.release_lease()
        return True

    async def block(self, claim: Claim, *, last_error: str, now: datetime) -> int:
        held = self._held(claim)
        if held is not None:
            held.last_error = last_error
        blocked = [
            item
            for item in self._items.values()
            if item.user_id == claim.user_id
            and item.provider == claim.provider
            and (item.status == ImportStatus.QUEUED or item is held)
        ]
        for item in blocked:
            item.status = ImportStatus.BLOCKED
            item.error_code = ImportErrorCode.AUTHORIZATION_REVOKED
            item.release_lease()
            item.updated_at = now
        return len(blocked)

    async def retry_failures(
        self,
        user_id: str,
        provider: str,
        *,
        activity_keys: Sequence[str] | None = None,
        now: datetime,
    ) -> int:
        dead = [
            item
            for item in self._items.values()
            if item.user_id == user_id
            and item.provider == provider
            and item.status == ImportStatus.DEAD
            and (activity_keys is None or item.activity_key in activity_keys)
        ]
        for item in dead:
            item.status = ImportStatus.QUEUED
            item.attempts = 0
            item.run_after = now
            item.updated_at = now
        return len(dead)

    async def count_by_status(self, user_id: str, provider: str) -> dict[ImportStatus, int]:
        counts = dict.fromkeys(ImportStatus, 0)
        for item in self._items.values():
            if item.user_id == user_id and item.provider == provider:
                counts[item.status] += 1
        return counts

    async def count_by_status_per_provider(
        self, user_id: str
    ) -> dict[str, dict[ImportStatus, int]]:
        counts: dict[str, dict[ImportStatus, int]] = {}
        for item in self._items.values():
            if item.user_id == user_id:
                counts.setdefault(item.provider, dict.fromkeys(ImportStatus, 0))[item.status] += 1
        return counts

    async def expire_leases(self, provider: str, *, max_attempts: int, now: datetime) -> int:
        expired = [
            item
            for item in self._items.values()
            if item.provider == provider
            and item.status == ImportStatus.RUNNING
            and item.lease_until < now
        ]
        for item in expired:
            if item.attempts >= max_attempts:
                item.status = ImportStatus.DEAD
                item.error_code = ImportErrorCode.WORKER_LOST
            else:
                item.status = ImportStatus.QUEUED
            item.release_lease()
            item.run_after = now
            item.updated_at = now
        return len(expired)

    async def purge_failures(self, provider: str, *, max_age: timedelta, now: datetime) -> int:
        old = [
            key
            for key, item in self._items.items()
            if item.provider == provider
            and item.status in (ImportStatus.DEAD, ImportStatus.BLOCKED)
            and item.updated_at < now - max_age
        ]
        for key in old:
            del self._items[key]
        return len(old)

    def _stored(self, user_id: str, provider: str, activity_key: str) -> bool:
        """Whether the user has a committed activity from ``provider`` under ``activity_key``."""
        record = self._activities.get(activity_key)
        return (
            record is not None and record.user_id == user_id and record.activity.source == provider
        )

    def _held(self, claim: Claim) -> FakeImportItem | None:
        """The claimed item, while it carries the claim's lease token."""
        item = self._items.get((claim.user_id, claim.provider, claim.activity_key))
        if item is None or item.lease_token != claim.lease_token:
            return None
        return item

    def _fail(
        self,
        claim: Claim,
        status: ImportStatus,
        error_code: ImportErrorCode,
        last_error: str,
        raw_payload: dict | None,
        now: datetime,
    ) -> FakeImportItem | None:
        item = self._held(claim)
        if item is None:
            return None
        item.status = status
        item.updated_at = now
        item.error_code = error_code
        item.last_error = last_error
        item.release_lease()
        if raw_payload is not None:
            fresh = item.generation == claim.generation
            item.raw_payload = copy.deepcopy(raw_payload) if fresh else None
        return item


@dataclass
class FakeProviderBudget:
    """A provider's budget, as a number of calls reservations may still take."""

    calls_left: int = 1000
    refills_at: datetime | None = None  # when calls_left is refilled
    paused_until: datetime | None = None
    reservations: list[tuple[int, ImportPriority]] = field(default_factory=list)  # (cost, priority)
    usage_reports: list[RateLimitUsage] = field(default_factory=list)  # record_usage calls
    sweeps: list[datetime] = field(default_factory=list)  # the now of delete_old_buckets calls


class FakeProviderBudgetRepository:
    """The providers' budgets over one block's copy of them, by provider. Policies and
    ceilings are not applied: the priority of each reservation is recorded.
    """

    def __init__(self, budgets: dict[str, FakeProviderBudget]):
        self._budgets = budgets

    async def reserve(
        self,
        provider: str,
        cost: int,
        *,
        policy: BudgetPolicy,
        priority: ImportPriority,
        now: datetime,
    ) -> bool:
        if cost == 0:
            return True
        budget = self._budget(provider)
        if self._paused(budget, now) or budget.calls_left < cost:
            return False
        budget.calls_left -= cost
        budget.reservations.append((cost, priority))
        return True

    async def resumes_at(
        self,
        provider: str,
        cost: int,
        *,
        policy: BudgetPolicy,
        priority: ImportPriority,
        now: datetime,
    ) -> datetime | None:
        if cost == 0:
            return None
        budget = self._budget(provider)
        waits = []
        if self._paused(budget, now):
            waits.append(budget.paused_until)
        if budget.calls_left < cost and budget.refills_at is not None:
            waits.append(budget.refills_at)
        return max(waits, default=None)

    async def record_usage(
        self,
        provider: str,
        usage: RateLimitUsage,
        *,
        policy: BudgetPolicy,
        sent_at: datetime | None = None,
        now: datetime,
    ) -> None:
        self._budget(provider).usage_reports.append(usage)

    async def pause(self, provider: str, until: datetime) -> None:
        budget = self._budget(provider)
        if budget.paused_until is None or budget.paused_until < until:
            budget.paused_until = until

    async def paused_until(self, provider: str, *, now: datetime) -> datetime | None:
        budget = self._budget(provider)
        return budget.paused_until if self._paused(budget, now) else None

    async def get_usage(
        self, provider: str, *, policy: BudgetPolicy, now: datetime
    ) -> RateLimitUsage:
        raise NotImplementedError

    async def delete_old_buckets(
        self, provider: str, *, policy: BudgetPolicy, now: datetime
    ) -> int:
        self._budget(provider).sweeps.append(now)
        return 0

    def _budget(self, provider: str) -> FakeProviderBudget:
        return self._budgets.setdefault(provider, FakeProviderBudget())

    @staticmethod
    def _paused(budget: FakeProviderBudget, now: datetime) -> bool:
        return budget.paused_until is not None and budget.paused_until > now


class FakeDatabase:
    """``app.db.factory.transaction`` over in-memory state.

    A block's writes become visible only when the block exits cleanly, as a
    committed Postgres transaction's do. Reads see committed state only. Locks are
    recorded, not enforced.
    """

    def __init__(self):
        # committed, by activity key, in list order, with their imported laps
        self.activities: dict[str, ActivityRecord] = {}
        # committed edited lap distances (Lap.index -> m), by activity key
        self.lap_distances: dict[str, dict[int, float]] = {}
        self.raw_payloads: dict[str, dict] = {}  # committed, by activity key
        self.payload_kinds: dict[str, str] = {}  # of the committed raw payloads, by activity key
        self.streams: dict[str, dict] = {}  # committed {stream type: samples}, by activity key
        self.token_updates: list[TokenUpdate] = []  # committed update_provider_tokens calls
        self.locks: list[list[str]] = []  # each block's get_and_lock_provider_credentials user ids
        self.activity_locks: list[list[str]] = []  # each block's get_and_lock_by_id activity keys
        self.users_by_athlete: dict[str, str] = {}  # Strava athlete id -> user id
        # user id -> Strava credentials; a user holding them is connected to Strava
        self.credentials: dict[str, ProviderCredentials] = {}
        # the credentials of providers other than Strava; their users are connected to them
        self.provider_credentials: dict[tuple[Provider, str], ProviderCredentials] = {}
        # committed pending sync requests, by (provider, user id)
        self.sync_requests: dict[tuple[Provider, str], datetime] = {}
        # committed import items by (user_id, provider, activity_key)
        self.import_items: dict[tuple[str, str, str], FakeImportItem] = {}
        self.budgets: dict[str, FakeProviderBudget] = {}  # committed, by provider
        # committed HR zone records, newest first, by user id
        self.hr_zones: dict[str, list[HeartRateZonesRecord]] = {}
        self.blocks_opened = 0

    def with_edited_laps(
        self, record: ActivityRecord, lap_distances: dict[int, float] | None = None
    ) -> ActivityRecord:
        """``record`` with each lap in ``lap_distances`` (by default the committed ones)
        as the user edited it."""
        if lap_distances is None:
            lap_distances = self.lap_distances.get(record.activity.key, {})
        if not lap_distances:
            return record
        activity_laps = [
            edited_lap(lap, lap_distances[lap.index]) if lap.index in lap_distances else lap
            for lap in record.activity.laps
        ]
        return replace(record, activity=replace(record.activity, laps=activity_laps))

    def budget(self, provider: str = "strava") -> FakeProviderBudget:
        """The provider's committed budget."""
        return self.budgets.setdefault(provider, FakeProviderBudget())

    def add_strava_user(self, user_id: str, athlete_id: int, refresh_token: str) -> None:
        """Link and connect the user to the Strava athlete, with an expired access token."""
        self.users_by_athlete[str(athlete_id)] = user_id
        self.credentials[user_id] = ProviderCredentials("access-1", refresh_token, expires_at=0)

    def queue_item(
        self,
        user_id: str,
        activity_key: str,
        *,
        provider: str = "strava",
        priority: ImportPriority = ImportPriority.SYNC,
        **fields,
    ) -> None:
        """Commit a queued item, its ``source`` matching ``priority``."""
        source = ImportSource.WEBHOOK if priority == ImportPriority.WEBHOOK else ImportSource.SYNC
        self.import_items[user_id, provider, activity_key] = FakeImportItem(
            user_id, provider, activity_key, source=source, priority=priority, **fields
        )

    def import_item(
        self, user_id: str, activity_key: str, *, provider: str = "strava"
    ) -> FakeImportItem | None:
        """The committed item, or None."""
        return self.import_items.get((user_id, provider, activity_key))

    @asynccontextmanager
    async def transaction(self):
        self.blocks_opened += 1
        block = _Block()
        import_items = copy.deepcopy(self.import_items)
        budgets = copy.deepcopy(self.budgets)
        hr_zones = copy.deepcopy(self.hr_zones)
        sync_requests = dict(self.sync_requests)
        yield Repositories(
            activities=FakeActivityRepository(self, block),
            users=FakeUserRepository(),
            providers=FakeProviderRepository(self, block, sync_requests),
            budgets=FakeProviderBudgetRepository(budgets),
            import_queue=FakeImportQueueRepository(import_items, self.activities),
            hr_zones=FakeHeartRateZonesRepository(hr_zones),
        )
        self.import_items = import_items
        self.budgets = budgets
        self.hr_zones = hr_zones
        self.sync_requests = sync_requests
        for saved in block.saved:
            key = saved.record.activity.key
            self.activities[key] = saved.record
            self.lap_distances.pop(key, None)
            if saved.raw_payload is not None:
                self.raw_payloads[key] = saved.raw_payload
                self.payload_kinds[key] = saved.payload_kind
            if saved.streams is not None:
                self.streams[key] = saved.streams
        self.activities.update(block.updates)
        self.lap_distances.update(block.lap_distances)
        self.token_updates.extend(block.token_updates)
        self.locks.append(block.locked)
        self.activity_locks.append(block.locked_activities)
        for update in block.token_updates:
            if update.provider == Provider.STRAVA:
                self.credentials[update.user_id] = update.credentials
            else:
                self.provider_credentials[update.provider, update.user_id] = update.credentials
        for provider, user_id in block.cleared:
            if provider == Provider.STRAVA:
                self.credentials.pop(user_id, None)
            else:
                self.provider_credentials.pop((provider, user_id), None)


def strava_usage(used_15m: int, used_day: int, limit_15m: int, limit_day: int) -> RateLimitUsage:
    """Strava's read usage in its 15-minute window and UTC day."""
    return RateLimitUsage(
        {
            "15m": WindowUsage(used=used_15m, limit=limit_15m),
            "day": WindowUsage(used=used_day, limit=limit_day),
        }
    )


def strava_run(
    activity_id: int,
    *,
    laps: int = 3,
    activity_type: str = "Run",
    start_date: str = "2026-05-01T06:00:00Z",
) -> dict:
    """A Strava activity detail with ``laps`` 1 km laps, started at ``start_date`` (UTC)."""
    return {
        "id": activity_id,
        "type": activity_type,
        "name": f"Run {activity_id}",
        "start_date": start_date,
        "start_date_local": "2026-05-01T08:00:00Z",
        "utc_offset": 7200.0,
        "timezone": "(GMT+01:00) Europe/Warsaw",
        "distance": 1000.0 * laps,
        "moving_time": 300 * laps,
        "average_speed": 3.33,
        "average_heartrate": 150.0,
        "max_heartrate": 170.0,
        "total_elevation_gain": 10.0,
        "laps": [
            {
                "lap_index": index,
                "distance": 1000.0,
                "moving_time": 300,
                "average_speed": 3.33,
                "average_heartrate": 150.0,
                "max_heartrate": 165.0,
                "total_elevation_gain": 3.0,
            }
            for index in range(1, laps + 1)
        ],
    }


# The streams ``FakeStrava`` serves for every activity, under Strava's keys
# with STRAVA_STREAMS' heart rates: 1 s in zone 2 and 1 s in zone 3; the defaults give 2 s
# in zone 3
USER_HR_ZONES = HeartRateZones(
    zone1_bpm=100, zone2_bpm=120, zone3_bpm=145, zone4_bpm=155, zone5_bpm=175
)

STRAVA_STREAMS = {
    "time": [0, 1, 2],
    "distance": [0.0, 3.0, 6.0],
    "heartrate": [140, 150, 160],
    "velocity_smooth": [3.0, 3.0, 3.0],
    "altitude": [100.0, 100.5, 101.0],
}


def run_payload(activity_id: int) -> dict:
    """The payload ``FakeStrava`` serves for ``strava_run(activity_id)``."""
    return {"format": "strava_v1", "detail": strava_run(activity_id), "streams": STRAVA_STREAMS}


def label_laps(activity: Activity, lap_type: LapType) -> Activity:
    """The activity with every lap ``lap_type``, segmented."""
    return segment_activity(
        replace(activity, laps=[replace(lap, type=lap_type) for lap in activity.laps])
    )


def stored_run(
    activity_id: int, *, user_id: str = "user-1", laps: int = 3, summary: str = ""
) -> ActivityRecord:
    """The stored record of ``strava_run(activity_id, laps=laps)``, every lap a run."""
    detail = strava_run(activity_id, laps=laps)
    activity = replace(
        normalize_strava_activity(detail, detail["laps"]), zone_bounds=(120, 140, 160, 180)
    )
    return ActivityRecord(
        user_id=user_id,
        activity=label_laps(activity, LapType.RUN),
        summary=Summary(text=summary),
    )


class FakeStrava:
    """Strava API stand-in serving the activities in ``details``."""

    _ACTIVITY_PATH = re.compile(r"/api/v3/activities/(\d+)(/streams)?")

    def __init__(self):
        self.details: dict[int, dict] = {}  # activity id -> detail
        self.listed_types: dict[int, str] = {}  # activity id -> type the listing reports
        # URL path -> HTTP status to answer with, or an exception to raise
        self.failures: dict[str, int | BaseException] = {}
        self.usage: RateLimitUsage | None = None  # reported with every API response
        self.requests: list[httpx.Request] = []

    def add(self, detail: dict, *, listed_type: str | None = None) -> None:
        """Serve ``detail``. The listing reports ``listed_type``, when given, instead of
        the detail's type.
        """
        self.details[detail["id"]] = detail
        if listed_type is not None:
            self.listed_types[detail["id"]] = listed_type

    def fail(self, path: str, outcome: int | BaseException) -> None:
        self.failures[path] = outcome

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        response = self._respond(request)
        if self.usage is not None and request.url.path.startswith("/api/v3/"):
            fifteen, day = self.usage.windows["15m"], self.usage.windows["day"]
            response.headers["X-ReadRateLimit-Usage"] = f"{fifteen.used},{day.used}"
            response.headers["X-ReadRateLimit-Limit"] = f"{fifteen.limit},{day.limit}"
        return response

    def _respond(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path in self.failures:
            outcome = self.failures[path]
            if isinstance(outcome, BaseException):
                raise outcome
            return httpx.Response(outcome)
        if path == "/oauth/deauthorize":
            return httpx.Response(200, json={})
        if path == "/oauth/token":
            return httpx.Response(200, json=STRAVA_TOKEN)
        if path == "/api/v3/athlete/activities":
            listed = [
                {
                    "id": d["id"],
                    "type": self.listed_types.get(d["id"], d["type"]),
                    "start_date": d["start_date"],
                }
                for d in self.details.values()
            ]
            return httpx.Response(200, json=listed if request.url.params["page"] == "1" else [])
        match = self._ACTIVITY_PATH.fullmatch(path)
        if match and int(match[1]) in self.details:
            if match[2]:
                return httpx.Response(
                    200,
                    json={key: {"data": samples} for key, samples in STRAVA_STREAMS.items()},
                )
            return httpx.Response(200, json=self.details[int(match[1])])
        return httpx.Response(404)
