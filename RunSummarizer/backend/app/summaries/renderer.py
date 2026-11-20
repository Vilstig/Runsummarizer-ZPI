from collections.abc import Iterable

from app.domain.enums import SegmentRole
from app.summaries.params import SegmentSummary
from app.summaries.summarizers import SUMMARIZERS, breaks


def summary_text(segments: Iterable[SegmentSummary]) -> str:
    """The summary text written from segment params, one paragraph per segment."""
    return "\n\n".join(_segment_text(segment) for segment in segments)


def _segment_text(segment: SegmentSummary) -> str:
    if segment.role == SegmentRole.BREAK:
        return breaks.render(segment.params)

    text = SUMMARIZERS[segment.run_type].text(segment.params)
    if segment.label:
        return f"{segment.label}:\n{text}"
    return text
