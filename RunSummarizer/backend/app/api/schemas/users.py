from __future__ import annotations

from itertools import pairwise

from pydantic import BaseModel, Field, model_validator

from app.domain.enums import Sex


class UserProfileSchema(BaseModel):
    age: int | None = Field(None, ge=5, le=99)  # years
    sex: Sex | None = None
    height_cm: float | None = Field(None, ge=50, le=240)
    max_hr: int | None = Field(None, ge=0, le=256)  # bpm


class HeartRateZonesSchema(BaseModel):
    zone1_bpm: int = Field(ge=0, le=256)  # lower bound of HR zone 1, in bpm
    zone2_bpm: int = Field(ge=0, le=256)  # lower bound of HR zone 2, in bpm
    zone3_bpm: int = Field(ge=0, le=256)  # lower bound of HR zone 3, in bpm
    zone4_bpm: int = Field(ge=0, le=256)  # lower bound of HR zone 4, in bpm
    zone5_bpm: int = Field(ge=0, le=256)  # lower bound of HR zone 5, in bpm

    @model_validator(mode="after")
    def zone_bounds_increase(self) -> HeartRateZonesSchema:
        bounds = (self.zone1_bpm, self.zone2_bpm, self.zone3_bpm, self.zone4_bpm, self.zone5_bpm)
        if any(later <= earlier for earlier, later in pairwise(bounds)):
            raise ValueError("heart rate zone lower bounds must be strictly increasing")
        return self
