"""
Translates FIT record messages into the app's streams.

Normalized streams: { StreamType: samples }, the samples aligned by index; a stream the
activity lacks is left out.
"""

from collections.abc import Sequence
from datetime import datetime

from app.domain.enums import StreamType

# The record field each stream is read from. The decoder fills enhanced_speed and
# enhanced_altitude from speed and altitude, so they hold the value whichever one the
# device wrote.
RECORD_FIELDS = {
    StreamType.DISTANCE: "distance",
    StreamType.HEARTRATE: "heart_rate",
    StreamType.VELOCITY: "enhanced_speed",
    StreamType.ALTITUDE: "enhanced_altitude",
}


def record_samples(records: Sequence[dict], *, start: datetime) -> dict:
    """``{StreamType: samples}`` of the timestamped ``records``, None where a record lacks
    the stream's field. Time is whole seconds since ``start``.
    """
    records = [record for record in records if record.get("timestamp") is not None]
    if not records:
        return {}
    samples: dict = {
        StreamType.TIME: [round((r["timestamp"] - start).total_seconds()) for r in records]
    }
    for stream_type, field in RECORD_FIELDS.items():
        samples[stream_type] = [record.get(field) for record in records]
    return samples


def normalize_streams(records: Sequence[dict], *, start: datetime) -> dict:
    """The normalized streams of ``records``, time counted from ``start``.

    A stream no record has is left out; in the others, a missing sample takes the value
    of the sample before it, or of the first sample when none comes before it.
    """
    streams = {}
    for stream_type, samples in record_samples(records, start=start).items():
        filled = fill_gaps(samples)
        if filled is not None:
            streams[stream_type] = filled
    return streams


def fill_gaps(samples: Sequence[float | None]) -> list[float] | None:
    """``samples`` with each None replaced by the sample before it, and leading Nones by
    the first sample that isn't None; None when every sample is None.
    """
    first = next((sample for sample in samples if sample is not None), None)
    if first is None:
        return None
    filled = []
    last = first
    for sample in samples:
        if sample is not None:
            last = sample
        filled.append(last)
    return filled
