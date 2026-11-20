"""Builds FIT activity files in memory with ``garmin_fit_sdk``'s encoder."""

import io
import zipfile
from datetime import UTC, datetime, timedelta

from garmin_fit_sdk import FIT_EPOCH_S, Encoder, Profile

START = datetime(2026, 5, 1, 6, 0, tzinfo=UTC)
END = START + timedelta(hours=1)
MESG_NUM = Profile["mesg_num"]


def record_mesg(seconds: int, **fields) -> dict:
    """A record message ``seconds`` after ``START``."""
    return {"timestamp": START + timedelta(seconds=seconds), **fields}


def lap_mesg(start_s: int = 0, **fields) -> dict:
    """A lap message starting ``start_s`` after ``START``."""
    return {
        "timestamp": START + timedelta(seconds=start_s + 300),
        "start_time": START + timedelta(seconds=start_s),
        **fields,
    }


def session_mesg(**fields) -> dict:
    """A running session from ``START`` to ``END``."""
    return {
        "timestamp": END,
        "start_time": START,
        "sport": "running",
        "sub_sport": "generic",
        **fields,
    }


def activity_mesg(utc_offset_s: int = 7200) -> dict:
    """An activity message ending at ``END``, recorded ``utc_offset_s`` east of UTC."""
    return {
        "timestamp": END,
        "local_timestamp": int(END.timestamp()) - FIT_EPOCH_S + utc_offset_s,
        "num_sessions": 1,
    }


def build_fit(
    *,
    sessions: tuple[dict, ...] = (),
    laps: tuple[dict, ...] = (),
    records: tuple[dict, ...] = (),
    activity: dict | None = None,
    file_id: dict | None = None,
    devices: tuple[dict, ...] = (),
) -> bytes:
    """A FIT activity file holding the messages, records first, as devices write them.

    ``file_id`` adds fields to the file_id message; ``devices`` are device_info messages.
    """
    encoder = Encoder()
    encoder.write_mesg(
        {
            "mesg_num": MESG_NUM["FILE_ID"],
            "type": "activity",
            "manufacturer": "garmin",
            "product": 1,
            "time_created": START,
            "serial_number": 1,
            **(file_id or {}),
        }
    )
    for device in devices:
        encoder.write_mesg({"mesg_num": MESG_NUM["DEVICE_INFO"], "timestamp": START, **device})
    for name, messages in (("RECORD", records), ("LAP", laps), ("SESSION", sessions)):
        for message in messages:
            encoder.write_mesg({"mesg_num": MESG_NUM[name], **message})
    if activity is not None:
        encoder.write_mesg({"mesg_num": MESG_NUM["ACTIVITY"], **activity})
    return bytes(encoder.close())


def running_fit(*, file_id: dict | None = None, **session_fields) -> bytes:
    """A FIT file of a 2 km run in two laps, with heart rate and speed samples."""
    return build_fit(
        sessions=(
            session_mesg(
                total_distance=2000.0,
                total_timer_time=600.0,
                total_elapsed_time=630.0,
                enhanced_avg_speed=3.333,
                avg_heart_rate=152,
                max_heart_rate=171,
                total_ascent=12,
                first_lap_index=0,
                num_laps=2,
                **session_fields,
            ),
        ),
        laps=(
            lap_mesg(0, total_distance=1000.0, total_timer_time=290.0, avg_heart_rate=148),
            lap_mesg(300, total_distance=1000.0, total_timer_time=310.0, avg_heart_rate=156),
        ),
        records=(
            record_mesg(0, distance=0.0, heart_rate=140, enhanced_speed=3.2),
            record_mesg(1, distance=3.2, enhanced_speed=3.3),
        ),
        activity=activity_mesg(7200),
        file_id=file_id,
    )


def build_zip(files: dict[str, bytes]) -> bytes:
    """A ZIP holding ``files``, ``{name: content}``."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()
