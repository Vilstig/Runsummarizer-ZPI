from collections import Counter
from datetime import date
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.enums import ActivitySortKey, LapType, Provider, RunType, SegmentRole
from app.domain.models import (
    Activity,
    ActivityFilter,
    ActivityOrder,
    ActivityPage,
    ActivityRecord,
    Lap,
    NumberRange,
    Segment,
    SegmentCriteria,
    UserSegment,
    WeekTotals,
    ZoneBounds,
    ZoneTimes,
)
from app.summaries.editing import TextPolicy
from app.summaries.hr_zones import HR_ZONES

MAX_PAGE_SIZE = 200
MAX_LAP_DISTANCE_M = 50_000  # 50 km
MAX_SEGMENT_GROUPS = 10
MAX_SUMMARY_WEEKS = 52
# Upper bounds on the lists and text of edit request bodies
MAX_LAPS = 1000
MAX_SUMMARY_TEXT_LENGTH = 10_000  # characters
DEFAULT_REP_DISTANCE_TOLERANCE = 0.05  # a fraction of the rep distance

TEXT_POLICY_DESCRIPTION = (
    'What happens to summary text the user edited. "regenerate": the summary text is '
    'written again from the new laps and segments. "keep": the user\'s text stays. Needed '
    "only when the summary text was edited (summaryTextEdited is true); without it the "
    "request gets a 409 text_policy_required. Ignored when the text wasn't edited."
)

# The textPolicy field of a request that changes an activity's laps or segments.
TextPolicyField = Annotated[TextPolicy | None, Field(description=TEXT_POLICY_DESCRIPTION)]


class ActivityListQuery(BaseModel):
    """Query parameters of ``GET /activities``.

    The date window is in calendar days: ``after`` inclusive, ``before`` exclusive;
    either may be open.
    """

    limit: int = Field(default=50, ge=1, le=MAX_PAGE_SIZE)
    skip: int = Field(default=0, ge=0)
    source: Provider | None = Field(
        default=None,
        description=f"Filter by source: {' or '.join(f"'{source.value}'" for source in Provider)}",
    )
    include_laps: bool = Field(
        default=False, description="whether the response should contain laps"
    )
    after: date | None = Field(
        default=None,
        description="First day included (local date of the activity), e.g. 2026-10-01.",
    )
    before: date | None = Field(
        default=None,
        description="First day excluded (local date of the activity), e.g. 2026-11-01.",
    )

    @model_validator(mode="after")
    def _after_precedes_before(self) -> "ActivityListQuery":
        _check_date_window(self.after, self.before)
        return self


def _check_date_window(after: date | None, before: date | None) -> None:
    if after is not None and before is not None and after >= before:
        raise ValueError("'after' must be earlier than 'before'")


class WeeklySummaryQuery(BaseModel):
    """Query parameters of ``GET /activities/weekly-summary``."""

    weeks: int = Field(
        default=12, ge=1, le=MAX_SUMMARY_WEEKS, description="How many weeks to return."
    )
    # the field is named 'date' on the wire; 'as_of' avoids shadowing the 'date' type above
    as_of: date | None = Field(
        default=None,
        alias="date",
        description=(
            "A day in the last week to include, e.g. 2026-11-19. The server's current "
            "day, by default."
        ),
    )


class NumberRangeModel(BaseModel):
    """Values from ``min`` to ``max``, both inclusive; either may be left out."""

    model_config = ConfigDict(extra="forbid")

    min: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    max: float | None = Field(default=None, ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def _min_not_above_max(self) -> Self:
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("'min' must not be greater than 'max'")
        return self

    def to_range(self) -> NumberRange:
        return NumberRange(min=self.min, max=self.max)


class PaceRangeModel(NumberRangeModel):
    """Paces in s/km from ``min``, the fastest, to ``max``, the slowest, both inclusive;
    either may be left out."""

    min: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    max: float | None = Field(default=None, gt=0, allow_inf_nan=False)


class RepDistanceModel(BaseModel):
    """Rep distances (m) from ``value × (1 - tolerance)`` to ``value × (1 + tolerance)``,
    both inclusive."""

    model_config = ConfigDict(extra="forbid")

    value: float = Field(gt=0, allow_inf_nan=False)  # m
    tolerance: float = Field(
        default=DEFAULT_REP_DISTANCE_TOLERANCE, ge=0, le=1, allow_inf_nan=False
    )  # a fraction of value

    def to_range(self) -> NumberRange:
        # rounded to a micrometre, so float error doesn't move a bound inside an exact one
        return NumberRange(
            min=round(self.value * (1 - self.tolerance), 6),
            max=round(self.value * (1 + self.tolerance), 6),
        )


class SegmentCriteriaModel(BaseModel):
    """Conditions one work segment of an activity meets, every one given; at least one."""

    model_config = ConfigDict(extra="forbid")

    runTypes: list[RunType] | None = Field(  # RunType ids
        default=None, min_length=1, description="The segment's run type is one of these."
    )
    distance: NumberRangeModel | None = Field(
        default=None, description="Metres; for intervals, the reps together."
    )
    duration: NumberRangeModel | None = Field(
        default=None, description="Seconds; for intervals, the reps together."
    )
    pace: PaceRangeModel | None = Field(
        default=None, description="Seconds per km; for intervals, of the reps."
    )
    avgHr: NumberRangeModel | None = Field(
        default=None, description="Average heart rate, bpm. Interval segments have none."
    )
    repCount: NumberRangeModel | None = Field(default=None, description="Number of reps.")
    repDistance: RepDistanceModel | None = Field(
        default=None, description="The reps' average distance, metres."
    )
    avgRepDuration: NumberRangeModel | None = Field(
        default=None, description="A rep's average time, seconds."
    )
    avgRecovery: NumberRangeModel | None = Field(
        default=None, description="A recovery's average time, seconds."
    )

    @model_validator(mode="after")
    def _some_condition(self) -> Self:
        if all(getattr(self, name) is None for name in type(self).model_fields):
            raise ValueError("A segment group needs at least one condition")
        return self

    def to_criteria(self) -> SegmentCriteria:
        return SegmentCriteria(
            run_types=frozenset(self.runTypes) if self.runTypes is not None else None,
            distance=_range(self.distance),
            duration=_range(self.duration),
            pace=_range(self.pace),
            avg_hr=_range(self.avgHr),
            rep_count=_range(self.repCount),
            rep_distance=_range(self.repDistance),
            avg_rep_duration=_range(self.avgRepDuration),
            avg_recovery=_range(self.avgRecovery),
        )


class ActivitySortModel(BaseModel):
    """The order of the search results; activities missing the value come last."""

    model_config = ConfigDict(extra="forbid")

    by: ActivitySortKey = ActivitySortKey.START_TIME
    order: Literal["asc", "desc"] = "desc"  # pace "asc": fastest first

    def to_order(self) -> ActivityOrder:
        return ActivityOrder(key=self.by, descending=self.order == "desc")


# The named request examples of ``POST /activities/search`` in the API docs.
SEARCH_EXAMPLES = {
    "everything": {
        "summary": "Every parameter",
        "description": (
            "Every field is optional; an activity must match all the filters given.\n\n"
            "- `after`, `before`: the activity's local start date; `after` is the first day "
            "included, `before` the first day excluded.\n"
            f"- `sources`: any of {', '.join(f'`{source.value}`' for source in Provider)}.\n"
            "- `trainingTypes`: the activity's `trainingTypeId` is one of these: "
            + ", ".join(f"{run_type.value} {run_type.display_name}" for run_type in RunType)
            + ".\n"
            "- `distance` (m), `duration` (s), `pace` (s/km), `avgHr` (bpm): `min` and `max`, "
            "both inclusive, either may be left out. A pace `min` is the fastest pace, `max` "
            "the slowest.\n"
            f"- `segments`: 1 to {MAX_SEGMENT_GROUPS} groups of conditions on the activity's "
            "work segments (not warm-ups, cool-downs or breaks). One segment must meet every "
            "condition of a group; each group may be met by a different segment. `runTypes` "
            "takes the run type ids above. `distance`, `duration` and `pace` of intervals are "
            "of the reps. `repCount`, `repDistance`, `avgRepDuration` (s) and `avgRecovery` "
            "(s) exist for short and time intervals only; `repDistance` matches the reps' "
            f"average distance within `tolerance` (a fraction, {DEFAULT_REP_DISTANCE_TOLERANCE} "
            "by default) of `value`. Interval segments have no `avgHr`.\n"
            f"- `sort.by`:{', '.join(f'`{key.value}`' for key in ActivitySortKey)}; "
            "`sort.order`: `asc` or `desc`, `pace` `asc` being fastest first. Newest first "
            "by default.\n"
            f"- `limit`: activities per page, 1 to {MAX_PAGE_SIZE}, 50 by default; `offset`: "
            "activities skipped before the page, 0 by default."
        ),
        "value": {
            "after": "2026-01-01",
            "before": "2026-07-01",
            "sources": [Provider.STRAVA.value, Provider.GARMIN.value],
            "trainingTypes": [RunType.TEMPO.value, RunType.RACE.value],
            "distance": {"min": 5000, "max": 21100},
            "duration": {"min": 900, "max": 7200},
            "pace": {"min": 180, "max": 300},
            "avgHr": {"min": 150, "max": 190},
            "segments": [
                {
                    "runTypes": [RunType.SHORT_INTERVALS.value],
                    "repDistance": {"value": 1000, "tolerance": DEFAULT_REP_DISTANCE_TOLERANCE},
                    "repCount": {"min": 5, "max": 10},
                    "pace": {"min": 180, "max": 200},
                    "avgRepDuration": {"min": 180, "max": 200},
                    "avgRecovery": {"min": 60, "max": 120},
                },
                {
                    "runTypes": [RunType.TEMPO.value],
                    "distance": {"min": 3000, "max": 8000},
                    "duration": {"min": 600, "max": 1800},
                    "avgHr": {"min": 160, "max": 180},
                },
            ],
            "sort": {"by": ActivitySortKey.PACE.value, "order": "asc"},
            "limit": 20,
            "offset": 0,
        },
    },
    "kilometreRepeats": {
        "summary": "1000 m intervals",
        "description": "At least five reps of about 1000 m, faster than 3:20/km.",
        "value": {
            "segments": [
                {
                    "runTypes": [RunType.SHORT_INTERVALS.value],
                    "repDistance": {"value": 1000},
                    "repCount": {"min": 5},
                    "pace": {"max": 200},
                }
            ],
        },
    },
    "intervals": {
        "summary": "Interval sessions since August",
        "value": {
            "after": "2026-08-01",
            "trainingTypes": [RunType.SHORT_INTERVALS.value, RunType.LONG_INTERVALS.value],
        },
    },
    "longRuns": {
        "summary": "Long runs, fastest first",
        "description": "Pace is in s/km: `max` 330 keeps runs faster than 5:30/km.",
        "value": {
            "distance": {"min": 18000},
            "pace": {"max": 330},
            "sort": {"by": ActivitySortKey.PACE.value, "order": "asc"},
            "limit": 20,
        },
    },
}


class ActivitySearchRequest(BaseModel):
    """Body of ``POST /activities/search``: the filters an activity must match, all of them,
    and the page of the matches to return. A filter left out doesn't filter; an activity
    missing a value a range filters on doesn't match it."""

    model_config = ConfigDict(extra="forbid")

    after: date | None = Field(
        default=None,
        description="First day included (local date of the activity), e.g. 2026-10-01.",
    )
    before: date | None = Field(
        default=None,
        description="First day excluded (local date of the activity), e.g. 2026-11-01.",
    )
    sources: list[Provider] | None = Field(default=None, min_length=1)
    trainingTypes: list[RunType] | None = Field(  # RunType ids
        default=None, min_length=1, description="The activity's trainingTypeId is one of these."
    )
    distance: NumberRangeModel | None = Field(default=None, description="Metres.")
    duration: NumberRangeModel | None = Field(default=None, description="Seconds.")
    pace: PaceRangeModel | None = Field(default=None, description="Seconds per km.")
    avgHr: NumberRangeModel | None = Field(default=None, description="Average heart rate, bpm.")
    segments: list[SegmentCriteriaModel] | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_SEGMENT_GROUPS,
        description=(
            "The activity has, for each group, a work segment meeting every condition of the "
            "group; different groups may be met by different segments."
        ),
    )
    sort: ActivitySortModel = Field(default_factory=ActivitySortModel)
    limit: int = Field(default=50, ge=1, le=MAX_PAGE_SIZE)
    offset: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _after_precedes_before(self) -> Self:
        _check_date_window(self.after, self.before)
        return self

    def to_filter(self, user_id: str) -> ActivityFilter:
        """The search's filter over the activities of ``user_id``."""
        return ActivityFilter(
            user_id=user_id,
            after=self.after,
            before=self.before,
            sources=frozenset(self.sources) if self.sources is not None else None,
            training_types=(
                frozenset(self.trainingTypes) if self.trainingTypes is not None else None
            ),
            distance=_range(self.distance),
            duration=_range(self.duration),
            pace=_range(self.pace),
            avg_hr=_range(self.avgHr),
            segments=tuple(group.to_criteria() for group in self.segments or ()),
        )


def _range(model: NumberRangeModel | RepDistanceModel | None) -> NumberRange | None:
    return model.to_range() if model is not None else None


# The named request examples of ``PATCH /activities/{id}/laps`` in the API docs.
EDIT_LAPS_EXAMPLES = {
    "type": {
        "summary": "Change a lap's type",
        "description": "`textPolicy` says what happens to summary text the user edited.",
        "value": {"laps": [{"lapIndex": 4, "typeId": LapType.REST.value}], "textPolicy": "keep"},
    },
    "distance": {
        "summary": "Correct lap distances",
        "description": (
            "Each lap's distance replaces the measured one, and its speed follows from it. "
            "`textPolicy` says what happens to summary text the user edited."
        ),
        "value": {
            "laps": [
                {"lapIndex": 3, "distance": 400},
                {"lapIndex": 5, "typeId": LapType.RUN.value, "distance": 400},
            ],
            "textPolicy": "regenerate",
        },
    },
}


class LapEdit(BaseModel):
    """The user's changes to the lap at ``lapIndex``: its type, its distance, or both."""

    model_config = ConfigDict(extra="forbid")

    lapIndex: int
    typeId: LapType | None = None
    distance: float | None = Field(  # m
        default=None, gt=0, le=MAX_LAP_DISTANCE_M, allow_inf_nan=False
    )

    @model_validator(mode="after")
    def _type_or_distance(self) -> Self:
        if self.typeId is None and self.distance is None:
            raise ValueError(f"Lap {self.lapIndex}: send 'typeId' or 'distance'")
        return self


class EditLapsRequest(BaseModel):
    """Body of ``PATCH /activities/{id}/laps``: changes to the activity's laps, with
    ``textPolicy`` saying what happens to summary text the user edited."""

    model_config = ConfigDict(extra="forbid")

    laps: list[LapEdit] = Field(min_length=1, max_length=MAX_LAPS)
    textPolicy: TextPolicyField = None

    @model_validator(mode="after")
    def _each_lap_once(self) -> Self:
        counts = Counter(lap.lapIndex for lap in self.laps)
        repeated = sorted(index for index, count in counts.items() if count > 1)
        if repeated:
            raise ValueError(f"Send each lap once; lap {repeated[0]} came more than once")
        return self

    def lap_types(self) -> dict[int, LapType]:
        return {lap.lapIndex: lap.typeId for lap in self.laps if lap.typeId is not None}

    def distances(self) -> dict[int, float]:
        return {lap.lapIndex: lap.distance for lap in self.laps if lap.distance is not None}


# The named request examples of ``POST /activities/{id}/laps/reset`` in the API docs.
RESET_LAPS_EXAMPLES = {
    "some": {
        "summary": "Reset some laps",
        "value": {"lapIndexes": [3, 5], "textPolicy": "keep"},
    },
    "all": {"summary": "Reset every lap", "value": {"textPolicy": "regenerate"}},
}


class ResetLapsRequest(BaseModel):
    """Body of ``POST /activities/{id}/laps/reset``: the laps whose distance goes back to
    the measured one, every lap when ``lapIndexes`` is left out, with ``textPolicy`` saying
    what happens to summary text the user edited."""

    model_config = ConfigDict(extra="forbid")

    lapIndexes: list[int] | None = Field(default=None, min_length=1, max_length=MAX_LAPS)
    textPolicy: TextPolicyField = None


class UserSegmentModel(BaseModel):
    """A segment the user split the activity into, from the lap ``startLapIndex`` to the lap
    before the next segment's start lap, the last one to the final lap."""

    startLapIndex: int
    role: SegmentRole
    # None: easy for a warm-up or cool-down, classified from the laps for work; None for a break
    runTypeId: RunType | None = None

    def to_user_segment(self) -> UserSegment:
        return UserSegment(
            start_lap_index=self.startLapIndex, role=self.role, run_type=self.runTypeId
        )


class SetSegmentsRequest(BaseModel):
    """Body of ``PUT /activities/{id}/segments``: the user's ``segments`` in lap order, or
    null to go back to automatic segments, with ``textPolicy`` saying what happens to
    summary text the user edited."""

    segments: list[UserSegmentModel] | None = Field(max_length=MAX_LAPS)
    textPolicy: TextPolicyField = None

    def user_segments(self) -> tuple[UserSegment, ...] | None:
        if self.segments is None:
            return None
        return tuple(segment.to_user_segment() for segment in self.segments)


# The named request examples of ``PATCH /activities/{id}/summary`` in the API docs.
SUMMARY_EDIT_EXAMPLES = {
    "text": {
        "summary": "Edit the text",
        "value": {"text": "Rozgrzewka 2 km, potem 10x300m na bieżni."},
    },
}


class SummaryEditRequest(BaseModel):
    """Body of ``PATCH /activities/{id}/summary``: the user's summary ``text``."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(max_length=MAX_SUMMARY_TEXT_LENGTH)


class HeartRateZoneResponse(BaseModel):
    """Seconds in one HR zone, which covers heart rates from ``minBpm`` to ``maxBpm``, both
    inclusive."""

    zone: int  # 1-5
    minBpm: int | None  # null when the zone bounds aren't known
    maxBpm: int | None  # null for zone 5, which has no upper limit, or when not known
    time: float  # s

    @classmethod
    def list_from(
        cls, zone_times: ZoneTimes, zone_bounds: ZoneBounds | None
    ) -> list["HeartRateZoneResponse"]:
        """Zones 1-5, zone 1 from 0 bpm and each zone ending 1 bpm below the next one."""
        if zone_bounds is None:
            lower = upper = (None,) * len(HR_ZONES)
        else:
            lower = (0, *zone_bounds)
            upper = (*(bound - 1 for bound in zone_bounds), None)
        return [
            cls(zone=zone, minBpm=min_bpm, maxBpm=max_bpm, time=zone_times[zone])
            for zone, min_bpm, max_bpm in zip(HR_ZONES, lower, upper, strict=True)
        ]


class LapResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    lapIndex: int
    typeId: LapType | None = None
    typeName: str | None = None
    typeDisplay: str | None = None
    distance: float | None = None
    duration: float | None = None
    speed: float | None = None
    avgHr: float | None = None
    maxHr: float | None = None
    elevationGain: float | None = None
    version: int = 0  # 0: as imported, 1: edited by the user

    @classmethod
    def from_lap(cls, lap: Lap) -> "LapResponse":
        return cls(
            lapIndex=lap.index,
            typeId=lap.type,
            typeName=lap.type.name if lap.type is not None else None,
            typeDisplay=lap.type.display_name if lap.type is not None else None,
            distance=lap.distance,
            duration=lap.duration,
            speed=lap.speed,
            avgHr=lap.avg_hr,
            maxHr=lap.max_hr,
            elevationGain=lap.elevation_gain,
            version=lap.version,
        )


class ActivityStreamsResponse(BaseModel):
    """An activity's requested sample streams, aligned by index; null for a stream it
    lacks."""

    time: list[int] | None = None  # seconds since the start
    distance: list[float] | None = None  # metres
    heartrate: list[int] | None = None  # bpm
    velocity: list[float] | None = None  # m/s
    altitude: list[float] | None = None  # metres


class SegmentResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    startLapIndex: int
    endLapIndex: int
    runTypeId: int
    runTypeDisplay: str
    label: str | None = None
    role: str
    runTypeAuto: bool  # True: worked out from the laps; False: set by the user

    @classmethod
    def from_segment(cls, segment: Segment, *, run_type_auto: bool) -> "SegmentResponse":
        return cls(
            startLapIndex=segment.start_lap_index,
            endLapIndex=segment.end_lap_index,
            runTypeId=segment.run_type.value,
            runTypeDisplay=segment.run_type.display_name,
            label=segment.label,
            role=segment.role.value,
            runTypeAuto=run_type_auto,
        )


def _user_typed_starts(activity: Activity) -> frozenset[int]:
    """The start laps of the user's segments whose run type the user set."""
    if activity.user_segments is None:
        return frozenset()
    return frozenset(
        segment.start_lap_index
        for segment in activity.user_segments
        if segment.run_type is not None
    )


class ProcessedData(BaseModel):
    model_config = ConfigDict(extra="ignore")

    activityId: str
    name: str | None = None
    startTimeLocal: str | None = None
    distance: float | None = None
    duration: float | None = None
    speed: float | None = None
    avgHr: float | None = None
    maxHr: float | None = None
    elevationGain: float | None = None
    heartRateZones: list[HeartRateZoneResponse] = []
    laps: list[LapResponse] = []
    segments: list[SegmentResponse] = []
    trainingTypeId: int | None = None
    trainingTypeName: str | None = None
    trainingTypeDisplay: str | None = None
    source: str | None = None
    deviceName: str | None = None  # the recording device, e.g. 'Forerunner 965'; None if unknown

    @classmethod
    def from_activity(cls, activity: Activity) -> "ProcessedData":
        training_type = activity.training_type
        user_typed_starts = _user_typed_starts(activity)
        return cls(
            activityId=activity.key,
            name=activity.name,
            startTimeLocal=activity.start_time_local.isoformat(),
            distance=activity.distance,
            duration=activity.duration,
            speed=activity.speed,
            avgHr=activity.avg_hr,
            maxHr=activity.max_hr,
            elevationGain=activity.elevation_gain,
            heartRateZones=HeartRateZoneResponse.list_from(
                activity.zone_times, activity.zone_bounds
            ),
            laps=[LapResponse.from_lap(lap) for lap in activity.laps],
            segments=[
                SegmentResponse.from_segment(
                    segment, run_type_auto=segment.start_lap_index not in user_typed_starts
                )
                for segment in activity.segments
            ],
            trainingTypeId=training_type.value if training_type is not None else None,
            trainingTypeName=training_type.name if training_type is not None else None,
            trainingTypeDisplay=training_type.display_name if training_type is not None else None,
            source=activity.source.value,
            deviceName=activity.device_name,
        )


class ActivityResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    activityId: str
    source: str
    userId: str
    summary: str
    summaryTextEdited: bool = False
    segmentsEdited: bool = False  # True: the user set the activity's segments
    processed_data: ProcessedData

    @classmethod
    def from_record(cls, record: ActivityRecord) -> "ActivityResponse":
        return cls(
            activityId=record.activity.key,
            source=record.activity.source.value,
            userId=record.user_id,
            summary=record.summary.text,
            summaryTextEdited=record.summary.text_edited_at is not None,
            segmentsEdited=record.activity.user_segments is not None,
            processed_data=ProcessedData.from_activity(record.activity),
        )


class ActivitySearchResponse(BaseModel):
    """One page of the activities a search found, and how many it found in all."""

    items: list[ActivityResponse]
    total: int

    @classmethod
    def from_page(cls, page: ActivityPage) -> "ActivitySearchResponse":
        return cls(
            items=[ActivityResponse.from_record(record) for record in page.records],
            total=page.total,
        )


class WeekTotalsResponse(BaseModel):
    """A user's totals of the Monday-based week starting ``weekStart``; zero when the week
    has no activities."""

    weekStart: date
    distance: float  # m
    duration: float  # s
    elevationGain: float  # m

    @classmethod
    def from_week_totals(cls, totals: WeekTotals) -> "WeekTotalsResponse":
        return cls(
            weekStart=totals.week_start,
            distance=totals.distance,
            duration=totals.duration,
            elevationGain=totals.elevation_gain,
        )


class WeeklySummaryResponse(BaseModel):
    """Weekly totals, oldest first, the current week last."""

    weeks: list[WeekTotalsResponse]

    @classmethod
    def from_week_totals(cls, weeks: list[WeekTotals]) -> "WeeklySummaryResponse":
        return cls(weeks=[WeekTotalsResponse.from_week_totals(week) for week in weeks])
