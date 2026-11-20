"""The params a segment's part of a summary is written from."""

from app.domain.enums import LapType, RunType, SegmentRole
from app.domain.models import Lap
from app.summaries.params import SegmentParams
from app.summaries.summarizers import SUMMARIZERS, breaks

REST_OR_RECOVERY = frozenset({LapType.REST, LapType.RECOVERY})


def segment_params(
    laps: list[Lap], role: SegmentRole, run_type: RunType | None
) -> SegmentParams | None:
    """The params of a segment of ``laps``: a break's duration, otherwise those of its
    ``run_type`` (easy when None) over its laps up to the last one that isn't REST or
    RECOVERY. None when there is nothing to summarize."""
    if role == SegmentRole.BREAK:
        return breaks.generate_params(laps)

    laps = _trim_trailing_rest_recovery(laps)
    if not laps:
        return None
    return SUMMARIZERS[run_type or RunType.EASY].generate_params(laps)


def _trim_trailing_rest_recovery(laps: list[Lap]) -> list[Lap]:
    """``laps`` without the REST and RECOVERY laps at their end."""
    end = len(laps)
    while end > 0 and laps[end - 1].type in REST_OR_RECOVERY:
        end -= 1
    return laps[:end]
