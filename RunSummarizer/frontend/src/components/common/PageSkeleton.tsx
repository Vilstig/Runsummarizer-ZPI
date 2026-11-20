import React from 'react';

/**
 * Athletic card skeleton for route-level code splitting fallbacks.
 * Matches container layout to prevent Cumulative Layout Shift (CLS) on lazy chunk hydration.
 */
export const PageSkeleton: React.FC = () => {
  return (
    <div
      role="status"
      aria-label="Loading..."
      className="space-y-6 animate-pulse pb-12"
    >
      {/* Header bar skeleton */}
      <div className="space-y-2">
        <div className="h-7 w-48 rounded-sm bg-muted/60" />
        <div className="h-4 w-72 rounded-sm bg-muted/40" />
      </div>

      {/* Metric tiles row skeleton */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[1, 2, 3, 4].map((i) => (
          <div
            key={i}
            className="h-24 rounded-md border border-border bg-card p-4 space-y-2"
          >
            <div className="h-3 w-16 rounded-sm bg-muted/60" />
            <div className="h-6 w-24 rounded-sm bg-muted/40" />
          </div>
        ))}
      </div>

      {/* Main content / chart skeleton */}
      <div className="h-72 w-full rounded-md border border-border bg-card p-6 flex flex-col justify-between">
        <div className="h-4 w-36 rounded-sm bg-muted/60" />
        <div className="h-48 w-full rounded-sm bg-muted/30" />
      </div>
    </div>
  );
};
