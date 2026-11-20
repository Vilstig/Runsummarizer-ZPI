from dataclasses import dataclass

from app.domain.enums import LapType
from app.domain.models import Lap
from app.summaries.formatting import (
    format_duration,
    format_pace,
    pace_s_per_km,
    round_to_nearest_100,
)
from app.summaries.params import LongIntervalParams, LongIntervalRep
from app.summaries.summarizers.base import Summarizer


@dataclass(frozen=True)
class LongIntervalDerived:
    distance_m: int  # all reps together, to the nearest 100 m
    duration_s: float  # all reps together
    pace_s_per_km: float
    rep_paces_s_per_km: tuple[float, ...]


def generate_params(laps: list[Lap]) -> LongIntervalParams | None:
    reps = tuple(
        LongIntervalRep(distance_m=lap.distance, duration_s=lap.duration)
        for lap in laps
        if lap.type == LapType.RUN
    )
    return LongIntervalParams(reps=reps) if reps else None


def derive(params: LongIntervalParams) -> LongIntervalDerived:
    distance_m = round_to_nearest_100(sum(rep.distance_m for rep in params.reps))
    duration_s = sum(rep.duration_s for rep in params.reps)
    return LongIntervalDerived(
        distance_m=distance_m,
        duration_s=duration_s,
        pace_s_per_km=pace_s_per_km(distance_m, duration_s),
        rep_paces_s_per_km=tuple(
            pace_s_per_km(rep.distance_m, rep.duration_s) for rep in params.reps
        ),
    )


def render(params: LongIntervalParams, derived: LongIntervalDerived) -> str:
    splits = "".join(
        f"Czas: {format_duration(rep.duration_s)}, "
        f"Dystans: {rep.distance_m:.1f}m, "
        f"Tempo: {format_pace(pace)}\n"
        for rep, pace in zip(params.reps, derived.rep_paces_s_per_km, strict=True)
    )
    return (
        "Zrobiłem:\n"
        f"Dystans: {derived.distance_m / 1000} km\n"
        f"Czas: {format_duration(derived.duration_s)}\n"
        f"Średnie tempo: {format_pace(derived.pace_s_per_km)}\n"
        "Międzyczasy:\n" + splits
    )


SUMMARIZER = Summarizer(generate_params, derive, render)
