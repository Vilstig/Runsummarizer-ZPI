from app.domain.models import Lap
from app.summaries.formatting import format_duration
from app.summaries.params import BreakParams


def generate_params(laps: list[Lap]) -> BreakParams:
    return BreakParams(duration_s=sum(lap.duration or 0 for lap in laps))


def render(params: BreakParams) -> str:
    return f"Przerwa: {format_duration(params.duration_s)}"
