import React from 'react';
import { cn } from '@/lib/utils';
import {
  GARMIN_DERIVED_DATA_NOTE,
  garminAttributionLabels,
  type AttributedActivity,
} from '@/utils/attribution';

export interface GarminAttributionProps {
  /** The activities whose data the view shows; renders nothing when none is from Garmin */
  activities: readonly AttributedActivity[];
  /** Also names Garmin as a source of insights computed from the data (lap types, summaries, estimates) */
  derived?: boolean;
  className?: string;
}

/**
 * "Garmin {device}" line for a view showing Garmin data, placed beneath or next to the
 * view's title. Lists each Garmin device once.
 */
export const GarminAttribution: React.FC<GarminAttributionProps> = ({
  activities,
  derived = false,
  className,
}) => {
  const labels = garminAttributionLabels(activities);
  if (labels.length === 0) return null;

  return (
    <div className={cn('text-xs leading-snug text-muted-foreground', className)}>
      <p className="font-semibold text-foreground/80">{labels.join(', ')}</p>
      {derived && <p className="mt-0.5">{GARMIN_DERIVED_DATA_NOTE}</p>}
    </div>
  );
};
