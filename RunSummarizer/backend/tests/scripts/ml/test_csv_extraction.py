import csv
from functools import partial

import pytest

from app.domain.models import ActivityRecord
from scripts.ml import csv_extraction
from tests.services.fakes import FakeDatabase, stored_run

pytestmark = pytest.mark.anyio


def database(*records: ActivityRecord) -> FakeDatabase:
    db = FakeDatabase()
    for record in records:
        db.activities[record.activity.key] = record
    return db


@pytest.fixture
def main_db(monkeypatch, tmp_path) -> FakeDatabase:
    """The database ``main`` reads; ``main`` writes its CSV into ``tmp_path``."""
    db = FakeDatabase()
    monkeypatch.setattr(
        csv_extraction,
        "load_activities",
        partial(csv_extraction.load_activities, transaction=db.transaction),
    )
    monkeypatch.chdir(tmp_path)
    return db


@pytest.mark.parametrize("stored_count", [4, 5], ids=["full-last-page", "short-last-page"])
async def test_loads_every_page_of_the_users_activities(stored_count):
    runs = [stored_run(activity_id) for activity_id in range(1, stored_count + 1)]
    db = database(*runs[:2], stored_run(99, user_id="user-2"), *runs[2:])

    activities = await csv_extraction.load_activities(
        "user-1", page_size=2, transaction=db.transaction
    )

    assert [activity.key for activity in activities] == [record.activity.key for record in runs]


async def test_an_unknown_user_has_no_activities():
    db = database(stored_run(1))

    assert await csv_extraction.load_activities("user-2", transaction=db.transaction) == []


async def test_main_exports_the_users_laps(main_db, monkeypatch, tmp_path):
    for record in (stored_run(1, laps=2), stored_run(2, laps=3), stored_run(3, user_id="user-2")):
        main_db.activities[record.activity.key] = record
    monkeypatch.setattr("sys.argv", ["csv_extraction", "--user-id", "user-1"])

    await csv_extraction.main()

    exported = (tmp_path / "treningi_do_etykietowania.csv").read_text(encoding="utf-8")
    rows = list(csv.DictReader(exported.splitlines()))
    assert [row["activity_id"] for row in rows] == ["strava_1"] * 2 + ["strava_2"] * 3


async def test_main_writes_to_the_out_path(main_db, monkeypatch, tmp_path):
    main_db.activities["strava_1"] = stored_run(1, laps=2)
    out = tmp_path / "laps" / "export.csv"
    out.parent.mkdir()
    monkeypatch.setattr("sys.argv", ["csv_extraction", "--user-id", "user-1", "--out", str(out)])

    await csv_extraction.main()

    assert out.exists()
    assert not (tmp_path / csv_extraction.DEFAULT_OUTPUT).exists()


async def test_main_requires_a_user_id(main_db, monkeypatch, tmp_path):
    main_db.activities["strava_1"] = stored_run(1)
    monkeypatch.setattr("sys.argv", ["csv_extraction"])

    with pytest.raises(SystemExit):
        await csv_extraction.main()

    assert list(tmp_path.iterdir()) == []
