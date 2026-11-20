from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from statistics import median

from app.config.loader import CONFIG
from app.domain.enums import LapType, RunType, SegmentRole
from app.domain.models import (
    Activity,
    Lap,
    Segment,
    UserSegment,
    ZoneBounds,
    ZoneTimes,
)
from app.summaries.classification import (
    classify_segment,
    dominant_run_type,
    segment_zone_times,
)
from app.summaries.hr_zones import default_zone_bounds, hr_zone
from app.summaries.reps import are_interval_reps, run_stretches
from app.summaries.segment_params import segment_params
from app.summaries.stats import stats_from_params
from app.summaries.user_segments import user_segment_laps, user_segment_run_type

MIN_STEADY_BLOCK_SECONDS = 480
MIN_STEADY_BLOCK_LAPS = 2

WARM_UP_LABEL = "Rozgrzewka"
COOL_DOWN_LABEL = "Schłodzenie"


@dataclass
class RunSegment:
    laps: list[Lap]
    start_lap_index: int
    end_lap_index: int
    role: SegmentRole = SegmentRole.WORK
    run_type: RunType | None = None
    label: str | None = None

    @classmethod
    def from_segment(cls, segment: Segment, laps: list[Lap]) -> RunSegment:
        """The working form of a stored segment, over its laps among ``laps``."""
        return cls(
            laps=[
                lap for lap in laps if segment.start_lap_index <= lap.index <= segment.end_lap_index
            ],
            start_lap_index=segment.start_lap_index,
            end_lap_index=segment.end_lap_index,
            role=segment.role,
            run_type=segment.run_type,
            label=segment.label,
        )

    def to_segment(self) -> Segment:
        """The stored form of the segment, with its figures from its summary params."""
        return Segment(
            start_lap_index=self.start_lap_index,
            end_lap_index=self.end_lap_index,
            role=self.role,
            run_type=self.run_type or RunType.EASY,
            label=self.label,
            stats=stats_from_params(segment_params(self.laps, self.role, self.run_type)),
        )


class GapPosition(Enum):
    """Where a stretch of laps outside every work span sits in the activity."""

    LEADING = "leading"  # before the first work span
    BETWEEN = "between"  # between two work spans
    TRAILING = "trailing"  # after the last work span
    WHOLE_RUN = "whole_run"  # the activity has no work span


def _config_float(key: str, default: float) -> float:
    value = CONFIG.get(key, default)
    return float(value)


def _warmup_pace_ratio() -> float:
    return _config_float("WARMUP_PACE_RATIO", 0.88)


class SegmentSplitter:
    def __init__(self, *, warmup_pace_ratio: float | None = None):
        # A lap slower than reference pace * this ratio is not part of a rep
        self.warmup_pace_ratio = (
            warmup_pace_ratio if warmup_pace_ratio is not None else _warmup_pace_ratio()
        )

    def split(self, laps: list[Lap]) -> list[RunSegment]:
        if not laps:
            return []

        work_spans = self._find_work_spans(laps)
        if not work_spans:
            return self._segments_from_gap(laps, GapPosition.WHOLE_RUN)

        segments: list[RunSegment] = []
        cursor = 0
        for start, end in work_spans:
            if cursor < start:
                position = GapPosition.LEADING if cursor == 0 else GapPosition.BETWEEN
                segments.extend(self._segments_from_gap(laps[cursor:start], position))

            segments.append(_segment(laps[start : end + 1], role=SegmentRole.WORK))
            cursor = end + 1

        if cursor < len(laps):
            segments.extend(self._segments_from_gap(laps[cursor:], GapPosition.TRAILING))

        return segments

    def _segments_from_gap(self, gap_laps: list[Lap], position: GapPosition) -> list[RunSegment]:
        segments: list[RunSegment] = []
        for group in _group_by_rest(gap_laps):
            if group[0].type == LapType.REST:
                segments.append(_segment(group, role=SegmentRole.BREAK))
            elif position == GapPosition.LEADING:
                segments.append(_segment(group, role=SegmentRole.PREAMBLE, label=WARM_UP_LABEL))
            elif position == GapPosition.TRAILING:
                segments.append(_segment(group, role=SegmentRole.EPILOGUE, label=COOL_DOWN_LABEL))
            else:
                segments.append(_segment(group, role=SegmentRole.WORK))
        return segments

    def _find_work_spans(self, laps: list[Lap]) -> list[tuple[int, int]]:
        interval_spans = self._find_interval_spans(laps)
        steady_spans = _find_steady_spans(laps, interval_spans)
        return sorted(interval_spans + steady_spans)

    def _find_interval_spans(self, laps: list[Lap]) -> list[tuple[int, int]]:
        spans: list[tuple[int, int]] = []
        for block_start, block_end in _run_recovery_blocks(laps):
            span = self._interval_span_in_block(laps, block_start, block_end)
            if span:
                spans.append(span)
        return spans

    def _interval_span_in_block(
        self, laps: list[Lap], block_start: int, block_end: int
    ) -> tuple[int, int] | None:
        stretches = [
            (block_start + first, block_start + last)
            for first, last in run_stretches(laps[block_start : block_end + 1])
        ]
        stretches = self._trim_edge_reps(laps, stretches, block_start, block_end)
        if not are_interval_reps([laps[first : last + 1] for first, last in stretches]):
            return None

        span_start = stretches[0][0]
        span_end = stretches[-1][1]
        while span_end < block_end and laps[span_end + 1].type == LapType.RECOVERY:
            span_end += 1
        return (span_start, span_end)

    def _trim_edge_reps(
        self,
        laps: list[Lap],
        stretches: list[tuple[int, int]],
        block_start: int,
        block_end: int,
    ) -> list[tuple[int, int]]:
        """Drop the slow laps from the outer ends of the first and last rep.

        The first and last RUN stretch of a block can include slow warm-up or cool-down
        running.
        Reference pace is the median of the RUN laps next to a recovery lap.
        """
        anchor_speeds = [
            laps[i].speed
            for i in range(block_start, block_end + 1)
            if laps[i].type == LapType.RUN
            and laps[i].speed
            and _touches_recovery(laps, i, block_start, block_end)
        ]
        if not anchor_speeds:
            return stretches

        min_speed = median(anchor_speeds) * self.warmup_pace_ratio
        stretches = list(stretches)

        while stretches:
            first, last = stretches[0]
            kept_first = last + 1
            while kept_first > first and (laps[kept_first - 1].speed or 0) >= min_speed:
                kept_first -= 1
            if kept_first <= last:
                stretches[0] = (kept_first, last)
                break
            stretches.pop(0)

        while stretches:
            first, last = stretches[-1]
            kept_last = first - 1
            while kept_last < last and (laps[kept_last + 1].speed or 0) >= min_speed:
                kept_last += 1
            if kept_last >= first:
                stretches[-1] = (first, kept_last)
                break
            stretches.pop()

        return stretches


def _segment(
    laps: list[Lap],
    *,
    role: SegmentRole,
    run_type: RunType | None = None,
    label: str | None = None,
) -> RunSegment:
    return RunSegment(
        laps=laps,
        start_lap_index=laps[0].index,
        end_lap_index=laps[-1].index,
        role=role,
        run_type=run_type,
        label=label,
    )


def _touches_recovery(laps: list[Lap], index: int, block_start: int, block_end: int) -> bool:
    return any(
        block_start <= neighbour <= block_end and laps[neighbour].type == LapType.RECOVERY
        for neighbour in (index - 1, index + 1)
    )


def _run_recovery_blocks(laps: list[Lap]) -> list[tuple[int, int]]:
    """Inclusive index ranges of consecutive RUN and RECOVERY laps."""
    blocks: list[tuple[int, int]] = []
    first: int | None = None
    for i, lap in enumerate(laps):
        if lap.type in (LapType.RUN, LapType.RECOVERY):
            if first is None:
                first = i
        elif first is not None:
            blocks.append((first, i - 1))
            first = None
    if first is not None:
        blocks.append((first, len(laps) - 1))
    return blocks


def _non_rest_parts(laps: list[Lap]) -> list[tuple[int, int]]:
    """Inclusive index ranges of the laps between REST laps."""
    parts: list[tuple[int, int]] = []
    first: int | None = None
    for i, lap in enumerate(laps):
        if lap.type == LapType.REST:
            if first is not None:
                parts.append((first, i - 1))
                first = None
        elif first is None:
            first = i
    if first is not None:
        parts.append((first, len(laps) - 1))
    return parts


def _find_steady_spans(
    laps: list[Lap], interval_spans: list[tuple[int, int]]
) -> list[tuple[int, int]]:
    """RUN stretches that are long enough to be work, in parts that hold no interval span."""
    spans: list[tuple[int, int]] = []
    for part_start, part_end in _non_rest_parts(laps):
        if any(part_start <= start and end <= part_end for start, end in interval_spans):
            continue
        for first, last in run_stretches(laps[part_start : part_end + 1]):
            span = (part_start + first, part_start + last)
            if _is_steady_work_block(laps[span[0] : span[1] + 1]):
                spans.append(span)
    return spans


def _is_steady_work_block(run_laps: list[Lap]) -> bool:
    duration = sum(lap.duration or 0 for lap in run_laps)
    return len(run_laps) >= MIN_STEADY_BLOCK_LAPS and duration >= MIN_STEADY_BLOCK_SECONDS


def _median_speed(laps: list[Lap]) -> float:
    speeds = [lap.speed or 0 for lap in laps if (lap.speed or 0) > 0]
    return median(speeds) if speeds else 0


def _group_by_rest(laps: list[Lap]) -> list[list[Lap]]:
    """Split laps into contiguous runs of REST vs non-REST."""
    if not laps:
        return []

    groups: list[list[Lap]] = []
    current = [laps[0]]
    current_is_rest = laps[0].type == LapType.REST

    for lap in laps[1:]:
        is_rest = lap.type == LapType.REST
        if is_rest == current_is_rest:
            current.append(lap)
        else:
            groups.append(current)
            current = [lap]
            current_is_rest = is_rest

    groups.append(current)
    return groups


def classify_segments(
    segments: list[RunSegment], zone_times: ZoneTimes, zone_bounds: ZoneBounds
) -> list[RunSegment]:
    """Type and label ``segments``: a break has no run type, an easy lead-in or cool-down
    is easy, and every other segment is work, classified by ``segment_zone_times``."""
    work_run_laps = [
        lap
        for seg in segments
        if seg.role == SegmentRole.WORK
        for lap in seg.laps
        if lap.type == LapType.RUN
    ]
    work_speed = _median_speed(work_run_laps)
    work_zone = _median_hr_zone(work_run_laps, zone_bounds)
    warmup_pace_ratio = _warmup_pace_ratio()

    work_segments: list[RunSegment] = []
    for segment in segments:
        is_lead_in_or_cool_down = segment.role in (SegmentRole.PREAMBLE, SegmentRole.EPILOGUE)
        if segment.role == SegmentRole.BREAK:
            segment.run_type = None
            segment.label = None
        elif is_lead_in_or_cool_down and _is_easy_lead_in_or_cool_down(
            segment.laps, work_speed, work_zone, warmup_pace_ratio, zone_bounds
        ):
            segment.run_type = RunType.EASY
        else:
            work_segments.append(segment)

    for segment in work_segments:
        segment_duration = sum(lap.duration or 0 for lap in segment.laps)
        segment_zones = segment_zone_times(
            segment.laps, zone_times, zone_bounds, work_segments=len(work_segments)
        )
        segment.run_type = classify_segment(segment.laps, segment_zones, segment_duration)
        if segment.role in (SegmentRole.PREAMBLE, SegmentRole.EPILOGUE):
            segment.role = SegmentRole.WORK
            segment.label = None
        else:
            segment.label = _work_label(segment.run_type)

    return segments


def _default_zone_bounds() -> ZoneBounds:
    return default_zone_bounds(_config_float("MAX_HR", 200))


def _zone_bounds(activity: Activity) -> ZoneBounds:
    """The bounds the activity's zone times are counted in, or the default ones."""
    return activity.zone_bounds if activity.zone_bounds is not None else _default_zone_bounds()


def _median_hr_zone(laps: list[Lap], bounds: ZoneBounds) -> int | None:
    """HR zone of the median average heart rate of the RUN laps, None without heart-rate data."""
    heart_rates = [lap.avg_hr for lap in laps if lap.type == LapType.RUN and lap.avg_hr]
    if not heart_rates:
        return None
    return hr_zone(median(heart_rates), bounds)


def _is_easy_lead_in_or_cool_down(
    laps: list[Lap],
    work_speed: float,
    work_zone: int | None,
    warmup_pace_ratio: float,
    bounds: ZoneBounds,
) -> bool:
    """Whether laps before or after the work are easy: slower than the work pace and, when
    heart-rate data exists, in a lower HR zone than the work."""
    run_laps = [lap for lap in laps if lap.type == LapType.RUN]
    speed = _median_speed(run_laps)
    if work_speed <= 0 or speed <= 0:
        return True
    if speed >= work_speed * warmup_pace_ratio:
        return False

    zone = _median_hr_zone(run_laps, bounds)
    return zone is None or work_zone is None or zone < work_zone


def _work_label(run_type: RunType) -> str | None:
    if run_type == RunType.EASY:
        return None
    return run_type.display_name_polish


def _user_segment_label(role: SegmentRole, run_type: RunType | None) -> str | None:
    if role == SegmentRole.PREAMBLE:
        return WARM_UP_LABEL
    if role == SegmentRole.EPILOGUE:
        return COOL_DOWN_LABEL
    if role == SegmentRole.WORK and run_type is not None:
        return _work_label(run_type)
    return None


def _user_run_segment(
    user_segment: UserSegment, laps: list[Lap], zone_times: ZoneTimes
) -> RunSegment:
    run_type = user_segment_run_type(user_segment, laps, zone_times)
    return _segment(
        laps,
        role=user_segment.role,
        run_type=run_type,
        label=_user_segment_label(user_segment.role, run_type),
    )


def _user_run_segments(
    activity: Activity, user_segments: tuple[UserSegment, ...]
) -> list[RunSegment]:
    """The activity's laps split into ``user_segments``, each typed and labelled."""
    lap_groups = user_segment_laps(activity.laps, user_segments)
    work_segments = sum(1 for segment in user_segments if segment.role == SegmentRole.WORK)
    zone_bounds = _zone_bounds(activity)
    return [
        _user_run_segment(
            user_segment,
            laps,
            segment_zone_times(laps, activity.zone_times, zone_bounds, work_segments=work_segments),
        )
        for user_segment, laps in zip(user_segments, lap_groups, strict=True)
    ]


def run_segments(activity: Activity) -> list[RunSegment]:
    """The activity's classified segments: the user's segments when it has them, otherwise
    segments worked out from its lap types. Raises ``InvalidSegmentationError`` for user
    segments that don't cover its laps."""
    if activity.user_segments is not None:
        return _user_run_segments(activity, activity.user_segments)
    segments = SegmentSplitter().split(activity.laps)
    return classify_segments(segments, activity.zone_times, _zone_bounds(activity))


def segment_activity(activity: Activity) -> Activity:
    """The activity with its segments and training type worked out from its lap types,
    keeping the boundaries, roles and run types of the user's segments when it has them."""
    segments = run_segments(activity)
    return replace(
        activity,
        segments=[segment.to_segment() for segment in segments],
        training_type=dominant_run_type(segments),
    )


def relabel_laps(activity: Activity, lap_types: dict[int, LapType]) -> Activity:
    """The activity with the laps of ``lap_types`` (``Lap.index`` -> type) retyped, and
    segmented again. Raises ``ValueError`` for an index the activity has no lap at.
    """
    indexes = {lap.index for lap in activity.laps}
    for index in lap_types:
        if index not in indexes:
            raise ValueError(f"Unknown lapIndex: {index}")
    laps = [replace(lap, type=lap_types.get(lap.index, lap.type)) for lap in activity.laps]
    return segment_activity(replace(activity, laps=laps))
