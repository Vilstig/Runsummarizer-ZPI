"""POST /api/v1/activities/search: the body becomes the user's filter, order and page, and
the page found comes back with its total."""

from dataclasses import fields
from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_activity_service, require_user
from app.api.schemas.activities import (
    MAX_SEGMENT_GROUPS,
    SEARCH_EXAMPLES,
    ActivitySearchRequest,
    ActivitySortModel,
    NumberRangeModel,
    RepDistanceModel,
    SegmentCriteriaModel,
)
from app.domain.enums import ActivitySortKey, Provider, RunType
from app.domain.models import (
    NEWEST_FIRST,
    ActivityFilter,
    ActivityOrder,
    ActivityPage,
    NumberRange,
    SegmentCriteria,
)
from app.main import app
from tests.db.builders import make_activity

SEARCH = "/api/v1/activities/search"
USER_ID = "user-1"


class FakeActivityService:
    """Stands in for ``ActivityService``: records the arguments of each search and answers
    with ``page``."""

    def __init__(self):
        self.calls: list[dict] = []
        self.page = ActivityPage(records=[], total=0)

    async def search_activities(self, activity_filter: ActivityFilter, **kwargs) -> ActivityPage:
        self.calls.append({"activity_filter": activity_filter, **kwargs})
        return self.page


@pytest.fixture(autouse=True)
def current_user():
    app.dependency_overrides[require_user] = lambda: USER_ID
    yield
    app.dependency_overrides.pop(require_user, None)


@pytest.fixture
def service():
    fake = FakeActivityService()
    app.dependency_overrides[get_activity_service] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_activity_service, None)


def search(body: dict) -> httpx.Response:
    return TestClient(app).post(SEARCH, json=body)


def test_an_empty_body_searches_every_activity_of_the_user_newest_first(service):
    response = search({})

    assert response.status_code == 200
    assert service.calls == [
        {
            "activity_filter": ActivityFilter(user_id=USER_ID),
            "order": NEWEST_FIRST,
            "limit": 50,
            "offset": 0,
        }
    ]


def test_the_filters_are_passed_to_the_service(service):
    search(
        {
            "after": "2026-08-01",
            "before": "2026-11-01",
            "sources": ["strava"],
            "trainingTypes": [RunType.SHORT_INTERVALS.value, RunType.LONG_INTERVALS.value],
            "distance": {"min": 8000, "max": 15000},
            "duration": {"min": 2400},
            "pace": {"max": 330},
            "avgHr": {"max": 160},
        }
    )

    assert service.calls[0]["activity_filter"] == ActivityFilter(
        user_id=USER_ID,
        after=date(2026, 8, 1),
        before=date(2026, 11, 1),
        sources=frozenset({Provider.STRAVA}),
        training_types=frozenset({RunType.SHORT_INTERVALS, RunType.LONG_INTERVALS}),
        distance=NumberRange(min=8000, max=15000),
        duration=NumberRange(min=2400),
        pace=NumberRange(max=330),
        avg_hr=NumberRange(max=160),
    )


def test_segment_groups_are_passed_to_the_service(service):
    search(
        {
            "segments": [
                {
                    "runTypes": [RunType.SHORT_INTERVALS.value],
                    "repDistance": {"value": 1000, "tolerance": 0.1},
                    "repCount": {"min": 5},
                    "pace": {"max": 200},
                    "avgRepDuration": {"max": 200},
                    "avgRecovery": {"max": 120},
                },
                {
                    "runTypes": [RunType.TEMPO.value],
                    "distance": {"min": 4000},
                    "duration": {"max": 1800},
                    "avgHr": {"max": 185},
                },
            ]
        }
    )

    assert service.calls[0]["activity_filter"].segments == (
        SegmentCriteria(
            run_types=frozenset({RunType.SHORT_INTERVALS}),
            rep_distance=NumberRange(min=900, max=1100),
            rep_count=NumberRange(min=5),
            pace=NumberRange(max=200),
            avg_rep_duration=NumberRange(max=200),
            avg_recovery=NumberRange(max=120),
        ),
        SegmentCriteria(
            run_types=frozenset({RunType.TEMPO}),
            distance=NumberRange(min=4000),
            duration=NumberRange(max=1800),
            avg_hr=NumberRange(max=185),
        ),
    )


@pytest.mark.parametrize(
    ("rep_distance", "expected"),
    [
        pytest.param({"value": 1000}, NumberRange(min=950, max=1050), id="default tolerance"),
        pytest.param(
            {"value": 400, "tolerance": 0}, NumberRange(min=400, max=400), id="exact distance"
        ),
        pytest.param(
            {"value": 50, "tolerance": 0.13}, NumberRange(min=43.5, max=56.5), id="no float error"
        ),
    ],
)
def test_a_rep_distance_becomes_the_range_within_its_tolerance(service, rep_distance, expected):
    search({"segments": [{"repDistance": rep_distance}]})

    assert service.calls[0]["activity_filter"].segments == (SegmentCriteria(rep_distance=expected),)


def test_the_order_and_page_are_passed_to_the_service(service):
    search({"sort": {"by": "pace", "order": "asc"}, "limit": 20, "offset": 40})

    call = service.calls[0]
    assert call["order"] == ActivityOrder(key=ActivitySortKey.PACE, descending=False)
    assert (call["limit"], call["offset"]) == (20, 40)


def test_the_page_found_comes_back_with_its_total(service):
    service.page = ActivityPage(records=[make_activity("strava_1", user_id=USER_ID)], total=7)

    response = search({"limit": 1})

    assert response.status_code == 200
    assert response.json()["total"] == 7
    assert [item["activityId"] for item in response.json()["items"]] == ["strava_1"]


def test_the_every_parameter_example_sets_every_field_and_is_accepted(service):
    example = SEARCH_EXAMPLES["everything"]["value"]

    response = search(example)

    assert set(example) == set(ActivitySearchRequest.model_fields)
    for name in ("distance", "duration", "pace", "avgHr"):
        assert set(example[name]) == set(NumberRangeModel.model_fields)
    assert set(example["sort"]) == set(ActivitySortModel.model_fields)
    groups = example["segments"]
    assert {name for group in groups for name in group} == set(SegmentCriteriaModel.model_fields)
    for group in groups:
        for name, value in group.items():
            if name == "repDistance":
                assert set(value) == set(RepDistanceModel.model_fields)
            elif name != "runTypes":
                assert set(value) == set(NumberRangeModel.model_fields)
    assert response.status_code == 200
    activity_filter = service.calls[0]["activity_filter"]
    assert all(getattr(activity_filter, field.name) is not None for field in fields(ActivityFilter))
    assert all(
        any(getattr(criteria, field.name) is not None for criteria in activity_filter.segments)
        for field in fields(SegmentCriteria)
    )


@pytest.mark.parametrize("name", list(SEARCH_EXAMPLES))
def test_every_example_is_accepted(service, name):
    response = search(SEARCH_EXAMPLES[name]["value"])

    assert response.status_code == 200


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"distance": {"min": 10, "max": 5}}, id="min above max"),
        pytest.param({"duration": {"min": -1}}, id="negative bound"),
        pytest.param({"pace": {"min": 0}}, id="zero pace"),
        pytest.param({"avgHr": {"max": "high"}}, id="non-numeric bound"),
        pytest.param({"distance": {"min": 1, "unit": "km"}}, id="unknown range field"),
        pytest.param({"after": "2026-10-01", "before": "2026-10-01"}, id="empty date window"),
        pytest.param({"after": "2026-11-01", "before": "2026-10-01"}, id="inverted date window"),
        pytest.param({"sources": []}, id="no sources"),
        pytest.param({"sources": ["polar"]}, id="unknown source"),
        pytest.param({"trainingTypes": []}, id="no training types"),
        pytest.param({"trainingTypes": [99]}, id="unknown training type"),
        pytest.param({"sort": {"by": "name"}}, id="unknown sort key"),
        pytest.param({"sort": {"order": "up"}}, id="unknown sort order"),
        pytest.param({"limit": 0}, id="limit too small"),
        pytest.param({"limit": 201}, id="limit too large"),
        pytest.param({"offset": -1}, id="negative offset"),
        pytest.param({"userId": "user-2"}, id="another user"),
        pytest.param({"segments": []}, id="no segment groups"),
        pytest.param(
            {"segments": [{"repCount": {"min": 1}}] * (MAX_SEGMENT_GROUPS + 1)},
            id="too many segment groups",
        ),
        pytest.param({"segments": [{}]}, id="empty segment group"),
        pytest.param({"segments": [{"runTypes": None}]}, id="segment group of nulls"),
        pytest.param({"segments": [{"runTypes": []}]}, id="no segment run types"),
        pytest.param({"segments": [{"runTypes": [99]}]}, id="unknown segment run type"),
        pytest.param({"segments": [{"role": "work"}]}, id="unknown segment group field"),
        pytest.param(
            {"segments": [{"repCount": {"min": 8, "max": 5}}]}, id="segment min above max"
        ),
        pytest.param({"segments": [{"pace": {"max": 0}}]}, id="zero segment pace"),
        pytest.param({"segments": [{"repDistance": {"value": 0}}]}, id="zero rep distance"),
        pytest.param({"segments": [{"repDistance": {"tolerance": 0.1}}]}, id="no rep distance"),
        pytest.param(
            {"segments": [{"repDistance": {"value": 1000, "tolerance": -0.1}}]},
            id="negative tolerance",
        ),
        pytest.param(
            {"segments": [{"repDistance": {"value": 1000, "tolerance": 1.5}}]},
            id="tolerance above 1",
        ),
    ],
)
def test_an_invalid_body_is_rejected(service, body):
    response = search(body)

    assert response.status_code == 422
    assert service.calls == []


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_a_bound_that_is_not_finite_is_rejected(service, value):
    response = TestClient(app).post(
        SEARCH,
        content=f'{{"distance": {{"min": {value}}}}}',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422
    assert [error["type"] for error in response.json()["detail"]] == ["finite_number"]
    assert service.calls == []


def test_the_request_examples_are_documented_and_valid():
    documented = app.openapi()["paths"]["/api/v1/activities/search"]["post"]["requestBody"][
        "content"
    ]["application/json"]

    assert documented["examples"].keys() == SEARCH_EXAMPLES.keys()
    for example in SEARCH_EXAMPLES.values():
        ActivitySearchRequest.model_validate(example["value"])
