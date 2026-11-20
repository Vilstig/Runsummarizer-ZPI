"""The running session of a FIT activity, its laps, samples and UTC offset."""

from datetime import timedelta

import pytest

from app.providers.fit.decode import FitMessages
from app.providers.fit.errors import InvalidFitFileError
from app.providers.fit.session import (
    running_session,
    session_laps,
    session_records,
    start_time,
    utc_offset,
)
from tests.providers.fit.fit_builder import END, START, activity_mesg, session_mesg


def messages(**fields) -> FitMessages:
    return FitMessages(**{"sessions": (), "laps": (), "records": (), "activity": None, **fields})


@pytest.mark.parametrize("sub_sport", ["generic", "treadmill", "track", "trail", "indoor_running"])
def test_every_running_sub_sport_is_a_running_session(sub_sport):
    session = session_mesg(sub_sport=sub_sport)
    assert running_session(messages(sessions=(session,))) is session


def test_the_first_running_session_is_taken():
    cycling = session_mesg(sport="cycling")
    running = session_mesg()
    assert running_session(messages(sessions=(cycling, running))) is running


def test_a_file_without_a_running_session_has_none():
    assert running_session(messages(sessions=(session_mesg(sport="cross_country_skiing"),))) is None


def test_a_session_without_a_start_time_raises():
    with pytest.raises(InvalidFitFileError):
        start_time({"sport": "running"})


def test_session_laps_are_the_ones_it_names():
    laps = tuple({"n": n} for n in range(4))
    session = session_mesg(first_lap_index=1, num_laps=2)
    assert session_laps(messages(laps=laps), session) == [{"n": 1}, {"n": 2}]


def test_a_session_naming_no_laps_has_them_all():
    laps = tuple({"n": n} for n in range(2))
    assert session_laps(messages(laps=laps), session_mesg()) == list(laps)


def test_session_records_run_to_the_next_session():
    later = session_mesg(start_time=END, timestamp=END, sport="cycling")
    inside = [{"timestamp": START}, {"timestamp": END - timedelta(seconds=1)}]
    outside = [{"timestamp": START - timedelta(seconds=1)}, {"timestamp": END}]
    untimed = [{"heart_rate": 140}]
    records = (outside[0], inside[0], *untimed, inside[1], outside[1])
    run = session_mesg()
    assert session_records(messages(sessions=(run, later), records=records), run) == inside


def test_the_last_session_records_run_to_the_end_of_the_file():
    run = session_mesg(timestamp=START)  # a device that writes the start time as timestamp
    records = tuple({"timestamp": START + timedelta(seconds=s)} for s in range(0, 7200, 600))
    assert session_records(messages(sessions=(run,), records=records), run) == list(records)


@pytest.mark.parametrize("offset", [7200, -18000, 19800, 0])
def test_utc_offset_is_local_minus_utc_time(offset):
    assert utc_offset(messages(activity=activity_mesg(offset))) == offset


def test_utc_offset_is_rounded_to_the_minute():
    activity = activity_mesg(3600)
    activity["local_timestamp"] += 2
    assert utc_offset(messages(activity=activity)) == 3600


def test_utc_offset_without_an_activity_message_is_zero():
    assert utc_offset(messages()) == 0
