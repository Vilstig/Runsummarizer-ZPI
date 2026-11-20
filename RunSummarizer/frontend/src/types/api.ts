import type { LapType, Provider, SegmentRole, Sex, SyncState, TextPolicy } from './enums';

export interface HeartRateZoneResponse {
  zone: number;
  minBpm: number | null;
  maxBpm: number | null;
  time: number;
}

/** @deprecated alias for backward compatibility */
export type HeartRateZones = HeartRateZoneResponse[];

export interface LapResponse {
  lapIndex: number;
  typeId: LapType | null;
  typeName: string | null;
  typeDisplay: string | null;
  distance: number | null;
  duration: number | null;
  speed: number | null;
  avgHr: number | null;
  maxHr: number | null;
  elevationGain: number | null;
  version: number;
}

export interface SegmentResponse {
  startLapIndex: number;
  endLapIndex: number;
  runTypeId: number;
  runTypeDisplay: string;
  label: string | null;
  role: SegmentRole | string;
  runTypeAuto: boolean;
}

export interface ProcessedData {
  activityId: string;
  name: string | null;
  startTimeLocal: string | null;
  distance: number | null;
  duration: number | null;
  speed: number | null;
  avgHr: number | null;
  maxHr: number | null;
  elevationGain: number | null;
  heartRateZones: HeartRateZoneResponse[];
  laps: LapResponse[];
  segments: SegmentResponse[];
  trainingTypeId: number | null;
  trainingTypeName: string | null;
  trainingTypeDisplay: string | null;
  source: string | null;
  /** Model of the device that recorded the run, e.g. 'Forerunner 965'; always null for Strava */
  deviceName: string | null;
}

export interface Activity {
  id?: string | null;
  activityId: string;
  source: string;
  userId: string;
  summary: string | null;
  summaryTextEdited: boolean;
  segmentsEdited: boolean;
  processed_data: ProcessedData;
}

export interface UserProfile {
  age: number | null;
  sex: Sex | null;
  height_cm: number | null;
  max_hr: number | null;
}

export interface UserHeartRateZones {
  zone1_bpm: number;
  zone2_bpm: number;
  zone3_bpm: number;
  zone4_bpm: number;
  zone5_bpm: number;
}

export interface ActivityStreamsResponse {
  time?: number[] | null;
  distance?: number[] | null;
  heartrate?: number[] | null;
  velocity?: number[] | null;
  altitude?: number[] | null;
}

export interface LapEdit {
  lapIndex: number;
  typeId?: LapType | null;
  distance?: number | null;
}

export interface EditLapsRequest {
  laps: LapEdit[];
  textPolicy?: TextPolicy | null;
}

export interface ResetLapsRequest {
  lapIndexes?: number[] | null;
  textPolicy?: TextPolicy | null;
}

export interface UserSegmentModel {
  startLapIndex: number;
  role: SegmentRole;
  runTypeId?: number | null;
}

export interface SetSegmentsRequest {
  segments: UserSegmentModel[] | null;
  textPolicy?: TextPolicy | null;
}

export interface SummaryEditRequest {
  text: string;
}

export interface ConnectResponse {
  authorize_url: string;
}

export interface ProviderStatus {
  provider: Provider;
  configured: boolean;
  connected: boolean;
  sync_state: SyncState;
  /** False for push-only providers: `POST /sync/{provider}` answers 409 and runs arrive on their own */
  can_sync: boolean;
}

export interface SyncStartedResponse {
  queued: number;
  /** The provider sends the runs later by webhook; `queued` is 0. */
  requested: boolean;
}

export interface SyncStatusResponse {
  state: SyncState;
}

/** Values from `min` to `max`, both inclusive; either may be left out. */
export interface NumberRange {
  min?: number;
  max?: number;
}

/** Conditions one work segment of an activity meets, every one given. */
export interface SegmentCriteria {
  runTypes?: number[]; // RunType ids
  distance?: NumberRange; // m; for intervals, the reps together
  duration?: NumberRange; // s; for intervals, the reps together
  pace?: NumberRange; // s/km, min is the fastest
  avgHr?: NumberRange; // bpm
  repCount?: NumberRange;
  repDistance?: { value: number; tolerance?: number }; // m; tolerance is a fraction of value
  avgRepDuration?: NumberRange; // s
  avgRecovery?: NumberRange; // s
}

export type ActivitySortKey = 'startTime' | 'distance' | 'duration' | 'pace';

export interface ActivitySort {
  by: ActivitySortKey;
  order: 'asc' | 'desc'; // pace 'asc' is fastest first
}

/** The filters of `POST /activities/search`; an activity must match all of them. */
export interface ActivitySearchFilters {
  after?: string; // first day included, yyyy-MM-dd
  before?: string; // first day excluded, yyyy-MM-dd
  sources?: string[];
  trainingTypes?: number[]; // RunType ids
  distance?: NumberRange; // m
  duration?: NumberRange; // s
  pace?: NumberRange; // s/km, min is the fastest
  avgHr?: NumberRange; // bpm
  segments?: SegmentCriteria[];
}

export interface ActivitySearchRequest extends ActivitySearchFilters {
  sort?: ActivitySort;
  limit?: number;
  offset?: number;
}

export interface ActivitySearchResponse {
  items: Activity[];
  total: number;
}

/** A user's totals of the Monday-based week starting `weekStart`; zero when the week has
 * no activities. */
export interface WeekTotalsDto {
  weekStart: string; // yyyy-MM-dd
  distance: number; // m
  duration: number; // s
  elevationGain: number; // m
}

export interface WeeklySummaryResponse {
  /** Oldest first; the last entry is the current week. */
  weeks: WeekTotalsDto[];
}
