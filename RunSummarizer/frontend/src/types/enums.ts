export enum Provider {
  STRAVA = 'strava',
  GARMIN = 'garmin',
  INTERVALS = 'intervals',
}

export enum LapType {
  RUN = 0,
  RECOVERY = 1,
  REST = 2,
}

export const LAP_TYPE_DISPLAY: Record<LapType, string> = {
  [LapType.RUN]: 'Run',
  [LapType.RECOVERY]: 'Recovery',
  [LapType.REST]: 'Rest',
};

export enum SegmentRole {
  PREAMBLE = 'preamble',
  WORK = 'work',
  EPILOGUE = 'epilogue',
  BREAK = 'break',
}

export const SEGMENT_ROLE_DISPLAY: Record<SegmentRole, string> = {
  [SegmentRole.PREAMBLE]: 'Warm-up',
  [SegmentRole.WORK]: 'Work',
  [SegmentRole.EPILOGUE]: 'Cool-down',
  [SegmentRole.BREAK]: 'Break',
};

export enum RunType {
  EASY = 0,
  SHORT_INTERVALS = 1,
  LONG_INTERVALS = 2,
  TEMPO = 3,
  RACE = 4,
  TIME_INTERVALS = 5,
  PROGRESSION_RUN = 6,
}

export const RUN_TYPE_DISPLAY: Record<RunType, string> = {
  [RunType.EASY]: 'Easy',
  [RunType.SHORT_INTERVALS]: 'Short Intervals',
  [RunType.LONG_INTERVALS]: 'Long Intervals',
  [RunType.TEMPO]: 'Tempo',
  [RunType.RACE]: 'Race',
  [RunType.TIME_INTERVALS]: 'Time Intervals',
  [RunType.PROGRESSION_RUN]: 'Progression Run',
};

export enum StreamType {
  TIME = 'time',
  DISTANCE = 'distance',
  HEARTRATE = 'heartrate',
  VELOCITY = 'velocity',
  ALTITUDE = 'altitude',
}

export enum TextPolicy {
  REGENERATE = 'regenerate',
  KEEP = 'keep',
}

export enum SyncState {
  NEEDS_RECONNECT = 'needs_reconnect',
  SYNCING = 'syncing',
  IDLE = 'idle',
}

export enum Sex {
  MALE = 'male',
  FEMALE = 'female',
}