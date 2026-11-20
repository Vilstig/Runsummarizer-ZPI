from dataclasses import dataclass

from app.domain.models import Lap
from app.summaries.formatting import format_duration, format_pace, pace_s_per_km
from app.summaries.params import TimeIntervalParams
from app.summaries.reps import merged_reps_and_recoveries
from app.summaries.summarizers.base import Summarizer


@dataclass(frozen=True)
class TimeIntervalDerived:
    avg_rep_pace_s_per_km: float


def generate_params(laps: list[Lap]) -> TimeIntervalParams | None:
    reps, recoveries = merged_reps_and_recoveries(laps)
    if not reps:
        return None
    rep_distances = [rep.distance for rep in reps]
    return TimeIntervalParams(
        rep_count=len(reps),
        avg_rep_s=sum(rep.duration for rep in reps) / len(reps),
        avg_recovery_s=(
            sum(recovery.duration for recovery in recoveries) / len(recoveries) if recoveries else 0
        ),
        avg_rep_distance_m=sum(rep_distances) / len(reps),
        longest_rep_m=max(rep_distances),
        shortest_rep_m=min(rep_distances),
    )


def derive(params: TimeIntervalParams) -> TimeIntervalDerived:
    return TimeIntervalDerived(
        avg_rep_pace_s_per_km=pace_s_per_km(params.avg_rep_distance_m, params.avg_rep_s)
    )


def render(params: TimeIntervalParams, derived: TimeIntervalDerived) -> str:
    return (
        f"{params.rep_count}x{format_duration(params.avg_rep_s)}"
        f"/{format_duration(params.avg_recovery_s)}\n"
        f"Średnie tempo interwału: {format_pace(derived.avg_rep_pace_s_per_km)}\n"
        f"Najdłuższy interwał: {params.longest_rep_m:.1f}m\n"
        f"Najkrótszy interwał: {params.shortest_rep_m:.1f}m"
    )


SUMMARIZER = Summarizer(generate_params, derive, render)
