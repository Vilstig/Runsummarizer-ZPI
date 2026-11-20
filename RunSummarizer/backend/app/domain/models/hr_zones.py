from dataclasses import dataclass
from datetime import datetime

# lower bounds of HR zones 2-5, in bpm; zone 1 is everything below the zone 2 bound
ZoneBounds = tuple[float, float, float, float]


@dataclass(frozen=True)
class HeartRateZones:
    zone1_bpm: int  # lower bound of HR zone 1, in bpm
    zone2_bpm: int  # lower bound of HR zone 2, in bpm
    zone3_bpm: int  # lower bound of HR zone 3, in bpm
    zone4_bpm: int  # lower bound of HR zone 4, in bpm
    zone5_bpm: int  # lower bound of HR zone 5, in bpm


@dataclass(frozen=True)
class HeartRateZonesRecord:
    """Zones in effect from ``valid_from`` until the next record's ``valid_from``."""

    valid_from: datetime
    zones: HeartRateZones
