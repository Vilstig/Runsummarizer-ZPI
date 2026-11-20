import apiClient from './client';
import type {
  Activity,
  ActivitySearchRequest,
  ActivitySearchResponse,
  ActivityStreamsResponse,
  EditLapsRequest,
  LapResponse,
  ResetLapsRequest,
  SetSegmentsRequest,
  SummaryEditRequest,
  WeeklySummaryResponse,
} from '@/types/api';
import type { Provider, StreamType } from '@/types/enums';

export interface GetActivitiesParams {
  limit?: number;
  skip?: number;
  source?: Provider;
  include_laps?: boolean;
  after?: string;
  before?: string;
}

export const getActivities = async (
  params: GetActivitiesParams = {}
): Promise<Activity[]> => {
  const { data } = await apiClient.get<Activity[]>('/api/v1/activities', {
    params,
  });
  return data;
};

export interface GetWeeklySummaryParams {
  /** How many weeks to return; 1-52, 12 by default. */
  weeks?: number;
  /** A day in the last week to include, yyyy-MM-dd; today by default. */
  date?: string;
}

export const getWeeklySummary = async (
  params: GetWeeklySummaryParams = {}
): Promise<WeeklySummaryResponse> => {
  const { data } = await apiClient.get<WeeklySummaryResponse>(
    '/api/v1/activities/weekly-summary',
    { params }
  );
  return data;
};

export const searchActivities = async (
  request: ActivitySearchRequest
): Promise<ActivitySearchResponse> => {
  const { data } = await apiClient.post<ActivitySearchResponse>(
    '/api/v1/activities/search',
    request
  );
  return data;
};

export const getActivity = async (activityId: string): Promise<Activity> => {
  const { data } = await apiClient.get<Activity>(
    `/api/v1/activities/${activityId}`
  );
  return data;
};

export const getActivityLaps = async (
  activityId: string
): Promise<LapResponse[]> => {
  const { data } = await apiClient.get<LapResponse[]>(
    `/api/v1/activities/${activityId}/laps`
  );
  return data;
};

export const getActivityStreams = async (
  activityId: string,
  keys: StreamType[] = []
): Promise<ActivityStreamsResponse> => {
  const params = keys.length > 0 ? { keys: keys.join(',') } : undefined;
  const { data } = await apiClient.get<ActivityStreamsResponse>(
    `/api/v1/activities/${activityId}/streams`,
    { params }
  );
  return data;
};

export const updateActivityLaps = async (
  activityId: string,
  payload: EditLapsRequest
): Promise<Activity> => {
  const { data } = await apiClient.patch<Activity>(
    `/api/v1/activities/${activityId}/laps`,
    payload
  );
  return data;
};

export const resetActivityLaps = async (
  activityId: string,
  payload: ResetLapsRequest = {}
): Promise<Activity> => {
  const { data } = await apiClient.post<Activity>(
    `/api/v1/activities/${activityId}/laps/reset`,
    payload
  );
  return data;
};

export const setActivitySegments = async (
  activityId: string,
  payload: SetSegmentsRequest
): Promise<Activity> => {
  const { data } = await apiClient.put<Activity>(
    `/api/v1/activities/${activityId}/segments`,
    payload
  );
  return data;
};

export const editActivitySummary = async (
  activityId: string,
  payload: SummaryEditRequest
): Promise<Activity> => {
  const { data } = await apiClient.patch<Activity>(
    `/api/v1/activities/${activityId}/summary`,
    payload
  );
  return data;
};

export const resetActivitySummary = async (
  activityId: string
): Promise<Activity> => {
  const { data } = await apiClient.post<Activity>(
    `/api/v1/activities/${activityId}/summary/reset`
  );
  return data;
};

export const deleteActivity = async (activityId: string): Promise<void> => {
  await apiClient.delete(`/api/v1/activities/${activityId}`);
};