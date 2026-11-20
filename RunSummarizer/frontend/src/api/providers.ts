import apiClient from './client';
import type { ConnectResponse, ProviderStatus } from '@/types/api';
import type { Provider } from '@/types/enums';

export const getProviders = async (): Promise<ProviderStatus[]> => {
  const { data } = await apiClient.get<ProviderStatus[]>('/api/v1/providers');
  return data;
};

export const getProviderConnectUrl = async (
  provider: Provider
): Promise<ConnectResponse> => {
  const { data } = await apiClient.get<ConnectResponse>(
    `/api/v1/providers/${provider}/connect`,
    // Stores the HttpOnly oauth_state and oauth_secrets cookies the callback checks.
    { withCredentials: true }
  );
  return data;
};

export const disconnectProvider = async (provider: Provider): Promise<void> => {
  await apiClient.delete(`/api/v1/providers/${provider}/connection`);
};
