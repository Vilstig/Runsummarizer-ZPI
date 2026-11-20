import React from 'react';
import { Trophy, Zap } from 'lucide-react';
import type { RacePredictions } from '@/utils/raceEstimator';
import type { Activity } from '@/types/api';
import { GarminAttribution } from '@/components/common/GarminAttribution';
import { formatDuration, formatPace } from '@/utils/formatters';

export interface RacePredictionsCardProps {
  predictions: RacePredictions | null;
  /** The runs the predictions are computed from */
  sourceRuns?: Activity[];
}

/**
 * RacePredictionsCard: Monochromatic Garmin-style Race Predictor Cockpit.
 * Pete Riegel formula projections with tabular numerals and disciplined Strava Orange pace accents.
 */
export const RacePredictionsCard: React.FC<RacePredictionsCardProps> = ({
  predictions,
  sourceRuns = [],
}) => {
  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <Trophy className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-xs sm:text-sm font-bold uppercase tracking-wider text-foreground">
            Race Predictor (Pete Riegel Model)
          </h2>
        </div>
        <span className="text-[11px] text-muted-foreground font-semibold">
          Estimated from recent top efforts
        </span>
      </div>
      {predictions && <GarminAttribution activities={sourceRuns} derived />}

      <div className="rounded-xl border border-border bg-card p-3.5 sm:p-5 shadow-xs">
        {predictions ? (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2.5 sm:gap-4">
            {[
              {
                title: '5K',
                distance: '5.0 km',
                time: predictions.fiveK,
                pace: 5000 / predictions.fiveK,
              },
              {
                title: '10K',
                distance: '10.0 km',
                time: predictions.tenK,
                pace: 10000 / predictions.tenK,
              },
              {
                title: 'Half Marathon',
                distance: '21.1 km',
                time: predictions.halfMarathon,
                pace: 21097.5 / predictions.halfMarathon,
              },
              {
                title: 'Marathon',
                distance: '42.2 km',
                time: predictions.marathon,
                pace: 42195 / predictions.marathon,
              },
            ].map((race) => (
              <div
                key={race.title}
                className="rounded-lg border border-border bg-muted/30 p-3 sm:p-4 text-left transition-all hover:border-neutral-400 dark:hover:border-neutral-600"
              >
                <div className="flex items-center justify-between">
                  <span className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
                    {race.title}
                  </span>
                  <span className="text-[10px] font-mono text-muted-foreground font-semibold">
                    {race.distance}
                  </span>
                </div>

                <div className="mt-2">
                  <span className="text-xl sm:text-2xl font-extrabold tabular-nums tracking-tight text-foreground block font-mono">
                    {formatDuration(race.time)}
                  </span>
                  <div className="mt-1 flex items-center gap-1 text-xs font-bold tabular-nums text-[#FC5200]">
                    <Zap className="h-3 w-3" />
                    <span>{formatPace(race.pace)}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="p-8 text-center text-xs sm:text-sm text-muted-foreground font-medium">
            Log at least one run of 2.5 km or more to unlock Pete Riegel race form estimations.
          </div>
        )}
      </div>
    </section>
  );
};
