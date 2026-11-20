import React from 'react';
import { SyncState } from '@/types/enums';
import { cn } from '@/lib/utils';
import { RefreshCw } from 'lucide-react';

export interface SyncStatusBadgeProps {
  state?: SyncState;
  /** Without it the badge only shows the state */
  onClick?: () => void;
  className?: string;
  isTriggering?: boolean;
  /** Display name of the provider the status is for, e.g. 'Strava' */
  providerName?: string;
}

export const SyncStatusBadge: React.FC<SyncStatusBadgeProps> = ({
  state = SyncState.IDLE,
  onClick,
  className,
  isTriggering = false,
  providerName,
}) => {
  const config = {
    [SyncState.IDLE]: {
      label: 'Synced',
      dotClass: 'bg-[#10B981]',
      containerClass:
        'bg-[#ECFDF5] text-[#059669] border-[#A7F3D0] dark:bg-[#132A1C] dark:text-[#34D399] dark:border-[#1C432C]',
      animate: false,
    },
    [SyncState.SYNCING]: {
      label: 'Syncing runs...',
      dotClass: 'bg-[#F59E0B]',
      containerClass:
        'bg-[#FFFBEB] text-[#D97706] border-[#FDE68A] dark:bg-[#2D2013] dark:text-[#FBBF24] dark:border-[#4E3719]',
      animate: true,
    },
    [SyncState.NEEDS_RECONNECT]: {
      label: providerName ? `Reconnect ${providerName}` : 'Reconnect',
      dotClass: 'bg-destructive',
      containerClass:
        'bg-destructive/10 text-destructive border-destructive/25',
      animate: false,
    },
  }[state];

  const content = (
    <>
      <span
        className={cn(
          'h-2 w-2 rounded-full shrink-0',
          config.dotClass,
          (config.animate || isTriggering) && 'animate-ping'
        )}
      />
      <span>{isTriggering ? 'Starting sync...' : config.label}</span>
      {onClick && state === SyncState.IDLE && (
        <RefreshCw className="h-3 w-3 ml-0.5 text-muted-foreground transition-transform duration-150 hover:rotate-90" />
      )}
    </>
  );
  const baseClass = cn(
    'inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-semibold transition-all duration-150 ease-out select-none',
    config.containerClass
  );

  if (!onClick) {
    return (
      <span className={cn(baseClass, className)}>
        {content}
      </span>
    );
  }

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={state === SyncState.SYNCING || isTriggering}
      className={cn(
        baseClass,
        'cursor-pointer hover:brightness-110 active:scale-[0.97]',
        className
      )}
    >
      {content}
    </button>
  );
};