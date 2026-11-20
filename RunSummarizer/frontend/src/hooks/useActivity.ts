import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import {
  deleteActivity,
  editActivitySummary,
  getActivity,
  getActivityLaps,
  getActivityStreams,
  resetActivityLaps,
  resetActivitySummary,
  setActivitySegments,
  updateActivityLaps,
} from '@/api/activities';
import { activitiesKeys } from '@/api/keys';
import { handleApiError } from '@/utils/errors';
import type {
  EditLapsRequest,
  ResetLapsRequest,
  SetSegmentsRequest,
  SummaryEditRequest,
} from '@/types/api';
import type { StreamType } from '@/types/enums';

/**
 * Historical workout details hook with co-located cache policies.
 */
export const useActivity = (activityId: string) => {
  return useQuery({
    queryKey: activitiesKeys.detail(activityId),
    queryFn: () => getActivity(activityId),
    enabled: Boolean(activityId),
    staleTime: 5 * 60 * 1000,
    gcTime: 15 * 60 * 1000,
  });
};

export const useActivityLaps = (activityId: string) => {
  return useQuery({
    queryKey: activitiesKeys.laps(activityId),
    queryFn: () => getActivityLaps(activityId),
    enabled: Boolean(activityId),
    staleTime: 5 * 60 * 1000,
    gcTime: 15 * 60 * 1000,
  });
};

export const useActivityStreams = (activityId: string, keys: StreamType[] = []) => {
  return useQuery({
    queryKey: activitiesKeys.streams(activityId, keys),
    queryFn: () => getActivityStreams(activityId, keys),
    enabled: Boolean(activityId),
    staleTime: 10 * 60 * 1000,
    gcTime: 30 * 60 * 1000,
  });
};

/**
 * Mutation hooks with atomic cache updates and selective invalidation.
 */
export const useUpdateLaps = (activityId: string) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: EditLapsRequest) =>
      updateActivityLaps(activityId, payload),
    onSuccess: (updatedActivity) => {
      queryClient.setQueryData(activitiesKeys.detail(activityId), updatedActivity);
      queryClient.invalidateQueries({ queryKey: activitiesKeys.laps(activityId) });
      queryClient.invalidateQueries({ queryKey: activitiesKeys.lists() });
      toast.success('Laps updated & summary refreshed');
    },
    onError: (error: unknown) => {
      handleApiError(error, 'Failed to update laps');
    },
  });
};

export const useResetLaps = (activityId: string) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: ResetLapsRequest = {}) =>
      resetActivityLaps(activityId, payload),
    onSuccess: (updatedActivity) => {
      queryClient.setQueryData(activitiesKeys.detail(activityId), updatedActivity);
      queryClient.invalidateQueries({ queryKey: activitiesKeys.laps(activityId) });
      queryClient.invalidateQueries({ queryKey: activitiesKeys.lists() });
      toast.success('Laps reset to original measurements');
    },
    onError: (error: unknown) => {
      handleApiError(error, 'Failed to reset laps');
    },
  });
};

export const useEditSummary = (activityId: string) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: SummaryEditRequest) =>
      editActivitySummary(activityId, payload),
    onSuccess: (updatedActivity) => {
      queryClient.setQueryData(activitiesKeys.detail(activityId), updatedActivity);
      queryClient.invalidateQueries({ queryKey: activitiesKeys.lists() });
      toast.success('Workout summary updated');
    },
    onError: (error: unknown) => {
      handleApiError(error, 'Failed to update summary');
    },
  });
};

export const useResetSummary = (activityId: string) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => resetActivitySummary(activityId),
    onSuccess: (updatedActivity) => {
      queryClient.setQueryData(activitiesKeys.detail(activityId), updatedActivity);
      queryClient.invalidateQueries({ queryKey: activitiesKeys.lists() });
      toast.success('AI summary restored');
    },
    onError: (error: unknown) => {
      handleApiError(error, 'Failed to regenerate summary');
    },
  });
};

export const useSetSegments = (activityId: string) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: SetSegmentsRequest) =>
      setActivitySegments(activityId, payload),
    onSuccess: (updatedActivity) => {
      queryClient.setQueryData(activitiesKeys.detail(activityId), updatedActivity);
      queryClient.invalidateQueries({ queryKey: activitiesKeys.lists() });
      toast.success('Workout phases updated');
    },
    onError: (error: unknown) => {
      handleApiError(error, 'Failed to update segments');
    },
  });
};

export const useDeleteActivity = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (activityId: string) => deleteActivity(activityId),
    onSuccess: (_data, activityId) => {
      queryClient.removeQueries({ queryKey: activitiesKeys.detail(activityId) });
      queryClient.invalidateQueries({ queryKey: activitiesKeys.lists() });
      toast.success('Activity deleted successfully');
    },
    onError: (error: unknown) => {
      handleApiError(error, 'Failed to delete activity');
    },
  });
};