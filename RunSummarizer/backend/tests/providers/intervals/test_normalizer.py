import base64
import gzip

import pytest

from app.domain.enums import Provider
from app.providers.intervals.normalizer import (
    PAYLOAD_FORMAT,
    PAYLOAD_KIND,
    build_payload,
    normalize_intervals_payload,
)
from tests.providers.fit.fit_builder import activity_mesg, build_fit, record_mesg, session_mesg
from tests.providers.intervals.fakes import intervals_activity


def running_fit(**session_fields) -> bytes:
    return build_fit(
        sessions=(
            session_mesg(
                total_distance=2000.0,
                total_timer_time=600.0,
                enhanced_avg_speed=3.333,
                avg_heart_rate=152,
                max_heart_rate=171,
                total_ascent=12,
                **session_fields,
            ),
        ),
        records=(record_mesg(0, distance=0.0, heart_rate=140, enhanced_speed=3.2),),
        activity=activity_mesg(7200),
    )


# ---------- build_payload ----------


def test_build_payload_gzip_compresses_and_base64_encodes_the_file():
    payload = build_payload(intervals_activity("i1"), file_source="original", file=b"FIT-BYTES")

    assert payload["format"] == PAYLOAD_FORMAT
    assert payload["file_source"] == "original"
    assert payload["activity"]["id"] == "i1"
    decoded = base64.b64decode(payload["file"])
    assert decoded == b"FIT-BYTES"


# ---------- normalize_intervals_payload ----------


def payload(
    activity: dict | None = None, *, file: bytes | None = None, gzipped: bool = False
) -> dict:
    raw = file if file is not None else running_fit()
    encoded = gzip.compress(raw) if gzipped else raw
    return {
        "format": PAYLOAD_FORMAT,
        "activity": activity if activity is not None else intervals_activity("i1"),
        "file_source": "original",
        "file": base64.b64encode(encoded).decode("ascii"),
    }


def test_a_running_payload_becomes_a_normalized_activity():
    activity = intervals_activity(
        "i1",
        name="Morning Run",
        start_date="2026-05-01T06:00:00Z",
        start_date_local="2026-05-01T08:00:00",
        timezone="Europe/Warsaw",
    )

    normalized = normalize_intervals_payload(payload(activity))

    assert normalized.activity.key == "intervals_i1"
    assert normalized.activity.source == Provider.INTERVALS
    assert normalized.activity.name == "Morning Run"
    assert normalized.activity.timezone == "Europe/Warsaw"
    assert normalized.activity.utc_offset == 7200
    assert normalized.payload_kind == PAYLOAD_KIND
    assert normalized.stored_payload == activity


def test_a_gzip_compressed_file_is_decompressed_first():
    normalized = normalize_intervals_payload(payload(gzipped=True))

    assert normalized is not None
    assert normalized.activity.key == "intervals_i1"


def test_a_file_without_a_running_session_is_no_normalized_activity():
    activity = normalize_intervals_payload(
        payload(file=running_fit(sport="cycling", sub_sport="road"))
    )

    assert activity is None


@pytest.mark.parametrize(
    ("start_date", "start_date_local", "expected_offset"),
    [
        ("2026-05-01T06:00:00Z", "2026-05-01T08:00:00", 7200),
        ("2026-05-01T06:00:00Z", "2026-05-01T06:00:00", 0),
        ("2026-05-01T06:00:00Z", "2026-05-01T01:00:00", -18000),
    ],
    ids=["ahead", "same", "behind"],
)
def test_the_utc_offset_comes_from_start_date_local_minus_start_date(
    start_date, start_date_local, expected_offset
):
    normalized = normalize_intervals_payload(
        payload(intervals_activity("i1", start_date=start_date, start_date_local=start_date_local))
    )

    assert normalized.activity.utc_offset == expected_offset


def test_a_missing_start_date_local_falls_back_to_the_fit_files_own_offset():
    activity = intervals_activity("i1")
    del activity["start_date_local"]

    normalized = normalize_intervals_payload(payload(activity))

    assert normalized.activity.utc_offset == 7200  # from activity_mesg(7200) in the FIT file


def test_an_unparseable_start_date_local_falls_back_to_the_fit_files_own_offset():
    normalized = normalize_intervals_payload(
        payload(intervals_activity("i1", start_date_local="not-a-date"))
    )

    assert normalized.activity.utc_offset == 7200
