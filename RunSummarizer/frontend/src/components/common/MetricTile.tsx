import React from 'react';
import { cn } from '@/lib/utils';

export interface MetricTileProps {
  label: string;
  value: React.ReactNode;
  unit?: string;
  icon?: React.ReactNode;
  subtext?: string;
  className?: string;
}

/**
 * MetricTile: Athletic Data Cockpit Tile (Garmin & Strava standard)
 * Tabular numerals, micro uppercase tracking, hairline boundary.
 */
export const MetricTile: React.FC<MetricTileProps> = ({
  label,
  value,
  unit,
  icon,
  subtext,
  className,
}) => {
  return (
    <div
      role="group"
      aria-label={`${label}: ${value}${unit ? ` ${unit}` : ''}`}
      className={cn(
        'relative overflow-hidden rounded-lg border border-border bg-card p-3.5 sm:p-4 text-card-foreground shadow-xs transition-all duration-150 hover:border-neutral-400 dark:hover:border-neutral-700',
        className
      )}
    >
      <div className="flex items-center justify-between text-muted-foreground">
        <span className="text-[10px] sm:text-xs font-bold uppercase tracking-wider truncate">
          {label}
        </span>
        {icon && (
          <span aria-hidden="true" className="text-muted-foreground shrink-0">
            {icon}
          </span>
        )}
      </div>

      <div className="mt-2 flex items-baseline gap-1 min-w-0">
        <span className="text-xl sm:text-2xl lg:text-3xl font-extrabold tabular-nums tracking-tight text-foreground truncate">
          {value}
        </span>
        {unit && (
          <span className="text-xs font-semibold text-muted-foreground shrink-0">
            {unit}
          </span>
        )}
      </div>

      {subtext && (
        <p className="mt-1 text-[11px] text-muted-foreground truncate font-normal">
          {subtext}
        </p>
      )}
    </div>
  );
};
