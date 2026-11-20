import React from 'react';
import { useNavigate } from 'react-router-dom';
import { BrandLogo } from '../common/BrandLogo';
import { SyncStatusBadge } from '../common/SyncStatusBadge';
import { UserNav } from './UserNav';
import { useSyncStatus, useTriggerSync } from '@/hooks/useSyncPolling';
import { useConnectedProvider } from '@/hooks/useProviders';
import { SyncState } from '@/types/enums';
import { PROVIDER_CONNECT_NAME, providerCanSync } from '@/utils/providers';
import { isMockEnabled } from '@/api/client';
import { mockStorage } from '@/mock/mockStorage';

export const Header: React.FC = () => {
  const navigate = useNavigate();
  const { data: connected } = useConnectedProvider();
  const provider = connected?.provider ?? null;
  const { data: syncStatus } = useSyncStatus(provider);
  const { mutate: triggerSync, isPending: isSyncing } = useTriggerSync();

  const needsReconnect = syncStatus?.state === SyncState.NEEDS_RECONNECT;
  const canSync = connected ? providerCanSync(connected) : false;
  // Push-only providers can't be synced; their badge only opens Settings to reconnect
  const badgeClickable = canSync || needsReconnect;

  const handleSyncClick = () => {
    if (!provider) return;
    if (needsReconnect) {
      navigate('/settings?tab=integrations');
    } else if (canSync) {
      triggerSync({ provider, params: { limit: 30 } });
    }
  };

  const handleResetMockData = () => {
    mockStorage.resetAll();
    window.location.reload();
  };

  return (
    <header className="sticky top-0 z-30 flex h-16 w-full items-center justify-between border-b border-border bg-background/95 px-3.5 sm:px-6 backdrop-blur-md">
      {/* Left: Mobile Brand Header linked to Home (Desktop brand is in Sidebar) */}
      <div className="flex items-center gap-2.5">
        <div className="flex items-center md:hidden">
          <BrandLogo size="sm" showText={false} />
        </div>
      </div>

      {/* Right: Sync Status and Unified Account/Settings Menu */}
      <div className="flex items-center gap-3">
        {isMockEnabled && (
          <button
            type="button"
            onClick={handleResetMockData}
            title="Mock mode active: click to reset sample workouts and biometrics"
            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[10px] sm:text-[11px] font-mono font-semibold bg-muted text-foreground border border-border hover:bg-muted/80 transition-all cursor-pointer"
          >
            <span className="h-1.5 w-1.5 rounded-full bg-foreground/50 animate-pulse" />
            <span className="hidden sm:inline">Mock Data: ON</span>
            <span className="sm:hidden">Mock</span>
            <span className="opacity-70">(Reset)</span>
          </button>
        )}

        {provider && (
          <>
            <SyncStatusBadge
              state={syncStatus?.state}
              isTriggering={isSyncing}
              onClick={badgeClickable ? handleSyncClick : undefined}
              providerName={PROVIDER_CONNECT_NAME[provider]}
            />

            <div className="h-5 w-px bg-border hidden sm:block" />
          </>
        )}

        <UserNav />
      </div>
    </header>
  );
};
