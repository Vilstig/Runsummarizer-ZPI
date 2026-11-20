from app.domain.enums import RunType, SegmentRole
from app.domain.models import Activity, Summary
from app.summaries.params import SegmentSummary
from app.summaries.renderer import summary_text
from app.summaries.segment_params import REST_OR_RECOVERY, segment_params
from app.summaries.segmentation import RunSegment, run_segments


def summarize(activity: Activity) -> Summary:
    """The activity's summary, from its stored segments, or from segments worked out from
    its lap types when it has none."""
    segments = _segment_summaries(_run_segments(activity))
    return Summary(text=summary_text(segments))


def _run_segments(activity: Activity) -> list[RunSegment]:
    if not activity.segments:
        return run_segments(activity)
    segments = [RunSegment.from_segment(segment, activity.laps) for segment in activity.segments]
    return [segment for segment in segments if segment.laps]


def _segment_summaries(segments: list[RunSegment]) -> tuple[SegmentSummary, ...]:
    """The params of each segment that has something to summarize. Trailing segments of
    only REST and RECOVERY laps are left out."""
    summaries = (_segment_summary(segment) for segment in _drop_trailing_rest_recovery(segments))
    return tuple(summary for summary in summaries if summary is not None)


def _segment_summary(segment: RunSegment) -> SegmentSummary | None:
    params = segment_params(segment.laps, segment.role, segment.run_type)
    if params is None:
        return None
    is_break = segment.role == SegmentRole.BREAK
    return SegmentSummary(
        start_lap_index=segment.start_lap_index,
        end_lap_index=segment.end_lap_index,
        role=segment.role,
        run_type=None if is_break else segment.run_type or RunType.EASY,
        label=None if is_break else segment.label,
        params=params,
    )


def _is_rest_or_recovery_only(segment: RunSegment) -> bool:
    return all(lap.type in REST_OR_RECOVERY for lap in segment.laps)


def _drop_trailing_rest_recovery(segments: list[RunSegment]) -> list[RunSegment]:
    end = len(segments)
    while end > 0 and _is_rest_or_recovery_only(segments[end - 1]):
        end -= 1
    return segments[:end]
