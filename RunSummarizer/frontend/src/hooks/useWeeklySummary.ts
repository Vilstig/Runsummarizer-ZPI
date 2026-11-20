import React from 'react';
import { addWeeks, format, parseISO, startOfWeek } from 'date-fns';
import { useQuery } from '@tanstack/react-query';
import { getWeeklySummary } from '@/api/activities';
import { activitiesKeys } from '@/api/keys';

export interface WeekTotals {
  weekStart: Date;
  distance: number;
  duration: number;
  elevationGain: number;
}

/**
 * Running totals for the last `weekCount` Monday-based weeks, oldest first,
 * ending with the week containing `date` (included even when it has no runs).
 * Aggregated server-side, by the database.
 */
export const useWeeklySummary = (date: Date, weekCount: number) => {
  const currentWeekStart = React.useMemo(
    () => startOfWeek(date, { weekStartsOn: 1 }),
    [date]
  );

  // Zero-filled weeks shown until the request resolves, so the chart and stats have
  // something to render immediately.
  const defaultWeeks = React.useMemo<WeekTotals[]>(
    () =>
      Array.from({ length: weekCount }, (_, i) => ({
        weekStart: addWeeks(currentWeekStart, i - (weekCount - 1)),
        distance: 0,
        duration: 0,
        elevationGain: 0,
      })),
    [currentWeekStart, weekCount]
  );

  const params = React.useMemo(
    () => ({ weeks: weekCount, date: format(date, 'yyyy-MM-dd') }),
    [date, weekCount]
  );

  const query = useQuery({
    queryKey: activitiesKeys.weeklySummary(params),
    queryFn: () => getWeeklySummary(params),
    staleTime: 5 * 60 * 1000,
    gcTime: 15 * 60 * 1000,
    select: (response): WeekTotals[] =>
      response.weeks.map((week) => ({
        weekStart: parseISO(week.weekStart),
        distance: week.distance,
        duration: week.duration,
        elevationGain: week.elevationGain,
      })),
  });

  return { ...query, weeks: query.data ?? defaultWeeks };
};
