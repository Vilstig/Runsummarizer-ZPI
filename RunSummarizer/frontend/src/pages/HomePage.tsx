import React from 'react';
import { Link } from 'react-router-dom';
import { addDays, format } from 'date-fns';
import { Compass, Flame, PlusCircle, Settings } from 'lucide-react';
import { useActivities } from '@/hooks/useActivities';
import { useMediaQuery } from '@/hooks/useMediaQuery';
import { useConnectedProvider } from '@/hooks/useProviders';
import { useWeeklySummary } from '@/hooks/useWeeklySummary';
import { ActivityCard } from '@/components/activity/ActivityCard';
import { RacePredictionsCard } from '@/components/home/RacePredictionsCard';
import { WeeklySummaryCard } from '@/components/home/WeeklySummaryCard';
import { Button } from '@/components/ui/button';
import { estimateRaceTimes } from '@/utils/raceEstimator';
import { PROVIDER_CONNECT_NAME, providerCanSync } from '@/utils/providers';
import type { Activity, ProviderStatus } from '@/types/api';

interface EmptyStateCopy {
  text: string;
  action: string;
  icon: React.ElementType;
}

/** `connected` is undefined while the provider list is unknown (loading or failed) */
const emptyStateCopy = (connected: ProviderStatus | null | undefined): EmptyStateCopy => {
  if (connected === undefined) {
    return {
      text: 'Your runs will appear here once they are imported from your fitness provider.',
      action: 'Open Settings',
      icon: Settings,
    };
  }
  if (connected === null) {
    return {
      text: 'Connect a fitness provider in Settings to import your runs and generate summaries.',
      action: 'Connect a provider',
      icon: PlusCircle,
    };
  }
  const name = PROVIDER_CONNECT_NAME[connected.provider];
  if (!providerCanSync(connected)) {
    return {
      text: `Your next run will appear here after your watch syncs with ${name}. Runs recorded before you connected aren't imported.`,
      action: 'Open Settings',
      icon: Settings,
    };
  }
  return {
    text: `Sync ${name} in Settings to import your recent runs and generate summaries.`,
    action: 'Go to Sync',
    icon: Settings,
  };
};

export const HomePage: React.FC = () => {
  const now = React.useMemo(() => new Date(), []);

  // Show more weeks of history as the screen widens (sm / lg breakpoints)
  const isSmUp = useMediaQuery('(min-width: 640px)');
  const isLgUp = useMediaQuery('(min-width: 1024px)');
  const weekCount = isLgUp ? 24 : isSmUp ? 16 : 12;

  const { weeks, isLoading: loadingWeekly } = useWeeklySummary(now, weekCount);

  // Recent runs (newest 6) feed race predictions
  const { data: recentRuns, isLoading: loadingRecent } = useActivities({
    limit: 6,
    include_laps: false,
  });

  const { data: connectedProvider } = useConnectedProvider();

  // Today's activities, a small bounded request of its own
  const { data: todayRuns = [] } = useActivities({
    after: format(now, 'yyyy-MM-dd'),
    before: format(addDays(now, 1), 'yyyy-MM-dd'),
    include_laps: false,
  });

  // The recent run race predictions use: the fastest one over 2.5 km and 5 min,
  // else any run over 10 min
  const predictionRun = React.useMemo((): Activity | null => {
    if (!recentRuns || recentRuns.length === 0) return null;

    const qualifiedRuns = recentRuns.filter(
      (r) =>
        (r.processed_data.distance || 0) >= 2500 &&
        (r.processed_data.duration || 0) > 300
    );

    if (qualifiedRuns.length === 0) {
      return recentRuns.find((r) => (r.processed_data.duration || 0) > 600) ?? null;
    }

    qualifiedRuns.sort((a, b) => {
      const speedA = a.processed_data.speed || 0;
      const speedB = b.processed_data.speed || 0;
      return speedB - speedA;
    });

    return qualifiedRuns[0] ?? null;
  }, [recentRuns]);

  const raceEstimations = React.useMemo(
    () =>
      predictionRun
        ? estimateRaceTimes(
            predictionRun.processed_data.distance || 0,
            predictionRun.processed_data.duration || 0
          )
        : null,
    [predictionRun]
  );

  const emptyState = emptyStateCopy(connectedProvider);
  const EmptyStateIcon = emptyState.icon;

  return (
    <div className="space-y-6 sm:space-y-8 pb-10">
      <WeeklySummaryCard weeks={weeks} isLoading={loadingWeekly} />

      {/* Today's activities, styled as an athletic cockpit section */}
      {todayRuns.length > 0 && (
        <section className="space-y-3">
          <div className="flex items-center gap-2">
            <span className="flex h-5 w-5 items-center justify-center rounded-full bg-muted text-muted-foreground">
              <Flame className="h-3.5 w-3.5 fill-current" />
            </span>
            <h2 className="text-xs sm:text-sm font-bold uppercase tracking-wider text-foreground">
              Today's Activities
            </h2>
          </div>
          <div className="space-y-2.5">
            {todayRuns.map((run) => (
              <ActivityCard key={run.activityId} activity={run} />
            ))}
          </div>
        </section>
      )}

      {/* New users: prompt to connect a provider until the first run is synced */}
      {!loadingRecent && recentRuns?.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border bg-card p-6 sm:p-10 text-center">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-primary/10 text-primary">
            <Compass className="h-6 w-6" />
          </div>
          <h3 className="mt-3 text-base sm:text-lg font-bold text-foreground">
            No activities synced yet
          </h3>
          <p className="mt-1 text-xs sm:text-sm text-muted-foreground max-w-sm mx-auto">
            {emptyState.text}
          </p>
          <div className="mt-5 flex justify-center">
            <Button asChild size="default" className="min-h-[44px] touch-manipulation">
              <Link to="/settings?tab=integrations">
                <EmptyStateIcon className="h-4 w-4 mr-1.5" />
                {emptyState.action}
              </Link>
            </Button>
          </div>
        </div>
      ) : (
        <RacePredictionsCard
          predictions={raceEstimations}
          sourceRuns={predictionRun ? [predictionRun] : []}
        />
      )}
    </div>
  );
};

export default HomePage;
