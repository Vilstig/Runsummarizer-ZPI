from dataclasses import dataclass

from app.domain.models import Lap
from app.summaries.formatting import format_duration, pace_s_per_km, round_to_nearest_50
from app.summaries.params import ShortIntervalParams
from app.summaries.reps import merged_reps_and_recoveries
from app.summaries.summarizers.base import Summarizer


@dataclass(frozen=True)
class ShortIntervalDerived:
    distance_m: float  # all reps together
    avg_rep_pace_s_per_km: float


def generate_params(laps: list[Lap]) -> ShortIntervalParams | None:
    reps, recoveries = merged_reps_and_recoveries(laps)
    if not reps:
        return None
    rep_times = [rep.duration for rep in reps]
    return ShortIntervalParams(
        rep_count=len(reps),
        rep_distance_m=round_to_nearest_50(sum(rep.distance for rep in reps) / len(reps)),
        avg_rep_s=sum(rep_times) / len(reps),
        avg_recovery_s=(
            sum(recovery.duration for recovery in recoveries) / len(recoveries) if recoveries else 0
        ),
        fastest_rep_s=min(rep_times),
        slowest_rep_s=max(rep_times),
    )


def derive(params: ShortIntervalParams) -> ShortIntervalDerived:
    return ShortIntervalDerived(
        distance_m=params.rep_count * params.rep_distance_m,
        avg_rep_pace_s_per_km=pace_s_per_km(params.rep_distance_m, params.avg_rep_s),
    )


def render(params: ShortIntervalParams, _derived: ShortIntervalDerived) -> str:
    return (
        f"{params.rep_count}x{params.rep_distance_m}m\n"
        f"Średni czas interwału: {format_duration(params.avg_rep_s, decimals=1)}\n"
        f"Średni czas przerwy: {format_duration(params.avg_recovery_s)}\n"
        f"Najszybszy odcinek: {format_duration(params.fastest_rep_s, decimals=1)}\n"
        f"Najwolniejszy odcinek: {format_duration(params.slowest_rep_s, decimals=1)}"
    )


SUMMARIZER = Summarizer(generate_params, derive, render)
