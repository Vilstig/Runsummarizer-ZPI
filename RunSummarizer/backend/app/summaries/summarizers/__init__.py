from app.domain.enums import RunType
from app.summaries.summarizers import (
    easy,
    long_intervals,
    progression_run,
    race,
    short_intervals,
    tempo,
    time_intervals,
)
from app.summaries.summarizers.base import Summarizer

SUMMARIZERS: dict[RunType, Summarizer] = {
    RunType.EASY: easy.SUMMARIZER,
    RunType.TEMPO: tempo.SUMMARIZER,
    RunType.PROGRESSION_RUN: progression_run.SUMMARIZER,
    RunType.RACE: race.SUMMARIZER,
    RunType.SHORT_INTERVALS: short_intervals.SUMMARIZER,
    RunType.LONG_INTERVALS: long_intervals.SUMMARIZER,
    RunType.TIME_INTERVALS: time_intervals.SUMMARIZER,
}

__all__ = ["SUMMARIZERS", "Summarizer"]
