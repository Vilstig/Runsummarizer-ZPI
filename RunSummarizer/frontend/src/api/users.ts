import apiClient from './client';
import type { UserProfile, UserHeartRateZones } from '@/types/api';

export const getUserProfile = async (): Promise<UserProfile> => {
  const { data } = await apiClient.get<UserProfile>(
    '/api/v1/users/me/profile'
  );
  return data;
};

export const updateUserProfile = async (
  profile: UserProfile
): Promise<UserProfile> => {
  const { data } = await apiClient.put<UserProfile>(
    '/api/v1/users/me/profile',
    profile
  );
  return data;
};

export const getUserHeartRateZones = async (): Promise<UserHeartRateZones | null> => {
  const { data } = await apiClient.get<UserHeartRateZones | null>(
    '/api/v1/users/me/hr-zones'
  );
  return data;
};

export const updateUserHeartRateZones = async (
  zones: UserHeartRateZones
): Promise<UserHeartRateZones> => {
  const { data } = await apiClient.put<UserHeartRateZones>(
    '/api/v1/users/me/hr-zones',
    zones
  );
  return data;
};