"""Contract tests for ``AsyncHeartRateZonesRepository``.

Each test runs in one transaction, where ``now()`` (and so every activity's
``created_at``) is the transaction start. Saves pass ``now`` explicitly, earlier or
later than that.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models import HrZones
from app.domain.errors import UserNotFoundError
from app.domain.models import HeartRateZones, HeartRateZonesRecord

pytestmark = pytest.mark.anyio

ZONES = HeartRateZones(zone1_bpm=100, zone2_bpm=120, zone3_bpm=140, zone4_bpm=160, zone5_bpm=175)
OTHER_ZONES = HeartRateZones(
    zone1_bpm=105, zone2_bpm=125, zone3_bpm=145, zone4_bpm=165, zone5_bpm=180
)


def _hours_ago(hours: float) -> datetime:
    return datetime.now(UTC) - timedelta(hours=hours)


@pytest.fixture
def stored(db_session):
    """The ``valid_from`` of each of a user's stored records, newest first."""

    async def read(user_id: str) -> list[datetime]:
        return list(
            await db_session.scalars(
                select(HrZones.valid_from)
                .where(HrZones.user_id == user_id)
                .order_by(HrZones.valid_from.desc())
            )
        )

    return read


async def test_first_save_adds_a_record(hr_zones_repo, user_id, stored):
    now = _hours_ago(1)

    saved = await hr_zones_repo.save(user_id, ZONES, now=now)

    assert saved == HeartRateZonesRecord(valid_from=now, zones=ZONES)
    assert await stored(user_id) == [now]


async def test_save_without_new_activities_overwrites_the_latest_record(
    hr_zones_repo, user_id, stored
):
    await hr_zones_repo.save(user_id, ZONES, now=_hours_ago(2))
    later = _hours_ago(1)

    saved = await hr_zones_repo.save(user_id, OTHER_ZONES, now=later)

    assert saved == HeartRateZonesRecord(valid_from=later, zones=OTHER_ZONES)
    assert await stored(user_id) == [later]
    assert await hr_zones_repo.get_current(user_id) == saved


async def test_save_after_a_new_activity_adds_a_record(
    hr_zones_repo, user_id, save_activity, stored
):
    first = await hr_zones_repo.save(user_id, ZONES, now=_hours_ago(1))
    await save_activity("act-1")

    second = await hr_zones_repo.save(user_id, OTHER_ZONES, now=datetime.now(UTC))

    assert await stored(user_id) == [second.valid_from, first.valid_from]
    assert await hr_zones_repo.get_current(user_id) == second


async def test_activities_added_before_the_latest_record_are_not_new(
    hr_zones_repo, user_id, save_activity, stored
):
    await save_activity("act-1")
    await hr_zones_repo.save(user_id, ZONES, now=datetime.now(UTC))
    await save_activity("act-1")  # a second insert of the same activity is ignored

    saved = await hr_zones_repo.save(user_id, OTHER_ZONES, now=datetime.now(UTC))

    assert await stored(user_id) == [saved.valid_from]


async def test_another_users_activities_are_ignored(
    hr_zones_repo, user_id, other_user_id, save_activity, stored
):
    await hr_zones_repo.save(user_id, ZONES, now=_hours_ago(2))
    await save_activity("act-1", user_id=other_user_id)

    saved = await hr_zones_repo.save(user_id, OTHER_ZONES, now=_hours_ago(1))

    assert await stored(user_id) == [saved.valid_from]


async def test_list_history_is_oldest_first(hr_zones_repo, user_id, save_activity):
    first = await hr_zones_repo.save(user_id, ZONES, now=_hours_ago(1))
    await save_activity("act-1")
    second = await hr_zones_repo.save(user_id, OTHER_ZONES, now=datetime.now(UTC))

    assert await hr_zones_repo.list_history(user_id) == [first, second]


async def test_list_history_without_records_is_empty(hr_zones_repo, user_id):
    assert await hr_zones_repo.list_history(user_id) == []


async def test_list_history_leaves_out_other_users_records(hr_zones_repo, user_id, other_user_id):
    await hr_zones_repo.save(other_user_id, ZONES, now=datetime.now(UTC))

    assert await hr_zones_repo.list_history(user_id) == []


async def test_get_current_without_records_is_none(hr_zones_repo, user_id):
    assert await hr_zones_repo.get_current(user_id) is None


async def test_save_for_an_unknown_user_raises(hr_zones_repo):
    with pytest.raises(UserNotFoundError, match="does not exist"):
        await hr_zones_repo.save("no-such-user", ZONES, now=datetime.now(UTC))


async def test_deleting_the_user_removes_their_records(hr_zones_repo, user_repo, user_id, stored):
    await hr_zones_repo.save(user_id, ZONES, now=datetime.now(UTC))

    await user_repo.delete_user(user_id)

    assert await stored(user_id) == []


async def test_save_rejects_bounds_that_do_not_increase(hr_zones_repo, user_id):
    zones = HeartRateZones(
        zone1_bpm=100, zone2_bpm=120, zone3_bpm=120, zone4_bpm=160, zone5_bpm=175
    )
    with pytest.raises(IntegrityError):
        await hr_zones_repo.save(user_id, zones, now=datetime.now(UTC))


async def test_save_rejects_bounds_above_256(hr_zones_repo, user_id):
    zones = HeartRateZones(
        zone1_bpm=100, zone2_bpm=120, zone3_bpm=140, zone4_bpm=160, zone5_bpm=300
    )
    with pytest.raises(IntegrityError):
        await hr_zones_repo.save(user_id, zones, now=datetime.now(UTC))
