import React from 'react';
import { cn } from '@/lib/utils';
import { Provider } from '@/types/enums';
import { garminDeviceLabel } from '@/utils/attribution';
import { PROVIDER_DISPLAY, isProvider } from '@/utils/providers';

export interface ProviderBadgeProps {
  source?: string | Provider | null;
  /** The recording device; a Garmin badge reads "Garmin {deviceName}" */
  deviceName?: string | null;
  className?: string;
}

interface BadgeStyle {
  badge: string;
  dot: string;
}

// Brand tints; dark-mode text uses a lighter shade so it keeps AA contrast on cockpit cards
const PROVIDER_BADGE_STYLES: Record<Provider, BadgeStyle> = {
  [Provider.STRAVA]: {
    badge: 'bg-[#FC5200]/10 text-[#FC5200] border-[#FC5200]/25 dark:bg-[#FC5200]/20 dark:text-[#FF7438]',
    dot: 'bg-[#FC5200]',
  },
  [Provider.GARMIN]: {
    badge: 'bg-[#007CC3]/10 text-[#007CC3] border-[#007CC3]/25 dark:bg-[#00B2FF]/15 dark:text-[#00B2FF] dark:border-[#00B2FF]/25',
    dot: 'bg-[#007CC3] dark:bg-[#00B2FF]',
  },
  [Provider.INTERVALS]: {
    badge: 'bg-[#E0064A]/10 text-[#E0064A] border-[#E0064A]/25 dark:bg-[#E0064A]/20 dark:text-[#FF5C8A] dark:border-[#FF5C8A]/25',
    dot: 'bg-[#E0064A] dark:bg-[#FF5C8A]',
  },
};

const FALLBACK_STYLE: BadgeStyle = {
  badge: 'bg-muted text-muted-foreground border-border/60',
  dot: 'bg-muted-foreground',
};

export const ProviderBadge: React.FC<ProviderBadgeProps> = ({
  source,
  deviceName,
  className,
}) => {
  const normalized = source?.toLowerCase();
  const provider = isProvider(normalized) ? normalized : null;

  const label =
    provider === Provider.GARMIN
      ? garminDeviceLabel(deviceName)
      : provider
        ? PROVIDER_DISPLAY[provider]
        : source || 'Manual';
  const style = provider ? PROVIDER_BADGE_STYLES[provider] : FALLBACK_STYLE;

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-sm border px-2 py-0.5 text-xs font-semibold tracking-tight transition-colors',
        style.badge,
        className
      )}
    >
      <span className={cn('h-1.5 w-1.5 rounded-full shrink-0', style.dot)} />
      {label}
    </span>
  );
};
