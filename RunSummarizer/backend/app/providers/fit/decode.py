from dataclasses import dataclass

from garmin_fit_sdk import Decoder, Stream

from app.providers.fit.errors import InvalidFitFileError


@dataclass(frozen=True)
class FitMessages:
    """The messages of a FIT activity file that an activity is built from.

    Each message is ``{field name: value}`` as ``garmin_fit_sdk`` decodes it: scaled
    values, timestamps as timezone-aware UTC datetimes, enum values as strings, and
    ``local_timestamp`` as seconds since ``garmin_fit_sdk.FIT_EPOCH_S``. Fields the
    device didn't record are left out.
    """

    sessions: tuple[dict, ...]
    laps: tuple[dict, ...]
    records: tuple[dict, ...]  # samples, in time order
    activity: dict | None  # None when the file has no activity message
    file_id: dict | None = None  # None when the file has no file_id message
    devices: tuple[dict, ...] = ()  # device_info messages


def decode_fit(data: bytes) -> FitMessages:
    """The messages of the FIT file ``data``.

    Raises ``InvalidFitFileError`` when ``data`` isn't a FIT file, fails its CRC check or
    can't be decoded.
    """
    try:
        messages, errors = Decoder(Stream.from_byte_array(data)).read()
    except Exception as exc:
        raise InvalidFitFileError(f"The FIT file could not be decoded: {exc}") from exc
    if errors:
        raise InvalidFitFileError(f"The FIT file could not be decoded: {errors[0]}")

    activities = messages.get("activity_mesgs", [])
    file_ids = messages.get("file_id_mesgs", [])
    return FitMessages(
        sessions=tuple(messages.get("session_mesgs", [])),
        laps=tuple(messages.get("lap_mesgs", [])),
        records=tuple(messages.get("record_mesgs", [])),
        activity=activities[0] if activities else None,
        file_id=file_ids[0] if file_ids else None,
        devices=tuple(messages.get("device_info_mesgs", [])),
    )
