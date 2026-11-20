import pytest

from app.summaries.formatting import format_duration, format_pace, whole_seconds


@pytest.mark.parametrize(
    ("seconds", "whole"),
    [(292.49, 292), (292.5, 293), (292.68, 293), (293.5, 294), (0.0, 0)],
)
def test_seconds_round_to_the_nearest_whole_second_with_halves_up(seconds, whole):
    assert whole_seconds(seconds) == whole


@pytest.mark.parametrize(
    ("seconds_per_km", "pace"),
    [(292.68, "4:53 /km"), (299.6, "5:00 /km"), (59.5, "1:00 /km"), (0.0, "0:00 /km")],
)
def test_a_pace_is_written_to_the_nearest_second(seconds_per_km, pace):
    assert format_pace(seconds_per_km) == pace


@pytest.mark.parametrize(
    ("seconds", "text"),
    [
        (0, "0:00"),
        (45, "0:45"),
        (59.5, "1:00"),
        (303, "5:03"),
        (3599.4, "59:59"),
        (3600, "1:00:00"),
        (3605, "1:00:05"),
        (3725.4, "1:02:05"),
        (36000, "10:00:00"),
    ],
)
def test_a_duration_is_written_as_hours_minutes_and_seconds(seconds, text):
    assert format_duration(seconds) == text


@pytest.mark.parametrize(
    ("seconds", "text"),
    [(78.46, "1:18.5"), (5.04, "0:05.0"), (59.96, "1:00.0"), (3600.25, "1:00:00.3")],
)
def test_a_duration_keeps_the_decimals_asked_for(seconds, text):
    assert format_duration(seconds, decimals=1) == text
