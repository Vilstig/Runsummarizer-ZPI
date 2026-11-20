from enum import IntEnum, StrEnum


class Provider(StrEnum):
    STRAVA = "strava"
    GARMIN = "garmin"
    INTERVALS = "intervals"


class SegmentRole(StrEnum):
    PREAMBLE = "preamble"
    WORK = "work"
    EPILOGUE = "epilogue"
    BREAK = "break"


class LapType(IntEnum):
    RUN = 0
    RECOVERY = 1
    REST = 2

    @property
    def display_name(self):
        names = {
            self.RUN: "Run",
            self.RECOVERY: "Recovery",
            self.REST: "Rest",
        }
        return names.get(self, "Unknown")


class RunType(IntEnum):
    EASY = 0
    SHORT_INTERVALS = 1
    LONG_INTERVALS = 2
    TEMPO = 3
    RACE = 4
    TIME_INTERVALS = 5
    PROGRESSION_RUN = 6

    @property
    def display_name(self):
        names = {
            self.EASY: "Easy",
            self.SHORT_INTERVALS: "Short Intervals",
            self.LONG_INTERVALS: "Long Intervals",
            self.TEMPO: "Tempo",
            self.RACE: "Race",
            self.TIME_INTERVALS: "Time Intervals",
            self.PROGRESSION_RUN: "Progression run",
        }
        return names.get(self, "Unknown")

    @property
    def display_name_polish(self):
        names = {
            self.EASY: "Bieg spokojny",
            self.SHORT_INTERVALS: "Interwały",
            self.LONG_INTERVALS: "Długie interwały",
            self.TEMPO: "Tempo",
            self.RACE: "Zawody",
            self.TIME_INTERVALS: "Interwały czasowe",
            self.PROGRESSION_RUN: "Bieg progresywny",
        }
        return names.get(self, "Nieznany")
