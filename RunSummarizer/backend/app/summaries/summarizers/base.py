from collections.abc import Callable
from dataclasses import dataclass

from app.domain.models import Lap


@dataclass(frozen=True)
class Summarizer[P, D]:
    """How a segment of one run type is summarized.

    ``generate_params`` reads the params the summary is built from off the laps,
    ``derive`` computes the values that follow from the params, and ``render`` writes
    the text from both.
    """

    generate_params: Callable[[list[Lap]], P | None]  # None: nothing to summarize
    derive: Callable[[P], D]
    render: Callable[[P, D], str]

    def text(self, params: P) -> str:
        return self.render(params, self.derive(params))

    def summarize(self, laps: list[Lap]) -> str:
        params = self.generate_params(laps)
        if params is None:
            return ""
        return self.text(params)
