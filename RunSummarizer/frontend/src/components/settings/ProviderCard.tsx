import React from 'react';
import { Link as LinkIcon, Unlink } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import type { ProviderStatus } from '@/types/api';
import { Provider } from '@/types/enums';
import { PROVIDER_CONNECT_NAME } from '@/utils/providers';
import { cn } from '@/lib/utils';
import garminConnectAppTile from '@/assets/garmin-connect-app.png';

interface ProviderCardMeta {
  titleClass: string;
  /** App tile shown beside the title */
  tile?: string;
  connectLabel: string;
  connectClass: string;
  description: string;
}

const PROVIDER_CARD_META: Record<Provider, ProviderCardMeta> = {
  [Provider.STRAVA]: {
    titleClass: 'text-[#FC5200]',
    connectLabel: 'Connect Strava',
    connectClass: 'bg-[#FC5200] hover:bg-[#FC5200]/90 text-white',
    description: 'Imports your runs with laps, pace and heart rate.',
  },
  [Provider.GARMIN]: {
    titleClass: 'text-foreground',
    tile: garminConnectAppTile,
    connectLabel: 'Connect to Garmin Connect',
    connectClass: 'bg-[#007cc3] hover:bg-[#007cc3]/90 text-white',
    description: 'Imports new runs from your Garmin device with laps, pace and heart rate.',
  },
  [Provider.INTERVALS]: {
    titleClass: 'text-[#E0064A] dark:text-[#FF5C8A]',
    connectLabel: 'Connect Intervals.icu',
    connectClass: 'bg-[#E0064A] hover:bg-[#E0064A]/90 text-white',
    description:
      "Imports runs from the watches and apps you sync to Intervals.icu, with laps, pace and heart rate. Runs that reach Intervals.icu from Strava can't be imported.",
  },
};

export interface ProviderCardProps {
  status: ProviderStatus;
  /** Another provider the user is connected to, which blocks connecting this one */
  blockedBy: Provider | null;
  connecting: boolean;
  onConnect: () => void;
  onDisconnect: () => void;
  /** Rendered below the actions while the provider is connected */
  children?: React.ReactNode;
}

export const ProviderCard: React.FC<ProviderCardProps> = ({
  status,
  blockedBy,
  connecting,
  onConnect,
  onDisconnect,
  children,
}) => {
  const meta = PROVIDER_CARD_META[status.provider];
  const name = PROVIDER_CONNECT_NAME[status.provider];

  return (
    <div className="flex flex-col justify-between rounded-xl border border-border/80 bg-muted/20 p-4 sm:p-5 space-y-4">
      <div className="space-y-1.5">
        <div className="flex items-center justify-between gap-2">
          <span className="flex min-w-0 items-center gap-2.5">
            {meta.tile && (
              <img
                src={meta.tile}
                alt=""
                width={40}
                height={40}
                className="h-10 w-10 shrink-0 rounded-lg"
              />
            )}
            <span className={cn('font-bold text-base', meta.titleClass)}>{name}</span>
          </span>
          {status.connected ? (
            <span className="text-xs font-semibold text-emerald-600 dark:text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded-full border border-emerald-500/20">
              Connected
            </span>
          ) : (
            <span className="text-xs font-semibold text-muted-foreground bg-muted px-2 py-0.5 rounded-full border border-border">
              Not connected
            </span>
          )}
        </div>
        <p className="text-xs text-muted-foreground leading-relaxed">{meta.description}</p>
      </div>

      <div className="pt-2 flex flex-col gap-2.5">
        <div className="flex flex-col sm:flex-row gap-2">
          <Button
            type="button"
            onClick={onConnect}
            disabled={connecting || blockedBy !== null}
            className={cn(
              'flex-1 min-h-[44px] font-semibold touch-manipulation',
              meta.connectClass
            )}
          >
            {connecting ? (
              <LoadingSpinner size="sm" className="p-0 mr-1.5" />
            ) : (
              <LinkIcon className="h-4 w-4 mr-1.5" />
            )}
            {status.connected ? 'Reconnect' : meta.connectLabel}
          </Button>

          {status.connected && (
            <Button
              type="button"
              variant="outline"
              onClick={onDisconnect}
              className="min-h-[44px] border-destructive/30 text-destructive hover:bg-destructive/10 touch-manipulation"
            >
              <Unlink className="h-4 w-4 mr-1" />
              Disconnect
            </Button>
          )}
        </div>

        {blockedBy !== null && (
          <p className="text-xs text-muted-foreground leading-relaxed">
            You can be connected to one provider at a time. Disconnect{' '}
            {PROVIDER_CONNECT_NAME[blockedBy]} to connect {name}.
          </p>
        )}

        {status.connected && children}
      </div>
    </div>
  );
};
