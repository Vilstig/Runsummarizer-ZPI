"""The user's edits of an activity's summary text, and what a change of the activity's laps
or segments does to it."""

from dataclasses import replace
from datetime import datetime
from enum import StrEnum

from app.domain.errors import TextPolicyRequiredError
from app.domain.models import Summary


class TextPolicy(StrEnum):
    """What a change of the activity's laps or segments does to a summary text the user
    edited."""

    REGENERATE = "regenerate"  # the text is written again from the new laps and segments
    KEEP = "keep"  # the user's text stays


def is_edited(summary: Summary) -> bool:
    """Whether the user edited the summary's text."""
    return summary.text_edited_at is not None


def edit_text(summary: Summary, text: str, now: datetime) -> Summary:
    """The summary with the user's ``text``, edited at ``now``."""
    return replace(summary, text=text, text_edited_at=now)


def check_text_policy(summary: Summary, text_policy: TextPolicy | None) -> None:
    """Raise ``TextPolicyRequiredError`` when the user edited the text of ``summary`` and
    ``text_policy`` is None."""
    if is_edited(summary) and text_policy is None:
        raise TextPolicyRequiredError("The summary text was edited; say whether to keep it")


def refreshed_summary(summary: Summary, fresh: Summary, text_policy: TextPolicy | None) -> Summary:
    """The summary after the activity's laps or segments changed, ``fresh`` being the
    summary generated over them.

    It is ``fresh``, unless the user edited the text of ``summary``; then ``text_policy``
    decides, and ``KEEP`` gives ``summary``. Raises as ``check_text_policy`` does.
    """
    check_text_policy(summary, text_policy)
    if is_edited(summary) and text_policy == TextPolicy.KEEP:
        return summary
    return fresh
