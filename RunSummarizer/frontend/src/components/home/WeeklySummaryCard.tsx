import React from 'react';
import { addDays, format, isSameMonth } from 'date-fns';
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { Calendar } from 'lucide-react';
import type { WeekTotals } from '@/hooks/useWeeklySummary';
import { useChartColors } from '@/hooks/useChartColors';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { formatDistance } from '@/utils/formatters';

export interface WeeklySummaryCardProps {
  /** Oldest first; the last entry is the current week. */
  weeks: WeekTotals[];
  isLoading?: boolean;
}

/** e.g. 'Oct 26 – Nov 1' or 'Oct 5–11' */
const formatWeekRange = (weekStart: Date): string => {
  const weekEnd = addDays(weekStart, 6);
  return isSameMonth(weekStart, weekEnd)
    ? `${format(weekStart, 'MMM d')}–${format(weekEnd, 'd')}`
    : `${format(weekStart, 'MMM d')} – ${format(weekEnd, 'MMM d')}`;
};

/** e.g. '6h 15m' or '45m' */
const formatHoursMinutes = (seconds: number): string => {
  const hrs = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  return hrs > 0 ? `${hrs}h ${mins}m` : `${mins}m`;
};

/** Rounded y-axis step so the top tick (2 × step) sits just above the busiest week. */
const niceStep = (maxKm: number): number => {
  const half = maxKm / 2;
  const steps = [5, 10, 20, 25, 40, 50, 75, 100, 150, 200];
  return steps.find((s) => s >= half) ?? Math.ceil(half / 100) * 100;
};

/**
 * WeeklySummaryCard: Strava-style athletic weekly cockpit.
 * Heroic metric triad (Distance, Time, Elevation) with tabular numerals and smooth Recharts volume curve.
 */
export const WeeklySummaryCard: React.FC<WeeklySummaryCardProps> = ({
  weeks,
  isLoading = false,
}) => {
  const { primary, tickFill, gridStroke, cardFill, foreground } = useChartColors();

  const lastIndex = weeks.length - 1;
  const [selectedIndex, setSelectedIndex] = React.useState(lastIndex);

  React.useEffect(() => setSelectedIndex(lastIndex), [lastIndex]);

  const chartData = React.useMemo(
    () =>
      weeks.map((w) => ({
        key: format(w.weekStart, 'yyyy-MM-dd'),
        km: Math.round((w.distance / 1000) * 10) / 10,
      })),
    [weeks]
  );

  const monthTicks = weeks
    .filter((w, i) => i > 0 && w.weekStart.getMonth() !== weeks[i - 1]?.weekStart.getMonth())
    .map((w) => format(w.weekStart, 'yyyy-MM-dd'));

  const step = niceStep(Math.max(...chartData.map((d) => d.km), 10));
  const selected = weeks[selectedIndex] ?? weeks[lastIndex];
  if (!selected) return null;

  return (
    <section className="rounded-xl border border-border bg-card p-4 sm:p-6 shadow-xs transition-all">
      {/* Header with athletic category label */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <span className="text-[10px] sm:text-xs font-bold uppercase tracking-widest text-muted-foreground block">
            Endurance Volume
          </span>
          <h2 className="text-xl sm:text-2xl font-extrabold tracking-tight text-foreground mt-0.5">
            {selectedIndex === lastIndex ? 'This week' : formatWeekRange(selected.weekStart)}
          </h2>
        </div>
        <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-muted text-[11px] font-semibold text-muted-foreground">
          <Calendar className="h-3.5 w-3.5 text-muted-foreground" />
          <span>Last {weeks.length} weeks</span>
        </div>
      </div>

      {/* Hero Metric Triad (Garmin & Strava Cockpit Grid) */}
      <dl className="mt-4 grid grid-cols-3 gap-2 sm:gap-4 divide-x divide-border border-y border-border py-4">
        {[
          { label: 'Distance', value: formatDistance(selected.distance), highlight: true },
          { label: 'Time', value: formatHoursMinutes(selected.duration), highlight: false },
          { label: 'Elevation', value: `${Math.round(selected.elevationGain)} m`, highlight: false },
        ].map((stat, idx) => (
          <div key={stat.label} className={idx === 0 ? 'min-w-0 pr-2' : 'min-w-0 px-2 sm:px-4'}>
            <dt className="text-[10px] sm:text-xs font-semibold uppercase tracking-wider text-muted-foreground truncate">
              {stat.label}
            </dt>
            <dd className="mt-1 text-xl sm:text-3xl lg:text-4xl font-extrabold tabular-nums tracking-tight text-foreground truncate">
              {isLoading ? '–' : stat.value}
            </dd>
          </div>
        ))}
      </dl>

      {/* Area Chart with Strava Orange Curve */}
      {isLoading ? (
        <div className="flex h-44 sm:h-52 items-center justify-center">
          <LoadingSpinner size="sm" label="Loading weekly distance..." />
        </div>
      ) : (
        <div
          className="mt-4 h-44 sm:h-52 w-full touch-manipulation select-none"
          role="img"
          aria-label={`Weekly running distance for the last ${weeks.length} weeks.`}
        >
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart
              data={chartData}
              margin={{ top: 14, right: 0, left: 0, bottom: 0 }}
              onClick={(state) => {
                if (typeof state?.activeTooltipIndex === 'number') {
                  setSelectedIndex(state.activeTooltipIndex);
                }
              }}
            >
              <defs>
                <linearGradient id="weeklyDistanceFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={primary} stopOpacity={0.35} />
                  <stop offset="100%" stopColor={primary} stopOpacity={0.00} />
                </linearGradient>
              </defs>

              <CartesianGrid vertical={false} stroke={gridStroke} strokeDasharray="3 3" />

              <XAxis
                dataKey="key"
                ticks={monthTicks}
                interval={0}
                tickFormatter={(key: string) => format(new Date(`${key}T00:00:00`), 'MMM').toUpperCase()}
                tick={{ fontSize: 11, fill: tickFill, fontWeight: 500 }}
                tickLine={false}
                axisLine={false}
                padding={{ left: 10, right: 10 }}
              />

              <YAxis
                orientation="right"
                domain={[0, step * 2]}
                ticks={[0, step, step * 2]}
                tickFormatter={(km: number) => `${km} km`}
                tick={{ fontSize: 11, fill: tickFill, fontWeight: 500 }}
                tickLine={false}
                axisLine={false}
                width={56}
              />

              <Tooltip content={() => null} cursor={false} />

              <ReferenceLine
                x={chartData[selectedIndex]?.key}
                stroke={foreground}
                strokeWidth={1.5}
                strokeDasharray="2 2"
              />

              <Area
                type="monotone"
                dataKey="km"
                stroke={primary}
                strokeWidth={3}
                fill="url(#weeklyDistanceFill)"
                isAnimationActive={true}
                animationDuration={600}
                activeDot={false}
                dot={({ cx, cy, index }: { cx: number; cy: number; index: number }) =>
                  index === selectedIndex ? (
                    <circle key={index} cx={cx} cy={cy} r={6} fill={primary} stroke="#ffffff" strokeWidth={2.5} />
                  ) : (
                    <circle key={index} cx={cx} cy={cy} r={3.5} fill={cardFill} stroke={primary} strokeWidth={2} />
                  )
                }
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  );
};
