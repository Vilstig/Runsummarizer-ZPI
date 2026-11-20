import { useQuery } from '@tanstack/react-query';
import { getActivities, type GetActivitiesParams } from '@/api/activities';
import { activitiesKeys } from '@/api/keys';

/**
 * Hook to query historical or filtered activity lists with optimized cache policy.
 * Historical running logs remain stable: 5 min staleTime, 15 min gcTime.
 */
export const useActivities = (filters: GetActivitiesParams = {}) => {
  return useQuery({
    queryKey: activitiesKeys.list(filters),
    queryFn: () => getActivities(filters),
    staleTime: 5 * 60 * 1000,
    gcTime: 15 * 60 * 1000,
  });
};