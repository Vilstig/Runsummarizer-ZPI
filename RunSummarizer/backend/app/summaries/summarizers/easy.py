from dataclasses import dataclass

from app.domain.models import Lap
from app.summaries.formatting import format_pace, pace_s_per_km, segment_stats
from app.summaries.params import EasyParams
from app.summaries.summarizers.base import Summarizer


@dataclass(frozen=True)
class EasyDerived:
    pace_s_per_km: float


def generate_params(laps: list[Lap]) -> EasyParams:
    stats = segment_stats(laps)
    return EasyParams(
        distance_m=stats["distance"], duration_s=stats["duration"], avg_hr=stats["avg_hr"]
    )


def derive(params: EasyParams) -> EasyDerived:
    return EasyDerived(pace_s_per_km=pace_s_per_km(params.distance_m, params.duration_s))


def render(params: EasyParams, derived: EasyDerived) -> str:
    distance_km = params.distance_m / 1000
    return (
        f"{distance_km:.2f} km\n"
        f"Średnie tempo: {format_pace(derived.pace_s_per_km)}\n"
        f"Średnie tętno: {params.avg_hr}"
    )


SUMMARIZER = Summarizer(generate_params, derive, render)
