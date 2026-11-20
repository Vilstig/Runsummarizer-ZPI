import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { getSyncStatus, triggerSync, type TriggerSyncParams } from '@/api/sync';
import { activitiesKeys, providerKeys, syncKeys } from '@/api/keys';
import type { SyncStatusResponse } from '@/types/api';
import { SyncState, type Provider } from '@/types/enums';
import { getApiErrorStatus, handleApiError } from '@/utils/errors';
import { PROVIDER_DISPLAY } from '@/utils/providers';

/**
 * The user's sync status with `provider`; idle until a provider is given.
 * Activity queries are refreshed when a sync finishes.
 */
export const useSyncStatus = (provider: Provider | null | undefined) => {
  const queryClient = useQueryClient();
  const queryKey = syncKeys.status(provider as Provider);

  return useQuery({
    queryKey,
    queryFn: async () => {
      const previous = queryClient.getQueryData<SyncStatusResponse>(queryKey)?.state;
      const status = await getSyncStatus(provider as Provider);
      if (previous === SyncState.SYNCING && status.state !== SyncState.SYNCING) {
        queryClient.invalidateQueries({ queryKey: activitiesKeys.all });
      }
      return status;
    },
    enabled: Boolean(provider),
    staleTime: 0,
    refetchInterval: (query) => {
      const state = query.state.data?.state;
      // Only poll when actively syncing; avoid polling indefinitely when IDLE or reconnect needed
      return state === SyncState.SYNCING ? 3000 : false;
    },
  });
};

export interface TriggerSyncVariables {
  provider: Provider;
  params?: TriggerSyncParams;
}

export const useTriggerSync = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ provider, params = {} }: TriggerSyncVariables) =>
      triggerSync(provider, params),
    onSuccess: (data, { provider }) => {
      queryClient.invalidateQueries({ queryKey: syncKeys.status(provider) });
      queryClient.invalidateQueries({ queryKey: activitiesKeys.lists() });
      const name = PROVIDER_DISPLAY[provider];
      toast.success(
        data.requested
          ? `Sync requested from ${name}`
          : `Sync started: queued ${data.queued} ${data.queued === 1 ? 'run' : 'runs'} from ${name}`
      );
    },
    onError: (error: unknown, { provider }) => {
      if (getApiErrorStatus(error) === 409) {
        // Not connected to this provider, or its authorization was revoked
        queryClient.invalidateQueries({ queryKey: providerKeys.all });
        queryClient.invalidateQueries({ queryKey: syncKeys.status(provider) });
      }
      handleApiError(error, 'Failed to start sync');
    },
  });
};
