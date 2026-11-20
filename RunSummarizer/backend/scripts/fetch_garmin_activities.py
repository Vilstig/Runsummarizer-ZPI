"""Fetch Garmin runs with the Personal API key in GARMIN_API_KEY, decode their FIT files
and print what the integration makes of them, to check against Garmin Connect.

Run from backend/:
    python -m scripts.fetch_garmin_activities [--days 14] [--limit 3] [--all-types]
    python -m scripts.fetch_garmin_activities --activity-id 123456789

The downloaded ZIP and FIT file of each activity are saved under --out/<activity id>/.
"""

import argparse
import os
from datetime import date, timedelta
from pathlib import Path

import anyio
import httpx
from dotenv import load_dotenv

from app.domain.enums import StreamType
from app.domain.models import Activity
from app.providers.fit.decode import FitMessages, decode_fit
from app.providers.fit.errors import InvalidFitFileError
from app.providers.fit.session import (
    running_session,
    session_laps,
    session_records,
    start_time,
    sub_sport,
)
from app.providers.fit.streams import record_samples
from app.providers.garmin.archive import fit_from_zip
from app.providers.garmin.errors import GarminInvalidResponseError, GarminUnsupportedFileError
from app.providers.garmin.normalizer import normalize_garmin_activity, normalize_garmin_streams
from app.providers.garmin.personal_api.auth import PersonalApiKeyAuth
from app.providers.garmin.personal_api.client import GarminClient
from app.providers.garmin.personal_api.errors import GarminUnauthorizedError

API_KEY_ENV_VAR = "GARMIN_API_KEY"
CONNECT_ACTIVITY_URL = "https://connect.garmin.com/modern/activity/{activity_id}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--activity-id", type=int, help="fetch this activity only")
    parser.add_argument("--days", type=int, default=14, help="list activities this many days back")
    parser.add_argument("--limit", type=int, default=3, help="fetch at most this many activities")
    parser.add_argument(
        "--all-types",
        action="store_true",
        help="list activities of every type, not only Garmin's 'running' type",
    )
    parser.add_argument("--out", type=Path, default=Path("garmin-demo-output"))
    return parser.parse_args()


async def run(args: argparse.Namespace, api_key: str) -> int:
    async with GarminClient(PersonalApiKeyAuth(api_key)) as garmin:
        try:
            items = await list_items(garmin, args)
        except GarminUnauthorizedError:
            print(f"Garmin rejected the API key in {API_KEY_ENV_VAR}.")
            return 1

        print(f"{len(items)} activities\n")
        for item in items:
            activity_id = item["activityId"]
            try:
                await report(garmin, activity_id, item, args.out)
            except (
                httpx.HTTPError,
                GarminInvalidResponseError,
                GarminUnsupportedFileError,
                InvalidFitFileError,
            ) as exc:
                print(f"=== {activity_id}: failed: {type(exc).__name__}: {exc}\n")
    return 0


async def list_items(garmin: GarminClient, args: argparse.Namespace) -> list[dict]:
    if args.activity_id is not None:
        return [{"activityId": args.activity_id}]
    today = date.today()
    return await garmin.list_activities(
        today - timedelta(days=args.days),
        today,
        activity_type=None if args.all_types else "running",
        limit=args.limit,
    )


async def report(garmin: GarminClient, activity_id: int, item: dict, out: Path) -> None:
    content = await garmin.download_activity_file(activity_id)
    directory = out / str(activity_id)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "activity.zip").write_bytes(content)
    fit = fit_from_zip(content)
    (directory / f"{activity_id}.fit").write_bytes(fit)

    messages = decode_fit(fit)
    sports = ", ".join(
        f"{session.get('sport')}/{sub_sport(session)}" for session in messages.sessions
    )
    print(f"=== {activity_id} - {item.get('activityName') or '(no name)'}")
    print(f"Garmin type: {_type_key(item)}   FIT sessions: {sports or 'none'}")
    print(CONNECT_ACTIVITY_URL.format(activity_id=activity_id))
    print(f"Saved to {directory}")

    activity = normalize_garmin_activity(activity_id, messages, name=item.get("activityName"))
    if activity is None:
        print("skipped: no running session\n")
        return
    session = running_session(messages)
    print_summary(activity, session)
    print_laps(activity, session_laps(messages, session))
    print_streams(messages)
    print()


def print_summary(activity: Activity, session: dict) -> None:
    offset_h, offset_m = divmod(abs(activity.utc_offset) // 60, 60)
    sign = "-" if activity.utc_offset < 0 else "+"
    print(
        f"Start       {activity.start_time_local:%Y-%m-%d %H:%M:%S} "
        f"(UTC{sign}{offset_h:02d}:{offset_m:02d})   "
        f"{activity.start_time_utc:%Y-%m-%d %H:%M:%S} UTC"
    )
    print(f"Distance    {_km(activity.distance)}")
    print(
        f"Timer time  {_hms(activity.duration)}   Elapsed {_hms(session.get('total_elapsed_time'))}"
    )
    print(f"Pace        {_pace(activity.speed)}")
    print(f"HR          avg {_num(activity.avg_hr)}   max {_num(activity.max_hr)}")
    print(
        f"Ascent      {_num(activity.elevation_gain)} m   "
        f"Descent {_num(session.get('total_descent'))} m (not stored)"
    )


def print_laps(activity: Activity, lap_mesgs: list[dict]) -> None:
    """``activity``'s laps, with each lap's descent from ``lap_mesgs``, the FIT lap
    messages they were built from, in the same order.
    """
    print(f"\nLaps ({len(activity.laps)}); descent is read from the FIT file, not stored")
    print(
        f"  {'#':>3}  {'Distance':>9}  {'Time':>8}  {'Pace':>9}  {'Avg HR':>6}  {'Max HR':>6}"
        f"  {'Ascent':>7}  {'Descent':>7}"
    )
    for lap, lap_mesg in zip(activity.laps, lap_mesgs, strict=True):
        print(
            f"  {lap.index + 1:>3}  {_km(lap.distance):>9}  {_hms(lap.duration):>8}  "
            f"{_pace(lap.speed):>9}  {_num(lap.avg_hr):>6}  {_num(lap.max_hr):>6}  "
            f"{_metres(lap.elevation_gain):>7}  {_metres(lap_mesg.get('total_descent')):>7}"
        )


def print_streams(messages: FitMessages) -> None:
    session = running_session(messages)
    raw = record_samples(session_records(messages, session), start=start_time(session))
    streams = normalize_garmin_streams(messages)
    times = streams.get(StreamType.TIME, [])
    span = f", {_hms(times[0])} to {_hms(times[-1])}" if times else ""
    print(f"\nStreams ({len(times)} samples{span})")
    for stream_type in StreamType:
        if stream_type not in streams:
            print(f"  {stream_type:<10} missing")
            continue
        gaps = raw[stream_type].count(None)
        share = gaps / len(times) if times else 0
        print(f"  {stream_type:<10} {len(streams[stream_type]):>6}   {gaps} filled ({share:.1%})")


def _type_key(item: dict) -> str:
    activity_type = item.get("activityType")
    if isinstance(activity_type, dict):
        return activity_type.get("typeKey", "?")
    return activity_type or "?"


def _km(metres: float | None) -> str:
    return "-" if metres is None else f"{metres / 1000:.2f} km"


def _hms(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    minutes, secs = divmod(round(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"


def _pace(speed: float | None) -> str:
    """Minutes and seconds per km at ``speed`` (m/s)."""
    if not speed:
        return "-"
    minutes, secs = divmod(round(1000 / speed), 60)
    return f"{minutes}:{secs:02d} /km"


def _num(value: float | None) -> str:
    return "-" if value is None else f"{value:g}"


def _metres(value: float | None) -> str:
    return "-" if value is None else f"{value:g} m"


def main() -> int:
    load_dotenv()
    args = parse_args()
    api_key = os.getenv(API_KEY_ENV_VAR)
    if not api_key:
        print(f"Set {API_KEY_ENV_VAR} to a Garmin Personal API key, e.g. in backend/.env.")
        return 1
    return anyio.run(run, args, api_key)


if __name__ == "__main__":
    raise SystemExit(main())
