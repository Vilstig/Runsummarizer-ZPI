"""A segment's figures, from the params its part of the summary is written from."""

from app.domain.models import SegmentStats
from app.summaries.params import (
    EasyParams,
    LongIntervalParams,
    RaceParams,
    SegmentParams,
    ShortIntervalParams,
    TimeIntervalParams,
)
from app.summaries.summarizers import easy, long_intervals, race, short_intervals, time_intervals


def stats_from_params(params: SegmentParams | None) -> SegmentStats:
    """The figures of a segment summarized from ``params``; none for a break or a segment
    with nothing to summarize (None). Long intervals have no rep figures: their reps are
    single RUN laps."""
    match params:
        case EasyParams():
            return _steady_stats(params, easy.derive(params).pace_s_per_km)
        case RaceParams():
            return _steady_stats(params, race.derive(params).pace_s_per_km)
        case ShortIntervalParams():
            derived = short_intervals.derive(params)
            return SegmentStats(
                distance=float(derived.distance_m),
                duration=params.rep_count * params.avg_rep_s,
                pace=_nonzero(derived.avg_rep_pace_s_per_km),
                rep_count=params.rep_count,
                rep_distance=float(params.rep_distance_m),
                avg_rep_duration=params.avg_rep_s,
                avg_recovery=_nonzero(params.avg_recovery_s),
            )
        case TimeIntervalParams():
            return SegmentStats(
                distance=params.rep_count * params.avg_rep_distance_m,
                duration=params.rep_count * params.avg_rep_s,
                pace=_nonzero(time_intervals.derive(params).avg_rep_pace_s_per_km),
                rep_count=params.rep_count,
                rep_distance=params.avg_rep_distance_m,
                avg_rep_duration=params.avg_rep_s,
                avg_recovery=_nonzero(params.avg_recovery_s),
            )
        case LongIntervalParams():
            derived = long_intervals.derive(params)
            return SegmentStats(
                distance=float(derived.distance_m),
                duration=derived.duration_s,
                pace=_nonzero(derived.pace_s_per_km),
            )
        case _:
            return SegmentStats()


def _steady_stats(params: EasyParams | RaceParams, pace: float) -> SegmentStats:
    return SegmentStats(
        distance=params.distance_m,
        duration=params.duration_s,
        avg_hr=_nonzero(params.avg_hr),
        pace=_nonzero(pace),
    )


def _nonzero(value: float) -> float | None:
    """``value``; None for 0, which the params hold for a figure the laps don't give
    (no heart rate, no distance, no recovery laps)."""
    return float(value) if value else None
