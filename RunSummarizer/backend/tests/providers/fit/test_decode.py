"""decode_fit: reading a FIT activity file."""

import pytest

from app.providers.fit.decode import decode_fit
from app.providers.fit.errors import InvalidFitFileError
from tests.providers.fit.fit_builder import (
    START,
    activity_mesg,
    build_fit,
    lap_mesg,
    record_mesg,
    session_mesg,
)


def running_fit() -> bytes:
    return build_fit(
        sessions=(session_mesg(),),
        laps=(lap_mesg(total_distance=1000.0),),
        records=(record_mesg(0, heart_rate=140), record_mesg(1, heart_rate=141)),
        activity=activity_mesg(),
    )


def test_a_fit_file_decodes_into_its_messages():
    messages = decode_fit(running_fit())

    assert [session["sport"] for session in messages.sessions] == ["running"]
    assert messages.sessions[0]["start_time"] == START
    assert [lap["total_distance"] for lap in messages.laps] == [1000.0]
    assert [record["heart_rate"] for record in messages.records] == [140, 141]
    assert isinstance(messages.activity["local_timestamp"], int)


def test_a_file_without_an_activity_message_has_none():
    assert decode_fit(build_fit(sessions=(session_mesg(),))).activity is None


def test_a_failed_crc_check_raises():
    data = running_fit()
    corrupted = data[:-1] + bytes([data[-1] ^ 0xFF])
    with pytest.raises(InvalidFitFileError, match="CRC"):
        decode_fit(corrupted)


def test_a_file_that_isnt_fit_raises():
    with pytest.raises(InvalidFitFileError):
        decode_fit(b"<html>maintenance</html>")
