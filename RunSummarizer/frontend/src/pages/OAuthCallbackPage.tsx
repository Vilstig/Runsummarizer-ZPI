import React from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { providerKeys, syncKeys } from '@/api/keys';
import { PROVIDER_CONNECT_NAME, isProvider, oauthCallbackErrorMessage } from '@/utils/providers';

const SETTINGS_PATH = '/settings?tab=integrations';
const TOAST_ID = 'oauth-callback';

export const OAuthCallbackPage: React.FC = () => {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  React.useEffect(() => {
    const provider = searchParams.get('provider');
    const error = searchParams.get('error');

    // Opened without the backend's redirect parameters: nothing to report
    if (!isProvider(provider)) {
      navigate(SETTINGS_PATH, { replace: true });
      return;
    }

    queryClient.invalidateQueries({ queryKey: providerKeys.all });
    queryClient.invalidateQueries({ queryKey: syncKeys.all });

    if (error) {
      toast.error(oauthCallbackErrorMessage(error, provider), { id: TOAST_ID });
      navigate(SETTINGS_PATH, { replace: true });
      return;
    }

    toast.success(`Connected to ${PROVIDER_CONNECT_NAME[provider]}`, { id: TOAST_ID });
    const timeout = setTimeout(() => {
      navigate(SETTINGS_PATH, { replace: true });
    }, 1200);

    return () => clearTimeout(timeout);
  }, [searchParams, navigate, queryClient]);

  return (
    <div className="flex h-screen w-screen flex-col items-center justify-center bg-background p-4 text-center">
      <div className="rounded-2xl border border-border bg-card p-8 shadow-lg max-w-sm w-full space-y-4">
        <LoadingSpinner size="lg" label="Connecting your account..." />
        <h2 className="text-base font-bold text-foreground">
          Linking Account
        </h2>
        <p className="text-xs text-muted-foreground">
          You will be taken back to Settings in a moment.
        </p>
      </div>
    </div>
  );
};

export default OAuthCallbackPage;
