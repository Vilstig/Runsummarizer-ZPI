import apiClient from './client';
import type { SyncStartedResponse, SyncStatusResponse } from '@/types/api';
import type { Provider } from '@/types/enums';

export interface TriggerSyncParams {
  after?: string;
  before?: string;
  limit?: number;
}

export const triggerSync = async (
  provider: Provider,
  params: TriggerSyncParams = {}
): Promise<SyncStartedResponse> => {
  const { data } = await apiClient.post<SyncStartedResponse>(
    `/api/v1/sync/${provider}`,
    null,
    { params }
  );
  return data;
};

export const getSyncStatus = async (
  provider: Provider
): Promise<SyncStatusResponse> => {
  const { data } = await apiClient.get<SyncStatusResponse>(
    `/api/v1/sync/${provider}/status`
  );
  return data;
};
