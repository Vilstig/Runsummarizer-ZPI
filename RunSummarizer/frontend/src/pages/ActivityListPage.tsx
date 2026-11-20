import React from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import {
  Activity as ActivityIcon,
  RotateCcw,
  Search,
  SlidersHorizontal,
} from 'lucide-react';
import { addDays, format, parseISO } from 'date-fns';
import { useActivities } from '@/hooks/useActivities';
import { ActivityCard } from '@/components/activity/ActivityCard';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { PROVIDER_DISPLAY, PROVIDER_ORDER, isProvider } from '@/utils/providers';
import { cn } from '@/lib/utils';

const PAGE_SIZE = 20;

export const ActivityListPage: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const [filtersOpen, setFiltersOpen] = React.useState(false);

  const sourceParam = searchParams.get('source') || 'all';
  const afterParam = searchParams.get('after') || '';
  const beforeParam = searchParams.get('before') || '';
  const skipParam = parseInt(searchParams.get('skip') || '0', 10);

  // Backend date filter 'before' is exclusive (< before 00:00:00).
  // Offset by +1 day so that any workout on the selected 'To' date is included.
  const beforeQuery = React.useMemo(() => {
    if (!beforeParam) return undefined;
    try {
      return format(addDays(parseISO(beforeParam), 1), 'yyyy-MM-dd');
    } catch {
      return beforeParam;
    }
  }, [beforeParam]);

  const { data: activities, isLoading } = useActivities({
    limit: PAGE_SIZE,
    skip: skipParam,
    source: isProvider(sourceParam) ? sourceParam : undefined,
    after: afterParam || undefined,
    before: beforeQuery,
    include_laps: false,
  });

  const handleSourceChange = (newSource: string) => {
    const next = new URLSearchParams(searchParams);
    if (newSource === 'all') {
      next.delete('source');
    } else {
      next.set('source', newSource);
    }
    next.set('skip', '0'); // reset page
    setSearchParams(next);
  };

  const handleDateChange = (type: 'after' | 'before', value: string) => {
    const next = new URLSearchParams(searchParams);
    if (value) {
      next.set(type, value);
    } else {
      next.delete(type);
    }
    next.set('skip', '0');
    setSearchParams(next);
  };

  const activeFilterCount =
    (sourceParam !== 'all' ? 1 : 0) + (afterParam ? 1 : 0) + (beforeParam ? 1 : 0);

  const resetFilters = () => {
    setSearchParams(new URLSearchParams());
  };

  const handlePrevPage = () => {
    const next = new URLSearchParams(searchParams);
    next.set('skip', Math.max(0, skipParam - PAGE_SIZE).toString());
    setSearchParams(next);
  };

  const handleNextPage = () => {
    const next = new URLSearchParams(searchParams);
    next.set('skip', (skipParam + PAGE_SIZE).toString());
    setSearchParams(next);
  };

  return (
    <div className="space-y-5 sm:space-y-6 pb-16">
      {/* Page Header (+ filter toggle on mobile) */}
      <div className="flex items-center justify-between gap-3">
        <div>
          <h1 className="text-xl sm:text-3xl font-bold tracking-tight text-foreground">
            Activities
          </h1>
          <p className="hidden sm:block text-sm text-muted-foreground mt-0.5">
            All your synced runs
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            asChild
            className="min-h-[44px] sm:min-h-[36px] text-xs touch-manipulation focus-visible:ring-2 focus-visible:ring-primary"
          >
            <Link to="/search">
              <Search className="h-3.5 w-3.5 mr-1" />
              Search
            </Link>
          </Button>
          <Button
            type="button"
            variant={activeFilterCount > 0 ? 'default' : 'outline'}
            size="sm"
            onClick={() => setFiltersOpen((open) => !open)}
            aria-expanded={filtersOpen}
            aria-controls="activity-filters"
            className="md:hidden min-h-[44px] text-xs touch-manipulation focus-visible:ring-2 focus-visible:ring-primary"
          >
            <SlidersHorizontal className="h-3.5 w-3.5 mr-1" />
            Filter{activeFilterCount > 0 && ` (${activeFilterCount})`}
          </Button>
        </div>
      </div>

      {/* Filter and Query Controls Bar: always shown on md+, toggled on mobile */}
      <div
        id="activity-filters"
        className={cn(
          filtersOpen ? 'flex' : 'hidden',
          'md:flex flex-col md:flex-row md:items-center justify-between gap-3 sm:gap-4 rounded-xl border border-border bg-card p-3.5 sm:p-4 shadow-xs'
        )}
      >
        {/* Source selector buttons */}
        <div className="flex items-center gap-1 rounded-xl bg-muted p-1">
          <Button
            type="button"
            variant={sourceParam === 'all' ? 'default' : 'ghost'}
            size="sm"
            onClick={() => handleSourceChange('all')}
            className="flex-1 sm:flex-initial min-h-[44px] sm:min-h-[34px] text-xs touch-manipulation focus-visible:ring-2 focus-visible:ring-primary"
          >
            <span className="sm:hidden">All</span>
            <span className="hidden sm:inline">All Sources</span>
          </Button>
          {PROVIDER_ORDER.map((provider) => (
            <Button
              key={provider}
              type="button"
              variant={sourceParam === provider ? 'default' : 'ghost'}
              size="sm"
              onClick={() => handleSourceChange(provider)}
              className="flex-1 sm:flex-initial min-h-[44px] sm:min-h-[34px] text-xs touch-manipulation focus-visible:ring-2 focus-visible:ring-primary"
            >
              {PROVIDER_DISPLAY[provider]}
            </Button>
          ))}
        </div>

        {/* Date Filters */}
        <div className="flex flex-wrap items-center gap-2.5 sm:gap-3 w-full md:w-auto">
          <div className="flex items-center gap-1.5 flex-1 min-w-[130px]">
            <label htmlFor="filter-from-date" className="text-xs text-muted-foreground font-semibold">
              From:
            </label>
            <Input
              id="filter-from-date"
              type="date"
              aria-label="Filter activities from date"
              value={afterParam}
              onChange={(e) => handleDateChange('after', e.target.value)}
              className="w-full sm:w-auto h-10 text-xs rounded-lg"
            />
          </div>

          <div className="flex items-center gap-1.5 flex-1 min-w-[130px]">
            <label htmlFor="filter-to-date" className="text-xs text-muted-foreground font-semibold">
              To:
            </label>
            <Input
              id="filter-to-date"
              type="date"
              aria-label="Filter activities to date"
              value={beforeParam}
              onChange={(e) => handleDateChange('before', e.target.value)}
              className="w-full sm:w-auto h-10 text-xs rounded-lg"
            />
          </div>

          {activeFilterCount > 0 && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={resetFilters}
              className="min-h-[44px] sm:min-h-[36px] text-xs touch-manipulation focus-visible:ring-2 focus-visible:ring-primary"
            >
              <RotateCcw className="h-3.5 w-3.5 mr-1" />
              Reset
            </Button>
          )}
        </div>
      </div>

      {/* Main Activity Cards List */}
      {isLoading ? (
        <div className="flex h-64 items-center justify-center rounded-2xl border border-border bg-card">
          <LoadingSpinner size="md" label="Loading activities..." />
        </div>
      ) : !activities || activities.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-border p-8 sm:p-12 text-center bg-card/40">
          <ActivityIcon className="h-10 w-10 text-muted-foreground mx-auto mb-3 opacity-60" />
          <h3 className="font-semibold text-foreground text-sm sm:text-base">
            No activities matching criteria
          </h3>
          <p className="text-xs text-muted-foreground max-w-sm mx-auto mt-1 mb-4">
            Try adjusting your provider filter or date ranges.
          </p>
          <div className="flex items-center justify-center gap-2.5 flex-wrap">
            <Button
              type="button"
              variant="outline"
              size="default"
              onClick={resetFilters}
              className="min-h-[44px] touch-manipulation focus-visible:ring-2 focus-visible:ring-primary"
            >
              Clear Active Filters
            </Button>
            <Button size="default" asChild className="min-h-[44px] touch-manipulation font-semibold focus-visible:ring-2 focus-visible:ring-primary">
              <Link to="/settings?tab=integrations">
                Manage Integrations & Sync
              </Link>
            </Button>
          </div>
        </div>
      ) : (
        <div className="space-y-2.5 sm:space-y-3">
          {activities.map((activity) => (
            <ActivityCard key={activity.activityId} activity={activity} />
          ))}

          {/* Pagination Controls with Tabular Numerals */}
          <div className="flex items-center justify-between border-t border-border pt-4">
            <span className="text-xs text-muted-foreground tabular-nums">
              Showing {skipParam + 1}–{skipParam + activities.length} activities
            </span>

            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={handlePrevPage}
                disabled={skipParam === 0}
                className="min-h-[44px] sm:min-h-[36px] text-xs touch-manipulation focus-visible:ring-2 focus-visible:ring-primary"
              >
                Previous
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={handleNextPage}
                disabled={activities.length < PAGE_SIZE}
                className="min-h-[44px] sm:min-h-[36px] text-xs touch-manipulation focus-visible:ring-2 focus-visible:ring-primary"
              >
                Next
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default ActivityListPage;
