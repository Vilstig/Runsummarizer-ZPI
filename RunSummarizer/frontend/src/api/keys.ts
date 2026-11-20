import type { GetActivitiesParams, GetWeeklySummaryParams } from './activities';
import type { Provider, StreamType } from '@/types/enums';
import type { ActivitySearchRequest } from '@/types/api';

/**
 * Type-safe, hierarchical Query Key Factory based on TanStack Query v5 architecture.
 * Enables granular, atomic cache invalidations and co-located query lifecycles.
 */
export const activitiesKeys = {
  all: ['activities'] as const,
  lists: () => [...activitiesKeys.all, 'list'] as const,
  list: (params: GetActivitiesParams = {}) => [...activitiesKeys.lists(), params] as const,
  weeklySummary: (params: GetWeeklySummaryParams = {}) =>
    [...activitiesKeys.lists(), 'weekly-summary', params] as const,
  searches: () => [...activitiesKeys.all, 'search'] as const,
  search: (request: ActivitySearchRequest | null) =>
    [...activitiesKeys.searches(), request] as const,
  details: () => [...activitiesKeys.all, 'detail'] as const,
  detail: (id: string) => [...activitiesKeys.details(), id] as const,
  laps: (id: string) => [...activitiesKeys.detail(id), 'laps'] as const,
  streams: (id: string, keys: StreamType[] = []) =>
    [...activitiesKeys.detail(id), 'streams', keys] as const,
};

export const userKeys = {
  all: ['user'] as const,
  profile: () => [...userKeys.all, 'profile'] as const,
  hrZones: () => [...userKeys.all, 'hr-zones'] as const,
};

export const providerKeys = {
  all: ['providers'] as const,
  list: () => [...providerKeys.all, 'list'] as const,
};

export const syncKeys = {
  all: ['sync'] as const,
  statuses: () => [...syncKeys.all, 'status'] as const,
  status: (provider: Provider) => [...syncKeys.statuses(), provider] as const,
};

/**
 * Backwards compatibility queryKeys alias
 */
export const queryKeys = {
  activities: activitiesKeys,
  profile: userKeys.profile,
  hrZones: userKeys.hrZones,
  providers: providerKeys.list,
  sync: syncKeys.status,
};