from dataclasses import dataclass
from math import isclose

from app.domain.models import Lap
from app.summaries.formatting import format_duration, format_pace, pace_s_per_km, segment_stats
from app.summaries.params import RaceParams
from app.summaries.summarizers.base import Summarizer

RACE_DISTANCES_KM = (0.8, 1.5, 3, 5, 10, 21.1, 42.2)
RACE_DISTANCE_TOLERANCE = 0.03  # max relative difference to a race distance to snap to it


@dataclass(frozen=True)
class RaceDerived:
    pace_s_per_km: float


def generate_params(laps: list[Lap]) -> RaceParams:
    stats = segment_stats(laps)
    return RaceParams(
        distance_m=_race_distance_km(stats["distance_km"]) * 1000,
        duration_s=stats["duration"],
        avg_hr=stats["avg_hr"],
    )


def derive(params: RaceParams) -> RaceDerived:
    return RaceDerived(pace_s_per_km=pace_s_per_km(params.distance_m, params.duration_s))


def render(params: RaceParams, derived: RaceDerived) -> str:
    return (
        f"{_format_distance_km(params.distance_m)} km\n"
        f"Czas: {format_duration(params.duration_s)}\n"
        f"Średnie tempo: {format_pace(derived.pace_s_per_km)}\n"
        f"Średnie tętno: {params.avg_hr}"
    )


def _race_distance_km(distance_km: float) -> float:
    for race_km in RACE_DISTANCES_KM:
        if abs(distance_km - race_km) < RACE_DISTANCE_TOLERANCE * race_km:
            return race_km
    return round(distance_km, 1)


def _format_distance_km(distance_m: float) -> str:
    """A race distance as written in ``RACE_DISTANCES_KM`` (``5``, ``21.1``), any other
    distance to 0.1 km (``7.0``)."""
    distance_km = distance_m / 1000
    if any(isclose(distance_km, race_km) for race_km in RACE_DISTANCES_KM):
        return f"{distance_km:g}"
    return f"{distance_km:.1f}"


SUMMARIZER = Summarizer(generate_params, derive, render)
