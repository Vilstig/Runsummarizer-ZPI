import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { disconnectProvider, getProviderConnectUrl, getProviders } from '@/api/providers';
import { providerKeys, syncKeys } from '@/api/keys';
import type { ProviderStatus } from '@/types/api';
import type { Provider } from '@/types/enums';
import { getApiErrorStatus, handleApiError } from '@/utils/errors';
import { PROVIDER_CONNECT_NAME } from '@/utils/providers';

const selectConfigured = (providers: ProviderStatus[]) =>
  providers.filter((provider) => provider.configured);

const selectConnected = (providers: ProviderStatus[]) =>
  providers.find((provider) => provider.configured && provider.connected) ?? null;

/** The providers the server is configured for, in the server's order. */
export const useProviders = () => {
  return useQuery({
    queryKey: providerKeys.list(),
    queryFn: getProviders,
    staleTime: 60 * 1000,
    select: selectConfigured,
  });
};

/** The provider the user is connected to (at most one), or `null`. */
export const useConnectedProvider = () => {
  return useQuery({
    queryKey: providerKeys.list(),
    queryFn: getProviders,
    staleTime: 60 * 1000,
    select: selectConnected,
  });
};

/** Starts a provider's OAuth flow by sending the browser to its authorize URL. */
export const useConnectProvider = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (provider: Provider) => getProviderConnectUrl(provider),
    onSuccess: ({ authorize_url }) => {
      window.location.href = authorize_url;
    },
    onError: (error: unknown, provider) => {
      const name = PROVIDER_CONNECT_NAME[provider];
      if (getApiErrorStatus(error) === 409) {
        queryClient.invalidateQueries({ queryKey: providerKeys.all });
        toast.error(`Disconnect your connected provider before connecting ${name}.`);
        return;
      }
      handleApiError(error, `Could not start connecting ${name}`);
    },
  });
};

export const useDisconnectProvider = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (provider: Provider) => disconnectProvider(provider),
    onSuccess: (_data, provider) => {
      queryClient.invalidateQueries({ queryKey: providerKeys.all });
      queryClient.invalidateQueries({ queryKey: syncKeys.all });
      toast.success(`Disconnected ${PROVIDER_CONNECT_NAME[provider]}`);
    },
    onError: (error: unknown, provider) => {
      handleApiError(error, `Failed to disconnect ${PROVIDER_CONNECT_NAME[provider]}`);
    },
  });
};
