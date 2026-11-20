import React from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { ArrowLeft, Pencil, SearchX, Search as SearchIcon } from 'lucide-react';
import { useActivitySearch } from '@/hooks/useActivitySearch';
import { useMediaQuery } from '@/hooks/useMediaQuery';
import { ActivityCard } from '@/components/activity/ActivityCard';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { SearchFilterForm } from '@/components/search/SearchFilterForm';
import { Button } from '@/components/ui/button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  SORT_OPTIONS,
  buildSearchFilters,
  decodeSearch,
  defaultSearchValues,
  describeSearch,
  encodeSearch,
  type SearchFormValues,
} from '@/schemas/search';
import type { ActivitySearchRequest } from '@/types/api';
import { getApiErrorMessage } from '@/utils/errors';
import { cn } from '@/lib/utils';

const PAGE_SIZE = 20;

export const ActivitySearchPage: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const isWide = useMediaQuery('(min-width: 1024px)');
  const resultsRef = React.useRef<HTMLElement>(null);

  // The submitted search lives in the URL, so going back from an activity restores it.
  const rawQuery = searchParams.get('q');
  const submitted = React.useMemo(() => decodeSearch(rawQuery), [rawQuery]);
  const sortOption =
    SORT_OPTIONS.find((option) => option.value === searchParams.get('sort')) ?? SORT_OPTIONS[0]!;
  const offset = Math.max(0, parseInt(searchParams.get('offset') || '0', 10) || 0);

  const request = React.useMemo<ActivitySearchRequest | null>(() => {
    if (!submitted) return null;
    const { filters, issues } = buildSearchFilters(submitted);
    if (issues.length > 0) return null;
    return { ...filters, sort: sortOption.sort, limit: PAGE_SIZE, offset };
  }, [submitted, sortOption, offset]);

  const { data, isLoading, isFetching, isError, error, refetch } = useActivitySearch(request);

  // Narrow screens show either the form or the results; wide ones show both.
  const [editing, setEditing] = React.useState(submitted === null);

  const updateParams = (update: (next: URLSearchParams) => void) => {
    const next = new URLSearchParams(searchParams);
    update(next);
    setSearchParams(next);
  };

  const handleSearch = (values: SearchFormValues) => {
    updateParams((next) => {
      next.set('q', encodeSearch(values));
      next.delete('offset');
    });
    setEditing(false);
    if (!isWide) resultsRef.current?.scrollIntoView({ block: 'start' });
  };

  const handleReset = () => {
    setSearchParams(new URLSearchParams());
    setEditing(true);
  };

  const handleSortChange = (value: string) =>
    updateParams((next) => {
      next.set('sort', value);
      next.delete('offset');
    });

  const goToOffset = (nextOffset: number) =>
    updateParams((next) => {
      if (nextOffset > 0) next.set('offset', String(nextOffset));
      else next.delete('offset');
    });

  const total = data?.total ?? 0;
  const items = data?.items ?? [];
  const showResults = submitted !== null;

  return (
    <div className="space-y-5 sm:space-y-6 pb-16">
      {/* Page Header */}
      <div className="flex items-center gap-2">
        <Button
          variant="ghost"
          size="icon"
          asChild
          className="md:hidden h-11 w-11 -ml-2 touch-manipulation"
        >
          <Link to="/activities" aria-label="Back to activities">
            <ArrowLeft className="size-5!" />
          </Link>
        </Button>
        <div>
          <h1 className="text-xl sm:text-3xl font-bold tracking-tight text-foreground">
            Search activities
          </h1>
          <p className="hidden sm:block text-sm text-muted-foreground mt-0.5">
            Find runs by type, date, distance, pace, and what happened inside them
          </p>
        </div>
      </div>

      <div className="lg:grid lg:grid-cols-[360px_minmax(0,1fr)] lg:items-start lg:gap-6 space-y-5 lg:space-y-0">
        {/* Filters */}
        <div
          className={cn(
            editing ? 'block' : 'hidden',
            'lg:block lg:sticky lg:top-0 lg:max-h-[calc(100vh-8rem)] lg:overflow-y-auto lg:rounded-2xl'
          )}
        >
          <SearchFilterForm
            key={rawQuery ?? ''}
            defaultValues={submitted ?? defaultSearchValues()}
            onSearch={handleSearch}
            onReset={handleReset}
            isSearching={isFetching}
          />
        </div>

        {/* Collapsed filters (narrow screens, after a search) */}
        {submitted && !editing && (
          <div className="lg:hidden flex items-start justify-between gap-3 rounded-2xl border border-border bg-card p-3.5 shadow-xs">
            <ul className="flex flex-wrap gap-1.5 min-w-0" aria-label="Active filters">
              {describeSearch(submitted).map((label) => (
                <li
                  key={label}
                  className="rounded-full border border-border bg-muted/50 px-2.5 py-1 text-xs font-medium text-foreground"
                >
                  {label}
                </li>
              ))}
            </ul>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setEditing(true)}
              className="shrink-0 min-h-[44px] touch-manipulation"
            >
              <Pencil />
              Edit
            </Button>
          </div>
        )}

        {/* Results */}
        <section
          ref={resultsRef}
          aria-label="Search results"
          className={cn(
            showResults && !editing ? 'block' : 'hidden',
            'lg:block scroll-mt-20 space-y-3'
          )}
        >
          {!showResults ? (
            <div className="rounded-2xl border border-dashed border-border p-8 sm:p-12 text-center bg-card/40">
              <SearchIcon className="h-10 w-10 text-muted-foreground mx-auto mb-3 opacity-60" />
              <h2 className="font-semibold text-foreground text-sm sm:text-base">
                Search your runs
              </h2>
              <p className="text-xs text-muted-foreground max-w-sm mx-auto mt-1">
                Pick a training type to unlock its specific filters, like rep distance for
                intervals, then run the search.
              </p>
            </div>
          ) : isLoading ? (
            <div className="flex h-64 items-center justify-center rounded-2xl border border-border bg-card">
              <LoadingSpinner size="md" label="Searching activities..." />
            </div>
          ) : isError ? (
            <div
              role="alert"
              className="rounded-2xl border border-destructive/40 bg-card p-6 text-center space-y-3"
            >
              <p className="text-sm font-semibold text-foreground">Search failed</p>
              <p className="text-xs text-muted-foreground">
                {getApiErrorMessage(error, "Couldn't load the results. Try again.")}
              </p>
              <Button
                type="button"
                variant="outline"
                onClick={() => refetch()}
                className="min-h-[44px] sm:min-h-[36px] touch-manipulation"
              >
                Try again
              </Button>
            </div>
          ) : (
            <>
              {/* Count + sort */}
              <div className="flex items-center justify-between gap-3">
                <p className="text-xs sm:text-sm text-muted-foreground tabular-nums" aria-live="polite">
                  {total === 1 ? '1 activity' : `${total} activities`}
                </p>
                <Select value={sortOption.value} onValueChange={handleSortChange}>
                  <SelectTrigger
                    aria-label="Sort results"
                    className="w-auto min-w-[150px] min-h-[44px] sm:min-h-[36px] gap-2"
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent align="end">
                    {SORT_OPTIONS.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {items.length === 0 ? (
                <div className="rounded-2xl border border-dashed border-border p-8 sm:p-12 text-center bg-card/40">
                  <SearchX className="h-10 w-10 text-muted-foreground mx-auto mb-3 opacity-60" />
                  <h2 className="font-semibold text-foreground text-sm sm:text-base">
                    No activities match these filters
                  </h2>
                  <p className="text-xs text-muted-foreground max-w-sm mx-auto mt-1 mb-4">
                    Widen a range, raise the rep distance tolerance, or try another training
                    type.
                  </p>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => setEditing(true)}
                    className="lg:hidden min-h-[44px] touch-manipulation"
                  >
                    Edit filters
                  </Button>
                </div>
              ) : (
                <div
                  className={cn(
                    'space-y-2.5 sm:space-y-3 transition-opacity',
                    isFetching && 'opacity-60'
                  )}
                  aria-busy={isFetching}
                >
                  {items.map((activity) => (
                    <ActivityCard key={activity.activityId} activity={activity} />
                  ))}

                  {/* Pagination */}
                  <div className="flex items-center justify-between border-t border-border pt-4">
                    <span className="text-xs text-muted-foreground tabular-nums">
                      {offset + 1}–{offset + items.length} of {total}
                    </span>
                    <div className="flex items-center gap-2">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => goToOffset(Math.max(0, offset - PAGE_SIZE))}
                        disabled={offset === 0}
                        className="min-h-[44px] sm:min-h-[36px] text-xs touch-manipulation"
                      >
                        Previous
                      </Button>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => goToOffset(offset + PAGE_SIZE)}
                        disabled={offset + items.length >= total}
                        className="min-h-[44px] sm:min-h-[36px] text-xs touch-manipulation"
                      >
                        Next
                      </Button>
                    </div>
                  </div>
                </div>
              )}
            </>
          )}
        </section>
      </div>
    </div>
  );
};

export default ActivitySearchPage;
