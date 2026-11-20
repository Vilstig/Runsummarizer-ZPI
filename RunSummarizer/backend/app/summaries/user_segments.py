"""Segments the user split an activity into: checking them against its laps, and the laps and
run type of each."""

from collections.abc import Sequence

from app.domain.enums import RunType, SegmentRole
from app.domain.errors import InvalidSegmentationError
from app.domain.models import Lap, UserSegment, ZoneTimes
from app.summaries.classification import classify_segment


def check_user_segments(laps: list[Lap], user_segments: Sequence[UserSegment]) -> None:
    """Raise ``InvalidSegmentationError`` unless ``user_segments`` cover every lap once, in
    order: there is at least one, the first starts at the first lap, each starts at a lap
    of the activity after the previous one's start lap, and no break has a run type."""
    if not user_segments:
        raise InvalidSegmentationError("Give at least one segment")

    positions = _lap_positions(laps)
    previous = -1  # position in ``laps`` of the previous segment's start lap
    for number, segment in enumerate(user_segments):
        position = positions.get(segment.start_lap_index)
        if position is None:
            raise InvalidSegmentationError(
                f"Segment {number}: the activity has no lap {segment.start_lap_index}"
            )
        if number == 0 and position != 0:
            raise InvalidSegmentationError(
                f"Segment 0: the first segment must start at the first lap, {laps[0].index}"
            )
        if position <= previous:
            raise InvalidSegmentationError(
                f"Segment {number}: it must start after the previous segment's start lap"
            )
        if segment.role == SegmentRole.BREAK and segment.run_type is not None:
            raise InvalidSegmentationError(f"Segment {number}: a break has no run type")
        previous = position


def user_segment_laps(laps: list[Lap], user_segments: Sequence[UserSegment]) -> list[list[Lap]]:
    """The laps of each of ``user_segments``, in order: from its start lap to the lap before
    the next segment's start lap, the last one to the final lap. Raises
    ``InvalidSegmentationError`` for segments ``check_user_segments`` refuses."""
    check_user_segments(laps, user_segments)
    positions = _lap_positions(laps)
    starts = [positions[segment.start_lap_index] for segment in user_segments]
    ends = [*starts[1:], len(laps)]
    return [laps[start:end] for start, end in zip(starts, ends, strict=True)]


def user_segment_run_type(
    segment: UserSegment, laps: list[Lap], zone_times: ZoneTimes
) -> RunType | None:
    """The run type of the user's ``segment`` over ``laps``: the one the user set; without
    one, easy for a warm-up or cool-down and, for work, classified from the laps and
    ``zone_times``, the segment's time in each HR zone. None for a break."""
    if segment.role == SegmentRole.BREAK:
        return None
    if segment.run_type is not None:
        return segment.run_type
    if segment.role in (SegmentRole.PREAMBLE, SegmentRole.EPILOGUE):
        return RunType.EASY
    return classify_segment(laps, zone_times, sum(lap.duration or 0 for lap in laps))


def _lap_positions(laps: list[Lap]) -> dict[int, int]:
    """Each lap's position in ``laps``, by ``Lap.index``."""
    return {lap.index: position for position, lap in enumerate(laps)}
