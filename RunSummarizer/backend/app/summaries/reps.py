from __future__ import annotations

import itertools

from app.domain.enums import LapType
from app.domain.models import Lap

MIN_REPS = 3  # sets of at least this many reps are intervals without any further check
REP_DISTANCE_TOLERANCE = 0.10  # max relative distance difference between the 2 reps of a set
LONG_REP_DISTANCE_M = 1100  # a set with a median rep distance above this is long intervals


def run_stretches(laps: list[Lap]) -> list[tuple[int, int]]:
    """Inclusive (first, last) index ranges of consecutive RUN laps; any other lap type ends one."""
    stretches: list[tuple[int, int]] = []
    first: int | None = None
    for i, lap in enumerate(laps):
        if lap.type == LapType.RUN:
            if first is None:
                first = i
        elif first is not None:
            stretches.append((first, i - 1))
            first = None
    if first is not None:
        stretches.append((first, len(laps) - 1))
    return stretches


def are_interval_reps(reps: list[list[Lap]]) -> bool:
    """Whether reps, each a list of RUN laps, form an interval set.

    3 or more reps always do. 2 reps (one recovery between them) do when their total
    run distances are within REP_DISTANCE_TOLERANCE of each other.
    """
    if len(reps) >= MIN_REPS:
        return True
    if len(reps) != 2:
        return False

    first, second = (rep_distance(rep) for rep in reps)
    longest = max(first, second)
    return longest > 0 and abs(first - second) <= REP_DISTANCE_TOLERANCE * longest


def rep_distance(rep: list[Lap]) -> float:
    return sum(lap.distance or 0 for lap in rep)


def merged_reps_and_recoveries(laps: list[Lap]) -> tuple[list[Lap], list[Lap]]:
    """Each run of consecutive laps of one type merged into one lap, in order: the merged
    RUN laps (reps) and the merged RECOVERY laps (recoveries). REST laps are left out."""
    reps: list[Lap] = []
    recoveries: list[Lap] = []
    for lap_type, group in itertools.groupby(laps, key=lambda lap: lap.type):
        laps_in_group = list(group)
        merged = sum(laps_in_group[1:], start=laps_in_group[0])
        if lap_type == LapType.RUN:
            reps.append(merged)
        elif lap_type == LapType.RECOVERY:
            recoveries.append(merged)
    return reps, recoveries
