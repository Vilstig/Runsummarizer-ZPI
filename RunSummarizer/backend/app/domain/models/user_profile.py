from dataclasses import dataclass

from app.domain.enums import Sex


@dataclass(frozen=True)
class UserProfile:
    age: int | None = None  # years
    sex: Sex | None = None
    height_cm: float | None = None
    max_hr: int | None = None  # bpm
