"""Editing a summary's text, and what a change of the laps or segments does to it."""

from datetime import UTC, datetime

import pytest

from app.domain.errors import TextPolicyRequiredError
from app.domain.models import Summary
from app.summaries.editing import (
    TextPolicy,
    check_text_policy,
    edit_text,
    is_edited,
    refreshed_summary,
)

EARLIER = datetime(2026, 10, 19, 18, 0, tzinfo=UTC)
NOW = datetime(2026, 10, 20, 8, 0, tzinfo=UTC)

GENERATED = Summary(text="2.00 km\n10x250m")
TEXT_EDITED = Summary(text="Moje interwały", text_edited_at=EARLIER)
# the summary generated over new laps or segments
FRESH = Summary(text="2.00 km\n5x250m\n5x200m")


# ---------- is_edited ----------


@pytest.mark.parametrize(("summary", "edited"), [(GENERATED, False), (TEXT_EDITED, True)])
def test_a_summary_is_edited_once_its_text_is(summary, edited):
    assert is_edited(summary) is edited


# ---------- edit_text ----------


def test_editing_the_text_replaces_it_and_flags_it():
    assert edit_text(GENERATED, "Moje interwały", NOW) == Summary(
        text="Moje interwały", text_edited_at=NOW
    )


def test_editing_edited_text_again_moves_its_edit_time():
    assert edit_text(TEXT_EDITED, "Inne słowa", NOW) == Summary(
        text="Inne słowa", text_edited_at=NOW
    )


# ---------- check_text_policy ----------


@pytest.mark.parametrize(
    ("summary", "policy"),
    [(GENERATED, None), (TEXT_EDITED, TextPolicy.KEEP), (TEXT_EDITED, TextPolicy.REGENERATE)],
)
def test_a_policy_is_needed_only_for_edited_text(summary, policy):
    check_text_policy(summary, policy)


def test_edited_text_without_a_policy_is_refused():
    with pytest.raises(TextPolicyRequiredError):
        check_text_policy(TEXT_EDITED, None)


# ---------- refreshed_summary ----------


@pytest.mark.parametrize("policy", [None, *TextPolicy])
def test_a_summary_whose_text_was_not_edited_is_the_fresh_one(policy):
    assert refreshed_summary(GENERATED, FRESH, policy) == FRESH


def test_edited_text_needs_a_policy():
    with pytest.raises(TextPolicyRequiredError):
        refreshed_summary(TEXT_EDITED, FRESH, None)


def test_keep_leaves_the_edited_text():
    assert refreshed_summary(TEXT_EDITED, FRESH, TextPolicy.KEEP) == TEXT_EDITED


def test_regenerate_gives_the_fresh_summary():
    assert refreshed_summary(TEXT_EDITED, FRESH, TextPolicy.REGENERATE) == FRESH
