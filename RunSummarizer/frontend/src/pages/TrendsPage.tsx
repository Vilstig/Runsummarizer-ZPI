import React from 'react';
import {
  subMonths,
  format,
  parseISO,
} from 'date-fns';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from 'recharts';
import {
  Activity as ActivityIcon,
  TrendingUp,
} from 'lucide-react';
import { useActivities } from '@/hooks/useActivities';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { GarminAttribution } from '@/components/common/GarminAttribution';
import { MetricTile } from '@/components/common/MetricTile';
import { Button } from '@/components/ui/button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { RunType, RUN_TYPE_DISPLAY } from '@/types/enums';
import {
  formatDistance,
  formatPace,
  formatPaceSeconds,
  speedToPaceSeconds,
} from '@/utils/formatters';
import { useChartColors } from '@/hooks/useChartColors';

export const TrendsPage: React.FC = () => {
  const { isDark, primary, cardFill, axisStroke, tickFill, gridStroke, tooltipBg, tooltipBorder } =
    useChartColors();

  const [monthsBack, setMonthsBack] = React.useState<number>(3);
  const [selectedRunType, setSelectedRunType] = React.useState<number>(
    RunType.EASY
  );

  const startDate = React.useMemo(() => {
    return format(subMonths(new Date(), monthsBack), 'yyyy-MM-dd');
  }, [monthsBack]);

  const { data: activities, isLoading } = useActivities({
    after: startDate,
    limit: 200,
    include_laps: false,
  });

  // The selected type's activities, the source of every number on the page
  const filtered = React.useMemo(() => {
    if (!activities) return [];

    const ofType = activities.filter((act) => {
      if (selectedRunType === -1) return true; // all types
      return act.processed_data.trainingTypeId === selectedRunType;
    });

    // Sort chronologically (oldest to newest for line chart)
    return ofType.sort((a, b) => {
      const dateA = a.processed_data.startTimeLocal
        ? new Date(a.processed_data.startTimeLocal).getTime()
        : 0;
      const dateB = b.processed_data.startTimeLocal
        ? new Date(b.processed_data.startTimeLocal).getTime()
        : 0;
      return dateA - dateB;
    });
  }, [activities, selectedRunType]);

  const trendData = React.useMemo(() => {
    return filtered.map((act) => {
      const paceSecs = speedToPaceSeconds(act.processed_data.speed);
      const dateStr = act.processed_data.startTimeLocal
        ? format(parseISO(act.processed_data.startTimeLocal), 'MMM dd')
        : 'Unknown';

      return {
        id: act.activityId,
        name: act.processed_data.name || 'Run',
        date: dateStr,
        paceSecs,
        speed: act.processed_data.speed,
        distance: act.processed_data.distance,
        avgHr: act.processed_data.avgHr ? Math.round(act.processed_data.avgHr) : null,
      };
    });
  }, [filtered]);

  // Aggregate statistics for the filtered dataset
  const stats = React.useMemo(() => {
    if (!trendData.length) return { avgSpeed: 0, totalKm: 0, count: 0 };

    const validPaces = trendData.filter((d) => d.speed && d.speed > 0);
    const totalDist = trendData.reduce((acc, curr) => acc + (curr.distance || 0), 0);
    const avgSpeed = validPaces.length
      ? validPaces.reduce((acc, curr) => acc + (curr.speed || 0), 0) / validPaces.length
      : 0;

    return {
      avgSpeed,
      totalKm: totalDist,
      count: trendData.length,
    };
  }, [trendData]);

  // Dynamic bounds for pace
  const paceValues = trendData
    .map((d) => d.paceSecs)
    .filter((p): p is number => p !== null && p > 150 && p < 900);

  const minPace = paceValues.length ? Math.max(120, Math.min(...paceValues) - 15) : 240;
  const maxPace = paceValues.length ? Math.min(900, Math.max(...paceValues) + 15) : 480;

  return (
    <div className="space-y-6 sm:space-y-8 pb-16">
      {/* Page Header */}
      <div>
        <span className="text-[10px] sm:text-xs font-bold uppercase tracking-widest text-[#FC5200]">
          Longitudinal Analytics
        </span>
        <h1 className="text-xl sm:text-3xl font-extrabold tracking-tight text-foreground mt-0.5">
          Pace Trends
        </h1>
        <p className="hidden sm:block text-sm text-muted-foreground mt-1 font-medium">
          Historical velocity and cardiovascular decoupling progression by workout category.
        </p>
        <GarminAttribution activities={filtered} className="mt-1" />
      </div>

      {/* Filter and Range Controls */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <label className="text-xs font-bold uppercase tracking-wider text-muted-foreground whitespace-nowrap">
            Category:
          </label>
          <Select
            value={String(selectedRunType)}
            onValueChange={(val) => setSelectedRunType(Number(val))}
          >
            <SelectTrigger
              aria-label="Filter trends by workout category"
              className="w-full sm:w-[220px] min-h-[44px] sm:min-h-[36px] text-xs font-bold focus-visible:ring-2 focus-visible:ring-primary rounded-lg"
            >
              <SelectValue placeholder="Category" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="-1">All Workout Types</SelectItem>
              {Object.entries(RUN_TYPE_DISPLAY).map(([id, label]) => (
                <SelectItem key={id} value={id}>
                  {label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="flex items-center gap-1 rounded-lg border border-border bg-card p-1 self-start sm:self-auto shadow-xs">
          {[
            { count: 1, label: '1M' },
            { count: 3, label: '3M' },
            { count: 6, label: '6M' },
          ].map((item) => (
            <Button
              key={item.count}
              type="button"
              variant={monthsBack === item.count ? 'default' : 'ghost'}
              size="sm"
              onClick={() => setMonthsBack(item.count)}
              className="min-h-[36px] px-3 text-xs font-bold touch-manipulation focus-visible:ring-2 focus-visible:ring-primary"
            >
              {item.label}
            </Button>
          ))}
        </div>
      </div>

      {/* Aggregate Metrics in Period */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2.5 sm:gap-4">
        <MetricTile
          label="Total Distance"
          value={formatDistance(stats.totalKm)}
          subtext={`Selected ${monthsBack} mo window`}
        />
        <MetricTile
          label="Mean Pace"
          value={formatPace(stats.avgSpeed)}
          subtext="Category average"
        />
        <MetricTile
          label="Sessions"
          value={stats.count}
          subtext="Workouts recorded"
          className="col-span-2 sm:col-span-1"
        />
      </div>

      {/* Main Pace Trend Chart */}
      <div
        role="region"
        aria-label="Pace Over Time Chart"
        className="rounded-xl border border-border bg-card p-4 sm:p-6 shadow-xs space-y-4"
      >
        <div className="flex items-center justify-between pb-3 border-b border-border">
          <div>
            <span className="text-[10px] font-bold uppercase tracking-wider text-[#FC5200]">
              Telemetry Progression
            </span>
            <h3 className="text-base sm:text-lg font-extrabold text-foreground flex items-center gap-2 mt-0.5">
              <TrendingUp className="h-4 w-4 text-[#FC5200]" />
              Pace Over Time
            </h3>
            <p className="text-xs text-muted-foreground mt-0.5 font-medium">
              Higher line placement = faster velocity (inverted scale)
            </p>
          </div>
        </div>

        {isLoading ? (
          <div className="flex h-72 items-center justify-center">
            <LoadingSpinner size="md" label="Loading trends..." />
          </div>
        ) : trendData.length === 0 ? (
          <div className="flex h-72 flex-col items-center justify-center text-center text-xs text-muted-foreground p-6">
            <ActivityIcon className="h-8 w-8 text-muted-foreground/40 mb-2" />
            <p className="font-bold text-sm text-foreground">
              No workouts matching this category
            </p>
            <p className="mt-1 max-w-sm font-medium">
              Try switching the category dropdown or expanding the date range to inspect trend metrics.
            </p>
          </div>
        ) : (
          <div className="h-72 w-full pt-2">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart
                data={trendData}
                margin={{ top: 10, right: 10, left: -6, bottom: 0 }}
              >
                <CartesianGrid strokeDasharray="3 3" opacity={isDark ? 0.15 : 0.6} stroke={gridStroke} />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 11, fill: tickFill, fontWeight: 500 }}
                  stroke={axisStroke}
                />
                <YAxis
                  domain={[minPace, maxPace]}
                  reversed={true} // Faster pace is higher
                  tickFormatter={(sec) => formatPaceSeconds(sec, false)}
                  tick={{ fontSize: 11, fill: tickFill, fontWeight: 500 }}
                  stroke={axisStroke}
                  width={46}
                />
                <Tooltip
                  content={({ active, payload }) => {
                    if (!active || !payload || !payload.length || !payload[0]?.payload) return null;
                    const d = payload[0].payload;
                    return (
                      <div
                        style={{ backgroundColor: tooltipBg, borderColor: tooltipBorder }}
                        className="rounded-lg border p-3 text-xs shadow-lg space-y-1"
                      >
                        <div className="font-bold text-foreground">{d.name}</div>
                        <div className="text-muted-foreground font-medium">{d.date}</div>
                        <div className="text-[#FC5200] font-bold tabular-nums">
                          Pace: {formatPace(d.speed)}
                        </div>
                        {d.avgHr && (
                          <div className="text-foreground font-semibold tabular-nums">
                            Heart Rate: {d.avgHr} bpm
                          </div>
                        )}
                        <div className="text-muted-foreground tabular-nums font-medium">
                          Distance: {formatDistance(d.distance)}
                        </div>
                      </div>
                    );
                  }}
                />
                <Line
                  type="monotone"
                  dataKey="paceSecs"
                  stroke={primary}
                  strokeWidth={2.5}
                  dot={{ r: 3.5, fill: primary }}
                  activeDot={{ r: 5.5, fill: cardFill, stroke: primary, strokeWidth: 2.5 }}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
    </div>
  );
};

export default TrendsPage;
