import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import {
  getUserProfile,
  updateUserProfile,
  getUserHeartRateZones,
  updateUserHeartRateZones,
} from '@/api/users';
import { userKeys } from '@/api/keys';
import { handleApiError } from '@/utils/errors';
import type { UserProfile, UserHeartRateZones } from '@/types/api';

/**
 * Runner profile biometrics hook with co-located cache policies.
 */
export const useProfile = () => {
  return useQuery({
    queryKey: userKeys.profile(),
    queryFn: getUserProfile,
    staleTime: 10 * 60 * 1000,
    gcTime: 30 * 60 * 1000,
  });
};

export const useUpdateProfile = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (profile: UserProfile) => updateUserProfile(profile),
    onSuccess: (saved) => {
      queryClient.setQueryData(userKeys.profile(), saved);
      toast.success('Runner biometrics updated');
    },
    onError: (error: unknown) => {
      handleApiError(error, 'Failed to update runner biometrics');
    },
  });
};

export const useHeartRateZones = () => {
  return useQuery({
    queryKey: userKeys.hrZones(),
    queryFn: getUserHeartRateZones,
    staleTime: 10 * 60 * 1000,
    gcTime: 30 * 60 * 1000,
  });
};

export const useUpdateHeartRateZones = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (zones: UserHeartRateZones) => updateUserHeartRateZones(zones),
    onSuccess: (saved) => {
      queryClient.setQueryData(userKeys.hrZones(), saved);
      toast.success('Heart rate zones updated');
    },
    onError: (error: unknown) => {
      handleApiError(error, 'Failed to update heart rate zones');
    },
  });
};
