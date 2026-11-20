import React from 'react';
import { Link } from 'react-router-dom';
import {
  addDays,
  addMonths,
  subMonths,
  startOfMonth,
  endOfMonth,
  startOfWeek,
  endOfWeek,
  eachDayOfInterval,
  format,
  isSameMonth,
  isToday,
  parseISO,
} from 'date-fns';
import {
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import { useActivities } from '@/hooks/useActivities';
import { ActivityCard } from '@/components/activity/ActivityCard';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { GarminAttribution } from '@/components/common/GarminAttribution';
import { Button } from '@/components/ui/button';
import {
  formatDistance,
  formatPace,
} from '@/utils/formatters';
import { cn } from '@/lib/utils';
import type { Activity } from '@/types/api';

const dayKeyOf = (day: Date) => format(day, 'yyyy-MM-dd');

const sumDistance = (acts: Activity[]) =>
  acts.reduce((sum, a) => sum + (a.processed_data.distance || 0), 0);

/**
 * Splits a day's runs into the ones that fit in the cell and an overflow count.
 */
const fitRuns = (acts: Activity[], maxSlots: number) =>
  acts.length <= maxSlots
    ? { shown: acts, hidden: 0 }
    : { shown: acts.slice(0, maxSlots - 1), hidden: acts.length - (maxSlots - 1) };

const MOBILE_SLOTS = 3;
const DESKTOP_SLOTS = 2;

export const CalendarPage: React.FC = () => {
  const [currentDate, setCurrentDate] = React.useState<Date>(new Date());
  const [selectedDayKey, setSelectedDayKey] = React.useState<string | null>(
    dayKeyOf(new Date())
  );

  const monthKey = format(currentDate, 'yyyy-MM');
  const { calendarStart, calendarEnd } = React.useMemo(() => {
    const monthStart = startOfMonth(currentDate);
    return {
      calendarStart: startOfWeek(monthStart, { weekStartsOn: 1 }),
      calendarEnd: endOfWeek(endOfMonth(monthStart), { weekStartsOn: 1 }),
    };
  }, [monthKey]);

  const queryAfter = format(calendarStart, 'yyyy-MM-dd');
  const queryBefore = format(addDays(calendarEnd, 1), 'yyyy-MM-dd');

  const { data: activities, isLoading } = useActivities({
    after: queryAfter,
    before: queryBefore,
    limit: 200,
    include_laps: false,
  });

  const activitiesByDate = React.useMemo(() => {
    const map = new Map<string, Activity[]>();
    if (!activities) return map;

    for (const act of activities) {
      if (!act.processed_data.startTimeLocal) continue;
      try {
        const key = dayKeyOf(parseISO(act.processed_data.startTimeLocal));
        const list = map.get(key) || [];
        list.push(act);
        map.set(key, list);
      } catch {
        // skip unparseable
      }
    }
    return map;
  }, [activities]);

  const monthDistance = React.useMemo(() => {
    if (!activities) return 0;
    return activities
      .filter((a) => {
        if (!a.processed_data.startTimeLocal) return false;
        try {
          return isSameMonth(parseISO(a.processed_data.startTimeLocal), currentDate);
        } catch {
          return false;
        }
      })
      .reduce((sum, a) => sum + (a.processed_data.distance || 0), 0);
  }, [activities, currentDate]);

  const days = React.useMemo(
    () => eachDayOfInterval({ start: calendarStart, end: calendarEnd }),
    [calendarStart, calendarEnd]
  );

  const weeks = React.useMemo(() => {
    const result: Date[][] = [];
    for (let i = 0; i < days.length; i += 7) {
      result.push(days.slice(i, i + 7));
    }
    return result;
  }, [days]);

  const prevMonth = () => setCurrentDate((d) => subMonths(d, 1));
  const nextMonth = () => setCurrentDate((d) => addMonths(d, 1));
  const jumpToToday = () => {
    const today = new Date();
    setCurrentDate(today);
    setSelectedDayKey(dayKeyOf(today));
  };

  const selectedDayActivities = selectedDayKey
    ? activitiesByDate.get(selectedDayKey) || []
    : [];

  return (
    <div className="space-y-5 sm:space-y-6 pb-16">
      {/* Calendar Header with Navigation */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <span className="text-[10px] sm:text-xs font-bold uppercase tracking-widest text-[#FC5200]">
            Training Log
          </span>
          <h1 className="text-xl sm:text-3xl font-extrabold tracking-tight text-foreground mt-0.5">
            Calendar
          </h1>
          <p className="text-xs sm:text-sm text-muted-foreground mt-0.5 font-medium">
            Monthly volume:{' '}
            <span className="font-mono font-bold text-foreground">
              {formatDistance(monthDistance)}
            </span>
          </p>
          <GarminAttribution activities={activities ?? []} className="mt-1" />
        </div>

        <div className="flex items-center gap-2 self-start sm:self-auto">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={jumpToToday}
            className="h-9 px-3 text-xs font-bold touch-manipulation focus-visible:ring-2 focus-visible:ring-primary rounded-lg"
          >
            Today
          </Button>

          <div className="flex items-center rounded-lg border border-border bg-card p-0.5 shadow-xs">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label="Previous month"
              onClick={prevMonth}
              className="h-8 w-8 rounded-md touch-manipulation focus-visible:ring-2 focus-visible:ring-primary"
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <span className="w-32 text-center text-xs sm:text-sm font-bold text-foreground select-none">
              {format(currentDate, 'MMMM yyyy')}
            </span>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label="Next month"
              onClick={nextMonth}
              className="h-8 w-8 rounded-md touch-manipulation focus-visible:ring-2 focus-visible:ring-primary"
            >
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </div>

      {isLoading ? (
        <div className="flex h-96 items-center justify-center rounded-xl border border-border bg-card">
          <LoadingSpinner size="lg" label="Loading calendar..." />
        </div>
      ) : (
        <>
          <div className="rounded-xl border border-border bg-card shadow-xs overflow-hidden">
            {/* Day of week headers (Mon - Sun) */}
            <div className="grid grid-cols-7 border-b border-border bg-muted/60 text-center text-[10px] sm:text-xs font-bold text-muted-foreground uppercase tracking-wider py-2.5">
              <span>Mon</span>
              <span>Tue</span>
              <span>Wed</span>
              <span>Thu</span>
              <span>Fri</span>
              <span>Sat</span>
              <span>Sun</span>
            </div>

            {/* Weeks and Days Grid */}
            <div className="divide-y divide-border">
              {weeks.map((week) => (
                <div key={dayKeyOf(week[0]!)} className="grid grid-cols-7 divide-x divide-border">
                  {week.map((day) => {
                    const dayKey = dayKeyOf(day);
                    const dayActs = activitiesByDate.get(dayKey) || [];
                    const isCurrentMonth = isSameMonth(day, currentDate);
                    const isCurrentDay = isToday(day);
                    const isSelected = selectedDayKey === dayKey;
                    const mobileRuns = fitRuns(dayActs, MOBILE_SLOTS);
                    const desktopRuns = fitRuns(dayActs, DESKTOP_SLOTS);

                    return (
                      <div
                        key={dayKey}
                        className={cn(
                          'relative min-h-[88px] sm:min-h-[120px] p-1.5 sm:p-2 transition-colors flex flex-col',
                          !isCurrentMonth ? 'bg-muted/30 opacity-60' : 'bg-card',
                          isCurrentDay && 'bg-[#FC5200]/5',
                          isSelected && 'ring-2 ring-inset ring-[#FC5200] sm:ring-0'
                        )}
                      >
                        {/* Mobile: tap selects day */}
                        <button
                          type="button"
                          onClick={() => setSelectedDayKey(dayKey)}
                          aria-pressed={isSelected}
                          aria-label={`${format(day, 'EEEE, MMMM d')}: ${
                            dayActs.length
                              ? `${dayActs.length} runs, ${formatDistance(sumDistance(dayActs))}`
                              : 'no runs'
                          }`}
                          className="absolute inset-0 sm:hidden touch-manipulation focus-visible:ring-2 focus-visible:ring-[#FC5200]"
                        />

                        {/* Day number */}
                        <div className="flex items-center justify-between">
                          <span
                            className={cn(
                              'flex h-6 w-6 items-center justify-center rounded-full text-xs tabular-nums font-bold',
                              isCurrentDay
                                ? 'bg-[#FC5200] text-white shadow-xs'
                                : isCurrentMonth
                                ? 'text-foreground'
                                : 'text-muted-foreground'
                            )}
                          >
                            {format(day, 'd')}
                          </span>
                          {dayActs.length > 0 && (
                            <span className="hidden sm:inline text-[10px] font-mono font-bold text-muted-foreground tabular-nums">
                              {formatDistance(sumDistance(dayActs))}
                            </span>
                          )}
                        </div>

                        {/* Mobile: compact indicator dots */}
                        {dayActs.length > 0 && (
                          <div className="mt-2 flex flex-col gap-1 sm:hidden" aria-hidden="true">
                            {mobileRuns.shown.map((act) => (
                              <div
                                key={act.activityId}
                                className="h-1.5 w-full rounded-full bg-muted-foreground/60"
                              />
                            ))}
                            {mobileRuns.hidden > 0 && (
                              <span className="text-center text-[10px] font-bold text-muted-foreground">
                                +{mobileRuns.hidden}
                              </span>
                            )}
                          </div>
                        )}

                        {/* Desktop: clean workout pills */}
                        <div className="mt-1.5 space-y-1 flex-1 hidden sm:block">
                          {desktopRuns.shown.map((act) => (
                            <Link
                              key={act.activityId}
                              to={`/activities/${act.activityId}`}
                              title={`${act.processed_data.name || 'Run'} - ${formatDistance(act.processed_data.distance)}`}
                              className="group block rounded-md p-1.5 border border-border bg-muted/50 hover:bg-muted text-left transition-all hover:border-neutral-400 dark:hover:border-neutral-600"
                            >
                              <div className="flex items-center justify-between text-xs font-semibold leading-tight">
                                <span className="truncate text-foreground group-hover:text-[#FC5200] transition-colors">
                                  {act.processed_data.name || 'Run'}
                                </span>
                              </div>
                              <div className="mt-0.5 flex items-center justify-between text-[11px] font-mono tabular-nums text-muted-foreground">
                                <span>{formatDistance(act.processed_data.distance)}</span>
                                <span className="font-semibold text-foreground">
                                  {formatPace(act.processed_data.speed)}
                                </span>
                              </div>
                            </Link>
                          ))}

                          {desktopRuns.hidden > 0 && (
                            <div className="text-[11px] font-bold text-muted-foreground text-center py-0.5">
                              +{desktopRuns.hidden} more
                            </div>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              ))}
            </div>
          </div>

          {/* Mobile bottom selected day details */}
          <div className="sm:hidden space-y-3 pt-2">
            <h2 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
              {selectedDayKey
                ? format(parseISO(selectedDayKey), 'EEEE, MMMM d, yyyy')
                : 'Select a day'}
            </h2>

            {selectedDayActivities.length > 0 ? (
              <div className="space-y-2.5">
                {selectedDayActivities.map((act) => (
                  <ActivityCard key={act.activityId} activity={act} />
                ))}
              </div>
            ) : (
              <p className="text-xs text-muted-foreground font-medium p-4 border border-dashed border-border rounded-lg text-center">
                No runs recorded on this date.
              </p>
            )}
          </div>
        </>
      )}
    </div>
  );
};

export default CalendarPage;
