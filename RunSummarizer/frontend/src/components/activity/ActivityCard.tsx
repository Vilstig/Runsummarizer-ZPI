import React from 'react';
import { Link } from 'react-router-dom';
import type { Activity } from '@/types/api';
import { RunTypeBadge } from './RunTypeBadge';
import { ProviderBadge } from '../common/ProviderBadge';
import {
  formatDate,
  formatDistance,
  formatDuration,
  formatPace,
} from '@/utils/formatters';
import { ChevronRight, Heart } from 'lucide-react';
import { cn } from '@/lib/utils';

export interface ActivityCardProps {
  activity: Activity;
  className?: string;
}

export const ActivityCard: React.FC<ActivityCardProps> = ({
  activity,
  className,
}) => {
  const { processed_data } = activity;
  const distance = formatDistance(processed_data.distance);
  const duration = formatDuration(processed_data.duration);
  const pace = formatPace(processed_data.speed);
  const dateFormatted = formatDate(processed_data.startTimeLocal);

  return (
    <Link
      to={`/activities/${activity.activityId}`}
      aria-label={`View workout details: ${processed_data.name || 'Running Workout'}, ${distance}, ${duration}, pace ${pace}`}
      className={cn(
        'group flex flex-col sm:flex-row sm:items-center justify-between gap-3.5 rounded-lg border border-border bg-card p-3.5 sm:p-4 text-card-foreground shadow-xs transition-all duration-150 ease-out hover:border-[#FC5200]/50 hover:bg-muted/30 active:scale-[0.99] touch-manipulation min-h-[44px] focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-primary select-none',
        className
      )}
    >
      {/* Left: Title, Date, Source Badge */}
      <div className="flex-1 space-y-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <h3 className="font-bold text-foreground text-sm sm:text-base truncate group-hover:text-[#FC5200] transition-colors duration-150">
            {processed_data.name || 'Running Workout'}
          </h3>
          <ProviderBadge source={activity.source} deviceName={processed_data.deviceName} />
        </div>
        <p className="text-xs text-muted-foreground">{dateFormatted}</p>
      </div>

      {/* Center: Key Running Telemetry (Distance, Pace, Time, HR) with tabular numerals */}
      <div className="grid grid-cols-3 sm:flex sm:items-center gap-3 sm:gap-6 text-xs sm:text-sm text-foreground">
        <div>
          <span className="text-[10px] sm:text-xs font-semibold uppercase tracking-wider text-muted-foreground block">
            Distance
          </span>
          <span className="font-extrabold tabular-nums text-sm sm:text-base tracking-tight text-foreground">
            {distance}
          </span>
        </div>

        <div>
          <span className="text-[10px] sm:text-xs font-semibold uppercase tracking-wider text-muted-foreground block">
            Pace
          </span>
          <span className="font-bold tabular-nums tracking-tight text-[#FC5200] text-sm sm:text-base">
            {pace}
          </span>
        </div>

        <div>
          <span className="text-[10px] sm:text-xs font-semibold uppercase tracking-wider text-muted-foreground block">
            Time
          </span>
          <span className="font-semibold tabular-nums tracking-tight text-foreground/90 text-sm sm:text-base">
            {duration}
          </span>
        </div>

        {processed_data.avgHr != null && (
          <div className="hidden md:block">
            <span className="text-[10px] sm:text-xs font-semibold uppercase tracking-wider text-muted-foreground block">
              Avg HR
            </span>
            <span className="font-bold tabular-nums tracking-tight flex items-center gap-1 text-sm sm:text-base text-foreground">
              <Heart className="h-3.5 w-3.5 text-red-500 fill-red-500" />
              {Math.round(processed_data.avgHr)}
            </span>
          </div>
        )}
      </div>

      {/* Right: RunType badge + Arrow */}
      <div className="flex items-center justify-between sm:justify-end gap-2.5 pt-2 sm:pt-0 border-t sm:border-0 border-border">
        <RunTypeBadge
          typeId={processed_data.trainingTypeId}
          typeName={processed_data.trainingTypeDisplay}
        />
        <ChevronRight className="h-4 w-4 text-muted-foreground group-hover:translate-x-0.5 group-hover:text-[#FC5200] transition-all duration-150 shrink-0" />
      </div>
    </Link>
  );
};
