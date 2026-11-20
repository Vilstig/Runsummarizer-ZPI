import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { searchActivities } from '@/api/activities';
import { activitiesKeys } from '@/api/keys';
import type { ActivitySearchRequest } from '@/types/api';

/**
 * Hook to run an activity search; idle while `request` is null.
 * Keeps the previous page on screen while the next one loads.
 */
export const useActivitySearch = (request: ActivitySearchRequest | null) => {
  return useQuery({
    queryKey: activitiesKeys.search(request),
    queryFn: () => searchActivities(request as ActivitySearchRequest),
    enabled: request !== null,
    placeholderData: keepPreviousData,
    staleTime: 5 * 60 * 1000,
    gcTime: 15 * 60 * 1000,
  });
};
