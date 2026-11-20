from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query, Response

from app.api.deps import get_activity_service, require_user
from app.api.schemas.activities import (
    EDIT_LAPS_EXAMPLES,
    RESET_LAPS_EXAMPLES,
    SEARCH_EXAMPLES,
    SUMMARY_EDIT_EXAMPLES,
    ActivityListQuery,
    ActivityResponse,
    ActivitySearchRequest,
    ActivitySearchResponse,
    ActivityStreamsResponse,
    EditLapsRequest,
    LapResponse,
    ResetLapsRequest,
    SetSegmentsRequest,
    SummaryEditRequest,
    WeeklySummaryQuery,
    WeeklySummaryResponse,
)
from app.api.schemas.errors import ErrorResponse
from app.api.stream_keys import KEYS_PARAMETER, get_stream_types
from app.domain.enums import StreamType
from app.services.activity_service import ActivityService

router = APIRouter(tags=["activities"])


@router.get("/activities", response_model=list[ActivityResponse])
async def get_activities(
    query: ActivityListQuery = Query(),
    user_id: str = Depends(require_user),
    service: ActivityService = Depends(get_activity_service),
):
    """List activities ordered by start time (newest first)."""
    records = await service.list_activities(**query.model_dump(), user_id=user_id)
    return [ActivityResponse.from_record(record) for record in records]


@router.post("/activities/search", response_model=ActivitySearchResponse)
async def search_activities(
    body: Annotated[ActivitySearchRequest, Body(openapi_examples=SEARCH_EXAMPLES)],
    user_id: str = Depends(require_user),
    service: ActivityService = Depends(get_activity_service),
):
    """Find the user's activities matching every filter of the body. ``items`` holds the
    page ``offset``/``limit`` of them in ``sort`` order, newest first by default, without
    their laps; ``total`` counts them all."""
    page = await service.search_activities(
        body.to_filter(user_id),
        order=body.sort.to_order(),
        limit=body.limit,
        offset=body.offset,
    )
    return ActivitySearchResponse.from_page(page)


@router.get("/activities/weekly-summary", response_model=WeeklySummaryResponse)
async def get_weekly_summary(
    query: WeeklySummaryQuery = Query(),
    user_id: str = Depends(require_user),
    service: ActivityService = Depends(get_activity_service),
):
    """Distance, duration and elevation gain of the user's runs, summed by Monday-based
    week and aggregated by the database. ``weeks`` entries come back oldest first, ending
    with the week containing ``date`` (today, by default); a week without runs is zero, not
    left out."""
    totals = await service.weekly_summary(weeks=query.weeks, as_of=query.as_of, user_id=user_id)
    return WeeklySummaryResponse.from_week_totals(totals)


@router.get(
    "/activities/{activity_id}",
    response_model=ActivityResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_activity(
    activity_id: str,
    user_id: str = Depends(require_user),
    service: ActivityService = Depends(get_activity_service),
):
    """Return a single activity with its processed laps."""
    return ActivityResponse.from_record(await service.get_activity(activity_id, user_id=user_id))


@router.get(
    "/activities/{activity_id}/laps",
    response_model=list[LapResponse],
    responses={404: {"model": ErrorResponse}},
)
async def get_activity_laps(
    activity_id: str,
    user_id: str = Depends(require_user),
    service: ActivityService = Depends(get_activity_service),
):
    """Return only the classified laps for a single activity."""
    laps = await service.get_activity_laps(activity_id, user_id=user_id)
    return [LapResponse.from_lap(lap) for lap in laps]


@router.get(
    "/activities/{activity_id}/streams",
    response_model=ActivityStreamsResponse,
    response_model_exclude_unset=True,
    openapi_extra={"parameters": [KEYS_PARAMETER]},
    responses={404: {"model": ErrorResponse}},
)
async def get_activity_streams(
    activity_id: str,
    stream_types: tuple[StreamType, ...] = Depends(get_stream_types),
    user_id: str = Depends(require_user),
    service: ActivityService = Depends(get_activity_service),
):
    """Return the requested sample streams of a single activity; a requested stream the
    activity lacks is null, and streams not requested are left out."""
    return await service.get_activity_streams(
        activity_id, user_id=user_id, stream_types=stream_types
    )


LAP_EDIT_RESPONSES = {
    400: {"model": ErrorResponse, "description": "The activity has no lap at a given lapIndex"},
    404: {"model": ErrorResponse, "description": "Activity not found"},
    409: {"model": ErrorResponse, "description": "The edited summary text needs textPolicy"},
}


@router.patch(
    "/activities/{activity_id}/laps",
    response_model=ActivityResponse,
    responses=LAP_EDIT_RESPONSES,
)
async def edit_activity_laps(
    activity_id: str,
    body: Annotated[EditLapsRequest, Body(openapi_examples=EDIT_LAPS_EXAMPLES)],
    user_id: str = Depends(require_user),
    service: ActivityService = Depends(get_activity_service),
):
    """Change lap types and distances, segment the activity again and write its summary
    again from them. A lap's ``version`` is 1 once its distance was edited. A refused change's
    detail is ``{"detail", "code"}``: 400 ``unknown_lap`` for a lap the activity doesn't
    have.

    ``textPolicy``: ``"regenerate"``, the summary text is written again from the new laps and
    segments; ``"keep"``, the user's text stays. It is needed only when the summary text was
    edited (``summaryTextEdited``): without it the answer is 409 ``text_policy_required``."""
    updated = await service.edit_laps(
        activity_id,
        body.lap_types(),
        body.distances(),
        text_policy=body.textPolicy,
        user_id=user_id,
    )
    return ActivityResponse.from_record(updated)


@router.post(
    "/activities/{activity_id}/laps/reset",
    response_model=ActivityResponse,
    responses=LAP_EDIT_RESPONSES,
)
async def reset_activity_laps(
    activity_id: str,
    body: Annotated[ResetLapsRequest, Body(openapi_examples=RESET_LAPS_EXAMPLES)],
    user_id: str = Depends(require_user),
    service: ActivityService = Depends(get_activity_service),
):
    """Put the measured distance back on the laps at ``lapIndexes``, or on every lap without
    them (``{}``), segment the activity again and write its summary again. Refused changes
    answer as in ``PATCH /laps``.

    ``textPolicy``: ``"regenerate"``, the summary text is written again from the new laps and
    segments; ``"keep"``, the user's text stays. It is needed only when the summary text was
    edited (``summaryTextEdited``): without it the answer is 409 ``text_policy_required``."""
    updated = await service.reset_laps(
        activity_id, body.lapIndexes, text_policy=body.textPolicy, user_id=user_id
    )
    return ActivityResponse.from_record(updated)


@router.put(
    "/activities/{activity_id}/segments",
    response_model=ActivityResponse,
    responses={
        400: {
            "model": ErrorResponse,
            "description": "The segments don't cover the activity's laps",
        },
        404: {"model": ErrorResponse, "description": "Activity not found"},
        409: {"model": ErrorResponse, "description": "The edited summary text needs textPolicy"},
    },
)
async def set_activity_segments(
    activity_id: str,
    body: SetSegmentsRequest,
    user_id: str = Depends(require_user),
    service: ActivityService = Depends(get_activity_service),
):
    """Split the activity into the user's segments, or back into automatic segments with
    ``segments: null``, and write its summary again from them. A refused change's detail is
    ``{"detail", "code"}``.

    ``textPolicy``: ``"regenerate"``, the summary text is written again from the new laps and
    segments; ``"keep"``, the user's text stays. It is needed only when the summary text was
    edited (``summaryTextEdited``): without it the answer is 409 ``text_policy_required``."""
    updated = await service.set_segments(
        activity_id, body.user_segments(), text_policy=body.textPolicy, user_id=user_id
    )
    return ActivityResponse.from_record(updated)


@router.patch(
    "/activities/{activity_id}/summary",
    response_model=ActivityResponse,
    responses={404: {"model": ErrorResponse}},
)
async def edit_activity_summary(
    activity_id: str,
    body: Annotated[SummaryEditRequest, Body(openapi_examples=SUMMARY_EDIT_EXAMPLES)],
    user_id: str = Depends(require_user),
    service: ActivityService = Depends(get_activity_service),
):
    """Replace the summary text with the user's text."""
    updated = await service.edit_summary(activity_id, body.text, user_id=user_id)
    return ActivityResponse.from_record(updated)


@router.post(
    "/activities/{activity_id}/summary/reset",
    response_model=ActivityResponse,
    responses={404: {"model": ErrorResponse}},
)
async def reset_activity_summary(
    activity_id: str,
    user_id: str = Depends(require_user),
    service: ActivityService = Depends(get_activity_service),
):
    """Write the summary again from the activity's laps and segments, dropping the user's
    edits of the summary; the user's segments stay."""
    updated = await service.reset_summary(activity_id, user_id=user_id)
    return ActivityResponse.from_record(updated)


@router.delete(
    "/activities/{activity_id}",
    status_code=204,
    responses={404: {"model": ErrorResponse}},
)
async def delete_activity(
    activity_id: str,
    user_id: str = Depends(require_user),
    service: ActivityService = Depends(get_activity_service),
):
    """Delete an activity."""
    await service.delete_activity(activity_id, user_id=user_id)
    return Response(status_code=204)
