from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Summary:
    """An activity's summary text."""

    text: str
    text_edited_at: datetime | None = None  # None: the text was not edited by hand
